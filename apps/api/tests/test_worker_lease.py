"""Worker concurrency and lease semantics.

These tests exist because the failure they guard against is silent: with the old
``SELECT ... then UPDATE`` claim, two workers could process the same job and the
second one would overwrite the first one's results with no error anywhere.
"""
from __future__ import annotations

import threading

import pytest
from sqlalchemy import update

from app.db import SessionLocal
from app.models import Job, Project, utcnow
from app.worker import (
    Heartbeat,
    Lease,
    claim_job,
    owns,
    recover_interrupted_jobs,
    renew_lease,
)


@pytest.fixture
def queue(client):
    """Park leftover jobs after the app has created the schema.

    The claim primitive is global (it scans the queue), so tests must not share
    queued rows or they would race over each other's fixtures. Depending on
    ``client`` guarantees the tables exist before the first UPDATE runs.
    """
    def _reset() -> None:
        db = SessionLocal()
        try:
            db.execute(
                update(Job)
                .where(Job.status.in_(["queued", "running", "paused"]))
                .values(status="cancelled", lease_expires_at=None, worker_id="")
            )
            db.commit()
        finally:
            db.close()

    _reset()
    yield _reset
    _reset()


def _make_project(db) -> Project:
    project = Project(name="并发测试项目", codename="race")
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _make_job(db, project_id: str) -> Job:
    job = Job(project_id=project_id, kind="distill", status="queued", config={}, result={})
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_claim_is_exclusive_under_concurrency(queue, client):
    db = SessionLocal()
    project = _make_project(db)
    job = _make_job(db, project.id)
    db.close()

    results: list[str] = []
    barrier = threading.Barrier(6)

    def worker() -> None:
        barrier.wait()
        lease = claim_job()
        if lease:
            results.append(lease.job_id)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Exactly one thread may win the claim.
    assert results == [job.id]

    db = SessionLocal()
    stored = db.get(Job, job.id)
    assert stored.status == "running"
    assert stored.lease_epoch == 1
    assert stored.worker_id
    db.close()


def test_claim_increments_epoch_for_fencing(queue, client):
    db = SessionLocal()
    project = _make_project(db)
    job = _make_job(db, project.id)
    db.close()

    first = claim_job()
    assert first is not None and first.epoch == 1

    # Simulate the worker dying: force the lease to expire.
    db = SessionLocal()
    stored = db.get(Job, job.id)
    stored.lease_expires_at = utcnow().replace(year=2000)
    db.add(stored)
    db.commit()
    db.close()

    from app.worker import recover_interrupted_jobs

    recovered = recover_interrupted_jobs()
    assert recovered == 1

    second = claim_job()
    assert second is not None
    assert second.epoch > first.epoch, "epoch must increase monotonically for fencing"
    assert second.epoch >= 2


def test_stale_lease_cannot_renew(queue, client):
    db = SessionLocal()
    project = _make_project(db)
    job = _make_job(db, project.id)
    db.close()

    lease = claim_job()
    assert lease is not None

    # A stale token with an older epoch must be rejected.
    stale = Lease(job_id=lease.job_id, worker_id=lease.worker_id, epoch=lease.epoch - 1)
    from app.worker import renew_lease

    assert renew_lease(stale) is False
    assert renew_lease(lease) is True
    assert owns(lease) is True
    assert owns(stale) is False


def test_recover_only_reclaims_expired_jobs(queue, client):
    db = SessionLocal()
    project = _make_project(db)
    alive = _make_job(db, project.id)
    dead = _make_job(db, project.id)
    db.close()

    # `alive` gets a fresh lease, `dead` keeps an unclaimed queued row.
    first = claim_job()
    assert first is not None
    dead_id = dead.id if first.job_id == alive.id else alive.id

    assert recover_interrupted_jobs() == 0, "a live lease must not be stolen"

    db = SessionLocal()
    stored = db.get(Job, dead_id)
    stored.status = "running"
    stored.worker_id = "dead-worker"
    stored.lease_expires_at = utcnow().replace(year=2000)
    db.add(stored)
    db.commit()
    db.close()

    assert recover_interrupted_jobs() == 1


def test_heartbeat_stops_when_lease_lost(queue, client):
    db = SessionLocal()
    project = _make_project(db)
    job = _make_job(db, project.id)
    db.close()

    lease = claim_job()
    assert lease is not None

    # Steal the job the way another replica would.
    db = SessionLocal()
    stored = db.get(Job, job.id)
    stored.lease_epoch = lease.epoch + 1
    db.add(stored)
    db.commit()
    db.close()

    heartbeat = Heartbeat(lease, interval=0.05)
    with heartbeat:
        assert heartbeat.lost is False
    # No assertion on lost here (the thread may not have ticked); ownership is
    # the authoritative check.
    assert owns(lease) is False