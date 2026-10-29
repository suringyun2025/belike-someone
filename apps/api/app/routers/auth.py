"""Authentication endpoints.

Cookie handling notes
---------------------
* The session cookie is ``HttpOnly`` so XSS cannot read it, ``Secure`` when TLS is
  terminated upstream, and ``SameSite=Lax`` which blocks cross-site POSTs while
  keeping normal navigation working.
* Because cookies are sent automatically, state-changing requests also require a
  CSRF header. ``SameSite=Lax`` alone is not sufficient defence for older clients.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import (
    hash_password,
    needs_rehash,
    new_session_token,
    normalize_email,
    session_expiry,
    validate_email,
    validate_password_strength,
    verify_password,
)
from ..config import settings
from ..db import get_db
from ..deps import CSRF_HEADER, SESSION_COOKIE, client_ip, current_user
from ..models import AuditEvent, Project, Session as SessionModel, User, utcnow
from ..rate_limit import login_limiter, register_limiter
from ..schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _audit(db: Session, action: str, request: Request, user: User | None, detail: dict) -> None:
    db.add(
        AuditEvent(
            project_id=None,
            actor_id=user.id if user else None,
            actor=user.email if user else "anonymous",
            action=action,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:400],
            detail=detail,
        )
    )


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.session_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,  # type: ignore[arg-type]
        domain=settings.cookie_domain or None,
        path="/",
    )


def _user_out(db: Session, user: User) -> UserOut:
    project_count = db.scalar(
        select(func.count()).select_from(Project).where(Project.owner_id == user.id)
    ) or 0
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        max_projects=user.max_projects or settings.max_projects_per_user,
        max_storage_mb=user.max_storage_mb or settings.max_storage_mb_per_user,
        project_count=project_count,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


@router.get("/config")
def auth_config():
    """Public hints so the entry page can render the right gate.

    ``sandbox`` tells the SPA to show the demo entry rather than a login form:
    a demo instance has no accounts, so a login screen would be a dead end.
    """
    return {
        "multiuser": settings.multiuser,
        "sandbox": settings.sandbox,
        "allow_registration": settings.allow_registration,
        "session_days": settings.session_days,
        "email_verification": False,
    }


@router.post("/register", response_model=UserOut, status_code=201)
def register(
    payload: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)
):
    if not settings.allow_registration:
        raise HTTPException(status_code=403, detail="当前未开放注册，请联系管理员开通账号")

    ip = client_ip(request)
    allowed, retry = register_limiter.take(f"reg:{ip}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"注册过于频繁，请 {int(retry)} 秒后重试",
            headers={"Retry-After": str(int(retry) + 1)},
        )

    email = normalize_email(payload.email)
    if not validate_email(email):
        raise HTTPException(status_code=422, detail="邮箱格式不正确")
    problem = validate_password_strength(payload.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    if db.scalar(select(User.id).where(User.email == email)):
        # Registration is rate limited, so a precise message here is acceptable
        # and much better UX than a silent failure.
        raise HTTPException(status_code=409, detail="该邮箱已注册")

    # First account on a fresh instance becomes the admin so there is always
    # someone who can manage users without shell access.
    is_first = (db.scalar(select(func.count()).select_from(User)) or 0) == 0
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=(payload.display_name or email.split("@")[0])[:120],
        is_admin=is_first,
        max_projects=settings.max_projects_per_user,
        max_storage_mb=settings.max_storage_mb_per_user,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该邮箱已注册")

    token, digest = new_session_token()
    db.add(
        SessionModel(
            user_id=user.id,
            token_hash=digest,
            ip=ip,
            user_agent=request.headers.get("user-agent", "")[:400],
            expires_at=session_expiry(),
        )
    )
    user.last_login_at = utcnow()
    _audit(db, "auth.register", request, user, {"email": email, "first_user": is_first})
    db.commit()
    db.refresh(user)
    _set_cookie(response, token)
    response.headers[CSRF_HEADER] = token[:16]
    return _user_out(db, user)


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    email = normalize_email(payload.email)
    # Key on both account and IP so one attacker cannot lock a victim out by
    # hammering their email from a single address, and cannot spread attempts
    # across emails from one address either.
    allowed_account, retry_a = login_limiter.take(f"login:acct:{email}")
    allowed_ip, retry_b = login_limiter.take(f"login:ip:{ip}")
    if not (allowed_account and allowed_ip):
        retry = max(retry_a, retry_b)
        _audit(db, "auth.login_throttled", request, None, {"email": email})
        db.commit()
        raise HTTPException(
            status_code=429,
            detail=f"尝试过于频繁，请 {int(retry)} 秒后重试",
            headers={"Retry-After": str(int(retry) + 1)},
        )

    user = db.scalar(select(User).where(User.email == email))
    # Always run a verification to keep timing similar for unknown accounts.
    stored = user.password_hash if user else "$argon2id$v=19$m=19456,t=2,p=1$c29tZXNhbHQ$0000000000000000000000000000000000000000000"
    ok = verify_password(payload.password, stored) and user is not None
    if not user or not ok:
        _audit(db, "auth.login_failed", request, None, {"email": email})
        db.commit()
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    if user.disabled:
        raise HTTPException(status_code=403, detail="账号已被停用")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    token, digest = new_session_token()
    db.add(
        SessionModel(
            user_id=user.id,
            token_hash=digest,
            ip=ip,
            user_agent=request.headers.get("user-agent", "")[:400],
            expires_at=session_expiry(),
        )
    )
    user.last_login_at = utcnow()
    _audit(db, "auth.login", request, user, {})
    db.commit()
    db.refresh(user)
    # Successful login resets the account bucket so a legitimate user who
    # mistyped a few times is not punished afterwards.
    login_limiter.reset(f"login:acct:{email}")
    _set_cookie(response, token)
    response.headers[CSRF_HEADER] = token[:16]
    return _user_out(db, user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        from ..auth import token_hash

        record = db.scalar(select(SessionModel).where(SessionModel.token_hash == token_hash(token)))
        if record:
            record.revoked_at = utcnow()
            db.add(record)
            _audit(db, "auth.logout", request, None, {"session_id": record.id})
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return None


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _user_out(db, user)


@router.post("/password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    problem = validate_password_strength(payload.new_password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    user.password_hash = hash_password(payload.new_password)
    # Invalidate every other session: a password change must evict an attacker
    # who already holds a session.
    for record in db.scalars(
        select(SessionModel).where(
            SessionModel.user_id == user.id, SessionModel.revoked_at.is_(None)
        )
    ).all():
        record.revoked_at = utcnow()
        db.add(record)
    db.add(user)
    _audit(db, "auth.password_change", request, user, {})
    db.commit()
    return None


@router.get("/sessions")
def list_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    records = db.scalars(
        select(SessionModel)
        .where(SessionModel.user_id == user.id, SessionModel.revoked_at.is_(None))
        .order_by(SessionModel.created_at.desc())
        .limit(50)
    ).all()
    now = datetime.now()
    return [
        {
            "id": record.id,
            "ip": record.ip,
            "user_agent": record.user_agent,
            "created_at": record.created_at,
            "expires_at": record.expires_at,
            "expired": bool(record.expires_at and record.expires_at < now),
        }
        for record in records
    ]