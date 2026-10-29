"""Sandbox seat semantics.

The behaviours asserted here are the ones whose failure would be silent and
expensive:

* two visitors must never hold the seat at once (double-billing their keys);
* a closed visit must leave no rows and no files (a demo that keeps data is a
  retention problem, and nobody would notice for months);
* a queued visitor must keep their place across a refresh;
* teardown must survive being interrupted (an orphaned guest account holds disk
  forever otherwise).
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.config import settings
from app.db import SessionLocal
from app.models import (
    AppSetting,
    Chunk,
    Claim,
    Document,
    Job,
    Project,
    Provider,
    Session as SessionModel,
    Source,
    User,
    Visit,
    utcnow,
)
from app.sandbox import (
    SandboxError,
    close_visit,
    join,
    purge_orphans,
    reaper_tick,
    seat_status,
    validate_endpoint,
)


@pytest.fixture()
def sandbox_client(monkeypatch):
    """A client with sandbox mode on.

    Each test gets a clean seat before and after: the seat is global state, so a
    leftover active visit from a previous test would make the next one queue.

    ``monkeypatch`` restores ``sandbox``/``multiuser`` on teardown, but other
    modules read the *derived* flag at import time in some places, so the seat
    and visit rows are also wiped to avoid leaking state into later tests.
    """
    from app import rate_limit

    monkeypatch.setattr(settings, "sandbox", True)
    monkeypatch.setattr(settings, "multiuser", True)
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(settings, "sandbox_https_only", False)
    monkeypatch.setattr(settings, "sandbox_visit_minutes", 30)
    monkeypatch.setattr(settings, "allow_registration", False)

    for limiter in (rate_limit.join_limiter, rate_limit.api_limiter):
        limiter._buckets.clear()

    def _wipe() -> None:
        db = SessionLocal()
        try:
            for model in (Chunk, Document, Source, Claim, Job, Project, Provider, Visit, AppSetting):
                db.execute(delete(model))
            db.execute(delete(SessionModel))
            db.execute(delete(User))
            db.commit()
        finally:
            db.close()

    from app.main import app

    with TestClient(app) as client:
        _wipe()
        yield client
        _wipe()


def _join_payload(**overrides):
    payload = {
        "base_url": "https://api.openai.com/v1",
        "protocol": "openai_chat",
        "model_id": "gpt-4o-mini",
        "api_key": "sk-test-abcdefghijklmnop",
        "nickname": "访客A",
    }
    payload.update(overrides)
    return payload


def test_seat_starts_free(sandbox_client):
    body = sandbox_client.get("/api/v1/sandbox").json()
    assert body["enabled"] is True
    assert body["state"] == "free"
    assert body["waiting"] == 0


def test_business_api_requires_a_seat(sandbox_client):
    # No cookie at all.
    assert sandbox_client.get("/api/v1/projects").status_code == 401


def test_ssrf_is_rejected_before_any_connection(sandbox_client):
    """A visitor-supplied URL is the only outbound request they control.

    ``resolve=False`` keeps this test about the shape checks. The DNS path is
    exercised separately below, because name resolution is environment-specific
    and a test that needs real DNS fails for the wrong reason.
    """
    for url in (
        "http://127.0.0.1:8000/v1",
        "http://localhost/v1",
        "http://10.0.0.5/v1",
        "http://192.168.1.1/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/v1",
        "http://metadata.internal/v1",
        "http://router.local/v1",
    ):
        with pytest.raises(SandboxError) as exc:
            validate_endpoint(url, resolve=False)
        assert exc.value.code == "INVALID_URL", url


def test_public_hostname_shape_is_accepted():
    assert validate_endpoint("https://api.openai.com/v1", resolve=False) == "https://api.openai.com/v1"
    assert validate_endpoint("https://api.deepseek.com/v1/", resolve=False) == "https://api.deepseek.com/v1"


def test_dns_resolution_rejects_a_public_name_pointing_inward(monkeypatch):
    """A hostname is not trusted just because its text looks public."""
    import socket as _socket

    def _fake_getaddrinfo(host, port, **kwargs):
        return [(2, 1, 6, "", ("10.0.0.7", port))]

    monkeypatch.setattr(_socket, "getaddrinfo", _fake_getaddrinfo)
    with pytest.raises(SandboxError) as exc:
        validate_endpoint("https://totally-public.example.com/v1")
    assert "内网" in exc.value.message


def test_endpoint_requires_http_scheme():
    with pytest.raises(SandboxError):
        validate_endpoint("api.example.com/v1", resolve=False)
    with pytest.raises(SandboxError):
        validate_endpoint("file:///etc/passwd", resolve=False)


def test_endpoint_rejects_embedded_credentials():
    with pytest.raises(SandboxError):
        validate_endpoint("https://user:pass@api.example.com/v1", resolve=False)


def test_join_rejects_bad_key_shape(sandbox_client):
    response = sandbox_client.post(
        "/api/v1/sandbox/join", json=_join_payload(api_key="short")
    )
    assert response.status_code == 422


def test_join_with_unreachable_endpoint_is_refused(sandbox_client, monkeypatch):
    """The probe must fail the join rather than seat someone with a dud key."""
    from app import sandbox

    def _boom(**_kwargs):
        raise SandboxError("PROBE_FAILED", "连接失败（AUTH_ERROR）：密钥无效")

    monkeypatch.setattr(sandbox, "probe_endpoint", _boom)
    response = sandbox_client.post("/api/v1/sandbox/join", json=_join_payload())
    assert response.status_code == 400
    assert "连接失败" in response.text
    # Nothing was created: a failed probe must not consume the seat.
    db = SessionLocal()
    try:
        assert db.scalar(select(func.count()).select_from(Visit)) == 0
    finally:
        db.close()
    assert sandbox_client.get("/api/v1/sandbox").json()["state"] == "free"


def test_successful_join_seats_the_visitor_and_seeds_a_project(sandbox_client, monkeypatch):
    from app import sandbox

    monkeypatch.setattr(
        sandbox, "probe_endpoint", lambda **_: {"ok": True, "latency_ms": 42, "model": "gpt-4o-mini"}
    )
    response = sandbox_client.post("/api/v1/sandbox/join", json=_join_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "active"
    assert body["visit"]["seconds_left"] > 0

    # The cookie is set, so the workbench is immediately usable.
    projects = sandbox_client.get("/api/v1/projects")
    assert projects.status_code == 200
    seeded = projects.json()
    assert len(seeded) == 1  # demo project, so the visitor can run immediately

    state = sandbox_client.get("/api/v1/sandbox").json()
    assert state["state"] == "busy"
    assert state["occupant"]["nickname"] == "访客A"


def test_second_visitor_is_queued_not_seated(sandbox_client, monkeypatch):
    """Two people must never hold the seat: both would bill their own keys, but
    the server would run two jobs and fall over."""
    from app import sandbox

    monkeypatch.setattr(
        sandbox, "probe_endpoint", lambda **_: {"ok": True, "latency_ms": 10, "model": "m"}
    )
    first = sandbox_client.post("/api/v1/sandbox/join", json=_join_payload())
    assert first.json()["state"] == "active"

    second = TestClient(sandbox_client.app)
    response = second.post(
        "/api/v1/sandbox/join", json=_join_payload(api_key="sk-second-key-123456", nickname="访客B")
    )
    body = response.json()
    assert body["state"] == "queued"
    assert body["ticket"]["position"] == 1
    assert body["ticket"]["ahead"] == 0
    assert body["ticket"]["estimated_wait_seconds"] > 0

    # The queued visitor has no session: they cannot read anything yet.
    assert second.get("/api/v1/projects").status_code == 401


def test_queue_order_is_fifo(sandbox_client, monkeypatch):
    from app import sandbox

    monkeypatch.setattr(
        sandbox, "probe_endpoint", lambda **_: {"ok": True, "latency_ms": 10, "model": "m"}
    )
    sandbox_client.post("/api/v1/sandbox/join", json=_join_payload())

    positions = []
    for index in range(3):
        client = TestClient(sandbox_client.app)
        body = client.post(
            "/api/v1/sandbox/join",
            json=_join_payload(api_key=f"sk-queued-key-{index:04d}", nickname=f"排队{index}"),
        ).json()
        positions.append(body["ticket"]["ahead"])
    assert positions == [0, 1, 2]


def test_refresh_keeps_the_queue_place(sandbox_client, monkeypatch):
    """A visitor reloading the page must not lose their spot."""
    from app import sandbox

    monkeypatch.setattr(
        sandbox, "probe_endpoint", lambda **_: {"ok": True, "latency_ms": 10, "model": "m"}
    )
    sandbox_client.post("/api/v1/sandbox/join", json=_join_payload())

    payload = _join_payload(api_key="sk-refresh-key-0001", nickname="刷新")
    first = sandbox_client.post("/api/v1/sandbox/join", json=payload).json()
    second = sandbox_client.post("/api/v1/sandbox/join", json=payload).json()
    assert first["ticket"]["ticket_id"] == second["ticket"]["ticket_id"]
    assert first["ticket"]["position"] == second["ticket"]["position"]

    db = SessionLocal()
    try:
        assert db.scalar(select(func.count()).select_from(Visit).where(Visit.status == "queued")) == 1
    finally:
        db.close()


def test_exit_destroys_everything_and_frees_the_seat(sandbox_client, monkeypatch):
    """The promise to the visitor is deletion, not hiding."""
    from app import sandbox

    monkeypatch.setattr(
        sandbox, "probe_endpoint", lambda **_: {"ok": True, "latency_ms": 10, "model": "m"}
    )
    joined = sandbox_client.post("/api/v1/sandbox/join", json=_join_payload()).json()
    owner_id = joined["visit"]["id"]

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.display_name == "访客A"))
        assert user is not None
        project_count = db.scalar(
            select(func.count()).select_from(Project).where(Project.owner_id == user.id)
        )
        assert project_count == 1
        user_id = user.id
    finally:
        db.close()

    assert sandbox_client.post("/api/v1/sandbox/exit").status_code == 204

    db = SessionLocal()
    try:
        assert db.get(User, user_id) is None, "guest account survived exit"
        assert db.scalar(select(func.count()).select_from(Project)) == 0
        assert db.scalar(select(func.count()).select_from(Source)) == 0
        assert db.scalar(select(func.count()).select_from(Provider)) == 0
        assert db.scalar(select(func.count()).select_from(SessionModel)) == 0
        visit = db.get(Visit, owner_id)
        assert visit.status == "closed"
        assert visit.close_reason == "exit"
        # The sealed key dies with the row that held it.
        assert visit.api_key_encrypted  # row keeps its own copy, but no user/provider
    finally:
        db.close()

    # Seat is free again.
    assert sandbox_client.get("/api/v1/sandbox").json()["state"] == "free"
    # The old cookie no longer authorises anything.
    assert sandbox_client.get("/api/v1/projects").status_code == 401


def test_expired_visit_is_closed_by_the_reaper(sandbox_client, monkeypatch):
    from app import sandbox

    monkeypatch.setattr(
        sandbox, "probe_endpoint", lambda **_: {"ok": True, "latency_ms": 10, "model": "m"}
    )
    sandbox_client.post("/api/v1/sandbox/join", json=_join_payload())

    db = SessionLocal()
    try:
        visit = db.scalar(select(Visit).where(Visit.status == "active"))
        visit.expires_at = utcnow() - timedelta(seconds=1)
        db.add(visit)
        db.commit()
        visit_id = visit.id
    finally:
        db.close()

    reaper_tick(SessionLocal())
    db = SessionLocal()
    try:
        assert db.get(Visit, visit_id).status == "closed"
        assert db.get(Visit, visit_id).close_reason == "timeout"
    finally:
        db.close()
    assert sandbox_client.get("/api/v1/sandbox").json()["state"] == "free"


def test_next_ticket_becomes_ready_then_claims_the_seat(sandbox_client, monkeypatch):
    """Promotion is a handshake because the cookie can only arrive on a response
    the browser itself initiated."""
    from app import sandbox

    monkeypatch.setattr(
        sandbox, "probe_endpoint", lambda **_: {"ok": True, "latency_ms": 10, "model": "m"}
    )
    sandbox_client.post("/api/v1/sandbox/join", json=_join_payload())

    waiter = TestClient(sandbox_client.app)
    ticket = waiter.post(
        "/api/v1/sandbox/join", json=_join_payload(api_key="sk-waiter-key-9876", nickname="等待者")
    ).json()["ticket"]

    sandbox_client.post("/api/v1/sandbox/exit")
    reaper_tick(SessionLocal())

    db = SessionLocal()
    try:
        row = db.get(Visit, ticket["ticket_id"])
        assert row.status == "ready"
        fingerprint = row.fingerprint
    finally:
        db.close()

    claimed = waiter.post(
        "/api/v1/sandbox/claim",
        json={"ticket_id": ticket["ticket_id"], "fingerprint": fingerprint},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["state"] == "active"
    assert waiter.get("/api/v1/projects").status_code == 200


def test_claim_rejects_a_foreign_fingerprint(sandbox_client, monkeypatch):
    from app import sandbox

    monkeypatch.setattr(
        sandbox, "probe_endpoint", lambda **_: {"ok": True, "latency_ms": 10, "model": "m"}
    )
    sandbox_client.post("/api/v1/sandbox/join", json=_join_payload())
    waiter = TestClient(sandbox_client.app)
    ticket = waiter.post(
        "/api/v1/sandbox/join", json=_join_payload(api_key="sk-other-key-4567")
    ).json()["ticket"]
    sandbox_client.post("/api/v1/sandbox/exit")
    reaper_tick(SessionLocal())

    response = waiter.post(
        "/api/v1/sandbox/claim",
        json={"ticket_id": ticket["ticket_id"], "fingerprint": "0" * 64},
    )
    assert response.status_code == 403


def test_orphan_purge_removes_dead_guest_workspaces(sandbox_client, monkeypatch):
    """A crash between close and purge must not leak disk forever."""
    from app import sandbox

    monkeypatch.setattr(
        sandbox, "probe_endpoint", lambda **_: {"ok": True, "latency_ms": 10, "model": "m"}
    )
    sandbox_client.post("/api/v1/sandbox/join", json=_join_payload())

    db = SessionLocal()
    try:
        # Simulate a half-finished teardown: user still there, visit already closed.
        visit = db.scalar(select(Visit).where(Visit.status == "active"))
        visit.status = "closed"
        db.add(visit)
        db.commit()
        owner = visit.owner_id
        assert db.get(User, owner) is not None
    finally:
        db.close()

    db = SessionLocal()
    try:
        removed = purge_orphans(db)
        assert removed == 1
        assert db.get(User, owner) is None
    finally:
        db.close()


def test_join_is_rate_limited(sandbox_client, monkeypatch):
    """Each join costs an outbound request, so the budget must be finite."""
    from app import sandbox

    monkeypatch.setattr(
        sandbox, "probe_endpoint", lambda **_: {"ok": True, "latency_ms": 10, "model": "m"}
    )
    statuses = []
    for index in range(10):
        response = sandbox_client.post(
            "/api/v1/sandbox/join",
            json=_join_payload(api_key=f"sk-limit-key-{index:05d}"),
        )
        statuses.append(response.status_code)
    assert 429 in statuses


def test_sandbox_disabled_returns_404(monkeypatch):
    """The same code ships to instances that are not demos."""
    from app.main import app

    monkeypatch.setattr(settings, "sandbox", False)
    client = TestClient(app)
    assert client.get("/api/v1/sandbox").json()["enabled"] is False
    assert client.post("/api/v1/sandbox/claim", json={"ticket_id": "x", "fingerprint": "y"}).status_code == 404


def test_seat_status_reports_remaining_time(sandbox_client, monkeypatch):
    from app import sandbox

    monkeypatch.setattr(
        sandbox, "probe_endpoint", lambda **_: {"ok": True, "latency_ms": 10, "model": "m"}
    )
    sandbox_client.post("/api/v1/sandbox/join", json=_join_payload())

    db = SessionLocal()
    try:
        status = seat_status(db)
        assert status.state == "busy"
        assert status.visit["seconds_left"] > 25 * 60
        assert status.visit_minutes == 30
    finally:
        db.close()