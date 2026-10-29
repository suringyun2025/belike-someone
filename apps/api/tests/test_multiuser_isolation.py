"""Tenant isolation acceptance tests.

These encode the threat model in docs/multiuser-security.md. Each test maps to an
S-numbered case there; if one of these regresses, the public deployment is
insecure, not merely buggy.
"""
from __future__ import annotations

import os

import pytest

# Enable multiuser for every test in this module. Must happen before app import,
# and conftest already pinned the data/database env vars.
os.environ.setdefault("DISTILL_MULTIUSER", "true")


@pytest.fixture(autouse=True)
def _reset_limiters():
    """Clear rate limiter state between tests.

    The limiters are process-wide singletons by design (a real server wants them
    to persist across requests). Tests each act like a fresh browser, so without
    this reset the second test in a session inherits the first one's budget.
    """
    from app import rate_limit

    limiters = (
        rate_limit.login_limiter,
        rate_limit.register_limiter,
        rate_limit.api_limiter,
        rate_limit.heavy_limiter,
    )
    for limiter in limiters:
        limiter._buckets.clear()
    yield
    for limiter in limiters:
        limiter._buckets.clear()


def _wipe_tenants() -> None:
    """Delete all tenant data.

    Called *inside* the client context so the schema already exists: the app's
    lifespan creates/migrates tables, and the suite shares one database file.
    """
    from sqlalchemy import delete, inspect

    from app.db import SessionLocal, engine
    from app.models import (
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
    )

    available = set(inspect(engine).get_table_names())
    db = SessionLocal()
    try:
        for model in (
            EvidenceItem,
            Conflict,
            Claim,
            SkillVersion,
            Skill,
            EvalRun,
            EvalCase,
            Export,
            StageRun,
            Job,
            ChunkEmbedding,
            Chunk,
            DocumentBlock,
            Document,
            Source,
            Project,
            Provider,
            SessionModel,
            AuditEvent,
            User,
        ):
            if model.__tablename__ in available:
                db.execute(delete(model))
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def multiuser_client(monkeypatch):
    """A client with multiuser enabled, registration open, and no prior tenants."""
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "multiuser", True)
    monkeypatch.setattr(settings, "allow_registration", True)
    monkeypatch.setattr(settings, "cookie_secure", False)

    with TestClient(app) as client:
        _wipe_tenants()
        yield client


def _register(client, email: str, password: str = "averylongpassword1"):
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login(client, email: str, password: str = "averylongpassword1"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def alice(multiuser_client):
    client = multiuser_client
    user = _register(client, "alice@example.com")
    project = client.post("/api/v1/projects", json={"name": "Alice 的项目"}).json()
    return {"client": client, "user": user, "project": project}


# --------------------------------------------------------------------------
# S1 — unauthenticated access
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/projects"),
        ("get", "/api/v1/providers"),
        ("get", "/api/v1/dashboard"),
        ("get", "/api/v1/stats"),
        ("get", "/api/v1/usage"),
        ("post", "/api/v1/demo"),
    ],
)
def test_s1_unauthenticated_is_rejected(multiuser_client, method, path):
    response = getattr(multiuser_client, method)(path)
    assert response.status_code == 401, f"{path} leaked to anonymous callers"


def test_s1_business_endpoints_require_session(multiuser_client, alice):
    """Every project-scoped endpoint must reject an anonymous caller."""
    project_id = alice["project"]["id"]
    paths = [
        f"/api/v1/projects/{project_id}",
        f"/api/v1/projects/{project_id}/sources",
        f"/api/v1/projects/{project_id}/claims",
        f"/api/v1/projects/{project_id}/skills",
        f"/api/v1/projects/{project_id}/exports",
        f"/api/v1/projects/{project_id}/jobs",
        f"/api/v1/projects/{project_id}/persona",
        f"/api/v1/projects/{project_id}/audit",
    ]
    alice["client"].cookies.clear()
    for path in paths:
        assert alice["client"].get(path).status_code == 401, path


# --------------------------------------------------------------------------
# S2 / S3 — cross-tenant access by id
# --------------------------------------------------------------------------
def test_s2_cannot_read_another_users_project(multiuser_client, alice):
    bob = _register(multiuser_client, "bob@example.com")
    project_id = alice["project"]["id"]

    response = multiuser_client.get(f"/api/v1/projects/{project_id}")
    # 404 rather than 403: a 403 would confirm the id exists.
    assert response.status_code == 404, response.text


def test_s2_cannot_modify_or_delete_another_users_project(multiuser_client, alice):
    _register(multiuser_client, "bob@example.com")
    project_id = alice["project"]["id"]

    assert multiuser_client.patch(
        f"/api/v1/projects/{project_id}", json={"name": "hijacked"}
    ).status_code == 404
    assert multiuser_client.delete(f"/api/v1/projects/{project_id}").status_code == 404


def test_s2_project_list_is_scoped(multiuser_client, alice):
    _register(multiuser_client, "bob@example.com")
    listing = multiuser_client.get("/api/v1/projects").json()
    assert listing == [], "Bob must not see Alice's projects"


def test_s3_cannot_reach_child_resources_by_id(multiuser_client, alice):
    """Claims, sources, skills, exports resolved through their own ids."""
    client = alice["client"]
    project_id = alice["project"]["id"]
    client.post(
        f"/api/v1/projects/{project_id}/sources",
        files=[("files", ("note.md", b"# t\n\nI prefer checking constraints first.\n", "text/markdown"))],
    )
    job = client.post(f"/api/v1/projects/{project_id}/jobs", json={"kind": "distill"}).json()
    from .conftest import drain_jobs

    drain_jobs(client, job["id"])
    claims = client.get(f"/api/v1/projects/{project_id}/claims").json()
    sources = client.get(f"/api/v1/projects/{project_id}/sources").json()

    _register(multiuser_client, "bob@example.com")
    bob = multiuser_client
    probes = [
        f"/api/v1/sources/{sources[0]['id']}" if sources else None,
        f"/api/v1/sources/{sources[0]['id']}/preview" if sources else None,
        f"/api/v1/claims/{claims[0]['id']}" if claims else None,
        f"/api/v1/jobs/{job['id']}",
        f"/api/v1/jobs/{job['id']}/events",
    ]
    for path in [p for p in probes if p]:
        assert bob.get(path).status_code == 404, f"{path} exposed another tenant's data"


# --------------------------------------------------------------------------
# S4 / S5 — provider (API key) isolation
# --------------------------------------------------------------------------
def test_s4_providers_are_per_user(multiuser_client, alice):
    created = alice["client"].post(
        "/api/v1/providers",
        json={
            "name": "Alice Key",
            "protocol": "openai_chat",
            "base_url": "https://api.example.com/v1",
            "model_id": "gpt-test",
            "api_key": "sk-alice-secret-value-1234567890",
        },
    )
    assert created.status_code == 201, created.text
    provider_id = created.json()["id"]

    _register(multiuser_client, "bob@example.com")
    assert multiuser_client.get("/api/v1/providers").json() == []
    assert multiuser_client.get(f"/api/v1/providers/{provider_id}").status_code == 404
    assert multiuser_client.post(f"/api/v1/providers/{provider_id}/test", json={}).status_code == 404
    assert multiuser_client.patch(
        f"/api/v1/providers/{provider_id}", json={"name": "stolen"}
    ).status_code == 404
    assert multiuser_client.delete(f"/api/v1/providers/{provider_id}").status_code == 404


def test_s5_api_key_never_returned(multiuser_client, alice):
    secret = "sk-live-should-never-appear-abcdef123456"
    created = alice["client"].post(
        "/api/v1/providers",
        json={
            "name": "K",
            "protocol": "openai_chat",
            "base_url": "https://api.example.com/v1",
            "model_id": "m",
            "api_key": secret,
        },
    )
    provider_id = created.json()["id"]
    payloads = [
        created.text,
        alice["client"].get("/api/v1/providers").text,
        alice["client"].get(f"/api/v1/providers/{provider_id}").text,
        alice["client"].patch(f"/api/v1/providers/{provider_id}", json={"name": "K2"}).text,
    ]
    for body in payloads:
        assert secret not in body, "plaintext API key leaked through the API"
        # ``api_key_mask`` is the deliberate placeholder ("已配置"); the actual
        # key field must never be serialised.
        import json

        parsed = json.loads(body)
        records = parsed if isinstance(parsed, list) else [parsed]
        for record in records:
            assert "api_key" not in record, "raw api_key field present in response"
            assert "api_key_encrypted" not in record, "ciphertext exposed in response"


def test_s5_ciphertext_cannot_be_moved_between_tenants(client):
    """AAD binding: A's sealed key must not decrypt as B's."""
    from app.auth import decrypt_secret, encrypt_secret

    sealed = encrypt_secret("sk-secret", "usr_alice")
    assert decrypt_secret(sealed, "usr_alice") == "sk-secret"
    with pytest.raises(ValueError):
        decrypt_secret(sealed, "usr_bob")


# --------------------------------------------------------------------------
# S6 / S7 — storage shape of credentials
# --------------------------------------------------------------------------
def test_s6_session_tokens_stored_as_hash(multiuser_client, alice):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Session as SessionModel

    token = multiuser_client.cookies.get("distill_session")
    assert token, "expected a session cookie"
    db = SessionLocal()
    try:
        rows = db.scalars(select(SessionModel)).all()
        stored = {row.token_hash for row in rows}
    finally:
        db.close()
    assert token not in stored, "raw token must never be persisted"
    assert all(len(value) == 64 for value in stored), "expected sha256 hex digests"


def test_s7_password_stored_as_argon2(multiuser_client, alice):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "alice@example.com"))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert "averylongpassword1" not in user.password_hash
    finally:
        db.close()


# --------------------------------------------------------------------------
# S8 — throttling
# --------------------------------------------------------------------------
def test_s8_login_attempts_are_throttled(multiuser_client, alice):
    statuses = []
    for _ in range(14):
        response = multiuser_client.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "definitely-wrong"},
        )
        statuses.append(response.status_code)
    assert 429 in statuses, f"expected throttling, got {statuses}"


def test_s8_registration_is_throttled(multiuser_client):
    statuses = []
    for index in range(9):
        response = multiuser_client.post(
            "/api/v1/auth/register",
            json={"email": f"bulk{index}@example.com", "password": "averylongpassword1"},
        )
        statuses.append(response.status_code)
    assert 429 in statuses, f"expected throttling, got {statuses}"


# --------------------------------------------------------------------------
# S9 — logout revokes the session
# --------------------------------------------------------------------------
def test_s9_logout_invalidates_cookie(multiuser_client, alice):
    client = alice["client"]
    assert client.get("/api/v1/auth/me").status_code == 200
    stolen = client.cookies.get("distill_session")

    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set("distill_session", stolen)
    assert client.get("/api/v1/auth/me").status_code == 401, "revoked session still works"


def test_password_change_evicts_other_sessions(multiuser_client, alice):
    client = alice["client"]
    other = multiuser_client
    _login(other, "alice@example.com")
    assert other.get("/api/v1/auth/me").status_code == 200

    response = client.post(
        "/api/v1/auth/password",
        json={"current_password": "averylongpassword1", "new_password": "anotherlongpassword2"},
    )
    assert response.status_code == 204
    assert other.get("/api/v1/auth/me").status_code == 401


# --------------------------------------------------------------------------
# S10 — SSE authorisation
# --------------------------------------------------------------------------
def test_s10_cannot_subscribe_to_foreign_job_stream(multiuser_client, alice):
    client = alice["client"]
    project_id = alice["project"]["id"]
    client.post(
        f"/api/v1/projects/{project_id}/sources",
        files=[("files", ("n.md", b"# t\n\nI always measure before concluding.\n", "text/markdown"))],
    )
    job = client.post(f"/api/v1/projects/{project_id}/jobs", json={"kind": "distill"}).json()

    _register(multiuser_client, "bob@example.com")
    assert multiuser_client.get(f"/api/v1/jobs/{job['id']}/events").status_code == 404


# --------------------------------------------------------------------------
# S11 — upload limits still enforced
# --------------------------------------------------------------------------
def test_s11_oversized_upload_rejected(multiuser_client, alice, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_upload_mb", 1)
    big = b"x" * (2 * 1024 * 1024)
    response = alice["client"].post(
        f"/api/v1/projects/{alice['project']['id']}/sources",
        files=[("files", ("big.txt", big, "text/plain"))],
    )
    assert response.status_code == 413


# --------------------------------------------------------------------------
# S12 — security headers
# --------------------------------------------------------------------------
def test_s12_security_headers_present(multiuser_client):
    response = multiuser_client.get("/api/v1/health")
    for header in (
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
        "content-security-policy",
        "permissions-policy",
    ):
        assert header in {key.lower() for key in response.headers}, f"missing {header}"


# --------------------------------------------------------------------------
# Tenant isolation for aggregates
# --------------------------------------------------------------------------
def test_dashboard_and_stats_are_scoped(multiuser_client, alice):
    before = alice["client"].get("/api/v1/dashboard").json()
    assert before["projects"] >= 1

    _register(multiuser_client, "bob@example.com")
    bob_dashboard = multiuser_client.get("/api/v1/dashboard").json()
    bob_stats = multiuser_client.get("/api/v1/stats").json()
    assert bob_dashboard["projects"] == 0
    assert bob_dashboard["sources"] == 0
    assert bob_stats["projects"] == 0


def test_usage_does_not_leak_across_tenants(multiuser_client, alice):
    _register(multiuser_client, "bob@example.com")
    usage = multiuser_client.get("/api/v1/usage").json()
    assert usage["projects"] == []


def test_first_user_becomes_admin(multiuser_client):
    first = _register(multiuser_client, "root@example.com")
    assert first["is_admin"] is True
    second = _register(multiuser_client, "other@example.com")
    assert second["is_admin"] is False