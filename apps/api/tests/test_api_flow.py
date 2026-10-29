from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient

from .conftest import drain_jobs


def test_demo_distill_review_compile_export(client: TestClient):
    demo = client.post("/api/v1/demo")
    assert demo.status_code == 201
    project_id = demo.json()["project_id"]

    distill = client.post(
        f"/api/v1/projects/{project_id}/jobs", json={"kind": "distill"}
    ).json()
    distill = drain_jobs(client, distill["id"])
    assert distill["status"] == "waiting_for_review", distill

    claims = client.get(f"/api/v1/projects/{project_id}/claims").json()
    assert claims, "demo should produce claims"
    assert all(claim["evidence"] for claim in claims), "claims should be grounded"
    assert all(claim["status"] == "proposed" for claim in claims)

    approve = client.post(
        f"/api/v1/projects/{project_id}/claims/bulk-review",
        json={"claim_ids": [claim["id"] for claim in claims], "status": "approved", "reason": "test"},
    )
    assert approve.status_code == 200
    assert approve.json()["updated"] == len(claims)

    persona = client.get(f"/api/v1/projects/{project_id}/persona").json()
    assert persona["approved_claims"] == len(claims)
    assert persona["pending_claims"] == 0

    compile_job = client.post(
        f"/api/v1/projects/{project_id}/jobs", json={"kind": "compile"}
    ).json()
    compile_job = drain_jobs(client, compile_job["id"])
    assert compile_job["status"] == "completed", compile_job

    skills = client.get(f"/api/v1/projects/{project_id}/skills").json()
    assert skills
    for skill in skills:
        assert skill["name"].isascii()
        assert len(skill["name"]) <= 64
        assert "SKILL.md" in skill["files"]
        validation = client.post(f"/api/v1/skills/{skill['id']}/validate").json()
        assert validation["ok"] is True, validation

    exports = client.get(f"/api/v1/projects/{project_id}/exports").json()
    assert exports
    archive = client.get(f"/api/v1/exports/{exports[0]['id']}/download")
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
        names = set(zipped.namelist())
        assert "manifest.json" in names
        assert "README.md" in names
        assert "persona/persona.md" in names
        assert "provenance/source-manifest.json" in names
        assert any(name.endswith("/SKILL.md") for name in names)
        manifest = json.loads(zipped.read("manifest.json"))
        assert manifest["format"] == "persona-package+agentskills"
        assert manifest["skills"]
        combined = b"\n".join(zipped.read(name) for name in names if name.endswith(".md"))
        assert b"sk-" not in combined.lower()


def test_upload_parse_preview_and_redaction(client: TestClient):
    project = client.post("/api/v1/projects", json={"name": "上传测试"}).json()
    content = "# 访谈\n\n我通常先复现问题，再提出假设。\n联系我 test@example.com。\n".encode("utf-8")
    response = client.post(
        f"/api/v1/projects/{project['id']}/sources",
        files=[("files", ("interview.md", content, "text/markdown"))],
    )
    assert response.status_code == 201
    source = response.json()[0]
    assert source["status"] == "parsed"
    assert source["chunk_count"] >= 1
    assert source["redaction_count"] >= 1

    preview = client.get(f"/api/v1/sources/{source['id']}/preview").json()
    assert preview["blocks"]
    assert all("test@example.com" not in block["text"] for block in preview["blocks"])
    assert "[REDACTED:EMAIL]" in preview["blocks"][-1]["text"] or any(
        "[REDACTED:EMAIL]" in block["text"] for block in preview["blocks"]
    )


def test_rerun_does_not_duplicate_claims(client: TestClient):
    demo = client.post("/api/v1/demo").json()
    project_id = demo["project_id"]
    first = client.post(f"/api/v1/projects/{project_id}/jobs", json={"kind": "distill"}).json()
    drain_jobs(client, first["id"])
    claims = client.get(f"/api/v1/projects/{project_id}/claims").json()
    second = client.post(f"/api/v1/projects/{project_id}/jobs", json={"kind": "distill"}).json()
    second = drain_jobs(client, second["id"])
    claims_after = client.get(f"/api/v1/projects/{project_id}/claims").json()
    assert len(claims_after) == len(claims)
    # Re-running on an already-reviewed corpus must succeed and explain itself.
    # Previously it failed with "no claims extracted", which read as a broken
    # source rather than "everything is already known".
    assert second["status"] != "failed", second.get("error")
    extract = next(stage for stage in second["stages"] if stage["stage"] == "s07_extract")
    assert extract["output"]["duplicates"] > 0
    assert extract["output"]["mode"].endswith("_no_new")
    assert extract["output"]["warnings"], "the user needs a reason, not silence"


def test_rerun_keeps_reviewed_status(client: TestClient):
    """Re-distillation must not silently reset human review decisions."""
    demo = client.post("/api/v1/demo").json()
    project_id = demo["project_id"]
    first = client.post(f"/api/v1/projects/{project_id}/jobs", json={"kind": "distill"}).json()
    drain_jobs(client, first["id"])
    claims = client.get(f"/api/v1/projects/{project_id}/claims").json()
    client.post(
        f"/api/v1/projects/{project_id}/claims/bulk-review",
        json={"claim_ids": [claim["id"] for claim in claims], "status": "approved", "reason": "ok"},
    )

    second = client.post(f"/api/v1/projects/{project_id}/jobs", json={"kind": "distill"}).json()
    drain_jobs(client, second["id"])

    after = client.get(f"/api/v1/projects/{project_id}/claims").json()
    assert all(claim["status"] == "approved" for claim in after)
    project = client.get(f"/api/v1/projects/{project_id}").json()
    assert project["approved_count"] == len(after)
    assert project["pending_count"] == 0
    assert project["rejected_count"] == 0


def test_deleting_source_invalidates_its_claims(client: TestClient):
    project = client.post("/api/v1/projects", json={"name": "删除测试"}).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/sources",
        files=[
            (
                "files",
                (
                    "delete-me.md",
                    "# 删除测试\n\n我通常先复现问题，再提出假设。\n".encode("utf-8"),
                    "text/markdown",
                ),
            )
        ],
    )
    source = response.json()[0]
    job = client.post(f"/api/v1/projects/{project['id']}/jobs", json={"kind": "distill"}).json()
    drain_jobs(client, job["id"])
    assert client.get(f"/api/v1/projects/{project['id']}/claims").json()
    deleted = client.delete(f"/api/v1/sources/{source['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/projects/{project['id']}/claims").json() == []


def test_vector_index_and_search(client: TestClient):
    project = client.post("/api/v1/projects", json={"name": "向量测试"}).json()
    documents = {
        "architecture.md": "# 架构\n\n数据库一致性要求在写入前校验版本号，并使用幂等重试。\n",
        "cooking.md": "# 烹饪\n\n番茄炒蛋需要先热锅，再放油，最后加入番茄。\n",
    }
    for name, content in documents.items():
        response = client.post(
            f"/api/v1/projects/{project['id']}/sources",
            files=[("files", (name, content.encode("utf-8"), "text/markdown"))],
        )
        assert response.status_code == 201
    indexed = client.post(f"/api/v1/projects/{project['id']}/index")
    assert indexed.status_code == 200
    assert indexed.json()["indexed"] >= 2
    status = client.get(f"/api/v1/projects/{project['id']}/vector-status").json()
    assert status["embedded"] >= 2
    search = client.get(
        f"/api/v1/projects/{project['id']}/search", params={"q": "数据库一致性", "limit": 5}
    )
    assert search.status_code == 200
    payload = search.json()
    assert payload["results"]
    assert any("数据库一致性" in item["text"] for item in payload["results"])
    assert payload["mode"] in {"vec", "cosine", "keyword"}


def test_provider_crud_masks_key(client: TestClient):
    response = client.post(
        "/api/v1/providers",
        json={
            "name": "测试 Provider",
            "protocol": "openai_responses",
            "base_url": "https://example.invalid/v1",
            "model_id": "mock",
            "api_key": "sk-test-secret-value",
        },
    )
    assert response.status_code == 201
    provider = response.json()
    assert provider["has_api_key"] is True
    assert provider["api_key_mask"] == "已配置"
    assert "sk-test-secret-value" not in json.dumps(provider)
    assert "capabilities" in provider

    updated = client.patch(
        f"/api/v1/providers/{provider['id']}", json={"name": "改名 Provider"}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "改名 Provider"

    deleted = client.delete(f"/api/v1/providers/{provider['id']}")
    assert deleted.status_code == 204
