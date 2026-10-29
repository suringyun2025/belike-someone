"""Concurrency-bounded job scheduler.

Why this exists
---------------
A single `while: claim(); run_job()` loop processes exactly one job at a time.
Raising the worker count is not enough either: the deployment target is a 2 vCPU
/ 2 GB host, and a distillation stage holds parsed text plus an ONNX embedding
model in memory. Two concurrent jobs there can push the box into swap, which is
slower than running them one after another.

So the scheduler enforces three limits at once:

1. **Global concurrency** (`max_concurrent_jobs`) — the hard cap the server can
   actually sustain. Extras wait in the queue, they are not rejected.
2. **Per-user concurrency** (`max_jobs_per_user`) — one account cannot occupy
   every slot, so a second user still makes progress.
3. **Memory headroom** (`min_free_mb`) — before claiming, check available RAM;
   if a new job would drop the host below the floor, wait. This turns "the box
   died at 3am" into "the job started a minute later".

Ordering is FIFO by `created_at`, so waiting is fair. Nothing is silently
dropped: a queued job keeps `status='queued'` and the API exposes its position.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from .config import settings
from .db import SessionLocal
from .models import Job, Project, StageRun, utcnow
from .pipeline import run_job

logger = logging.getLogger("distill.worker")

ACTIVE_STATUSES = ("running",)


class Lease:
    """Ownership token for a claimed job.

    ``epoch`` is a fencing token: it increments on every claim, so a worker that
    stalls past its lease cannot overwrite the results of the worker that took
    over. Every state write must be conditioned on the current epoch.
    """

    __slots__ = ("job_id", "worker_id", "epoch", "owner_id")

    def __init__(self, job_id: str, worker_id: str, epoch: int, owner_id: str | None = None) -> None:
        self.job_id = job_id
        self.worker_id = worker_id
        self.epoch = epoch
        self.owner_id = owner_id

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Lease({self.job_id}, epoch={self.epoch})"


# --------------------------------------------------------------------------- #
# Resource awareness
# --------------------------------------------------------------------------- #
def available_memory_mb() -> int | None:
    """Return free memory in MiB, or None when it cannot be determined."""
    try:
        import psutil  # optional dependency

        return int(psutil.virtual_memory().available / (1024 * 1024))
    except Exception:
        pass
    try:
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", encoding="ascii") as handle:
                for line in handle:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def memory_ok() -> tuple[bool, str]:
    """Check the memory floor before admitting a new job."""
    free = available_memory_mb()
    if free is None:
        return True, ""
    floor = settings.min_free_mb
    if free < floor:
        return False, f"可用内存 {free} MB 低于保留下限 {floor} MB"
    return True, ""


# --------------------------------------------------------------------------- #
# Admission control
# --------------------------------------------------------------------------- #
def active_jobs(db) -> int:
    return db.scalar(
        select(func.count()).select_from(Job).where(Job.status.in_(ACTIVE_STATUSES))
    ) or 0


def active_jobs_for(db, owner_id: str | None) -> int:
    if not owner_id:
        return 0
    return db.scalar(
        select(func.count())
        .select_from(Job)
        .join(Project, Project.id == Job.project_id)
        .where(Job.status.in_(ACTIVE_STATUSES), Project.owner_id == owner_id)
    ) or 0


def _next_candidate(db) -> str | None:
    """Oldest queued job whose owner still has capacity.

    Per-user capacity is evaluated in Python because the limit depends on
    settings, not a column. The scan is bounded: with a handful of concurrent
    users, checking the first few dozen rows is enough to find a runnable job and
    avoids an unbounded walk if one user has queued hundreds.
    """
    rows = db.execute(
        select(Job.id, Project.owner_id)
        .join(Project, Project.id == Job.project_id)
        .where(Job.status == "queued", Project.deleted_at.is_(None))
        .order_by(Job.created_at)
        .limit(50)
    ).all()
    per_user: dict[str | None, int] = {}
    for _job_id, owner_id in rows:
        if owner_id not in per_user:
            per_user[owner_id] = active_jobs_for(db, owner_id)
        if per_user[owner_id] < settings.max_jobs_per_user:
            return _job_id
        # Already saturated: keep looking at the next owner.
    return None


def queue_position(db, job) -> dict:
    """Describe where a queued job sits and what it is waiting for.

    Surfaced by the API so the UI can say "queued: 2 jobs ahead, waiting for a
    free slot" instead of showing an indefinite spinner.
    """
    if job.status != "queued":
        return {"position": 0, "ahead": 0, "reason": ""}

    ahead = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.status == "queued", Job.created_at < job.created_at)
    ) or 0
    running = active_jobs(db)
    owner_running = active_jobs_for(db, job.owner_id)
    reason = ""
    if runnable_slots(db) <= 0:
        reason = f"服务器并发已满（{running}/{settings.max_concurrent_jobs}），排队等待"
    elif owner_running >= settings.max_jobs_per_user:
        reason = f"你的并发任务已达上限（{owner_running}/{settings.max_jobs_per_user}）"
    ok, why = memory_ok()
    if not ok:
        reason = f"服务器内存紧张，稍后自动开始（{why}）"
    return {"position": ahead + 1, "ahead": ahead, "reason": reason}


def runnable_slots(db) -> int:
    """How many more jobs may start right now."""
    return max(0, settings.max_concurrent_jobs - active_jobs(db))


def claim_job() -> Lease | None:
    """Atomically claim one queued job that is allowed to start.

    Admission control happens *before* the claim so a rejected job is never
    flipped to `running` and then abandoned. The claim itself stays a conditional
    UPDATE, which is what makes two schedulers safe on the same database.
    """
    if settings.max_concurrent_jobs <= 0:
        return None
    ok, why = memory_ok()
    if not ok:
        logger.debug("admission deferred: %s", why)
        return None

    db = SessionLocal()
    try:
        if active_jobs(db) >= settings.max_concurrent_jobs:
            return None
        job_id = _next_candidate(db)
        if not job_id:
            return None

        now = utcnow()
        lease_until = now + timedelta(seconds=settings.worker_lease_seconds)
        try:
            result = db.execute(
                update(Job)
                .where((Job.id == job_id) & (Job.status == "queued"))
                .values(
                    status="running",
                    worker_id=settings.worker_id,
                    lease_expires_at=lease_until,
                    lease_epoch=Job.lease_epoch + 1,
                    started_at=func.coalesce(Job.started_at, now),
                    error="",
                )
            )
        except OperationalError as exc:  # pragma: no cover - write contention
            db.rollback()
            logger.debug("claim contention on %s: %s", job_id, exc)
            return None

        if result.rowcount != 1:
            db.rollback()
            return None

        row = db.execute(
            select(Job.lease_epoch, Project.owner_id)
            .join(Project, Project.id == Job.project_id)
            .where(Job.id == job_id)
        ).first()
        db.commit()
        epoch = int(row[0]) if row else 0
        owner_id = row[1] if row else None
        logger.info(
            "claimed job %s (epoch %s, active=%s/%s)",
            job_id,
            epoch,
            active_jobs(db),
            settings.max_concurrent_jobs,
        )
        return Lease(job_id=job_id, worker_id=settings.worker_id, epoch=epoch, owner_id=owner_id)
    except IntegrityError:  # pragma: no cover - concurrent claim race
        db.rollback()
        return None
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Lease maintenance
# --------------------------------------------------------------------------- #
def renew_lease(lease: Lease) -> bool:
    """Extend the lease. False means ownership was lost — stop writing."""
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
            .values(lease_expires_at=utcnow() + timedelta(seconds=settings.worker_lease_seconds))
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


def recover_interrupted_jobs() -> int:
    """Return jobs whose owner died back to the queue.

    Only expired leases are reclaimed, so a healthy worker is never stolen from.
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
        db.execute(update(StageRun).where(StageRun.status == "running").values(status="pending"))
        db.commit()
        count = stale.rowcount or 0
        if count:
            logger.warning("recovered %s job(s) with expired lease", count)
        return count
    finally:
        db.close()


class Heartbeat:
    """Background lease renewal for long provider calls."""

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


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #
def execute_lease(lease: Lease) -> None:
    """Run one claimed job to completion, then release its slot."""
    try:
        with Heartbeat(lease):
            run_job(lease.job_id, lease=lease, owns=lambda: owns(lease))
    except Exception as exc:  # pragma: no cover - never kill the scheduler
        logger.exception("job %s crashed: %s", lease.job_id, exc)
        # Mark it failed so the slot is not held by a zombie row.
        db = SessionLocal()
        try:
            job = db.get(Job, lease.job_id)
            if job and job.status == "running":
                job.status = "failed"
                job.error = f"任务执行异常：{str(exc)[:500]}"
                job.finished_at = utcnow()
                job.lease_expires_at = None
                db.add(job)
                db.commit()
        finally:
            db.close()
    finally:
        try:
            release_lease(lease)
        except Exception:
            pass


def run_once() -> bool:
    """Claim and execute a single job synchronously. Returns True if work ran."""
    lease = claim_job()
    if not lease:
        return False
    execute_lease(lease)
    return True


def _supervise(active: dict[str, threading.Thread], lease: Lease, stop_event: threading.Event) -> None:
    def _target() -> None:
        try:
            execute_lease(lease)
        finally:
            active.pop(lease.job_id, None)

    thread = threading.Thread(target=_target, daemon=True, name=f"job-{lease.job_id}")
    active[lease.job_id] = thread
    thread.start()


def worker_loop(stop_event: threading.Event) -> None:
    """Concurrency-bounded scheduler.

    Starts up to ``max_concurrent_jobs`` jobs in parallel threads and keeps
    refilling freed slots. Jobs beyond the cap stay queued rather than being
    rejected, which is what makes the behaviour "queue and wait" rather than
    "fail fast".
    """
    logger.info(
        "scheduler %s started (max_concurrent=%s, per_user=%s, lease=%ss, mem_floor=%sMB)",
        settings.worker_id,
        settings.max_concurrent_jobs,
        settings.max_jobs_per_user,
        settings.worker_lease_seconds,
        settings.min_free_mb,
    )
    try:
        recover_interrupted_jobs()
    except Exception as exc:  # pragma: no cover - startup resilience
        logger.warning("job recovery failed: %s", exc)

    active: dict[str, threading.Thread] = {}
    while not stop_event.is_set():
        # Reap finished threads so slots free up promptly.
        for job_id, thread in list(active.items()):
            if not thread.is_alive():
                active.pop(job_id, None)

        claimed_any = False
        while len(active) < settings.max_concurrent_jobs and not stop_event.is_set():
            lease = claim_job()
            if not lease:
                break
            _supervise(active, lease, stop_event)
            claimed_any = True

        if not claimed_any and not active:
            stop_event.wait(settings.worker_poll_seconds)
        else:
            # Still poll while jobs run, cheaper than being woken per completion.
            stop_event.wait(min(settings.worker_poll_seconds, 1.0))

    # Graceful shutdown: let in-flight jobs finish rather than orphaning leases.
    if active:
        logger.info("waiting for %s in-flight job(s) to finish", len(active))
        deadline = time.time() + 30
        for thread in list(active.values()):
            remaining = max(0.1, deadline - time.time())
            thread.join(timeout=remaining)
    logger.info("scheduler %s stopped", settings.worker_id)


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