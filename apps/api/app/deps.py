"""Authorisation dependencies.

The rule everywhere else in the codebase: **never trust an id from the client**.
Each handler either
  * resolves the caller's own project via ``owned_project``, or
  * resolves a child resource, then derives its project and re-checks ownership.

Returning 404 (not 403) for someone else's resource is deliberate: a 403 would
confirm the id exists, which is an enumeration oracle.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import token_hash
from .config import settings
from .db import get_db
from .models import Project, Session as SessionModel, User

SESSION_COOKIE = "distill_session"
CSRF_HEADER = "x-csrf-token"
# Cookie lifetime. Long enough for a demo turn (or a working day in multiuser
# mode); the server-side session row is the authority and expires independently.
SESSION_MAX_AGE = 14 * 24 * 3600


def client_ip(request: Request) -> str:
    """Best-effort client address honouring a single trusted proxy hop."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    real = request.headers.get("x-real-ip", "")
    if real:
        return real.strip()[:64]
    return (request.client.host if request.client else "")[:64]


def _load_session(db: Session, token: str) -> SessionModel | None:
    if not token:
        return None
    record = db.scalar(select(SessionModel).where(SessionModel.token_hash == token_hash(token)))
    if not record or record.revoked_at is not None:
        return None
    if record.expires_at and record.expires_at < datetime.now().replace(tzinfo=None):
        return None
    return record


def _session_token(request: Request) -> str:
    """Read the token from the cookie, falling back to a bearer header.

    The header path exists for API clients and tests; the browser uses the
    HttpOnly cookie so JavaScript cannot read it.
    """
    cookie = request.cookies.get(SESSION_COOKIE, "")
    if cookie:
        return cookie
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the caller.

    Three modes, in order:

    * A valid session cookie identifies a user (multiuser and sandbox builds).
    * ``sandbox`` mode additionally requires that user to be the current
      occupant. Deleting the visit's owner is not enough on its own — a request
      in flight could still hold the old object — so the seat is re-checked.
    * Single-user mode (``multiuser=False``) synthesises a local user, which keeps
      the local-first build usable without a login step while exercising the same
      ownership checks.
    """
    token = _session_token(request)
    record = _load_session(db, token)
    if record:
        user = db.get(User, record.user_id)
        if user and not user.disabled:
            if settings.sandbox and not _holds_seat(db, user.id):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="体验已结束，请重新进入",
                )
            request.state.user = user
            request.state.session = record
            return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不可用")

    if not settings.multiuser and not settings.sandbox:
        user = _local_user(db)
        request.state.user = user
        request.state.session = None
        return user

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")


def _holds_seat(db: Session, user_id: str) -> bool:
    """True when this user is the current occupant of the demo seat."""
    from .models import AppSetting, Visit

    row = db.get(AppSetting, "active_visit")
    if not row or not isinstance(row.value, dict):
        return False
    visit_id = str(row.value.get("visit_id") or "")
    if not visit_id:
        return False
    visit = db.get(Visit, visit_id)
    if not visit or visit.status != "active" or visit.owner_id != user_id:
        return False
    # Enforce the clock here as well: the reaper runs every 30 s, and a visitor
    # must not get 30 extra seconds of writes after their turn expires.
    if visit.expires_at and visit.expires_at <= datetime.now():
        return False
    return True


def _local_user(db: Session) -> User:
    """The implicit owner of all data in single-user mode.

    Created on demand so a fresh local install has something to attribute rows
    to, and reused afterwards so ownership stays stable across requests.
    """
    marker = "local@localhost"
    user = db.scalar(select(User).where(User.email == marker))
    if user:
        return user
    user = User(
        email=marker,
        password_hash="!",  # unusable: this account cannot be logged into
        display_name="本地用户",
        is_admin=True,
        max_projects=10_000,
        max_storage_mb=10_000_000,
    )
    db.add(user)
    try:
        db.commit()
    except Exception:  # pragma: no cover - concurrent first request
        db.rollback()
        user = db.scalar(select(User).where(User.email == marker))
    db.refresh(user)
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def owned_project(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Project:
    """Resolve a project the caller owns, or 404.

    In single-user mode (``multiuser=False``) ownership is not enforced, which
    keeps the local build behaviour identical to before.
    """
    project = db.get(Project, project_id)
    if not project or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if (settings.multiuser or settings.sandbox) and project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def scope_project(db: Session, project_id: str, user: User) -> Project:
    """Non-dependency variant for code paths without request scope."""
    project = db.get(Project, project_id)
    if not project or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if (settings.multiuser or settings.sandbox) and project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def assert_project_owned(db: Session, project_id: str, user: User) -> None:
    scope_project(db, project_id, user)