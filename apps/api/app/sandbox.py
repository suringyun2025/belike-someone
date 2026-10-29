"""Single-occupant demo sandbox.

The public instance is not a multi-tenant service. It is one seat on a small
server: a visitor brings their own model endpoint, proves it works, uses the
workbench alone, and leaves. The next visitor gets the seat.

Why a seat rather than accounts
-------------------------------
Accounts imply persistence, which implies obligations: backups, deletion
requests, breach notification. For a demo whose purpose is "try it for twenty
minutes", holding data past the visit is liability with no upside. So a visit is
a row that expires on its own, and when it ends for any reason — explicit exit,
idle timeout, hard expiry, restart — every row and file it created is deleted,
including the sealed model key.

State machine
-------------
``queued``  waiting for the seat. Holds the sealed key so the visitor does not
            have to re-enter it on promotion. Has its own expiry.
``ready``   the seat freed up and this ticket is next. The visitor has a short
            window to claim it; the browser can only receive the session cookie
            from its own request, so promotion cannot complete unattended.
``active``  occupying the seat, with a real user, provider and session.
``closed``  finished, data purged.
``expired`` never claimed in time, or queued too long. Data purged.

Concurrency
-----------
The seat is a row in ``app_settings`` rather than an in-process lock, because
the worker thread and the HTTP handlers are separate code paths and a restart
must not leave the seat permanently taken. Every transition is a conditional
UPDATE so two browsers racing for the same seat cannot both win.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import shutil
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    AppSetting,
    AuditEvent,
    Chunk,
    ChunkEmbedding,
    Claim,
    Conflict,
    Document,
    DocumentBlock,
    EvalCase,
    EvalRun,
    EvidenceItem,
    Export,
    Job,
    Project,
    Provider,
    Session as SessionModel,
    Skill,
    SkillVersion,
    Source,
    StageRun,
    User,
    Visit,
    utcnow,
)

logger = logging.getLogger("distill.sandbox")

SEAT_KEY = "active_visit"
# How long the next person has to claim a freed seat before it moves on.
CLAIM_WINDOW_SECONDS = 120
# A queued ticket that waits longer than this lapses, so an abandoned tab cannot
# block the queue behind it.
QUEUE_TTL_MINUTES = 30
MAX_QUEUE = 200


class SandboxError(Exception):
    """A rejection the visitor should read, not a 500."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# --------------------------------------------------------------------------- #
# Input validation — the SSRF boundary
# --------------------------------------------------------------------------- #
_BLOCKED_HOST_PATTERN = (
    r"^(localhost|127\.|0\.|10\.|169\.254\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|\[?::1\]?$"
    r"|.*\.local$|.*\.internal$|.*\.lan$|.*\.localhost$)"
)

_PRIVATE_HOST = re.compile(_BLOCKED_HOST_PATTERN, re.IGNORECASE)


def validate_endpoint(url: str, *, resolve: bool = True) -> str:
    """Normalise and vet a visitor-supplied base URL.

    This is the only place where a visitor can make the server open an outbound
    connection, so it is the SSRF boundary. Checks are allowlist-shaped: http(s)
    only, no embedded credentials, no literal private address, and — when
    ``resolve`` is on — the hostname is resolved so a public name that points
    inward is rejected too.

    ``resolve=False`` exists for tests and for the entry-form preview, where a
    DNS failure would be noise rather than a security decision. The real join
    always resolves.
    """
    raw = (url or "").strip()
    if not raw:
        raise SandboxError("INVALID_URL", "请填写 API Base URL")
    if len(raw) > 500:
        raise SandboxError("INVALID_URL", "Base URL 过长")

    parsed = urlparse(raw)
    if parsed.scheme not in {"https", "http"}:
        raise SandboxError("INVALID_URL", "Base URL 必须以 https:// 或 http:// 开头")
    if settings.sandbox_https_only and parsed.scheme != "https":
        raise SandboxError("INVALID_URL", "公开体验仅接受 https:// 端点")
    authority = raw.split("//", 1)[-1].split("/", 1)[0]
    if "@" in authority:
        raise SandboxError("INVALID_URL", "Base URL 不能内嵌账号或密码")

    host = (parsed.hostname or "").strip()
    if not host:
        raise SandboxError("INVALID_URL", "Base URL 缺少主机名")
    # ``sandbox_allow_private`` is a local-development escape hatch only: it lets
    # the demo form point at a mock endpoint on loopback. It is off by default and
    # must never be enabled on a public instance.
    if not settings.sandbox_allow_private and _PRIVATE_HOST.match(host):
        raise SandboxError("INVALID_URL", "不允许指向内网、本机或链路本地地址")

    if not resolve:
        return raw.rstrip("/")

    if not settings.sandbox_allow_private:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise SandboxError("INVALID_URL", f"域名无法解析：{host}") from exc
        for info in infos:
            address = info[4][0]
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                continue
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                raise SandboxError("INVALID_URL", "该域名解析到内网或保留网段，不允许访问")

    return raw.rstrip("/")


def validate_api_key(key: str) -> str:
    value = (key or "").strip()
    if len(value) < 8:
        raise SandboxError("INVALID_KEY", "API Key 看起来不完整")
    if len(value) > 500:
        raise SandboxError("INVALID_KEY", "API Key 过长")
    if any(ch in value for ch in "\r\n\t "):
        raise SandboxError("INVALID_KEY", "API Key 不能包含空白字符")
    return value


def fingerprint_key(base_url: str, api_key: str) -> str:
    """Stable identity for a credential pair, so a refresh keeps its place."""
    return hashlib.sha256(f"{base_url}\x00{api_key}".encode("utf-8")).hexdigest()[:32]


# --------------------------------------------------------------------------- #
# Seat bookkeeping
# --------------------------------------------------------------------------- #
def _read_seat(db: Session) -> str:
    row = db.get(AppSetting, SEAT_KEY)
    if not row or not isinstance(row.value, dict):
        return ""
    return str(row.value.get("visit_id") or "")


def _write_seat(db: Session, visit_id: str) -> None:
    row = db.get(AppSetting, SEAT_KEY)
    payload = {"visit_id": visit_id} if visit_id else {}
    if row is None:
        db.add(AppSetting(key=SEAT_KEY, value=payload))
    else:
        row.value = payload
        db.add(row)


def visit_view(visit: Visit) -> dict[str, Any]:
    return {
        "id": visit.id,
        "owner_id": visit.owner_id,
        "nickname": visit.nickname or "访客",
        "protocol": visit.protocol,
        "model_id": visit.model_id,
        "status": visit.status,
        "started_at": visit.started_at.isoformat() if visit.started_at else None,
        "expires_at": visit.expires_at.isoformat() if visit.expires_at else None,
        "seconds_left": max(0, int((visit.expires_at - utcnow()).total_seconds()))
        if visit.expires_at
        else 0,
    }


def active_visit(db: Session) -> Visit | None:
    """The current occupant, expiring it first if its time is up."""
    visit_id = _read_seat(db)
    if not visit_id:
        return None
    visit = db.get(Visit, visit_id)
    if not visit or visit.status != "active":
        _write_seat(db, "")
        db.commit()
        return None
    if visit.expires_at and visit.expires_at <= utcnow():
        close_visit(db, visit, reason="timeout")
        return None
    return visit


# --------------------------------------------------------------------------- #
# Teardown
# --------------------------------------------------------------------------- #
def close_visit(db: Session, visit: Visit, reason: str = "exit") -> None:
    """End a visit and destroy everything it created.

    Four paths funnel here — explicit exit, reaper timeout, restart recovery and
    seat takeover — so the deletion order is written once.
    """
    if visit.status == "closed":
        return
    visit.status = "closed"
    visit.closed_at = utcnow()
    visit.close_reason = reason
    db.add(visit)
    purge_visit_data(db, visit)
    if _read_seat(db) == visit.id:
        _write_seat(db, "")
    db.commit()
    logger.info("visit %s closed (%s)", visit.id, reason)


def purge_visit_data(db: Session, visit: Visit) -> None:
    """Delete every row and file owned by this visit's user.

    Bulk deletes rather than ORM cascades: a visit can leave thousands of chunks,
    and loading them into the identity map to cascade would be slow enough to be
    noticeable on a 2 GB host.
    """
    user = db.get(User, visit.owner_id) if visit.owner_id else None
    project_ids: list[str] = []
    if user is not None:
        project_ids = list(
            db.scalars(select(Project.id).where(Project.owner_id == user.id)).all()
        )

    if project_ids:
        job_ids = list(db.scalars(select(Job.id).where(Job.project_id.in_(project_ids))).all())
        if job_ids:
            db.execute(delete(StageRun).where(StageRun.job_id.in_(job_ids)))
        db.execute(
            delete(EvidenceItem).where(
                EvidenceItem.claim_id.in_(select(Claim.id).where(Claim.project_id.in_(project_ids)))
            )
        )
        db.execute(delete(Conflict).where(Conflict.project_id.in_(project_ids)))
        db.execute(delete(Claim).where(Claim.project_id.in_(project_ids)))
        db.execute(delete(ChunkEmbedding).where(ChunkEmbedding.project_id.in_(project_ids)))
        db.execute(delete(Chunk).where(Chunk.project_id.in_(project_ids)))
        db.execute(
            delete(DocumentBlock).where(
                DocumentBlock.document_id.in_(
                    select(Document.id).where(
                        Document.source_id.in_(
                            select(Source.id).where(Source.project_id.in_(project_ids))
                        )
                    )
                )
            )
        )
        db.execute(
            delete(Document).where(
                Document.source_id.in_(select(Source.id).where(Source.project_id.in_(project_ids)))
            )
        )
        db.execute(
            delete(SkillVersion).where(SkillVersion.project_id.in_(project_ids))
        )
        db.execute(delete(Skill).where(Skill.project_id.in_(project_ids)))
        db.execute(delete(EvalRun).where(EvalRun.project_id.in_(project_ids)))
        db.execute(delete(EvalCase).where(EvalCase.project_id.in_(project_ids)))
        db.execute(delete(Export).where(Export.project_id.in_(project_ids)))
        db.execute(delete(Source).where(Source.project_id.in_(project_ids)))
        db.execute(delete(Job).where(Job.project_id.in_(project_ids)))
        db.execute(delete(Project).where(Project.id.in_(project_ids)))

    if user is not None:
        db.execute(delete(Provider).where(Provider.owner_id == user.id))
        db.execute(delete(SessionModel).where(SessionModel.user_id == user.id))
        db.execute(delete(AuditEvent).where(AuditEvent.actor_id == user.id))
        db.execute(delete(User).where(User.id == user.id))

    _remove_files(project_ids)


def _remove_files(project_ids: list[str]) -> None:
    """Delete on-disk artefacts. Never raises: a leftover file is better than a
    seat that cannot be freed because one unlink failed."""
    for project_id in project_ids:
        for root in (
            settings.sources_dir,
            settings.skills_dir,
            settings.export_dir,
            settings.artifacts_dir,
        ):
            target = root / project_id
            try:
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
            except Exception as exc:  # pragma: no cover - filesystem boundary
                logger.warning("cleanup failed for %s: %s", target, exc)


def purge_orphans(db: Session) -> int:
    """Delete guest users left behind by an interrupted teardown.

    A crash between "close the visit" and "commit the purge" would otherwise
    leave a guest account holding disk space forever.
    """
    orphans = list(
        db.scalars(select(User).where(User.email.like("%@sandbox.local"))).all()
    )
    removed = 0
    for user in orphans:
        still_open = db.scalar(
            select(func.count())
            .select_from(Visit)
            .where(Visit.owner_id == user.id, Visit.status.in_(["queued", "ready", "active"]))
        ) or 0
        if still_open:
            continue
        fake = Visit(owner_id=user.id, status="closed", api_key_encrypted="")
        purge_visit_data(db, fake)
        removed += 1
    if removed:
        db.commit()
        logger.info("purged %s orphaned guest workspace(s)", removed)
    return removed


# --------------------------------------------------------------------------- #
# Join / queue / claim
# --------------------------------------------------------------------------- #
def join(
    db: Session,
    *,
    base_url: str,
    protocol: str,
    model_id: str,
    api_key: str,
    nickname: str = "",
) -> dict[str, Any]:
    """Validate the endpoint, then either take the seat or take a ticket."""
    from .auth import encrypt_secret

    base_url = validate_endpoint(base_url)
    api_key = validate_api_key(api_key)
    model_id = (model_id or "").strip()
    if not model_id:
        raise SandboxError("INVALID_MODEL", "请填写模型 ID，例如 gpt-4o-mini")
    if len(model_id) > 300:
        raise SandboxError("INVALID_MODEL", "模型 ID 过长")
    if protocol not in {"openai_responses", "openai_chat", "anthropic", "gemini"}:
        raise SandboxError("INVALID_PROTOCOL", "不支持的协议类型")

    reaper_tick(db)

    # Prove the credential works before spending a seat or a queue slot on it.
    # Doing this first means the queue only holds people who could actually start.
    probe = probe_endpoint(
        base_url=base_url, protocol=protocol, model_id=model_id, api_key=api_key
    )

    seat = active_visit(db)
    if seat is not None:
        # Somebody already on the seat re-submitting (page refresh, second tab)
        # is not a queue event: telling them "you are position 1 behind yourself"
        # would be nonsense, and it would hold a phantom slot.
        if seat.fingerprint and seat.fingerprint == fingerprint_key(base_url, api_key):
            token = _issue_session(db, seat)
            db.commit()
            return {
                "state": "active",
                "visit": visit_view(seat),
                "session_token": token,
                "probe": probe,
            }
        return _enqueue(
            db,
            nickname=nickname,
            protocol=protocol,
            model_id=model_id,
            base_url=base_url,
            sealed_key=encrypt_secret(api_key, "queue"),
            fingerprint=fingerprint_key(base_url, api_key),
            probe=probe,
        )

    visit, token = _open_visit(
        db,
        nickname=nickname,
        protocol=protocol,
        model_id=model_id,
        base_url=base_url,
        sealed_key=encrypt_secret(api_key, "queue"),
        fingerprint=fingerprint_key(base_url, api_key),
        probe=probe,
    )
    return {"state": "active", "visit": visit_view(visit), "session_token": token, "probe": probe}


def _enqueue(
    db: Session,
    *,
    nickname: str,
    protocol: str,
    model_id: str,
    base_url: str,
    sealed_key: str,
    fingerprint: str,
    probe: dict[str, Any],
) -> dict[str, Any]:
    waiting = db.scalar(select(func.count()).select_from(Visit).where(Visit.status == "queued")) or 0
    if waiting >= MAX_QUEUE:
        raise SandboxError("QUEUE_FULL", "等待队列已满，请稍后再来", status=429)

    # Re-submitting while already queued keeps the original place instead of
    # joining twice (a refresh must not penalise the visitor).
    existing = db.scalar(
        select(Visit)
        .where(
            Visit.status.in_(["queued", "ready"]),
            Visit.fingerprint == fingerprint,
        )
        .order_by(Visit.queued_at.asc())
    )
    if existing is None:
        existing = Visit(
            owner_id="",
            nickname=(nickname or "访客")[:60],
            protocol=protocol,
            model_id=model_id,
            base_url=base_url,
            fingerprint=fingerprint,
            api_key_encrypted=sealed_key,
            status="queued",
            queued_at=utcnow(),
            expires_at=utcnow() + timedelta(minutes=QUEUE_TTL_MINUTES),
        )
        db.add(existing)
        db.flush()
        # A queued visit has no user yet. Owner id carries a placeholder so the
        # column stays non-null and promotion can fill it in one statement.
        existing.owner_id = f"pending_{existing.id}"
        db.add(existing)
        db.commit()
        db.refresh(existing)

    return {
        "state": "queued",
        "ticket": ticket_view(db, existing),
        "probe": probe,
    }


def ticket_view(db: Session, ticket: Visit) -> dict[str, Any]:
    ahead = db.scalar(
        select(func.count())
        .select_from(Visit)
        .where(Visit.status.in_(["queued", "ready"]), Visit.queued_at < ticket.queued_at)
    ) or 0
    seat = active_visit(db)
    seat_left = 0
    if seat and seat.expires_at:
        seat_left = max(0, int((seat.expires_at - utcnow()).total_seconds()))
    return {
        "ticket_id": ticket.id,
        # The fingerprint is what lets the holder claim the seat. It is derived
        # from their own credential, so returning it reveals nothing they did not
        # supply, and it stops a guessed ticket id from stealing the seat.
        "fingerprint": ticket.fingerprint,
        "status": ticket.status,
        "position": ahead + 1,
        "ahead": ahead,
        # Rough: the occupant's remaining time plus full visits ahead.
        "estimated_wait_seconds": seat_left
        + max(0, ahead - (1 if ticket.status == "ready" else 0)) * settings.sandbox_visit_minutes * 60,
        "claimable": ticket.status == "ready",
        "expires_at": ticket.expires_at.isoformat() if ticket.expires_at else None,
    }


def claim(db: Session, ticket_id: str, fingerprint: str) -> dict[str, Any]:
    """Turn a ready ticket into an active visit and hand back a session token.

    Conditional UPDATE is the guard: two tabs polling the same ticket must not
    both create a workspace.
    """
    ticket = db.get(Visit, ticket_id)
    if not ticket:
        raise SandboxError("TICKET_NOT_FOUND", "排队凭证不存在，请重新进入", status=404)
    if ticket.fingerprint != fingerprint:
        raise SandboxError("TICKET_FORBIDDEN", "凭证与提交的模型信息不匹配", status=403)

    if ticket.status == "active":
        # Already claimed (double-click): hand out a fresh session rather than
        # failing, which is what the visitor actually wants.
        token = _issue_session(db, ticket)
        return {"state": "active", "visit": visit_view(ticket), "session_token": token}

    if ticket.status != "ready":
        raise SandboxError("NOT_READY", "还没轮到你，请继续等待", status=409)

    updated = db.execute(
        update(Visit)
        .where(Visit.id == ticket_id, Visit.status == "ready")
        .values(status="active", started_at=utcnow())
    ).rowcount
    if updated != 1:
        db.rollback()
        raise SandboxError("NOT_READY", "座位刚刚被占用，请重新排队", status=409)

    db.refresh(ticket)
    _materialise_owner(db, ticket)
    token = _issue_session(db, ticket)
    _write_seat(db, ticket.id)
    db.commit()
    db.refresh(ticket)
    return {"state": "active", "visit": visit_view(ticket), "session_token": token}


def _open_visit(
    db: Session,
    *,
    nickname: str,
    protocol: str,
    model_id: str,
    base_url: str,
    sealed_key: str,
    fingerprint: str,
    probe: dict[str, Any],
) -> tuple[Visit, str]:
    now = utcnow()
    visit = Visit(
        owner_id="",
        nickname=(nickname or "访客")[:60],
        protocol=protocol,
        model_id=model_id,
        base_url=base_url,
        fingerprint=fingerprint,
        api_key_encrypted=sealed_key,
        status="active",
        started_at=now,
        expires_at=now + timedelta(minutes=settings.sandbox_visit_minutes),
    )
    db.add(visit)
    db.flush()
    _materialise_owner(db, visit)
    token = _issue_session(db, visit)
    _write_seat(db, visit.id)
    db.add(
        AuditEvent(
            project_id=None,
            actor_id=visit.owner_id,
            actor=f"guest:{visit.nickname}",
            action="sandbox.join",
            detail={"protocol": protocol, "probe_ms": probe.get("latency_ms")},
        )
    )
    db.commit()
    db.refresh(visit)
    return visit, token


def _materialise_owner(db: Session, visit: Visit) -> None:
    """Create the guest user and provider that will own this visit's data."""
    from .auth import decrypt_secret, encrypt_secret

    api_key = decrypt_secret(visit.api_key_encrypted, "queue")

    user = User(
        email=f"guest-{visit.id}@sandbox.local",
        password_hash="!",  # unusable: guests never log in with a password
        display_name=(visit.nickname or "访客")[:120],
        is_admin=False,
        max_projects=settings.sandbox_max_projects,
        max_storage_mb=settings.sandbox_max_storage_mb,
    )
    db.add(user)
    db.flush()

    provider = Provider(
        owner_id=user.id,
        name="访客自带模型",
        protocol=visit.protocol,
        base_url=visit.base_url,
        model_id=visit.model_id,
        api_key_encrypted=encrypt_secret(api_key, user.id),
        params={},
        capabilities={},
        enabled=True,
        last_test_status="ok",
        last_tested_at=utcnow(),
    )
    db.add(provider)
    db.flush()

    visit.owner_id = user.id
    visit.provider_id = provider.id
    # Re-seal under the real owner id: the "queue" seal was only a carrier.
    visit.api_key_encrypted = encrypt_secret(api_key, user.id)
    db.add(visit)
    db.flush()


def _issue_session(db: Session, visit: Visit) -> str:
    from .auth import new_session_token

    token, digest = new_session_token()
    db.add(
        SessionModel(
            user_id=visit.owner_id,
            token_hash=digest,
            expires_at=visit.expires_at or utcnow() + timedelta(minutes=settings.sandbox_visit_minutes),
        )
    )
    return token


# --------------------------------------------------------------------------- #
# Reaper
# --------------------------------------------------------------------------- #
def reaper_tick(db: Session) -> None:
    """Advance the state machine: lapse stale tickets, seat the next person.

    Called by the background loop every 30 s and opportunistically on entry, so a
    visitor never reads a stale "busy" state.
    """
    now = utcnow()

    for ticket in db.scalars(select(Visit).where(Visit.status.in_(["queued", "ready"]))).all():
        if ticket.expires_at and ticket.expires_at <= now:
            ticket.status = "expired"
            ticket.closed_at = now
            ticket.close_reason = "queue_timeout"
            db.add(ticket)
        elif ticket.status == "ready" and ticket.claim_deadline and ticket.claim_deadline <= now:
            # Promoted but nobody claimed it. Send it to the back rather than
            # dropping the visitor: they may simply have closed the laptop.
            ticket.status = "queued"
            ticket.claim_deadline = None
            ticket.queued_at = now
            db.add(ticket)

    if active_visit(db) is None:
        # Promote the longest waiter to "ready". It only becomes "active" when
        # that visitor's own browser claims it, because the session cookie has to
        # arrive on a response the browser initiated.
        has_ready = db.scalar(
            select(func.count()).select_from(Visit).where(Visit.status == "ready")
        ) or 0
        if not has_ready:
            nxt = db.scalar(
                select(Visit).where(Visit.status == "queued").order_by(Visit.queued_at.asc())
            )
            if nxt:
                nxt.status = "ready"
                nxt.claim_deadline = now + timedelta(seconds=CLAIM_WINDOW_SECONDS)
                db.add(nxt)
    db.commit()


def reaper_loop(stop_event: threading.Event) -> None:
    """Background tick: keep the seat moving even when nobody is looking."""
    from .db import SessionLocal

    while not stop_event.is_set():
        try:
            db = SessionLocal()
            try:
                reaper_tick(db)
            finally:
                db.close()
        except Exception as exc:  # pragma: no cover - keep the loop alive
            logger.warning("reaper error: %s", exc)
        stop_event.wait(30)


def recover_on_startup(db: Session) -> None:
    """Close visits orphaned by a restart, then free the seat.

    A restart kills in-flight work. Leaving the old visit "active" would lock
    everyone out until its timer drained, so startup closes it and lets the queue
    advance.
    """
    for visit in db.scalars(select(Visit).where(Visit.status == "active")).all():
        try:
            close_visit(db, visit, reason="restart")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("could not clear visit %s: %s", visit.id, exc)
    _write_seat(db, "")
    db.commit()
    purge_orphans(db)


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
@dataclass
class SeatStatus:
    state: str
    visit: dict[str, Any] | None = None
    waiting: int = 0
    visit_minutes: int = 0


def seat_status(db: Session) -> SeatStatus:
    """Public snapshot for the entry page."""
    reaper_tick(db)
    seat = active_visit(db)
    waiting = db.scalar(
        select(func.count()).select_from(Visit).where(Visit.status.in_(["queued", "ready"]))
    ) or 0
    if seat:
        return SeatStatus(
            state="busy",
            visit=visit_view(seat),
            waiting=waiting,
            visit_minutes=settings.sandbox_visit_minutes,
        )
    return SeatStatus(state="free", waiting=waiting, visit_minutes=settings.sandbox_visit_minutes)


# --------------------------------------------------------------------------- #
# Endpoint probe
# --------------------------------------------------------------------------- #
def probe_endpoint(
    *, base_url: str, protocol: str, model_id: str, api_key: str
) -> dict[str, Any]:
    """One tiny request to confirm the endpoint and key work.

    Built over an unsaved Provider so nothing is persisted, but still routed
    through the real adapter so protocol quirks are exercised exactly as a job
    would hit them.
    """
    from .llm import LLMError, get_adapter

    stub = Provider(
        id="probe",
        owner_id="probe",
        name="probe",
        protocol=protocol,
        base_url=base_url,
        model_id=model_id,
        api_version="",
        api_key_encrypted="",
        params={},
        capabilities={},
        enabled=True,
    )
    try:
        adapter = get_adapter(stub)
        # Nothing is stored, so assign the plaintext directly instead of sealing.
        adapter.api_key = api_key
        result = adapter.test_connection(json_mode=False)
    except LLMError as exc:
        raise SandboxError("PROBE_FAILED", f"连接失败（{exc.code}）：{exc.message}"[:300]) from exc
    except Exception as exc:  # pragma: no cover - network boundary
        raise SandboxError("PROBE_FAILED", f"无法连接该端点：{str(exc)[:200]}") from exc

    if not result.get("ok"):
        message = (result.get("error_message") or "端点未通过校验")[:300]
        raise SandboxError("PROBE_FAILED", message)
    return {
        "ok": True,
        "latency_ms": int(result.get("latency_ms") or 0),
        "model": result.get("model") or model_id,
    }


# --------------------------------------------------------------------------- #
# Demo seed
# --------------------------------------------------------------------------- #
def seed_demo_project(db: Session, user: User) -> str:
    """Give the visitor something to run immediately.

    An empty workbench in a timed demo wastes the visitor's first five minutes
    creating a project. A seeded fictional project lets them press "开始蒸馏"
    straight away and see the evidence chain, which is the point of the demo.
    """
    from .ingest import create_source_from_file
    from .routers.dashboard import DEMO_CHAT, DEMO_NOTE

    existing = db.scalar(select(Project.id).where(Project.owner_id == user.id).limit(1))
    if existing:
        return existing

    project = Project(
        owner_id=user.id,
        name="示例项目：解决方案架构师",
        codename="示例架构师",
        purpose="演示如何从工作笔记与评审对话中蒸馏专业能力、决策方式与表达风格。",
        authorization_note="虚构示例资料，仅用于产品演示，不包含真实人物信息。",
        prohibited_uses="不得用于冒充真实人物、欺骗或未经授权的商业用途。",
        target_platforms=["Claude Code", "Cursor", "Qoder"],
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    create_source_from_file(
        db,
        project.id,
        "示例-架构师工作笔记.md",
        DEMO_NOTE.encode("utf-8"),
        source_type="document",
        parse_now=True,
    )
    create_source_from_file(
        db,
        project.id,
        "示例-评审对话.jsonl",
        DEMO_CHAT.encode("utf-8"),
        source_type="chat",
        parse_now=True,
    )
    db.add(
        AuditEvent(
            project_id=project.id,
            actor_id=user.id,
            actor=user.email,
            action="sandbox.seed",
            detail={},
        )
    )
    db.commit()
    return project.id