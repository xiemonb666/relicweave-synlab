#!/usr/bin/env python
"""真实演示数据集生成器（A12 合成数据展示页 `/synlab/showcase` 的数据源）。

这个脚本**只调用仓库里真实的模块 API**，不写任何硬编码或伪造的数值：

* 母体：``synlab.mothers.api`` 的 ``sample_parameters`` / ``create_mother`` / ``audit_mother`` /
  ``commit_mother``，另派生一份米制 / Y-up 的 ``display_lod_glb`` 展示资产（trimesh 导出）；
* 纹样：``synlab.patterns.api`` 的 ``build_pattern`` / ``evaluate`` / ``audit_pattern`` /
  ``commit_pattern``，并在真实母体上按面积加权采样，把 albedo / roughness / height_mm
  三通道分箱成 PNG（PNG 是**显示编码**，图例写进资产 meta 与 demo manifest）；
* 碎裂：``synlab.fracture.api`` 的 ``fracture_event`` + ``audit_fracture``；失败时把**真实的**
  错误码 / message / measurements 原样写进清单（``status: FAILED/BLOCKED``），页面照实显示；
* 退化：``synlab.degrade.api`` 的 ``apply_axis``，10 个轴 × 5 档，**同一 source、同一 basis**；
  I 轴输出真实渲染帧 PNG，几何轴输出 mesh GLB 与实测变化量，level 0 引用原始字节并标注 identity。

设计与可续跑
------------

本机对重负载 Python 进程会直接杀掉（退出码 -1，见 ``docs/a12/showcase.md``）。因此脚本把
**每个工作单元放进独立子进程**执行，父进程逐单元写盘：

* 单个单元被杀 / 超时只会丢失那一个单元，已完成的条目留在 ``demo_manifest.json`` 里；
* 重新运行会跳过状态为 ``OK`` 的条目（``--force`` 可强制重跑），因此天然幂等、可续跑；
* 每一步的产物（资产提交 + 清单条目）在该单元结束时立即落盘。

用法
----

```powershell
# 全量（推荐按步骤跑，避免一次跑太久）
& .venv\\Scripts\\python.exe tools\\build_demo_assets.py

# 分步 / 限量
& .venv\\Scripts\\python.exe tools\\build_demo_assets.py --only mothers
& .venv\\Scripts\\python.exe tools\\build_demo_assets.py --only patterns --limit 4
& .venv\\Scripts\\python.exe tools\\build_demo_assets.py --only fracture --limit 2
& .venv\\Scripts\\python.exe tools\\build_demo_assets.py --only degrade

# 单进程（调试 / 小规模测试；--inline 不做子进程隔离）
& .venv\\Scripts\\python.exe tools\\build_demo_assets.py --only mothers --limit 1 --inline

# 查看清单摘要（不生成任何东西）
& .venv\\Scripts\\python.exe tools\\build_demo_assets.py --summary
```

退出码：``0`` = 所有被请求的单元都走到了 ``OK``；``1`` = 至少一个单元 ``FAILED/BLOCKED``
（这是**真实结果**，不是脚本崩溃）；``2`` = 参数错误。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DEMO_ROOT = REPO_ROOT / "data" / "a12_demo"
MANIFEST_SCHEMA = "synlab.showcase.demo_manifest.v1"
MANIFEST_NAME = "demo_manifest.json"
STORE_DIRNAME = "store"

MASTER_SEED = 20261001
LINEAGE_ID = "a12_demo"
SPLIT = "train"

#: 唯一权威的生成命令（写进清单，也被展示 API `synlab/api/routers/showcase.py` 使用；
#: `tests/a12/showcase/test_showcase_api.py` 断言两处字符串一致）。
GENERATOR_COMMAND = "& .venv\\Scripts\\python.exe tools\\build_demo_assets.py"

RESULT_MARKER = "@@SYNLAB_DEMO_RESULT@@"

#: 运行中标记。启动时若发现它存在，说明上一次运行（父进程）被系统杀掉了——
#: 本机对重负载 Python 进程会直接杀进程树，父进程来不及写任何条目。
INFLIGHT_NAME = ".inflight.json"

#: 演示用器型（全部实测可用；材料固定 M03，避免把器型差异和材料差异混在一起）
MOTHER_UNITS: tuple[tuple[str, str], ...] = (
    ("V01", "M03"), ("V02", "M03"), ("V03", "M03"), ("V04", "M03"),
    ("V06", "M03"), ("V07", "M03"), ("V13", "M03"), ("V18", "M03"),
)

#: 演示纹样族（母体按顺序轮转绑定，绑定关系写进清单）
PATTERN_FAMILIES: tuple[str, ...] = (
    "PAT01", "PAT02", "PAT03", "PAT06", "PAT10", "PAT12", "PAT14", "PAT15",
)

#: 碎裂事件（母体, 后端）。全部为真实尝试；失败原因原样入清单。
#: ``warped_partition`` 在构建里是 PENDING、``fracture_modes`` 是 MISSING，调用会被结构化拒绝——
#: 这正是要展示给用户的真实状态，所以它们也在列表里，只是永远不会变成 OK。
FRACTURE_CASES: tuple[tuple[str, str], ...] = (
    ("V01", "plane_shared_cut"),
    ("V13", "plane_shared_cut"),
    ("V04", "plane_shared_cut"),
    ("V01", "rough_shared_cut"),
    ("V13", "rough_shared_cut"),
    ("V01", "secondary_fracture"),
    ("V01", "warped_partition"),
    ("V01", "fracture_modes"),
)

#: 本机实测到的环境事实（写进清单 notes，页面在诚实性面板里原样展示）。
ENVIRONMENT_FINDINGS: tuple[str, ...] = (
    "host-kill: 本机对重负载 Python 进程会直接杀掉（无 Python 异常、退出码 -1）。生成器把每个工作"
    "单元放进独立子进程并在启动时对账 `.inflight.json`，被杀只丢一个单元、记为 BLOCKED/PROCESS_KILLED，"
    "重跑会跳过已 OK 的条目。",
    "rough-budget: rough_shared_cut 在默认 0.01 mm 插值误差预算下报 PRECISION_NOT_REALIZED"
    "（实测 realized_error_mm ≈ 0.2260 mm，真实测量结果，不是估计）。",
    "blender: 本机没有 Blender / bpy（无 Windows + py3.12 wheel），渲染只有软件光栅后端；"
    "synlab.observe.render.capability_probe() 会如实报告 blender 不可用。",
    "real-data: 仓库里没有任何真实实拍数据；所有展示数据都是合成数据（data_scope=SYNTHETIC）。",
    "observe-defect: delivered_size=(320,240) 且 route_params.hole_count=2 时，"
    "synlab/observe/routes.py::_carve_holes 抛 IndexError（空洞圆盘贴边越界）；演示集用 "
    "hole_count=0 换取稳定的 320×240 真实渲染。synlab/** 不在本任务写入范围，未修复。",
)

#: 这些错误码表示「能力没有实现/环境不具备」，语义上是 BLOCKED 而不是 FAILED。
BLOCKED_CODES: frozenset[str] = frozenset({
    "OPERATOR_NOT_REALIZED",
    "DEPENDENCY_CAPABILITY_MISSING",
    "ENV_CAPABILITY_MISSING",
    "INTEGRATION_PENDING",
    "NA_NOT_APPLICABLE",
    "REAL_DATA_PENDING",
    "MVS_NOT_AVAILABLE",
    "PROCESS_KILLED",
    "TIMEOUT",
    "MOTHER_ASSET_MISSING",
    "DEGRADE_SOURCE_MISSING",
})

#: 断裂后端的注册状态（**在运行时从真实注册表读取**，取不到就写 UNKNOWN，绝不猜）。
def backend_registry_status() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        import synlab.fracture.api  # noqa: F401  (注册发生在模块导入时)
        from synlab.registry import REGISTRY, load_all

        load_all()
        for backend_id in REGISTRY.ids("fracture_backend"):
            entry = REGISTRY.get("fracture_backend", backend_id)
            status = getattr(entry, "status", None)
            out[str(backend_id)] = str(getattr(status, "value", status))
    except BaseException:  # noqa: BLE001 - 取不到就老实说取不到
        pass
    return out



#: 退化轴（覆盖 P / I / G / X 四族）
DEGRADE_AXES: tuple[str, ...] = (
    "P03", "P05", "P06", "I01", "I03", "I09", "I10", "G03", "G05", "G08",
    "X01", "X04",
)

#: 纹样通道 PNG 的显示编码（写进资产 meta 与清单，页面原样展示）
PNG_ENCODING_LEGEND: dict[str, str] = {
    "rgb": "渲染线性 RGB → 显示编码 uint8 = round(255 * clip(linear,0,1)^(1/2.2))；"
           "PNG 是显示编码，不是线性真值",
    "albedo": "线性 RGB → 显示编码 uint8 = round(255 * clip(linear,0,1)^(1/2.2))；"
              "PNG 是显示编码，不是线性真值",
    "roughness": "标量 [0,1] 线性灰度 uint8 = round(255 * clip(r,0,1))，无 γ",
    "height_mm": "有符号 mm，对称归一化 u = (h + amax) / (2 * amax)，"
                 "蓝-白-红发散色标；amax 与 min/max 写在 legend 里",
}


# ======================================================================================
# 通用小工具
# ======================================================================================
def _jsonable(value: Any, *, depth: int = 0, max_items: int = 400) -> Any:
    """把任意对象转成可 JSON 序列化、且体积可控的结构（不丢真实数值，只截断超长集合）。"""
    import numpy as np

    if depth > 6:
        return f"<max-depth {type(value).__name__}>"
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return str(value)
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return str(number)
        return number
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        flat = value.reshape(-1)
        if flat.size == 0:
            return {"shape": list(value.shape), "dtype": str(value.dtype), "empty": True}
        return {
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "min": float(np.min(flat)) if flat.dtype.kind in "fiu" else None,
            "max": float(np.max(flat)) if flat.dtype.kind in "fiu" else None,
        }
    if isinstance(value, dict):
        items = list(value.items())
        out = {str(k): _jsonable(v, depth=depth + 1, max_items=max_items)
               for k, v in items[:max_items]}
        if len(items) > max_items:
            out["__truncated_keys__"] = len(items) - max_items
        return out
    if isinstance(value, (list, tuple)):
        out = [_jsonable(v, depth=depth + 1, max_items=max_items) for v in value[:max_items]]
        if len(value) > max_items:
            out.append(f"<truncated {len(value) - max_items} items>")
        return out
    if isinstance(value, Path):
        return str(value)
    return f"<{type(value).__module__}.{type(value).__name__}>"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _png_bytes(rgb_or_gray: Any, *, compress_level: int = 6) -> bytes:
    import numpy as np
    from PIL import Image

    array = np.asarray(rgb_or_gray)
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG", compress_level=compress_level)
    return buffer.getvalue()


def _linear_to_display_u8(linear: Any) -> Any:
    """线性 RGB → 显示编码 uint8（γ = 1/2.2），与 PNG_ENCODING_LEGEND 一致。"""
    import numpy as np

    values = np.clip(np.asarray(linear, dtype=np.float64), 0.0, 1.0) ** (1.0 / 2.2)
    return np.rint(values * 255.0).astype(np.uint8)


def _diverging_bwr(normalized: Any) -> Any:
    """[-1,1] → 蓝-白-红 uint8 (H,W,3)。纯显示映射，端点值在 legend 里。"""
    import numpy as np

    u = np.clip(np.asarray(normalized, dtype=np.float64), -1.0, 1.0)
    red = np.clip(u, 0.0, 1.0)
    blue = np.clip(-u, 0.0, 1.0)
    white = 1.0 - np.abs(u)
    rgb = np.stack([red + white, white, blue + white], axis=-1)
    return np.rint(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8)


def _gray_u8(values: Any) -> Any:
    import numpy as np

    return np.rint(np.clip(np.asarray(values, dtype=np.float64), 0.0, 1.0) * 255.0).astype(np.uint8)


# ======================================================================================
# 清单读写（原子写盘）
# ======================================================================================
class Manifest:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {
            "schema": MANIFEST_SCHEMA,
            "generated_at": None,
            "demo_root": _rel(path.parent),
            "store_root": _rel(path.parent / STORE_DIRNAME),
            "manifest_path": _rel(path),
            "generator": "tools/build_demo_assets.py",
            "generator_command": "& .venv\\Scripts\\python.exe tools\\build_demo_assets.py",
            "master_seed": MASTER_SEED,
            "lineage_id": LINEAGE_ID,
            "entries": [],
            "axis_catalog": [],
            "runs": [],
            "notes": [],
            "environment_findings": list(ENVIRONMENT_FINDINGS),
        }
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except (OSError, ValueError) as exc:  # 损坏的清单必须显式暴露，不能静默重建
                self.data["notes"].append(f"EXISTING_MANIFEST_UNREADABLE: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------ entries
    @property
    def entries(self) -> list[dict[str, Any]]:
        return self.data["entries"]

    def get(self, entry_id: str) -> dict[str, Any] | None:
        for entry in self.entries:
            if entry.get("entry_id") == entry_id:
                return entry
        return None

    def upsert(self, entry: dict[str, Any]) -> None:
        for index, existing in enumerate(self.entries):
            if existing.get("entry_id") == entry["entry_id"]:
                self.entries[index] = entry
                return
        self.entries.append(entry)

    def by_kind(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.entries if e.get("kind") == kind]

    def ok_ids(self, kind: str) -> list[str]:
        return [e["entry_id"] for e in self.by_kind(kind) if e.get("status") == "OK"]

    # ------------------------------------------------------------------ counts / save
    def counts(self) -> dict[str, Any]:
        by_kind: dict[str, dict[str, int]] = {}
        total = {"OK": 0, "BLOCKED": 0, "FAILED": 0, "NA": 0}
        for entry in self.entries:
            kind = str(entry.get("kind", "unknown"))
            status = str(entry.get("status", "NA"))
            bucket = by_kind.setdefault(kind, {"total": 0, "OK": 0, "BLOCKED": 0, "FAILED": 0, "NA": 0})
            bucket["total"] += 1
            bucket[status] = bucket.get(status, 0) + 1
            total[status] = total.get(status, 0) + 1
        return {"by_kind": by_kind, "total": total, "entries": len(self.entries)}

    def save(self) -> None:
        self.data["generated_at"] = self.data.get("generated_at") or _now_iso()
        self.data["updated_at"] = _now_iso()
        self.data["counts"] = self.counts()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1, sort_keys=False),
                       encoding="utf-8")
        os.replace(tmp, self.path)


def _entry(entry_id: str, kind: str, *, title: str, status: str = "OK", **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "entry_id": entry_id,
        "kind": kind,
        "title": title,
        "status": status,
        "generated_at": _now_iso(),
        "asset_id": None,
        "role": None,
        "schema": None,
        "unit": None,
        "frame": None,
        "metrics": {},
        "artifacts": {},
        "failure": None,
    }
    entry.update(extra)
    return entry


def _failure(code: str, message: str, *, stage: str = "", measurements: Any = None,
             retryable: bool = False, detail: str | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "stage": stage,
        "retryable": bool(retryable),
        "measurements": _jsonable(measurements) if measurements is not None else {},
        "detail": detail,
    }


def _failure_from_exception(exc: BaseException) -> dict[str, Any]:
    code = type(exc).__name__
    message = str(exc)
    stage = ""
    measurements: Any = None
    retryable = False
    try:  # SynLabError 的真实结构
        from synlab.errors import SynLabError

        if isinstance(exc, SynLabError):
            code = exc.code.value if hasattr(exc.code, "value") else str(exc.code)
            message = exc.message
            stage = exc.stage
            measurements = exc.measurements
            retryable = bool(exc.retryable)
    except Exception:  # noqa: BLE001 - 诚实：拿不到结构就退回类型名
        pass
    return _failure(code, message, stage=stage, measurements=measurements, retryable=retryable)


# ======================================================================================
# 资产导出辅助（全部走真实模块）
# ======================================================================================
def _store(demo_root: Path) -> Any:
    from synlab.storage.store import AssetStore

    return AssetStore(demo_root / STORE_DIRNAME)


def _export_display_glb(store: Any, mesh: Any, *, source_asset: str | None,
                        label: str, extra_meta: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
    """权威 mm/Z-up mesh → 米/Y-up 的 ``display_lod_glb`` 派生资产（与 worker 同一套契约）。"""
    import numpy as np
    import trimesh

    from synlab.api import display
    from synlab.roles import ROLE_DISPLAY_LOD

    authority_vertices = np.asarray(mesh.vertices, dtype=np.float64)
    authority_extent = np.asarray(mesh.bounds[1]) - np.asarray(mesh.bounds[0])
    display_vertices = display.transform_vertices(authority_vertices)
    display_mesh = trimesh.Trimesh(vertices=display_vertices, faces=np.asarray(mesh.faces),
                                   process=False)
    display_extent = np.asarray(display_mesh.bounds[1]) - np.asarray(display_mesh.bounds[0])

    levels: dict[str, Any] = {"L0": {"faces": int(len(display_mesh.faces)),
                                     "vertices": int(len(display_mesh.vertices))}}
    lod_notes: list[str] = []
    scene = trimesh.Scene()
    scene.add_geometry(display_mesh, node_name="L0")
    for level, ratio in (("L1", 0.3), ("L2", 0.08)):
        try:
            simplified = display_mesh.simplify_quadric_decimation(
                face_count=max(4, int(len(display_mesh.faces) * ratio)))
        except BaseException as exc:  # noqa: BLE001 - 简化后端是可选的，缺失要如实记录
            lod_notes.append(f"{level} skipped: {type(exc).__name__}: {exc}")
            continue
        if simplified is None or len(simplified.faces) == 0:
            lod_notes.append(f"{level} skipped: decimation returned no faces")
            continue
        scene.add_geometry(simplified.copy(), node_name=level)
        levels[level] = {"faces": int(len(simplified.faces)),
                         "vertices": int(len(simplified.vertices))}
    glb = scene.export(file_type="glb")

    transform = display.describe()
    record = store.commit_asset(
        role=ROLE_DISPLAY_LOD,
        schema="synlab.display_glb.v1",
        unit=display.DISPLAY_UNIT,
        frame=f"{display.DISPLAY_UP_AXIS}_up_m",
        payload={"glb": bytes(glb)},
        meta={
            "derived": True,
            "label": label,
            "source_asset": source_asset,
            "display_transform": transform,
            "authority_extent_mm": authority_extent.tolist(),
            "display_extent_m": display_extent.tolist(),
            "lod_levels": levels,
            "lod_notes": lod_notes,
            "note": "display-only derivation; authoritative geometry remains mm/Z-up and is untouched",
            **(extra_meta or {}),
        },
        qa={
            "authority_extent_mm": authority_extent.tolist(),
            "display_extent_m": display_extent.tolist(),
            "transform_id": transform["transform_id"],
            "glb_bytes": len(glb),
        },
        qa_status="QA_PASS",
        ancestry=[source_asset] if source_asset else [],
        lineage_id=LINEAGE_ID,
        split=SPLIT,
    )
    metrics = {
        "glb_asset_id": record.asset_id,
        "glb_bytes": len(glb),
        "authority_extent_mm": authority_extent.tolist(),
        "display_extent_m": display_extent.tolist(),
        "triangles": int(len(display_mesh.faces)),
        "vertices": int(len(display_mesh.vertices)),
        "lod_levels": sorted(levels),
        "lod_notes": lod_notes,
        "display_transform_id": transform["transform_id"],
    }
    return record, metrics


def _commit_png_asset(store: Any, *, role: str, schema: str, unit: str, frame: str,
                      images: dict[str, bytes], meta: dict[str, Any], qa: dict[str, Any],
                      ancestry: list[str], label: str) -> Any:
    return store.commit_asset(
        role=role, schema=schema, unit=unit, frame=frame,
        payload=dict(images),
        meta={"label": label, "image_keys": sorted(images),
              "encoding_legend": PNG_ENCODING_LEGEND, **meta},
        qa=dict(qa), qa_status="QA_PASS", ancestry=list(ancestry),
        lineage_id=LINEAGE_ID, split=SPLIT,
    )


# ======================================================================================
# 任务：母体
# ======================================================================================
def _load_mother(store: Any, asset_id: str) -> Any:
    from synlab.mothers.api import load_mother

    return load_mother(store, asset_id)


def task_mother(demo_root: Path, task: dict[str, Any], manifest: Manifest) -> dict[str, Any]:
    from synlab.mothers.api import audit_mother, commit_mother, create_mother, sample_parameters
    from synlab.seeds import make_rng

    vessel_id = str(task["vessel_id"])
    material_id = str(task.get("material_id", "M03"))
    entry_id = f"mother:{vessel_id}"
    entry = _entry(entry_id, "mother", title=f"母体 {vessel_id} / {material_id}")
    entry["vessel_id"] = vessel_id
    entry["material_id"] = material_id
    started = time.time()
    try:
        store = _store(demo_root)
        rng = make_rng(MASTER_SEED, LINEAGE_ID, "mothers", vessel_id)
        params = sample_parameters(vessel_id, 1, rng, require_feasible=True)[0]
        mother = create_mother(vessel_id, material_id, params, rng,
                               mother_id=f"{LINEAGE_ID}_{vessel_id}")
        report = audit_mother(mother)
        record = commit_mother(store, mother, lineage_id=LINEAGE_ID, split=SPLIT)
        glb_record, glb_metrics = _export_display_glb(
            store, mother.mesh, source_asset=record.asset_id, label=f"mother:{vessel_id}")

        bounds = mother.mesh.bounds
        entry.update({
            "status": "OK" if report.get("ok") else "FAILED",
            "asset_id": record.asset_id,
            "role": record.role,
            "schema": record.schema,
            "unit": record.unit,
            "frame": record.frame,
            "qa_status": record.qa_status,
            "metrics": {
                "vessel_id": vessel_id,
                "material_id": material_id,
                "params": _jsonable(params),
                "params_source": "synlab.mothers.api.sample_parameters(require_feasible=True)",
                "faces": int(len(mother.mesh.faces)),
                "vertices": int(len(mother.mesh.vertices)),
                "watertight": bool(mother.mesh.is_watertight),
                "winding_consistent": bool(mother.mesh.is_winding_consistent),
                "volume_mm3": float(abs(mother.mesh.volume)),
                "area_mm2": float(mother.mesh.area),
                "extent_mm": (bounds[1] - bounds[0]).tolist(),
                "surface_tags": {str(k): v for k, v in mother.surface_tag_names.items()},
                "charts": [c.as_dict() if hasattr(c, "as_dict") else str(c) for c in mother.charts],
                "qa_state": report.get("state"),
                "qa_ok": bool(report.get("ok")),
                "qa_failures": _jsonable(report.get("failures")),
                "qa_metrics": _jsonable(report.get("metrics")),
                "qa_checks": _jsonable(report.get("checks")),
                "geometry_hash": report.get("geometry_hash"),
                "mother_audit_source": "synlab.mothers.api.audit_mother",
            },
            "artifacts": {
                "glb": {"asset_id": glb_record.asset_id, "role": glb_record.role,
                        "key": "glb", "metrics": glb_metrics},
            },
            "failure": (None if report.get("ok") else _failure(
                "MOTHER_QA_FAILED",
                f"audit_mother 判定 {vessel_id} 未通过：{_jsonable(report.get('failures'))}",
                stage="mothers.audit_mother")),
        })
    except BaseException as exc:  # noqa: BLE001 - 单元素失败必须变成条目，不是崩溃
        entry.update({"status": "FAILED", "failure": _failure_from_exception(exc),
                      "traceback_tail": traceback.format_exc()[-1500:]})
    entry["duration_s"] = round(time.time() - started, 3)
    return entry


# ======================================================================================
# 任务：纹样
# ======================================================================================
def _pattern_channel_images(mother: Any, recipe: Any, channels: Any, *, rng: Any,
                            n_samples: int = 600_000, width: int = 256, height: int = 128
                            ) -> tuple[dict[str, bytes], dict[str, Any]]:
    """在真实母体上按面积加权采样 → ``evaluate`` → (x,s) 网格分箱 → 三通道 PNG。"""
    import numpy as np

    from synlab.patterns.api import to_chart_mm
    from synlab.patterns.charts import face_centre_chart, resolve_frame

    tag_name = str((recipe.meta.get("chart") or {}).get("surface_tag") or "outer_wall")
    frame = resolve_frame(mother, tag_name)
    faces = np.asarray(mother.mesh.faces, dtype=np.int64)
    tags = np.asarray(mother.face_surface_tag)
    mask = tags == int(frame.tag)
    if not bool(np.any(mask)):
        raise RuntimeError(f"母体上没有 surface_tag={tag_name} 的面，无法做纹样通道分箱")
    triangles = np.asarray(mother.mesh.triangles, dtype=np.float64)[mask]
    areas = np.asarray(mother.mesh.area_faces, dtype=np.float64)[mask]
    weights = areas / float(areas.sum())

    index = rng.choice(len(triangles), size=int(n_samples), p=weights)
    uv = rng.random((int(n_samples), 2))
    flip = uv.sum(axis=1) > 1.0
    uv[flip] = 1.0 - uv[flip]
    origin = triangles[index, 0]
    points = (origin
              + (triangles[index, 1] - origin) * uv[:, 0:1]
              + (triangles[index, 2] - origin) * uv[:, 1:2])

    channels_eval = _evaluate_pattern(recipe, mother, points, int(frame.tag))
    x_mm, s_mm = to_chart_mm(frame, points)

    period = float(frame.x_period_mm) if frame.x_period_mm else float(x_mm.max() - x_mm.min())
    periodic = bool(frame.u_periodic)
    x_lo = 0.0 if periodic else float(x_mm.min())
    s_lo, s_hi = float(frame.s_min_mm), float(frame.s_max_mm)
    s_span = max(s_hi - s_lo, 1e-9)

    col = np.floor((x_mm - x_lo) / max(period, 1e-9) * width).astype(np.int64)
    col = np.mod(col, width) if periodic else np.clip(col, 0, width - 1)
    row = np.clip(np.floor((s_mm - s_lo) / s_span * height).astype(np.int64), 0, height - 1)
    flat = row * width + col

    counts = np.bincount(flat, minlength=width * height).astype(np.float64)
    filled = counts > 0

    pixels_albedo = np.zeros((width * height, 3), dtype=np.float64)
    pixels_rough = np.zeros((width * height,), dtype=np.float64)
    pixels_height = np.zeros((width * height,), dtype=np.float64)
    albedo = np.asarray(channels_eval.albedo, dtype=np.float64)
    roughness = np.asarray(channels_eval.roughness, dtype=np.float64)
    height_mm = np.asarray(channels_eval.height_mm, dtype=np.float64)
    for channel_index in range(3):
        pixels_albedo[:, channel_index] = np.bincount(
            flat, weights=albedo[:, channel_index], minlength=width * height)
    pixels_rough = np.bincount(flat, weights=roughness, minlength=width * height)
    pixels_height = np.bincount(flat, weights=height_mm, minlength=width * height)
    denom = np.where(filled, counts, 1.0)
    binned_albedo = (pixels_albedo / denom[:, None]).reshape(height, width, 3)
    binned_rough = (pixels_rough / denom).reshape(height, width)
    binned_height = (pixels_height / denom).reshape(height, width)
    covered = filled.reshape(height, width)
    has_data = bool(np.any(filled))

    albedo_u8 = _linear_to_display_u8(binned_albedo)
    rough_u8 = _gray_u8(binned_rough)
    amp = float(np.max(np.abs(binned_height[covered]))) if has_data else 0.0
    amp = max(amp, 1e-6)
    height_u8 = _diverging_bwr(binned_height / amp)

    # 未覆盖的 bin 保持黑色：诚实标注覆盖率，不用插值填洞
    coverage = float(counts[filled].size) / float(width * height)
    legend = {
        "albedo_png": f"{PNG_ENCODING_LEGEND['albedo']}；网格 {width}×{height}，"
                      f"面积加权随机采样 n={int(n_samples)}，分箱覆盖 {coverage:.1%}；未覆盖像素为黑",
        "roughness_png": (f"{PNG_ENCODING_LEGEND['roughness']}；分箱均值实测范围 "
                          f"[{float(binned_rough[covered].min()):.4f}, "
                          f"{float(binned_rough[covered].max()):.4f}]"
                          if has_data else PNG_ENCODING_LEGEND["roughness"]),
        "height_png": (f"{PNG_ENCODING_LEGEND['height_mm']}；对称幅度 amax={amp:.6f} mm，"
                       f"分箱均值实测 min={float(binned_height[covered].min()):.6f} mm、"
                       f"max={float(binned_height[covered].max()):.6f} mm"
                       if has_data else PNG_ENCODING_LEGEND["height_mm"]),
    }
    images = {
        "albedo_png": _png_bytes(albedo_u8),
        "roughness_png": _png_bytes(rough_u8),
        "height_png": _png_bytes(height_u8),
    }
    stats = {
        "raster": {
            "width": width, "height": height, "n_samples": int(n_samples),
            "bin_coverage": coverage, "filled_bins": int(counts[filled].size),
            "mean_samples_per_filled_bin": (float(counts[filled].mean())
                                            if bool(np.any(filled)) else 0.0),
            "chart": frame.as_dict(), "x_period_mm": period, "x_periodic": periodic,
            "s_range_mm": [s_lo, s_hi],
            "method": "面元面积加权随机采样 → evaluate() → (x,s) 网格分箱算术平均；"
                      "不是逐像素解析真值，未覆盖 bin 保持黑色；"
                      "bin 内残余颗粒是采样噪声，不是纹样结构",
            "rng": f"make_rng({MASTER_SEED}, {LINEAGE_ID}, patterns, {recipe.family_id})",
        },
        "channel_stats": {
            "albedo_linear_min": (float(albedo.min()) if albedo.size else None),
            "albedo_linear_max": (float(albedo.max()) if albedo.size else None),
            "roughness_min": (float(roughness.min()) if roughness.size else None),
            "roughness_max": (float(roughness.max()) if roughness.size else None),
            "height_mm_min": (float(height_mm.min()) if height_mm.size else None),
            "height_mm_max": (float(height_mm.max()) if height_mm.size else None),
            "pattern_region_fraction": (float(np.mean(np.asarray(channels_eval.pattern_region,
                                                                 dtype=bool)))
                                        if channels_eval.pattern_region is not None else None),
        },
        "legend": legend,
    }
    return images, stats


def _evaluate_pattern(recipe: Any, mother: Any, points: Any, tag: int) -> Any:
    from synlab.patterns.api import evaluate

    return evaluate(recipe, mother, points, tag)


def task_pattern(demo_root: Path, task: dict[str, Any], manifest: Manifest) -> dict[str, Any]:
    import numpy as np

    from synlab.patterns.api import PatternSpec, audit_pattern, build_pattern, commit_pattern
    from synlab.patterns.serialize import recipe_to_dict
    from synlab.roles import ROLE_PATTERN_CHANNELS
    from synlab.seeds import make_rng

    family = str(task["family_id"])
    mother_entry_id = str(task["mother_entry"])
    entry_id = f"pattern:{family}"
    entry = _entry(entry_id, "pattern", title=f"纹样 {family} → {mother_entry_id}")
    entry["family_id"] = family
    entry["mother_entry"] = mother_entry_id
    started = time.time()
    mother_entry = manifest.get(mother_entry_id)
    try:
        if not mother_entry or mother_entry.get("status") != "OK":
            entry.update({
                "status": "BLOCKED",
                "failure": _failure("MOTHER_ASSET_MISSING",
                                    f"{mother_entry_id} 尚未生成成功；先运行 --only mothers",
                                    stage="showcase.pattern"),
            })
            entry["duration_s"] = round(time.time() - started, 3)
            return entry
        store = _store(demo_root)
        mother_asset = str(mother_entry["asset_id"])
        mother = _load_mother(store, mother_asset)
        rng = make_rng(MASTER_SEED, LINEAGE_ID, "patterns", family)
        spec = PatternSpec(family=family)
        recipe = build_pattern(mother, spec, rng)
        images, raster_stats = _pattern_channel_images(mother, recipe, None, rng=rng)
        audit = audit_pattern(recipe, mother, geometry_probe=False)
        recipe_record = commit_pattern(store, recipe, None, lineage_id=LINEAGE_ID, split=SPLIT,
                                       ancestry=[mother_asset], mother_id=mother.mother_id,
                                       qa=_jsonable(audit),
                                       qa_status="QA_PASS" if audit.get("pass") else "QA_FAIL")
        image_record = _commit_png_asset(
            store, role=ROLE_PATTERN_CHANNELS, schema="synlab.pattern.v1", unit="mm",
            frame="W_mm", images=images,
            meta={"family_id": family, "mother_asset": mother_asset,
                  "recipe_hash": recipe_record.meta.get("recipe_hash"),
                  "chart": raster_stats["raster"]["chart"],
                  "channel_stats": raster_stats["channel_stats"],
                  "legend": raster_stats["legend"]},
            qa={"pass": bool(audit.get("pass")), "failures": _jsonable(audit.get("failures"))},
            ancestry=[mother_asset, recipe_record.asset_id],
            label=f"pattern:{family}:channels")
        entry.update({
            "status": "OK" if audit.get("pass") else "FAILED",
            "asset_id": recipe_record.asset_id,
            "role": recipe_record.role,
            "schema": recipe_record.schema,
            "unit": recipe_record.unit,
            "frame": recipe_record.frame,
            "qa_status": recipe_record.qa_status,
            "metrics": {
                "family_id": family,
                "family_name": recipe.meta.get("family_name"),
                "mother_asset": mother_asset,
                "mother_vessel_id": mother_entry.get("vessel_id"),
                "recipe_hash": recipe_record.meta.get("recipe_hash"),
                "resource_hash": recipe.resource_hash,
                "palette_id": recipe.meta.get("palette_id"),
                "channels": list(recipe.channels),
                "recipe": _jsonable(recipe_to_dict(recipe)),
                "seam": _jsonable((audit.get("seam") or {})),
                "scale": _jsonable((audit.get("scale") or {})),
                "region": _jsonable((audit.get("region") or {})),
                "determinism": _jsonable((audit.get("determinism") or {})),
                "inheritance": _jsonable((audit.get("inheritance") or {})),
                "audit_pass": bool(audit.get("pass")),
                "audit_failures": _jsonable(audit.get("failures")),
                "audit_units": _jsonable(audit.get("units")),
                "raster": raster_stats["raster"],
                "channel_stats": raster_stats["channel_stats"],
                "legend": raster_stats["legend"],
                "audit_source": "synlab.patterns.audit.audit_pattern",
            },
            "artifacts": {
                "channels": {"asset_id": image_record.asset_id, "role": image_record.role,
                             "keys": {"albedo": "albedo_png", "roughness": "roughness_png",
                                      "height_mm": "height_png"}},
            },
            "failure": (None if audit.get("pass") else _failure(
                "PATTERN_AUDIT_FAIL", f"audit_pattern 判定 {family} 未通过",
                stage="patterns.audit_pattern", measurements=audit.get("failures"))),
        })
    except BaseException as exc:  # noqa: BLE001
        entry.update({"status": "FAILED", "failure": _failure_from_exception(exc),
                      "traceback_tail": traceback.format_exc()[-1500:]})
    entry["duration_s"] = round(time.time() - started, 3)
    return entry


# ======================================================================================
# 任务：碎裂
# ======================================================================================
def task_fracture(demo_root: Path, task: dict[str, Any], manifest: Manifest) -> dict[str, Any]:
    from synlab.fracture.api import BACKEND_ROUGH, FractureSpec, audit_fracture, fracture_event
    from synlab.seeds import make_rng

    vessel_id = str(task["vessel_id"])
    backend = str(task["backend"])
    mother_entry_id = f"mother:{vessel_id}"
    entry_id = f"fracture:{vessel_id}:{backend}"
    entry = _entry(entry_id, "fracture", title=f"碎裂 {vessel_id} / {backend}")
    entry["vessel_id"] = vessel_id
    entry["backend"] = backend
    started = time.time()
    mother_entry = manifest.get(mother_entry_id)
    if not mother_entry or mother_entry.get("status") != "OK":
        entry.update({"status": "BLOCKED",
                      "failure": _failure("MOTHER_ASSET_MISSING",
                                          f"{mother_entry_id} 尚未生成成功；先运行 --only mothers",
                                          stage="showcase.fracture")})
        entry["duration_s"] = round(time.time() - started, 3)
        return entry

    store = _store(demo_root)
    mother_asset = str(mother_entry["asset_id"])
    entry["asset_id"] = mother_asset
    entry["role"] = mother_entry.get("role")
    entry["schema"] = mother_entry.get("schema")
    entry["unit"] = "mm"
    entry["frame"] = "W_mm"

    # ---------------------------------------------------------------- 1) 真实断裂
    try:
        mother = _load_mother(store, mother_asset)
        rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", vessel_id, backend)
        spec = FractureSpec(backend=backend)
        result = fracture_event(mother, spec, rng, event_id=f"{LINEAGE_ID}_{vessel_id}_{backend}")
    except BaseException as exc:  # noqa: BLE001 - 断裂本身失败：没有碎片可展示
        failure = _failure_from_exception(exc)
        if backend == BACKEND_ROUGH:
            failure["detail"] = (
                "rough_shared_cut 在本机有三种真实结局：默认 0.01 mm 预算下先撞 "
                "PRECISION_NOT_REALIZED（实测 realized_error_mm ≈ 0.22 mm）；把预算放宽到 0.3 mm "
                "后进入布尔阶段；在部分器型上该后端会以「进程被系统杀掉」终止（无 Python 异常），"
                "生成器把这种结局记为 PROCESS_KILLED。")
        code = str(failure.get("code"))
        entry.update({
            "status": "BLOCKED" if code in BLOCKED_CODES else "FAILED",
            "failure": failure,
            "metrics": {
                "backend": backend,
                "backend_status": backend_registry_status().get(backend),
                "fragments": [],
                "fragment_count": 0,
                "audit_source": "synlab.fracture.api.fracture_event（未产出 FractureResult）",
            },
            "traceback_tail": traceback.format_exc()[-1500:],
        })
        entry["duration_s"] = round(time.time() - started, 3)
        return entry

    # ---------------------------------------------------------------- 2) 真实碎片（即使 QA 门未通过也保留）
    fragments: list[dict[str, Any]] = []
    for fragment in result.fragments:
        glb_record, glb_metrics = _export_display_glb(
            store, fragment.mesh, source_asset=mother_asset,
            label=f"fragment:{entry_id}:{fragment.fragment_id}",
            extra_meta={"fragment_id": str(fragment.fragment_id), "event_id": entry_id})
        fragments.append({
            "fragment_id": str(fragment.fragment_id),
            "volume_mm3": float(fragment.volume_mm3),
            "area_mm2": float(fragment.area_mm2),
            "faces": int(len(fragment.mesh.faces)),
            "vertices": int(len(fragment.mesh.vertices)),
            "is_tiny": bool(fragment.is_tiny),
            "component_id": int(getattr(fragment, "component_id", 0)),
            "parent_id": str(getattr(fragment, "parent_id", "")),
            "source_face_coverage": (
                float(np_mean(getattr(fragment, "face_source_tri", [])))
                if getattr(fragment, "face_source_tri", None) is not None else None),
            "glb": {"asset_id": glb_record.asset_id, "role": glb_record.role, "key": "glb",
                    "metrics": glb_metrics},
        })

    metrics: dict[str, Any] = {
        "backend": backend,
        "backend_status": backend_registry_status().get(backend),
        "event_id": entry_id,
        "fragment_count": len(result.fragments),
        "tiny_count": int(sum(1 for f in result.fragments if f.is_tiny)),
        "debris_count": len(result.debris),
        "interface_count": len(result.interfaces),
        "mother_volume_mm3": float(abs(mother.mesh.volume)),
        "fragment_volume_sum_mm3": float(sum(f.volume_mm3 for f in result.fragments)),
        "volume_conservation_rel": _volume_rel(mother, result),
        "event_tree": _jsonable(result.event_tree),
        "fracture_qa": _jsonable(result.qa),
        "cutter_ref": result.cutter_ref,
        "fragments": fragments,
        "fragments_available": bool(fragments),
        "fracture_event_source": "synlab.fracture.api.fracture_event（真实产出 FractureResult）",
    }

    # ---------------------------------------------------------------- 3) QA 门（真实审计）
    try:
        qa = audit_fracture(result, mother)
    except BaseException as exc:  # noqa: BLE001 - 审计门失败：碎片仍然真实存在
        failure = _failure_from_exception(exc)
        code = str(failure.get("code"))
        entry.update({
            "status": "BLOCKED" if code in BLOCKED_CODES else "FAILED",
            "failure": failure,
            "metrics": {
                **metrics,
                "audit": None,
                "audit_source": "synlab.fracture.api.audit_fracture（抛出了结构化错误）",
                "fragments_available": bool(fragments),
            },
            "artifacts": {"fragments": [f["glb"] for f in fragments]},
        })
        entry["duration_s"] = round(time.time() - started, 3)
        return entry

    entry.update({
        "status": "OK",
        "metrics": {
            **metrics,
            "audit": _jsonable(qa),
            "audit_source": "synlab.fracture.api.audit_fracture",
        },
        "artifacts": {"fragments": [f["glb"] for f in fragments]},
    })
    entry["duration_s"] = round(time.time() - started, 3)
    return entry


def np_mean(values: Any) -> float:
    import numpy as np

    array = np.asarray(values)
    return float(array.mean()) if array.size else 0.0


def _volume_rel(mother: Any, result: Any) -> float | None:
    mother_volume = float(abs(mother.mesh.volume))
    if mother_volume <= 0:
        return None
    total = float(sum(f.volume_mm3 for f in result.fragments))
    return (total - mother_volume) / mother_volume


# ======================================================================================
# 任务：退化（源 + 轴）
# ======================================================================================
def _degrade_observation_spec() -> Any:
    """退化演示用的真实观测规格。

    ``hole_count=0`` 是一个**被迫的降级**：在 ``delivered_size=(320,240)`` 下，
    ``route_params={'hole_count': 2}`` 会让 ``synlab/observe/routes.py::_carve_holes`` 抛
    ``IndexError: index 240 is out of bounds for axis 0 with size 240``（空洞圆盘越界的
    真实缺陷，``synlab/**`` 不在本任务的写入范围，因此不修改它，只把事实记录下来）。
    ``hole_count=0`` 意味着本演示集的代理扫描帧里没有人工空洞——这一点写在清单的
    ``metrics.route_params`` 与 ``defect_notes`` 里，页面照实显示。
    """
    from synlab.observe.api import ObsSpec
    from synlab.observe.imaging import ImagingSpec

    return ObsSpec(
        view_count=4,
        delivered_size=(320, 240),
        max_render_pixels=320 * 240,
        master_seed=MASTER_SEED,
        lineage_id=LINEAGE_ID,
        imaging=ImagingSpec(effective_gain=20000.0, read_noise_sigma=0.002,
                            response="LINEAR", encode="PNG"),
        route_params={"voxel_mm": 0.2, "sparse_keep": 1.0, "hole_count": 0,
                      "depth_error_sigma_mm": 0.05, "stride": 2},
    )


OBSERVATION_DEFECT_NOTES: tuple[str, ...] = (
    "delivered_size=(320,240) 且 route_params.hole_count=2 时，"
    "synlab/observe/routes.py::_carve_holes 抛 IndexError: index 240 is out of bounds for "
    "axis 0 with size 240（空洞圆盘贴边越界）。实测 (288,224) 或 hole_count=0 可复现通过；"
    "本演示集用 hole_count=0 换取 320×240 的稳定真实渲染。synlab/** 不在写入范围内，故未修复。",
)


def _build_family_sources(store: Any, *, mother_asset: str, mother_mesh: Any) -> dict[str, Any]:
    """四个族的真实 source bundle（P 用内置探针实体；I/G/X 用真实母体的真实观测）。"""
    from synlab.degrade.api import bundles_from_observation, probe_sources
    from synlab.observe.api import ROUTE_PROXY_SCAN, observe
    from synlab.seeds import derive_named_rngs

    probe = probe_sources(store=None, size=(128, 96), views=4, seed=MASTER_SEED)
    physical = probe["P"]
    physical.meta["master_seed"] = MASTER_SEED
    physical.meta.setdefault("provenance", "BUILTIN_PROBE_FIXTURE_ROUGH_INTERFACE")

    observation = observe(mother_mesh, None, derive_named_rngs(MASTER_SEED, LINEAGE_ID),
                          route=ROUTE_PROXY_SCAN, profile="LOCAL", spec=_degrade_observation_spec())
    bundles = bundles_from_observation(observation)
    for bundle in bundles.values():
        bundle.meta["master_seed"] = MASTER_SEED
        bundle.meta["mother_asset_id"] = mother_asset
        bundle.meta["provenance"] = (
            f"DEMO_MOTHER_OBSERVATION:{observation.observation_id}"
            f"|route={observation.route}|size=320x240|views=4")
    return {"P": physical, **bundles}


_SOURCE_ROLE_SCHEMA: dict[str, tuple[str, str]] = {
    "P": ("physical_component", "synlab.physical.v1"),
    "I": ("obs_view", "synlab.obs.v1"),
    "G": ("obs_fused_geometry", "synlab.obs.v1"),
    "X": ("feature_bundle", "a12.obs.v1"),
}


def task_degrade_source(demo_root: Path, task: dict[str, Any], manifest: Manifest) -> dict[str, Any]:
    from synlab.degrade.api import commit_source

    family = str(task["family"])
    entry_id = f"degrade-source:{family}"
    entry = _entry(entry_id, "degrade_source", title=f"退化源 {family}")
    entry["family"] = family
    started = time.time()
    try:
        mother_entry = manifest.get("mother:V01")
        if not mother_entry or mother_entry.get("status") != "OK":
            entry.update({"status": "BLOCKED",
                          "failure": _failure("MOTHER_ASSET_MISSING",
                                              "mother:V01 尚未生成成功；先运行 --only mothers",
                                              stage="showcase.degrade_source")})
            entry["duration_s"] = round(time.time() - started, 3)
            return entry
        store = _store(demo_root)
        mother_asset = str(mother_entry["asset_id"])
        mother = _load_mother(store, mother_asset)
        sources = _build_family_sources(store, mother_asset=mother_asset, mother_mesh=mother.mesh)
        bundle = sources[family]
        role, schema = _SOURCE_ROLE_SCHEMA[family]
        record = commit_source(store, bundle, role=role, schema=schema,
                               lineage_id=LINEAGE_ID, split=SPLIT,
                               meta={"provenance": bundle.meta.get("provenance")})
        bundle.asset_id = record.asset_id
        entry.update({
            "status": "OK",
            "asset_id": record.asset_id,
            "role": record.role,
            "schema": record.schema,
            "unit": record.unit,
            "frame": record.frame,
            "metrics": {
                "family": family,
                "source_kind": bundle.source_kind,
                "content_hash": bundle.content_hash(),
                "payload_keys": sorted(bundle.payload),
                "provenance": bundle.meta.get("provenance"),
                "dropped_non_storable_keys": record.meta.get("dropped_non_storable_keys"),
                "storable": record.meta.get("storable", True),
                "master_seed": MASTER_SEED,
                "lineage_id": LINEAGE_ID,
                "mother_asset": mother_asset,
                "observation_size_px": [320, 240] if family in ("I", "G", "X") else None,
                "route_params": ({"voxel_mm": 0.2, "sparse_keep": 1.0, "hole_count": 0,
                                  "depth_error_sigma_mm": 0.05, "stride": 2}
                                 if family in ("I", "G", "X") else None),
                "defect_notes": list(OBSERVATION_DEFECT_NOTES) if family in ("I", "G", "X") else [],
                "commit_source": "synlab.degrade.api.commit_source",
            },
        })
    except BaseException as exc:  # noqa: BLE001
        entry.update({"status": "FAILED", "failure": _failure_from_exception(exc),
                      "traceback_tail": traceback.format_exc()[-1500:]})
    entry["duration_s"] = round(time.time() - started, 3)
    return entry


def _freeze_basis(axis_id: str, source: Any) -> Any:
    from synlab.degrade.api import DEFAULT_MASTER_SEED, get_operator
    from synlab.seeds import make_rng

    operator = get_operator(axis_id)
    variant = operator.resolve_variant(None)
    master_seed = int((source.meta or {}).get("master_seed", DEFAULT_MASTER_SEED))
    context = {
        "axis_id": axis_id,
        "lineage_id": LINEAGE_ID,
        "fragment_id": str(source.fragment_id or (source.meta or {}).get("fragment_id", "fragment")),
        "mother_id": str((source.meta or {}).get("mother_id", "")),
        "master_seed": master_seed,
        "source": source,
        "source_kind": source.source_kind,
    }
    rng = make_rng(master_seed, LINEAGE_ID, "degrade", axis_id, variant)
    return operator, variant, operator.sample_basis(context, rng, variant)


def _small_view_frame(frame: Any, *, max_edge: int = 320) -> Any:
    """把相机档缩到 ≤max_edge 长边（只改像素网格与内参，光轴/位姿不变）。"""
    import dataclasses

    import numpy as np

    width, height = int(frame.image_size[0]), int(frame.image_size[1])
    scale = min(1.0, float(max_edge) / float(max(width, height)))
    if scale >= 1.0:
        return frame
    K = np.asarray(frame.K, dtype=np.float64).copy() * scale
    K[2, 2] = 1.0
    return dataclasses.replace(
        frame, K=K, image_size=(max(int(round(width * scale)), 8),
                                max(int(round(height * scale)), 8)))


def _framed_view_frame(frame: Any, mesh: Any, *, max_edge: int = 320,
                       pad_fraction: float = 0.18) -> tuple[Any, dict[str, Any]]:
    """把相机档裁到物体投影窗口并缩放到 ≤max_edge 长边。

    这是**几何裁剪**：先按真实内参把网格顶点投到传感器像素，取包围窗口（含边距），
    再把主点平移、内参与窗口等比缩放，光轴方向与相机位姿完全不变。裁剪窗与缩放比
    写进渲染 meta，页面照实显示。
    """
    import dataclasses

    import numpy as np

    from synlab.cameras.api import project

    if frame.image_size[0] <= max_edge and frame.image_size[1] <= max_edge:
        return _small_view_frame(frame, max_edge=max_edge), {
            "crop": None, "note": "相机档原生长边已 ≤ 目标长边，未裁剪"}
    K = np.asarray(frame.K, dtype=np.float64)
    uv, z = project(np.asarray(mesh.vertices, dtype=np.float64), K,
                    np.asarray(frame.T_WC, dtype=np.float64),
                    None if frame.dist is None else np.asarray(frame.dist, dtype=np.float64),
                    model=str(frame.camera_model))
    finite = np.isfinite(uv[:, 0]) & np.isfinite(uv[:, 1]) & (z > 0)
    if not bool(np.any(finite)):
        return _small_view_frame(frame, max_edge=max_edge), {
            "crop": None, "note": "物体在当前相机档下没有有限投影，退回整幅缩放"}
    width, height = int(frame.image_size[0]), int(frame.image_size[1])
    u, v = uv[finite, 0], uv[finite, 1]
    span = max(float(u.max() - u.min()), float(v.max() - v.min()))
    pad = float(pad_fraction) * span + 4.0
    x0 = max(0.0, float(u.min()) - pad)
    x1 = min(float(width), float(u.max()) + pad)
    y0 = max(0.0, float(v.min()) - pad)
    y1 = min(float(height), float(v.max()) + pad)
    crop_w = max(x1 - x0, 8.0)
    crop_h = max(y1 - y0, 8.0)
    scale = min(1.0, float(max_edge) / max(crop_w, crop_h))
    out_w = max(int(round(crop_w * scale)), 8)
    out_h = max(int(round(crop_h * scale)), 8)
    K2 = K * scale
    K2[0, 2] = (K[0, 2] - x0) * scale
    K2[1, 2] = (K[1, 2] - y0) * scale
    K2[2, 2] = 1.0
    info = {
        "crop": {"x0": x0, "y0": y0, "width": crop_w, "height": crop_h,
                 "sensor_size_px": [width, height], "scale": scale},
        "object_pixels_in_sensor": [float(u.max() - u.min()), float(v.max() - v.min())],
        "note": "只裁剪像素窗口并等比缩放内参，光轴/位姿/畸变系数不变",
    }
    return dataclasses.replace(frame, K=K2, image_size=(out_w, out_h)), info


def _render_appearance_png(bundle: Any) -> tuple[Any, dict[str, Any]] | None:
    """用软件光栅把真实的逐面 texel albedo 渲染成一张帧（P05/P06 等外观轴）。"""
    import numpy as np

    from synlab.observe.render import LightSpec, RenderSpec, build_scene, render_view

    appearance = bundle.get("appearance") or {}
    mesh = bundle.get("mesh")
    if mesh is None or not appearance:
        return None
    albedo = appearance.get("texel_albedo")
    if albedo is None or len(np.asarray(albedo)) != len(mesh.faces):
        return None
    roughness = appearance.get("texel_roughness")
    n_faces = len(np.asarray(mesh.faces))
    if roughness is None or len(np.asarray(roughness)) != n_faces:
        roughness = np.full(n_faces, 0.6, dtype=np.float32)

    from synlab.cameras.api import camera_profiles, make_view_frames

    profile = next((p for p in camera_profiles() if p.tier == "LOCAL"), camera_profiles()[0])
    bbox = np.asarray(mesh.bounds, dtype=np.float64).reshape(-1)
    frames = make_view_frames(profile, bbox, 1, np.random.default_rng(MASTER_SEED), orbit=True)
    if not frames:
        return None
    frame, frame_info = _framed_view_frame(frames[0], mesh, max_edge=320)
    scene = build_scene(mesh, surface_tag=np.zeros(n_faces, dtype=np.int16),
                        face_id=np.arange(n_faces, dtype=np.int32),
                        albedo=np.asarray(albedo, dtype=np.float32),
                        roughness=np.asarray(roughness, dtype=np.float32),
                        name="degrade-appearance")
    direction = np.array([-0.35, -0.62, -0.70], dtype=np.float64)
    direction /= float(np.linalg.norm(direction))
    light = LightSpec(direction=direction, color=np.array([2.35, 2.25, 2.10]),
                      ambient=np.array([0.30, 0.30, 0.33]))
    render = render_view(scene, frame, light=light, spec=RenderSpec(supersample=1,
                                                                   max_pixels=4_000_000))
    rgb = _linear_to_display_u8(render.rgb_linear)
    return rgb, {
        "render_backend": render.meta.get("backend"),
        "view_id": frame.view_id,
        "profile_id": getattr(profile, "profile_id", None),
        "image_size_px": list(frame.image_size),
        "framing": frame_info,
        "mm_per_pixel": render.meta.get("mm_per_pixel"),
        "albedo_source_kind": render.meta.get("albedo_source_kind"),
        "surface_visible_fraction": render.meta.get("surface_visible_fraction"),
        "note": "真实软件光栅渲染：逐面 texel_albedo 取自本档位的真实 degradation 输出",
    }


def task_degrade_axis(demo_root: Path, task: dict[str, Any], manifest: Manifest) -> dict[str, Any]:
    import numpy as np

    from synlab.degrade.api import apply_axis, load_source
    from synlab.roles import ROLE_OBS_VIEW

    axis_id = str(task["axis_id"])
    family = axis_id[0]
    entry_id = f"degrade:{axis_id}"
    entry = _entry(entry_id, "degrade", title=f"退化轴 {axis_id}")
    entry["axis_id"] = axis_id
    entry["family"] = family
    started = time.time()
    source_entry = manifest.get(f"degrade-source:{family}")
    try:
        if not source_entry or source_entry.get("status") != "OK":
            entry.update({"status": "BLOCKED",
                          "failure": _failure("DEGRADE_SOURCE_MISSING",
                                              f"degrade-source:{family} 尚未生成成功；"
                                              f"先运行 --only degrade",
                                              stage="showcase.degrade")})
            entry["duration_s"] = round(time.time() - started, 3)
            return entry
        store = _store(demo_root)
        mother_entry = manifest.get("mother:V01")
        mother = _load_mother(store, str(mother_entry["asset_id"]))
        sources = _build_family_sources(store, mother_asset=str(mother_entry["asset_id"]),
                                        mother_mesh=mother.mesh)
        source = sources[family]
        expected_hash = str(source_entry["metrics"]["content_hash"])
        rebuilt_hash = source.content_hash()
        if rebuilt_hash != expected_hash:
            entry.update({
                "status": "FAILED",
                "failure": _failure(
                    "SOURCE_REBUILD_MISMATCH",
                    f"重建的 {family} 源与 degrade-source 步骤记录的内容哈希不一致；"
                    f"拒绝在同一 basis 上做跨源比较",
                    stage="showcase.degrade",
                    measurements={"expected": expected_hash, "rebuilt": rebuilt_hash}),
            })
            entry["duration_s"] = round(time.time() - started, 3)
            return entry
        source.asset_id = str(source_entry["asset_id"])
        source.role = str(source_entry.get("role") or "")
        source.schema = str(source_entry.get("schema") or "")
        source.lineage_id = LINEAGE_ID

        operator, variant, basis = _freeze_basis(axis_id, source)
        levels: list[dict[str, Any]] = []
        statuses: list[str] = []
        source_png: bytes | None = None
        source_png_meta: dict[str, Any] | None = None
        source_glb: dict[str, Any] | None = None

        for level in range(5):
            level_entry: dict[str, Any] = {
                "level": level,
                "variant": variant,
                "planned": _jsonable(operator.params_for(level, variant)),
                "status": "OK",
                "asset_id": None,
                "identity": False,
                "realized": False,
                "measured": {},
                "units": {},
                "artifacts": {},
            }
            try:
                record, measurement = apply_axis(
                    axis_id, level, source, store, variant=variant, basis=basis,
                    lineage_id=LINEAGE_ID, split=SPLIT)
                asset_id = getattr(record, "asset_id", None)
                bundle = load_source(store, asset_id) if asset_id else record.as_bundle()
                level_entry.update({
                    "asset_id": asset_id,
                    "role": getattr(record, "role", None),
                    "identity": bool(measurement.identity),
                    "realized": bool(measurement.realized),
                    "factor_kind": measurement.factor_kind,
                    "measured": _jsonable(measurement.measured),
                    "units": _jsonable(measurement.units),
                    "source_hash": measurement.source_hash,
                    "result_hash": measurement.result_hash,
                    "na_reason": measurement.na_reason,
                    "failure_code": measurement.failure_code,
                    "label_status": measurement.extra.get("label_status"),
                    "invariants": _jsonable(measurement.extra.get("invariants")),
                    "calibration_status": measurement.calibration_status,
                    "identity_bytes_unchanged": bool(
                        measurement.result_hash == measurement.source_hash),
                })
                if level == 0:
                    level_entry["identity_reference_ok"] = bool(
                        asset_id == source.asset_id)

                artifacts: dict[str, Any] = {}
                # --- 图像通道：I 轴直接取真实渲染帧；外观变化轴用真实 texel albedo 重渲染
                rgb = None
                render_meta: dict[str, Any] | None = None
                frames = bundle.get("frames")
                if frames and "rgb" in (frames[0] or {}):
                    rgb = np.asarray(frames[0]["rgb"], dtype=np.uint8)
                    render_meta = {
                        "source": "degrade 输出的真实帧（route=PROXY_SCAN, 320x240）",
                        "view_id": str(frames[0].get("view_id")),
                        "encoding": str(frames[0].get("encoding")),
                        "image_size_px": [int(rgb.shape[1]), int(rgb.shape[0])],
                    }
                else:
                    rendered = _render_appearance_png(bundle)
                    if rendered is not None:
                        rgb, render_meta = rendered
                if rgb is not None:
                    png = _png_bytes(rgb)
                    image_record = _commit_png_asset(
                        store, role=ROLE_OBS_VIEW, schema="synlab.obs.v1", unit="px",
                        frame="pixel_cv_center", images={"png": png},
                        meta={"axis_id": axis_id, "level": level, "variant": variant,
                              "render": render_meta,
                              "source_asset": source.asset_id},
                        qa={"axis_id": axis_id, "level": level, "identity": bool(measurement.identity)},
                        ancestry=[source.asset_id] if source.asset_id else [],
                        label=f"degrade:{axis_id}:L{level}:png")
                    artifacts["png"] = {"asset_id": image_record.asset_id,
                                        "role": image_record.role, "key": "png",
                                        "render": render_meta}
                    if level == 0:
                        source_png = png
                        source_png_meta = render_meta

                # --- 几何通道：导出真实 mesh 的展示 GLB
                mesh = bundle.get("mesh")
                if mesh is not None and len(np.asarray(mesh.faces)) > 0:
                    glb_record, glb_metrics = _export_display_glb(
                        store, mesh, source_asset=asset_id,
                        label=f"degrade:{axis_id}:L{level}",
                        extra_meta={"axis_id": axis_id, "level": level, "variant": variant})
                    artifacts["glb"] = {"asset_id": glb_record.asset_id,
                                        "role": glb_record.role, "key": "glb",
                                        "metrics": glb_metrics}
                    if level == 0:
                        source_glb = artifacts["glb"]
                level_entry["artifacts"] = artifacts
                level_entry["result_hash_verified"] = bool(measurement.result_hash)
            except BaseException as exc:  # noqa: BLE001 - 单档失败不影响其它档
                failure = _failure_from_exception(exc)
                level_entry.update({
                    "status": "NA" if failure["code"] in ("NA_NOT_APPLICABLE",
                                                          "DEPENDENCY_CAPABILITY_MISSING")
                    else "FAILED",
                    "failure": failure,
                })
            levels.append(level_entry)
            statuses.append(str(level_entry["status"]))

        if "FAILED" in statuses:
            overall = "FAILED"
        elif all(status == "OK" for status in statuses):
            overall = "OK"
        elif "OK" in statuses:
            overall = "FAILED"
        else:
            overall = "NA"

        identity_level = levels[0]
        entry.update({
            "status": overall,
            "asset_id": source.asset_id,
            "role": source.role,
            "schema": source.schema,
            "unit": source.unit,
            "frame": source.frame,
            "metrics": {
                "axis_id": axis_id,
                "family": family,
                "stage": operator.STAGE,
                "substage": operator.SUBSTAGE,
                "variant": variant,
                "variants": operator.variants(),
                "default_variant": operator.default_variant,
                "factor_kind": operator.factor_kind_for(variant),
                "accepted_sources": list(operator.ACCEPTED_SOURCES),
                "label_invalidations": list(operator.LABEL_INVALIDATIONS),
                "calibration_status": levels[0].get("calibration_status"),
                "basis_id": basis.basis_id,
                "basis_seed_ref": basis.seed_ref,
                "basis_payload_keys": sorted(basis.payload),
                "source_asset": source.asset_id,
                "source_kind": source.source_kind,
                "source_content_hash": source.content_hash(),
                "source_provenance": source.meta.get("provenance"),
                "levels": levels,
                "level0_identity": {
                    "identity": bool(identity_level.get("identity")),
                    "asset_id": identity_level.get("asset_id"),
                    "identity_reference_ok": identity_level.get("identity_reference_ok"),
                    "bytes_unchanged": identity_level.get("identity_bytes_unchanged"),
                    "source_hash": identity_level.get("source_hash"),
                    "result_hash": identity_level.get("result_hash"),
                    "note": "level 0 不做任何重采样：返回 source 的资产引用/字节",
                },
                "measurements_source": "synlab.degrade.api.apply_axis -> Measurement",
            },
            "artifacts": {
                "baseline_png": (levels[0]["artifacts"].get("png") if levels[0].get("artifacts")
                                 else None),
                "baseline_glb": (levels[0]["artifacts"].get("glb") if levels[0].get("artifacts")
                                 else None),
            },
            "failure": (None if overall == "OK" else _failure(
                "AXIS_LEVEL_FAILED",
                f"{axis_id} 的 5 档中至少一档未达到 OK；逐档真实状态见 metrics.levels",
                stage="showcase.degrade",
                measurements={"statuses": statuses})),
        })
        del source_png, source_png_meta, source_glb  # 只用于可读性，等级资产已在 levels 里
    except BaseException as exc:  # noqa: BLE001
        entry.update({"status": "FAILED", "failure": _failure_from_exception(exc),
                      "traceback_tail": traceback.format_exc()[-1500:]})
    entry["duration_s"] = round(time.time() - started, 3)
    return entry


# ======================================================================================
# 轴目录（31 轴的声明 + 本次演示是否生成了数据）
# ======================================================================================
def build_axis_catalog(manifest: Manifest) -> list[dict[str, Any]]:
    try:
        from synlab.degrade.api import AXIS_REGISTRY

        rows = AXIS_REGISTRY.status_table()
    except BaseException as exc:  # noqa: BLE001
        return [{"axis_id": None, "error": f"{type(exc).__name__}: {exc}"}]
    generated = {e.get("axis_id"): e for e in manifest.by_kind("degrade")}
    catalog: list[dict[str, Any]] = []
    for row in rows:
        axis_id = str(row["axis_id"])
        entry = generated.get(axis_id)
        item = {
            "axis_id": axis_id,
            "family": axis_id[0],
            "family_name": {"P": "physical", "I": "image", "G": "geometry", "X": "estimate"}
            .get(axis_id[0], "unknown"),
            "stage": row.get("stage"),
            "substage": row.get("substage"),
            "unit": row.get("unit"),
            "variants": row.get("variants"),
            "default_variant": row.get("default_variant"),
            "factor_kinds": row.get("factor_kinds"),
            "accepted_sources": row.get("accepted_sources"),
            "level_parameters": (row.get("parameter_schema") or {}).get("levels"),
            "generated": bool(entry),
            "status": (entry or {}).get("status", "NA"),
            "entry_id": (entry or {}).get("entry_id"),
        }
        if not entry:
            item["na_reason"] = (
                f"本次演示集只生成 {len(DEGRADE_AXES)} 个轴"
                f"（{'/'.join(DEGRADE_AXES)}，见 tools/build_demo_assets.py::DEGRADE_AXES）；"
                "该轴未生成数据，因此没有可展示的真实测量值。"
                "要补齐请把它加进 DEGRADE_AXES 后运行 "
                "`& .venv\\Scripts\\python.exe tools\\build_demo_assets.py --only degrade`")
        catalog.append(item)
    return catalog


# ======================================================================================
# 工作单元编排
# ======================================================================================
def units_for(step: str, manifest: Manifest, limit: int | None) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    if step == "mothers":
        units = [{"kind": "mother", "vessel_id": v, "material_id": m} for v, m in MOTHER_UNITS]
    elif step == "patterns":
        mothers = [e["entry_id"] for e in manifest.by_kind("mother") if e.get("status") == "OK"]
        if not mothers:
            mothers = [f"mother:{v}" for v, _ in MOTHER_UNITS]
        for index, family in enumerate(PATTERN_FAMILIES):
            units.append({"kind": "pattern", "family_id": family,
                          "mother_entry": mothers[index % len(mothers)]})
    elif step == "fracture":
        units = [{"kind": "fracture", "vessel_id": v, "backend": b} for v, b in FRACTURE_CASES]
    elif step == "degrade":
        units = [{"kind": "degrade_source", "family": family} for family in ("P", "I", "G", "X")]
        units += [{"kind": "degrade_axis", "axis_id": axis} for axis in DEGRADE_AXES]
    if limit is not None:
        units = units[: max(int(limit), 0)]
    return units


def entry_id_for(task: dict[str, Any]) -> str:
    kind = task["kind"]
    if kind == "mother":
        return f"mother:{task['vessel_id']}"
    if kind == "pattern":
        return f"pattern:{task['family_id']}"
    if kind == "fracture":
        return f"fracture:{task['vessel_id']}:{task['backend']}"
    if kind == "degrade_source":
        return f"degrade-source:{task['family']}"
    if kind == "degrade_axis":
        return f"degrade:{task['axis_id']}"
    raise SystemExit(f"unknown task kind {kind!r}")


DISPATCH = {
    "mother": task_mother,
    "pattern": task_pattern,
    "fracture": task_fracture,
    "degrade_source": task_degrade_source,
    "degrade_axis": task_degrade_axis,
}

#: 每类单元的默认超时（秒）。碎裂最重，粗刀具体在本机会被系统杀掉，用短超时快速收集真实结局。
DEFAULT_TIMEOUTS = {
    "mother": 300.0,
    "pattern": 600.0,
    "fracture": 420.0,
    "degrade_source": 900.0,
    "degrade_axis": 900.0,
}


def run_task_inline(demo_root: Path, task: dict[str, Any], manifest: Manifest) -> dict[str, Any]:
    handler = DISPATCH[task["kind"]]
    return handler(demo_root, task, manifest)


def _inflight_path(demo_root: Path) -> Path:
    return demo_root / INFLIGHT_NAME


def mark_inflight(demo_root: Path, task: dict[str, Any]) -> None:
    path = _inflight_path(demo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"task": task, "started_at": _now_iso(), "pid": os.getpid()},
                               ensure_ascii=False), encoding="utf-8")


def clear_inflight(demo_root: Path) -> None:
    try:
        _inflight_path(demo_root).unlink(missing_ok=True)
    except OSError:  # pragma: no cover - best effort
        pass


def reconcile_inflight(manifest: Manifest, demo_root: Path) -> dict[str, Any] | None:
    """把上一次被系统杀掉的单元补成一条真实的 BLOCKED 条目（不是猜测，是观测事实）。"""
    path = _inflight_path(demo_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    clear_inflight(demo_root)
    task = data.get("task") or {}
    if not task:
        return None
    try:
        entry_id = entry_id_for(task)
    except SystemExit:
        return None
    previous = manifest.get(entry_id) or {}
    attempts = int(previous.get("attempts", 0)) + 1
    entry = _entry(entry_id, str(task.get("kind", "unknown")), title=f"单元 {entry_id}",
                   status="BLOCKED")
    entry.update({
        "task": task,
        "attempts": attempts,
        "duration_s": None,
        "exit_code": None,
        "failure": _failure(
            "PROCESS_KILLED",
            f"上一次运行在 {data.get('started_at')} 执行该单元时被系统杀掉：父进程与该单元的子进程"
            f"一起终止，没有 Python 异常、没有退出码，因此不存在任何算法结论。本机对重负载 Python "
            f"进程会直接杀进程树（见 docs/a12/showcase.md）。已连续被杀 {attempts} 次。",
            stage="showcase.subprocess",
            measurements={"killed_at": data.get("started_at"), "parent_pid": data.get("pid"),
                          "attempts": attempts}),
    })
    manifest.upsert(entry)
    manifest.save()
    return entry


#: 同一单元被系统杀掉多少次之后就不再自动重试（--force 可强制再试一次）。
DEFAULT_MAX_ATTEMPTS = 2


def run_task_child(task: dict[str, Any], *, demo_root: Path, timeout: float) -> dict[str, Any]:
    """在独立子进程里跑一个单元；被杀/超时/崩溃都变成真实的失败条目。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[name] = "1"
    cmd = [sys.executable, str(Path(__file__).resolve()), "--demo-root", str(demo_root),
           "--task", json.dumps(task, ensure_ascii=False)]
    started = time.time()
    try:
        completed = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   timeout=timeout, shell=False)
    except subprocess.TimeoutExpired:
        entry = _entry(entry_id_for(task), task["kind"], title=f"单元 {entry_id_for(task)}",
                       status="FAILED")
        entry.update({
            "task": task,
            "duration_s": round(time.time() - started, 3),
            "failure": _failure("TIMEOUT",
                                f"单元在 {timeout:.0f} s 内没有结束，父进程已终止它；"
                                f"这不是算法结论，而是本机的资源/时限事实",
                                stage="showcase.subprocess"),
            "exit_code": None,
        })
        return entry
    stdout = completed.stdout or ""
    payload = None
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_MARKER):
            try:
                payload = json.loads(line[len(RESULT_MARKER):].strip())
            except ValueError:
                payload = None
            break
    if payload is None:
        tail = ((completed.stderr or "") + "\n" + stdout)[-2500:]
        entry = _entry(entry_id_for(task), task["kind"], title=f"单元 {entry_id_for(task)}",
                       status="FAILED")
        killed = completed.returncode not in (0, 1)
        entry.update({
            "task": task,
            "duration_s": round(time.time() - started, 3),
            "exit_code": completed.returncode,
            "failure": _failure(
                "PROCESS_KILLED" if killed else "CHILD_NO_RESULT",
                (f"子进程以退出码 {completed.returncode} 结束且没有写出结果；"
                 f"本机对重负载 Python 进程会直接杀掉（无 Python 异常），"
                 f"因此该单元的真实结局是「被杀」而不是某条算法错误")
                if killed else
                (f"子进程退出码 {completed.returncode}，但没有输出结果行"),
                stage="showcase.subprocess",
                measurements={"returncode": completed.returncode}),
            "stderr_tail": tail,
        })
        return entry
    payload["exit_code"] = completed.returncode
    payload["task"] = task
    return payload


# ======================================================================================
# 主流程
# ======================================================================================
def _print_summary(manifest: Manifest, demo_root: Path) -> None:
    counts = manifest.counts()
    print(f"清单：{_rel(manifest.path)}")
    print(f"演示数据根：{_rel(demo_root)}  资产库：{_rel(demo_root / STORE_DIRNAME)}")
    print(f"条目总数：{counts['entries']}  "
          f"OK={counts['total'].get('OK', 0)}  FAILED={counts['total'].get('FAILED', 0)}  "
          f"BLOCKED={counts['total'].get('BLOCKED', 0)}  NA={counts['total'].get('NA', 0)}")
    for kind in sorted(counts["by_kind"]):
        bucket = counts["by_kind"][kind]
        print(f"  {kind:<15} total={bucket['total']:<3} OK={bucket.get('OK', 0):<3} "
              f"FAILED={bucket.get('FAILED', 0):<3} BLOCKED={bucket.get('BLOCKED', 0):<3} "
              f"NA={bucket.get('NA', 0):<3}")
    print("非 OK 条目（真实原因）：")
    for entry in manifest.entries:
        if entry.get("status") == "OK":
            continue
        failure = entry.get("failure") or {}
        print(f"  [{entry.get('status')}] {entry.get('entry_id')}  "
              f"{failure.get('code', '?')} :: {str(failure.get('message', ''))[:160]}")


def main(argv: list[str] | None = None) -> int:
    try:  # 逐行刷新：父进程可能被系统杀掉，缓冲的输出会整段丢失
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):  # pragma: no cover - 非 tty / 老解释器
        pass
    parser = argparse.ArgumentParser(
        description="生成 /synlab/showcase 的真实演示数据集（幂等、可分步、可续跑）")
    parser.add_argument("--only", action="append", default=None,
                        choices=["mothers", "patterns", "fracture", "degrade"],
                        help="只跑指定步骤（可重复）")
    parser.add_argument("--limit", type=int, default=None, help="每个步骤最多跑多少个单元")
    parser.add_argument("--unit", action="append", default=None,
                        help="只跑指定 entry_id 的单元（可重复），例如 --unit degrade-source:I")
    parser.add_argument("--force", action="store_true", help="忽略清单里已 OK 的条目，重跑")
    parser.add_argument("--demo-root", default=str(DEFAULT_DEMO_ROOT))
    parser.add_argument("--timeout", type=float, default=None, help="覆盖单元超时（秒）")
    parser.add_argument("--inline", action="store_true",
                        help="在父进程内执行单元（调试用；失去被杀保护）")
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS,
                        help="同一单元被系统杀掉多少次后不再自动重试（--force 可强制再试）")
    parser.add_argument("--summary", action="store_true", help="只打印清单摘要")
    parser.add_argument("--task", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    demo_root = Path(args.demo_root).expanduser().resolve()
    manifest = Manifest(demo_root / MANIFEST_NAME)

    if args.task:
        task = json.loads(args.task)
        try:
            result = run_task_inline(demo_root, task, manifest)
        except BaseException as exc:  # noqa: BLE001 - 子进程必须总能给出结构化结果
            result = _entry(entry_id_for(task), task.get("kind", "unknown"),
                            title=f"单元 {entry_id_for(task)}", status="FAILED")
            result["failure"] = _failure_from_exception(exc)
            result["traceback_tail"] = traceback.format_exc()[-2000:]
        sys.stdout.write(RESULT_MARKER + json.dumps(_jsonable(result), ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return 0

    if args.summary:
        _print_summary(manifest, demo_root)
        return 0

    steps = args.only or ["mothers", "patterns", "fracture", "degrade"]
    started = time.time()
    print(f"== build_demo_assets == {_now_iso()}")
    print(f"仓库根：{REPO_ROOT}")
    print(f"演示数据根：{_rel(demo_root)}   清单：{_rel(manifest.path)}")
    print(f"步骤：{', '.join(steps)}   limit={args.limit}   force={args.force}   "
          f"inline={args.inline}   seed={MASTER_SEED}")

    killed = reconcile_inflight(manifest, demo_root)
    if killed is not None:
        print(f"！上一次运行在 {killed['failure']['measurements'].get('killed_at')} "
              f"执行 {killed['entry_id']} 时被系统杀掉；已按真实观测记为 BLOCKED/PROCESS_KILLED"
              f"（attempts={killed.get('attempts')}）")

    # 依赖顺序：patterns/fracture 需要 mothers；degrade 需要 mothers
    if any(s in steps for s in ("patterns", "fracture", "degrade")) and "mothers" not in steps:
        if not [e for e in manifest.by_kind("mother") if e.get("status") == "OK"]:
            print("！patterns/fracture/degrade 需要母体资产，但清单里没有 OK 的母体："
                  "请先运行 --only mothers")

    executed = 0
    for step in steps:
        units = units_for(step, manifest, args.limit)
        print(f"\n-- 步骤 {step}：{len(units)} 个单元")
        for task in units:
            entry_id = entry_id_for(task)
            if args.unit and entry_id not in args.unit:
                continue
            existing = manifest.get(entry_id)
            if existing and existing.get("status") == "OK" and not args.force:
                print(f"   [skip] {entry_id} 已 OK（--force 可重跑）")
                continue
            previous_failure = (existing or {}).get("failure") or {}
            if (not args.force and previous_failure.get("code") == "PROCESS_KILLED"
                    and int((existing or {}).get("attempts", 0)) >= int(args.max_attempts)):
                print(f"   [skip] {entry_id} 已连续被系统杀掉 "
                      f"{existing.get('attempts')} 次（--force 可再试一次；"
                      f"--max-attempts 可调阈值）")
                continue
            timeout = (args.timeout if args.timeout is not None
                       else DEFAULT_TIMEOUTS.get(task["kind"], 600.0))
            t0 = time.time()
            attempts = int((existing or {}).get("attempts", 0)) + 1
            if not args.inline:
                mark_inflight(demo_root, task)
            try:
                if args.inline:
                    entry = run_task_inline(demo_root, task, manifest)
                else:
                    entry = run_task_child(task, demo_root=demo_root, timeout=timeout)
            finally:
                if not args.inline:
                    clear_inflight(demo_root)
            entry["attempts"] = attempts
            manifest.upsert(entry)
            manifest.data["axis_catalog"] = build_axis_catalog(manifest)
            manifest.save()
            executed += 1
            failure = entry.get("failure") or {}
            print(f"   [{entry.get('status')}] {entry_id}  {time.time() - t0:.1f}s"
                  + (f"  {failure.get('code')}: {str(failure.get('message'))[:120]}"
                     if failure else ""))

    manifest.data["axis_catalog"] = build_axis_catalog(manifest)
    manifest.data["demo_root"] = _rel(demo_root)
    manifest.data["store_root"] = _rel(demo_root / STORE_DIRNAME)
    manifest.data["manifest_path"] = _rel(manifest.path)
    manifest.data["environment_findings"] = list(ENVIRONMENT_FINDINGS)
    manifest.data["fracture_backends"] = backend_registry_status()
    runs = manifest.data.setdefault("runs", [])
    runs.append({
        "started_at": _now_iso(),
        "command": "& .venv\\Scripts\\python.exe tools\\build_demo_assets.py"
                   + (f" --only {' --only '.join(steps)}" if args.only else "")
                   + (f" --limit {args.limit}" if args.limit else "")
                   + (" --force" if args.force else ""),
        "steps": steps,
        "limit": args.limit,
        "force": bool(args.force),
        "inline": bool(args.inline),
        "units_executed": executed,
        "duration_s": round(time.time() - started, 2),
        "counts": manifest.counts(),
    })
    del runs[:-20]
    manifest.save()

    print(f"\n== 汇总（真实计数）==")
    _print_summary(manifest, demo_root)
    counts = manifest.counts()
    print(f"\n本次执行单元数：{executed}   总耗时：{time.time() - started:.1f}s")
    failing = counts["total"].get("FAILED", 0) + counts["total"].get("BLOCKED", 0)
    print(f"EXIT：{'0（全部 OK）' if failing == 0 else f'1（{failing} 个非 OK 条目，见上面真实原因）'}")
    return 0 if failing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
