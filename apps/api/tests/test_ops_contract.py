"""Contract tests for the operational surface added in 0.2.

Every item here corresponds to a claim made in the README; if the behaviour
regresses the documentation becomes wrong, so it is pinned by a test.
"""
from __future__ import annotations

import io


def test_health_does_not_touch_database(client):
    """Liveness must stay cheap and independent of the database.

    A container orchestrator restarting pods because the DB is briefly slow is a
    classic own goal, so /health deliberately reports only process state.
    """
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "uptime_seconds" in body
    assert "database" not in body


def test_ready_reports_component_checks(client):
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    checks = body["checks"]
    assert checks["database"]["status"] == "ok"
    assert checks["data_dir"]["status"] == "ok"
    assert "vector" in checks


def test_request_id_is_echoed(client):
    response = client.get("/api/v1/health")
    assert response.headers.get("x-request-id")
    supplied = client.get("/api/v1/health", headers={"x-request-id": "trace-abc"})
    assert supplied.headers["x-request-id"] == "trace-abc"


def test_error_payload_has_stable_code_and_legacy_detail(client):
    """The frontend reads `detail`; orchestrators read `error.code`."""
    response = client.get("/api/v1/projects/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == body["detail"]
    assert body["error"]["request_id"]


def test_validation_error_lists_fields(client):
    response = client.post("/api/v1/projects", json={"name": ""})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["errors"]


def test_oversized_upload_is_rejected_and_cleaned_up(client, monkeypatch):
    from app.config import settings
    from pathlib import Path
    import tempfile

    temp_root = Path(tempfile.gettempdir())
    before = {path.name for path in temp_root.glob("distill-upload-*")}

    monkeypatch.setattr(settings, "max_upload_mb", 1)
    project = client.post("/api/v1/projects", json={"name": "上传测试"}).json()
    payload = b"a" * (2 * 1024 * 1024)
    files = [("files", ("big.txt", io.BytesIO(payload), "text/plain"))]
    response = client.post(f"/api/v1/projects/{project['id']}/sources", files=files)
    assert response.status_code == 413
    assert response.json()["error"]["message"].startswith("big.txt")

    # The streaming spooler must delete the partial temp file on rejection.
    # Compare against the pre-test snapshot so an unrelated leftover from an
    # earlier crashed run cannot make this test fail.
    after = {path.name for path in temp_root.glob("distill-upload-*")}
    assert after - before == set()


def test_chunk_can_be_excluded_from_future_runs(client):
    demo = client.post("/api/v1/demo").json()
    project_id = demo["project_id"]
    sources = client.get(f"/api/v1/projects/{project_id}/sources").json()
    chunks = client.get(f"/api/v1/sources/{sources[0]['id']}/chunks").json()
    assert chunks, "demo source should produce chunks"
    target = chunks[0]["id"]

    response = client.patch(f"/api/v1/chunks/{target}", json={"excluded": True})
    assert response.status_code == 200
    assert response.json()["excluded"] is True

    refreshed = client.get(f"/api/v1/sources/{sources[0]['id']}/chunks").json()
    matching = [chunk for chunk in refreshed if chunk["id"] == target]
    assert matching and matching[0]["excluded"] is True

    audit = client.get(f"/api/v1/projects/{project_id}/audit").json()
    assert any(event["action"] == "chunk.exclude" for event in audit)


def test_usage_endpoint_reports_no_fabricated_numbers(client):
    response = client.get("/api/v1/usage")
    assert response.status_code == 200
    body = response.json()
    # Without a configured model nothing was ever called, so totals stay zero
    # rather than showing an estimate.
    assert body["totals"]["calls"] == 0
    assert "未返回时不估算" in body["note"]


def test_stats_exposes_runtime_shape(client):
    body = client.get("/api/v1/stats").json()
    assert body["runtime"]["version"]
    assert body["runtime"]["database"] in {"sqlite", "postgresql"}
    assert "lease_seconds" in body["runtime"]