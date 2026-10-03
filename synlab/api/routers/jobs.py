"""Job creation, listing, control and the SSE event stream (plan 21.1 / 21.2).

``POST /jobs`` is fail-closed and idempotent:

* the idempotency key plus a *request fingerprint* is stored in the scheduler's
  ``idempotency`` table; the same key with the same fingerprint returns the original
  run/job refs, the same key with a different fingerprint answers ``409``;
* a stage whose capability modules are not importable answers ``503`` and creates nothing;
* accepting a job answers ``202`` — it means *accepted*, never *computed*.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from ...canonical import hash_json
from ...errors import ErrorCode, SynLabError
from ...jobs.scheduler import MAX_ATTEMPTS
from ...jobs.state import TERMINAL, JobState, can_transition
from ...storage.store import _dumps
from ..capabilities import probe_capability
from ..deps import ControlEnvelope, JobCreateEnvelope, PreviewEnvelope, RetryEnvelope, SessionDep
from ..handlers import estimate_for
from ..pagination import MAX_LIMIT, page_jobs
from ..problems import (
    API_CODE_NOT_FOUND,
    API_CODE_REVISION_CONFLICT,
    API_CODE_STATE_CONFLICT,
    ApiProblem,
    from_synlab,
)
from ..security import require_job_control, resolve_asset_ref
from ..specs import kind_for_schema, validate_spec
from ..stages import PIPELINE_STAGES, STAGES, plan_generate, required_capabilities, stage_spec

router = APIRouter(tags=["jobs"])

PREVIEW_STAGES = ("mother", "pattern", "fracture", "degrade", "display_lod")

#: Rows the events route reads per query.  It is deliberately not the client's ``limit``:
#: the event log is shared by every run, so a small client limit must not stop the cursor
#: from walking past other runs' events (it would silently truncate this run's history).
MAX_EVENT_PAGE = 2000
RETRYABLE_RUN_STATUSES = frozenset({"PENDING", "ACCEPTED", "RUNNING", "PAUSED"})


# --------------------------------------------------------------------------- helpers
def _events_url(run_id: str) -> str:
    return f"/api/synlab/runs/{run_id}/events"


def _fingerprint(body: JobCreateEnvelope, *, workspace: str) -> dict[str, Any]:
    return {
        "schema_version": body.schema_version,
        "stage": body.stage,
        "data_scope": body.data_scope,
        "release_profile": body.release_profile,
        "spec_ref": body.spec_ref,
        "input_refs": sorted(body.input_refs),
        "spec": body.spec,
        "planned_jobs": body.planned_jobs,
        "budget_ref": body.budget_ref,
        "workspace": workspace,
    }


def _check_capabilities(stage: str) -> None:
    missing: list[dict[str, Any]] = []
    for key in required_capabilities(stage):
        probe = probe_capability(key)
        if not probe.available:
            missing.append({"capability": key, "module": probe.module, "status": probe.status,
                            "error": probe.error,
                            "missing_entry_points": probe.missing_entry_points})
    env_missing: list[dict[str, Any]] = []
    for env_key in stage_spec(stage).env:
        from ..capabilities import env_report

        probe = env_report().get(env_key, {})
        if probe.get("status") != "OK":
            env_missing.append({"capability": env_key, "status": probe.get("status"),
                                "detail": probe.get("detail")})
    if missing or env_missing:
        raise ApiProblem(
            503, "DEPENDENCY_CAPABILITY_MISSING",
            f"stage {stage!r} requires capabilities that are not importable; nothing was created",
            stage="jobs.capabilities", retryable=False,
            details={"stage": stage, "missing_capabilities": missing, "missing_env": env_missing,
                     "frozen_calls": {s: STAGES[s].description for s in PIPELINE_STAGES},
                     "expected_entry_points": {m["capability"]: m["missing_entry_points"]
                                               for m in missing}},
            evidence_refs=[m["module"] for m in missing],
        )


def _resolve_inputs(session: SessionDep, refs: list[str]) -> list[str]:
    resolved: list[str] = []
    for ref in refs:
        asset_id = resolve_asset_ref(ref)
        record = session.store.get_asset(asset_id)
        asset_ws = (record.meta or {}).get("workspace", "default")
        if asset_ws != session.workspace:
            raise ApiProblem(403, "WORKSPACE_FORBIDDEN",
                             f"input asset {asset_id} belongs to workspace {asset_ws!r}",
                             stage="jobs.inputs")
        resolved.append(asset_id)
    return resolved


def _admission_precheck(session: SessionDep, stage: str, planned_jobs: int) -> dict[str, Any]:
    estimate = estimate_for(stage, planned_jobs=planned_jobs)
    report = session.guard.budget_report(planned_jobs, [estimate])
    if not report["feasible"]:
        raise ApiProblem(409, "BUDGET_EXCEEDED",
                         f"stage {stage!r} with planned_jobs={planned_jobs} exceeds the aggregate budget",
                         stage="jobs.budget", details={"budget": report})
    return report


# --------------------------------------------------------------------------- create
@router.post("/jobs", status_code=202, summary="frozen spec + idempotency key → run/job refs")
def post_jobs(session: SessionDep, body: JobCreateEnvelope) -> dict[str, Any]:
    require_job_control(session.policy, stage="jobs.create", action="enqueue a job")
    if body.stage not in STAGES:
        raise ApiProblem(422, "BAD_REQUEST",
                         f"unknown stage {body.stage!r}; known: {sorted(STAGES)}", stage="jobs.stage")
    expected_kind = kind_for_schema(body.schema_version) if body.schema_version != "synlab.v3" \
        else "generation"
    validation = validate_spec(body.spec or {}, kind=expected_kind)
    if not validation["ok"]:
        raise ApiProblem(422, "SCHEMA_INVALID",
                         f"spec rejected: {len(validation['errors'])} error(s)",
                         stage="jobs.validate", details={"validation": validation})
    spec_hash = validation["spec_hash"]
    if body.spec_ref is not None and body.spec_ref not in (spec_hash, spec_hash.split(":", 1)[-1]):
        raise ApiProblem(422, "SCHEMA_INVALID",
                         "spec_ref does not match the submitted spec hash",
                         stage="jobs.validate",
                         details={"spec_ref": body.spec_ref, "spec_hash": spec_hash})

    fingerprint = _fingerprint(body, workspace=session.workspace)
    existing = session.scheduler.idempotent_lookup(body.idempotency_key, fingerprint)
    if existing is not None:
        job_id, run_id = existing
        job = session.scheduler.get_job(job_id)
        return {
            "ok": True, "accepted": True, "idempotent_replay": True, "created": False,
            "run_id": run_id, "job_id": job_id, "status": job.state,
            "spec_hash": spec_hash, "events_url": _events_url(run_id),
            "jobs_url": f"/api/synlab/jobs?run_id={run_id}",
            "note": "same idempotency key and same payload: the original job is returned",
        }

    _check_capabilities(body.stage)
    inputs = _resolve_inputs(session, body.input_refs)
    budget = _admission_precheck(session, body.stage, body.planned_jobs)

    run_id = "run_" + hash_json({"fp": fingerprint, "key": body.idempotency_key,
                                 "t": time.time()}).split(":", 1)[-1][:20]
    session.store.create_run(run_id, spec_hash or hash_json(body.spec), body.data_scope or "SYNTHETIC",
                             body.release_profile, meta={"workspace": session.workspace,
                                                         "stage": body.stage,
                                                         "role": session.role,
                                                         "budget_ref": budget.get("budget_ref")})

    dag = _plan(body) if body.stage == "generate" else [
        {"node_id": f"n0_{body.stage}", "stage": body.stage, "chain": 0, "depends_on": [],
         "cost_class": STAGES[body.stage].cost_class}]
    id_by_node = {
        node["node_id"]: "job_" + hash_json({"run": run_id, "node": node["node_id"]}).split(":", 1)[-1][:20]
        for node in dag
    }
    created: list[dict[str, Any]] = []
    for node in dag:
        deps = [id_by_node[d] for d in node["depends_on"] if d in id_by_node]
        session.scheduler.create_job(
            job_id=id_by_node[node["node_id"]], run_id=run_id, stage=node["stage"],
            spec={"workspace": session.workspace, "spec": body.spec, "spec_hash": spec_hash,
                  "node_id": node["node_id"], "chain": node["chain"],
                  "input_refs": inputs, "budget_ref": body.budget_ref or budget.get("budget_ref"),
                  "planned_jobs": body.planned_jobs, "role": session.role},
            inputs=inputs, depends_on=deps,
        )
        created.append({"node_id": node["node_id"], "stage": node["stage"],
                        "job_id": id_by_node[node["node_id"]], "depends_on": deps})

    root_job = created[0]["job_id"]
    session.scheduler.idempotent_record(body.idempotency_key, fingerprint, root_job, run_id)
    session.store.append_event(run_id=run_id, job_id=None, type="run.accepted", state="PENDING",
                               revision=1, message=f"{len(created)} job(s) planned",
                               payload={"stage": body.stage, "spec_hash": spec_hash,
                                        "jobs": [c["job_id"] for c in created]})
    session.store.set_run_status(run_id, "ACCEPTED", meta={"workspace": session.workspace,
                                                           "jobs": len(created)})
    return {
        "ok": True, "accepted": True, "created": True, "idempotent_replay": False,
        "run_id": run_id, "job_id": root_job, "job_ids": [c["job_id"] for c in created],
        "status": JobState.PENDING.value, "spec_hash": spec_hash,
        "events_url": _events_url(run_id), "jobs_url": f"/api/synlab/jobs?run_id={run_id}",
        "dag": created, "budget": budget,
        "note": "HTTP 202 means accepted only; computation runs in synlab.api.worker and "
                "success is reported by later events",
    }


def _plan(body: JobCreateEnvelope) -> list[dict[str, Any]]:
    """Expand a ``generate`` request into real DAG nodes (dependencies name sibling nodes)."""
    return plan_generate(body.spec or {}, max_mothers=min(4, max(1, body.planned_jobs)))


@router.post("/previews", status_code=202, summary="母体/纹样/断裂/退化共用的 typed 预览请求")
def post_previews(session: SessionDep, body: PreviewEnvelope) -> dict[str, Any]:
    # A preview creates a real job, so the same control gate as POST /jobs applies.
    require_job_control(session.policy, stage="previews.create", action="enqueue a preview job")
    if body.stage not in PREVIEW_STAGES:
        raise ApiProblem(422, "BAD_REQUEST",
                         f"preview stage must be one of {list(PREVIEW_STAGES)}, got {body.stage!r}",
                         stage="previews.stage")
    envelope = JobCreateEnvelope(
        schema_version="synlab.v3", spec=body.spec, input_refs=body.input_refs,
        idempotency_key=body.idempotency_key or f"preview:{body.stage}:{hash_json(body.spec)}",
        stage=body.stage, budget_ref=body.budget_ref, planned_jobs=1,
    )
    result = post_jobs(session, envelope)
    result["preview"] = True
    result["preview_note"] = ("预览是真实 preview job；滑块只改本地草稿，未运行前一律标‘未计算’")
    return result


# --------------------------------------------------------------------------- query
@router.get("/jobs", summary="分页任务列表（上限固定，避免全库扫描）")
def get_jobs(
    session: SessionDep,
    run_id: str | None = Query(None),
    state: list[str] | None = Query(None),
    stage: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(None),
    with_total: bool = Query(False),
) -> dict[str, Any]:
    if run_id:
        session.store.get_run(run_id)
    payload = page_jobs(session.store, run_id=run_id, states=state, stage=stage,
                        workspace=session.workspace, limit=limit, cursor=cursor,
                        with_total=with_total)
    payload["ok"] = True
    payload["states"] = [s.value for s in JobState]
    payload["terminal_states"] = [s.value for s in TERMINAL]
    return payload


@router.get("/jobs/{job_id}", summary="当前权威状态/阶段/资源/error refs")
def get_job(session: SessionDep, job_id: str) -> dict[str, Any]:
    job = _job_or_404(session, job_id)
    run_meta: dict[str, Any] = {}
    try:
        run_meta = session.store.get_run(job.run_id)
    except SynLabError:
        run_meta = {}
    spec = job.spec or {}
    queues = [j.job_id for j in session.scheduler.list_jobs(state=JobState.PENDING.value, limit=1000)]
    payload: dict[str, Any] = {
        "ok": True,
        "job": job.as_dict(),
        "stage_title": STAGES[job.stage].title if job.stage in STAGES else job.stage,
        "run": {"run_id": job.run_id, "status": run_meta.get("status"),
                "revision": run_meta.get("revision"), "profile": run_meta.get("profile"),
                "spec_hash": run_meta.get("spec_hash")},
        "progress": spec.get("progress"),
        "queue_position": (queues.index(job.job_id) if job.job_id in queues else None),
        "dependencies": session.scheduler.dependencies(job_id),
        "blocked_dependents": [j.job_id for j in session.scheduler.list_jobs(limit=500)
                               if job_id in session.scheduler.dependencies(j.job_id)],
        "resource_estimate": estimate_for(job.stage).__dict__,
        "events_url": _events_url(job.run_id),
        "terminal": job.state in {s.value for s in TERMINAL},
        "error": job.error,
        "note": "state is authoritative; missing progress means the handler has not counted work yet",
    }
    return payload


# --------------------------------------------------------------------------- control
def _transition_run_status(session: SessionDep, run_id: str, dst: str, *,
                           allowed_current: set[str], expected_revision: int | None,
                           meta: dict[str, Any], stage: str) -> tuple[int, int]:
    """Compare and transition a run under the same SQLite writer transaction.

    ``BEGIN IMMEDIATE`` serializes this change with scheduler claims and other control
    requests, so a stale request cannot replace a later CANCELLED state. The event carries
    the revision committed by this transaction.
    """
    conn = session.store.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status, revision FROM runs WHERE run_id = ?",
                           (run_id,)).fetchone()
        if row is None:
            raise ApiProblem(404, API_CODE_NOT_FOUND, f"unknown run {run_id}", stage=stage)
        status = str(row["status"])
        current_revision = int(row["revision"])
        if expected_revision is not None and int(expected_revision) != current_revision:
            raise ApiProblem(409, API_CODE_REVISION_CONFLICT,
                             f"run revision is {current_revision}, expected {expected_revision}",
                             stage=stage, details={"current_revision": current_revision})
        if status not in allowed_current:
            raise ApiProblem(409, API_CODE_STATE_CONFLICT,
                             f"run {run_id} is {status!r}; action is allowed only for statuses "
                             f"{sorted(allowed_current)}", stage=stage,
                             details={"run_status": status,
                                      "allowed_statuses": sorted(allowed_current)})
        next_revision = current_revision + 1
        updated = conn.execute(
            """UPDATE runs SET status=?, revision=?, meta_json=?
               WHERE run_id=? AND status=? AND revision=?""",
            (dst, next_revision, _dumps(meta), run_id, status, current_revision),
        )
        if updated.rowcount != 1:
            raise ApiProblem(409, API_CODE_STATE_CONFLICT,
                             f"run {run_id} changed while applying {dst}", stage=stage)
        conn.execute(
            """INSERT INTO events(run_id, job_id, type, state, revision, message,
               payload_json, created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (run_id, None, "run.status", dst, next_revision, dst, "{}", time.time()),
        )
        conn.execute("COMMIT")
        return current_revision, next_revision
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _run_jobs(session: SessionDep, run_id: str) -> list[Any]:
    return session.scheduler.list_jobs(run_id=run_id, limit=1000)


@router.post("/jobs/{job_id}/pause", summary="安全点暂停：停止开始新步骤")
def post_pause(session: SessionDep, job_id: str, body: ControlEnvelope) -> dict[str, Any]:
    require_job_control(session.policy, stage="jobs.pause", action="pause a job run")
    job = _job_or_404(session, job_id)
    revision, new_revision = _transition_run_status(
        session, job.run_id, "PAUSED",
        allowed_current={"PENDING", "ACCEPTED", "RUNNING", "PAUSED"},
        expected_revision=body.revision,
        meta={"workspace": session.workspace, "paused_by": session.session_id,
              "reason": body.reason}, stage="jobs.pause")
    pending = [j.job_id for j in _run_jobs(session, job.run_id)
               if j.state in (JobState.PENDING.value, JobState.RETRYABLE.value)]
    return {
        "ok": True, "action": "pause", "run_id": job.run_id, "run_status": "PAUSED",
        "previous_revision": revision, "revision": new_revision,
        "jobs_not_started": pending,
        "running_jobs": [j.job_id for j in _run_jobs(session, job.run_id)
                         if j.state == JobState.RUNNING.value],
        "note": "暂停在安全点生效：worker 不再领取该 run 的新 job，已在运行的 job 跑完并保留已提交输出",
    }


@router.post("/jobs/{job_id}/resume", summary="恢复：核验依赖与 lease")
def post_resume(session: SessionDep, job_id: str, body: ControlEnvelope) -> dict[str, Any]:
    require_job_control(session.policy, stage="jobs.resume", action="resume a job run")
    job = _job_or_404(session, job_id)
    dependencies: dict[str, Any] = {}
    blocked: list[str] = []
    for item in _run_jobs(session, job.run_id):
        deps = session.scheduler.dependencies(item.job_id)
        states = {}
        for dep in deps:
            try:
                states[dep] = session.scheduler.get_job(dep).state
            except SynLabError:
                states[dep] = "MISSING"
        dependencies[item.job_id] = states
        if item.state in (JobState.PENDING.value, JobState.BLOCKED.value) and \
                any(s != JobState.COMMITTED.value for s in states.values()):
            blocked.append(item.job_id)
    leases = [row for row in _lease_rows(session) if row.get("state") != "DRAINED"]
    revision, new_revision = _transition_run_status(
        session, job.run_id, "RUNNING", allowed_current={"PAUSED"},
        expected_revision=body.revision,
        meta={"workspace": session.workspace, "resumed_by": session.session_id},
        stage="jobs.resume")
    return {
        "ok": True, "action": "resume", "run_id": job.run_id, "run_status": "RUNNING",
        "previous_revision": revision, "revision": new_revision,
        "dependencies": dependencies, "still_blocked": blocked, "active_leases": leases,
        "note": "恢复只解除暂停；依赖未 COMMITTED 或 lease 未清空的 job 仍然不会开始",
    }


@router.post("/jobs/{job_id}/cancel", summary="停新步骤，保留已提交")
def post_cancel(session: SessionDep, job_id: str, body: ControlEnvelope) -> dict[str, Any]:
    require_job_control(session.policy, stage="jobs.cancel", action="cancel a job run")
    job = _job_or_404(session, job_id)
    # Publish the run-level stop before touching individual jobs. ``claim`` takes the
    # SQLite write lock and rechecks this status in the same transaction, so ordering is
    # deterministic: a claim committed first is allowed to drain; later claims are closed.
    revision, new_revision = _transition_run_status(
        session, job.run_id, "CANCELLED",
        allowed_current={"PENDING", "ACCEPTED", "RUNNING", "PAUSED", "CANCELLED"},
        expected_revision=body.revision,
        meta={"workspace": session.workspace, "cancelled_by": session.session_id,
              "reason": body.reason}, stage="jobs.cancel")
    cancelled: list[str] = []
    kept_running: list[str] = []
    committed: list[str] = []
    for item in _run_jobs(session, job.run_id):
        if item.state == JobState.COMMITTED.value:
            committed.append(item.job_id)
        elif item.state in (JobState.PENDING.value, JobState.BLOCKED.value,
                            JobState.RETRYABLE.value, JobState.QUARANTINED.value):
            if can_transition(item.state, JobState.CANCELLED):
                session.scheduler.transition(item.job_id, JobState.CANCELLED,
                                             message=body.reason or "cancelled by client")
                cancelled.append(item.job_id)
        elif item.state == JobState.RUNNING.value:
            kept_running.append(item.job_id)
    return {
        "ok": True, "action": "cancel", "run_id": job.run_id, "run_status": "CANCELLED",
        "previous_revision": revision, "revision": new_revision,
        "cancelled_jobs": cancelled, "committed_jobs_kept": committed,
        "running_jobs_draining": kept_running,
        "note": "取消不删除已提交数据；正在运行的 job 跑完当前 attempt 后不再进入后续阶段",
    }


@router.post("/jobs/{job_id}/retry", status_code=202, summary="只允许明确可重试错误，产生新 attempt")
def post_retry(session: SessionDep, job_id: str, body: RetryEnvelope) -> dict[str, Any]:
    require_job_control(session.policy, stage="jobs.retry", action="retry a job")
    job = _job_or_404(session, job_id)
    run_status = str(session.store.get_run(job.run_id)["status"])
    if run_status not in RETRYABLE_RUN_STATUSES:
        raise ApiProblem(409, API_CODE_STATE_CONFLICT,
                         f"run {job.run_id} is {run_status!r}; retry is not allowed",
                         stage="jobs.retry", details={"run_status": run_status})
    error = job.error or {}
    retryable_error = bool(error.get("retryable"))
    if job.state == JobState.RETRYABLE.value and can_transition(JobState.RETRYABLE, JobState.PENDING):
        requeued = session.scheduler.requeue(
            job_id, message=body.reason, allowed_run_statuses=RETRYABLE_RUN_STATUSES)
        return {"ok": True, "action": "retry", "mode": "requeue", "job_id": job_id,
                "attempt": requeued.attempt, "state": requeued.state,
                "reason": body.reason, "error": error,
                "note": ("RETRYABLE 直接回到 PENDING；内容种子不变；run 暂停时需先恢复才能领取"
                         if run_status == "PAUSED" else
                         "RETRYABLE 直接回到 PENDING；内容种子不变")}
    if job.state == JobState.FAILED.value and retryable_error and job.attempt < MAX_ATTEMPTS - 1:
        new_id = "job_" + hash_json({"retry_of": job_id, "attempt": job.attempt + 1,
                                     "t": time.time()}).split(":", 1)[-1][:20]
        created = session.scheduler.create_job(
            job_id=new_id, run_id=job.run_id, stage=job.stage,
            spec={**(job.spec or {}), "retry_of": job_id, "retry_reason": body.reason},
            inputs=job.inputs, allowed_run_statuses=RETRYABLE_RUN_STATUSES,
        )
        return {"ok": True, "action": "retry", "mode": "new_attempt", "job_id": new_id,
                "previous_job_id": job_id, "attempt": created.attempt, "state": created.state,
                "reason": body.reason, "error": error,
                "events_url": _events_url(job.run_id),
                "note": "失败但可重试：创建新 attempt job；已提交输出不被覆盖"}
    raise ApiProblem(
        409, API_CODE_STATE_CONFLICT,
        f"job {job_id} in state {job.state} with retryable={retryable_error} cannot be retried; "
        "only explicitly retryable failures may be retried",
        stage="jobs.retry",
        details={"state": job.state, "attempt": job.attempt, "max_attempts": MAX_ATTEMPTS,
                 "error": error},
    )


def _job_or_404(session: SessionDep, job_id: str) -> Any:
    try:
        job = session.scheduler.get_job(job_id)
    except SynLabError as exc:
        raise from_synlab(exc) from exc
    job_ws = (job.spec or {}).get("workspace", "default")
    if job_ws != session.workspace:
        raise ApiProblem(403, "WORKSPACE_FORBIDDEN",
                         f"job {job_id} belongs to workspace {job_ws!r}", stage="jobs.workspace")
    return job


def _lease_rows(session: SessionDep) -> list[dict[str, Any]]:
    from ...jobs.leases import LeaseManager

    return LeaseManager(session.store).status()


# --------------------------------------------------------------------------- SSE
def _event_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") or {}
    metrics = payload.get("metrics")
    error = payload.get("error")
    return {
        "seq": row["event_seq"],
        "revision": row["revision"],
        "run_id": row["run_id"],
        "job_id": row["job_id"],
        "type": row["type"],
        "state": row["state"],
        "progress": payload.get("progress") or row.get("progress"),
        "metrics_ref": ("metrics_" + hash_json(metrics).split(":", 1)[-1][:16]) if metrics else None,
        "error_ref": ("error_" + hash_json(error).split(":", 1)[-1][:16]) if error else None,
        "message": row.get("message") or "",
        "created_at": row.get("created_at"),
        "payload": payload,
    }


def _sse_format(event: dict[str, Any]) -> str:
    return f"id: {event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, sort_keys=True)}\n\n"


@router.get("/runs/{run_id}/events", summary="有序事件流（seq/revision，支持 Last-Event-ID 重连）")
def get_run_events(
    request: Request,
    session: SessionDep,
    run_id: str,
    after_seq: int | None = Query(None, ge=0, description="从该 seq 之后开始；缺省用 Last-Event-ID"),
    follow: bool = Query(True, description="false 表示只回放已有事件后关闭（用于测试/一次性拉取）"),
    limit: int = Query(200, ge=1, le=1000),
    poll_ms: int = Query(1000, ge=100, le=30000),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
) -> StreamingResponse:
    try:
        run = session.store.get_run(run_id)
    except SynLabError as exc:
        raise from_synlab(exc) from exc
    run_ws = (json.loads(run.get("meta_json") or "{}") or {}).get("workspace", "default")
    if run_ws != session.workspace:
        raise ApiProblem(403, "WORKSPACE_FORBIDDEN",
                         f"run {run_id} belongs to workspace {run_ws!r}", stage="events.workspace")

    # Everything that can refuse the request is decided *before* the body starts streaming:
    # once a StreamingResponse has sent its headers the status is already on the wire, so a
    # late failure could only be smuggled into the stream as fake data or lost silently.
    start = after_seq
    if start is None and last_event_id:
        if not last_event_id.strip().isdigit():
            raise ApiProblem(400, "BAD_REQUEST",
                             "Last-Event-ID must be a non-negative integer event seq",
                             stage="events.reconnect")
        start = int(last_event_id.strip())
    start = 0 if start is None else int(start)
    # The client chooses how many of *its own* events one response carries, not how many raw
    # rows the server reads per query: the log is shared, so a client-supplied LIMIT must
    # never cap the cursor's ability to walk past other runs' events.
    page_size = max(200, min(int(limit), MAX_EVENT_PAGE))

    async def stream() -> AsyncIterator[str]:
        cursor = int(start)
        yield f": synlab events run={run_id} from seq={cursor} follow={follow}\n\n"

        async def drain() -> AsyncIterator[str]:
            """Emit every pending event of this run, crossing batch boundaries."""
            nonlocal cursor
            while True:
                rows = session.store.events_since(cursor, limit=page_size)
                if not rows:
                    return
                highest = cursor
                for row in rows:
                    highest = max(highest, int(row["event_seq"]))
                    if row.get("run_id") != run_id:
                        continue
                    yield _sse_format(_event_payload(row))
                reached_end = highest <= cursor
                cursor = highest
                if reached_end or cursor >= _max_event_seq(session):
                    return

        idle_polls = 0
        while True:
            async for frame in drain():
                yield frame
            if not follow:
                yield f"event: stream_end\ndata: {json.dumps({'seq': cursor, 'run_id': run_id, 'reason': 'not_following'})}\n\n"
                return
            if await request.is_disconnected():
                return
            idle_polls += 1
            yield f": heartbeat {time.time():.3f} idle_polls={idle_polls}\n\n"
            if _run_status(session, run_id) in ("CANCELLED",):
                yield ("event: stream_end\ndata: "
                       + json.dumps({"seq": cursor, "run_id": run_id, "reason": "run_cancelled"})
                       + "\n\n")
                return
            await asyncio.sleep(poll_ms / 1000.0)
            if await request.is_disconnected():
                return

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


def _max_event_seq(session: SessionDep) -> int:
    with session.store.connect() as conn:
        row = conn.execute("SELECT MAX(event_seq) AS n FROM events").fetchone()
    return int(row["n"]) if row and row["n"] is not None else 0


def _run_status(session: SessionDep, run_id: str) -> str:
    try:
        return str(session.store.get_run(run_id)["status"])
    except SynLabError:
        return "UNKNOWN"


__all__ = ["router"]
