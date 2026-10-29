from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="distill-tests-"))
os.environ["DISTILL_DATA_DIR"] = str(_TEST_ROOT / "data")
os.environ["DISTILL_EXPORT_DIR"] = str(_TEST_ROOT / "exports")
os.environ["DISTILL_DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'data' / 'test.db').as_posix()}"
os.environ["DISTILL_INLINE_WORKER"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.worker import run_once  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def drain_jobs(client: TestClient, job_id: str, timeout: float = 60.0) -> dict:
    terminal = {"completed", "failed", "cancelled", "waiting_for_review"}
    deadline = time.time() + timeout
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    while time.time() < deadline:
        if job["status"] in terminal:
            return job
        run_once()
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in terminal:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {job}")
