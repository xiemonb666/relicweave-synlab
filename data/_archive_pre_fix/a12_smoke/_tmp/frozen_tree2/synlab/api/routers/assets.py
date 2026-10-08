"""Assets, typed metadata, role-whitelisted file download and the research truth entry.

Role rules (plan 21.1, 30.16): the generic asset routes never serve research answers to a
non-researcher session, and the truth route lives behind a separate research mount that a
deployment package does not carry.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import Response

from ...errors import SynLabError
from ...roles import (
    ROLE_CLEAN_TRUTH,
    ROLE_DISPLAY_LOD,
    ROLE_FRAGMENT_MESH,
    ROLE_MOTHER_MESH,
    ROLE_OBS_RESULT,
    ROLE_OBS_VIEW,
    ROLE_PHYSICAL_TRUTH,
    ROLE_VISIBLE_LABELS,
)
from ..deps import SessionDep
from ..integrity import resolve_file, role_mismatch, verify_all_files
from ..pagination import MAX_LIMIT, page_assets
from ..problems import (
    API_CODE_FILE_ROLE_NOT_SERVABLE,
    API_CODE_NOT_FOUND,
    ApiProblem,
    from_synlab,
)
from ..security import (
    DEPLOYMENT_SAFE_ROLES,
    RESEARCH_ONLY_ROLES,
    require_truth_access,
    require_workspace_match,
    resolve_asset_ref,
)

router = APIRouter(tags=["assets"])

#: roles whose payload may be streamed through ``GET /assets/{id}/files/{role}``
SERVABLE_FILE_ROLES: frozenset[str] = frozenset({
    ROLE_MOTHER_MESH, ROLE_FRAGMENT_MESH, ROLE_DISPLAY_LOD, ROLE_OBS_VIEW, ROLE_OBS_RESULT,
    "mother_meta", "material_profile", "pattern_recipe", "pattern_channels", "pattern_audit",
    "cutter_mesh", "physical_component", "physical_result", "obs_fused_geometry",
    "feature_bundle", "relation_pool", "query_roster", "episode_trace", "train_checkpoint",
    "train_metrics", "diagnostic_report", "operator_audit", "qa_report", "coverage",
    "run_spec", "mvs_result", "provenance",
    # research roles stay servable, but only for a researcher session
    *sorted(RESEARCH_ONLY_ROLES),
})

#: deterministic payload-key priority for the default download
FILE_KEY_PRIORITY: tuple[str, ...] = (
    "glb.bin", "mesh.bin", "preview.bin", "data.bin", "arrays", "meta",
)

MEDIA_TYPES: dict[str, str] = {
    "glb.bin": "model/gltf-binary",
    "mesh.bin": "application/octet-stream",
    "meta": "application/json",
    "arrays": "application/octet-stream",
}


@router.get("/assets", summary="分页资产列表（kind/split/lineage/QA），不暴露服务器任意路径")
def get_assets(
    session: SessionDep,
    role: list[str] | None = Query(None, description="按 asset role 过滤（可重复）"),
    split: str | None = Query(None),
    lineage_id: str | None = Query(None),
    qa_status: str | None = Query(None, pattern="^(QA_PASS|QA_PENDING|QA_FAIL)$"),
    limit: int | None = Query(None, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(None),
    with_total: bool = Query(False),
    include_research_roles: bool = Query(False, description="部署/运维会话会被拒绝"),
) -> dict[str, Any]:
    is_research = session.policy.can_read_truth
    requested_roles = list(role or [])
    if requested_roles:
        if not is_research:
            forbidden = [r for r in requested_roles if r in RESEARCH_ONLY_ROLES]
            if forbidden:
                raise ApiProblem(403, "ROLE_FORBIDDEN",
                                 f"role(s) {forbidden} carry research answers; use the research entry",
                                 stage="assets.roles", details={"role": session.role})
    else:
        requested_roles = sorted(DEPLOYMENT_SAFE_ROLES) if not is_research else []
    if include_research_roles and not is_research:
        raise ApiProblem(403, "ROLE_FORBIDDEN",
                         "include_research_roles requires a researcher session", stage="assets.roles")
    exclude = () if is_research else tuple(sorted(RESEARCH_ONLY_ROLES))
    payload = page_assets(session.store, roles=requested_roles or None, exclude_roles=exclude,
                          lineage_id=lineage_id, split=split, qa_status=qa_status,
                          workspace=session.workspace, limit=limit, cursor=cursor,
                          with_total=with_total)
    payload["ok"] = True
    payload["role_filter"] = requested_roles or None
    payload["role_filter_default"] = "deployment-safe roles" if not is_research and not role else None
    payload["research_roles_hidden"] = sorted(exclude)
    payload["empty_reason"] = (None if payload["items"] else
                               "no asset in this workspace matches the filter; "
                               "run a job first — the API never fabricates placeholder assets")
    return payload


@router.get("/assets/{asset_id}", summary="typed 观测 metadata / preview refs（默认不含 truth）")
def get_asset(session: SessionDep, asset_id: str) -> dict[str, Any]:
    resolved = resolve_asset_ref(asset_id)
    try:
        record = session.store.get_asset(resolved)
    except SynLabError as exc:
        raise from_synlab(exc) from exc
    require_workspace_match(session.policy, session.workspace, (record.meta or {}).get("workspace"),
                            object_kind="asset", object_id=resolved)
    require_truth_access(session.policy, record.role, stage="assets.get")
    integrity = verify_all_files(session.store, resolved)
    payload = record.as_dict()
    payload.pop("path", None)
    payload["integrity"] = {"ok": integrity["ok"], "problems": integrity["problems"],
                            "files": integrity["files"]}
    payload["file_urls"] = {
        name: f"/api/synlab/assets/{resolved}/files/{quote(record.role)}?key={quote(name)}"
        for name in sorted(record.files)
    }
    payload["research_only_role"] = record.role in RESEARCH_ONLY_ROLES
    if not session.policy.can_read_ancestry:
        payload["ancestry"] = []
        payload["ancestry_hidden"] = True
    return {"ok": True, "asset": payload, "role": session.role,
            "display_transform": (record.meta or {}).get("display_transform")}


@router.get("/assets/{asset_id}/files/{role}", summary="preview/合法数据流：role 白名单 + 存在/hash 核验")
def get_asset_file(
    session: SessionDep,
    asset_id: str,
    role: str,
    key: str | None = Query(None, description="payload file key；缺省按确定性优先级选择"),
    download: bool = Query(True),
    verify: bool = Query(True),
) -> Response:
    resolved = resolve_asset_ref(asset_id)
    if role not in SERVABLE_FILE_ROLES:
        raise ApiProblem(
            403, API_CODE_FILE_ROLE_NOT_SERVABLE,
            f"file role {role!r} is not on the servable whitelist",
            stage="assets.files",
            details={"whitelist_size": len(SERVABLE_FILE_ROLES),
                     "hint": "roles are the registered asset roles from synlab/roles.py"},
        )
    try:
        record = session.store.get_asset(resolved)
    except SynLabError as exc:
        raise from_synlab(exc) from exc
    require_workspace_match(session.policy, session.workspace, (record.meta or {}).get("workspace"),
                            object_kind="asset", object_id=resolved)
    require_truth_access(session.policy, record.role, stage="assets.files")
    if record.role != role:
        raise role_mismatch(record.role, role)

    file_name = key
    if file_name is None:
        for candidate in FILE_KEY_PRIORITY:
            if candidate in record.files:
                file_name = candidate
                break
    if file_name is None:
        raise ApiProblem(404, API_CODE_NOT_FOUND,
                         f"asset {resolved} has no downloadable payload", stage="assets.files")
    if file_name not in record.files:
        raise ApiProblem(404, API_CODE_NOT_FOUND,
                         f"asset {resolved} has no payload key {file_name!r}",
                         stage="assets.files", details={"available": sorted(record.files)})

    ref = resolve_file(session.store, resolved, file_name, verify=verify)
    body = ref.path.read_bytes()
    media = MEDIA_TYPES.get(file_name) or _guess_media(file_name)
    headers = {
        "X-SynLab-Asset-Id": resolved,
        "X-SynLab-Asset-Role": record.role,
        "X-SynLab-File-Key": file_name,
        "X-SynLab-File-Sha256": ref.sha256,
        "X-SynLab-Hash-Verified": ref.hash_verified,
        "X-SynLab-Unit": record.unit,
        "X-SynLab-Frame": record.frame,
        "X-SynLab-QA-Status": record.qa_status,
        "Cache-Control": "private, max-age=0, must-revalidate",
    }
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{resolved}_{file_name}"'
    return Response(content=body, media_type=media, headers=headers)


def _guess_media(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith((".glb", ".gltf")):
        return "model/gltf-binary"
    if lowered.endswith(".json"):
        return "application/json"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".npz"):
        return "application/octet-stream"
    return "application/octet-stream"


# ---------------------------------------------------------------- research-only mount
research_router = APIRouter(tags=["research"])

TRUTH_ROLES = (ROLE_CLEAN_TRUTH, ROLE_PHYSICAL_TRUTH, ROLE_VISIBLE_LABELS, "spurious_mask")


@research_router.get("/research/assets/{asset_id}/truth", summary="typed 研究标签（研究角色专属）")
def get_research_truth(
    session: SessionDep,
    asset_id: str,
    include_arrays: bool = Query(False, description="是否包含数组键名清单（不含像素数据）"),
) -> dict[str, Any]:
    resolved = resolve_asset_ref(asset_id)
    try:
        record = session.store.get_asset(resolved)
    except SynLabError as exc:
        raise from_synlab(exc) from exc
    require_workspace_match(session.policy, session.workspace, (record.meta or {}).get("workspace"),
                            object_kind="asset", object_id=resolved)
    if not session.policy.can_read_truth:
        raise ApiProblem(403, "ROLE_FORBIDDEN",
                         f"role {session.role!r} may not read research truth", stage="research.truth")
    integrity = verify_all_files(session.store, resolved)
    keys: list[str] = []
    if include_arrays:
        try:
            keys = sorted(session.store.load_arrays(resolved).keys())
        except SynLabError:
            keys = []
    return {
        "ok": True,
        "asset_id": resolved,
        "role": record.role,
        "schema": record.schema,
        "unit": record.unit,
        "frame": record.frame,
        "qa_status": record.qa_status,
        "qa": record.qa,
        "meta": record.meta,
        "ancestry": record.ancestry,
        "lineage_id": record.lineage_id,
        "split": record.split,
        "interpretation_hash": record.interpretation_hash,
        "array_keys": keys,
        "integrity": {"ok": integrity["ok"], "problems": integrity["problems"]},
        "truth_role": record.role in TRUTH_ROLES,
        "access": {"role": session.role, "session_id": session.session_id,
                   "note": "研究入口不与部署 adapter 相连；部署包不挂载本路由"},
    }


__all__ = ["router", "research_router", "SERVABLE_FILE_ROLES"]
