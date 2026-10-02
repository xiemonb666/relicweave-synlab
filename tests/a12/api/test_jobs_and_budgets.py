"""``POST /jobs`` idempotency, budgets, capability gating and job control."""

from __future__ import annotations

import pytest
from conftest import create_job, run_worker_once, valid_spec

from synlab.api.capabilities import probe_capability


def test_budget_reports_infeasible_as_budget_exceeded(researcher):
    response = researcher.post("/api/synlab/budgets",
                               json={"spec": valid_spec(), "stage": "generate",
                                     "planned_jobs": 100000})
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "BUDGET_EXCEEDED"
    assert error["details"]["budget"]["feasible"] is False
    assert error["details"]["budget"]["rss_gb"] > error["details"]["budget"]["rss_budget_gb"]


def test_budget_returns_a_reference_for_a_feasible_plan(researcher):
    response = researcher.post("/api/synlab/budgets",
                               json={"spec": valid_spec(), "stage": "freeze_spec",
                                     "planned_jobs": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["feasible"] is True
    assert body["budget_ref"].startswith("budget_")
    assert body["note"].startswith("development initial values")


def test_jobs_idempotent_replay_returns_the_original_job(researcher):
    first = create_job(researcher, stage="freeze_spec", key="idem-key-1")
    assert first.status_code == 202, first.text
    second = create_job(researcher, stage="freeze_spec", key="idem-key-1")
    assert second.status_code == 202
    assert second.json()["idempotent_replay"] is True
    assert second.json()["run_id"] == first.json()["run_id"]
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["created"] is False


def test_jobs_same_key_different_payload_is_a_conflict(researcher):
    assert create_job(researcher, stage="freeze_spec", key="idem-key-2").status_code == 202
    response = create_job(researcher, stage="freeze_spec", key="idem-key-2",
                          spec=valid_spec(master_seed=999))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_jobs_rejects_unknown_fields_and_invalid_spec(researcher):
    payload = {"schema_version": "synlab.v3", "idempotency_key": "k", "stage": "freeze_spec",
               "spec": valid_spec(), "surprise": True}
    assert researcher.post("/api/synlab/jobs", json=payload).status_code == 422
    bad_spec = valid_spec()
    bad_spec["not_a_field"] = 1
    response = create_job(researcher, stage="freeze_spec", spec=bad_spec)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SCHEMA_INVALID"


def test_jobs_capability_gate_is_fail_closed(researcher):
    """A stage whose modules are not importable must create nothing at all."""
    missing_stage = None
    for stage, capability in (("mother", "mothers"), ("fracture", "fracture"),
                              ("degrade", "degrade"), ("diagnostics", "diagnostics")):
        if not probe_capability(capability).available:
            missing_stage = (stage, capability)
            break
    if missing_stage is None:
        pytest.skip("every probed capability is importable in this checkout")
    stage, capability = missing_stage
    before = researcher.get("/api/synlab/jobs").json()["count"]
    response = create_job(researcher, stage=stage)
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DEPENDENCY_CAPABILITY_MISSING"
    assert capability in [m["capability"] for m in error["details"]["missing_capabilities"]]
    after = researcher.get("/api/synlab/jobs").json()["count"]
    assert after == before, "a rejected request must not create a half-built run"


def test_jobs_unknown_stage_is_rejected(researcher):
    response = create_job(researcher, stage="teleport")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_freeze_spec_job_runs_in_a_worker_and_commits_a_real_asset(researcher, store_root, cube_asset):
    created = create_job(researcher, stage="freeze_spec", key="freeze-1",
                         input_refs=[_cube(researcher)])
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    assert created.json()["events_url"].endswith(f"/runs/{created.json()['run_id']}/events")

    pending = researcher.get(f"/api/synlab/jobs/{job_id}").json()
    assert pending["job"]["state"] == "PENDING"

    report = run_worker_once(store_root)
    assert report["processed"] >= 1

    done = researcher.get(f"/api/synlab/jobs/{job_id}").json()
    assert done["job"]["state"] == "COMMITTED"
    assert done["job"]["outputs"], "a committed job must reference its output assets"
    output = done["job"]["outputs"][0]
    asset = researcher.get(f"/api/synlab/assets/{output}").json()["asset"]
    assert asset["role"] == "run_spec"
    assert asset["qa_status"] == "QA_PASS"
    assert asset["integrity"]["ok"] is True
    assert asset["meta"]["spec_hash"].startswith("sha256:")


def _cube(client) -> str:
    return client.get("/api/synlab/assets", params={"role": "mother_mesh"}).json()["items"][0]["asset_id"]


def test_job_listing_pagination_cursor_is_stable(researcher, store_root):
    for index in range(5):
        assert create_job(researcher, stage="freeze_spec", key=f"page-{index}").status_code == 202
    first = researcher.get("/api/synlab/jobs", params={"limit": 2}).json()
    assert first["count"] == 2 and first["has_more"] is True
    seen = [item["job_id"] for item in first["items"]]
    cursor = first["next_cursor"]
    while cursor:
        page = researcher.get("/api/synlab/jobs", params={"limit": 2, "cursor": cursor}).json()
        seen.extend(item["job_id"] for item in page["items"])
        cursor = page["next_cursor"] if page["has_more"] else None
    assert len(seen) == len(set(seen)) == 5
    assert first["order"] == "created_at.asc,id.asc"
    assert first["limit"] == 2


def test_job_listing_rejects_oversized_limit_and_bad_cursor(researcher):
    over = researcher.get("/api/synlab/jobs", params={"limit": 100000})
    assert over.status_code == 422
    bad = researcher.get("/api/synlab/jobs", params={"cursor": "not-a-cursor"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "INVALID_CURSOR"
    wrong_kind = researcher.get("/api/synlab/assets", params={"cursor": _job_cursor(researcher)})
    assert wrong_kind.status_code == 400


def _job_cursor(client) -> str:
    for index in range(3):
        create_job(client, stage="freeze_spec", key=f"cursor-{index}")
    page = client.get("/api/synlab/jobs", params={"limit": 1}).json()
    return page["next_cursor"]


def test_pause_resume_cancel_keep_committed_outputs(researcher, store_root):
    created = create_job(researcher, stage="freeze_spec", key="control-1").json()
    job_id = created["job_id"]
    run_id = created["run_id"]

    paused = researcher.post(f"/api/synlab/jobs/{job_id}/pause", json={"reason": "maintenance"})
    assert paused.status_code == 200
    assert paused.json()["run_status"] == "PAUSED"
    assert job_id in paused.json()["jobs_not_started"]

    resumed = researcher.post(f"/api/synlab/jobs/{job_id}/resume", json={})
    assert resumed.status_code == 200
    assert resumed.json()["run_status"] == "RUNNING"

    revision = resumed.json()["revision"]
    conflict = researcher.post(f"/api/synlab/jobs/{job_id}/pause",
                               json={"revision": revision + 99})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "REVISION_CONFLICT"

    assert researcher.post(f"/api/synlab/jobs/{job_id}/resume", json={}).status_code == 409

    run_worker_once(store_root)
    assert researcher.get(f"/api/synlab/jobs/{job_id}").json()["job"]["state"] == "COMMITTED"

    cancelled = researcher.post(f"/api/synlab/jobs/{job_id}/cancel", json={"reason": "stop"})
    assert cancelled.status_code == 200
    assert cancelled.json()["run_status"] == "CANCELLED"
    assert cancelled.json()["committed_jobs_kept"] == [job_id]
    still = researcher.get(f"/api/synlab/jobs/{job_id}").json()["job"]["state"]
    assert still == "COMMITTED", "cancel must never delete committed data"


def test_retry_only_for_explicitly_retryable_failures(researcher):
    created = create_job(researcher, stage="freeze_spec", key="retry-1").json()
    job_id = created["job_id"]
    response = researcher.post(f"/api/synlab/jobs/{job_id}/retry", json={"reason": "why not"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STATE_CONFLICT"
    assert "retryable" in response.json()["error"]["message"]


def test_unknown_job_is_404(researcher):
    response = researcher.get("/api/synlab/jobs/job_does_not_exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
