"""Pools, training runs, diagnostics runs and episodes (plan 21.1 rows 19-25).

Every route here is capability-gated: when the owning module is not importable the API
answers ``503 DEPENDENCY_CAPABILITY_MISSING`` and records nothing, so the UI can show a
blocked state with the real reason instead of a plausible-looking empty chart.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Query

from ...errors import SynLabError
from ..capabilities import probe_capability
from ..deps import (
    DiagnosticsRunEnvelope,
    EpisodeResetEnvelope,
    EpisodeStepEnvelope,
    PoolEnvelope,
    SessionDep,
    TrainingRunEnvelope,
)
from ..pagination import DEFAULT_LIMIT, MAX_LIMIT
from ..problems import API_CODE_NOT_FOUND, ApiProblem, from_synlab
from ..security import (
    RESEARCH_ONLY_ROLES,
    require_job_control,
    require_training_start,
    require_workspace_match,
    resolve_resource_ref,
)
from ..tables import get as table_get, insert as table_insert, list_rows, update as table_update

router = APIRouter(tags=["learning"])


def _capability_or_503(key: str, *, stage: str, detail: str) -> Any:
    probe = probe_capability(key)
    if not probe.available:
        raise ApiProblem(
            503, "DEPENDENCY_CAPABILITY_MISSING",
            f"{detail}: capability {key!r} ({probe.module}) is not usable — {probe.error}",
            stage=stage, retryable=False, details={"capability": probe.as_dict()},
        )
    return probe


def _enqueue(session: SessionDep, *, stage: str, spec: dict[str, Any], prefix: str,
             table: str, id_key: str, inputs: list[str] | None = None) -> dict[str, Any]:
    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    identifier = f"{prefix}_{stamp}_{int(time.time() * 1000) % 100000:05d}"
    run_id = "run_" + identifier.split("_", 1)[-1]
    session.store.create_run(run_id, stage, "SYNTHETIC", None,
                             meta={"workspace": session.workspace, id_key: identifier})
    job_id = "job_" + identifier.split("_", 1)[-1]
    session.scheduler.create_job(job_id=job_id, run_id=run_id, stage=stage,
                                 spec={"workspace": session.workspace, id_key: identifier, **spec},
                                 inputs=inputs or [])
    row = table_insert(session.store, table, {
        id_key: identifier, "status": "NOT_RUN", "job_id": job_id,
        "workspace": session.workspace, **spec,
    })
    return {"identifier": identifier, "run_id": run_id, "job_id": job_id, "row": row}


# --------------------------------------------------------------------------- pools
@router.post("/pools", status_code=202, summary="release + gallery spec → pool job（互斥事件/全 R2 检查）")
def post_pools(session: SessionDep, body: PoolEnvelope) -> dict[str, Any]:
    require_job_control(session.policy, stage="pools.create", action="enqueue a pool job")
    _capability_or_503("relations", stage="pools.create", detail="building a relation pool")
    manifest = session.releases.load(body.release_id)
    made = _enqueue(session, stage="pool",
                    spec={"release_id": body.release_id, "spec": body.spec,
                          "manifest_hash": manifest.get("manifest_hash")},
                    prefix="pool", table="api_pools", id_key="pool_id")
    return {"ok": True, "accepted": True, "pool_id": made["identifier"], "job_id": made["job_id"],
            "run_id": made["run_id"], "status": made["row"]["status"],
            "events_url": f"/api/synlab/runs/{made['run_id']}/events",
            "note": "R2 不得进入负例、同一母体的替代事件不得混池；这些检查由 relations 模块执行"}


@router.get("/pools", summary="池列表")
def list_pools(session: SessionDep, limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)) -> dict[str, Any]:
    rows = list_rows(session.store, "api_pools", workspace=session.workspace, limit=limit)
    return {"ok": True, "count": len(rows), "items": rows,
            "capability": probe_capability("relations").as_dict()}


@router.get("/pools/{pool_id}", summary="固定库/查询 manifest（研究与部署响应分离）")
def get_pool(session: SessionDep, pool_id: str) -> dict[str, Any]:
    row = table_get(session.store, "api_pools", "pool_id", resolve_resource_ref(pool_id, kind="pool"))
    if row is None:
        raise ApiProblem(404, API_CODE_NOT_FOUND, f"unknown pool {pool_id!r}", stage="pools.get")
    require_workspace_match(session.policy, session.workspace, row.get("workspace"),
                            object_kind="pool", object_id=pool_id)
    if not session.policy.can_read_truth:
        result = dict(row.get("result") or {})
        for key in list(result):
            if key in RESEARCH_ONLY_ROLES or key in ("spurious_mask", "hard_case_tag", "truth_labels"):
                result.pop(key, None)
        row = {**row, "result": result, "research_sections_hidden": True}
    return {"ok": True, "pool": row,
            "response_profile": "research" if session.policy.can_read_truth else "deployment",
            "capability": probe_capability("relations").as_dict()}


# --------------------------------------------------------------------------- training
@router.post("/training/runs", status_code=202, summary="release + train spec → job（GPU 租约、冻结输入合同）")
def post_training_runs(session: SessionDep, body: TrainingRunEnvelope) -> dict[str, Any]:
    require_training_start(session.policy, stage="training.create", action="start training")
    _capability_or_503("training", stage="training.create", detail="starting a training run")
    from .meta import _gpu_availability

    gpu = _gpu_availability()
    validation = _validate_train_spec(body.spec)
    if not validation["ok"]:
        raise ApiProblem(422, "SCHEMA_INVALID",
                         f"train spec rejected: {len(validation['errors'])} error(s)",
                         stage="training.create", details={"validation": validation})
    made = _enqueue(session, stage="training",
                    spec={"spec": body.spec, "spec_hash": validation.get("spec_hash"),
                          "release_id": body.release_id, "device": body.spec.get("device", "auto")},
                    prefix="train", table="api_training_runs", id_key="training_run_id")
    return {"ok": True, "accepted": True, "training_run_id": made["identifier"],
            "job_id": made["job_id"], "run_id": made["run_id"], "status": made["row"]["status"],
            "spec_hash": validation.get("spec_hash"), "gpu": gpu,
            "gpu_blocked": None if gpu["cuda_available"] else {
                "code": "ENV_CAPABILITY_MISSING", "reason": gpu["detail"]},
            "events_url": f"/api/synlab/runs/{made['run_id']}/events",
            "note": "曲线只来自实测日志；没有 GPU 时 device=cuda 的 run 必须在 UI 上显示阻塞"}


def _validate_train_spec(spec: dict[str, Any]) -> dict[str, Any]:
    from ..specs import validate_spec

    return validate_spec(spec, kind="train")


@router.get("/training/runs", summary="训练 run 列表")
def list_training_runs(session: SessionDep,
                       limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)) -> dict[str, Any]:
    rows = list_rows(session.store, "api_training_runs", workspace=session.workspace, limit=limit)
    return {"ok": True, "count": len(rows), "items": rows,
            "capability": probe_capability("training").as_dict()}


@router.get("/training/runs/{training_run_id}", summary="state/checkpoints/metrics（实测训练）")
def get_training_run(session: SessionDep, training_run_id: str) -> dict[str, Any]:
    row = table_get(session.store, "api_training_runs", "training_run_id",
                    resolve_resource_ref(training_run_id, kind="training_run"))
    if row is None:
        raise ApiProblem(404, API_CODE_NOT_FOUND, f"unknown training run {training_run_id!r}",
                         stage="training.get")
    require_workspace_match(session.policy, session.workspace, row.get("workspace"),
                            object_kind="training_run", object_id=training_run_id)
    jobs = session.scheduler.list_jobs(run_id=_run_of(session, row), limit=200)
    checkpoints = [a for job in jobs for a in job.outputs]
    return {"ok": True, "training_run": row,
            "jobs": [j.as_dict() for j in jobs],
            "checkpoint_assets": checkpoints,
            "metrics": (row.get("result") or {}).get("metrics", {}),
            "curves": (row.get("result") or {}).get("curves", []),
            "capability": probe_capability("training").as_dict(),
            "not_run_reason": None if row.get("result") else
            f"status={row['status']}：未运行的训练不生成任何 loss 曲线"}


def _run_of(session: SessionDep, row: dict[str, Any]) -> str:
    job_id = row.get("job_id")
    if not job_id:
        return ""
    try:
        return session.scheduler.get_job(job_id).run_id
    except SynLabError:
        return ""


@router.post("/training/runs/{training_run_id}/resume", status_code=202,
             summary="checkpoint ref → job（release/config 一致检查）")
def post_training_resume(session: SessionDep, training_run_id: str,
                         body: dict[str, Any] | None = None) -> dict[str, Any]:
    require_training_start(session.policy, stage="training.resume", action="resume training")
    _capability_or_503("training", stage="training.resume", detail="resuming a training run")
    row = table_get(session.store, "api_training_runs", "training_run_id",
                    resolve_resource_ref(training_run_id, kind="training_run"))
    if row is None:
        raise ApiProblem(404, API_CODE_NOT_FOUND, f"unknown training run {training_run_id!r}",
                         stage="training.resume")
    require_workspace_match(session.policy, session.workspace, row.get("workspace"),
                            object_kind="training_run", object_id=training_run_id)
    if row.get("status") not in ("COMPLETED", "INTERRUPTED", "PAUSED", "RUNNING"):
        raise ApiProblem(409, "SCHEMA_INVALID",
                         f"cannot resume a training run in status {row['status']!r}",
                         stage="training.resume")
    made = _enqueue(session, stage="training",
                    spec={"resume_of": training_run_id, "spec": row.get("spec"),
                          "checkpoint_ref": (body or {}).get("checkpoint_ref")},
                    prefix="train", table="api_training_runs", id_key="training_run_id")
    return {"ok": True, "accepted": True, "training_run_id": made["identifier"],
            "resume_of": training_run_id, "job_id": made["job_id"], "run_id": made["run_id"],
            "note": "续训必须从实际 step/游标继续，不复用旧曲线"}


# --------------------------------------------------------------------------- diagnostics
@router.post("/diagnostics/runs", status_code=202, summary="checkpoint/pool/protocol → job（冻结实验）")
def post_diagnostics_runs(session: SessionDep, body: DiagnosticsRunEnvelope) -> dict[str, Any]:
    require_job_control(session.policy, stage="diagnostics.create",
                        action="enqueue a diagnostics run")
    _capability_or_503("diagnostics", stage="diagnostics.create", detail="running a diagnosis")
    validation = _validate_diagnose_spec(body.spec)
    if not validation["ok"]:
        raise ApiProblem(422, "SCHEMA_INVALID",
                         f"diagnose spec rejected: {len(validation['errors'])} error(s)",
                         stage="diagnostics.create", details={"validation": validation})
    made = _enqueue(session, stage="diagnostics",
                    spec={"spec": body.spec, "spec_hash": validation.get("spec_hash"),
                          "checkpoint_ref": body.checkpoint_ref, "pool_ref": body.pool_ref},
                    prefix="diag", table="api_diagnostics_runs", id_key="diagnostics_run_id")
    return {"ok": True, "accepted": True, "diagnostics_run_id": made["identifier"],
            "job_id": made["job_id"], "run_id": made["run_id"], "status": made["row"]["status"],
            "spec_hash": validation.get("spec_hash"),
            "events_url": f"/api/synlab/runs/{made['run_id']}/events",
            "note": "确认用途不得选 SANDBOX；未运行的诊断不生成指标"}


def _validate_diagnose_spec(spec: dict[str, Any]) -> dict[str, Any]:
    from ..specs import validate_spec

    return validate_spec(spec, kind="diagnose")


@router.get("/diagnostics/runs", summary="诊断 run 列表")
def list_diagnostics_runs(session: SessionDep,
                          limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)) -> dict[str, Any]:
    rows = list_rows(session.store, "api_diagnostics_runs", workspace=session.workspace, limit=limit)
    return {"ok": True, "count": len(rows), "items": rows,
            "capability": probe_capability("diagnostics").as_dict()}


@router.get("/diagnostics/runs/{diagnostics_run_id}", summary="summary/query refs/curves")
def get_diagnostics_run(session: SessionDep, diagnostics_run_id: str) -> dict[str, Any]:
    row = table_get(session.store, "api_diagnostics_runs", "diagnostics_run_id",
                    resolve_resource_ref(diagnostics_run_id, kind="diagnostics_run"))
    if row is None:
        raise ApiProblem(404, API_CODE_NOT_FOUND,
                         f"unknown diagnostics run {diagnostics_run_id!r}", stage="diagnostics.get")
    require_workspace_match(session.policy, session.workspace, row.get("workspace"),
                            object_kind="diagnostics_run", object_id=diagnostics_run_id)
    result = dict(row.get("result") or {})
    if not session.policy.can_read_truth:
        result.pop("per_query_truth", None)
        result.pop("spurious_mask", None)
    return {"ok": True, "diagnostics_run": {**row, "result": result},
            "curves": result.get("curves", []),
            "queries": result.get("queries", []),
            "capability": probe_capability("diagnostics").as_dict(),
            "not_run_reason": None if result else
            f"status={row['status']}：未运行的诊断不替它生成曲线"}


# --------------------------------------------------------------------------- episodes
@router.post("/episodes/{episode_id}/reset", summary="episode spec → 初始状态（只揭示初始观察）")
def post_episode_reset(session: SessionDep, episode_id: str,
                       body: EpisodeResetEnvelope) -> dict[str, Any]:
    require_job_control(session.policy, stage="episodes.reset", action="drive an episode")
    _capability_or_503("episodes", stage="episodes.reset", detail="resetting an episode")
    identifier = resolve_resource_ref(episode_id, kind="episode")
    state = {
        "tick": 0, "observation": None, "available_actions": [],
        "cost_total": 0.0, "status": "RESET_PENDING",
    }
    existing = table_get(session.store, "api_episodes", "episode_id", identifier)
    if existing is None:
        row = table_insert(session.store, "api_episodes", {
            "episode_id": identifier, "spec": body.spec, "state": state,
            "observation": {"revealed": False}, "steps": [], "cost_total": 0.0,
            "status": "RESET_PENDING", "workspace": session.workspace,
        })
    else:
        require_workspace_match(session.policy, session.workspace, existing.get("workspace"),
                                object_kind="episode", object_id=identifier)
        row = table_update(session.store, "api_episodes", "episode_id", identifier,
                           spec=body.spec, state=state, observation={"revealed": False},
                           steps=[], cost_total=0.0, status="RESET_PENDING")
    return {"ok": True, "episode_id": identifier, "state": row["state"],
            "note": "初始观察由 episodes 模块返回；未揭示的帧不进入 state"}


@router.post("/episodes/{episode_id}/step", summary="available action → 新 state + cost（全库重检）")
def post_episode_step(session: SessionDep, episode_id: str,
                      body: EpisodeStepEnvelope) -> dict[str, Any]:
    require_job_control(session.policy, stage="episodes.step", action="drive an episode")
    _capability_or_503("episodes", stage="episodes.step", detail="stepping an episode")
    identifier = resolve_resource_ref(episode_id, kind="episode")
    row = table_get(session.store, "api_episodes", "episode_id", identifier)
    if row is None:
        raise ApiProblem(404, API_CODE_NOT_FOUND, f"unknown episode {identifier!r}",
                         stage="episodes.step")
    require_workspace_match(session.policy, session.workspace, row.get("workspace"),
                            object_kind="episode", object_id=identifier)
    if row.get("status") == "STOPPED":
        raise ApiProblem(409, "SCHEMA_INVALID",
                         "episode has STOPPED; no further action is accepted", stage="episodes.step")
    return {"ok": True, "episode_id": identifier, "requested_action": body.action,
            "state": row["state"],
            "note": "动作只有在 episodes 模块真实执行后才会推进 tick；本响应不回填未执行的观测"}


@router.get("/episodes/{episode_id}", summary="episode 轨迹")
def get_episode(session: SessionDep, episode_id: str) -> dict[str, Any]:
    identifier = resolve_resource_ref(episode_id, kind="episode")
    row = table_get(session.store, "api_episodes", "episode_id", identifier)
    if row is None:
        raise ApiProblem(404, API_CODE_NOT_FOUND, f"unknown episode {identifier!r}",
                         stage="episodes.get")
    require_workspace_match(session.policy, session.workspace, row.get("workspace"),
                            object_kind="episode", object_id=identifier)
    payload = dict(row)
    if not session.policy.can_read_truth:
        payload.pop("observation", None)
    return {"ok": True, "episode": payload, "capability": probe_capability("episodes").as_dict()}


__all__ = ["router", "from_synlab"]
