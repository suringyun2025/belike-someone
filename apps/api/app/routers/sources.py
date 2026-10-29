from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..ingest import create_source_from_file, invalidate_source_evidence, parse_source, reparse_source
from ..models import AuditEvent, Chunk, Project, Source
from ..schemas import SourceOut
from ..security import sha256_file
from ..storage import detect_source_type, safe_extract_zip
from .common import source_out

router = APIRouter(tags=["sources"])

CHUNK = 1024 * 1024


def _get_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _get_source(db: Session, source_id: str) -> Source:
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="资料不存在")
    return source


def _spool_upload(upload: UploadFile, max_bytes: int) -> Path:
    """Stream a multipart upload to a temp file with an enforced size cap.

    The previous implementation called ``await upload.read()`` before checking
    the size, so a 256 MB limit could still allocate 256 MB per concurrent
    request. Streaming keeps peak memory bounded by ``CHUNK`` regardless of the
    declared file size and stops early once the cap is exceeded.

    On any failure the partial temp file is removed, otherwise a rejected upload
    would leak up to ``max_bytes`` of disk per attempt.
    """
    tmp = tempfile.NamedTemporaryFile(prefix="distill-upload-", delete=False)
    path = Path(tmp.name)
    total = 0
    try:
        while True:
            block = upload.file.read(CHUNK)
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"{upload.filename or '文件'} 超过单文件上限 {settings.max_upload_mb} MB",
                )
            tmp.write(block)
        tmp.flush()
        os.fsync(tmp.fileno())
    except BaseException:
        tmp.close()
        path.unlink(missing_ok=True)
        raise
    tmp.close()
    return path


@router.get("/projects/{project_id}/sources", response_model=list[SourceOut])
def list_sources(project_id: str, db: Session = Depends(get_db)):
    _get_project(db, project_id)
    sources = db.scalars(
        select(Source).where(Source.project_id == project_id).order_by(Source.created_at.desc())
    ).all()
    return [source_out(db, source) for source in sources]


@router.post("/projects/{project_id}/sources", response_model=list[SourceOut], status_code=201)
def upload_sources(
    project_id: str,
    files: list[UploadFile],
    db: Session = Depends(get_db),
):
    project = _get_project(db, project_id)
    created: list[Source] = []
    max_bytes = settings.max_upload_mb * 1024 * 1024
    spooled: list[Path] = []
    try:
        for upload in files:
            filename = Path(upload.filename or "upload.bin").name
            path = _spool_upload(upload, max_bytes)
            spooled.append(path)

            if filename.lower().endswith(".zip"):
                try:
                    with tempfile.TemporaryDirectory(prefix="distill-zip-") as tmp:
                        extracted = safe_extract_zip(path.read_bytes(), Path(tmp))
                        if not extracted:
                            raise ValueError("ZIP 中没有文件")
                        for item in extracted:
                            relative = item.relative_to(tmp).as_posix()
                            data = item.read_bytes()
                            if len(data) > max_bytes:
                                continue
                            from ..security import sha256_bytes

                            digest = sha256_bytes(data)
                            duplicate = db.scalar(
                                select(Source).where(
                                    Source.project_id == project_id, Source.sha256 == digest
                                )
                            )
                            created.append(
                                create_source_from_file(
                                    db,
                                    project_id,
                                    relative,
                                    data,
                                    source_type=detect_source_type(relative),
                                    duplicate_of=duplicate.id if duplicate else None,
                                    parse_now=True,
                                )
                            )
                except HTTPException:
                    raise
                except Exception as exc:
                    raise HTTPException(status_code=400, detail=f"ZIP 处理失败：{exc}") from exc
                continue

            digest = sha256_file(path)
            duplicate = db.scalar(
                select(Source).where(Source.project_id == project_id, Source.sha256 == digest)
            )
            created.append(
                create_source_from_file(
                    db,
                    project_id,
                    filename,
                    path.read_bytes(),
                    source_type=detect_source_type(filename),
                    duplicate_of=duplicate.id if duplicate else None,
                    parse_now=True,
                )
            )
    finally:
        for path in spooled:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    db.add(
        AuditEvent(
            project_id=project.id,
            action="source.upload",
            detail={"count": len(created), "names": [source.original_name for source in created]},
        )
    )
    db.commit()
    return [source_out(db, source) for source in created]


@router.get("/sources/{source_id}", response_model=SourceOut)
def get_source(source_id: str, db: Session = Depends(get_db)):
    return source_out(db, _get_source(db, source_id))


@router.get("/sources/{source_id}/preview")
def preview_source(source_id: str, db: Session = Depends(get_db)):
    source = _get_source(db, source_id)
    blocks = []
    for document in source.documents:
        for block in document.blocks:
            blocks.append(
                {
                    "id": block.id,
                    "order_index": block.order_index,
                    "text": block.text,
                    "kind": block.kind,
                    "heading": block.heading,
                    "page": block.page,
                    "start_char": block.start_char,
                    "end_char": block.end_char,
                    "meta": block.meta,
                }
            )
    return {
        "source": source_out(db, source).model_dump(mode="json"),
        "blocks": blocks[:300],
        "truncated": len(blocks) > 300,
    }


@router.get("/sources/{source_id}/chunks")
def list_chunks(source_id: str, db: Session = Depends(get_db)):
    source = _get_source(db, source_id)
    chunks = db.scalars(
        select(Chunk).where(Chunk.source_id == source.id).order_by(Chunk.order_index)
    ).all()
    return [
        {
            "id": chunk.id,
            "order_index": chunk.order_index,
            "text": chunk.text,
            "token_estimate": chunk.token_estimate,
            "heading_path": chunk.heading_path,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "excluded": chunk.excluded,
            "sha256": chunk.sha256,
        }
        for chunk in chunks
    ]


@router.patch("/chunks/{chunk_id}")
def update_chunk(chunk_id: str, payload: dict, db: Session = Depends(get_db)):
    """Exclude or re-include a chunk so it never reaches the LLM again.

    Excluding a chunk also retires claims whose only evidence came from it,
    mirroring the source-deletion semantics.
    """
    chunk = db.get(Chunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="文本块不存在")
    if "excluded" in payload:
        chunk.excluded = bool(payload["excluded"])
        db.add(chunk)
        db.add(
            AuditEvent(
                project_id=chunk.project_id,
                action="chunk.exclude" if chunk.excluded else "chunk.include",
                detail={"chunk_id": chunk.id, "source_id": chunk.source_id},
            )
        )
    db.commit()
    db.refresh(chunk)
    return {"id": chunk.id, "excluded": chunk.excluded}


@router.post("/sources/{source_id}/parse", response_model=SourceOut)
def parse_source_endpoint(source_id: str, db: Session = Depends(get_db)):
    source = _get_source(db, source_id)
    source = reparse_source(db, source)
    db.add(
        AuditEvent(
            project_id=source.project_id,
            action="source.reparse",
            detail={"source_id": source.id, "status": source.status},
        )
    )
    db.commit()
    return source_out(db, source)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str, db: Session = Depends(get_db)):
    source = _get_source(db, source_id)
    project_id = source.project_id
    path = Path(source.storage_path)
    invalidated = invalidate_source_evidence(db, source.id)
    db.delete(source)
    db.add(
        AuditEvent(
            project_id=project_id,
            action="source.delete",
            detail={
                "source_id": source.id,
                "filename": source.original_name,
                "invalidated": invalidated,
            },
        )
    )
    db.commit()
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    return None