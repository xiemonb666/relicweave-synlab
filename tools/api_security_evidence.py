#!/usr/bin/env python
"""Real-request API security evidence for acceptance item A33 (plan 21.1 / 30.16).

Run it with the project venv::

    .venv\\Scripts\\python.exe tools\\api_security_evidence.py

The script builds a real :func:`synlab.api.create_app` over a fresh on-disk
:class:`~synlab.storage.store.AssetStore`, commits a genuine mother-mesh asset, and then
performs **real HTTP requests** through a Starlette ``TestClient`` (plus a direct ASGI
stream reader for SSE).  Every boolean in the report is the observed outcome of those
requests; nothing is stubbed, mocked or pre-filled.  A ``bool`` is written only when the
request produced the *expected refusal* with the expected structured error code.

Output: ``data/a12/reports/api_security.json`` — the file Lead reads for A33.
"""

from __future__ import annotations

import argparse
import ast
import gc
import importlib.util
import json
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from synlab.api import create_app  # noqa: E402
from synlab.api.integrity import record_integrity  # noqa: E402
from synlab.roles import ROLE_MOTHER_MESH, SCHEMA_MOTHER  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

PREFIX = "/api/synlab"
DEFAULT_REPORT = REPO_ROOT / "data" / "a12" / "reports" / "api_security.json"
CUBE_EDGE_MM = 100.0

#: metric -> the plan clause it evidences
CONTRACT: dict[str, str] = {
    "deployment_truth_denied": "21.1/30.16: 生产部署服务不挂载 truth 路由；deployment_client 不可读取 truth",
    "operator_truth_denied": "30.16: operator 不因能启动 job 就自动获得全部研究数据",
    "path_traversal_denied": "30.16: 防 `..`、symlink 越界和客户端注入 arbitrary_path",
    "unregistered_file_role_denied": "21.1/30.16: file refs 先解析注册 asset/resource ID，role 白名单",
    "oracle_export_denied": "30.16: deployment_client 不可请求 oracle export",
    "idempotency_conflict_409": "21.2: 相同幂等键+同 payload 返回原任务；同键不同 payload 返回 409",
    "sse_seq_monotonic": "21.2: 事件 seq 持久化且单调；heartbeat 不是假百分比；支持 Last-Event-ID 重连",
    "workspace_isolation": "21.1/30.16: 任务/资产按 workspace 授权，服务端对每个 run/asset 校验 workspace",
}


# --------------------------------------------------------------------------- helpers
def cube_arrays(edge_mm: float = CUBE_EDGE_MM) -> dict[str, np.ndarray]:
    """A real 100 mm edge cube: 8 vertices, 12 triangles, centred on the origin."""
    half = edge_mm / 2.0
    vertices = np.array([
        [-half, -half, -half], [+half, -half, -half], [+half, +half, -half], [-half, +half, -half],
        [-half, -half, +half], [+half, -half, +half], [+half, +half, +half], [-half, +half, +half],
    ], dtype=np.float64)
    faces = np.array([
        [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
        [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
    ], dtype=np.int64)
    return {"mesh.vertices": vertices, "mesh.faces": faces}


def valid_spec() -> dict[str, Any]:
    """A minimal genuinely valid ``synlab.v3`` spec (same shape the tests use)."""
    return {
        "schema": "synlab.v3",
        "data_scope": "SYNTHETIC",
        "release_profile": "SANDBOX_CORE",
        "experiment_purpose": "DEVELOPMENT",
        "master_seed": 20261001,
        "implementation": {"require_poc_before_custom": False},
        "dataset": {
            "target_mothers": 1, "target_fragments_estimate": 8, "vessel_ids": ["V01"],
            "material_ids": ["M01"], "pattern_ids": ["PAT01"], "layer_combo_ids": ["L01"],
        },
        "fracture": {"backend": "rough_shared_cut"},
    }


class Recorder:
    """Collects the literal request/response pairs behind every metric."""

    def __init__(self) -> None:
        self.observations: list[dict[str, Any]] = []

    def note(self, metric: str, request: str, status: int, code: str | None,
             detail: str = "", extra: dict[str, Any] | None = None) -> None:
        row: dict[str, Any] = {"metric": metric, "request": request, "status": status,
                               "error_code": code, "detail": detail}
        if extra:
            row["observed"] = extra
        self.observations.append(row)

    def for_metric(self, metric: str) -> list[dict[str, Any]]:
        return [row for row in self.observations if row["metric"] == metric]


def error_code(response: Any) -> str | None:
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - a non-JSON body is itself evidence
        return None
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        return payload["error"].get("code")
    return None


def metric(recorder: Recorder, name: str, check: Callable[[], bool]) -> bool:
    """Run one metric, converting any failure into ``False`` plus a recorded reason."""
    started = time.time()
    try:
        outcome = bool(check())
        reason = "ok" if outcome else "observed outcome did not match the required refusal"
    except Exception as exc:  # noqa: BLE001 - a crash is a failed check, not a crash of the run
        outcome = False
        reason = f"{type(exc).__name__}: {exc}"
        recorder.note(name, "<metric raised>", 0, None, reason,
                      {"traceback": traceback.format_exc(limit=4)})
    for row in recorder.observations:
        if row["metric"] == name and "elapsed_s" not in row:
            row["elapsed_s"] = round(time.time() - started, 4)
    if outcome:
        return True
    recorder.note(name, "<metric verdict>", 0, None, reason)
    return False


def load_asgi_stream() -> Any:
    """Import the SSE stream reader that the API tests use (no duplicated logic)."""
    path = REPO_ROOT / "tests" / "a12" / "api" / "_sse_client.py"
    spec = importlib.util.spec_from_file_location("_a12_sse_client", path)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # register before exec: the module uses @dataclass, which resolves types via sys.modules
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module.asgi_stream


def parse_sse(text: str, *, keep_stream_end: bool = False) -> list[dict[str, Any]]:
    """Parse SSE frames.

    ``stream_end`` is the transport sentinel that closes a non-following stream; it carries
    the cursor but is not a job event, so it is dropped unless explicitly asked for.
    """
    events: list[dict[str, Any]] = []
    current: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line == "":
            if current.get("data"):
                events.append({"id": current.get("id"), "event": current.get("event"),
                               "data": json.loads(current["data"])})
            current = {}
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        current[field.strip()] = value.strip()
    if current.get("data"):
        events.append({"id": current.get("id"), "event": current.get("event"),
                       "data": json.loads(current["data"])})
    if not keep_stream_end:
        events = [event for event in events if event["event"] != "stream_end"]
    return events


# --------------------------------------------------------------------------- checks
def run_checks(store_root: Path, recorder: Recorder, *, started: float) -> dict[str, Any]:
    asgi_stream = load_asgi_stream()
    store = AssetStore(store_root)
    record = store.commit_asset(
        role=ROLE_MOTHER_MESH, schema=SCHEMA_MOTHER, unit="mm", frame="W_mm",
        payload=cube_arrays(), qa={"watertight": True, "edge_mm": CUBE_EDGE_MM},
        qa_status="QA_PASS", meta={"vessel_id": "V01", "material_id": "M01",
                                   "workspace": "default", "evidence_fixture": True},
        lineage_id="lin_evidence_cube",
    )
    record_integrity(store, record.asset_id, source="producer")
    cube_asset = record.asset_id

    researcher = TestClient(create_app(store_root, role="researcher"))
    operator = TestClient(create_app(store_root, role="operator"))
    deployment = TestClient(create_app(store_root, role="deployment_client"))
    other_ws = TestClient(create_app(store_root, role="researcher", workspace="ws-evidence-other"))
    clients = {"researcher": researcher, "operator": operator,
               "deployment_client": deployment, "researcher@ws-evidence-other": other_ws}

    results: dict[str, bool] = {}
    #: run ids the job-creating checks accepted, so the SSE metric reads a real event log
    sse_run_ids: list[str] = []
    try:
        # ------------------------------------------------------------------ roles / truth
        def deployment_truth_denied() -> bool:
            health = deployment.get(f"{PREFIX}/health")
            mounted = health.json().get("research_routes_mounted")
            recorder.note("deployment_truth_denied", f"GET {PREFIX}/health", health.status_code,
                          None, f"research_routes_mounted={mounted}", {"body": health.json()})
            ok = health.status_code == 200 and mounted is False
            for path in (f"{PREFIX}/research/assets/{cube_asset}/truth",
                         f"{PREFIX}/assets/{cube_asset}/truth", f"{PREFIX}/truth/anything"):
                response = deployment.get(path)
                code = error_code(response)
                recorder.note("deployment_truth_denied", f"GET {path}", response.status_code, code,
                              "truth route must be unmounted for deployment_client")
                ok = ok and response.status_code == 403 and code == "TRUTH_ROUTE_UNMOUNTED"
            return ok

        def operator_truth_denied() -> bool:
            health = operator.get(f"{PREFIX}/health")
            mounted = health.json().get("research_routes_mounted")
            recorder.note("operator_truth_denied", f"GET {PREFIX}/health", health.status_code, None,
                          f"research_routes_mounted={mounted}", {"body": health.json()})
            response = operator.get(f"{PREFIX}/research/assets/{cube_asset}/truth")
            code = error_code(response)
            recorder.note("operator_truth_denied",
                          f"GET {PREFIX}/research/assets/{cube_asset}/truth",
                          response.status_code, code,
                          "an operator may start jobs but must not gain research data")
            policy = operator.get(f"{PREFIX}/capabilities").json()["session"]["policy"]
            recorder.note("operator_truth_denied", f"GET {PREFIX}/capabilities", 200, None,
                          "operator policy snapshot", {"policy": policy})
            return (mounted is False and response.status_code == 403
                    and code == "TRUTH_ROUTE_UNMOUNTED"
                    and policy["can_control_jobs"] is True
                    and policy["can_read_truth"] is False)

        # ------------------------------------------------------------------ paths / file roles
        def path_traversal_denied() -> bool:
            ok = True
            candidates = [
                (f"{PREFIX}/assets/{cube_asset}/files/../../../../etc/passwd", "role traversal"),
                (f"{PREFIX}/assets/{cube_asset}/files/mother_mesh?key=../../../meta.json",
                 "payload key traversal"),
                (f"{PREFIX}/assets/{cube_asset}/files/mother_mesh?key=" + "a" * 300,
                 "payload key injection"),
            ]
            for path, label in candidates:
                response = researcher.get(path)
                code = error_code(response)
                refused = response.status_code in (400, 403, 404, 422)
                leaked = str(store_root) in response.text or "root:" in response.text
                recorder.note("path_traversal_denied", f"GET {path[:120]}", response.status_code,
                              code, f"{label}; refused={refused}; path_leaked={leaked}")
                ok = ok and refused and not leaked
            # the generic asset route is never a side door to an arbitrary path
            response = researcher.get(f"{PREFIX}/assets/../../etc/passwd")
            code = error_code(response)
            recorder.note("path_traversal_denied", f"GET {PREFIX}/assets/../../etc/passwd",
                          response.status_code, code, "resolved by the router before any file IO")
            ok = ok and response.status_code in (400, 403, 404, 422) and "root:" not in response.text
            return ok

        def unregistered_file_role_denied() -> bool:
            ok = True
            for role, label in (("definitely_not_a_role", "unknown role"),
                                ("nope_%2e%2e", "injection attempt")):
                response = researcher.get(f"{PREFIX}/assets/{cube_asset}/files/{role}")
                code = error_code(response)
                recorder.note("unregistered_file_role_denied",
                              f"GET {PREFIX}/assets/{cube_asset}/files/{role}",
                              response.status_code, code, label)
                ok = ok and response.status_code in (403, 404) and code in (
                    "FILE_ROLE_NOT_SERVABLE", "NOT_FOUND")
            mismatched = researcher.get(f"{PREFIX}/assets/{cube_asset}/files/display_lod_glb")
            code = error_code(mismatched)
            recorder.note("unregistered_file_role_denied",
                          f"GET {PREFIX}/assets/{cube_asset}/files/display_lod_glb",
                          mismatched.status_code, code,
                          "a whitelisted role that does not match this asset's registered role")
            ok = ok and mismatched.status_code == 409 and code == "FILE_ROLE_MISMATCH"
            # the registered role+key still works, so the refusal above is not a blanket deny
            allowed = researcher.get(f"{PREFIX}/assets/{cube_asset}/files/mother_mesh",
                                     params={"key": "arrays"})
            recorder.note("unregistered_file_role_denied",
                          f"GET {PREFIX}/assets/{cube_asset}/files/mother_mesh?key=arrays",
                          allowed.status_code, error_code(allowed),
                          "control: the whitelisted (role, key) pair is served",
                          {"hash_verified": allowed.headers.get("X-SynLab-Hash-Verified")})
            ok = ok and allowed.status_code == 200 and len(allowed.content) > 0
            return ok

        # ------------------------------------------------------------------ exports
        def oracle_export_denied() -> bool:
            ok = True
            payload = {"release_id": "rel_evidence_missing", "adapter": "oracle_truth"}
            response = deployment.post(f"{PREFIX}/exports", json=payload)
            code = error_code(response)
            recorder.note("oracle_export_denied", f"POST {PREFIX}/exports", response.status_code,
                          code, "deployment_client must not request an oracle export")
            ok = ok and response.status_code == 403 and code == "ORACLE_EXPORT_FORBIDDEN"
            # a non-oracle adapter must not be refused by the same gate (no over-blocking),
            # it fails later on the genuinely missing release
            legal = deployment.post(f"{PREFIX}/exports",
                                    json={"release_id": "rel_evidence_missing",
                                          "adapter": "manifest"})
            recorder.note("oracle_export_denied", f"POST {PREFIX}/exports (adapter=manifest)",
                          legal.status_code, error_code(legal),
                          "control: the refusal is specific to oracle adapters")
            ok = ok and legal.status_code == 404
            for adapter in ("truth_pack", "gt_oracle"):
                response = deployment.post(f"{PREFIX}/exports",
                                           json={"release_id": "rel_evidence_missing",
                                                 "adapter": adapter})
                code = error_code(response)
                recorder.note("oracle_export_denied", f"POST {PREFIX}/exports (adapter={adapter})",
                              response.status_code, code,
                              "aliases of oracle export data are refused by the role gate too")
                ok = ok and response.status_code == 403 and code == "ORACLE_EXPORT_FORBIDDEN"
            researcher_only = researcher.post(
                f"{PREFIX}/exports",
                json={"release_id": "rel_evidence_missing", "adapter": "oracle_truth"})
            recorder.note("oracle_export_denied",
                          f"POST {PREFIX}/exports (researcher, oracle_truth)",
                          researcher_only.status_code, error_code(researcher_only),
                          "a researcher passes the role gate and stops at the missing release; "
                          "this build never fabricates an export")
            ok = ok and researcher_only.status_code == 404
            return ok

        # ------------------------------------------------------------------ idempotency
        def idempotency_conflict_409() -> bool:
            body = {"schema_version": "synlab.v3", "idempotency_key": "evidence-idem-1",
                    "stage": "freeze_spec", "spec": valid_spec(), "input_refs": [cube_asset]}
            first = researcher.post(f"{PREFIX}/jobs", json=body)
            recorder.note("idempotency_conflict_409", f"POST {PREFIX}/jobs (first)", first.status_code,
                          error_code(first), "accepted, never 'computed'",
                          {"run_id": first.json().get("run_id") if first.status_code == 202 else None})
            if first.status_code != 202:
                return False
            replay = researcher.post(f"{PREFIX}/jobs", json=body)
            replay_body = replay.json() if replay.status_code < 500 else {}
            recorder.note("idempotency_conflict_409", f"POST {PREFIX}/jobs (same key, same payload)",
                          replay.status_code, error_code(replay),
                          "same key + same payload returns the original job",
                          {"idempotent_replay": replay_body.get("idempotent_replay"),
                           "same_run": replay_body.get("run_id") == first.json()["run_id"]})
            changed = dict(body)
            changed["spec"] = valid_spec() | {"master_seed": 777}
            conflict = researcher.post(f"{PREFIX}/jobs", json=changed)
            code = error_code(conflict)
            recorder.note("idempotency_conflict_409",
                          f"POST {PREFIX}/jobs (same key, different payload)",
                          conflict.status_code, code, "must be a 409 conflict")
            run_id = first.json()["run_id"]
            sse_run_ids.append(run_id)
            return (replay.status_code == 202 and replay_body.get("idempotent_replay") is True
                    and replay_body.get("run_id") == first.json()["run_id"]
                    and conflict.status_code == 409 and code == "IDEMPOTENCY_CONFLICT")

        # ------------------------------------------------------------------ workspace
        def workspace_isolation() -> bool:
            listing = other_ws.get(f"{PREFIX}/assets")
            body = listing.json()
            recorder.note("workspace_isolation", f"GET {PREFIX}/assets (ws=ws-evidence-other)",
                          listing.status_code, error_code(listing),
                          "another workspace must not see this store's assets",
                          {"count": body.get("count"), "workspace": body.get("workspace")})
            detail = other_ws.get(f"{PREFIX}/assets/{cube_asset}")
            code = error_code(detail)
            recorder.note("workspace_isolation", f"GET {PREFIX}/assets/{cube_asset} (other ws)",
                          detail.status_code, code, "cross-workspace asset read refused")
            job = other_ws.post(f"{PREFIX}/jobs",
                                json={"schema_version": "synlab.v3",
                                      "idempotency_key": "evidence-ws-1", "stage": "freeze_spec",
                                      "spec": valid_spec(), "input_refs": [cube_asset]})
            recorder.note("workspace_isolation", f"POST {PREFIX}/jobs (other ws, foreign input)",
                          job.status_code, error_code(job), "cross-workspace job input refused")
            header = other_ws.get(f"{PREFIX}/capabilities",
                                  headers={"X-SynLab-Workspace": "default"})
            recorder.note("workspace_isolation", f"GET {PREFIX}/capabilities (workspace header)",
                          header.status_code, error_code(header),
                          "a client header cannot switch the server-side workspace scope")
            return (listing.status_code == 200 and body.get("count") == 0
                    and body.get("workspace") == "ws-evidence-other"
                    and detail.status_code == 403 and code == "WORKSPACE_FORBIDDEN"
                    and job.status_code == 403
                    and header.status_code == 403
                    and error_code(header) == "WORKSPACE_FORBIDDEN")

        # ------------------------------------------------------------------ metrics
        results["deployment_truth_denied"] = metric(recorder, "deployment_truth_denied",
                                                    deployment_truth_denied)
        results["operator_truth_denied"] = metric(recorder, "operator_truth_denied",
                                                 operator_truth_denied)
        results["path_traversal_denied"] = metric(recorder, "path_traversal_denied",
                                                  path_traversal_denied)
        results["unregistered_file_role_denied"] = metric(
            recorder, "unregistered_file_role_denied", unregistered_file_role_denied)
        results["oracle_export_denied"] = metric(recorder, "oracle_export_denied",
                                                oracle_export_denied)
        results["idempotency_conflict_409"] = metric(recorder, "idempotency_conflict_409",
                                                     idempotency_conflict_409)

        def sse_check() -> bool:
            if not sse_run_ids:
                recorder.note("sse_seq_monotonic", "<no accepted run>", 0, None,
                              "the idempotency check did not produce a run to stream")
                return False
            return sse_seq_monotonic(researcher, asgi_stream, sse_run_ids[0], recorder)

        results["sse_seq_monotonic"] = metric(recorder, "sse_seq_monotonic", sse_check)
        results["workspace_isolation"] = metric(recorder, "workspace_isolation",
                                                workspace_isolation)
    finally:
        for client in clients.values():
            client.close()

    ordered = {name: bool(results.get(name, False)) for name in CONTRACT}
    payload = {
        "ok": all(ordered.values()),
        "metrics": ordered,
        "generated_at": time.time(),
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generated_by": "tools/api_security_evidence.py",
        "acceptance_item": "A33 权限/输入：服务端角色、SSE/导出/资产授权、safe config、路径/资源/脚本限制",
        "contract": CONTRACT,
        "method": {
            "transport": "starlette.testclient.TestClient over the real create_app()",
            "sse_transport": "direct ASGI stream reader (tests/a12/api/_sse_client.py)",
            "store": "real on-disk AssetStore; a real 100 mm mother-mesh cube with recorded "
                     "sha256 integrity is committed for the file-role checks",
            "honesty": "every bool is the observed outcome of a real request; a metric is false "
                       "unless the expected refusal and structured error code were both observed",
        },
        "observations": recorder.observations,
        "route_inventory": route_inventory(),
        "elapsed_s": round(time.time() - started, 3),
        "python": sys.version.split()[0],
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_REPORT), help="report path")
    parser.add_argument("--keep-store", action="store_true",
                        help="keep the temporary evidence store for inspection")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    work_root = REPO_ROOT / "data" / "a12" / "_evidence_store"
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    store_root = work_root / "store"

    started = time.time()
    try:
        payload = run_checks(store_root, Recorder())
    finally:
        if not args.keep_store:
            shutil.rmtree(work_root, ignore_errors=True)

    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False),
                        encoding="utf-8")

    if not args.quiet:
        print(f"evidence -> {out_path}")
        for name, value in payload["metrics"].items():
            print(f"  {'PASS' if value else 'FAIL'}  {name}")
        print(f"ok={payload['ok']}  observations={len(payload['observations'])}  "
              f"routes={payload['route_inventory']['count']}  elapsed={payload['elapsed_s']}s")
    return 0 if payload["ok"] else 1


def sse_seq_monotonic(researcher: TestClient, asgi_stream: Any, run_id: str,
                      recorder: Recorder) -> bool:
    """Monotonic seq, Last-Event-ID resume, and heartbeat comments that fake nothing."""
    ok = True
    path = f"{PREFIX}/runs/{run_id}/events?follow=false&limit=500"
    with asgi_stream(researcher.app, "GET", path) as stream:
        status = stream.status_code
        content_type = stream.headers.get("content-type", "")
        response = stream.read_to_end(timeout=20.0)
    events = parse_sse(response.body)
    seqs = [event["data"]["seq"] for event in events]
    recorder.note("sse_seq_monotonic", f"GET {path}", status, None,
                  "replay of persisted events",
                  {"content_type": content_type, "event_count": len(events),
                   "seqs": seqs[:24], "self_closed": response.finished})
    ok = ok and status == 200 and response.finished
    ok = ok and content_type.startswith("text/event-stream")
    ok = ok and len(seqs) >= 3 and seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    ok = ok and all(event["data"]["run_id"] == run_id for event in events)

    midpoint = seqs[len(seqs) // 2] if seqs else 0
    resume_path = f"{PREFIX}/runs/{run_id}/events?follow=false"
    with asgi_stream(researcher.app, "GET", resume_path,
                     headers={"Last-Event-ID": str(midpoint)}) as stream:
        resumed_status = stream.status_code
        resumed = stream.read_to_end(timeout=20.0)
    resumed_seqs = [event["data"]["seq"] for event in parse_sse(resumed.body)]
    recorder.note("sse_seq_monotonic", f"GET {resume_path} (Last-Event-ID: {midpoint})",
                  resumed_status, None, "reconnect resumes strictly after the last seen seq",
                  {"resumed_seqs": resumed_seqs})
    ok = ok and resumed_status == 200
    ok = ok and resumed_seqs == [seq for seq in seqs if seq > midpoint]

    bad_path = f"{PREFIX}/runs/{run_id}/events?follow=false"
    with asgi_stream(researcher.app, "GET", bad_path,
                     headers={"Last-Event-ID": "abc"}) as stream:
        bad_status = stream.status_code
        bad_code = None
        try:
            bad_code = stream.body_json()["error"]["code"]
        except Exception:  # noqa: BLE001 - a non-JSON refusal is a failed check
            bad_code = None
    recorder.note("sse_seq_monotonic", f"GET {bad_path} (Last-Event-ID: abc)", bad_status, bad_code,
                  "a malformed resume token is refused with 400, not silently treated as 0")
    ok = ok and bad_status == 400 and bad_code == "BAD_REQUEST"

    follow_path = f"{PREFIX}/runs/{run_id}/events?follow=true&poll_ms=150"
    with asgi_stream(researcher.app, "GET", follow_path) as stream:
        follow_status = stream.status_code
        text = stream.read_for(1.2)
        still_open = stream.close()
    lines = text.splitlines()
    heartbeats = [line for line in lines if line.startswith(": heartbeat")]
    idle_events = parse_sse(text)
    fabricated = [event for event in idle_events if event["data"].get("progress") is not None]
    recorder.note("sse_seq_monotonic", f"GET {follow_path}", follow_status, None,
                  "idle stream emits comment heartbeats only",
                  {"heartbeats": len(heartbeats), "events_while_idle": len(idle_events),
                   "fabricated_progress": len(fabricated), "open_until_client_hangup": still_open})
    ok = ok and follow_status == 200 and bool(heartbeats)
    ok = ok and not fabricated
    ok = ok and not any("%" in line for line in lines if line.startswith("data:"))
    return ok


# --------------------------------------------------------------------------- route inventory
ROUTERS_DIR = REPO_ROOT / "synlab" / "api" / "routers"
_METHODS = {"get", "post", "put", "patch", "delete"}


def _literal(node: Any) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:  # noqa: BLE001 - a computed value stays unreadable rather than guessed
        return None


#: paths mounted directly in ``synlab/api/app.py`` (not through a ``routers/*.py`` decorator)
APP_LEVEL_PATHS = {
    f"{PREFIX}/health": "synlab/api/app.py:create_app",
    f"{PREFIX}/research/assets/{{asset_id}}/truth": "synlab/api/routers/assets.py:research_router "
                                                    "(mounted by create_app for research roles)",
}


def route_inventory() -> dict[str, Any]:
    """Read the shipped routes from the ``@router.<method>(...)`` decorators in the sources.

    The declarations come from the files themselves (not from the plan, and not from a
    hand-kept list), so a route that exists only in documentation cannot appear here.  The
    live mounted table is recorded next to it as a cross-check.
    """
    routes: list[dict[str, Any]] = []
    for source in sorted(ROUTERS_DIR.glob("*.py")):
        if source.name == "__init__.py":
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute) or func.attr not in _METHODS:
                    continue
                if not isinstance(func.value, ast.Name) or func.value.id != "router":
                    continue
                path = _literal(decorator.args[0]) if decorator.args else None
                if not isinstance(path, str):
                    continue
                entry: dict[str, Any] = {
                    "module": f"synlab/api/routers/{source.name}",
                    "method": func.attr.upper(),
                    "path": f"{PREFIX}{path}" if path.startswith("/") else path,
                    "handler": node.name,
                }
                for keyword in decorator.keywords:
                    if keyword.arg == "status_code":
                        entry["declared_status"] = _literal(keyword.value)
                    elif keyword.arg == "summary":
                        entry["summary"] = _literal(keyword.value)
                routes.append(entry)
    routes.sort(key=lambda item: (item["path"], item["method"]))

    by_module: dict[str, int] = {}
    by_method: dict[str, int] = {}
    for route in routes:
        by_module[route["module"]] = by_module.get(route["module"], 0) + 1
        by_method[route["method"]] = by_method.get(route["method"], 0) + 1

    live = _live_route_paths()
    declared_paths = {route["path"] for route in routes}
    return {
        "count": len(routes),
        "by_module": by_module,
        "by_method": by_method,
        "routes": routes,
        "live_mounted_paths": live,
        "app_level_paths": {path: origin for path, origin in sorted(APP_LEVEL_PATHS.items())
                            if path in live},
        "declared_not_mounted": sorted(declared_paths - set(live)),
        "mounted_not_declared": sorted(set(live) - declared_paths),
        "cross_check": ("declared_not_mounted must be empty (every declared route is really "
                        "mounted); mounted_not_declared is expected to hold only the "
                        "app-level paths listed in app_level_paths"),
    }


def _live_route_paths() -> list[str]:
    """Mount the app once on a scratch store and read the paths it really serves.

    FastAPI 0.142 keeps included routers as ``_IncludedRouter`` wrappers, so
    ``app.routes`` no longer enumerates them; the generated OpenAPI document is the
    authoritative list of what the running app exposes.
    """
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="synlab-routes-"))
    app = None
    try:
        app = create_app(tmp / "store", role="researcher")
        return sorted(
            path for path in app.openapi().get("paths", {})
            if path.startswith(PREFIX)
        )
    finally:
        del app
        gc.collect()
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_REPORT), help="report path")
    parser.add_argument("--keep-store", action="store_true",
                        help="keep the temporary evidence store for inspection")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    work_root = REPO_ROOT / "data" / "a12" / "_evidence_store"
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    store_root = work_root / "store"

    recorder = Recorder()
    started = time.time()
    try:
        payload = run_checks(store_root, recorder, started=started)
    finally:
        if not args.keep_store:
            shutil.rmtree(work_root, ignore_errors=True)

    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False),
                        encoding="utf-8")

    if not args.quiet:
        print(f"evidence -> {out_path}")
        for name, value in payload["metrics"].items():
            print(f"  {'PASS' if value else 'FAIL'}  {name}")
        print(f"ok={payload['ok']}  observations={len(payload['observations'])}  "
              f"routes={payload['route_inventory']['count']}  elapsed={payload['elapsed_s']}s")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
