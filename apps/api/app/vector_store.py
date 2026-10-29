from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

import jieba
import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import settings
from .db import engine
from .models import Chunk, ChunkEmbedding, Source


class EmbeddingError(Exception):
    pass


def _hash_texts(texts: list[str], dim: int) -> np.ndarray:
    """Offline lexical vector fallback: signed hashing over words and CJK bigrams."""
    vectors = np.zeros((len(texts), dim), dtype=np.float32)
    for row, text in enumerate(texts):
        tokens = [
            token.lower()
            for token in jieba.lcut(text)
            if len(token.strip()) >= 2
        ]
        cjk = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text)
        grams = [cjk[i : i + 2] for i in range(max(0, len(cjk) - 1))]
        weights: dict[str, float] = {}
        for token in tokens:
            weights[token] = weights.get(token, 0.0) + 1.0
        for gram in grams:
            weights[gram] = weights.get(gram, 0.0) + 0.35
        for token, weight in weights.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vectors[row, index] += sign * weight
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


@dataclass
class EmbeddingService:
    _model: Any = None
    _backend: str = ""
    _load_error: str = ""
    _vec_available: bool | None = None
    _vec_warning: str = ""

    def _discover_local_model(self) -> str:
        if settings.embedding_model_path:
            return settings.embedding_model_path
        root = settings.data_dir / "models"
        if not root.exists():
            return ""
        for pattern in ("**/model_optimized.onnx", "**/model.onnx"):
            for model_file in root.glob(pattern):
                return str(model_file.parent)
        return ""

    def _load_fastembed(self, local_only: bool):
        from fastembed import TextEmbedding

        local_path = self._discover_local_model()
        kwargs = {
            "model_name": settings.embedding_model,
            "cache_dir": str(settings.data_dir / "models"),
            "threads": 2,
            "local_files_only": local_only,
        }
        if local_path:
            kwargs["specific_model_path"] = local_path
        return TextEmbedding(**kwargs)

    def model(self):
        if self._model is not None or self._backend == "hash-ngram":
            return self._model
        if settings.embedding_backend == "hash":
            self._backend = "hash-ngram"
            return None
        try:
            self._model = self._load_fastembed(local_only=settings.embedding_backend == "auto")
            self._backend = "fastembed"
        except Exception as exc:  # pragma: no cover - model cache/network boundary
            self._load_error = str(exc)
            if settings.embedding_backend == "fastembed":
                raise EmbeddingError(f"无法加载嵌入模型 {settings.embedding_model}：{exc}") from exc
            self._backend = "hash-ngram"
            self._model = None
        return self._model

    def model_tag(self) -> str:
        self.model()
        if self._backend == "fastembed":
            return f"fastembed:{settings.embedding_model}"
        return f"hash-ngram:{settings.embedding_dim}"

    @property
    def backend(self) -> str:
        self.model()
        return self._backend or "hash-ngram"

    @property
    def load_error(self) -> str:
        return self._load_error

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, settings.embedding_dim), dtype=np.float32)
        model = self.model()
        if model is None:
            vectors = _hash_texts(texts, settings.embedding_dim)
        else:
            try:
                vectors = np.asarray(list(model.embed(texts)), dtype=np.float32)
            except Exception as exc:  # pragma: no cover - model runtime boundary
                raise EmbeddingError(f"嵌入失败：{exc}") from exc
        if vectors.ndim != 2 or vectors.shape[1] != settings.embedding_dim:
            raise EmbeddingError(
                f"嵌入维度不匹配：期望 {settings.embedding_dim}，实际 {vectors.shape[-1]}；"
                "请同步修改 DISTILL_EMBEDDING_DIM"
            )
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    def vec_available(self) -> bool:
        if self._vec_available is None:
            if not settings.is_sqlite:
                self._vec_available = False
                self._vec_warning = ""
                return self._vec_available
            try:
                with engine.connect() as connection:
                    connection.exec_driver_sql("SELECT vec_version()")
                    row = connection.exec_driver_sql(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='chunk_vectors'"
                    ).first()
                    self._vec_available = bool(row)
            except Exception as exc:
                self._vec_available = False
                self._vec_warning = str(exc)
        return bool(self._vec_available)

    @property
    def vec_warning(self) -> str:
        return self._vec_warning


embedding_service = EmbeddingService()


def ensure_vector_schema() -> bool:
    """Create the sqlite-vec virtual table when the extension is present.

    On PostgreSQL (or a SQLite build without sqlite-vec) this is a no-op and the
    application falls back to exact cosine search over ``chunk_embeddings``,
    which keeps every backend portable at the cost of a full scan.
    """
    if not settings.is_sqlite:
        return False
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0("
                "chunk_id TEXT PRIMARY KEY, "
                "project_id TEXT, "
                f"embedding FLOAT[{settings.embedding_dim}]"
                ")"
            )
        return True
    except Exception:
        return False


def _serialize(vector: np.ndarray) -> bytes:
    """Portable float32 blob.

    Deliberately avoids ``sqlite_vec.serialize_float32`` so the stored bytes are
    identical on every backend and can be copied to Postgres as ``bytea``.
    """
    return np.asarray(vector, dtype=np.float32).tobytes()


def index_chunks(
    db: Session, project_id: str, limit: int = 240, force: bool = False
) -> dict[str, Any]:
    if force:
        db.query(ChunkEmbedding).filter(ChunkEmbedding.project_id == project_id).delete(
            synchronize_session=False
        )
        if embedding_service.vec_available():
            try:
                db.execute(
                    text("DELETE FROM chunk_vectors WHERE project_id = :project_id"),
                    {"project_id": project_id},
                )
            except Exception:
                pass
        db.commit()
    embedded_ids = select(ChunkEmbedding.chunk_id)
    chunks = db.scalars(
        select(Chunk)
        .where(
            Chunk.project_id == project_id,
            Chunk.excluded.is_(False),
            ~Chunk.id.in_(embedded_ids),
        )
        .order_by(Chunk.source_id, Chunk.order_index)
        .limit(limit)
    ).all()
    if not chunks:
        return {
            "indexed": 0,
            "remaining": 0,
            "model": embedding_service.model_tag(),
            "backend": embedding_service.backend,
            "vec": embedding_service.vec_available(),
            "warning": embedding_service.vec_warning or embedding_service.load_error,
        }
    warning = ""
    indexed = 0
    vec_ok = embedding_service.vec_available()
    for start in range(0, len(chunks), settings.embedding_batch_size):
        batch = chunks[start : start + settings.embedding_batch_size]
        vectors = embedding_service.embed([chunk.text for chunk in batch])
        for chunk, vector in zip(batch, vectors):
            serialized = _serialize(vector)
            db.add(
                ChunkEmbedding(
                    chunk_id=chunk.id,
                    project_id=project_id,
                    model=embedding_service.model_tag(),
                    dim=settings.embedding_dim,
                    vector=serialized,
                )
            )
            if vec_ok:
                try:
                    db.execute(
                        text("DELETE FROM chunk_vectors WHERE chunk_id = :chunk_id"),
                        {"chunk_id": chunk.id},
                    )
                    db.execute(
                        text(
                            "INSERT INTO chunk_vectors (chunk_id, project_id, embedding) "
                            "VALUES (:chunk_id, :project_id, :embedding)"
                        ),
                        {
                            "chunk_id": chunk.id,
                            "project_id": project_id,
                            "embedding": serialized,
                        },
                    )
                except Exception as exc:
                    vec_ok = False
                    warning = f"sqlite-vec 写入失败，回退到内存余弦检索：{exc}"
            indexed += 1
        db.commit()
    remaining = db.scalar(
        select(Chunk.id)
        .where(
            Chunk.project_id == project_id,
            Chunk.excluded.is_(False),
            ~Chunk.id.in_(select(ChunkEmbedding.chunk_id)),
        )
        .limit(1)
    )
    return {
        "indexed": indexed,
        "remaining": 1 if remaining else 0,
        "model": embedding_service.model_tag(),
        "backend": embedding_service.backend,
        "vec": vec_ok,
        "warning": warning or embedding_service.vec_warning or embedding_service.load_error,
    }


def _result(chunk: Chunk, source: Source | None, score: float | None, mode: str) -> dict[str, Any]:
    return {
        "chunk_id": chunk.id,
        "project_id": chunk.project_id,
        "source_id": chunk.source_id,
        "source_name": source.original_name if source else chunk.source_id,
        "text": chunk.text,
        "heading_path": chunk.heading_path,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "score": round(score, 4) if score is not None else None,
        "mode": mode,
    }


def _keyword_search(db: Session, project_id: str, query: str, limit: int) -> list[dict[str, Any]]:
    chunks = db.scalars(
        select(Chunk)
        .where(
            Chunk.project_id == project_id,
            Chunk.excluded.is_(False),
            Chunk.text.contains(query),
        )
        .order_by(Chunk.source_id, Chunk.order_index)
        .limit(limit)
    ).all()
    source_ids = {chunk.source_id for chunk in chunks}
    sources = {
        source.id: source
        for source in db.scalars(select(Source).where(Source.id.in_(source_ids))).all()
    }
    return [_result(chunk, sources.get(chunk.source_id), None, "keyword") for chunk in chunks]


def _cosine_search(db: Session, project_id: str, vector: np.ndarray, limit: int) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ChunkEmbedding).where(ChunkEmbedding.project_id == project_id)
    ).all()
    if not rows:
        return []
    scored: list[tuple[float, str]] = []
    for row in rows:
        stored = np.frombuffer(row.vector, dtype=np.float32)
        if stored.shape[0] != vector.shape[0]:
            continue
        score = float(np.dot(stored, vector))
        scored.append((score, row.chunk_id))
    scored.sort(reverse=True)
    top = scored[:limit]
    chunks = {
        chunk.id: chunk
        for chunk in db.scalars(
            select(Chunk).where(Chunk.id.in_([chunk_id for _, chunk_id in top]))
        ).all()
    }
    source_ids = {chunk.source_id for chunk in chunks.values()}
    sources = {
        source.id: source
        for source in db.scalars(select(Source).where(Source.id.in_(source_ids))).all()
    }
    results = []
    for score, chunk_id in top:
        chunk = chunks.get(chunk_id)
        if chunk:
            results.append(_result(chunk, sources.get(chunk.source_id), max(0.0, score), "cosine"))
    return results


def search_chunks(
    db: Session,
    project_id: str,
    query: str,
    limit: int | None = None,
) -> dict[str, Any]:
    query = query.strip()
    limit = min(limit or settings.vector_search_limit, 50)
    if not query:
        return {"query": query, "mode": "empty", "results": [], "warning": ""}
    warning = ""
    vector: np.ndarray | None = None
    try:
        vector = embedding_service.embed([query])[0]
    except EmbeddingError as exc:
        warning = str(exc)

    if vector is not None and embedding_service.vec_available():
        try:
            rows = db.execute(
                text(
                    "SELECT chunk_id, distance FROM chunk_vectors "
                    "WHERE project_id = :project_id AND embedding MATCH :embedding "
                    "AND k = :k"
                ),
                {
                    "project_id": project_id,
                    "embedding": _serialize(vector),
                    "k": limit,
                },
            ).all()
        except Exception as exc:
            warning = f"sqlite-vec 检索失败，回退到余弦检索：{exc}"
            rows = []
        if rows:
            chunk_ids = [row[0] for row in rows]
            chunks = {
                chunk.id: chunk
                for chunk in db.scalars(
                    select(Chunk).where(
                        Chunk.id.in_(chunk_ids), Chunk.project_id == project_id
                    )
                ).all()
            }
            source_ids = {chunk.source_id for chunk in chunks.values()}
            sources = {
                source.id: source
                for source in db.scalars(select(Source).where(Source.id.in_(source_ids))).all()
            }
            results = []
            for chunk_id, distance in rows:
                chunk = chunks.get(chunk_id)
                if not chunk:
                    continue
                similarity = max(0.0, 1.0 - float(distance) / 2.0)
                results.append(_result(chunk, sources.get(chunk.source_id), similarity, "vec"))
            if results:
                return {"query": query, "mode": "vec", "results": results, "warning": warning}

    if vector is not None:
        results = _cosine_search(db, project_id, vector, limit)
        if results:
            return {"query": query, "mode": "cosine", "results": results, "warning": warning}
    results = _keyword_search(db, project_id, query, limit)
    return {"query": query, "mode": "keyword", "results": results, "warning": warning}


def vector_status(db: Session, project_id: str) -> dict[str, Any]:
    chunk_count = db.scalar(
        select(Chunk.id).where(Chunk.project_id == project_id).limit(1)
    )
    total = db.query(Chunk).filter(Chunk.project_id == project_id).count()
    embedded = db.query(ChunkEmbedding).filter(ChunkEmbedding.project_id == project_id).count()
    return {
        "chunks": total,
        "embedded": embedded,
        "model": embedding_service.model_tag(),
        "backend": embedding_service.backend,
        "dim": settings.embedding_dim,
        "vec": embedding_service.vec_available(),
        "warning": embedding_service.vec_warning or embedding_service.load_error,
        "has_chunks": bool(chunk_count),
    }
