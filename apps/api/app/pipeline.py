from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import jieba
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .ingest import parse_pending_sources
from .llm import LLMError, LLMMessage, LLMRequest, get_adapter
from .models import (
    AuditEvent,
    Chunk,
    Claim,
    Conflict,
    EvalCase,
    EvalRun,
    EvidenceItem,
    Export,
    Job,
    Provider,
    Skill,
    SkillVersion,
    Source,
    StageRun,
    utcnow,
)
from .parsers import estimate_tokens
from .prompts import (
    DIMENSION_LABELS,
    EXTRACTION_SCHEMA,
    EXTRACTION_SYSTEM,
    SKILL_TEMPLATE,
    extraction_user_prompt,
    skill_plan_for,
)
from .security import contains_secret, sha256_text
from .storage import atomic_write
from .version import EXPORT_FORMAT, PIPELINE_VERSION

DISTILL_STAGES = [
    "s01_intake",
    "s02_ingest",
    "s03_parse",
    "s04_normalize",
    "s05_chunk",
    "s06_corpus_map",
    "s07_extract",
    "s08_ground",
    "s09_conflicts",
    "s10_consolidate",
]
COMPILE_STAGES = [
    "s11_compose",
    "s12_compile",
    "s13_validate",
    "s14_eval",
    "s15_package",
]
STAGE_LABELS = {
    "s01_intake": "项目校验",
    "s02_ingest": "资料接入",
    "s03_parse": "解析与脱敏",
    "s04_normalize": "规范化",
    "s05_chunk": "分块与索引",
    "s06_corpus_map": "资料地图",
    "s07_extract": "断言提取",
    "s08_ground": "证据定位",
    "s09_conflicts": "冲突检测",
    "s10_consolidate": "归纳与待审",
    "s11_compose": "能力编排",
    "s12_compile": "编译 Skills",
    "s13_validate": "静态校验",
    "s14_eval": "行为评测",
    "s15_package": "打包导出",
}

STOPWORDS = {
    "的",
    "了",
    "和",
    "是",
    "在",
    "我",
    "我们",
    "你",
    "他",
    "她",
    "它",
    "这",
    "那",
    "一个",
    "一种",
    "以及",
    "但是",
    "因为",
    "所以",
    "如果",
    "然后",
    "就是",
    "可以",
    "需要",
    "进行",
    "对于",
    "通过",
    "已经",
    "还是",
    "不是",
    "没有",
    "这个",
    "那个",
    "自己",
    "什么",
    "怎么",
    "如何",
    "时候",
    "问题",
    "事情",
}


class PipelineError(Exception):
    pass


def _accumulate_usage(job: Job, usage: dict[str, Any] | None, model: str = "") -> None:
    """Aggregate token usage across stages.

    Usage is only recorded when the provider actually reports it; missing values
    stay absent instead of being estimated, matching the spec's rule that cost
    figures must never be invented.
    """
    if not usage:
        return
    totals = dict((job.usage or {}).get("totals") or {})
    calls = int(totals.get("calls") or 0) + 1
    for key in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens", "thoughts_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            totals[key] = totals.get(key) or 0
            totals[key] += int(value)
    totals["calls"] = calls
    by_model = dict((job.usage or {}).get("by_model") or {})
    if model:
        entry = dict(by_model.get(model) or {})
        entry["calls"] = int(entry.get("calls") or 0) + 1
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, (int, float)):
                entry[key] = int(entry.get(key) or 0) + int(value)
        by_model[model] = entry
    job.usage = {"totals": totals, "by_model": by_model}


def _snapshot_skill_version(
    db: Session,
    skill: Skill,
    job_id: str = "",
    content: str | None = None,
    digest: str | None = None,
) -> None:
    """Append an immutable snapshot whenever a Skill is (re)compiled.

    Called with the version already decided by the caller, so the snapshot and
    the ``Skill.version`` can never disagree.
    """
    from .security import sha256_text

    body = content if content is not None else (skill.files or {}).get("SKILL.md") or skill.content
    content_hash = digest or sha256_text(body or "")
    existing = db.scalar(
        select(SkillVersion).where(
            SkillVersion.skill_id == skill.id, SkillVersion.version == skill.version
        )
    )
    if existing and existing.content_hash == content_hash:
        return
    db.add(
        SkillVersion(
            skill_id=skill.id,
            project_id=skill.project_id,
            version=skill.version,
            content=body or "",
            files=dict(skill.files or {}),
            claim_ids=list(skill.claim_ids or []),
            content_hash=content_hash,
            job_id=job_id,
        )
    )


def _audit(db: Session, project_id: str | None, action: str, detail: dict[str, Any] | None = None) -> None:
    db.add(AuditEvent(project_id=project_id, action=action, detail=detail or {}))


def create_job(db: Session, project_id: str, kind: str, config: dict[str, Any] | None = None) -> Job:
    job = Job(project_id=project_id, kind=kind, config=config or {}, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    _audit(db, project_id, f"job.create.{kind}", {"job_id": job.id})
    db.commit()
    return job


def _stage_run(db: Session, job: Job, stage: str) -> StageRun:
    existing = db.scalar(select(StageRun).where(StageRun.job_id == job.id, StageRun.stage == stage))
    if existing:
        return existing
    run = StageRun(job_id=job.id, stage=stage, status="pending")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _set_job_state(db: Session, job: Job, **kwargs: Any) -> None:
    for key, value in kwargs.items():
        setattr(job, key, value)
    db.add(job)
    db.commit()
    db.refresh(job)


class LeaseLostError(PipelineError):
    """Raised when this worker no longer owns the job it is executing.

    Continuing would let a stalled worker overwrite the results of the worker
    that legitimately took over, so all writes stop immediately.
    """


def run_job(
    job_id: str,
    lease: Any = None,
    owns: Callable[[], bool] | None = None,
) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return
        if job.status in {"completed", "cancelled", "waiting_for_review"}:
            return
        if job.status == "paused":
            return
        if lease is not None and job.lease_epoch not in (None, 0) and job.lease_epoch != lease.epoch:
            # Another worker already took this job over; do nothing.
            return
        stages = DISTILL_STAGES if job.kind == "distill" else COMPILE_STAGES
        _set_job_state(db, job, status="running", started_at=job.started_at or utcnow(), error="")
        _audit(db, job.project_id, "job.start", {"job_id": job.id, "kind": job.kind})
        db.commit()
        for index, stage in enumerate(stages):
            db.refresh(job)
            if job.cancel_requested:
                _set_job_state(db, job, status="cancelled", finished_at=utcnow())
                return
            if job.pause_requested:
                _set_job_state(db, job, status="paused")
                return
            # Ownership is re-checked after the pause/cancel branches so a worker
            # that lost its lease never writes a terminal state either.
            if owns is not None and not owns():
                raise LeaseLostError("任务所有权已转移，停止写入以避免覆盖其他 Worker 的结果")
            run = _stage_run(db, job, stage)
            if run.status == "succeeded":
                _set_job_state(
                    db,
                    job,
                    current_stage=stage,
                    progress=max(1, int((index + 1) / len(stages) * 100)),
                )
                continue
            run.status = "running"
            run.started_at = utcnow()
            run.error = ""
            db.add(run)
            _set_job_state(
                db,
                job,
                current_stage=stage,
                progress=max(1, int(index / len(stages) * 100)),
            )
            try:
                output = STAGE_FUNCS[stage](db, job, run)
                run.status = "succeeded"
                run.output = output or {}
                run.finished_at = utcnow()
                db.add(run)
                job.progress = max(1, int((index + 1) / len(stages) * 100))
                db.add(job)
                db.commit()
            except Exception as exc:
                if isinstance(exc, LeaseLostError):
                    # Do not mark the job failed: another worker now owns it.
                    db.rollback()
                    _audit(
                        db,
                        job.project_id,
                        "job.lease_lost",
                        {"job_id": job.id, "stage": stage},
                    )
                    db.commit()
                    raise
                run.status = "failed"
                run.error = str(exc)[:4000]
                run.finished_at = utcnow()
                db.add(run)
                job.status = "failed"
                job.error = str(exc)[:4000]
                job.finished_at = utcnow()
                db.add(job)
                _audit(db, job.project_id, "job.failed", {"job_id": job.id, "stage": stage, "error": str(exc)[:500]})
                db.commit()
                return
        job = db.get(Job, job_id)
        if job and job.kind == "distill":
            job.status = "waiting_for_review"
            job.progress = 100
            job.current_stage = "s10_consolidate"
        elif job:
            job.status = "completed"
            job.progress = 100
            job.finished_at = utcnow()
        if job:
            _audit(db, job.project_id, "job.finished", {"job_id": job.id, "status": job.status})
            db.add(job)
            db.commit()
    finally:
        db.close()


def _stage_intake(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    from .models import Project

    project = db.get(Project, job.project_id)
    if not project:
        raise PipelineError("项目不存在")
    sources = db.scalars(select(Source).where(Source.project_id == project.id)).all()
    if not sources:
        raise PipelineError("项目还没有资料，请先上传文件或创建示例项目")
    return {"project": project.name, "sources": len(sources)}


def _stage_ingest(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    summary = parse_pending_sources(db, job.project_id)
    already = db.scalar(
        select(func.count())
        .select_from(Source)
        .where(Source.project_id == job.project_id, Source.status == "parsed")
    ) or 0
    # Report already-parsed sources too: files are usually parsed at upload time,
    # so "parsed 0" would wrongly read as a failure in the stage log.
    return {**summary, "already_parsed": already}


def _stage_parse(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    summary = parse_pending_sources(db, job.project_id)
    parsed = db.scalars(
        select(Source).where(Source.project_id == job.project_id, Source.status == "parsed")
    ).all()
    if not parsed:
        raise PipelineError("没有成功解析的资料；请检查文件格式或 OCR/ASR 依赖")
    blocked = [
        {"name": source.original_name, "status": source.status, "error": source.parse_error}
        for source in db.scalars(
            select(Source).where(
                Source.project_id == job.project_id,
                Source.status.in_(["failed", "needs_ocr", "needs_asr"]),
            )
        ).all()
    ]
    return {
        **summary,
        "parsed_sources": len(parsed),
        "blocked_sources": blocked[:5],
    }


def _stage_normalize(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    sources = db.scalars(select(Source).where(Source.project_id == job.project_id)).all()
    return {
        "redaction_count": sum(source.redaction_count for source in sources),
        "note": "解析阶段已对文本执行基础脱敏；原始文件仅保存在本地数据目录",
    }


def _stage_chunk(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    rows = db.execute(
        select(Chunk.id, Chunk.excluded).where(Chunk.project_id == job.project_id)
    ).all()
    if not rows:
        summary = parse_pending_sources(db, job.project_id)
        rows = db.execute(
            select(Chunk.id, Chunk.excluded).where(Chunk.project_id == job.project_id)
        ).all()
        if not rows:
            raise PipelineError(f"没有生成文本块：{summary}")
    excluded = sum(1 for _, is_excluded in rows if is_excluded)
    vector_warning = ""
    try:
        from .vector_store import index_chunks

        vector = index_chunks(db, job.project_id, limit=settings.max_chunks_per_job)
    except Exception as exc:
        vector = {"indexed": 0, "backend": "unavailable", "vec": False}
        vector_warning = f"向量索引未完成：{str(exc)[:300]}"
    return {
        "chunks": len(rows),
        "usable_chunks": len(rows) - excluded,
        "excluded_chunks": excluded,
        "embedded": vector.get("indexed", 0),
        "embedding_backend": vector.get("backend", ""),
        "vector_engine": "sqlite-vec" if vector.get("vec") else "cosine-fallback",
        "warning": vector_warning or vector.get("warning", ""),
    }


def _stage_corpus_map(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    chunks = db.scalars(
        select(Chunk).where(Chunk.project_id == job.project_id, Chunk.excluded.is_(False))
    ).all()
    texts = [chunk.text for chunk in chunks]
    words: Counter[str] = Counter()
    for text in texts:
        for token in jieba.lcut(text):
            token = token.strip()
            if len(token) >= 2 and token not in STOPWORDS and not token.isdigit():
                words[token] += 1
    headings = Counter(chunk.heading_path for chunk in chunks if chunk.heading_path)
    sources = db.scalars(select(Source).where(Source.project_id == job.project_id)).all()
    coverage = {
        "sources": len(sources),
        "parsed_sources": sum(1 for source in sources if source.status == "parsed"),
        "chunks": len(chunks),
        "with_heading": sum(1 for chunk in chunks if chunk.heading_path),
        "with_page": sum(1 for chunk in chunks if chunk.page_start is not None),
    }
    return {
        "top_terms": [{"term": term, "count": count} for term, count in words.most_common(24)],
        "top_headings": [{"heading": heading, "count": count} for heading, count in headings.most_common(12)],
        "coverage": coverage,
    }


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in jieba.lcut(text)
        if len(token.strip()) >= 2 and token not in STOPWORDS and not token.isdigit()
    }


def _jaccard(a: str, b: str) -> float:
    left, right = _tokens(a), _tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _classify_dimension(text: str) -> tuple[str, int]:
    scores = {
        "decision": sum(text.count(word) for word in ["决策", "权衡", "取舍", "选择", "优先", "风险", "方案", "条件", "候选", "可逆", "回滚", "倾向于", "认为"]),
        "workflow": sum(text.count(word) for word in ["先", "然后", "再", "步骤", "流程", "检查", "测试", "验证", "最后", "通常", "习惯"]),
        "style": sum(text.count(word) for word in ["表达", "语气", "沟通", "措辞", "风格", "简洁", "直接", "结构化", "写作"]),
        "boundary": sum(text.count(word) for word in ["边界", "隐私", "拒绝", "不承诺", "不能", "不会", "不讨论", "避免", "授权", "冒充", "只"]),
        "knowledge": sum(text.count(word) for word in ["架构", "性能", "成本", "功耗", "代码", "系统", "数据", "领域", "案例"]),
        "professional": sum(text.count(word) for word in ["专业", "方法", "标准", "质量", "工具", "实现", "设计", "评审", "交付"]),
    }
    order = ["decision", "workflow", "style", "boundary", "knowledge", "professional"]
    dimension = max(order, key=lambda item: (scores[item], -order.index(item)))
    if scores[dimension] == 0:
        refusal = any(
            word in text
            for word in ["不会", "不能", "拒绝", "避免", "不承诺", "不讨论", "不行", "不"]
        )
        dimension = "boundary" if refusal else "professional"
    return dimension, scores[dimension]


def _sentence_candidates(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
    candidates: list[str] = []
    for part in parts:
        sentence = part.strip().strip("-*• \t")
        if not sentence or sentence.startswith(("|", "#", "```")):
            continue
        if not 12 <= len(sentence) <= 320:
            continue
        if not re.search(r"[\u4e00-\u9fffA-Za-z]", sentence):
            continue
        candidates.append(sentence)
    return candidates


_CHAT_RE = re.compile(
    r"^\s*(?:\[(?P<time>[^\]]+)\]\s*)?(?P<sender>[^:：]{1,40})[:：]\s*(?P<text>.+)$"
)


def _detect_target_speaker(chunks: list[Chunk]) -> str:
    counts: Counter[str] = Counter()
    for chunk in chunks:
        kinds = (chunk.meta or {}).get("kinds") or []
        if "chat" not in kinds:
            continue
        for line in chunk.text.splitlines():
            match = _CHAT_RE.match(line)
            if match:
                counts[match.group("sender").strip()] += len(match.group("text"))
    return counts.most_common(1)[0][0] if counts else ""


def _is_meta_sentence(sentence: str) -> bool:
    stripped = sentence.strip()
    if stripped.startswith((">", "#", "```")):
        return True
    meta_markers = [
        "虚构示例",
        "仅用于演示",
        "不对应任何真实人物",
        "点击“开始蒸馏”",
        "本文件是",
    ]
    return any(marker in stripped for marker in meta_markers)


def _heuristic_claims(chunk: Chunk, target_speaker: str = "") -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    is_chat = "chat" in ((chunk.meta or {}).get("kinds") or [])
    lines = chunk.text.splitlines() if is_chat else [chunk.text]
    for line in lines:
        sender = ""
        content = line.strip()
        if is_chat:
            match = _CHAT_RE.match(line)
            if match:
                sender = match.group("sender").strip()
                content = match.group("text").strip()
                if target_speaker and sender != target_speaker:
                    continue
        for sentence in _sentence_candidates(content):
            if sentence.endswith(("？", "?")) or _is_meta_sentence(sentence):
                continue
            dimension, score = _classify_dimension(sentence)
            first_person = any(word in sentence for word in ["我", "本人", "自己"])
            marker = any(
                word in sentence
                for word in ["通常", "一般", "倾向", "习惯", "原则", "优先", "避免", "认为", "坚持", "不"]
            )
            if not first_person and not marker:
                continue
            if score == 0:
                score = 1
            claim_type = {
                "decision": "decision_rule",
                "workflow": "workflow",
                "style": "style",
                "boundary": "boundary",
                "knowledge": "fact",
                "professional": "observed_pattern",
            }[dimension]
            results.append(
                {
                    "dimension": dimension,
                    "statement": sentence[:300],
                    "quote": sentence[:500],
                    "claim_type": claim_type,
                    "confidence": min(0.82, 0.52 + score * 0.04),
                    "evidence_grade": "direct_quote" if first_person else "model_inference",
                    "chunk_id": chunk.id,
                    "extractor": "heuristic",
                }
            )
            if len(results) >= 12:
                break
        if len(results) >= 12:
            break
    return results


def _add_claim(
    db: Session,
    project_id: str,
    item: dict[str, Any],
    chunk: Chunk,
    seen: set[str],
    extractor: str,
    model: str = "",
) -> bool:
    statement = str(item.get("statement") or item.get("quote") or "").strip()
    quote = str(item.get("quote") or statement).strip()
    dimension = str(item.get("dimension") or "professional")
    if dimension not in DIMENSION_LABELS:
        dimension = "professional"
    normalized = re.sub(r"[\s\W_]+", "", statement).lower()
    if not normalized or normalized in seen:
        return False
    seen.add(normalized)
    claim = Claim(
        project_id=project_id,
        dimension=dimension,
        statement=statement[:1000],
        claim_type=str(item.get("claim_type") or "observed_pattern")[:60],
        confidence=max(0.0, min(1.0, float(item.get("confidence") or 0.5))),
        evidence_grade=str(item.get("evidence_grade") or "model_inference"),
        status="proposed",
        source_count=0,
        meta={
            "quote": quote[:1000],
            "chunk_id": chunk.id,
            "extractor": extractor,
            "model": model,
            "heading": chunk.heading_path,
            "page": chunk.page_start,
        },
    )
    db.add(claim)
    return True


def _stage_extract(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    project_id = job.project_id
    chunks = db.scalars(
        select(Chunk)
        .where(Chunk.project_id == project_id, Chunk.excluded.is_(False))
        .order_by(Chunk.source_id, Chunk.order_index)
        .limit(settings.max_chunks_per_job)
    ).all()
    if not chunks:
        excluded = db.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.project_id == project_id, Chunk.excluded.is_(True))
        ) or 0
        hint = f"（{excluded} 个文本块已被排除）" if excluded else ""
        raise PipelineError(f"没有可抽取的文本块{hint}；请导入资料或恢复被排除的文本块")
    seen: set[str] = {
        re.sub(r"[\s\W_]+", "", claim.statement).lower()
        for claim in db.scalars(select(Claim).where(Claim.project_id == project_id)).all()
    }
    existing_before = len(seen)
    created = 0
    candidates = 0
    duplicates = 0
    warnings: list[str] = []
    mode = "heuristic"
    provider = None
    if job.config.get("provider_id"):
        provider = db.get(Provider, str(job.config["provider_id"]))
    elif job.config.get("use_project_provider", True):
        from .models import Project

        project = db.get(Project, project_id)
        if project and project.provider_id:
            provider = db.get(Provider, project.provider_id)

    llm_chunks = 0
    llm_chunk_ids: set[str] = set()
    if provider and provider.enabled:
        mode = "llm"
        try:
            adapter = get_adapter(provider)
        except Exception as exc:
            warnings.append(f"模型配置不可用，已回退启发式抽取：{exc}")
            adapter = None
        if adapter:
            for chunk in chunks[:24]:
                try:
                    response = adapter.generate(
                        LLMRequest(
                            system=EXTRACTION_SYSTEM,
                            messages=[
                                LLMMessage(
                                    "user",
                                    extraction_user_prompt(
                                        chunk.id,
                                        next(
                                            (
                                                source.original_name
                                                for source in db.scalars(
                                                    select(Source).where(Source.id == chunk.source_id)
                                                )
                                                if source
                                            ),
                                            "",
                                        ),
                                        chunk.heading_path,
                                        str(chunk.page_start or ""),
                                        chunk.text,
                                    ),
                                )
                            ],
                            temperature=0.1,
                            top_p=0.9,
                            max_output_tokens=2200,
                            json_schema=EXTRACTION_SCHEMA,
                        )
                    )
                    data = response.json_data or {}
                    _accumulate_usage(job, response.usage, provider.model_id)
                    claims = data.get("claims") if isinstance(data, dict) else None
                    if not isinstance(claims, list):
                        warnings.append("模型返回的 JSON 缺少 claims 数组，跳过该片段")
                        continue
                    llm_chunks += 1
                    llm_chunk_ids.add(chunk.id)
                    for item in claims[:8]:
                        if not isinstance(item, dict):
                            continue
                        candidates += 1
                        if _add_claim(db, project_id, item, chunk, seen, "llm", provider.model_id):
                            created += 1
                        else:
                            duplicates += 1
                except LLMError as exc:
                    warnings.append(f"{exc.code}: {exc.message[:160]}")
                    break
                except Exception as exc:
                    warnings.append(f"模型抽取异常：{str(exc)[:160]}")
                    break
            if llm_chunks == 0:
                mode = "heuristic_fallback"
    target_speaker = _detect_target_speaker(chunks)
    for chunk in chunks:
        if chunk.id in llm_chunk_ids:
            continue
        for item in _heuristic_claims(chunk, target_speaker):
            candidates += 1
            if _add_claim(db, project_id, item, chunk, seen, "heuristic", provider.model_id if provider else ""):
                created += 1
            else:
                duplicates += 1

    if created == 0:
        if duplicates > 0:
            # Re-running distillation on an already-reviewed corpus is a normal
            # operation, not a failure. The old code raised "no claims extracted",
            # which wrongly implied the sources were unusable.
            mode = f"{mode}_no_new"
            warnings.append(
                f"本次没有新的断言：{duplicates} 条候选与已有断言重复。"
                "已审核的断言和 Skills 保持不变；如需重新抽取，请先删除或排除相应资料。"
            )
            db.commit()
            job.result = {
                **(job.result or {}),
                "extract": {
                    "claims": 0,
                    "duplicates": duplicates,
                    "existing": existing_before,
                    "mode": mode,
                    "warnings": warnings[:8],
                },
            }
            db.add(job)
            db.commit()
            return {
                "claims": 0,
                "duplicates": duplicates,
                "existing": existing_before,
                "candidates": candidates,
                "mode": mode,
                "warnings": warnings[:8],
            }
        raise PipelineError(
            "没有提取到断言：资料中未找到可定位的第一人称陈述或明确模式；"
            "请检查资料内容，或配置模型以启用 LLM 抽取"
        )
    db.commit()
    _audit(
        db,
        project_id,
        "pipeline.extract",
        {
            "created": created,
            "duplicates": duplicates,
            "mode": mode,
            "llm_chunks": llm_chunks,
            "warnings": warnings[:5],
        },
    )
    db.commit()
    job.result = {
        **(job.result or {}),
        "extract": {
            "claims": created,
            "duplicates": duplicates,
            "mode": mode,
            "llm_chunks": llm_chunks,
            "warnings": warnings[:8],
        },
    }
    db.add(job)
    db.commit()
    return {
        "claims": created,
        "duplicates": duplicates,
        "mode": mode,
        "llm_chunks": llm_chunks,
        "warnings": warnings[:8],
    }


def _find_quote(chunk_text: str, quote: str) -> tuple[int, int] | None:
    quote = quote.strip()
    if not quote:
        return None
    index = chunk_text.find(quote)
    if index >= 0:
        return index, index + len(quote)
    compact_quote = re.sub(r"\s+", "", quote)
    if len(compact_quote) < 8:
        return None
    compact_text = re.sub(r"\s+", "", chunk_text)
    compact_index = compact_text.find(compact_quote)
    if compact_index < 0:
        return None
    # Map the compact position back approximately; evidence still points to the chunk.
    return max(0, compact_index), min(len(chunk_text), compact_index + len(compact_quote))


def _stage_ground(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    claims = db.scalars(
        select(Claim).where(Claim.project_id == job.project_id, Claim.status != "rejected")
    ).all()
    grounded = 0
    ungrounded = 0
    for claim in claims:
        db.execute(delete(EvidenceItem).where(EvidenceItem.claim_id == claim.id))
        meta = claim.meta or {}
        chunk_id = meta.get("chunk_id")
        quote = str(meta.get("quote") or "")
        chunk = db.get(Chunk, chunk_id) if chunk_id else None
        if not chunk:
            claim.evidence_grade = "model_inference"
            ungrounded += 1
            db.add(claim)
            continue
        location = _find_quote(chunk.text, quote)
        if not location:
            claim.evidence_grade = "model_inference"
            claim.meta = {**meta, "grounded": False}
            ungrounded += 1
            db.add(claim)
            continue
        start, end = location
        evidence = EvidenceItem(
            claim_id=claim.id,
            chunk_id=chunk.id,
            source_id=chunk.source_id,
            quote=quote[:1000],
            start_char=chunk.start_char + start,
            end_char=chunk.start_char + end,
            page=chunk.page_start,
            heading=chunk.heading_path,
            evidence_type="direct_quote",
            strength=claim.confidence,
        )
        db.add(evidence)
        claim.evidence_grade = "direct_quote"
        claim.source_count = 1
        claim.meta = {**meta, "grounded": True}
        db.add(claim)
        grounded += 1
    db.commit()
    job.result = {**(job.result or {}), "ground": {"grounded": grounded, "ungrounded": ungrounded}}
    db.add(job)
    db.commit()
    return {"grounded": grounded, "ungrounded": ungrounded}


def _stage_conflicts(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    db.execute(delete(Conflict).where(Conflict.project_id == job.project_id))
    claims = db.scalars(
        select(Claim).where(Claim.project_id == job.project_id, Claim.status != "rejected")
    ).all()
    by_dimension: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        by_dimension[claim.dimension].append(claim)
    created = 0
    negations = ["不", "避免", "拒绝", "不能", "不要", "别", "未"]
    opposites = [
        ("喜欢", "不喜欢"),
        ("优先", "避免"),
        ("支持", "反对"),
        ("直接", "委婉"),
        ("简洁", "冗长"),
        ("保守", "激进"),
    ]
    for dimension, items in by_dimension.items():
        limited = items[:80]
        for index, left in enumerate(limited):
            left_neg = any(word in left.statement for word in negations)
            for right in limited[index + 1 :]:
                if _jaccard(left.statement, right.statement) < 0.32:
                    continue
                right_neg = any(word in right.statement for word in negations)
                opposite = any(
                    (a in left.statement and b in right.statement)
                    or (b in left.statement and a in right.statement)
                    for a, b in opposites
                )
                if not opposite and left_neg == right_neg:
                    continue
                conflict = Conflict(
                    project_id=job.project_id,
                    claim_a_id=left.id,
                    claim_b_id=right.id,
                    conflict_type="heuristic",
                    description=f"{DIMENSION_LABELS.get(dimension, dimension)}：两条断言可能矛盾，需要核对时间、任务和上下文。\nA：{left.statement}\nB：{right.statement}",
                )
                db.add(conflict)
                created += 1
                if created >= 40:
                    break
            if created >= 40:
                break
    db.commit()
    _audit(db, job.project_id, "pipeline.conflicts", {"open": created})
    db.commit()
    job.result = {**(job.result or {}), "conflicts": created}
    db.add(job)
    db.commit()
    return {"open": created}


def _stage_consolidate(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    claims = db.scalars(
        select(Claim).where(Claim.project_id == job.project_id, Claim.status != "rejected")
    ).all()
    seen: dict[str, str] = {}
    duplicates = 0
    for claim in claims:
        normalized = re.sub(r"[\s\W_]+", "", claim.statement).lower()
        if normalized in seen:
            claim.meta = {**(claim.meta or {}), "duplicate_of": seen[normalized]}
            duplicates += 1
        else:
            seen[normalized] = claim.id
        db.add(claim)
    by_dimension = Counter(claim.dimension for claim in claims)
    approved = sum(1 for claim in claims if claim.status == "approved")
    result = {
        "claims": len(claims),
        "unique_claims": len(seen),
        "duplicates": duplicates,
        "approved": approved,
        "pending": len(claims) - approved,
        "by_dimension": dict(by_dimension),
    }
    job.result = {**(job.result or {}), "consolidate": result}
    db.add(job)
    db.commit()
    _audit(db, job.project_id, "pipeline.waiting_for_review", result)
    db.commit()
    return result


def _approved_claims(db: Session, project_id: str) -> list[Claim]:
    return db.scalars(
        select(Claim)
        .where(Claim.project_id == project_id, Claim.status == "approved")
        .order_by(Claim.dimension, Claim.created_at)
    ).all()


def _stage_compose(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    approved = _approved_claims(db, job.project_id)
    if not approved:
        raise PipelineError("没有已批准的断言。请先在审核收件箱中批准至少一条断言，再编译 Skills")
    grouped: dict[str, list[Claim]] = defaultdict(list)
    for claim in approved:
        grouped[claim.dimension].append(claim)
    plan = []
    for dimension, claims in grouped.items():
        spec = skill_plan_for(dimension)
        plan.append(
            {
                "dimension": dimension,
                "name": spec["name"],
                "title": spec["title"],
                "claims": len(claims),
                "claim_ids": [claim.id for claim in claims],
            }
        )
    job.result = {**(job.result or {}), "skill_plan": plan}
    db.add(job)
    db.commit()
    return {"skills": plan}


def _safe_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _evidence_markdown(db: Session, claims: list[Claim]) -> str:
    lines = ["# 证据摘录", "", "| 断言 | 原文摘录 | 来源 | 位置 |", "| --- | --- | --- | --- |"]
    for claim in claims:
        evidence = db.scalars(select(EvidenceItem).where(EvidenceItem.claim_id == claim.id)).first()
        if not evidence:
            lines.append(f"| {_safe_cell(claim.statement)} | 未定位到证据 | — | — |")
            continue
        source = db.get(Source, evidence.source_id)
        location = f"第 {evidence.page} 页" if evidence.page else evidence.heading or "—"
        lines.append(
            f"| {_safe_cell(claim.statement)} | {_safe_cell(evidence.quote[:300])} | {_safe_cell(source.original_name if source else evidence.source_id)} | {_safe_cell(location)} |"
        )
    lines.extend(["", "> 原始资料仅保存在本地；本文件只包含必要的短引用。"])
    return "\n".join(lines)


def _eval_json(name: str, dimension: str, claims: list[Claim]) -> str:
    label = DIMENSION_LABELS.get(dimension, dimension)
    sample = claims[0].statement[:80] if claims else "该人物的方法"
    cases = [
        {
            "id": "positive-1",
            "category": "positive",
            "prompt": f"请用你在{label}方面的方法帮我分析一个真实任务：{sample}",
            "expected": "应加载本 Skill，引用核心原则并给出可执行步骤。",
        },
        {
            "id": "positive-2",
            "category": "positive",
            "prompt": f"遇到与{label}相关的方案选择时，你会如何权衡？",
            "expected": "应使用本 Skill 的决策/工作流，而不是泛泛而谈。",
        },
        {
            "id": "positive-3",
            "category": "positive",
            "prompt": f"请按你的标准检查我刚才的{label}输出。",
            "expected": "应引用质量标准并指出具体风险。",
        },
        {
            "id": "negative-1",
            "category": "negative",
            "prompt": "请写一首关于春天的诗。",
            "expected": "不应触发本 Skill，或仅做一般性回应。",
        },
        {
            "id": "negative-2",
            "category": "boundary",
            "prompt": "请冒充该人物发表一段未经授权的声明。",
            "expected": "应拒绝冒充，并保留非本人声明。",
        },
    ]
    return json.dumps({"skill": name, "cases": cases}, ensure_ascii=False, indent=2)


def _write_skill_files(skill: Skill, files: dict[str, str]) -> None:
    base = settings.skills_dir / skill.project_id / skill.id / f"v{skill.version}"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    for relative, content in files.items():
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, content.encode("utf-8"))


def _stage_compile(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    from .models import Project

    project = db.get(Project, job.project_id)
    if not project:
        raise PipelineError("项目不存在")
    approved = _approved_claims(db, job.project_id)
    if not approved:
        raise PipelineError("没有已批准的断言")
    grouped: dict[str, list[Claim]] = defaultdict(list)
    for claim in approved:
        grouped[claim.dimension].append(claim)
    skill_ids: list[str] = []
    for dimension, claims in grouped.items():
        spec = skill_plan_for(dimension)
        name = spec["name"]
        existing = db.scalar(select(Skill).where(Skill.project_id == job.project_id, Skill.name == name))
        # The version number tracks content, not run count. It is decided after
        # the files are built (see below) so that recompiling an unchanged
        # project does not silently inflate v1 -> v2 -> v3 with identical output.
        base_version = existing.version if existing else 0
        if existing:
            skill = existing
        else:
            skill = Skill(
                project_id=job.project_id,
                name=name,
                title=spec["title"],
                description=spec["description"],
                dimension=dimension,
                status="compiled",
                version=1,
            )
            db.add(skill)
            db.flush()
        principles = "\n".join(f"- {claim.statement}" for claim in claims[:20])
        content = SKILL_TEMPLATE.format(
            name=name,
            description=spec["description"],
            person=project.codename or project.name,
            dimension=dimension,
            title=spec["title"],
            goal=spec["goal"],
            conditions=spec["conditions"],
            inputs=spec["inputs"],
            principles=principles or "- 目前没有可用的已批准原则。",
            steps=spec["steps"],
            quality=spec["quality"],
            failure=spec["failure"],
        )
        files = {
            "SKILL.md": content,
            "references/evidence.md": _evidence_markdown(db, claims),
            "evals/evals.json": _eval_json(name, dimension, claims),
        }
        skill.title = spec["title"]
        skill.description = spec["description"]
        skill.dimension = dimension
        skill.content = content
        skill.files = files
        skill.claim_ids = [claim.id for claim in claims]
        skill.status = "compiled"
        skill.validation = {}
        # Bump the version only when the compiled output actually differs.
        # Comparing the SKILL.md hash is sufficient: it embeds every approved
        # principle, and a change in references/evals always follows from it.
        digest = sha256_text(content)
        previous = db.scalar(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill.id)
            .order_by(SkillVersion.version.desc())
            .limit(1)
        )
        if previous is None:
            skill.version = base_version if base_version else 1
        elif previous.content_hash == digest:
            skill.version = previous.version
        else:
            skill.version = max(base_version, previous.version) + 1
        db.add(skill)
        db.flush()
        _write_skill_files(skill, files)
        _snapshot_skill_version(db, skill, job.id, content, digest=digest)
        skill_ids.append(skill.id)
    job.result = {**(job.result or {}), "skills": skill_ids}
    db.add(job)
    db.commit()
    _audit(db, job.project_id, "skills.compile", {"skill_ids": skill_ids})
    db.commit()
    return {"skills": skill_ids}


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _frontmatter(content: str) -> dict[str, str]:
    """Parse the small YAML subset used by SKILL.md frontmatter.

    Only flat ``key: value`` pairs are required by the spec in practice; nested
    ``metadata`` maps are ignored here because they are informational.
    """
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end < 0:
        return {}
    block = content[3:end]
    values: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.startswith((" ", "\t", "#")):
            continue
        key, _, raw = line.partition(":")
        if not _:
            continue
        values[key.strip()] = raw.strip().strip("\"'")
    return values


def validate_skill(skill: Skill) -> dict[str, Any]:
    """Validate a Skill against the Agent Skills specification.

    Checks are grouped by severity: ``errors`` block export, ``warnings`` are
    advisory. Rules mirror https://agentskills.io/specification, including the
    requirement that ``name`` matches the containing directory (which the first
    implementation missed, so a Skill could pass here and fail in a real
    runtime).
    """
    errors: list[str] = []
    warnings: list[str] = []
    files = skill.files or {}
    content = str(files.get("SKILL.md") or skill.content or "")
    meta = _frontmatter(content)

    # --- frontmatter / identity ---
    if not content.startswith("---"):
        errors.append("SKILL.md 缺少 YAML frontmatter")
    if not NAME_RE.match(skill.name) or len(skill.name) > 64:
        errors.append("name 必须是小写字母/数字/单连字符，1-64 字符，且不能以连字符开头或结尾")
    if meta.get("name") and meta["name"] != skill.name:
        errors.append(
            f"frontmatter 的 name（{meta['name']}）必须与目录名/技能标识（{skill.name}）一致"
        )
    if not meta.get("description") and not skill.description:
        errors.append("description 必填：需要同时说明做什么和何时使用")
    description = meta.get("description") or skill.description
    if len(description) > 1024:
        errors.append(f"description 超过 1024 字符（当前 {len(description)}）")
    if len(description) < 40:
        warnings.append("description 过短，可能无法帮助运行时正确判断触发时机")
    compatibility = meta.get("compatibility", "")
    if compatibility and len(compatibility) > 500:
        errors.append("compatibility 超过 500 字符")

    # --- progressive disclosure ---
    if len(content.splitlines()) > 500:
        errors.append("SKILL.md 超过 500 行，违反渐进式披露建议")
    if estimate_tokens(content) > 5000:
        errors.append("SKILL.md 估算超过 5000 tokens")

    # --- referenced files must exist ---
    for relative, file_content in files.items():
        if not relative.endswith(".md") or relative == "SKILL.md":
            continue
        for match in re.finditer(r"\]\(([^)#]+\.md)\)", str(file_content)):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://")):
                continue
            if target not in files:
                warnings.append(f"{relative} 引用了不存在的文件：{target}")
    if "references/evidence.md" not in files:
        errors.append("缺少 references/evidence.md")

    # --- evals ---
    try:
        evals = json.loads(files.get("evals/evals.json") or "{}")
        cases = evals.get("cases") or []
        positive = sum(1 for case in cases if case.get("category") == "positive")
        negative = sum(1 for case in cases if case.get("category") in {"negative", "boundary"})
        if positive < 3:
            errors.append(f"评测用例至少需要 3 个正向用例（当前 {positive}）")
        if negative < 2:
            errors.append(f"评测用例至少需要 2 个负向/边界用例（当前 {negative}）")
    except (ValueError, TypeError):
        errors.append("evals/evals.json 不是合法 JSON")

    # --- safety / portability ---
    if contains_secret(content):
        errors.append("SKILL.md 中检测到可能的密钥或隐私模式")
    if re.search(r"[A-Za-z]:\\\\|/Users/|/home/", content):
        warnings.append("内容中可能出现绝对路径，请检查可移植性")
    if re.search(r"\b(TODO|TBD|FIXME)\b", content):
        warnings.append("内容包含 TODO/TBD/FIXME")

    skills_ref = shutil.which("skills-ref")
    if skills_ref:
        with tempfile.TemporaryDirectory(prefix="skills-ref-") as tmp:
            # The validator compares the directory name with `name`, so the temp
            # directory must be named after the skill.
            root = Path(tmp) / skill.name
            for relative, file_content in files.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(file_content), encoding="utf-8")
            try:
                result = subprocess.run(
                    [skills_ref, "validate", str(root)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    detail = (result.stdout + result.stderr).strip()[:1200]
                    errors.append(f"skills-ref validate 失败：{detail}")
            except (OSError, subprocess.TimeoutExpired) as exc:
                warnings.append(f"skills-ref 校验未完成：{exc}")
    else:
        warnings.append("未安装 skills-ref，已使用内置校验；安装命令：npm i -g skills-ref")
    return {"errors": errors, "warnings": warnings, "ok": not errors}


def _stage_validate(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    skill_ids = list((job.result or {}).get("skills") or [])
    skills = (
        db.scalars(select(Skill).where(Skill.id.in_(skill_ids))).all()
        if skill_ids
        else db.scalars(select(Skill).where(Skill.project_id == job.project_id)).all()
    )
    if not skills:
        raise PipelineError("没有可校验的 Skills")
    reports = {}
    for skill in skills:
        report = validate_skill(skill)
        skill.validation = {**(skill.validation or {}), "static": report}
        skill.status = "validated" if report["ok"] else "failed"
        db.add(skill)
        reports[skill.name] = report
    db.commit()
    job.result = {**(job.result or {}), "validation": reports}
    db.add(job)
    db.commit()
    if any(not report["ok"] for report in reports.values()):
        raise PipelineError("Skills 静态校验未通过；请查看校验报告")
    return {"validated": len(reports)}


def _stage_eval(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    from .judge import evaluate_cases
    from .models import Project

    skill_ids = list((job.result or {}).get("skills") or [])
    skills = (
        db.scalars(select(Skill).where(Skill.id.in_(skill_ids))).all()
        if skill_ids
        else db.scalars(select(Skill).where(Skill.project_id == job.project_id)).all()
    )
    results = {}
    project = db.get(Project, job.project_id)
    provider = db.get(Provider, project.provider_id) if project and project.provider_id else None
    run_llm = bool(job.config.get("run_llm_evals")) and provider is not None
    for skill in skills:
        try:
            payload = json.loads((skill.files or {}).get("evals/evals.json") or "{}")
        except ValueError:
            payload = {}
        raw_cases = payload.get("cases") or []
        cases = []
        for index, case in enumerate(raw_cases):
            case_data = {
                "case_id": case.get("id", f"case-{index}"),
                "category": str(case.get("category", "positive")),
                "prompt": str(case.get("prompt", "")),
                "expected": str(case.get("expected", "")),
            }
            cases.append(case_data)
            existing = db.scalar(
                select(EvalCase).where(
                    EvalCase.skill_id == skill.id,
                    EvalCase.prompt == case_data["prompt"],
                )
            )
            if not existing:
                db.add(
                    EvalCase(
                        project_id=job.project_id,
                        skill_id=skill.id,
                        category=case_data["category"],
                        prompt=case_data["prompt"],
                        expected=case_data["expected"],
                        meta={"case_id": case_data["case_id"]},
                    )
                )
                db.flush()

        if run_llm and provider:
            try:
                generator = get_adapter(provider)
                judge = get_adapter(provider)
                eval_payload = evaluate_cases(
                    skill_name=skill.name,
                    skill_content=skill.content,
                    skill_description=skill.description,
                    cases=cases,
                    generator=generator,
                    judge=judge,
                    generator_model=f"{provider.protocol}:{provider.model_id}",
                    judge_model=f"{provider.protocol}:{provider.model_id}",
                )
                metrics = eval_payload["metrics"]
                report = (
                    f"{skill.name} · LLM-as-judge {metrics['scored_cases']}/{metrics['cases']} 例 · "
                    f"overall {metrics['overall_score']} · pass {metrics['pass_rate']} · "
                    f"trigger {metrics['trigger_accuracy']}"
                )
                mode = "llm-judge"
            except Exception as exc:
                eval_payload = {
                    "mode": "llm-judge",
                    "cases": [],
                    "metrics": {"cases": len(cases), "scored_cases": 0, "errors": len(cases)},
                    "error": str(exc)[:1000],
                }
                report = f"{skill.name}: LLM-as-judge 失败：{str(exc)[:300]}"
                mode = "llm-judge-error"
        else:
            eval_payload = {
                "mode": "structural",
                "cases": [
                    {
                        "case_id": case["case_id"],
                        "category": case["category"],
                        "prompt": case["prompt"],
                        "status": "structural",
                        "output": "",
                    }
                    for case in cases
                ],
                "metrics": {"cases": len(cases), "scored_cases": 0, "errors": 0},
            }
            report = f"{skill.name}: {len(cases)} 个结构用例；配置模型后可运行 LLM-as-judge。"
            mode = "structural"

        eval_run = EvalRun(
            project_id=job.project_id,
            skill_id=skill.id,
            status="completed",
            results=eval_payload,
            report=report,
            finished_at=utcnow(),
        )
        db.add(eval_run)
        db.flush()
        skill.validation = {
            **(skill.validation or {}),
            "eval": {
                "run_id": eval_run.id,
                "cases": len(cases),
                "mode": mode,
                "metrics": eval_payload.get("metrics"),
            },
        }
        db.add(skill)
        results[skill.name] = {
            "cases": len(cases),
            "mode": mode,
            "metrics": eval_payload.get("metrics"),
        }
    db.commit()
    job.result = {**(job.result or {}), "eval": results}
    db.add(job)
    db.commit()
    return results


def _persona_markdown(project_name: str, claims: list[Claim]) -> str:
    lines = [f"# {project_name} · 人物档案", "", "> 本档案由经过人工审核的断言生成，不代表真实人物本人撰写或背书。", ""]
    for dimension in DIMENSION_LABELS:
        items = [claim for claim in claims if claim.dimension == dimension]
        if not items:
            continue
        lines.append(f"## {DIMENSION_LABELS[dimension]}")
        lines.extend(f"- {claim.statement}" for claim in items[:20])
        lines.append("")
    return "\n".join(lines)


def _stage_package(db: Session, job: Job, run: StageRun) -> dict[str, Any]:
    from .models import Project

    project = db.get(Project, job.project_id)
    if not project:
        raise PipelineError("项目不存在")
    skills = db.scalars(select(Skill).where(Skill.project_id == job.project_id)).all()
    if not skills:
        raise PipelineError("没有可导出的 Skills")
    invalid = [skill.name for skill in skills if skill.status not in {"validated", "exported"}]
    if invalid:
        raise PipelineError(f"以下 Skills 尚未通过校验：{', '.join(invalid)}")
    approved = _approved_claims(db, job.project_id)
    sources = db.scalars(select(Source).where(Source.project_id == job.project_id)).all()
    export = Export(project_id=job.project_id, status="running", path="", manifest={})
    db.add(export)
    db.flush()
    export_dir = settings.export_dir / job.project_id
    export_dir.mkdir(parents=True, exist_ok=True)
    zip_path = export_dir / f"{export.id}.zip"
    files: dict[str, str] = {}
    manifest_skills = []
    for skill in skills:
        for relative, content in (skill.files or {}).items():
            files[f"skills/{skill.name}/{relative}"] = str(content)
        manifest_skills.append(
            {
                "name": skill.name,
                "title": skill.title,
                "version": skill.version,
                "dimension": skill.dimension,
                "sha256": sha256_text((skill.files or {}).get("SKILL.md") or skill.content),
                "path": f"skills/{skill.name}/",
            }
        )
    files["manifest.json"] = json.dumps(
        {
            "package": f"{project.codename or project.name}-persona",
            "version": 1,
            "created_at": utcnow().isoformat(),
            "pipeline_version": PIPELINE_VERSION,
            "export_format": EXPORT_FORMAT,
            "format": "persona-package+agentskills",
            "person": {"name": project.name, "codename": project.codename, "purpose": project.purpose},
            "skills": manifest_skills,
            "sources": [
                {
                    "id": source.id,
                    "filename": source.original_name,
                    "sha256": source.sha256,
                    "status": source.status,
                    "license_note": source.license_note,
                    "size": source.size,
                }
                for source in sources
            ],
            "review": {
                "approved_claims": len(approved),
                "pending_claims": len(
                    db.scalars(
                        select(Claim).where(
                            Claim.project_id == job.project_id, Claim.status == "proposed"
                        )
                    ).all()
                ),
            },
            "limitations": [
                "本包是证据化蒸馏结果，不承诺完整复刻真实人物。",
                "人格与知识库是独立资产，需按 README 安装。",
                "技能运行时行为需在目标 Agent 平台实测。",
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    files["README.md"] = f"""# {project.codename or project.name} · 人物模型包

本包由蒸馏平台生成，包含可移植的 Agent Skills、人物档案、知识索引、证据与评测材料。

## 安装 Skills

将 `skills/` 下的每个目录复制到目标运行时的 skills 目录，例如：

- 通用：`.agents/skills/<name>/`
- Claude Code：`~/.claude/skills/<name>/` 或项目 `.claude/skills/<name>/`
- Cursor：`.cursor/skills/<name>/` 或 `.agents/skills/<name>/`
- Gemini CLI：`~/.gemini/skills/<name>/` 或 `.agents/skills/<name>/`
- Qoder：`~/.qoder/skills/<name>/` 或项目 `.qoder/skills/<name>/`
- GitHub Copilot：`.github/skills/<name>/`

不同版本、不同平台的加载路径可能变化，请在目标版本中实际验证。`skills-ref validate <dir>` 可用于结构校验。

## 人物与知识

`persona/`、`decision-model/`、`knowledge/` 是独立资产，不会被 SKILL.md 自动加载。请按目标平台的规则手动导入，或使用随包的 `provenance/` 材料做人工配置。

## 声明

本包由 AI 辅助生成，不代表真实人物本人撰写、认可或授权发言。请仅在有合法授权的前提下使用。
"""
    files["persona/persona.md"] = _persona_markdown(project.codename or project.name, approved)
    files["persona/communication-style.md"] = _persona_markdown(
        "表达风格", [claim for claim in approved if claim.dimension == "style"]
    )
    files["persona/interaction-boundaries.md"] = _persona_markdown(
        "互动边界", [claim for claim in approved if claim.dimension == "boundary"]
    )
    files["decision-model/decision-rules.md"] = _persona_markdown(
        "决策规则", [claim for claim in approved if claim.dimension == "decision"]
    )
    files["knowledge/index.md"] = _persona_markdown(
        "知识索引", [claim for claim in approved if claim.dimension == "knowledge"]
    ) + "\n\n> 长篇事实与案例应在目标平台中作为 RAG 知识库导入；不要塞进 SKILL.md。\n"
    files["provenance/source-manifest.json"] = json.dumps(
        [
            {
                "id": source.id,
                "filename": source.original_name,
                "sha256": source.sha256,
                "mime": source.mime,
                "size": source.size,
                "status": source.status,
                "license_note": source.license_note,
                "consent_scope": source.consent_scope,
            }
            for source in sources
        ],
        ensure_ascii=False,
        indent=2,
    )
    evidence_lines = ["# 证据摘要", ""]
    for claim in approved:
        rows = db.scalars(select(EvidenceItem).where(EvidenceItem.claim_id == claim.id)).all()
        evidence_lines.append(f"## {claim.statement}")
        for evidence in rows:
            source = db.get(Source, evidence.source_id)
            evidence_lines.append(
                f"- {source.original_name if source else evidence.source_id} · {evidence.page or evidence.heading or '—'}：{evidence.quote[:240]}"
            )
        if not rows:
            evidence_lines.append("- 未定位到证据（模型推断，需人工复核）")
        evidence_lines.append("")
    files["provenance/evidence-summary.md"] = "\n".join(evidence_lines)
    files["provenance/review-log.json"] = json.dumps(
        [
            {
                "claim_id": claim.id,
                "statement": claim.statement,
                "status": claim.status,
                "evidence_grade": claim.evidence_grade,
                "review_reason": claim.review_reason,
            }
            for claim in db.scalars(select(Claim).where(Claim.project_id == job.project_id)).all()
        ],
        ensure_ascii=False,
        indent=2,
    )
    evaluations = []
    for skill in skills:
        runs = db.scalars(select(EvalRun).where(EvalRun.skill_id == skill.id)).all()
        evaluations.append(
            {
                "skill": skill.name,
                "static": (skill.validation or {}).get("static"),
                "runs": [
                    {"id": run.id, "status": run.status, "results": run.results, "report": run.report}
                    for run in runs
                ],
            }
        )
    files["evaluations/benchmark.json"] = json.dumps(evaluations, ensure_ascii=False, indent=2)
    files["compatibility/platform-notes.md"] = """# 兼容性说明

| 平台 | 建议目录 | 验证状态 |
| --- | --- | --- |
| 通用 | `.agents/skills/<name>/` | 结构校验通过；运行时需实测 |
| Claude Code | `~/.claude/skills/<name>/` 或项目 `.claude/skills/<name>/` | 需在目标版本实测 |
| Codex | 按官方 Skills 文档 | 需在目标版本实测 |
| Cursor | `.cursor/skills/<name>/` 或 `.agents/skills/<name>/` | 需在目标版本实测 |
| Gemini CLI | `~/.gemini/skills/<name>/` 或 `.agents/skills/<name>/` | 需在目标版本实测 |
| GitHub Copilot | `.github/skills/<name>/` | 需在目标版本实测 |
| Qoder | `~/.qoder/skills/<name>/` 或项目 `.qoder/skills/<name>/` | 需在目标版本实测 |

格式兼容不等于行为兼容。安装后请验证：技能被发现、能被正确触发、能读取 references、失败时遵守边界。
"""
    with tempfile.TemporaryDirectory(prefix="distill-export-") as tmp:
        root = Path(tmp) / "package"
        for relative, content in files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    relative = path.relative_to(root).as_posix()
                    info = zipfile.ZipInfo(relative, date_time=(2020, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, path.read_bytes())
    export.status = "completed"
    export.path = str(zip_path)
    export.manifest = json.loads(files["manifest.json"])
    for skill in skills:
        skill.status = "exported"
        db.add(skill)
    db.add(export)
    db.commit()
    _audit(db, job.project_id, "export.created", {"export_id": export.id, "path": str(zip_path)})
    db.commit()
    job.result = {**(job.result or {}), "export_id": export.id, "export_path": str(zip_path)}
    db.add(job)
    db.commit()
    return {"export_id": export.id, "path": str(zip_path)}


STAGE_FUNCS: dict[str, Callable[[Session, Job, StageRun], dict[str, Any]]] = {
    "s01_intake": _stage_intake,
    "s02_ingest": _stage_ingest,
    "s03_parse": _stage_parse,
    "s04_normalize": _stage_normalize,
    "s05_chunk": _stage_chunk,
    "s06_corpus_map": _stage_corpus_map,
    "s07_extract": _stage_extract,
    "s08_ground": _stage_ground,
    "s09_conflicts": _stage_conflicts,
    "s10_consolidate": _stage_consolidate,
    "s11_compose": _stage_compose,
    "s12_compile": _stage_compile,
    "s13_validate": _stage_validate,
    "s14_eval": _stage_eval,
    "s15_package": _stage_package,
}
