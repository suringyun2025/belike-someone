"""Public demo entry endpoints.

Three calls make up the whole visitor lifecycle:

``GET  /sandbox``         public state — is the seat free, who is on it, how long
``POST /sandbox/join``    submit credentials; either take the seat or take a ticket
``POST /sandbox/claim``   (polled) claim the seat once the ticket is promoted
``POST /sandbox/exit``    end early and release the seat immediately
``GET  /sandbox/me``      what the current session is allowed to do

The session cookie can only be set on a response the browser itself initiated,
which is why promotion is a two-step handshake instead of a push: the ticket
becomes ``ready`` and the polling browser claims it, receiving the cookie.

Everything here runs before the multiuser gate; the seat endpoints are public by
design, the rest of the app is not.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import CSRF_HEADER, SESSION_COOKIE, SESSION_MAX_AGE, client_ip, current_user
from ..models import User, Visit
from ..rate_limit import join_limiter, api_limiter
from ..sandbox import (
    SandboxError,
    active_visit,
    claim,
    close_visit,
    fingerprint_key,
    join,
    seed_demo_project,
    seat_status,
    ticket_view,
    validate_api_key,
    validate_endpoint,
)
from ..schemas import (
    SandboxClaimRequest,
    SandboxJoinRequest,
    SandboxJoinOut,
    SandboxStateOut,
)

logger = logging.getLogger("distill.sandbox.api")

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


def _require_mode() -> None:
    """Reject sandbox calls on a build that is not a demo instance."""
    if not settings.sandbox:
        raise HTTPException(status_code=404, detail="该实例未开启体验模式")


def _set_session(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,  # type: ignore[arg-type]
        domain=settings.cookie_domain or None,
        path="/",
    )
    # Expose a short CSRF token the SPA echoes on state-changing requests.
    response.headers[CSRF_HEADER] = token[:16]


def _seed_for(visit: dict | None) -> None:
    """Give a newly seated visitor the demo project.

    Every path that grants the seat must do this, or a visitor who queued arrives
    at an empty workbench and burns their turn creating a project — the opposite
    of what a timed demo should spend it on.

    Runs after the response is built, in its own session: seeding parses two
    documents, and holding the request's transaction open for that would delay
    the redirect for no benefit.
    """
    owner_id = (visit or {}).get("owner_id")
    if not owner_id:
        return
    from ..db import SessionLocal

    own = SessionLocal()
    try:
        user = own.get(User, owner_id)
        if user is not None:
            seed_demo_project(own, user)
    except Exception as exc:  # pragma: no cover - demo seed is best-effort
        logger.warning("demo seed failed: %s", exc)
    finally:
        own.close()


def _visit_for(db: Session, user: User) -> Visit | None:
    """The active visit this user is sitting on, if any."""
    seat = active_visit(db)
    if seat and seat.owner_id == user.id:
        return seat
    return None


@router.get("", response_model=SandboxStateOut)
def state(db: Session = Depends(get_db)):
    """Public seat state for the entry page.

    Deliberately exposes nothing about the occupant beyond a display name and the
    remaining time: the point of showing it is queue transparency, not presence
    tracking.
    """
    if not settings.sandbox:
        return SandboxStateOut(enabled=False)
    status = seat_status(db)
    return SandboxStateOut(
        enabled=True,
        state=status.state,
        occupant=status.visit,
        waiting=status.waiting,
        visit_minutes=status.visit_minutes,
        protocols=[
            {"value": "openai_chat", "label": "OpenAI Chat Completions（兼容 DeepSeek / Qwen / Ollama）"},
            {"value": "openai_responses", "label": "OpenAI Responses"},
            {"value": "anthropic", "label": "Anthropic Messages"},
            {"value": "gemini", "label": "Google Gemini"},
        ],
    )


@router.post("/join", response_model=SandboxJoinOut)
def join_endpoint(
    payload: SandboxJoinRequest, request: Request, response: Response, db: Session = Depends(get_db)
):
    """Validate the visitor's endpoint, then either seat them or queue them.

    The probe happens before queueing on purpose: a queue full of people whose
    keys do not work would waste everyone's turn.
    """
    _require_mode()

    ip = client_ip(request)
    allowed, retry = join_limiter.take(f"join:{ip}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"尝试过于频繁，请 {int(retry)} 秒后重试",
            headers={"Retry-After": str(int(retry) + 1)},
        )

    try:
        result = join(
            db,
            base_url=payload.base_url,
            protocol=payload.protocol,
            model_id=payload.model_id,
            api_key=payload.api_key,
            nickname=payload.nickname,
        )
    except SandboxError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc

    if result["state"] == "active":
        _set_session(response, result["session_token"])
        _seed_for(result.get("visit"))

    return SandboxJoinOut(**result)


@router.get("/ticket/{ticket_id}")
def ticket_status(
    ticket_id: str, fingerprint: str = "", db: Session = Depends(get_db)
):
    """Poll a ticket. The caller passes the fingerprint so we do not accept a
    bare id as proof of ownership."""
    _require_mode()
    visit = db.get(Visit, ticket_id)
    if not visit:
        raise HTTPException(status_code=404, detail="排队凭证不存在")
    if fingerprint and visit.fingerprint != fingerprint:
        raise HTTPException(status_code=403, detail="凭证不匹配")
    return {
        "state": visit.status,
        "ticket": ticket_view(db, visit),
        "fingerprint": visit.fingerprint,
    }


@router.post("/claim", response_model=SandboxJoinOut)
def claim_endpoint(
    payload: SandboxClaimRequest, response: Response, db: Session = Depends(get_db)
):
    """Claim a promoted seat and receive the session cookie."""
    _require_mode()
    try:
        result = claim(db, payload.ticket_id, payload.fingerprint)
    except SandboxError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc

    if result["state"] == "active":
        _set_session(response, result["session_token"])
        _seed_for(result.get("visit"))
    return SandboxJoinOut(**result)


@router.get("/me")
def me(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Session-scoped limits for the banner in the workbench."""
    if not settings.sandbox:
        return {"sandbox": False}
    visit = _visit_for(db, user)
    if not visit:
        raise HTTPException(status_code=401, detail="体验已结束")
    return {
        "sandbox": True,
        "visit": {
            "id": visit.id,
            "nickname": visit.nickname,
            "model_id": visit.model_id,
            "protocol": visit.protocol,
            "seconds_left": max(0, int((visit.expires_at - visit.started_at).total_seconds()))
            if visit.expires_at and visit.started_at
            else 0,
            "expires_at": visit.expires_at.isoformat() if visit.expires_at else None,
        },
        "limits": {
            "max_projects": settings.sandbox_max_projects,
            "max_jobs": settings.sandbox_max_jobs,
            "max_upload_mb": settings.max_upload_mb,
        },
    }


@router.post("/exit", status_code=204)
def exit_endpoint(
    request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """End the visit now and hand the seat to the next person.

    Data is destroyed here, not lazily. A visitor who clicks "结束并销毁" expects
    their uploaded material to be gone, not hidden behind a soft delete.
    """
    _require_mode()
    visit = _visit_for(db, user)
    response.delete_cookie(SESSION_COOKIE, path="/", domain=settings.cookie_domain or None)
    if visit is None:
        # No active visit: the cookie may still be valid for a closed one.
        return Response(status_code=204)
    close_visit(db, visit, reason="exit")
    return Response(status_code=204)


@router.post("/probe")
def probe_endpoint_route(payload: SandboxJoinRequest, db: Session = Depends(get_db)):
    """Dry-run the credential check without taking a seat.

    Exposed so the entry form can show "连接正常" before the visitor commits to a
    turn (and, when busy, before they join the queue).
    """
    _require_mode()
    from ..sandbox import probe_endpoint

    try:
        base_url = validate_endpoint(payload.base_url)
        api_key = validate_api_key(payload.api_key)
        result = probe_endpoint(
            base_url=base_url,
            protocol=payload.protocol,
            model_id=payload.model_id,
            api_key=api_key,
        )
    except SandboxError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return result