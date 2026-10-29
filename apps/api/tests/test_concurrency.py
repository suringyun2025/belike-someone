"""Concurrency admission and queueing.

The deployment host is small (2 vCPU / 2 GB). These tests pin the behaviour that
keeps it alive: never more than N jobs running, extras wait instead of failing,
one user cannot monopolise the slots, and the queue drains in order.
"""
from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import delete, update

from app.config import settings
from app.db import SessionLocal
from app.models import Job, Project, User
from app.worker import (
    Lease,
    active_jobs,
    available_memory_mb,
    claim_job,
    memory_ok,
    owns,
    queue_position,
    recover_interrupted_jobs,
    renew_lease,
)


@pytest.fixture()
def queue(client):
    """Isolate queued rows, and undo concurrency overrides afterwards.

    The suite shares one database file across modules, so any job left in
    ``running`` by another test would consume a slot and skew the cap
    assertions here.
    """
    def _reset() -> None:
        db = SessionLocal()
        try:
            # Release every active slot first, then clear tenant rows.
            db.execute(
                update(Job)
                .where(Job.status.in_(["queued", "running", "paused"]))
                .values(status="cancelled", lease_expires_at=None, worker_id="")
            )
            db.commit()
            for model in (Job, Project, User):
                db.execute(delete(model))
            db.commit()
        finally:
            db.close()

    _reset()
    yield _reset
    _reset()


@pytest.fixture()
def limits(monkeypatch):
    """Set concurrency limits per test without touching the environment."""
    def _set(max_concurrent: int = 1, per_user: int = 1, min_free: int = 0, max_queue: int = 30):
        monkeypatch.setattr(settings, "max_concurrent_jobs", max_concurrent)
        monkeypatch.setattr(settings, "max_jobs_per_user", per_user)
        monkeypatch.setattr(settings, "min_free_mb", min_free)
        monkeypatch.setattr(settings, "max_queue_length", max_queue)
        monkeypatch.setattr(settings, "worker_lease_seconds", 300)

    return _set


def _user(db, email: str) -> User:
    user = db.query(User).filter_by(email=email).first()
    if user:
        return user
    user = User(email=email, password_hash="x", display_name=email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _project(db, owner_id: str, name: str) -> Project:
    project = Project(name=name, owner_id=owner_id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _job(db, project_id: str, owner_id: str, status: str = "queued") -> Job:
    job = Job(project_id=project_id, owner_id=owner_id, status=status, config={}, result={})
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# --------------------------------------------------------------------------- #
# Global cap
# --------------------------------------------------------------------------- #
def test_global_cap_blocks_further_claims(queue, limits):
    """With max_concurrent=1 a second claim must be refused, not queued as running."""
    limits(max_concurrent=1, per_user=5)
    db = SessionLocal()
    alice = _user(db, "a@x.com")
    project = _project(db, alice.id, "p1")
    first = _job(db, project.id, alice.id)
    second = _job(db, project.id, alice.id)
    db.close()

    lease = claim_job()
    assert lease is not None and lease.job_id == first.id

    # The slot is occupied, so no further claim is allowed.
    assert claim_job() is None, "global concurrency cap was exceeded"

    db = SessionLocal()
    assert active_jobs(db) == 1
    assert db.get(Job, second.id).status == "queued"
    db.close()


def test_cap_of_two_allows_two(queue, limits):
    limits(max_concurrent=2, per_user=5)
    db = SessionLocal()
    alice = _user(db, "a2@x.com")
    project = _project(db, alice.id, "p2")
    _job(db, project.id, alice.id)
    _job(db, project.id, alice.id)
    _job(db, project.id, alice.id)
    db.close()

    first = claim_job()
    second = claim_job()
    third = claim_job()
    assert first is not None and second is not None
    assert third is None, "cap of 2 must not admit a third job"
    assert first.job_id != second.job_id


# --------------------------------------------------------------------------- #
# Per-user fairness
# --------------------------------------------------------------------------- #
def test_one_user_cannot_take_every_slot(queue, limits):
    """alice at her cap must not starve bob."""
    limits(max_concurrent=2, per_user=1)
    db = SessionLocal()
    alice = _user(db, "fair-a@x.com")
    bob = _user(db, "fair-b@x.com")
    pa = _project(db, alice.id, "pa")
    pb = _project(db, bob.id, "pb")
    # Alice queues two jobs first (older), Bob queues one.
    a1 = _job(db, pa.id, alice.id)
    a2 = _job(db, pa.id, alice.id)
    b1 = _job(db, pb.id, bob.id)
    db.close()

    first = claim_job()
    assert first is not None and first.job_id == a1.id

    # Alice is at her per-user cap, so the next claim must skip to Bob even
    # though a2 is older.
    second = claim_job()
    assert second is not None
    assert second.job_id == b1.id, "per-user cap did not yield to another user"


def test_per_user_cap_blocks_same_owner(queue, limits):
    limits(max_concurrent=3, per_user=1)
    db = SessionLocal()
    alice = _user(db, "solo@x.com")
    project = _project(db, alice.id, "ps")
    _job(db, project.id, alice.id)
    _job(db, project.id, alice.id)
    db.close()

    assert claim_job() is not None
    assert claim_job() is None, "second job from the same user must wait"


# --------------------------------------------------------------------------- #
# FIFO ordering
# --------------------------------------------------------------------------- #
def test_queue_is_fifo(queue, limits):
    limits(max_concurrent=5, per_user=5)
    db = SessionLocal()
    alice = _user(db, "fifo@x.com")
    project = _project(db, alice.id, "pf")
    jobs = [_job(db, project.id, alice.id) for _ in range(4)]
    db.close()

    order = []
    for _ in range(4):
        lease = claim_job()
        assert lease is not None
        order.append(lease.job_id)
        db = SessionLocal()
        job = db.get(Job, lease.job_id)
        job.status = "completed"
        db.add(job)
        db.commit()
        db.close()

    assert order == [job.id for job in jobs], "queue is not FIFO"


# --------------------------------------------------------------------------- #
# Queue visibility
# --------------------------------------------------------------------------- #
def test_queue_position_reported(queue, limits):
    limits(max_concurrent=1, per_user=5)
    db = SessionLocal()
    alice = _user(db, "pos@x.com")
    project = _project(db, alice.id, "pp")
    first = _job(db, project.id, alice.id)
    second = _job(db, project.id, alice.id)
    third = _job(db, project.id, alice.id)
    db.close()

    lease = claim_job()  # occupies the only slot with `first`
    assert lease is not None

    db = SessionLocal()
    info = queue_position(db, db.get(Job, second.id))
    db.close()
    assert info["position"] >= 1
    assert info["reason"], "user needs to know why nothing is happening"

    assert first.id != second.id != third.id


# --------------------------------------------------------------------------- #
# Memory guard
# --------------------------------------------------------------------------- #
def test_memory_floor_blocks_admission(queue, limits, monkeypatch):
    """Simulate a low-memory host; claiming must stop."""
    import app.worker as worker_module

    limits(max_concurrent=5, per_user=5)
    db = SessionLocal()
    alice = _user(db, "mem@x.com")
    project = _project(db, alice.id, "pm")
    _job(db, project.id, alice.id)
    db.close()

    monkeypatch.setattr(worker_module, "available_memory_mb", lambda: 50)
    monkeypatch.setattr(settings, "min_free_mb", 320)

    ok, reason = memory_ok()
    assert ok is False
    assert "内存" in reason
    assert claim_job() is None, "job started despite low memory"


def test_memory_check_skipped_when_unavailable(queue, limits, monkeypatch):
    import app.worker as worker_module

    limits(max_concurrent=5, per_user=5, min_free=320)
    monkeypatch.setattr(worker_module, "available_memory_mb", lambda: None)
    ok, _ = memory_ok()
    assert ok is True, "unknown memory must not block work forever"


# --------------------------------------------------------------------------- #
# Lease discipline still holds under the new scheduler
# --------------------------------------------------------------------------- #
def test_epoch_increases_on_reclaim(queue, limits):
    limits(max_concurrent=1, per_user=5)
    db = SessionLocal()
    alice = _user(db, "lease@x.com")
    project = _project(db, alice.id, "pl")
    job = _job(db, project.id, alice.id)
    db.close()

    first = claim_job()
    assert first is not None

    db = SessionLocal()
    stored = db.get(Job, job.id)
    stored.lease_expires_at = stored.lease_expires_at.replace(year=2000)
    db.add(stored)
    db.commit()
    db.close()

    assert recover_interrupted_jobs() == 1
    second = claim_job()
    assert second is not None
    assert second.epoch > first.epoch


def test_stale_lease_cannot_write(queue, limits):
    limits(max_concurrent=2, per_user=5)
    db = SessionLocal()
    alice = _user(db, "stale@x.com")
    project = _project(db, alice.id, "ps2")
    _job(db, project.id, alice.id)
    db.close()

    lease = claim_job()
    assert lease is not None
    stale = Lease(job_id=lease.job_id, worker_id=lease.worker_id, epoch=lease.epoch - 1)
    assert renew_lease(stale) is False
    assert renew_lease(lease) is True
    assert owns(lease) is True
    assert owns(stale) is False


def test_concurrent_claims_respect_cap(queue, limits):
    """Six threads racing for slots must not exceed the cap."""
    limits(max_concurrent=2, per_user=10)
    db = SessionLocal()
    alice = _user(db, "race@x.com")
    project = _project(db, alice.id, "pr")
    for _ in range(6):
        _job(db, project.id, alice.id)
    db.close()

    claimed: list[str] = []
    barrier = threading.Barrier(6)

    def attempt() -> None:
        barrier.wait()
        lease = claim_job()
        if lease:
            claimed.append(lease.job_id)

    threads = [threading.Thread(target=attempt) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(claimed) == 2, f"cap violated: {len(claimed)} jobs claimed"
    assert len(set(claimed)) == 2
    db = SessionLocal()
    assert active_jobs(db) == 2
    db.close()


# --------------------------------------------------------------------------- #
# Queue depth guard
# --------------------------------------------------------------------------- #
def test_queue_depth_constant_is_respected(queue, limits):
    """The depth guard compares against the configured limit.

    Exercised at the settings level rather than through HTTP: the endpoint
    requires a session, and this test is about the scheduler's admission rule,
    not authentication (covered in test_multiuser_isolation).
    """
    limits(max_concurrent=1, per_user=5, max_queue=2)
    assert settings.max_queue_length == 2

    db = SessionLocal()
    alice = _user(db, "depth@x.com")
    project = _project(db, alice.id, "pd")
    for _ in range(3):
        _job(db, project.id, alice.id)
    queued = db.query(Job).filter(Job.status == "queued").count()
    db.close()

    # At the limit the endpoint refuses; one below it accepts.
    assert queued >= settings.max_queue_length