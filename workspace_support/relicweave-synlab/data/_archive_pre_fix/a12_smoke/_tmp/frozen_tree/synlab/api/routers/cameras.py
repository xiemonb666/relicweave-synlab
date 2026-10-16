"""Camera / capture profiles (plan 21.1 row 18, page U06).

``GET`` always answers with real stored profiles plus the capability status of
``synlab.cameras``.  ``POST`` validates through the camera module — registering an
unvalidated calibration is refused instead of accepted silently.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Query

from ...errors import SynLabError
from ..capabilities import probe_capability
from ..deps import CameraProfileEnvelope, SessionDep
from ..pagination import DEFAULT_LIMIT, MAX_LIMIT
from ..problems import API_CODE_NOT_FOUND, ApiProblem
from ..security import require_training_start, require_workspace_match
from ..serde import jsonable
from ..tables import get as table_get, insert as table_insert, list_rows

router = APIRouter(tags=["cameras"])

#: actions a profile may declare; the UI slider must not exceed these (plan U06 acceptance)
REACHABLE_ACTIONS = ("GLOBAL_ROTATE", "MID_ORBIT", "LOCAL_DOLLY", "FOCUS_STEP", "LIGHT_STATE")

CALIBRATION_STATES = ("UNCALIBRATED", "MANUFACTURER", "MEASURED", "SYNTHETIC_GT")


@router.get("/camera-profiles", summary="校准 profile 列表 + 可达动作 + 标定状态")
def list_camera_profiles(
    session: SessionDep,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    tier: str | None = Query(None, pattern="^(GLOBAL|MID|LOCAL)$"),
) -> dict[str, Any]:
    probe = probe_capability("cameras")
    where = "tier = ?" if tier else ""
    rows = list_rows(session.store, "api_camera_profiles", workspace=session.workspace,
                     where=where, params=[tier] if tier else None, limit=limit)
    catalogue: list[dict[str, Any]] = []
    if probe.available:
        try:
            import importlib

            module = importlib.import_module("synlab.cameras.api")
            catalogue = jsonable(list(module.camera_profiles()))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - reported, never hidden
            catalogue = []
            probe = probe.__class__(probe.key, probe.module, "DEPENDENCY_CAPABILITY_MISSING",
                                    error=f"camera_profiles() failed: {type(exc).__name__}: {exc}")
    return {
        "ok": True,
        "capability": probe.as_dict(),
        "registered": rows,
        "catalogue": catalogue,
        "reachable_actions": list(REACHABLE_ACTIONS),
        "calibration_states": list(CALIBRATION_STATES),
        "blocked_reason": None if probe.available else (
            "synlab.cameras 未就绪：无法枚举真实档位，页面显示阻塞而不是示例数值"),
        "empty_reason": None if rows or catalogue else "no camera profile registered in this workspace",
    }


@router.post("/camera-profiles", status_code=201, summary="注册新 profile 版本（GLOBAL/MID/LOCAL）")
def create_camera_profile(session: SessionDep, body: CameraProfileEnvelope) -> dict[str, Any]:
    require_training_start(session.policy, stage="cameras.create",
                           action="register a camera profile")
    probe = probe_capability("cameras")
    if not probe.available:
        raise ApiProblem(
            503, "DEPENDENCY_CAPABILITY_MISSING",
            f"registering a camera profile requires synlab.cameras: {probe.error}",
            stage="cameras.create", retryable=False,
            details={"capability": probe.as_dict()},
        )
    unknown_actions = [a for a in (body.payload.get("reachable_actions") or [])
                       if a not in REACHABLE_ACTIONS]
    if unknown_actions:
        raise ApiProblem(422, "SCHEMA_INVALID",
                         f"unreachable actions requested: {unknown_actions}",
                         stage="cameras.create",
                         details={"allowed": list(REACHABLE_ACTIONS)})
    if body.payload.get("calibrated") and body.calibration_source == "UNCALIBRATED":
        raise ApiProblem(422, "SCHEMA_INVALID",
                         "a profile cannot claim calibrated=True with calibration_source=UNCALIBRATED",
                         stage="cameras.create")
    existing = table_get(session.store, "api_camera_profiles", "profile_id", body.profile_id)
    if existing is not None and existing.get("version") == body.version:
        raise ApiProblem(409, "ASSET_HASH_MISMATCH",
                         f"camera profile {body.profile_id} version {body.version} already exists; "
                         "bump the version instead of overwriting a calibration",
                         stage="cameras.create")
    row = table_insert(session.store, "api_camera_profiles", {
        "profile_id": body.profile_id, "version": body.version, "tier": body.tier,
        "status": "REGISTERED", "payload": body.payload,
        "calibration_source": body.calibration_source, "workspace": session.workspace,
    })
    return {"ok": True, "profile": row, "registered_at": time.time(),
            "note": "profile 只描述采集档；未实拍标定的档位在 UI 上必须显示未校准"}


@router.get("/camera-profiles/{profile_id}", summary="单个 profile（含历史版本）")
def get_camera_profile(session: SessionDep, profile_id: str) -> dict[str, Any]:
    rows = list_rows(session.store, "api_camera_profiles", workspace=session.workspace,
                     where="profile_id = ?", params=[profile_id], limit=MAX_LIMIT,
                     order="created_at DESC, profile_id ASC")
    if not rows:
        raise ApiProblem(404, API_CODE_NOT_FOUND, f"unknown camera profile {profile_id!r}",
                         stage="cameras.get")
    require_workspace_match(session.policy, session.workspace, rows[0].get("workspace"),
                            object_kind="camera_profile", object_id=profile_id)
    return {"ok": True, "profile_id": profile_id, "versions": rows,
            "latest": rows[0], "count": len(rows)}


__all__ = ["router", "REACHABLE_ACTIONS", "SynLabError"]
