"""Run-level claim and control boundaries for the A12 job scheduler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synlab.errors import ErrorCode, SynLabError
from synlab.jobs.scheduler import Scheduler
from synlab.jobs.state import JobState
from synlab.storage.store import AssetStore
from tests.a12.api.api_test_support import create_job, make_client, valid_spec


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir(parents=True)
    return root


def _new_scheduled_job(store: AssetStore, run_id: str = "run_test") -> tuple[Scheduler, str]:
    store.create_run(run_id, "sha256:test", "SYNTHETIC")
    scheduler = Scheduler(store, owner="test-worker")
    job_id = f"job_{run_id}"
    scheduler.create_job(job_id=job_id, run_id=run_id, stage="freeze_spec", spec={})
    return scheduler, job_id


def _job_and_events(store: AssetStore, job_id: str):
    with store.connect() as conn:
        job = tuple(conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())
        events = [tuple(row) for row in conn.execute(
            "SELECT * FROM events WHERE job_id=? ORDER BY event_seq", (job_id,)).fetchall()]
    return job, events


@pytest.mark.parametrize("run_status", ["PAUSED", "CANCELLED", "FAILED", "QA_PASSED", "UNRECOGNIZED"])
def test_paused_cancelled_terminal_and_unknown_runs_filter_ready_and_reject_claim(
        store_root: Path, run_status: str):
    store = AssetStore(store_root)
    scheduler, job_id = _new_scheduled_job(store)
    assert [job.job_id for job in scheduler.ready()] == [job_id]
    store.set_run_status("run_test", run_status)

    before = _job_and_events(store, job_id)
    assert scheduler.ready() == []
    with pytest.raises(SynLabError) as exc:
        scheduler.claim(job_id)
    assert exc.value.code == ErrorCode.LEASE_STALE
    assert _job_and_events(store, job_id) == before
    job = scheduler.get_job(job_id)
    assert (job.state, job.attempt, job.fencing, job.owner, job.lease_token) == (
        JobState.PENDING.value, 0, 0, None, None)


def test_missing_run_is_not_ready_or_claimable(store_root: Path):
    store = AssetStore(store_root)
    scheduler, job_id = _new_scheduled_job(store)
    with store.connect() as conn:
        conn.execute("DELETE FROM runs WHERE run_id=?", ("run_test",))
    before = _job_and_events(store, job_id)
    assert scheduler.ready() == []
    with pytest.raises(SynLabError) as exc:
        scheduler.claim(job_id)
    assert exc.value.code == ErrorCode.LEASE_STALE
    assert "missing" in exc.value.message
    assert _job_and_events(store, job_id) == before


@pytest.mark.parametrize("initial_status", ["PENDING", "ACCEPTED", "RUNNING"])
def test_existing_schedulable_run_states_still_claim_and_resume_allows_claim(
        store_root: Path, initial_status: str):
    store = AssetStore(store_root)
    scheduler, job_id = _new_scheduled_job(store)
    if initial_status != "PENDING":
        store.set_run_status("run_test", initial_status)
    assert [job.job_id for job in scheduler.ready()] == [job_id]
    claimed, token, fence = scheduler.claim(job_id)
    assert (claimed.state, claimed.attempt, claimed.fencing) == ("RUNNING", 1, 1)
    assert token and fence == 1

    # A paused run holds jobs in place; restoring the existing RUNNING control state
    # makes the same PENDING job eligible again without changing the job itself.
    other_store = AssetStore(store_root / "resumed")
    resumed_scheduler, resumed_job = _new_scheduled_job(other_store, "run_resumed")
    other_store.set_run_status("run_resumed", "PAUSED")
    assert resumed_scheduler.ready() == []
    other_store.set_run_status("run_resumed", "RUNNING")
    assert [job.job_id for job in resumed_scheduler.ready()] == [resumed_job]
    _, _, resumed_fence = resumed_scheduler.claim(resumed_job)
    assert resumed_fence == 1


def _db_snapshot(store: AssetStore) -> dict[str, list[tuple[object, ...]]]:
    tables = ("runs", "jobs", "dependencies", "events", "idempotency")
    with store.connect() as conn:
        return {table: [tuple(row) for row in conn.execute(
            f"SELECT * FROM {table} ORDER BY rowid").fetchall()] for table in tables}


def test_deployment_cannot_create_or_control_jobs_without_database_changes(store_root: Path):
    store = AssetStore(store_root)
    researcher = make_client(store_root, "researcher")
    deployment = make_client(store_root, "deployment_client")
    try:
        accepted = create_job(researcher, stage="freeze_spec", key="role-control-seed")
        assert accepted.status_code == 202, accepted.text
        job_id = accepted.json()["job_id"]

        mutations = [
            ("POST", "/api/synlab/jobs", {
                "schema_version": "synlab.v3", "idempotency_key": "deployment-create",
                "stage": "freeze_spec", "spec": valid_spec()}),
            ("POST", f"/api/synlab/jobs/{job_id}/pause", {}),
            ("POST", f"/api/synlab/jobs/{job_id}/resume", {}),
            ("POST", f"/api/synlab/jobs/{job_id}/cancel", {}),
            ("POST", f"/api/synlab/jobs/{job_id}/retry", {"reason": "deployment attempt"}),
        ]
        for method, path, body in mutations:
            before = _db_snapshot(store)
            response = deployment.request(method, path, json=body)
            assert response.status_code == 403, (path, response.status_code, response.text)
            assert response.json()["error"]["code"] == "ROLE_FORBIDDEN"
            assert _db_snapshot(store) == before, path
    finally:
        researcher.close()
        deployment.close()


def test_operator_and_researcher_keep_authorized_job_controls(store_root: Path):
    operator = make_client(store_root, "operator")
    researcher = make_client(store_root, "researcher")
    store = AssetStore(store_root)
    try:
        op_job = create_job(operator, stage="freeze_spec", key="operator-control")
        assert op_job.status_code == 202, op_job.text
        op_job_id = op_job.json()["job_id"]
        assert operator.post(f"/api/synlab/jobs/{op_job_id}/pause", json={}).status_code == 200
        assert operator.post(f"/api/synlab/jobs/{op_job_id}/resume", json={}).status_code == 200
        assert operator.post(f"/api/synlab/jobs/{op_job_id}/cancel", json={}).status_code == 200

        researcher_job = create_job(researcher, stage="freeze_spec", key="researcher-control")
        assert researcher_job.status_code == 202, researcher_job.text
        researcher_job_id = researcher_job.json()["job_id"]
        with store.connect() as conn:
            conn.execute("UPDATE jobs SET state=?, error_json=? WHERE job_id=?",
                         ("RETRYABLE", json.dumps({"retryable": True}), researcher_job_id))
        retried = researcher.post(f"/api/synlab/jobs/{researcher_job_id}/retry",
                                  json={"reason": "retry authorized"})
        assert retried.status_code == 202, retried.text
        assert retried.json()["state"] == "PENDING"
    finally:
        operator.close()
        researcher.close()


def test_get_and_control_routes_reject_other_workspace(store_root: Path):
    owner = make_client(store_root, "researcher", workspace="workspace-a")
    other = make_client(store_root, "researcher", workspace="workspace-b")
    store = AssetStore(store_root)
    try:
        accepted = create_job(owner, stage="freeze_spec", key="workspace-job")
        assert accepted.status_code == 202, accepted.text
        job_id = accepted.json()["job_id"]
        before = _db_snapshot(store)

        get_response = other.get(f"/api/synlab/jobs/{job_id}")
        assert get_response.status_code == 403
        assert get_response.json()["error"]["code"] == "WORKSPACE_FORBIDDEN"
        for action, body in (("pause", {}), ("resume", {}), ("cancel", {}),
                             ("retry", {"reason": "cross-workspace"})):
            response = other.post(f"/api/synlab/jobs/{job_id}/{action}", json=body)
            assert response.status_code == 403, (action, response.text)
            assert response.json()["error"]["code"] == "WORKSPACE_FORBIDDEN"
        assert _db_snapshot(store) == before
    finally:
        owner.close()
        other.close()


def test_cancel_closes_claim_gate_before_per_job_transitions_and_cannot_be_reopened(
        store_root: Path, monkeypatch: pytest.MonkeyPatch):
    client = make_client(store_root, "researcher")
    store = AssetStore(store_root)
    scheduler = Scheduler(store, owner="interleaving-worker")
    observed: list[str] = []
    original_transition = Scheduler.transition
    try:
        accepted = create_job(client, stage="freeze_spec", key="cancel-gate-order")
        assert accepted.status_code == 202, accepted.text
        job_id = accepted.json()["job_id"]
        run_id = accepted.json()["run_id"]
        assert [job.job_id for job in scheduler.ready()] == [job_id]
        # Snapshot through one connection before the cancel request uses another.
        with store.connect() as conn:
            stale_revision = int(conn.execute(
                "SELECT revision FROM runs WHERE run_id=?", (run_id,)).fetchone()["revision"])

        def interleave_claim(instance, candidate_id, dst, **kwargs):
            if candidate_id == job_id and str(getattr(dst, "value", dst)) == "CANCELLED":
                assert store.get_run(run_id)["status"] == "CANCELLED"
                before = _job_and_events(store, job_id)
                with pytest.raises(SynLabError) as exc:
                    scheduler.claim(job_id)
                assert exc.value.code == ErrorCode.LEASE_STALE
                assert _job_and_events(store, job_id) == before
                observed.append("claim rejected in cancel gap")
            return original_transition(instance, candidate_id, dst, **kwargs)

        monkeypatch.setattr(Scheduler, "transition", interleave_claim)
        cancelled = client.post(f"/api/synlab/jobs/{job_id}/cancel", json={})
        assert cancelled.status_code == 200, cancelled.text
        assert observed == ["claim rejected in cancel gap"]
        assert store.get_run(run_id)["status"] == "CANCELLED"
        with store.connect() as conn:
            last_status_event = conn.execute(
                """SELECT revision FROM events WHERE run_id=? AND type='run.status'
                   ORDER BY event_seq DESC LIMIT 1""", (run_id,)).fetchone()
        assert int(last_status_event["revision"]) == int(store.get_run(run_id)["revision"])

        # A terminal cancellation cannot be changed to PAUSED and then resumed.
        before = _db_snapshot(store)
        pause = client.post(f"/api/synlab/jobs/{job_id}/pause", json={"revision": stale_revision})
        assert pause.status_code == 409
        assert pause.json()["error"]["code"] == "REVISION_CONFLICT"
        assert store.get_run(run_id)["status"] == "CANCELLED"
        assert _db_snapshot(store) == before
        resume_stale = client.post(f"/api/synlab/jobs/{job_id}/resume",
                                   json={"revision": stale_revision})
        assert resume_stale.status_code == 409
        assert resume_stale.json()["error"]["code"] == "REVISION_CONFLICT"
        assert _db_snapshot(store) == before
        pause_current = client.post(f"/api/synlab/jobs/{job_id}/pause", json={})
        assert pause_current.status_code == 409
        assert pause_current.json()["error"]["code"] == "STATE_CONFLICT"
        assert _db_snapshot(store) == before

        # A stale/recovered RETRYABLE row in a cancelled run also cannot be requeued.
        with store.connect() as conn:
            conn.execute("UPDATE jobs SET state=?, error_json=? WHERE job_id=?",
                         ("RETRYABLE", json.dumps({"retryable": True}), job_id))
        retry_before = _db_snapshot(store)
        retry = client.post(f"/api/synlab/jobs/{job_id}/retry", json={"reason": "must stay closed"})
        assert retry.status_code == 409
        assert retry.json()["error"]["code"] == "STATE_CONFLICT"
        assert _db_snapshot(store) == retry_before
        resume = client.post(f"/api/synlab/jobs/{job_id}/resume", json={})
        assert resume.status_code == 409
        assert _db_snapshot(store) == retry_before
    finally:
        client.close()


def test_cancel_keeps_an_in_flight_attempt_running_and_allows_its_safe_point(
        store_root: Path):
    client = make_client(store_root, "researcher")
    store = AssetStore(store_root)
    scheduler = Scheduler(store, owner="safe-point-worker")
    try:
        accepted = create_job(client, stage="freeze_spec", key="cancel-safe-point")
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["run_id"]
        running_id = accepted.json()["job_id"]
        pending_id = "job_pending_during_cancel"
        scheduler.create_job(job_id=pending_id, run_id=run_id, stage="freeze_spec",
                             spec={"workspace": "default"})
        running, token, fence = scheduler.claim(running_id)
        assert running.state == "RUNNING"

        cancelled = client.post(f"/api/synlab/jobs/{running_id}/cancel", json={})
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["running_jobs_draining"] == [running_id]
        assert cancelled.json()["cancelled_jobs"] == [pending_id]
        assert scheduler.get_job(running_id).state == "RUNNING"
        assert scheduler.ready() == []

        # Cancellation closes future claims but does not revoke the active attempt's
        # fencing token; it can finish its already-entered safe-point unit of work.
        finished = scheduler.transition(running_id, JobState.OUTPUT_READY,
                                        token=token, fence=fence, message="safe point reached")
        assert finished.state == "OUTPUT_READY"
    finally:
        client.close()
