"""Capabilities, registry, spec validation, budgets and the stage catalogue."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Query

from ...canonical import hash_json
from ...errors import SynLabError
from ...registry import KINDS, REGISTRY
from ...storage.store import health_check
from ..capabilities import CAPABILITY_MODULES, capability_report, require_capabilities
from ..deps import BudgetEnvelope, SessionDep, SpecEnvelope
from ..handlers import estimate_for
from ..problems import API_CODE_BAD_REQUEST, API_CODE_NOT_FOUND, ApiProblem, from_synlab
from ..specs import SCHEMA_IDS, validate_spec
from ..stages import STAGES, required_capabilities, stage_catalog

router = APIRouter(tags=["meta"])

API_VERSION = "synlab.api.v1"


@router.get("/capabilities", summary="能力、doctor 与 registry 概要；缺能力如实返回")
def get_capabilities(
    session: SessionDep,
    doctor: str = Query("light", pattern="^(none|light|full)$",
                        description="none=仅进程能力; light=SQLite 完整性; full=逐文件 hash 校验"),
    refresh: bool = Query(False, description="绕过 5 秒探测缓存"),
    include_env: bool = Query(True),
    include_registry: bool = Query(True),
) -> dict[str, Any]:
    report = capability_report(refresh=refresh)
    registry_summary = REGISTRY.summary()
    payload: dict[str, Any] = {
        "ok": True,
        "api_version": API_VERSION,
        "prefix": "/api/synlab",
        "server_time": time.time(),
        "session": session.as_dict(),
        "python": report["python"],
        "modules": report["modules"],
        "available": report["available"],
        "missing": report["missing"],
        "stage_requirements": {stage: list(required_capabilities(stage)) for stage in sorted(STAGES)},
        "registry_fingerprint": REGISTRY.fingerprint(),
        "probed_at": report["probed_at"],
        "honesty": {
            "missing_modules": "reported as DEPENDENCY_CAPABILITY_MISSING; no substitute data is produced",
            "missing_backends": "reported as ENV_CAPABILITY_MISSING",
        },
        "worker": {
            "command": session.context.worker_command
            or "python -m synlab.api.worker --store-root <store> --once",
            "in_process_execution": False,
            "note": "re-computation always runs in a separate worker process",
        },
    }
    if include_env:
        payload["env"] = report["env"]
    if include_registry:
        payload["registry"] = registry_summary

    doctor_result: dict[str, Any] = {"mode": doctor, "ok": True, "problems": []}
    if doctor == "light":
        try:
            with session.store.connect() as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                counts = {
                    "assets": int(conn.execute("SELECT COUNT(*) AS n FROM assets").fetchone()["n"]),
                    "jobs": int(conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]),
                    "runs": int(conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]),
                    "releases": int(conn.execute("SELECT COUNT(*) AS n FROM releases").fetchone()["n"]),
                    "events": int(conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]),
                }
            doctor_result.update({"sqlite_integrity": integrity, "counts": counts})
            if integrity != "ok":
                doctor_result["ok"] = False
                doctor_result["problems"].append(f"sqlite integrity: {integrity}")
        except Exception as exc:  # noqa: BLE001 - doctor must never crash the API
            doctor_result.update({"ok": False, "problems": [f"{type(exc).__name__}: {exc}"]})
    elif doctor == "full":
        try:
            result = health_check(session.store.root)
            doctor_result.update({"ok": bool(result["ok"]), "problems": result["problems"][:50],
                                  "files_checked": result["files_checked"], "assets": result["assets"]})
        except Exception as exc:  # noqa: BLE001
            doctor_result.update({"ok": False, "problems": [f"{type(exc).__name__}: {exc}"]})
    payload["doctor"] = doctor_result
    return payload


@router.get("/registry/{kind}", summary="参数 schema、适用组合、版本")
def get_registry_kind(
    session: SessionDep,
    kind: str,
    status: str | None = Query(None, description="SPECIFIED/IMPLEMENTED/QA_PASSED/VALIDATED/PENDING/MISSING"),
    id: str | None = Query(None, description="只取一个 id"),
) -> dict[str, Any]:
    if kind != "all" and kind not in KINDS:
        raise ApiProblem(404, API_CODE_NOT_FOUND,
                         f"unknown registry kind {kind!r}; known: {list(KINDS)}",
                         stage="registry.kind")
    kinds = list(KINDS) if kind == "all" else [kind]
    entries: list[dict[str, Any]] = []
    for one in kinds:
        entries.extend(entry.as_dict() for entry in REGISTRY.list(one, status=status))
    if id is not None:
        entries = [e for e in entries if e["id"] == id]
        if not entries:
            raise ApiProblem(404, API_CODE_NOT_FOUND,
                             f"unregistered {kind} id {id!r} for status filter {status!r}",
                             stage="registry.get")
    missing_kinds = [one for one in kinds if not REGISTRY.list(one)]
    return {
        "ok": True,
        "kind": kind,
        "count": len(entries),
        "entries": entries,
        "empty_kinds": missing_kinds,
        "registry_fingerprint": REGISTRY.fingerprint(),
        "note": "registry 为空表示实现模块尚未注册；API 不会复制一份前端内的范围表",
    }


@router.post("/specs/validate", summary="v3 spec → validation（字段/单位/组合/版本）")
def post_specs_validate(session: SessionDep, body: SpecEnvelope) -> dict[str, Any]:
    result = validate_spec(body.spec, kind=body.kind, registry_check=body.registry_check)
    result["required_capabilities"] = _capabilities_for_spec(body.spec, body.kind)
    return result


def _capabilities_for_spec(spec: dict[str, Any], kind: str = "generation") -> list[str]:
    from ..stages import required_capabilities as _req

    if kind == "recipe" or (isinstance(spec, dict) and "operators" in spec):
        return list(_req("degrade"))
    if kind == "train":
        return list(_req("training"))
    if kind == "diagnose":
        return list(_req("diagnostics"))
    return list(_req("generate"))


@router.post("/budgets", summary="spec → resource estimate（实测基准引用，不写资产）")
def post_budgets(session: SessionDep, body: BudgetEnvelope) -> dict[str, Any]:
    validation = validate_spec(body.spec, kind=body.kind) if body.spec else {"ok": True, "errors": []}
    estimate = estimate_for(body.stage, planned_jobs=body.planned_jobs)
    requires_gpu = body.requires_gpu
    if requires_gpu is None:
        requires_gpu = STAGES[body.stage].requires_gpu if body.stage in STAGES else False
    report = session.guard.budget_report(body.planned_jobs, [estimate])
    report.update({
        "ok": bool(report["feasible"]),
        "stage": body.stage,
        "requires_gpu": bool(requires_gpu),
        "spec_valid": bool(validation.get("ok", True)),
        "spec_errors": validation.get("errors", []),
        "env": _gpu_availability(),
    })
    report["budget_ref"] = "budget_" + hash_json({
        "stage": body.stage, "planned_jobs": body.planned_jobs,
        "rss_gb": report["rss_gb"], "temp_disk_gb": report["temp_disk_gb"],
        "vram_gb": report["vram_gb"], "feasible": report["feasible"],
    }).split(":", 1)[-1][:20]
    if not report["feasible"]:
        raise ApiProblem(
            409, "BUDGET_EXCEEDED",
            f"planned_jobs={body.planned_jobs} stage={body.stage} does not fit the aggregate budget",
            stage="budget.admit", retryable=False,
            details={"budget": report},
        )
    if requires_gpu and report["env"].get("cuda_available") is False:
        report["gpu_blocked"] = {
            "code": "ENV_CAPABILITY_MISSING",
            "reason": report["env"].get("detail"),
        }
    return report


def _gpu_availability() -> dict[str, Any]:
    from ..capabilities import env_report

    probe = env_report().get("cuda", {})
    return {"cuda_available": probe.get("status") == "OK", "status": probe.get("status"),
            "detail": probe.get("detail")}


@router.get("/stages", summary="任务阶段目录（能力需求与成本类）")
def get_stages(session: SessionDep) -> dict[str, Any]:
    return {
        "ok": True,
        "stages": stage_catalog(),
        "capability_modules": CAPABILITY_MODULES,
        "note": "POST /jobs 对能力缺失 fail-closed（503），不会创建半成品 run",
    }


__all__ = ["router", "require_capabilities", "from_synlab", "SynLabError", "API_CODE_BAD_REQUEST"]
