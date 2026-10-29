from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from .config import settings
from .db import SessionLocal
from .models import Job, StageRun, utcnow
from .pipeline import run_job

logger = logging.getLogger("distill.worker")


@dataclass(frozen=True)
class Lease:
    """Ownership token for a claimed job.

    ``epoch`` is a fencing token: it increments on every claim, so a worker that
    stalls past its lease cannot overwrite the results of the worker that took
    over. Every state write must be conditioned on the current epoch.
    """

    job_id: str
    worker_id: str
    epoch: int


def recover_interrupted_jobs() -> int:
    """Return jobs whose owning worker died back to the queue.

    Only jobs with an expired lease are reclaimed, so a healthy worker in
    another replica is never stolen from. The epoch is bumped here as well, which
    invalidates any late write from the dead worker.
    """
    db = SessionLocal()
    try:
        now = utcnow()
        stale = db.execute(
            update(Job)
            .where(
                (Job.status == "running")
                & ((Job.lease_expires_at.is_(None)) | (Job.lease_expires_at < now))
            )
            .values(
                status="queued",
                error="",
                worker_id="",
                lease_expires_at=None,
                lease_epoch=Job.lease_epoch + 1,
            )
        )
        db.execute(
            update(StageRun).where(StageRun.status == "running").values(status="pending")
        )
        db.commit()
        count = stale.rowcount or 0
        if count:
            logger.warning("recovered %s job(s) with expired lease", count)
        return count
    finally:
        db.close()


def claim_job() -> Lease | None:
    """Atomically claim one queued job.

    The conditional ``UPDATE ... WHERE status='queued'`` is the atomicity
    primitive: two workers racing on the same row produce exactly one
    ``rowcount == 1``. This works on SQLite (single writer) and PostgreSQL
    (row lock) without depending on ``FOR UPDATE SKIP LOCKED`` or on
    ``RETURNING`` support, which older SQLite builds lack.

    The epoch is incremented inside the same statement, so no window exists in
    which a job is running under an epoch another worker could reuse.
    """
    db = SessionLocal()
    try:
        now = utcnow()
        lease_until = now + timedelta(seconds=settings.worker_lease_seconds)
        candidates = db.scalars(
            select(Job.id).where(Job.status == "queued").order_by(Job.created_at).limit(5)
        ).all()
        for job_id in candidates:
            try:
                result = db.execute(
                    update(Job)
                    .where((Job.id == job_id) & (Job.status == "queued"))
                    .values(
                        status="running",
                        worker_id=settings.worker_id,
                        lease_expires_at=lease_until,
                        lease_epoch=Job.lease_epoch + 1,
                        # Preserve the original start time across retries.
                        started_at=func.coalesce(Job.started_at, now),
                        error="",
                    )
                )
            except OperationalError as exc:  # pragma: no cover - write contention
                db.rollback()
                logger.debug("claim contention on %s: %s", job_id, exc)
                continue
            if result.rowcount == 1:
                epoch = db.scalar(select(Job.lease_epoch).where(Job.id == job_id)) or 0
                db.commit()
                logger.info("claimed job %s (epoch %s)", job_id, epoch)
                return Lease(job_id=job_id, worker_id=settings.worker_id, epoch=int(epoch))
            db.rollback()
        return None
    except IntegrityError:  # pragma: no cover - concurrent claim race
        db.rollback()
        return None
    finally:
        db.close()


def renew_lease(lease: Lease) -> bool:
    """Extend the lease. Returns False when ownership was lost.

    A False result means another worker reclaimed the job, so the caller must
    stop writing immediately instead of finishing with stale data.
    """
    db = SessionLocal()
    try:
        result = db.execute(
            update(Job)
            .where(
                (Job.id == lease.job_id)
                & (Job.worker_id == lease.worker_id)
                & (Job.lease_epoch == lease.epoch)
                & (Job.status == "running")
            )
            .values(
                lease_expires_at=utcnow() + timedelta(seconds=settings.worker_lease_seconds)
            )
        )
        db.commit()
        return (result.rowcount or 0) == 1
    finally:
        db.close()


def release_lease(lease: Lease) -> None:
    db = SessionLocal()
    try:
        db.execute(
            update(Job)
            .where((Job.id == lease.job_id) & (Job.lease_epoch == lease.epoch))
            .values(lease_expires_at=None, worker_id="")
        )
        db.commit()
    finally:
        db.close()


def owns(lease: Lease) -> bool:
    """Check whether this worker still owns the job."""
    db = SessionLocal()
    try:
        row = db.scalar(
            select(Job.lease_epoch).where(
                (Job.id == lease.job_id)
                & (Job.worker_id == lease.worker_id)
                & (Job.status == "running")
            )
        )
        return row is not None and int(row) == lease.epoch
    finally:
        db.close()


class Heartbeat:
    """Background lease renewal for long provider calls.

    Renewing only between stages is not enough: a single extraction stage can run
    for minutes. A daemon thread keeps the lease alive and flips ``lost`` when
    ownership disappears.
    """

    def __init__(self, lease: Lease, interval: float | None = None) -> None:
        self.lease = lease
        self.interval = interval or max(5.0, settings.worker_lease_seconds / 3)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.lost = False

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                if not renew_lease(self.lease):
                    self.lost = True
                    logger.warning(
                        "lease lost for job %s (epoch %s)", self.lease.job_id, self.lease.epoch
                    )
                    return
            except Exception as exc:  # pragma: no cover - transient DB errors
                logger.debug("lease renewal failed: %s", exc)

    def __enter__(self) -> "Heartbeat":
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"lease-{self.lease.job_id}"
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def run_once() -> bool:
    """Claim and execute a single job. Returns True when work was done."""
    lease = claim_job()
    if not lease:
        return False
    try:
        with Heartbeat(lease):
            run_job(lease.job_id, lease=lease, owns=lambda: owns(lease))
    except Exception as exc:  # pragma: no cover - never kill the loop
        logger.exception("job %s crashed: %s", lease.job_id, exc)
    finally:
        try:
            release_lease(lease)
        except Exception:
            pass
    return True


def worker_loop(stop_event: threading.Event) -> None:
    logger.info("worker %s started", settings.worker_id)
    try:
        recover_interrupted_jobs()
    except Exception as exc:  # pragma: no cover - startup resilience
        logger.warning("job recovery failed: %s", exc)
    while not stop_event.is_set():
        try:
            worked = run_once()
        except Exception as exc:  # pragma: no cover - keep the loop alive
            logger.exception("worker iteration failed: %s", exc)
            worked = False
        if not worked:
            stop_event.wait(settings.worker_poll_seconds)
        else:
            time.sleep(0.05)
    logger.info("worker %s stopped", settings.worker_id)


def main() -> None:
    from .logging_setup import configure_logging

    configure_logging()
    stop_event = threading.Event()
    try:
        worker_loop(stop_event)
    except KeyboardInterrupt:
        stop_event.set()


if __name__ == "__main__":
    main()