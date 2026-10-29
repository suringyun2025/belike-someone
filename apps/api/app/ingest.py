from __future__ import annotations

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Chunk, Claim, Conflict, Document, DocumentBlock, EvidenceItem, Source
from .parsers import NeedsASR, NeedsOCR, ParseError, chunk_text, parse_file
from .storage import detect_source_type, guess_mime


def invalidate_source_evidence(db: Session, source_id: str) -> dict[str, int]:
    """Remove evidence tied to a source and retire claims that have no evidence left."""
    chunk_ids = list(
        db.scalars(select(Chunk.id).where(Chunk.source_id == source_id)).all()
    )
    if not chunk_ids:
        return {"evidence": 0, "claims": 0, "conflicts": 0}
    affected_claim_ids = set(
        db.scalars(
            select(EvidenceItem.claim_id).where(EvidenceItem.chunk_id.in_(chunk_ids))
        ).all()
    )
    evidence_count = db.execute(
        delete(EvidenceItem).where(EvidenceItem.chunk_id.in_(chunk_ids))
    ).rowcount or 0
    removed_claims = 0
    for claim_id in affected_claim_ids:
        claim = db.get(Claim, claim_id)
        if not claim:
            continue
        remaining = db.scalar(
            select(func.count())
            .select_from(EvidenceItem)
            .where(EvidenceItem.claim_id == claim_id)
        ) or 0
        if remaining == 0:
            db.delete(claim)
            removed_claims += 1
        else:
            claim.source_count = remaining
            claim.evidence_grade = "direct_quote"
            db.add(claim)
    conflict_count = 0
    if affected_claim_ids:
        conflict_count = db.execute(
            delete(Conflict).where(
                or_(
                    Conflict.claim_a_id.in_(affected_claim_ids),
                    Conflict.claim_b_id.in_(affected_claim_ids),
                )
            )
        ).rowcount or 0
    db.flush()
    return {
        "evidence": evidence_count,
        "claims": removed_claims,
        "conflicts": conflict_count,
    }


def parse_source(db: Session, source: Source) -> Source:
    try:
        parsed = parse_file(
            source.storage_path,
            source.original_name,
            mime=source.mime,
            source_type=source.source_type,
        )
        if not parsed.blocks:
            raise ParseError("未从资料中提取到可用文本")

        invalidate_source_evidence(db, source.id)
        for document in list(source.documents):
            db.delete(document)
        db.flush()

        document = Document(
            source_id=source.id,
            parser=parsed.parser,
            parser_version=parsed.parser_version,
            language=parsed.language,
            normalized_text=parsed.text,
            meta=parsed.meta,
        )
        db.add(document)
        db.flush()

        for index, block in enumerate(parsed.blocks):
            db.add(
                DocumentBlock(
                    document_id=document.id,
                    order_index=index,
                    text=block.text,
                    kind=block.kind,
                    heading=block.heading,
                    page=block.page,
                    start_char=block.start_char,
                    end_char=block.end_char,
                    meta=block.meta,
                )
            )

        chunks = chunk_text(
            parsed.blocks,
            chunk_chars=settings.chunk_chars,
            overlap=settings.chunk_overlap,
        )
        for index, item in enumerate(chunks):
            db.add(
                Chunk(
                    project_id=source.project_id,
                    source_id=source.id,
                    document_id=document.id,
                    order_index=index,
                    text=item["text"],
                    token_estimate=item["token_estimate"],
                    heading_path=item["heading_path"],
                    page_start=item["page_start"],
                    page_end=item["page_end"],
                    start_char=item["start_char"],
                    end_char=item["end_char"],
                    sha256=item["sha256"],
                    meta=item["meta"],
                )
            )

        source.status = "parsed"
        source.parse_error = ""
        source.redaction_count = parsed.redaction_count
        source.meta = {
            **(source.meta or {}),
            "parser": parsed.parser,
            "language": parsed.language,
            "blocks": len(parsed.blocks),
            "chunks": len(chunks),
            "pages": parsed.meta.get("pages"),
        }
        db.add(source)
        db.commit()
        db.refresh(source)
        return source
    except NeedsOCR as exc:
        source.status = "needs_ocr"
        source.parse_error = str(exc)
        db.add(source)
        db.commit()
        return source
    except NeedsASR as exc:
        source.status = "needs_asr"
        source.parse_error = str(exc)
        db.add(source)
        db.commit()
        return source
    except Exception as exc:
        source.status = "failed"
        source.parse_error = str(exc)
        db.add(source)
        db.commit()
        return source


def parse_pending_sources(db: Session, project_id: str) -> dict[str, int]:
    sources = db.scalars(
        select(Source).where(
            Source.project_id == project_id,
            Source.status.in_(["uploaded", "failed", "needs_ocr", "needs_asr"]),
        )
    ).all()
    summary = {"total": len(sources), "parsed": 0, "failed": 0}
    for source in sources:
        parse_source(db, source)
        if source.status == "parsed":
            summary["parsed"] += 1
        else:
            summary["failed"] += 1
    return summary


def reparse_source(db: Session, source: Source) -> Source:
    source.status = "uploaded"
    source.parse_error = ""
    db.add(source)
    db.commit()
    return parse_source(db, source)


def create_source_from_file(
    db: Session,
    project_id: str,
    filename: str,
    data: bytes,
    mime: str = "",
    source_type: str = "",
    duplicate_of: str | None = None,
    parse_now: bool = True,
) -> Source:
    from .security import sha256_bytes
    from .storage import save_source_file

    digest, path, size = save_source_file(project_id, filename, data)
    source = Source(
        project_id=project_id,
        filename=filename,
        original_name=filename,
        mime=mime or guess_mime(filename),
        size=size,
        sha256=digest,
        storage_path=path,
        source_type=source_type or detect_source_type(filename, mime),
        status="uploaded",
        duplicate_of=duplicate_of,
        meta={"original_filename": filename},
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    if parse_now:
        source = parse_source(db, source)
    return source
