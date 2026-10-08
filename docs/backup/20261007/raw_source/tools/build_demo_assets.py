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
import hashlib
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
#: 素面展示资产的**展示用**中性陶土色（不是权威材质；authority 的 materials 集成是 PENDING）
DISPLAY_NEUTRAL_BODY_U8 = [214, 208, 196, 255]

#: 展示用平滑法线的角度阈值（度）。**只影响 GLB 的 NORMAL 属性**：权威网格的顶点、面索引与
#: 绕向一字不改（`_verify_display_glb` 会逐三角面复算位置张量与绕向并写进资产 meta）。
#: 语义：顶点法线 = 与该顶点「主面」（面积最大的相邻面）夹角 ≤ 阈值的相邻面的**面积加权**平均。
#: 因此曲率连续的器壁会平滑，而真正跨过棱（如断面与外壁的交线）的面不会被平均糊掉。
DISPLAY_NORMAL_ANGLE_DEG = 30.0

#: 展示用断面着色（**显示着色**，不是权威材质）。分组来自权威面属性
#: `origin_kind`（0=mother_surface / 1=interface / 2=ambiguous）与 `interface_id`（≥0 = 新断面）。
#: 颜色只用于在视口里区分「新断面」与「原表面」；它**不代表**几何起伏、粗糙度或材质真值。
DISPLAY_SURFACE_STYLES: dict[str, dict[str, Any]] = {
    "new_fracture_surface": {
        "material": "synlab_display_new_fracture_surface",
        "label": "新断面（origin_kind=INTERFACE / interface_id≥0）",
        "base_color_u8": [246, 231, 197, 255],
        "roughness": 0.50,
    },
    "original_mother_surface": {
        "material": "synlab_display_original_surface",
        "label": "原表面（origin_kind=mother_surface）",
        "base_color_u8": [176, 172, 164, 255],
        "roughness": 0.85,
    },
    "ambiguous_surface": {
        "material": "synlab_display_ambiguous_surface",
        "label": "未判定面（origin_kind=ambiguous）",
        "base_color_u8": [132, 126, 118, 255],
        "roughness": 0.75,
    },
}

#: 断面分组的固定顺序（GLB 里 primitive / node 的顺序，也是前端图例的顺序）
DISPLAY_SURFACE_ORDER: tuple[str, ...] = (
    "original_mother_surface", "new_fracture_surface", "ambiguous_surface")

MASTER_SEED = 20261001
LINEAGE_ID = "a12_demo"
SPLIT = "train"

#: 唯一权威的生成命令（写进清单，也被展示 API `synlab/api/routers/showcase.py` 使用；
#: `tests/a12/showcase/test_showcase_api.py` 断言两处字符串一致）。
GENERATOR_COMMAND = "& .venv\\Scripts\\python.exe tools\\build_demo_assets.py"

RESULT_MARKER = "@@SYNLAB_DEMO_RESULT@@"

#: 子进程 → 父进程的结果传输深度预算。展示资产的实测值嵌在
#: ``metrics.fragments[i].glb.metrics.normals.*`` 里（第 7 层），默认 6 层会把它们抹成
#: 占位符；因此结果传输单独放宽，其它调用点保持默认值。
RESULT_MAX_DEPTH = 14

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
def _jsonable(value: Any, *, depth: int = 0, max_items: int = 400,
              max_depth: int = 6) -> Any:
    """把任意对象转成可 JSON 序列化、且体积可控的结构（不丢真实数值，只截断超长集合）。

    ``max_depth`` 是**嵌套深度上限**：超过就写 ``"<max-depth T>"`` 占位符。子进程把结果
    传回父进程时用更深的预算（``max_depth=RESULT_MAX_DEPTH``），否则展示资产的实测值
    （``fragments[i].glb.metrics.normals…``）会在第 7 层被抹成占位符、页面与测试都读不到。
    """
    import numpy as np

    if depth > max_depth:
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
        out = {str(k): _jsonable(v, depth=depth + 1, max_items=max_items, max_depth=max_depth)
               for k, v in items[:max_items]}
        if len(items) > max_items:
            out["__truncated_keys__"] = len(items) - max_items
        return out
    if isinstance(value, (list, tuple)):
        out = [_jsonable(v, depth=depth + 1, max_items=max_items, max_depth=max_depth)
               for v in value[:max_items]]
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


def _authority_vertex_normals(mesh: Any, *,
                              angle_threshold_deg: float = DISPLAY_NORMAL_ANGLE_DEG
                              ) -> tuple[Any, dict[str, Any]]:
    """权威网格 → 展示用逐顶点法线：**面积加权 + 角度阈值平滑 + 保持绕向**。

    规则（全部可复算，measurements 里带数值）：

    * 面法线由**绕向**决定（``cross(v1 - v0, v2 - v0)``，右手系），因此正反面与权威一致；
      退化面（面积 0）权重为 0，且不会被当作主面。
    * 每个顶点选「面积最大的相邻面」为主面，只平均与该主面夹角 ≤ ``angle_threshold_deg``
      的相邻面；权重是该面在这个顶点处的**面积**（三角面面积，与顶点无关 → 纯面积加权）。
    * 结果单位化；若加权和退化为 0（极罕见）则退回主面法线。

    这是**显示变换**：不移动任何顶点、不改变面索引与绕向，只写出 glTF 的 ``NORMAL``。
    """
    import numpy as np

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    stats: dict[str, Any] = {
        "angle_threshold_deg": float(angle_threshold_deg),
        "weighting": "face_area",
        "orientation": "winding (right-hand rule, cross(v1-v0, v2-v0))",
        "vertices": int(len(vertices)), "faces": int(len(faces)),
    }
    if len(faces) == 0 or len(vertices) == 0:
        return np.zeros((len(vertices), 3), dtype=np.float64), stats

    v0, v1, v2 = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    raw = np.cross(v1 - v0, v2 - v0)
    twice_area = np.linalg.norm(raw, axis=1)
    degenerate = twice_area <= 1e-12
    face_normals = raw / np.where(degenerate, 1.0, twice_area)[:, None]
    face_normals[degenerate] = 0.0
    area = 0.5 * twice_area
    area[degenerate] = 0.0

    order = np.argsort(faces.reshape(-1), kind="stable")
    flat_vertex = faces.reshape(-1)[order]
    flat_face = np.repeat(np.arange(len(faces)), 3)[order]
    starts = np.searchsorted(flat_vertex, np.arange(len(vertices) + 1))

    cos_limit = float(np.cos(np.radians(float(angle_threshold_deg))))
    normals = np.zeros((len(vertices), 3), dtype=np.float64)
    isolated = 0
    restricted = 0
    fallback = 0
    for vertex in range(len(vertices)):
        incident = flat_face[starts[vertex]:starts[vertex + 1]]
        if incident.size == 0:
            isolated += 1
            continue
        weights = area[incident]
        seed = int(incident[int(np.argmax(weights))])
        dots = face_normals[incident] @ face_normals[seed]
        keep = (dots >= cos_limit) & (weights > 0.0)
        if not bool(keep.any()):
            normals[vertex] = face_normals[seed]
            fallback += 1
            restricted += 1
            continue
        if int(keep.sum()) < int(incident.size):
            restricted += 1
        normal = (face_normals[incident[keep]] * weights[keep][:, None]).sum(axis=0)
        length = float(np.linalg.norm(normal))
        if length <= 1e-15:
            normals[vertex] = face_normals[seed]
            fallback += 1
        else:
            normals[vertex] = normal / length

    lengths = np.linalg.norm(normals, axis=1)
    reference = np.asarray(mesh.vertex_normals, dtype=np.float64)
    dots = np.einsum("ij,ij->i", normals, reference)
    stats.update({
        "degenerate_faces": int(degenerate.sum()),
        "isolated_vertices": int(isolated),
        "vertices_restricted_by_threshold": int(restricted),
        "seed_fallbacks": int(fallback),
        "max_normal_length_error": float(np.abs(lengths - 1.0).max()) if len(lengths) else 0.0,
        "min_normal_length": float(lengths.min()) if len(lengths) else 0.0,
        "max_angle_vs_trimesh_vertex_normals_deg":
            float(np.degrees(np.arccos(np.clip(dots.min(), -1.0, 1.0)))) if len(dots) else 0.0,
        "mean_angle_vs_trimesh_vertex_normals_deg":
            float(np.degrees(np.arccos(np.clip(dots, -1.0, 1.0))).mean()) if len(dots) else 0.0,
        "flipped_vs_trimesh_vertex_normals": int(np.count_nonzero(dots < 0.0)),
        "note": ("显示变换：只写 GLB 的 NORMAL，顶点位置 / 面索引 / 绕向未改"),
    })
    return normals, stats


def _display_surface_groups(mesh: Any) -> dict[str, Any]:
    """从**权威面属性**读断面分组（`origin_kind` / `interface_id`），不做任何几何推断。

    返回 ``{"groups": {name: {"faces": int, "area_mm2": float, "mask": ndarray}},
    "source": str, "authority": {...}}``；mesh 上没有这些面属性时返回空 ``groups``
    并说明原因（不猜）。
    """
    import numpy as np

    from synlab.schemas.runtime import (ORIGIN_AMBIGUOUS, ORIGIN_INTERFACE,
                                        ORIGIN_MOTHER_SURFACE)
    from synlab.storage.mesh_io import face_attrs

    attrs = face_attrs(mesh) or {}
    origin = attrs.get("origin_kind")
    interface = attrs.get("interface_id")
    if origin is None and interface is None:
        return {"groups": {}, "source": "mesh has no origin_kind/interface_id face attribute",
                "authority": {}}

    faces = np.asarray(mesh.faces, dtype=np.int64)
    area = np.asarray(mesh.area_faces, dtype=np.float64)
    origin_arr = (np.asarray(origin, dtype=np.int64) if origin is not None
                  else np.full(len(faces), -1, dtype=np.int64))
    interface_arr = (np.asarray(interface, dtype=np.int64) if interface is not None
                     else np.full(len(faces), -1, dtype=np.int64))

    # 权威语义：新断面 = origin_kind==INTERFACE **或** interface_id>=0；两者不一致时按并集归属
    # 到新断面，并把分歧数记下来（诚实：不掩盖属性之间的不一致）。
    new_surface = (origin_arr == ORIGIN_INTERFACE) | (interface_arr >= 0)
    ambiguous = (origin_arr == ORIGIN_AMBIGUOUS) & ~new_surface
    original = ~(new_surface | ambiguous)
    masks = {"new_fracture_surface": new_surface, "original_mother_surface": original,
             "ambiguous_surface": ambiguous}
    conflict = int(np.count_nonzero((origin_arr == ORIGIN_INTERFACE) != (interface_arr >= 0)))

    groups: dict[str, Any] = {}
    for name in DISPLAY_SURFACE_ORDER:
        mask = masks[name]
        if not bool(mask.any()):
            continue
        groups[name] = {"faces": int(mask.sum()),
                        "area_mm2": float(area[mask].sum()),
                        "mask": mask}
    # 相邻分组之间**共享**的顶点数：>0 说明断面与原表面在拓扑上共用顶点，
    # 顶点法线只能在阈值内平均（否则会把断面和原表面糊成一片，看不出断口棱线）。
    spans = 0
    masks_present = [masks[name] for name in DISPLAY_SURFACE_ORDER if bool(masks[name].any())]
    if len(masks_present) > 1:
        seen: set[int] = set()
        shared: set[int] = set()
        for mask in masks_present:
            current = set(np.unique(faces[mask]).tolist())
            shared |= (current & seen)
            seen |= current
        spans = len(shared)
    authority = {
        "faces_total": int(len(faces)),
        "area_total_mm2": float(area.sum()),
        "vertices_spanning_surface_groups": int(spans),
        "origin_kind_counts": {str(int(v)): int(np.count_nonzero(origin_arr == v))
                               for v in sorted(set(origin_arr.tolist()))},
        "interface_id_counts": {str(int(v)): int(np.count_nonzero(interface_arr == v))
                                for v in sorted(set(interface_arr.tolist()))},
        "origin_interface_vs_interface_id_conflicts": conflict,
        "new_surface_definition":
            "origin_kind == ORIGIN_INTERFACE(1) 或 interface_id >= 0",
    }
    return {"groups": groups, "source": "authority face attributes origin_kind/interface_id",
            "authority": authority}


def _decode_glb(glb: bytes) -> tuple[dict[str, Any], bytes]:
    """把 GLB 拆回 ``(glTF JSON, BIN chunk)``（用于导出后逐字节实测，而不是相信导出器）。"""
    import json as _json
    import struct

    data = bytes(glb)
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise ValueError(f"导出结果不是 GLB（magic={magic:#x}）")
    offset, tree, binary = 12, None, b""
    while offset < min(length, len(data)):
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset:offset + chunk_len]
        offset += chunk_len
        if chunk_type == 0x4E4F534A:
            tree = _json.loads(chunk.decode("utf-8"))
        elif chunk_type == 0x004E4942:
            binary = chunk
    if tree is None:
        raise ValueError("GLB 没有 JSON chunk")
    return tree, binary


def _accessor_array(tree: dict[str, Any], binary: bytes, index: int) -> Any:
    """读出 accessor 的数值数组（只支持 glTF 导出器实际会写的标量/向量类型）。"""
    import numpy as np

    component_dtypes = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16,
                        5125: np.uint32, 5126: np.float32}
    widths = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
    accessor = tree["accessors"][index]
    dtype = np.dtype(component_dtypes[accessor["componentType"]])
    width = widths[accessor["type"]]
    view = tree["bufferViews"][accessor["bufferView"]]
    base = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    count = int(accessor["count"])
    stride = int(view.get("byteStride") or dtype.itemsize * width)
    if stride == dtype.itemsize * width:
        flat = np.frombuffer(binary, dtype=dtype, count=count * width, offset=base)
        return flat.reshape(count, width) if width > 1 else flat
    rows = [np.frombuffer(binary, dtype=dtype, count=width,
                          offset=base + i * stride) for i in range(count)]
    stacked = np.stack(rows)
    return stacked if width > 1 else stacked.reshape(-1)


def _verify_display_glb(glb: bytes, *, expected_parts: list[dict[str, Any]]) -> dict[str, Any]:
    """导出后**从字节里复算**：属性列表、法线归一化误差、位置/绕向是否与权威一致。

    ``expected_parts`` 每项 ``{"name", "positions" (display m), "faces", "normal_index"}``，
    其中 ``positions``/``faces`` 就是要写进 GLB 的权威派生数组。任何一项对不上都会写进
    ``mismatches``（页面与文档照实引用，不隐藏）。
    """
    import numpy as np

    tree, binary = _decode_glb(glb)
    report: dict[str, Any] = {"primitives": [], "mismatches": []}
    by_node: dict[str, dict[str, Any]] = {}
    for node in tree.get("nodes", []):
        if "mesh" not in node:
            continue
        mesh_def = tree["meshes"][node["mesh"]]
        for primitive in mesh_def.get("primitives", []):
            attributes = sorted(primitive.get("attributes", {}))
            position = _accessor_array(tree, binary, primitive["attributes"]["POSITION"])
            index = (_accessor_array(tree, binary, primitive["indices"]).astype(np.int64)
                     if "indices" in primitive else None)
            material = primitive.get("material")
            material_name = (tree["materials"][material].get("name")
                             if material is not None else None)
            entry = {
                "node": str(node.get("name")),
                "material": material_name,
                "attributes": attributes,
                "has_normal": "NORMAL" in attributes,
                "vertices": int(position.shape[0]),
                "triangles": int(len(index) // 3) if index is not None else
                             int(position.shape[0] // 3),
            }
            normals = None
            if entry["has_normal"]:
                normals = _accessor_array(tree, binary, primitive["attributes"]["NORMAL"])
                lengths = np.linalg.norm(normals.astype(np.float64), axis=1)
                entry["normal_unit_max_abs_error"] = float(np.abs(lengths - 1.0).max())
                entry["normal_min_length"] = float(lengths.min())
            by_node[entry["node"]] = {"entry": entry, "position": position, "index": index,
                                      "normals": normals}
            report["primitives"].append(entry)
    report["primitive_count"] = len(report["primitives"])
    report["primitives_with_normal"] = sum(1 for p in report["primitives"] if p["has_normal"])
    report["all_primitives_have_normal"] = bool(
        report["primitives"] and report["primitives_with_normal"] == report["primitive_count"])
    if report["primitives"]:
        report["normal_unit_max_abs_error"] = max(
            (p.get("normal_unit_max_abs_error", 0.0) for p in report["primitives"]), default=0.0)

    triangles_total = 0
    position_max_error = 0.0
    normal_angle_max = 0.0
    normal_angle_mean = 0.0
    winding_ok = True
    for part in expected_parts:
        found = by_node.get(part["name"])
        if found is None:
            report["mismatches"].append(f"missing primitive {part['name']!r}")
            continue
        position = found["position"].astype(np.float64)
        index = found["index"]
        expected_positions = np.asarray(part["positions"], dtype=np.float64)
        expected_faces = np.asarray(part["faces"], dtype=np.int64)
        triangles_total += int(len(expected_faces))
        if index is None:
            report["mismatches"].append(f"{part['name']}: primitive has no indices")
            continue
        if position.shape != expected_positions.shape:
            report["mismatches"].append(
                f"{part['name']}: vertices {position.shape} != expected "
                f"{expected_positions.shape}")
            continue
        delta = np.abs(position - expected_positions).max() if position.size else 0.0
        position_max_error = max(position_max_error, float(delta))
        if not np.array_equal(index.reshape(-1, 3), expected_faces):
            report["mismatches"].append(f"{part['name']}: index buffer != authority faces")
            continue
        # 绕向：用 GLB 自己写出的位置与索引重算法线方向，必须与权威面法线同向
        tri = position[index.reshape(-1, 3)]
        raw = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        lengths = np.linalg.norm(raw, axis=1)
        good = lengths > 1e-12
        if bool(good.any()):
            authority_tri = expected_positions[expected_faces]
            ref = np.cross(authority_tri[:, 1] - authority_tri[:, 0],
                           authority_tri[:, 2] - authority_tri[:, 0])
            dots = np.einsum("ij,ij->i", raw[good], ref[good])
            if bool((dots <= 0).any()):
                winding_ok = False
                report["mismatches"].append(f"{part['name']}: winding flipped")
        if found["normals"] is not None and part.get("normals") is not None:
            got = found["normals"].astype(np.float64)
            want = np.asarray(part["normals"], dtype=np.float64)
            if got.shape == want.shape and got.size:
                cosines = np.clip(np.einsum("ij,ij->i", got, want), -1.0, 1.0)
                angles = np.degrees(np.arccos(cosines))
                normal_angle_max = max(normal_angle_max, float(angles.max()))
                normal_angle_mean = max(normal_angle_mean, float(angles.mean()))
    report.update({
        "triangles_total": int(triangles_total),
        "position_max_abs_error_vs_authority_m": float(position_max_error),
        "winding_matches_authority": bool(winding_ok),
        "normal_max_angle_vs_intended_deg": float(normal_angle_max),
        "normal_mean_angle_vs_intended_deg": float(normal_angle_mean),
    })
    return report


def _export_display_glb(store: Any, mesh: Any, *, source_asset: str | None,
                        label: str, extra_meta: dict[str, Any] | None = None,
                        bake: dict[str, Any] | None = None,
                        surface_split: bool = False) -> tuple[Any, dict[str, Any]]:
    """权威 mm/Z-up mesh → 米/Y-up 的 ``display_lod_glb`` 派生资产（与 worker 同一套契约）。

    ``bake`` 非空时导出**带纹样贴图**的展示几何：两个 primitive（带图卡 UV 的外壁 +
    纯 body 颜色的其余面），贴图就是卡片上那张 albedo PNG；法线从完整母体网格算一次后共用。
    没有 ``bake`` 时导出一个纯色 primitive（L0）。

    ``surface_split=True`` 时按**权威面属性** `origin_kind` / `interface_id` 把 L0 拆成
    多个 primitive（新断面 / 原表面 / 未判定），每个 primitive 一个展示材质；顶点位置、
    面索引与绕向一字不改，只是分组与着色——这是显示着色，不是几何起伏。
    所有路径都会写出由权威网格算出的逐顶点 ``NORMAL``（面积加权 + 角度阈值 + 保绕向），
    并在导出后从 GLB 字节里复算校验（``_verify_display_glb``）。
    """
    import numpy as np
    import trimesh

    from synlab.api import display
    from synlab.roles import ROLE_DISPLAY_LOD

    authority_vertices = np.asarray(mesh.vertices, dtype=np.float64)
    authority_extent = np.asarray(mesh.bounds[1]) - np.asarray(mesh.bounds[0])
    display_vertices = display.transform_vertices(authority_vertices)
    display_extent = display_vertices.max(axis=0) - display_vertices.min(axis=0)

    levels: dict[str, Any] = {}
    lod_notes: list[str] = []
    scene = trimesh.Scene()
    bake_stats: dict[str, Any] = {}
    geometry_totals = {"faces": 0, "vertices": 0}

    rotation = np.asarray(display.T_DISPLAY_AUTHORITY, dtype=np.float64)[:3, :3]
    # 法线**从权威网格算一次**（面积加权 + 角度阈值 + 保绕向），再按展示变换旋转到 m/Y-up。
    authority_normals, normal_stats = _authority_vertex_normals(
        mesh, angle_threshold_deg=DISPLAY_NORMAL_ANGLE_DEG)
    display_normals = authority_normals @ rotation.T
    normal_lengths = np.linalg.norm(display_normals, axis=1, keepdims=True)
    display_normals = display_normals / np.where(normal_lengths > 0, normal_lengths, 1.0)

    surface = (_display_surface_groups(mesh) if surface_split
               else {"groups": {}, "authority": {},
                     "source": "surface_split=False：本展示资产不做断面分色"})
    surface_groups = surface["groups"]
    expected_parts: list[dict[str, Any]] = []
    scene_nodes: list[str] = []
    display_parts: dict[str, Any] = {}

    def _neutral_material(name: str = "synlab_display_neutral_body") -> Any:
        return trimesh.visual.material.PBRMaterial(
            name=name, baseColorFactor=DISPLAY_NEUTRAL_BODY_U8, metallicFactor=0.0,
            roughnessFactor=0.72)

    def _add_solid_part(node_name: str, face_ids: Any, material: Any) -> Any:
        """按给定的**权威面 id 集合**加一个 primitive。

        顶点做**致密化重映射**（只保留该组引用到的顶点，位置值不变），法线按同一映射取——
        因此几何（位置张量与绕向）与权威逐位一致，变的只是分组、顶点缓冲排布与材质。
        """
        ids = np.asarray(face_ids, dtype=np.int64)
        faces_arr = (np.asarray(mesh.faces, dtype=np.int64)[ids] if ids.size
                     else np.zeros((0, 3), dtype=np.int64))
        used = (np.unique(faces_arr.reshape(-1)) if faces_arr.size
                else np.zeros(0, dtype=np.int64))
        remap = np.full(len(display_vertices), -1, dtype=np.int64)
        remap[used] = np.arange(len(used), dtype=np.int64)
        part = trimesh.Trimesh(vertices=display_vertices[used],
                               faces=remap[faces_arr], process=False)
        part.visual = trimesh.visual.TextureVisuals(material=material)
        part._cache["vertex_normals"] = np.ascontiguousarray(display_normals[used])
        scene.add_geometry(part, node_name=node_name)
        scene_nodes.append(node_name)
        display_parts[node_name] = {
            "faces": int(len(part.faces)), "vertices": int(len(part.vertices)),
            "material": getattr(material, "name", None),
            "uv": False}
        expected_parts.append({"name": node_name,
                               "positions": np.asarray(part.vertices, dtype=np.float64),
                               "faces": np.asarray(part.faces, dtype=np.int64),
                               "normals": np.asarray(part._cache["vertex_normals"])})
        return part

    if bake is None:
        faces_all = np.asarray(mesh.faces, dtype=np.int64)
        # L1/L2 的简化结果**照实测量并记录**，但不放进同一个场景：展示页的视口把场景里的
        # 所有节点一起渲染（`SceneViewport` 没有 LOD 选择器），多层级重叠会 z-fighting，
        # 而二次误差简化的 L2 实测外扩到 193.95 mm（L0 是 182.45 mm），会直接穿出器壁。
        measure_mesh = trimesh.Trimesh(vertices=display_vertices, faces=faces_all, process=False)
        levels["L0"] = {"faces": int(len(faces_all)), "vertices": int(len(display_vertices)),
                        "exported_as_scene_node": False}
        for level, ratio in (("L1", 0.3), ("L2", 0.08)):
            try:
                simplified = measure_mesh.simplify_quadric_decimation(
                    face_count=max(4, int(len(measure_mesh.faces) * ratio)))
            except BaseException as exc:  # noqa: BLE001 - 简化后端是可选的，缺失要如实记录
                lod_notes.append(f"{level} skipped: {type(exc).__name__}: {exc}")
                continue
            if simplified is None or len(simplified.faces) == 0:
                lod_notes.append(f"{level} skipped: decimation returned no faces")
                continue
            extent = np.asarray(simplified.bounds[1]) - np.asarray(simplified.bounds[0])
            levels[level] = {"faces": int(len(simplified.faces)),
                             "vertices": int(len(simplified.vertices)),
                             "display_extent_m": extent.tolist(),
                             "exported_as_scene_node": False}
            lod_notes.append(
                f"{level} measured only (faces={int(len(simplified.faces))}, "
                f"extent_m={np.round(extent, 6).tolist()}): 不放进场景，避免与 L0 重叠渲染")

        if surface_groups:
            # 断面分色：按权威面属性把 L0 拆成 2~3 个 primitive，每个一个展示材质。
            for name in DISPLAY_SURFACE_ORDER:
                group = surface_groups.get(name)
                if group is None:
                    continue
                style = DISPLAY_SURFACE_STYLES[name]
                material = trimesh.visual.material.PBRMaterial(
                    name=str(style["material"]), baseColorFactor=list(style["base_color_u8"]),
                    metallicFactor=0.0, roughnessFactor=float(style["roughness"]))
                _add_solid_part(name, np.flatnonzero(group["mask"]), material)
            lod_notes.append(
                "surface_split：按权威面属性 origin_kind/interface_id 分成 "
                + "/".join(scene_nodes) + "（顶点位置、面索引、绕向与权威逐位一致；"
                "颜色只是显示着色，不代表几何起伏或材质真值）")
        else:
            _add_solid_part("L0", np.arange(len(faces_all), dtype=np.int64), _neutral_material())
        geometry_totals = {"faces": int(len(faces_all)), "vertices": int(len(display_vertices))}
        lod_notes.append("scene_nodes=" + ",".join(scene_nodes) +
                         "（展示视口同时渲染场景所有节点，因此只放 L0 的展示几何）")
    else:
        from PIL import Image

        texture = Image.open(io.BytesIO(bytes(bake["albedo_png"])))
        texture.load()
        roughness = float(bake.get("roughness", 0.65))
        body_color = np.asarray(bake.get("body_color_linear", (0.5, 0.5, 0.5)),
                                dtype=np.float64)

        textured = bake["textured"]
        wall_vertices = display.transform_vertices(
            np.asarray(textured["vertices_mm"], dtype=np.float64))
        wall_faces = np.asarray(textured["faces"], dtype=np.int64)
        wall_index = np.asarray(textured["normal_index"], dtype=np.int64)
        wall = trimesh.Trimesh(vertices=wall_vertices, faces=wall_faces, process=False)
        wall.visual = trimesh.visual.TextureVisuals(
            uv=np.asarray(textured["uv"], dtype=np.float64),
            material=trimesh.visual.material.PBRMaterial(
                name="synlab_display_pattern_wall", baseColorFactor=[255, 255, 255, 255],
                metallicFactor=0.0, roughnessFactor=roughness, baseColorTexture=texture))
        parts = [("wall", wall, wall_index)]
        body = bake["body"]
        if len(np.asarray(body["faces"])) > 0:
            shell = trimesh.Trimesh(
                vertices=display.transform_vertices(np.asarray(body["vertices_mm"], dtype=np.float64)),
                faces=np.asarray(body["faces"], dtype=np.int64), process=False)
            shell.visual = trimesh.visual.TextureVisuals(
                material=trimesh.visual.material.PBRMaterial(
                    name="synlab_display_pattern_body",
                    baseColorFactor=np.rint(np.clip(body_color, 0.0, 1.0) * 255.0).astype(np.uint8),
                    metallicFactor=0.0, roughnessFactor=roughness))
            parts.append(("body", shell, np.asarray(body["normal_index"], dtype=np.int64)))
        for name, part, normal_index in parts:
            # 法线从完整母体网格算一次后按索引取，两个 primitive 共用 → tag 边界与 UV 解缠缝
            # 上都不会出现假折线（trimesh 只在 cache 里有 vertex_normals 时才导出 NORMAL）
            part_normals = np.ascontiguousarray(display_normals[normal_index])
            part._cache["vertex_normals"] = part_normals
            scene.add_geometry(part, node_name=name)
            scene_nodes.append(name)
            display_parts[name] = {"faces": int(len(part.faces)),
                                   "vertices": int(len(part.vertices)),
                                   "material": getattr(part.visual.material, "name", None),
                                   "uv": bool(getattr(part.visual, "uv", None) is not None)}
            expected_parts.append({"name": name,
                                   "positions": np.asarray(part.vertices, dtype=np.float64),
                                   "faces": np.asarray(part.faces, dtype=np.int64),
                                   "normals": part_normals})
            levels[name] = {"faces": int(len(part.faces)), "vertices": int(len(part.vertices)),
                            "uv": bool(getattr(part.visual, "uv", None) is not None),
                            "exported_as_scene_node": True}
        lod_notes.append("LOD skipped: 顶点色/贴图是逐原始顶点烘焙的，简化会重采样它们")
        bake_stats = {"primitives": [name for name, _, _ in parts],
                      "texture_bytes": len(bytes(bake["albedo_png"]))}
        geometry_totals = {
            "faces": int(sum(len(part.faces) for _, part, _ in parts)),
            "vertices": int(sum(len(part.vertices) for _, part, _ in parts)),
        }
    glb = scene.export(file_type="glb", include_normals=True)
    # 导出后**从字节里复算**：属性列表 / 归一化误差 / 位置与绕向是否与权威一致。
    glb_check = _verify_display_glb(glb, expected_parts=expected_parts)
    if not glb_check["all_primitives_have_normal"]:
        raise RuntimeError(
            f"展示 GLB 缺少 NORMAL（{label}）：primitives="
            f"{[p['attributes'] for p in glb_check['primitives']]}")

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
            "bake": bake_stats or None,
            "scene_nodes": list(scene_nodes),
            "display_parts": display_parts,
            "display_material": (
                {"mode": "pattern_texture", "metallicFactor": 0.0}
                if bake is not None else
                ({"mode": "surface_split_display_shading", "metallicFactor": 0.0,
                  "styles": {name: {"material": DISPLAY_SURFACE_STYLES[name]["material"],
                                    "label": DISPLAY_SURFACE_STYLES[name]["label"],
                                    "baseColorFactor": DISPLAY_SURFACE_STYLES[name]["base_color_u8"],
                                    "roughnessFactor": DISPLAY_SURFACE_STYLES[name]["roughness"]}
                             for name in display_parts if name in DISPLAY_SURFACE_STYLES},
                  "note": "新断面/原表面只是**显示着色**（来源：权威面属性 "
                          "origin_kind/interface_id），不代表几何起伏、粗糙度或材质真值"}
                 if surface_groups else
                 {"mode": "neutral_display_body", "baseColorFactor": DISPLAY_NEUTRAL_BODY_U8,
                  "metallicFactor": 0.0, "roughnessFactor": 0.72,
                  "material_name": "synlab_display_neutral_body",
                  "note": "展示用中性陶土色，不是权威材质；synlab.materials 的集成仍是 PENDING"})),
            "normals": {
                "mode": "authority_area_weighted_angle_threshold",
                "angle_threshold_deg": DISPLAY_NORMAL_ANGLE_DEG,
                "weighting": "face_area",
                "orientation": "winding-preserving (cross(v1-v0, v2-v0))",
                "stats": normal_stats,
                "export_check": glb_check,
                "note": ("顶点法线随 GLB 导出：three.js GLTFLoader 在几何没有 NORMAL 时会设 "
                         "flatShading=true（node_modules/three/examples/jsm/loaders/GLTFLoader.js:"
                         "3522/3581），那样每个三角面都是平色块。这是**显示着色**：顶点位置、"
                         "面索引与绕向与权威逐位一致（见 export_check）。"),
            },
            "surface_groups": (
                {name: {"faces": group["faces"], "area_mm2": group["area_mm2"],
                        "material": DISPLAY_SURFACE_STYLES[name]["material"],
                        "label": DISPLAY_SURFACE_STYLES[name]["label"]}
                 for name, group in surface_groups.items()} if surface_groups else None),
            "surface_group_source": surface["source"] if surface_groups else None,
            "surface_group_authority": surface["authority"] or None,
            "note": "display-only derivation; authoritative geometry remains mm/Z-up and is untouched",
            **(extra_meta or {}),
        },
        qa={
            "authority_extent_mm": authority_extent.tolist(),
            "display_extent_m": display_extent.tolist(),
            "transform_id": transform["transform_id"],
            "glb_bytes": len(glb),
            "primitives_with_normal": glb_check["primitives_with_normal"],
            "all_primitives_have_normal": glb_check["all_primitives_have_normal"],
            "normal_unit_max_abs_error": glb_check.get("normal_unit_max_abs_error", None),
            "position_max_abs_error_vs_authority_m":
                glb_check["position_max_abs_error_vs_authority_m"],
            "winding_matches_authority": glb_check["winding_matches_authority"],
            "glb_mismatches": glb_check["mismatches"],
        },
        qa_status="QA_PASS" if (glb_check["all_primitives_have_normal"]
                                and not glb_check["mismatches"]) else "QA_FAIL",
        ancestry=[source_asset] if source_asset else [],
        lineage_id=LINEAGE_ID,
        split=SPLIT,
    )
    metrics = {
        "glb_asset_id": record.asset_id,
        "glb_bytes": len(glb),
        "authority_extent_mm": authority_extent.tolist(),
        "display_extent_m": display_extent.tolist(),
        "triangles": int(geometry_totals["faces"]),
        "vertices": int(geometry_totals["vertices"]),
        "lod_levels": sorted(levels),
        "lod_notes": lod_notes,
        "display_transform_id": transform["transform_id"],
        "bake": bake_stats or None,
        "scene_nodes": list(scene_nodes),
        "normals": {
            "angle_threshold_deg": DISPLAY_NORMAL_ANGLE_DEG,
            "weighting": "face_area",
            "primitives": [{k: p[k] for k in ("node", "material", "attributes", "vertices",
                                              "triangles", "has_normal")}
                           for p in glb_check["primitives"]],
            "all_primitives_have_normal": glb_check["all_primitives_have_normal"],
            "normal_unit_max_abs_error": glb_check.get("normal_unit_max_abs_error", None),
            "normal_max_angle_vs_intended_deg": glb_check["normal_max_angle_vs_intended_deg"],
            "max_normal_length_error": normal_stats["max_normal_length_error"],
            "vertices_restricted_by_threshold": normal_stats["vertices_restricted_by_threshold"],
            "max_angle_vs_trimesh_vertex_normals_deg":
                normal_stats["max_angle_vs_trimesh_vertex_normals_deg"],
            "flipped_vs_trimesh_vertex_normals": normal_stats["flipped_vs_trimesh_vertex_normals"],
        },
        "geometry_unchanged": {
            "position_max_abs_error_vs_authority_m":
                glb_check["position_max_abs_error_vs_authority_m"],
            "winding_matches_authority": glb_check["winding_matches_authority"],
            "triangles_in_glb": glb_check["triangles_total"],
            "authority_faces": int(len(np.asarray(mesh.faces))),
            "mismatches": glb_check["mismatches"],
        },
        "surface_groups": (
            {name: {"faces": group["faces"], "area_mm2": group["area_mm2"],
                    "material": DISPLAY_SURFACE_STYLES[name]["material"]}
             for name, group in surface_groups.items()} if surface_groups else None),
        "surface_group_source": surface["source"] if surface_groups else None,
        "surface_group_authority": surface["authority"] or None,
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
#: 纹样通道栅格的采样预算：一次 ``evaluate`` 调用的总点数（含超采样与像素中心点）。
PATTERN_RASTER_SAMPLE_BUDGET = 1_200_000
#: 每像素 2×2 超采样 → 线性空间面积平均（抗锯齿）；全程确定性，不抽随机数。
PATTERN_RASTER_SUPERSAMPLE = 2
PATTERN_RASTER_MIN_COLS = 64
PATTERN_RASTER_MAX_COLS = 1280
PATTERN_RASTER_MIN_ROWS = 8
PATTERN_RASTER_MAX_ROWS = 1280


def _chart_parts(frame: Any) -> tuple[dict[str, Any], dict[str, Any], str]:
    """图卡冻结时一起落盘的数值数组 / 规格 / 真实类型（母体把数组存在 ``meta["arrays"]``）。"""
    meta = dict(getattr(getattr(frame, "chart", None), "meta", None) or {})
    return (dict(meta.get("arrays") or {}), dict(meta.get("spec") or {}),
            str((meta.get("spec") or {}).get("kind") or frame.kind))


def _chart_inverse(frame: Any) -> tuple[Any, str]:
    """``(x_mm, s_mm) -> 母体毫米坐标``：只用图卡冻结时自带的数据重建。

    母体图卡**不带** ``chart.meta["uv_to_xyz"]`` 闭包（``synlab/mothers/charts.py`` 从不写它，
    只有 ``synlab/patterns/fixtures.py`` 的测试实体提供），所以逆映射从图卡自带的冻结数组重建：

    * ``revolve``：``profile_rzs`` 是母线折线 ``(r, z)``，``s`` 是沿母线的弧长（与 ``to_uv``
      里 ``poly.project`` 同一张弧长表），``u = x_mm / x_period_mm`` 是方位角分数；
    * ``prism``：``ring_xy`` 是挤出环，``u`` 是环周长分数、``s`` 是高度；
    * ``sweep``（开放）：``x`` 本身就是沿路径的毫米弧长，``s`` 是 z。

    重建点与 ``to_chart_mm`` 的往返误差在 1e-13 mm 量级（生成时实测并写进清单）。
    """
    import numpy as np

    arrays, spec, kind = _chart_parts(frame)
    if kind == "revolve":
        profile = np.asarray(arrays.get("profile_rzs"), dtype=np.float64)
        if profile.ndim != 2 or profile.shape[1] < 2 or profile.shape[0] < 2:
            raise RuntimeError("revolve 图卡缺少 profile_rzs，无法重建 (x,s) → 世界坐标")
        rz = profile[:, :2]
        s_tab = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(rz, axis=0), axis=1))])
        period = float(spec.get("x_period_mm") or frame.x_period_mm or 0.0)
        if not period > 0:
            raise RuntimeError("revolve 图卡缺少正周期，无法重建 (x,s) → 世界坐标")

        def inverse_revolve(x_mm: Any, s_mm: Any) -> Any:
            x = np.asarray(x_mm, dtype=np.float64)
            s = np.asarray(s_mm, dtype=np.float64)
            r = np.interp(s, s_tab, rz[:, 0])
            z = np.interp(s, s_tab, rz[:, 1])
            theta = 2.0 * np.pi * np.mod(x, period) / period
            return np.column_stack([r * np.cos(theta), r * np.sin(theta), z])

        return inverse_revolve, kind

    if kind == "prism":
        ring = np.asarray(arrays.get("ring_xy"), dtype=np.float64)
        if ring.ndim != 2 or ring.shape[1] != 2 or ring.shape[0] < 3:
            raise RuntimeError("prism 图卡缺少 ring_xy，无法重建 (x,s) → 世界坐标")
        closed = np.vstack([ring, ring[:1]])
        s_tab = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))])
        perimeter = float(s_tab[-1])
        z0 = float(spec.get("z_min_mm", 0.0))

        def inverse_prism(x_mm: Any, s_mm: Any) -> Any:
            x = np.asarray(x_mm, dtype=np.float64)
            s = np.asarray(s_mm, dtype=np.float64)
            s_ring = np.mod(x, perimeter)
            return np.column_stack([np.interp(s_ring, s_tab, closed[:, 0]),
                                    np.interp(s_ring, s_tab, closed[:, 1]),
                                    z0 + s])

        return inverse_prism, kind

    if kind == "sweep":
        path = np.asarray(arrays.get("path_xyz"), dtype=np.float64)
        if path.ndim != 2 or path.shape[1] != 3 or path.shape[0] < 2:
            raise RuntimeError("sweep 图卡缺少 path_xyz，无法重建 (x,s) → 世界坐标")
        s_tab = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])

        def inverse_sweep(x_mm: Any, s_mm: Any) -> Any:
            x = np.asarray(x_mm, dtype=np.float64)
            s = np.asarray(s_mm, dtype=np.float64)
            return np.column_stack([np.interp(x, s_tab, path[:, 0]),
                                    np.interp(x, s_tab, path[:, 1]), s])

        return inverse_sweep, kind

    raise RuntimeError(f"图卡类型 {kind!r} 没有 (x,s) → 世界坐标的逆映射")


def _measure_chart_x_range(mother: Any, frame: Any) -> tuple[float, float]:
    """开放图卡（planar/sweep）没有声明 x 范围：从真实网格量出来，不猜。"""
    import numpy as np

    from synlab.patterns.api import to_chart_mm

    faces = np.asarray(mother.mesh.faces, dtype=np.int64)
    tags = np.asarray(mother.face_surface_tag)
    mask = tags == int(frame.tag)
    if not bool(np.any(mask)):
        raise RuntimeError(f"母体上没有 surface_tag={frame.tag_name!r} 的面，无法建纹样栅格")
    vidx = np.unique(faces[mask].reshape(-1))
    verts = np.asarray(mother.mesh.vertices, dtype=np.float64)[vidx]
    x_mm, _ = to_chart_mm(frame, verts)
    return float(x_mm.min()), float(x_mm.max())


def _pattern_raster_plan(frame: Any, mother: Any, *, footprint_mm: float | None = None
                         ) -> dict[str, Any]:
    """栅格几何：周期列 ``u_k = (k + 0.5) / W``、行 ``s_j = s_lo + j * ds``（``ds = span/(H-1)``）。

    列一定是 ``[0,1)`` 上的周期采样（**不含**端点 1）：``u=0`` 与 ``u=1`` 落在同一列上，
    接缝天然闭合，回绕列差就是普通相邻列差。行取满 ``[s_lo, s_hi]`` 且**端点即首末行中心**，
    于是贴图 v 坐标严格落在 ``[0.5/H, 1-0.5/H]`` 内——采样器的 wrap 模式（REPEAT/CLAMP）
    在 v 上不可能造成任何差异。

    分辨率：texel 近似正方形，先受 :data:`PATTERN_RASTER_SAMPLE_BUDGET` 约束，再**不必细于
    场自带的特征尺度** ``footprint_mm``（小于它只是重复采样同一个平滑场）。
    """
    import numpy as np

    supersample = max(int(PATTERN_RASTER_SUPERSAMPLE), 1)
    periodic = bool(frame.u_periodic) and bool(frame.x_period_mm)
    if periodic:
        period: float | None = float(frame.x_period_mm)
        x_lo, x_span = 0.0, period
    else:
        period = None
        x_lo, x_hi = _measure_chart_x_range(mother, frame)
        x_span = max(x_hi - x_lo, 1e-9)
    s_lo, s_hi = float(frame.s_min_mm), float(frame.s_max_mm)
    s_span = s_hi - s_lo
    if not s_span > 0:
        raise RuntimeError(f"图卡 {frame.name!r} 的 s 范围为空 [{s_lo}, {s_hi}]，无法建纹样栅格")
    aspect = s_span / x_span
    pixels_budget = max(PATTERN_RASTER_SAMPLE_BUDGET // (supersample * supersample + 1), 1)
    width = int(np.clip(round(np.sqrt(pixels_budget / max(aspect, 1e-12))),
                        PATTERN_RASTER_MIN_COLS, PATTERN_RASTER_MAX_COLS))
    footprint = None if footprint_mm is None or footprint_mm <= 0 else float(footprint_mm)
    if footprint is not None:  # 不比场自己的特征尺度更细
        cap = int(np.ceil(x_span / footprint))
        if PATTERN_RASTER_MIN_COLS <= cap < width:
            width = cap
    height = int(np.clip(round(width * aspect), PATTERN_RASTER_MIN_ROWS, PATTERN_RASTER_MAX_ROWS))
    total = width * height * (supersample * supersample + 1)
    if total > PATTERN_RASTER_SAMPLE_BUDGET:  # 仍超预算：等比缩到预算内
        scale = float(np.sqrt(PATTERN_RASTER_SAMPLE_BUDGET / float(total)))
        width = max(int(width * scale), PATTERN_RASTER_MIN_COLS)
        height = max(int(height * scale), PATTERN_RASTER_MIN_ROWS)
    ds = s_span / float(max(height - 1, 1))
    texel = [float(x_span) / float(width), float(ds)]
    return {
        "width": width, "height": height, "supersample": supersample,
        "x_lo": float(x_lo), "x_span": float(x_span), "x_period_mm": period,
        "x_periodic": periodic, "s_lo": s_lo, "s_hi": s_hi, "s_span": float(s_span), "ds": float(ds),
        "texel_mm": texel,
        "footprint_mm": footprint,
        "texel_over_footprint": (None if footprint is None
                                 else float(np.hypot(texel[0], texel[1]) / footprint)),
        "u_rule": "u_k = (k + 0.5) / W，k = 0..W-1（周期 [0,1)，不含端点 1）",
        "s_rule": "s_j = s_lo + j * ds，ds = (s_hi - s_lo) / (H - 1)（端点即首末行中心）",
    }


def _texel_face_coverage(mother: Any, frame: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """实测：图卡矩形里到底有多少 texel 真的被 tagged 面占据（逐面精确点内测试）。

    这不是"有没有花纹"的指标，而是"这张图卡贴图有多少面积在网格上真的可见"的诚实披露：
    图卡坐标是 (u, s) 的展开矩形，而真实网格只占据其中一部分（例如内壁与外壁共享同一个
    ``(u,s)``，被占据的 texel 也会多于外壁；反过来某段 ``s`` 可能只有部分方位角有面）。
    """
    import numpy as np

    from synlab.patterns.charts import to_chart_mm

    width, height = int(plan["width"]), int(plan["height"])
    faces = np.asarray(mother.mesh.faces, dtype=np.int64)
    tags = np.asarray(mother.face_surface_tag)
    mask = tags == int(frame.tag)
    if not bool(np.any(mask)):
        return {"fraction": 0.0, "texels": 0, "faces": 0}
    vertices = np.asarray(mother.mesh.vertices, dtype=np.float64)
    x_mm, s_mm = to_chart_mm(frame, vertices)
    if plan["x_periodic"]:
        u = np.mod(x_mm, float(plan["x_period_mm"])) / float(plan["x_period_mm"])
    else:
        u = (x_mm - plan["x_lo"]) / max(plan["x_span"], 1e-9)
    u = u * width - 0.5
    v = (s_mm - plan["s_lo"]) / max(plan["ds"], 1e-12)

    covered = np.zeros((height, width), dtype=bool)
    tri = faces[mask]
    for corners in (tri,):
        cu = u[corners]
        cv = v[corners]
        if plan["x_periodic"]:
            lo = cu.min(axis=1, keepdims=True)
            wrapped = (cu.max(axis=1, keepdims=True) - lo) > 0.5 * width
            shift = np.where(cu < (lo + 0.5 * width), width, 0.0)
            cu = np.where(wrapped, cu + shift, cu)
        for k in range(cu.shape[0]):
            xu, yv = cu[k], cv[k]
            x0, x1 = int(np.floor(xu.min())), int(np.ceil(xu.max()))
            y0, y1 = int(np.floor(yv.min())), int(np.ceil(yv.max()))
            if x1 < x0 or y1 < y0:
                continue
            cols = np.arange(x0, x1 + 1, dtype=np.int64)
            rows = np.arange(max(y0, 0), min(y1, height - 1) + 1, dtype=np.int64)
            if cols.size == 0 or rows.size == 0:
                continue
            gx, gy = np.meshgrid(cols.astype(np.float64), rows.astype(np.float64))
            # 重心坐标点内测试（像素中心 = texel 中心）
            ax, ay = xu[0], yv[0]
            bx, by = xu[1], yv[1]
            cx, cy = xu[2], yv[2]
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(float(den)) < 1e-12:
                continue
            w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
            w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
            if not bool(np.any(inside)):
                continue
            hit_rows, hit_cols = np.nonzero(inside)
            covered[rows[hit_rows], np.mod(cols[hit_cols], width)] = True
    texels = int(covered.sum())
    return {"fraction": float(texels) / float(width * height), "texels": texels,
            "faces": int(tri.shape[0])}


def _pattern_chart_raster(mother: Any, recipe: Any, frame: Any, plan: dict[str, Any]
                          ) -> dict[str, Any]:
    """冻结 recipe 在真实图卡坐标上的**确定性**求值 → 三通道栅格 + 三张 PNG。

    每个像素取 ``supersample²`` 个 texel 内子样点 + 1 个 texel 中心点；所有点先在
    ``(x_mm, s_mm)`` 上构造，再用图卡逆映射变成真实母体毫米坐标，交给
    ``synlab.patterns.api.evaluate``（场本身是纯函数、不抽随机数）。三通道用**同一网格、
    同一 recipe、同一次调用**，所以 albedo/roughness/height 逐像素对齐；超采样在线性空间
    取面积平均（抗锯齿）。栅格**没有**"未覆盖像素"：整张图卡矩形都被解析求值覆盖，
    同时实测并记录"矩形里到底有多少 texel 真的被 tagged 面占据"。
    """
    import numpy as np

    from synlab.patterns.api import evaluate
    from synlab.patterns.charts import to_chart_mm

    inverse, chart_kind = _chart_inverse(frame)
    width, height, ss = int(plan["width"]), int(plan["height"]), int(plan["supersample"])
    n_texels = width * height
    ku = (np.arange(width, dtype=np.float64) + 0.5) / float(width)
    ks = np.arange(height, dtype=np.float64)
    grid_x = np.broadcast_to((plan["x_lo"] + ku * plan["x_span"])[None, :], (height, width))
    grid_s = np.broadcast_to((plan["s_lo"] + ks * plan["ds"])[:, None], (height, width))

    step_x, step_s = float(plan["texel_mm"][0]), float(plan["ds"])
    half = (np.arange(ss, dtype=np.float64) + 0.5) / float(ss) - 0.5  # ss=2 → [-0.25, +0.25]
    offsets = [(du, dv) for dv in half for du in half] if ss > 1 else []
    # 超采样只在图卡的合法范围内取样（边界行/列按 clamp 处理）：图卡外的点会被
    # ``to_uv`` 的 clip 折叠回边界，那会让"逆映射往返"变成假误差
    layers = [np.clip(grid_x + du * step_x, plan["x_lo"], plan["x_lo"] + plan["x_span"])
              for du, _ in offsets] + [grid_x]
    layers_s = [np.clip(grid_s + dv * step_s, plan["s_lo"], plan["s_hi"])
                for _, dv in offsets] + [grid_s]
    x_all = np.concatenate([a.reshape(-1) for a in layers])
    s_all = np.concatenate([a.reshape(-1) for a in layers_s])
    points = inverse(x_all, s_all)

    x_back, s_back = to_chart_mm(frame, points)
    if plan["x_periodic"]:
        period = float(plan["x_period_mm"])
        dx = np.abs(np.mod(x_back - x_all + 0.5 * period, period) - 0.5 * period)
    else:
        dx = np.abs(x_back - x_all)
    roundtrip = {"x_max_mm": float(dx.max()), "s_max_mm": float(np.abs(s_back - s_all).max())}

    channels_eval = evaluate(recipe, mother, points, int(frame.tag))
    n_layers = len(layers)
    albedo_layers = np.asarray(channels_eval.albedo, dtype=np.float64).reshape(n_layers, n_texels, 3)
    rough_layers = np.asarray(channels_eval.roughness, dtype=np.float64).reshape(n_layers, n_texels)
    height_layers = np.asarray(channels_eval.height_mm, dtype=np.float64).reshape(n_layers, n_texels)
    region_layers = np.asarray(channels_eval.pattern_region, dtype=np.uint8).reshape(
        n_layers, n_texels)

    n_sub = len(offsets)
    if n_sub:
        albedo = albedo_layers[:n_sub].mean(axis=0)
        roughness = rough_layers[:n_sub].mean(axis=0)
        height_mm = height_layers[:n_sub].mean(axis=0)
    else:  # 没有超采样时唯一一层就是像素中心
        albedo = albedo_layers[0]
        roughness = rough_layers[0]
        height_mm = height_layers[0]
    centre_albedo, centre_rough, centre_height = albedo_layers[-1], rough_layers[-1], height_layers[-1]
    in_region = region_layers.any(axis=0)

    albedo = albedo.reshape(height, width, 3)
    roughness = roughness.reshape(height, width)
    height_mm = height_mm.reshape(height, width)
    centre_albedo = centre_albedo.reshape(height, width, 3)
    centre_rough = centre_rough.reshape(height, width)
    centre_height = centre_height.reshape(height, width)
    in_region = in_region.reshape(height, width)

    # 逐像素来看，超采样面积均值与"像素中心解析值"的差就是抗锯齿低通量（如实记录，不掩饰）
    dev_albedo = np.abs(albedo - centre_albedo).reshape(n_texels, 3)
    dev_rough = np.abs(roughness - centre_rough).reshape(n_texels)
    dev_height = np.abs(height_mm - centre_height).reshape(n_texels)

    albedo_u8 = _linear_to_display_u8(albedo)
    rough_u8 = _gray_u8(roughness)
    amp = max(float(np.max(np.abs(height_mm))) if height_mm.size else 0.0, 1e-6)
    height_u8 = _diverging_bwr(height_mm / amp)

    # 连续性：列均值（x 方向）与行均值（s 方向）的相邻差、以及回绕列差
    def _continuity(plane: Any) -> dict[str, float]:
        cols = np.asarray(plane, dtype=np.float64).mean(axis=0)
        rows = np.asarray(plane, dtype=np.float64).mean(axis=1)
        adj_col = np.abs(np.diff(cols))
        adj_row = np.abs(np.diff(rows))
        return {
            "column_adjacent_mean_abs": float(adj_col.mean()) if adj_col.size else 0.0,
            "column_adjacent_max_abs": float(adj_col.max()) if adj_col.size else 0.0,
            "column_wrap_abs": float(abs(cols[0] - cols[-1])) if cols.size else 0.0,
            "row_adjacent_mean_abs": float(adj_row.mean()) if adj_row.size else 0.0,
            "row_max_abs": float(adj_row.max()) if adj_row.size else 0.0,
        }

    continuity = {"albedo_linear": _continuity(albedo.mean(axis=2)),
                  "roughness": _continuity(roughness),
                  "height_mm": _continuity(height_mm)}

    # 图卡矩形被 tagged 面真实占据的比例（逐面点内测试；没被占据的 texel 在网格上不可见）
    coverage = _texel_face_coverage(mother, frame, plan)
    face_coverage = float(coverage["fraction"])

    legend = {
        "albedo_png": (f"{PNG_ENCODING_LEGEND['albedo']}；网格 {width}×{height}（texel "
                       f"{plan['texel_mm'][0]:.4f}×{plan['texel_mm'][1]:.4f} mm），"
                       f"每像素 {ss}×{ss} 超采样在线性空间取面积平均；"
                       f"整张图卡矩形都被求值覆盖，没有空洞像素"),
        "roughness_png": (f"{PNG_ENCODING_LEGEND['roughness']}；同一网格、同一 recipe 的同一次 "
                          f"evaluate() 调用；实测范围 [{float(roughness.min()):.4f}, "
                          f"{float(roughness.max()):.4f}]"),
        "height_png": (f"{PNG_ENCODING_LEGEND['height_mm']}；对称幅度 amax={amp:.6f} mm，"
                       f"实测 min={float(height_mm.min()):.6f} mm、"
                       f"max={float(height_mm.max()):.6f} mm；"
                       f"height 是几何通道，展示 GLB 只烘焙 albedo，不做位移"),
    }
    images = {
        "albedo_png": _png_bytes(albedo_u8),
        "roughness_png": _png_bytes(rough_u8),
        "height_png": _png_bytes(height_u8),
    }
    stats = {
        "raster": {
            "width": width, "height": height, "supersample": ss,
            "n_samples": int(x_all.size),
            "method": ("确定性图卡栅格：像素中心 (u_k, s_j) 经图卡逆映射回到母体毫米坐标后调用 "
                       "evaluate()，每像素 ss×ss 超采样在线性空间取面积平均；不抽随机数、无空洞"),
            "grid": {"u_rule": plan["u_rule"], "s_rule": plan["s_rule"],
                     "texel_mm": [float(plan["texel_mm"][0]), float(plan["ds"])],
                     "width": width, "height": height},
            "footprint_mm": plan["footprint_mm"],
            "texel_over_footprint": plan["texel_over_footprint"],
            "chart": frame.as_dict(), "chart_kind": chart_kind,
            "x_period_mm": (None if plan["x_period_mm"] is None else float(plan["x_period_mm"])),
            "x_periodic": bool(plan["x_periodic"]),
            "s_range_mm": [float(plan["s_lo"]), float(plan["s_hi"])],
            "inverse_mapping": ("(x_mm, s_mm) → 母体 mm：由图卡自带的 "
                                f"{'profile_rzs' if chart_kind == 'revolve' else 'ring_xy' if chart_kind == 'prism' else 'path_xyz'} "
                                "数组重建；往返误差见 inverse_roundtrip_mm"),
            "inverse_roundtrip_mm": roundtrip,
            "face_coverage_fraction": face_coverage,
            "texels_in_pattern_region_fraction": float(in_region.mean()),
            "continuity": continuity,
            "analytic_deviation": {
                "note": "超采样面积均值 vs 像素中心解析值（抗锯齿低通量，不是误差掩盖）",
                "albedo_max_abs": float(dev_albedo.max()) if dev_albedo.size else 0.0,
                "albedo_p95_abs": float(np.percentile(dev_albedo, 95)) if dev_albedo.size else 0.0,
                "roughness_max_abs": float(dev_rough.max()) if dev_rough.size else 0.0,
                "height_mm_max_abs": float(dev_height.max()) if dev_height.size else 0.0,
            },
            "rng": "NONE：栅格是冻结 recipe 的确定性求值",
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
            "albedo_at_pixel_centre_min": float(centre_albedo.min()),
            "albedo_at_pixel_centre_max": float(centre_albedo.max()),
        },
        "legend": legend,
    }
    return {"images": images, "stats": stats, "plan": plan, "frame": frame,
            "x_mm": (plan["x_lo"] + ku * plan["x_span"]), "s_mm": (plan["s_lo"] + ks * plan["ds"]),
            "n_texels": n_texels}


def _pattern_texture_bake(mother: Any, recipe: Any, frame: Any, plan: dict[str, Any], *,
                          albedo_png: bytes, albedo_sha256: str,
                          texture_asset: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """把同一份冻结栅格贴到母体真实图卡坐标上 → 展示 GLB 的贴图 primitive + UV + 统计。

    * **图卡坐标 → UV**：``u = x_mm / x_period_mm``（周期，采样器 wrapS=REPEAT），
      ``v = ((s_mm - s_lo) / ds + 0.5) / H``（texel 中心对齐，严格落在 ``(0,1)`` 内）；
    * **接缝**：跨 ``u=0/1`` 的面按面做 UV 解缠（给小于半周的一侧 ``+1`` 一整周），并把解缠后的
      角点拆成独立顶点，于是同一三角形内不会出现"绕整张贴图倒着插值"；又因为场本身周期，
      缝两侧的色值本来就相等；
    * **未带纹样的面**（rim/foot/base/inner_wall…）单独一个 primitive、用 recipe 的 body 颜色：
      内壁与外壁共享同一个 ``(u,s)``，拿外壁的 UV 去采样贴图会把图案画到内壁；
    * **法线**：从完整母体网格算一次（面积加权）后由两个 primitive 共用，tag 边界与解缠缝上
      都不会出现假折线。
    """
    import numpy as np

    from synlab.patterns.charts import to_chart_mm

    vertices = np.asarray(mother.mesh.vertices, dtype=np.float64)
    faces = np.asarray(mother.mesh.faces, dtype=np.int64)
    tags = np.asarray(mother.face_surface_tag)
    x_mm, s_mm = to_chart_mm(frame, vertices)
    width, height = int(plan["width"]), int(plan["height"])

    if plan["x_periodic"]:
        period = float(plan["x_period_mm"])
        u_chart = np.mod(x_mm, period) / period
    else:
        u_chart = (x_mm - plan["x_lo"]) / max(plan["x_span"], 1e-9)
    row_coord = (s_mm - plan["s_lo"]) / max(plan["ds"], 1e-12)
    v_target = (row_coord + 0.5) / float(height)
    v_lo, v_hi = 0.5 / float(height), 1.0 - 0.5 / float(height)
    v_clamped = int(np.count_nonzero((v_target < v_lo) | (v_target > v_hi)))
    v_target = np.clip(v_target, v_lo, v_hi)

    wall_mask = tags == int(frame.tag)
    wall_faces = faces[wall_mask]
    body_faces = faces[~wall_mask]
    if wall_faces.size == 0:
        raise RuntimeError(f"母体上没有 surface_tag={frame.tag_name!r} 的面，无法烘焙纹样贴图")
    wall_vidx_all = np.unique(wall_faces.reshape(-1))
    wall_v_clamped = int(np.count_nonzero((row_coord[wall_vidx_all] < 0.0)
                                          | (row_coord[wall_vidx_all] > float(height - 1))))

    # 面级 UV 解缠：同一三角形内的 u 跨度不超过半周，否则给小的一侧 +1
    u_corner = u_chart[wall_faces].copy()
    if plan["x_periodic"]:
        u_lo = u_corner.min(axis=1, keepdims=True)
        wrapped = (u_corner.max(axis=1, keepdims=True) - u_lo) > 0.5
        if bool(np.any(wrapped)):
            shift = np.where(u_corner < (u_lo + 0.5), 1.0, 0.0)
            u_corner = np.where(wrapped, u_corner + shift, u_corner)
    offset = np.rint(u_corner - u_chart[wall_faces]).astype(np.int64)
    corner_key = wall_faces.astype(np.int64) * 4 + offset
    unique_key, inverse_index = np.unique(corner_key.reshape(-1), return_inverse=True)
    vidx = unique_key // 4
    u_unique = u_chart[vidx] + (unique_key % 4).astype(np.float64)
    wall_vertices = vertices[vidx]
    # trimesh 导出 GLB 时会做 uv[:, 1] = 1 - uv[:, 1]（见 trimesh/exchange/gltf 的
    # _append_mesh），所以这里先取补，写进 GLB 的 TEXCOORD_0.v 才等于 v_target。
    wall_uv = np.column_stack([u_unique, 1.0 - v_target[vidx]])
    wall_faces_idx = np.asarray(inverse_index, dtype=np.int64).reshape(-1, 3)

    body_vidx = (np.unique(body_faces.reshape(-1)) if body_faces.size
                 else np.zeros(0, dtype=np.int64))
    remap = np.full(vertices.shape[0], -1, dtype=np.int64)
    remap[body_vidx] = np.arange(body_vidx.size, dtype=np.int64)
    body_faces_idx = (remap[body_faces] if body_faces.size
                      else np.zeros((0, 3), dtype=np.int64))

    palette = dict((recipe.meta or {}).get("palette") or {})
    body = np.asarray(palette.get("body", (recipe.palette or [(0.5, 0.5, 0.5)])[0]),
                      dtype=np.float64)
    body_color = np.clip(body, 0.0, 1.0)
    body_roughness = float(palette.get("body_roughness", 0.6))

    stats = {
        "mode": "chart_texture",
        "uv_mapping": ("TEXCOORD_0.u = x_mm / x_period_mm（周期，sampler wrapS=REPEAT）；"
                       "TEXCOORD_0.v = ((s_mm - s_lo) / ds + 0.5) / H"
                       "（texel 中心对齐，v ∈ (0,1)）"),
        "texture_source": ("与卡片同一份 albedo PNG（同一冻结 recipe、同一栅格、同一份字节），"
                           "以 glTF baseColorTexture（sRGB）嵌进 GLB"),
        "texture_asset": texture_asset,
        "texture_sha256": albedo_sha256,
        "texture_key": "albedo_png",
        "wall_faces": int(wall_faces_idx.shape[0]),
        "wall_vertices": int(wall_vertices.shape[0]),
        "body_faces": int(body_faces_idx.shape[0]),
        "body_vertices": int(body_vidx.size),
        "body_color_linear": [float(c) for c in body_color],
        "body_roughness": body_roughness,
        "seam_unwrapped_corners": int(np.count_nonzero(offset)),
        "uv_v_clamped_vertices": v_clamped,
        "uv_v_clamped_wall_vertices": wall_v_clamped,
        "uv_u_range": [float(wall_uv[:, 0].min()), float(wall_uv[:, 0].max())],
        "uv_v_range_gltf": [float((1.0 - wall_uv[:, 1]).min()),
                            float((1.0 - wall_uv[:, 1]).max())],
        "normals": "完整母体网格的面积加权顶点法线，两个 primitive 共用（无缝、无假折线）",
        "height_channel_in_glb": False,
        "height_note": ("height_mm 是几何通道（PAT14 relief / PAT15 engrave），由 "
                        "synlab.patterns.api.apply_pattern_geometry 在断裂前作用到完整母体；"
                        "展示 GLB 只烘焙 albedo，不做位移"),
    }
    bake = {
        "textured": {"vertices_mm": wall_vertices, "faces": wall_faces_idx, "uv": wall_uv,
                     "normal_index": vidx},
        "body": {"vertices_mm": (vertices[body_vidx] if body_vidx.size
                                 else np.zeros((0, 3), dtype=np.float64)),
                 "faces": body_faces_idx, "normal_index": body_vidx},
        "albedo_png": albedo_png,
        "body_color_linear": body_color,
        "roughness": body_roughness,
    }
    return bake, stats


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
        from synlab.patterns.charts import resolve_frame

        frame = resolve_frame(mother, str((recipe.meta.get("chart") or {}).get("surface_tag")
                                          or "outer_wall"))
        plan = _pattern_raster_plan(frame, mother,
                                    footprint_mm=recipe.meta.get("footprint_mm"))
        raster = _pattern_chart_raster(mother, recipe, frame, plan)
        images, raster_stats = raster["images"], raster["stats"]
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
                  "raster": raster_stats["raster"],
                  "channel_stats": raster_stats["channel_stats"],
                  "legend": raster_stats["legend"]},
            qa={"pass": bool(audit.get("pass")), "failures": _jsonable(audit.get("failures"))},
            ancestry=[mother_asset, recipe_record.asset_id],
            label=f"pattern:{family}:channels")
        # ---- 器物三维烘焙：同一份冻结栅格贴到该母体真实图卡坐标上
        albedo_png = images["albedo_png"]
        albedo_sha = "sha256:" + hashlib.sha256(albedo_png).hexdigest()
        bake, bake_stats = _pattern_texture_bake(
            mother, recipe, frame, plan, albedo_png=albedo_png, albedo_sha256=albedo_sha,
            texture_asset=image_record.asset_id)
        glb_record, glb_metrics = _export_display_glb(
            store, mother.mesh, source_asset=mother_asset,
            label=f"pattern:{family}:{mother_entry_id}",
            extra_meta={
                "family_id": family,
                "family_name": recipe.meta.get("family_name"),
                "mother_entry": mother_entry_id,
                "mother_asset": mother_asset,
                "mother_vessel_id": mother_entry.get("vessel_id"),
                "recipe_hash": recipe_record.meta.get("recipe_hash"),
                "raster_asset": image_record.asset_id,
                "raster_size": [int(plan["width"]), int(plan["height"])],
                "chart": raster_stats["raster"]["chart"],
                "uv": bake_stats,
                "note": ("pattern-baked display derivation: 同一冻结 recipe 的同一张 albedo 栅格"
                         "贴在母体真实图卡坐标上；权威几何仍是 mm/Z-up 且未被修改"),
            },
            bake=bake)
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
                "texture_bake": bake_stats,
                "provenance": {
                    "family_id": family,
                    "family_name": recipe.meta.get("family_name"),
                    "recipe_hash": recipe_record.meta.get("recipe_hash"),
                    "recipe_asset": recipe_record.asset_id,
                    "mother_entry": mother_entry_id,
                    "mother_asset": mother_asset,
                    "mother_vessel_id": mother_entry.get("vessel_id"),
                    "raster_asset": image_record.asset_id,
                    "raster_png_keys": {"albedo": "albedo_png", "roughness": "roughness_png",
                                        "height_mm": "height_png"},
                    "albedo_png_sha256": albedo_sha,
                    "pattern_glb_asset": glb_record.asset_id,
                    "note": "族名 / recipe hash / PNG 文件名 / 贴图 GLB 四者由同一次单元生成写入，"
                            "可在清单与资产 meta 里逐项核对",
                },
            },
            "artifacts": {
                "channels": {"asset_id": image_record.asset_id, "role": image_record.role,
                             "keys": {"albedo": "albedo_png", "roughness": "roughness_png",
                                      "height_mm": "height_png"}},
                "pattern_glb": {"asset_id": glb_record.asset_id, "role": glb_record.role,
                                "key": "glb", "metrics": glb_metrics,
                                "raster_asset": image_record.asset_id,
                                "albedo_png_sha256": albedo_sha},
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
            extra_meta={"fragment_id": str(fragment.fragment_id), "event_id": entry_id},
            surface_split=True)
        # 断面分色的一致性**用权威面属性复算**（不看 GLB 里的分组自证）：
        # 分组面数 / 面积来自 fragment.mesh 的 origin_kind / interface_id 与权威面积。
        authority_groups = _display_surface_groups(fragment.mesh)
        group_rows = {name: {"faces": group["faces"], "area_mm2": group["area_mm2"],
                             "material": DISPLAY_SURFACE_STYLES[name]["material"]}
                      for name, group in authority_groups["groups"].items()}
        display_rows = glb_metrics.get("surface_groups") or {}
        faces_ok = all(display_rows.get(name, {}).get("faces") == row["faces"]
                       for name, row in group_rows.items()) and len(display_rows) == len(group_rows)
        area_ok = all(abs(display_rows.get(name, {}).get("area_mm2", -1.0) - row["area_mm2"])
                      <= 1e-9 * max(1.0, abs(row["area_mm2"]))
                      for name, row in group_rows.items())
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
            "surface_groups": group_rows,
            "surface_group_source": authority_groups["source"],
            "surface_group_authority": authority_groups["authority"],
            "surface_group_check": {
                "display_face_counts_match_authority": bool(faces_ok),
                "display_areas_match_authority": bool(area_ok),
                "authority_faces_total": int(len(fragment.mesh.faces)),
                "display_faces_total": int(sum(row.get("faces", 0) for row in display_rows.values())),
                "authority_area_total_mm2": float(authority_groups["authority"]["area_total_mm2"]),
                "display_area_total_mm2": float(sum(row.get("area_mm2", 0.0)
                                                    for row in display_rows.values())),
            },
            "display_geometry_check": glb_metrics.get("geometry_unchanged"),
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
        "display_shading": {
            "mode": "authority_area_weighted_angle_threshold + surface_split",
            "angle_threshold_deg": DISPLAY_NORMAL_ANGLE_DEG,
            "surface_group_source": "authority face attributes origin_kind / interface_id",
            "geometry_untouched": "GLB 的 POSITION 与索引逐位等于权威派生数组（见各碎片 display_geometry_check）",
            "note": ("新断面 / 原表面只是**显示着色**，不代表几何起伏、粗糙度或材质真值；"
                     "断口真实起伏需要 rough_shared_cut 后端（本机 FAILED）或 warped_partition"
                     "（PENDING）/ fracture_modes（MISSING），未实现的部分不伪造。"),
        },
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
        sys.stdout.write(RESULT_MARKER
                         + json.dumps(_jsonable(result, max_depth=RESULT_MAX_DEPTH),
                                      ensure_ascii=False) + "\n")
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
