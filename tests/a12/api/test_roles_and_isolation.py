"""Server-side role isolation (plan 21.1, 30.16).

Hiding a field in the UI is never authorisation: these tests prove the refusals happen on
the server, for every role combination.
"""

from __future__ import annotations

import pytest
from tests.a12.api.api_test_support import create_job, make_client, run_worker_once, valid_spec


def test_researcher_sees_truth_routes_mounted(researcher, cube_asset):
    body = researcher.get("/api/synlab/health").json()
    assert body["research_routes_mounted"] is True
    truth = researcher.get(f"/api/synlab/research/assets/{cube_asset}/truth")
    assert truth.status_code == 200
    payload = truth.json()
    assert payload["ok"] is True
    assert payload["asset_id"] == cube_asset
    assert payload["access"]["role"] == "researcher"
    assert payload["ancestry"] == ["lin_test_cube"] or payload["ancestry"] == []


@pytest.mark.parametrize("role", ["operator", "deployment_client"])
def test_truth_route_is_refused_for_non_research_roles(store_root, role, cube_asset):
    client = make_client(store_root, role)
    try:
        assert client.get("/api/synlab/health").json()["research_routes_mounted"] is False
        response = client.get(f"/api/synlab/research/assets/{cube_asset}/truth")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "TRUTH_ROUTE_UNMOUNTED"
        # and the generic asset route cannot be used as a side door
        for path in (f"/api/synlab/assets/{cube_asset}/truth", "/api/synlab/truth/anything"):
            assert client.get(path).status_code == 403
    finally:
        client.close()


def test_deployment_cannot_list_research_roles(store_root, deployment, cube_asset):
    response = deployment.get("/api/synlab/assets", params={"role": "clean_truth"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_FORBIDDEN"
    assert "research" in response.json()["error"]["message"]


def test_deployment_cannot_request_oracle_export(store_root, deployment, researcher):
    for adapter in ("oracle_truth", "truth_pack", "gt_oracle"):
        response = deployment.post("/api/synlab/exports",
                                   json={"release_id": "rel_missing", "adapter": adapter})
        assert response.status_code == 403, adapter
        assert response.json()["error"]["code"] == "ORACLE_EXPORT_FORBIDDEN"
    # researcher passes the role gate and then fails on the missing release instead
    allowed = researcher.post("/api/synlab/exports",
                              json={"release_id": "rel_missing", "adapter": "oracle_truth"})
    assert allowed.status_code == 404


def test_role_header_cannot_escalate(store_root, deployment):
    response = deployment.get("/api/synlab/capabilities", headers={"X-SynLab-Role": "researcher"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_MISMATCH"
    restated = deployment.get("/api/synlab/capabilities",
                              headers={"X-SynLab-Role": "deployment_client"})
    assert restated.status_code == 200


def test_deployment_cannot_create_jobs_or_releases(store_root, deployment):
    jobs = deployment.get("/api/synlab/jobs")
    assert jobs.status_code == 200  # read-only listing is allowed
    assert jobs.json()["count"] == 0
    assert deployment.get("/api/synlab/assets").status_code == 200
    assert deployment.post("/api/synlab/releases",
                           json={"release_id": "rel_x", "profile": "SANDBOX_CORE",
                                 "asset_ids": ["asset_0000000000000000abcd"],
                                 "audit_id": "audit_x"}).status_code == 403


#: every route that enqueues work or drives a live run, with a body that is otherwise legal
ENQUEUING_ROUTES = (
    ("POST", "/api/synlab/pools", {"release_id": "rel_nope"}),
    ("POST", "/api/synlab/diagnostics/runs", {"spec": {}}),
    ("POST", "/api/synlab/training/runs", {"spec": {}}),
    ("POST", "/api/synlab/training/runs/train_nope/resume", {}),
    ("POST", "/api/synlab/episodes/ep_nope/reset", {}),
    ("POST", "/api/synlab/episodes/ep_nope/step", {"action": {"kind": "STOP"}}),
    ("POST", "/api/synlab/camera-profiles",
     {"profile_id": "P1", "version": "v1", "tier": "GLOBAL", "payload": {}}),
)


@pytest.mark.parametrize("method,path,body", ENQUEUING_ROUTES,
                         ids=[f"{m} {p}" for m, p, _ in ENQUEUING_ROUTES])
def test_deployment_cannot_reach_any_enqueuing_route(deployment, method, path, body):
    """A deployment session is read-only: no route that creates work may accept it.

    Hiding these buttons in the UI is not authorisation (plan 30.16), so each route checks
    ``can_control_jobs``/``can_start_training`` on the server even when a deployment build
    would never call it.
    """
    response = deployment.request(method, path, json=body)
    assert response.status_code == 403, (path, response.status_code, response.text)
    assert response.json()["error"]["code"] == "ROLE_FORBIDDEN"
    assert deployment.get("/api/synlab/capabilities").json()["session"]["policy"][
        "can_control_jobs"] is False


def test_previews_are_a_job_creation_route_and_are_gated(store_root, deployment, operator,
                                                         researcher):
    body = {"stage": "mother", "spec": valid_spec()}
    denied = deployment.post("/api/synlab/previews", json=body)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ROLE_FORBIDDEN"
    # operator and researcher still pass the role gate; their outcome is the real
    # capability/budget answer, never a fabricated preview
    for client in (operator, researcher):
        allowed = client.post("/api/synlab/previews", json=body)
        assert allowed.status_code in (202, 503), allowed.text


def test_read_only_routes_stay_available_to_deployment(store_root, deployment):
    for path in ("/api/synlab/capabilities", "/api/synlab/stages", "/api/synlab/jobs",
                 "/api/synlab/assets", "/api/synlab/audits", "/api/synlab/pools",
                 "/api/synlab/camera-profiles", "/api/synlab/training/runs",
                 "/api/synlab/diagnostics/runs", "/api/synlab/releases"):
        response = deployment.get(path)
        assert response.status_code == 200, (path, response.status_code, response.text)


def test_workspace_header_cannot_switch_scope(store_root, researcher):
    response = researcher.get("/api/synlab/capabilities",
                              headers={"X-SynLab-Workspace": "somewhere-else"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "WORKSPACE_FORBIDDEN"


def test_unknown_role_is_rejected_at_construction(store_root):
    with pytest.raises(Exception):
        make_client(store_root, "superuser")


def test_session_id_is_validated(store_root, researcher):
    ok = researcher.get("/api/synlab/capabilities", headers={"X-SynLab-Session": "sess-01:abc"})
    assert ok.status_code == 200
    assert ok.json()["session"]["session_id"] == "sess-01:abc"
    bad = researcher.get("/api/synlab/capabilities", headers={"X-SynLab-Session": "bad session!"})
    assert bad.status_code == 400


def test_policy_matrix_is_exposed_and_truthful(researcher, operator, deployment):
    r = researcher.get("/api/synlab/capabilities").json()["session"]["policy"]
    o = operator.get("/api/synlab/capabilities").json()["session"]["policy"]
    d = deployment.get("/api/synlab/capabilities").json()["session"]["policy"]
    assert r["can_read_truth"] and r["truth_routes_mounted"]
    assert not o["can_read_truth"] and not o["truth_routes_mounted"]
    assert o["can_control_jobs"] and o["can_create_release"]
    assert not d["can_control_jobs"] and not d["can_create_release"]
    assert not d["can_request_oracle_export"] and not d["can_start_training"]


def test_operator_can_run_platform_but_not_read_truth(store_root, operator, cube_asset):
    created = create_job(operator, stage="freeze_spec", key="op-1", input_refs=[cube_asset])
    assert created.status_code == 202
    run_worker_once(store_root)
    job = operator.get(f"/api/synlab/jobs/{created.json()['job_id']}").json()["job"]
    assert job["state"] == "COMMITTED"
    assert operator.get(f"/api/synlab/assets/{cube_asset}").json()["asset"]["ancestry"] == []
    assert operator.get(f"/api/synlab/assets/{cube_asset}").json()["asset"]["ancestry_hidden"] is True
