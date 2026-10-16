"""只读展示路由：``/api/synlab/showcase/*``（合成数据展示页的数据源）。

两条路由，**只读**、不改既有语义、不新增角色要求：

* ``GET /showcase/manifest`` —— 读 ``data/a12_demo/demo_manifest.json``（由
  ``tools/build_demo_assets.py`` 生成），原样返回条目列表 + 真实指标 + 状态。
  清单不存在时返回 ``status="NOT_RUN"`` 与生成命令，**不返回任何假数据**。
* ``GET /showcase/asset/{asset_id}/{key}`` —— 只服务白名单 key ``glb`` / ``png`` /
  ``arrays`` / ``meta``；解析到清单所属的演示资产库，校验文件存在性与内容哈希，
  返回正确的 Content-Type。越权 / 未知 key / 未知资产一律走结构化错误信封。

设计要点
--------

* 展示资产住在**独立的演示资产库**（``data/a12_demo/store``），与会话的
  ``store_root`` 无关；因此部署角色（``deployment_client``）也能只读浏览展示页，
  而不会因此获得任何研究真值。研究真值路由的挂载策略完全不变。
* key 白名单是"类别"；``name`` 可选参数只在**该资产已记录的 payload key**里挑选，
  仍然逐个做 sha256 校验，不能借此读到资产之外的文件。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from ...errors import SynLabError
from ...storage.store import AssetStore
from ..deps import SessionDep
from ..integrity import resolve_file
from ..problems import API_CODE_NOT_FOUND, ApiProblem, from_synlab

router = APIRouter(tags=["showcase"])

MANIFEST_NAME = "demo_manifest.json"
SHOWCASE_SUBDIR = "a12_demo"
#: 与 `tools/build_demo_assets.py::GENERATOR_COMMAND` 保持一致（测试会断言相等）。
GENERATOR_COMMAND = "& .venv\\Scripts\\python.exe tools\\build_demo_assets.py"

#: 白名单 key -> (payload key 候选, Content-Type)。``png``/``glb`` 允许用 ``name`` 细化。
KEY_WHITELIST: dict[str, dict[str, Any]] = {
    "glb": {"keys": ("glb", "glb.bin", "mesh.glb", "scene.glb"), "media_type": "model/gltf-binary",
            "suffix": ".glb"},
    "png": {"keys": ("png", "image", "albedo_png", "roughness_png", "height_png", "render_png"),
            "media_type": "image/png", "suffix": ".png"},
    "arrays": {"keys": ("arrays", "arrays.npz"), "media_type": "application/octet-stream",
               "suffix": ".npz"},
    "meta": {"keys": ("meta", "meta.json"), "media_type": "application/json", "suffix": ".json"},
}

TEXT_KEYS = frozenset({"meta"})


class ShowcaseLocator:
    """解析展示清单与演示资产库的位置（不触碰 ``AppContext``，语义零变更）。"""

    def __init__(self, store_root: Path | str, explicit: Path | str | None = None) -> None:
        self.store_root = Path(store_root)
        self.explicit = Path(explicit) if explicit else None

    # ------------------------------------------------------------------ resolution
    def candidate_roots(self) -> list[Path]:
        """显式 ``showcase_root`` 是**严格覆盖**：给了它就只看它，不再回退到仓库默认位置。

        没有显式给定时才按「会话 store_root → 其父目录下的 a12_demo → 进程工作目录下的
        data/a12_demo」依次查找（后者让 `data/a12` 这类会话根也能找到演示集）。
        """
        if self.explicit is not None:
            return [self.explicit]
        roots = [self.store_root, self.store_root.parent / SHOWCASE_SUBDIR,
                 Path.cwd() / "data" / SHOWCASE_SUBDIR]
        seen: set[str] = set()
        unique: list[Path] = []
        for root in roots:
            key = str(root.resolve()) if root.exists() else str(root)
            if key in seen:
                continue
            seen.add(key)
            unique.append(root)
        return unique

    def resolve(self) -> tuple[Path | None, Path | None]:
        """Return ``(manifest_path, showcase_root)``; either may be ``None``."""
        for root in self.candidate_roots():
            manifest = root / MANIFEST_NAME
            if manifest.is_file():
                return manifest, root
            nested = root / SHOWCASE_SUBDIR / MANIFEST_NAME
            if nested.is_file():
                return nested, nested.parent
        default = self.candidate_roots()[0] / MANIFEST_NAME
        return None, default.parent

    def manifest_path(self) -> Path:
        return self.resolve()[0] or (self.candidate_roots()[-1] / MANIFEST_NAME)

    def store(self) -> AssetStore | None:
        manifest, root = self.resolve()
        if manifest is None or root is None:
            return None
        store_root = root / "store"
        if not store_root.is_dir():
            return None
        return AssetStore(store_root)


def locator_for(request: Request) -> ShowcaseLocator:
    locator = getattr(request.app.state, "showcase", None)
    if locator is None:  # pragma: no cover - create_app always sets it
        locator = ShowcaseLocator(request.app.state.ctx.store_root)
    return locator


def _display_path(path: Path | None) -> str:
    """仓库相对路径（不含服务器绝对路径），与 ``/assets`` 的脱敏口径一致。"""
    if path is None:
        return f"data/{SHOWCASE_SUBDIR}/{MANIFEST_NAME}"
    try:
        parts = path.resolve().parts
        if "relicweave-synlab" in parts:
            index = parts.index("relicweave-synlab")
            return "/".join(parts[index + 1:])
    except OSError:  # pragma: no cover - defensive
        pass
    return path.name


def _manifest_summary(payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("entries") or []
    counts = payload.get("counts") or {}
    return {
        "entry_count": len(entries),
        "counts": counts,
        "kinds": sorted({str(e.get("kind")) for e in entries}),
        "statuses": sorted({str(e.get("status")) for e in entries}),
    }


@router.get("/showcase/manifest", summary="展示清单（只读，未生成时返回 NOT_RUN，不返回假数据）")
def get_showcase_manifest(session: SessionDep, request: Request) -> dict[str, Any]:
    """返回 ``data/a12_demo/demo_manifest.json`` 的真实内容（不做任何加工或补零）。"""
    locator = locator_for(request)
    manifest_path, root = locator.resolve()
    base: dict[str, Any] = {
        "ok": True,
        "manifest_path": _display_path(manifest_path or (locator.manifest_path())),
        "store_path": _display_path((root / "store") if root else None),
        "generator_command": GENERATOR_COMMAND,
        "generator": "tools/build_demo_assets.py",
        "role": session.role,
        "workspace": session.workspace,
        "read_only": True,
    }
    if manifest_path is None or not manifest_path.is_file():
        base.update({
            "status": "NOT_RUN",
            "generated_at": None,
            "entries": [],
            "axis_catalog": [],
            "runs": [],
            "environment_findings": [],
            "fracture_backends": {},
            "counts": {"by_kind": {}, "total": {"OK": 0, "FAILED": 0, "BLOCKED": 0, "NA": 0},
                       "entries": 0},
            "empty_reason": (
                "演示数据集尚未生成：本工作区没有 demo_manifest.json。"
                f"请运行 {GENERATOR_COMMAND}（API 不会返回任何占位或假数据）。"),
        })
        return base
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApiProblem(
            409, "SHOWCASE_MANIFEST_UNREADABLE",
            f"demo_manifest.json 存在但无法解析：{type(exc).__name__}: {exc}",
            stage="showcase.manifest",
            details={"manifest_path": _display_path(manifest_path)},
        ) from exc
    entries = payload.get("entries") or []
    base.update({
        "status": "OK" if entries else "NOT_RUN",
        "generated_at": payload.get("generated_at"),
        "updated_at": payload.get("updated_at"),
        "master_seed": payload.get("master_seed"),
        "lineage_id": payload.get("lineage_id"),
        "schema": payload.get("schema"),
        "entries": entries,
        "axis_catalog": payload.get("axis_catalog") or [],
        "runs": payload.get("runs") or [],
        "notes": payload.get("notes") or [],
        "environment_findings": payload.get("environment_findings") or [],
        "fracture_backends": payload.get("fracture_backends") or {},
        "counts": payload.get("counts") or {},
        "summary": _manifest_summary(payload),
        "empty_reason": (None if entries else
                         "清单存在但没有条目；请重新运行 " + GENERATOR_COMMAND),
    })
    return base


def _pick_payload_key(record: Any, key: str, name: str | None) -> str:
    spec = KEY_WHITELIST[key]
    available = sorted(record.files or {})
    if not available:
        raise ApiProblem(404, API_CODE_NOT_FOUND,
                         f"资产 {record.asset_id}（role={record.role}）没有任何 payload 文件",
                         stage="showcase.asset")
    if name:
        if name not in available:
            raise ApiProblem(
                404, API_CODE_NOT_FOUND,
                f"资产 {record.asset_id} 没有 payload key {name!r}",
                stage="showcase.asset", details={"available": available})
        if key == "png" and not name.lower().endswith(("png", "image")):
            raise ApiProblem(
                422, "SHOWCASE_KEY_MISMATCH",
                f"key=png 但 payload key {name!r} 不是 PNG 类文件",
                stage="showcase.asset", details={"available": available})
        if key == "glb" and not name.lower().endswith(("glb", "mesh", "model")):
            raise ApiProblem(
                422, "SHOWCASE_KEY_MISMATCH",
                f"key=glb 但 payload key {name!r} 不是 GLB 类文件",
                stage="showcase.asset", details={"available": available})
        return name
    for candidate in spec["keys"]:
        if candidate in record.files:
            return candidate
    for candidate in available:
        if candidate.lower().endswith(spec["suffix"]):
            return candidate
    if key == "png":
        pngish = [c for c in available if "png" in c.lower()]
        if pngish:
            return pngish[0]
    if len(available) == 1:
        return available[0]
    raise ApiProblem(
        404, API_CODE_NOT_FOUND,
        f"资产 {record.asset_id} 没有 {key} 类 payload（可用 key：{available}）；"
        f"可以用 ?name=<payload key> 明确指定",
        stage="showcase.asset", details={"available": available,
                                         "whitelist": sorted(KEY_WHITELIST)})


@router.get("/showcase/asset/{asset_id}/{key}",
            summary="展示资产文件（白名单 key：glb/png/arrays/meta；校验存在性与 sha256）")
def get_showcase_asset(
    session: SessionDep,
    request: Request,
    asset_id: str,
    key: str,
    name: str | None = Query(None, description="在该资产已记录的 payload key 中精确指定"),
    download: bool = Query(False),
    verify: bool = Query(True),
) -> Response:
    if key not in KEY_WHITELIST:
        raise ApiProblem(
            400, "SHOWCASE_KEY_NOT_ALLOWED",
            f"未知展示 key {key!r}；白名单只允许 {sorted(KEY_WHITELIST)}",
            stage="showcase.asset",
            details={"whitelist": sorted(KEY_WHITELIST), "key": key},
        )
    locator = locator_for(request)
    store = locator.store()
    if store is None:
        raise ApiProblem(
            404, "SHOWCASE_NOT_GENERATED",
            "演示资产库不存在：先运行 " + GENERATOR_COMMAND,
            stage="showcase.asset",
            details={"manifest_path": _display_path(locator.manifest_path())},
        )
    try:
        record = store.get_asset(asset_id)
    except SynLabError as exc:
        raise from_synlab(exc) from exc
    file_name = _pick_payload_key(record, key, name)
    try:
        ref = resolve_file(store, asset_id, file_name, verify=verify)
    except ApiProblem:
        raise
    except SynLabError as exc:
        raise from_synlab(exc) from exc

    spec = KEY_WHITELIST[key]
    if key in TEXT_KEYS:
        body = ref.path.read_bytes()
        media = spec["media_type"]
    else:
        body = ref.path.read_bytes()
        media = spec["media_type"]
    headers = {
        "X-SynLab-Asset-Id": record.asset_id,
        "X-SynLab-Asset-Role": record.role,
        "X-SynLab-File-Key": file_name,
        "X-SynLab-File-Sha256": ref.sha256,
        "X-SynLab-Hash-Verified": str(ref.hash_verified),
        "X-SynLab-Unit": record.unit,
        "X-SynLab-Frame": record.frame,
        "X-SynLab-QA-Status": record.qa_status,
        "X-SynLab-Showcase-Key": key,
        "Cache-Control": "private, max-age=0, must-revalidate",
    }
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{record.asset_id}_{file_name}"'
    return Response(content=body, media_type=media, headers=headers)


__all__ = ["router", "ShowcaseLocator", "KEY_WHITELIST", "MANIFEST_NAME", "GENERATOR_COMMAND"]
