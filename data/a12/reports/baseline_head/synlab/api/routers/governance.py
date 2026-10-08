"""Audits, immutable releases and exports (plan 21.1 rows 12-17)."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Query

from ...errors import SynLabError
from ...storage.release import PROFILE_GATES
from ..deps import (
    AuditEnvelope,
    ExportEnvelope,
    ReleaseEnvelope,
    RetryEnvelope,
    SessionDep,
)
from ..pagination import DEFAULT_LIMIT, MAX_LIMIT
from ..problems import (
    API_CODE_NOT_FOUND,
    API_CODE_UNSUPPORTED_ADAPTER,
    ApiProblem,
    from_synlab,
)
from ..security import require_oracle_adapter, require_workspace_match, resolve_asset_ref
from ..tables import get as table_get, insert as table_insert, list_rows, update as table_update
from ..handlers import EXPORT_ADAPTERS

router = APIRouter(tags=["governance"])


def _not_found(kind: str, identifier: str) -> ApiProblem:
    return ApiProblem(404, API_CODE_NOT_FOUND, f"unknown {kind} {identifier!r}",
                      stage=f"governance.{kind}")


# --------------------------------------------------------------------------- audits
@router.post("/audits", status_code=202, summary="run/release scope → audit job（真值/权限/覆盖/恢复资格）")
def post_audits(session: SessionDep, body: AuditEnvelope) -> dict[str, Any]:
    scope_assets: list[str] = []
    for ref in body.asset_ids:
        asset_id = resolve_asset_ref(ref)
        record = session.store.get_asset(asset_id)
        require_workspace_match(session.policy, session.workspace,
                                (record.meta or {}).get("workspace"),
                                object_kind="asset", object_id=asset_id)
        scope_assets.append(asset_id)
    if body.run_id:
        session.store.get_run(body.run_id)
        for job in session.scheduler.list_jobs(run_id=body.run_id, limit=1000):
            scope_assets.extend(job.outputs)
    if body.release_id:
        manifest = session.releases.load(body.release_id)
        scope_assets.extend(a["asset_id"] for a in manifest.get("assets", []))
    if body.release_profile not in PROFILE_GATES:
        raise ApiProblem(422, "SCHEMA_INVALID",
                         f"unknown release profile {body.release_profile!r}; "
                         f"known: {sorted(PROFILE_GATES)}", stage="audits.profile")
    if body.include_truth and not session.policy.can_read_truth:
        raise ApiProblem(403, "ROLE_FORBIDDEN",
                         "include_truth requires a researcher session", stage="audits.truth")

    audit_id = "audit_" + time.strftime("%Y%m%d%H%M%S", time.gmtime()) + "_" + \
        f"{int(time.time() * 1000) % 100000:05d}"
    run_id = "run_audit_" + audit_id.split("_", 1)[-1]
    session.store.create_run(run_id, "audit", "SYNTHETIC", body.release_profile,
                             meta={"workspace": session.workspace, "audit_id": audit_id})
    job_id = "job_" + audit_id.split("_", 1)[-1]
    session.scheduler.create_job(
        job_id=job_id, run_id=run_id, stage="audit",
        spec={"workspace": session.workspace, "audit_id": audit_id,
              "release_profile": body.release_profile, "asset_ids": sorted(set(scope_assets)),
              "run_id": body.run_id, "release_id": body.release_id,
              "include_truth": body.include_truth},
        inputs=sorted(set(scope_assets)),
    )
    row = table_insert(session.store, "api_audits", {
        "audit_id": audit_id, "run_id": run_id, "release_id": body.release_id,
        "scope": {"run_id": body.run_id, "release_id": body.release_id,
                  "asset_ids": sorted(set(scope_assets)),
                  "release_profile": body.release_profile, "include_truth": body.include_truth},
        "status": "NOT_RUN", "job_id": job_id, "result": {}, "workspace": session.workspace,
    })
    return {"ok": True, "accepted": True, "audit_id": audit_id, "job_id": job_id, "run_id": run_id,
            "status": row["status"], "profile": body.release_profile,
            "scope_asset_count": len(row["scope"]["asset_ids"]),
            "events_url": f"/api/synlab/runs/{run_id}/events",
            "audit_url": f"/api/synlab/audits/{audit_id}",
            "note": "审计由 worker 真实执行；未运行时 GET 返回 NOT_RUN，不生成占位 gate 结果"}


@router.get("/audits/{audit_id}", summary="gate 结果与证据（未运行为未运行）")
def get_audit(session: SessionDep, audit_id: str) -> dict[str, Any]:
    row = table_get(session.store, "api_audits", "audit_id", audit_id)
    if row is None:
        raise _not_found("audit", audit_id)
    require_workspace_match(session.policy, session.workspace, row.get("workspace"),
                            object_kind="audit", object_id=audit_id)
    job = None
    try:
        job = session.scheduler.get_job(row["job_id"]).as_dict() if row.get("job_id") else None
    except SynLabError:
        job = None
    if not session.policy.can_read_truth:
        result = dict(row.get("result") or {})
        result.pop("truth_basis", None)
        row = {**row, "result": result, "truth_hidden": True}
    return {"ok": True, "audit": row, "job": job, "profile_gates": PROFILE_GATES.get(
        (row.get("scope") or {}).get("release_profile", ""), []),
        "note": "status NOT_RUN/QUEUED/RUNNING 时没有任何 gate 结果被推断出来"}


@router.get("/audits", summary="审计列表")
def list_audits(session: SessionDep, limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)) -> dict[str, Any]:
    rows = list_rows(session.store, "api_audits", workspace=session.workspace, limit=limit)
    return {"ok": True, "count": len(rows), "items": rows,
            "empty_reason": None if rows else "no audit has been requested in this workspace"}


# --------------------------------------------------------------------------- releases
@router.post("/releases", status_code=201, summary="committed refs + audit → 只读 release（gate pass 才能冻结）")
def post_releases(session: SessionDep, body: ReleaseEnvelope) -> dict[str, Any]:
    if not session.policy.can_create_release:
        raise ApiProblem(403, "ROLE_FORBIDDEN",
                         f"role {session.role!r} may not freeze releases", stage="releases.create")
    if body.profile not in PROFILE_GATES:
        raise ApiProblem(422, "SCHEMA_INVALID",
                         f"unknown release profile {body.profile!r}; known: {sorted(PROFILE_GATES)}",
                         stage="releases.create")
    audit = table_get(session.store, "api_audits", "audit_id", body.audit_id)
    if audit is None:
        raise _not_found("audit", body.audit_id)
    require_workspace_match(session.policy, session.workspace, audit.get("workspace"),
                            object_kind="audit", object_id=body.audit_id)
    audit_result = audit.get("result") or {}
    if not audit_result:
        raise ApiProblem(409, "STOP_QA",
                         f"audit {body.audit_id} has no result yet (status={audit['status']}); "
                         "a release cannot be frozen on an unrun audit",
                         stage="releases.create",
                         details={"audit_status": audit["status"]})
    audit_gates = audit_result.get("gates", {}).get("gates", {})
    gates = {name: info.get("status", "PENDING") for name, info in audit_gates.items()
             if isinstance(info, dict)}
    asset_ids = [resolve_asset_ref(ref) for ref in body.asset_ids]
    try:
        record = session.releases.freeze(
            release_id=body.release_id, profile=body.profile, scope=body.scope,
            asset_ids=asset_ids, gates=gates, coverage=body.coverage,
            scope_pending=body.scope_pending or None,
            extra={"audit_id": body.audit_id, "frozen_by": session.session_id,
                   "audit_result": {"profile": audit_result.get("profile"),
                                    "release_ready": audit_result.get("gates", {}).get("release_ready")}},
        )
    except SynLabError as exc:
        raise from_synlab(exc) from exc
    return {"ok": True, "release": record.as_dict(), "gates": gates,
            "audit_id": body.audit_id,
            "note": "release 不可变；修复后必须创建新版本"}


@router.get("/releases", summary="发布列表")
def list_releases(session: SessionDep, limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)) -> dict[str, Any]:
    rows = session.releases.list_releases()[:limit]
    return {"ok": True, "count": len(rows), "items": rows,
            "empty_reason": None if rows else "no release frozen yet"}


@router.get("/releases/{release_id}", summary="manifest/hash/coverage（只读）")
def get_release(session: SessionDep, release_id: str) -> dict[str, Any]:
    try:
        manifest = session.releases.load(release_id)
    except SynLabError as exc:
        raise from_synlab(exc) from exc
    assets = manifest.get("assets", [])
    if not session.policy.can_read_truth:
        assets = [{**a, "ancestry": [], "meta": _strip_research(a.get("meta") or {})} for a in assets]
    return {
        "ok": True,
        "release_id": release_id,
        "manifest_hash": manifest.get("manifest_hash"),
        "profile": manifest.get("profile"),
        "scope": manifest.get("scope"),
        "gates": manifest.get("gates"),
        "required_gates": manifest.get("required_gates"),
        "scope_completed": manifest.get("scope_completed"),
        "scope_pending": manifest.get("scope_pending"),
        "coverage": manifest.get("coverage"),
        "closure": manifest.get("closure"),
        "assets": assets,
        "asset_count": len(assets),
        "frozen_at": manifest.get("frozen_at"),
        "readonly": True,
        "manifest_url": f"/api/synlab/releases/{release_id}",
    }


def _strip_research(meta: dict[str, Any]) -> dict[str, Any]:
    blocked = {"spurious_mask", "hard_case_tag", "clean_hidden_surface", "truth_pose"}
    return {k: v for k, v in meta.items() if k not in blocked}


# --------------------------------------------------------------------------- exports
@router.post("/exports", status_code=202, summary="release + adapter → export job（不改原 release）")
def post_exports(session: SessionDep, body: ExportEnvelope) -> dict[str, Any]:
    # Authorisation is checked before the adapter whitelist: an oracle adapter must be
    # refused with 403 ORACLE_EXPORT_FORBIDDEN for a non-research role even when this build
    # does not know that adapter name at all, otherwise the role refusal is masked by a 422.
    require_oracle_adapter(session.policy, body.adapter, stage="exports.adapter")
    if body.adapter not in EXPORT_ADAPTERS:
        raise ApiProblem(422, API_CODE_UNSUPPORTED_ADAPTER,
                         f"unknown adapter {body.adapter!r}; known: {list(EXPORT_ADAPTERS)}",
                         stage="exports.adapter")
    try:
        manifest = session.releases.load(body.release_id)
    except SynLabError as exc:
        raise from_synlab(exc) from exc
    export_id = "export_" + time.strftime("%Y%m%d%H%M%S", time.gmtime()) + "_" + \
        f"{int(time.time() * 1000) % 100000:05d}"
    run_id = "run_" + export_id.split("_", 1)[-1]
    session.store.create_run(run_id, manifest.get("manifest_hash", "export"), manifest.get("scope", "SYNTHETIC"),
                             manifest.get("profile"), meta={"workspace": session.workspace,
                                                            "export_id": export_id})
    job_id = "job_" + export_id.split("_", 1)[-1]
    session.scheduler.create_job(
        job_id=job_id, run_id=run_id, stage="export",
        spec={"workspace": session.workspace, "export_id": export_id, "release_id": body.release_id,
              "adapter": body.adapter, "requested_by": session.session_id,
              "oracle": body.adapter in ("oracle_truth",)},
        inputs=[],
    )
    row = table_insert(session.store, "api_exports", {
        "export_id": export_id, "release_id": body.release_id, "adapter": body.adapter,
        "status": "NOT_RUN", "job_id": job_id, "result": {}, "workspace": session.workspace,
    })
    return {"ok": True, "accepted": True, "export_id": export_id, "job_id": job_id, "run_id": run_id,
            "status": row["status"], "adapter": body.adapter, "release_id": body.release_id,
            "events_url": f"/api/synlab/runs/{run_id}/events",
            "export_url": f"/api/synlab/exports/{export_id}",
            "note": "导出不修改原 release；oracle adapter 仅 researcher 可请求"}


@router.get("/exports/{export_id}", summary="导出状态与校验和")
def get_export(session: SessionDep, export_id: str) -> dict[str, Any]:
    row = table_get(session.store, "api_exports", "export_id", export_id)
    if row is None:
        raise _not_found("export", export_id)
    require_workspace_match(session.policy, session.workspace, row.get("workspace"),
                            object_kind="export", object_id=export_id)
    return {"ok": True, "export": row,
            "note": "status NOT_RUN/QUEUED 表示导出尚未运行；不返回占位包"}
