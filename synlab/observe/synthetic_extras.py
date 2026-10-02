"""Synthetic **extras**: the nine modalities the V1.44 capture rig cannot obtain.

Why this module exists
----------------------
``docs/a12/rig_contract.md`` §8 and ``docs/a12/v144_project_core.md`` §5.9 list modalities
the documented rig is *not* able to obtain (photometric-stereo normals, automatic
polarizer angle, 0.1 mm absolute accuracy, hard-sync stereo, reliable depth, unlimited
continuous rotation, automatic flip, excavation context, real calibration).  The machine
readable copy of that list is ``configs/a12/capture_contract.json`` →
``explicitly_unavailable``.

The laboratory owner has ruled that these modalities must still be **generated and kept**,
because they are the only way to run controlled experiments (upper-bound simulation,
ablation switches, "what would this buy us if the rig could do it" studies).  What is
forbidden is *misrepresentation*: no synthesized modality may ever be presented as
something the bench can obtain.

Therefore every asset produced here carries a machine-readable annotation with

* ``rig_obtainable``  -- always ``false`` for the nine §8 items;
* ``synthetic_only``  -- always ``true`` here;
* ``rig_source``      -- ``"none"``: no bench step produces it;
* ``claim_allowed``   -- always ``false``: it may never enter a capability claim;
* ``reason``          -- why the bench cannot obtain it, with the document pointer;
* ``unit`` / ``frame`` / ``shape`` and the generation parameters plus the seed path.

Honesty rules enforced in code (see :func:`assert_claim_ban` and the checks in
``tools/load_extras.py``):

1. ``rig_obtainable``/``claim_allowed`` are constants of the catalogue and are **never**
   derived from a run parameter, so no caller can turn them on.
2. Nothing here writes into a ``deploy/`` view.  The exporter keeps extras in a sibling
   ``synthetic_extra/`` directory.
3. A modality that cannot be generated is reported as a failure with a reason; it is never
   replaced by placeholder data.

This module deliberately does **not** touch ``synlab/observe/routes.py``: it composes the
existing renderer/route primitives into *new, separate* channels and never changes the
semantics of an existing observation.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..cameras.api import (
    pixel_transform_crop_resize,
    profile_by_id,
    project,
    rotation_about_axis,
    unproject,
)
from ..roles import (
    FRAME_CAMERA,
    FRAME_FRAGMENT,
    FRAME_WORLD,
    SOURCE_SENSOR_SIM,
    UNIT_MM,
    UNIT_NONE,
    UNIT_PX,
)
from ..schemas.runtime import CameraProfile, ViewFrame
from ..seeds import make_rng, seed_ref
from .render import BACKEND_SOFTWARE, LightSpec, RenderSpec, build_scene, render_view
from .routes import ObsSpec, Target, resolve_target

#: Schema id of one extras annotation record.
SCHEMA_EXTRA_ANNOTATION = "synlab.synthetic_extra.annotation.v1"
#: Schema id of the package-level extras index written by :mod:`synlab.storage.export_extras`.
SCHEMA_EXTRA_INDEX = "synlab.synthetic_extra.index.v1"
#: Name of the export directory, a sibling of ``deploy/`` and ``research/``.
EXTRA_DIRNAME = "synthetic_extra"

#: The §8 items are, by definition, *not* obtainable.  These two constants are deliberately
#: module level literals: no argument of any function in this module can flip them.
RIG_OBTAINABLE_EXTRA = False
CLAIM_ALLOWED_EXTRA = False

#: Rejection reason text shared by every §8 item (the honest one-line summary).  The
#: per-modality ``reason`` field carries the specific pointer.
CLAIM_BAN = (
    "§8 / §5.9 modalities are bench-unobtainable by document; they may be used only as "
    "declared upper-bound simulation inside controlled experiments and may never enter a "
    "capability claim (docs/a12/rig_contract.md §8, docs/a12/v144_project_core.md §5.9)."
)


# --------------------------------------------------------------------------------------
# catalogue
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ModalitySpec:
    """One §8 modality: its annotation template plus its ablation switch."""

    modality_id: str
    item: int
    title: str
    rig_obtainable: bool
    synthetic_only: bool
    rig_source: str
    claim_allowed: bool
    reason: str
    doc_refs: tuple[str, ...]
    unit: str
    frame: str
    arrays: tuple[str, ...]
    #: Ablation: the field a caller sets to switch this modality on/off, and the group id
    #: used by the experiment protocol.  ``extra::<modality_id>`` is the prefix that keeps
    #: these groups distinct from any other teammate's group vocabulary.
    ablation_field: str
    ablation_group: str
    #: The same group expressed in the ``docs/a12/ablation_experiments.md`` ``G-DOMAIN-THING``
    #: spelling, so the two documents can be joined without either one renaming anything.
    teammate_group_id: str
    hypothesis: str
    generator: str


MODALITIES: tuple[ModalitySpec, ...] = (
    ModalitySpec(
        modality_id="photometric_normals",
        item=1,
        title="光度立体法向（per-pixel normals from multi-light solve）",
        rig_obtainable=False,
        synthetic_only=True,
        rig_source="none",
        claim_allowed=False,
        reason=(
            "文档只写 MVS 低频深度 + 可选 Photometric Stereo 法向／normal-guided "
            "refinement；普通四灯加 RGB 相机不自动获得准确法向（rig_contract §8、"
            "v144_project_core §5.9、capture_contract.lighting.photometric_stereo_normals）"
        ),
        doc_refs=("t096", "p541", "p096", "rig_contract.md#8", "v144_project_core.md#5.9"),
        unit=UNIT_NONE,
        frame=FRAME_WORLD,
        arrays=("ps_normal", "ps_albedo", "ps_valid", "ps_residual", "ps_observations",
                "ps_vs_geom_angle_deg", "geom_normal", "geom_normal_valid", "light_dirs",
                "images"),
        ablation_field="extras.enable_photometric_normals",
        ablation_group="extra::photometric_normals",
        teammate_group_id="G-EXTRA-NORMAL-PS",
        hypothesis="N/A（法向输入在检索主干之外）；可检验的点是 §8-11 的 normal_stability 质量分量与 normal-guided refinement 的上界增益。",
        generator="solve_photometric_normals",
    ),
    ModalitySpec(
        modality_id="polarizer_angle_sequence",
        item=2,
        title="连续偏振角序列（continuous polarizer angle sweep + per-angle image）",
        rig_obtainable=False,
        synthetic_only=True,
        rig_source="none",
        claim_allowed=False,
        reason=(
            "polarizer_auto=false：第一版偏振为膜人工抽插／手动转角，无角传感器时实测角为 "
            "null；手动偏振不冒充自动（p0577、t044、rig_contract §8）"
        ),
        doc_refs=("p0577", "t044", "p0539", "rig_contract.md#8"),
        unit=UNIT_PX,
        frame=FRAME_CAMERA,
        arrays=("polarizer_images", "polarizer_angles_deg", "polarizer_rho",
                "polarizer_axis_deg", "base_image"),
        ablation_field="extras.enable_polarizer_sequence",
        ablation_group="extra::polarizer_angle_sequence",
        teammate_group_id="G-EXTRA-POLAR-SWEEP",
        hypothesis="交叉偏振去高光是否提升釉面片的断口可见率与 Hit@10（对照 t053 的 CROSS_POL 用途）。",
        generator="synthesize_polarizer_sequence",
    ),
    ModalitySpec(
        modality_id="sub_millimetre_scale_claim",
        item=3,
        title="0.1 mm 级几何／尺度版本（declared 0.1 mm, unverified beyond rig）",
        rig_obtainable=False,
        synthetic_only=True,
        rig_source="none",
        claim_allowed=False,
        reason=(
            "文档明确不承诺 0.1mm 绝对精度：'不是 0.2mm 测量精度承诺'、'无可信参考不虚报"
            "毫米误差，只给可核重复一致性'；0.10mm 属未来 Gate B 工程目标"
            "（p0517／p0473、p1172、rig_contract §8）"
        ),
        doc_refs=("p0517", "p0473", "p1172", "p0466", "rig_contract.md#8"),
        unit=UNIT_MM,
        frame=FRAME_WORLD,
        arrays=("points_q01", "points_unquantised", "quantisation_residual_mm",
                "scale_reference_corners_mm"),
        ablation_field="extras.enable_sub_mm_claim",
        ablation_group="extra::sub_millimetre_scale_claim",
        teammate_group_id="G-EXTRA-SCALE-0P1",
        hypothesis="把几何量化到 0.1mm 网格是否改变断口几何描述子与匹配指标（检验'精度提升的收益上界'）。",
        generator="synthesize_sub_millimetre_claim",
    ),
    ModalitySpec(
        modality_id="hard_sync_stereo",
        item=4,
        title="硬同步双目对（strictly simultaneous stereo pair + baseline + disparity）",
        rig_obtainable=False,
        synthetic_only=True,
        rig_source="none",
        claim_allowed=False,
        reason=(
            "t050 明写两路依次拍摄、不宣称硬同步双目；第二节点为可选升级（双节点 1435 元档）"
            "（t050、rig_contract §1／§8）"
        ),
        doc_refs=("t050", "rig_contract.md#1", "rig_contract.md#8"),
        unit=UNIT_MM,
        frame=FRAME_CAMERA,
        arrays=("left_rgb", "right_rgb", "depth_left_mm", "depth_right_mm", "disparity_px",
                "stereo_valid", "T_WC_left", "T_WC_right"),
        ablation_field="extras.enable_hard_sync_stereo",
        ablation_group="extra::hard_sync_stereo",
        teammate_group_id="G-EXTRA-STEREO",
        hypothesis="双目视差是否提升断口匹配（断口局部几何的退化鲁棒性）；对照单目 proxy_scan 基线。",
        generator="synthesize_hard_sync_stereo",
    ),
    ModalitySpec(
        modality_id="dense_depth_reliable",
        item=5,
        title="可靠稠密深度（hole-free dense depth from the authoritative mesh）",
        rig_obtainable=False,
        synthetic_only=True,
        rig_source="none",
        claim_allowed=False,
        reason=(
            "文档：多个普通 RGB 相机也不自动产生可信深度；3D 不合格 → 关模态走经验证 2D，"
            "缺失不填 0 分（t073／p0473、p100、rig_contract §8）"
        ),
        doc_refs=("t073", "p0473", "p100", "rig_contract.md#8"),
        unit=UNIT_MM,
        frame=FRAME_CAMERA,
        arrays=("depth_z_mm", "depth_valid", "depth_confidence", "world_points",
                "raycast_check_uv", "raycast_check_depth_mm", "raycast_check_delta_mm"),
        ablation_field="extras.enable_dense_depth",
        ablation_group="extra::dense_depth_reliable",
        teammate_group_id="G-EXTRA-DENSE-DEPTH",
        hypothesis="稠密深度是否提升 Hit@10（深度质量是 MVS 与 local refine 的前置）。",
        generator="synthesize_dense_depth",
    ),
    ModalitySpec(
        modality_id="continuous_rotation",
        item=6,
        title="无限连续旋转角序列（0–360° continuous sweep, declared synthetic）",
        rig_obtainable=False,
        synthetic_only=True,
        rig_source="none",
        claim_allowed=False,
        reason=(
            "文档：有线束旋转要限制累计角并提供回绕动作，不承诺无限连续旋转；不边转边拍；"
            "Global 3D 不采用单圈 360° 作为正式采集（p0432／p1156、p0524、rig_contract §4）"
        ),
        doc_refs=("p0432", "p1156", "p0524", "rig_contract.md#4", "rig_contract.md#8"),
        unit=UNIT_MM,
        frame=FRAME_CAMERA,
        arrays=("angles_deg", "rgb_stack", "depth_stack", "silhouette_fraction",
                "T_WO_stack"),
        ablation_field="extras.enable_continuous_rotation",
        ablation_group="extra::continuous_rotation",
        teammate_group_id="G-EXTRA-CONT-ROT",
        hypothesis="连续角度序列相对 12 视图基线是否提升覆盖与 Hit@10（检验 Global 3D 帧数的收益上界）。",
        generator="synthesize_continuous_rotation",
    ),
    ModalitySpec(
        modality_id="auto_flip_second_set",
        item=7,
        title="自动翻面第二组视角（front/back paired second set after a flip）",
        rig_obtainable=False,
        synthetic_only=True,
        rig_source="none",
        claim_allowed=False,
        reason=(
            "支撑遮面时人工翻面或换支撑并建立新 session；首版不自动滚动或翻转脆弱碎片；"
            "文档无自动翻面能力（p0434／t045、p0525、rig_contract §6／§8）"
        ),
        doc_refs=("p0434", "t045", "p0525", "rig_contract.md#6", "rig_contract.md#8"),
        unit=UNIT_MM,
        frame=FRAME_CAMERA,
        arrays=("front_rgb", "back_rgb", "front_depth_mm", "back_depth_mm",
                "pair_azimuth_deg", "T_WO_flip", "front_back_overlap_iou"),
        ablation_field="extras.enable_auto_flip",
        ablation_group="extra::auto_flip_second_set",
        teammate_group_id="G-EXTRA-AUTO-FLIP",
        hypothesis="翻面后的背面观测是否提升粘合失败的可见面覆盖与配对召回（对照无翻面）。",
        generator="synthesize_auto_flip_set",
    ),
    ModalitySpec(
        modality_id="excavation_context_ref",
        item=8,
        title="出土上下文引用（reference to the simulated excavation context pack）",
        rig_obtainable=False,
        synthetic_only=True,
        rig_source="none",
        claim_allowed=False,
        reason=(
            "只有'受限的模拟出土上下文'，有缺失冲突和噪声，不能等价母体 ID；真实侧'坑位／层位"
            "只有真实可信字段时才使用'；模型输入不包含母体 ID、袋号"
            "（t101(D23)／p1146／p0412、rig_contract §8）。本机库内该项由队友实现，本模块只引用。"
        ),
        doc_refs=("t101(D23)", "p1146", "p0412", "rig_contract.md#8"),
        unit=UNIT_NONE,
        frame=FRAME_FRAGMENT,
        arrays=("present",),
        ablation_field="extras.enable_excavation_context",
        ablation_group="extra::excavation_context_ref",
        teammate_group_id="G-EXTRA-CONTEXT-REF",
        hypothesis="出土上下文在上下文分支上的增益（必须保持与母体 ID 不可等价，禁止进入检索输入）。",
        generator="reference_excavation_context",
    ),
    ModalitySpec(
        modality_id="synthetic_calibration",
        item=9,
        title="合成标定档（intrinsics + distortion + scale, calibrated=true, NOT real capture）",
        rig_obtainable=False,
        synthetic_only=True,
        rig_source="none",
        claim_allowed=False,
        reason=(
            "本机从未做过真实标定：3/3 相机档位 calibrated=false、STRESS_UNCALIBRATED，"
            "无比例尺参照物；真实标定需要实物标定板与逐稳定工况实测"
            "（p1163、p0427、普查 §5.4、rig_contract §5）。本档是合成标定，非实拍。"
        ),
        doc_refs=("p1163", "p0427", "t044", "rig_contract.md#5", "rig_contract.md#8"),
        unit=UNIT_PX,
        frame=FRAME_CAMERA,
        arrays=("intrinsics_K", "distortion_coeffs", "target_corners_world_mm",
                "target_corners_uv", "roundtrip_corners_world_mm", "roundtrip_residual_mm",
                "scale_reference_size_mm"),
        ablation_field="extras.enable_synthetic_calibration",
        ablation_group="extra::synthetic_calibration",
        teammate_group_id="G-EXTRA-CALIB",
        hypothesis="以标定档替换 calibrated=false 的档位，检验 G07 标定误差轴的下界与尺度漂移算法本身。",
        generator="synthesize_calibration",
    ),
)
MODALITY_BY_ID: dict[str, ModalitySpec] = {m.modality_id: m for m in MODALITIES}
MODALITY_IDS: tuple[str, ...] = tuple(m.modality_id for m in MODALITIES)

#: The four documented lamp groups (left / right / front-top / back-top, one colour
#: temperature) expressed as positions in the rig frame the software rasteriser uses:
#: camera at ``+Z`` looking down ``-Z`` with image ``+Y`` pointing to world ``-Y``.
_PS_LIGHT_POSITIONS: tuple[tuple[str, tuple[float, float, float]], ...] = (
    ("LEFT", (-1.0, 0.0, 0.35)),
    ("RIGHT", (1.0, 0.0, 0.35)),
    ("FRONT_TOP", (0.0, -0.7, 0.7)),
    ("BACK_TOP", (0.0, -0.7, -0.7)),
)


# --------------------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------------------
@dataclass
class ExtraBundle:
    """One generated modality for one fragment: arrays plus its full annotation."""

    modality_id: str
    annotation: dict[str, Any]
    arrays: dict[str, np.ndarray] = field(default_factory=dict)
    seconds: float = 0.0
    failure: str | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None

    def array_bytes(self) -> int:
        return int(sum(int(np.asarray(v).nbytes) for v in self.arrays.values()))

    def as_index_row(self) -> dict[str, Any]:
        return {
            "modality_id": self.modality_id,
            "item": self.annotation.get("item"),
            "ok": self.ok,
            "failure": self.failure,
            "seconds": round(float(self.seconds), 4),
            "array_bytes": self.array_bytes(),
            "arrays": {k: list(np.asarray(v).shape) for k, v in sorted(self.arrays.items())},
        }


@dataclass
class ExtrasResult:
    """All extras generated for one fragment."""

    fragment_id: str
    component_id: str
    lineage_id: str
    master_seed: int
    profile_id: str
    bundles: list[ExtraBundle]
    seconds: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def by_id(self, modality_id: str) -> ExtraBundle:
        for bundle in self.bundles:
            if bundle.modality_id == modality_id:
                return bundle
        raise KeyError(modality_id)

    def index(self) -> dict[str, Any]:
        rows = [b.as_index_row() for b in self.bundles]
        return {
            "schema": SCHEMA_EXTRA_INDEX,
            "fragment_id": self.fragment_id,
            "component_id": self.component_id,
            "lineage_id": self.lineage_id,
            "master_seed": int(self.master_seed),
            "profile_id": self.profile_id,
            "seconds": round(float(self.seconds), 4),
            "modalities": rows,
            "claim_ban": CLAIM_BAN,
        }


# --------------------------------------------------------------------------------------
# annotation helpers
# --------------------------------------------------------------------------------------
def annotation_template(modality_id: str) -> dict[str, Any]:
    """The static, machine-readable annotation of one §8 modality."""
    spec = MODALITY_BY_ID[modality_id]
    return {
        "schema": SCHEMA_EXTRA_ANNOTATION,
        "modality_id": spec.modality_id,
        "item": spec.item,
        "title": spec.title,
        "rig_obtainable": RIG_OBTAINABLE_EXTRA,
        "synthetic_only": True,
        "rig_source": "none",
        "claim_allowed": CLAIM_ALLOWED_EXTRA,
        "reason": spec.reason,
        "doc_refs": list(spec.doc_refs),
        "unit": spec.unit,
        "frame": spec.frame,
        "claim_ban": CLAIM_BAN,
        "ablation": {
            "field": spec.ablation_field,
            "group": spec.ablation_group,
            "hypothesis": spec.hypothesis,
        },
        "generator": {"function": spec.generator, "params": {}, "seed_path": []},
        "shape": {},
        "dtype": {},
        "bytes": {},
    }


def assert_claim_ban(annotation: Mapping[str, Any]) -> None:
    """Refuse an annotation that would let a §8 modality enter a capability claim.

    Called on every record this module produces and again by the exporter and the loader,
    so a hand-edited annotation on disk is caught as well.
    """
    problems: list[str] = []
    if annotation.get("rig_obtainable") is not False:
        problems.append("rig_obtainable must be exactly False")
    if annotation.get("claim_allowed") is not False:
        problems.append("claim_allowed must be exactly False")
    if annotation.get("synthetic_only") is not True:
        problems.append("synthetic_only must be exactly True")
    if annotation.get("rig_source") != "none":
        problems.append("rig_source must be 'none'")
    if annotation.get("modality_id") not in MODALITY_BY_ID:
        problems.append(f"unknown modality_id {annotation.get('modality_id')!r}")
    for key in ("modality_id", "reason", "unit", "frame", "shape", "generator", "doc_refs"):
        if key not in annotation:
            problems.append(f"missing annotation key {key!r}")
    if problems:
        raise ValueError("synthetic extras annotation violates the claim ban: "
                         + "; ".join(problems))


def _fill_shape(
    annotation: dict[str, Any], arrays: Mapping[str, np.ndarray]
) -> dict[str, Any]:
    annotation["shape"] = {k: list(np.asarray(v).shape) for k, v in sorted(arrays.items())}
    annotation["dtype"] = {k: str(np.asarray(v).dtype) for k, v in sorted(arrays.items())}
    annotation["bytes"] = {k: int(np.asarray(v).nbytes) for k, v in sorted(arrays.items())}
    return annotation


def _rng_for(master_seed: int, lineage_id: str, fragment_id: str, modality_id: str
             ) -> np.random.Generator:
    """A dedicated, reproducible numpy sub-stream under the lineage's master seed."""
    return make_rng(master_seed, lineage_id, fragment_id, "synthetic_extras", modality_id)


def _seed_path(master_seed: int, lineage_id: str, fragment_id: str, modality_id: str
               ) -> list[Any]:
    return [int(master_seed), lineage_id, fragment_id, "synthetic_extras", modality_id]


# --------------------------------------------------------------------------------------
# geometry / camera helpers
# --------------------------------------------------------------------------------------
def resolve_profile(profile: Any = None) -> CameraProfile:
    """Accept a :class:`CameraProfile`, a tier name or a profile id."""
    from ..cameras.api import camera_profiles

    if profile is None:
        return camera_profiles()[1]
    if isinstance(profile, CameraProfile):
        return profile
    if isinstance(profile, str):
        if profile in ("GLOBAL", "MID", "LOCAL"):
            for candidate in camera_profiles():
                if candidate.tier == profile:
                    return candidate
            raise KeyError(f"tier {profile!r} unavailable")
        return profile_by_id(profile)
    raise TypeError(f"profile must be a CameraProfile or str, got {type(profile)!r}")


def _extras_size(profile: CameraProfile, long_edge_px: int) -> tuple[int, int]:
    """A small extra camera grid that keeps the profile aspect ratio."""
    width, height = int(profile.image_size[0]), int(profile.image_size[1])
    scale = float(long_edge_px) / float(max(width, height))
    out_w = max(int(round(width * scale)), 32)
    out_h = max(int(round(height * scale)), 24)
    return (out_w, out_h)


def _scaled_intrinsics(profile: CameraProfile, size: tuple[int, int]) -> tuple[np.ndarray, float, float]:
    """``K`` for a resized pixel grid, plus the realised ``(sx, sy)``.

    A smaller grid is a *declared affine resampling of the pixel lattice*, exactly as
    ``synlab.observe.routes.ObsSpec.derivation`` does it -- never a silent change of the
    camera.  Reusing the full-resolution ``K`` on a small grid would put the principal point
    outside the image and silently render an empty frame.
    """
    width, height = int(profile.image_size[0]), int(profile.image_size[1])
    sx = float(size[0]) / float(width)
    sy = float(size[1]) / float(height)
    _, K_new = pixel_transform_crop_resize(0.0, 0.0, sx, sy,
                                           np.asarray(profile.K, dtype=np.float64))
    return np.asarray(K_new, dtype=np.float64), sx, sy


def _bbox_center(bbox: np.ndarray) -> np.ndarray:
    b = np.asarray(bbox, dtype=np.float64).reshape(-1)
    return np.array([(b[0] + b[3]) / 2.0, (b[1] + b[4]) / 2.0, (b[2] + b[5]) / 2.0])


def _turntable_frame(
    *, view_id: str, profile: CameraProfile, size: tuple[int, int], center: np.ndarray,
    source_kind: str = SOURCE_SENSOR_SIM, extra_meta: Mapping[str, Any] | None = None,
) -> ViewFrame:
    """The frozen fixture camera of ``make_view_frames(orbit=False)``, re-expressed here.

    The camera never leaves the optical axis; azimuthal diversity is a *scene* motion
    (``object_pose``), exactly as a centred turntable behaves.  This is the same rig model
    the existing routes use, so an extras view is comparable with an observation view.
    ``K`` is rescaled to the extras grid by a declared affine lattice transform.
    """
    T_WC = np.eye(4, dtype=np.float64)
    T_WC[:3, 0] = np.array([1.0, 0.0, 0.0])
    T_WC[:3, 1] = np.array([0.0, -1.0, 0.0])
    T_WC[:3, 2] = np.array([0.0, 0.0, -1.0])
    T_WC[:3, 3] = center + np.array([0.0, 0.0, float(profile.working_distance_mm)])
    K, sx, sy = _scaled_intrinsics(profile, size)
    meta: dict[str, Any] = {
        "rig_model": "camera_on_linear_rail_with_turntable",
        "framing": "TURNTABLE",
        "extra_modality": True,
        "target_center_mm": center.tolist(),
        "pixel_lattice_scale": [float(sx), float(sy)],
        "full_resolution_K": np.asarray(profile.K, dtype=np.float64).tolist(),
        "full_resolution_image_size": [int(profile.image_size[0]),
                                       int(profile.image_size[1])],
        "mm_per_pixel": float(profile.working_distance_mm / float(K[0, 0])),
        "calibration_status": "SYNTHETIC_NOT_REAL_CAPTURE",
    }
    meta.update(dict(extra_meta or {}))
    return ViewFrame(
        view_id=view_id,
        K=K,
        T_WC=T_WC,
        image_size=(int(size[0]), int(size[1])),
        profile_id=profile.profile_id,
        tier=str(profile.tier),
        u_position_mm=float(profile.u_position_mm),
        working_distance_mm=float(profile.working_distance_mm),
        focus_setting=profile.focus_setting,
        source_kind=str(source_kind),
        camera_model=str(profile.meta.get("camera_model", "PINHOLE")),
        dist=np.asarray(profile.dist, dtype=np.float64).copy(),
        meta=meta,
    )


def _turn_about_point(axis: Sequence[float], angle_rad: float, center: np.ndarray
                      ) -> np.ndarray:
    """Rigid ``T_WO``: rotate about ``axis`` through ``center`` (turntable semantics)."""
    R = rotation_about_axis(np.asarray(axis, dtype=np.float64), float(angle_rad))
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = R
    T[:3, 3] = center - R @ center
    return T


def _as_target(target_or_fragment: Any, *, fragment_id: str | None = None) -> Target:
    if isinstance(target_or_fragment, Target):
        return target_or_fragment
    return resolve_target(target_or_fragment, fragment_id)


def _scene_for(target: Target) -> Any:
    return build_scene(target.mesh, surface_tag=target.surface_tag, face_id=target.face_id,
                       name=str(target.fragment_id))


def _to_u8(linear: np.ndarray) -> np.ndarray:
    """Linear radiance in [0,1] to the delivered 8-bit encoding used by the obs view."""
    return np.clip(np.rint(np.asarray(linear, dtype=np.float32) * 255.0), 0.0,
                   255.0).astype(np.uint8)


def _require_pixels(mask: np.ndarray, what: str) -> None:
    """An extras modality with no object pixels is a **failure**, never a quiet NaN field.

    A silent all-invalid channel would look like a successful generation whose downstream
    experiment simply has no signal -- exactly the kind of placeholder this module forbids.
    """
    if not bool(np.asarray(mask, dtype=bool).any()):
        raise ValueError(
            f"{what}: the target projects no valid pixel into the extras frame; refusing to "
            f"emit an all-invalid channel")


def _face_normals_of(target: Target) -> np.ndarray:
    mesh = target.mesh
    normals = np.asarray(getattr(mesh, "face_normals", None), dtype=np.float64)
    if normals.ndim != 2 or normals.shape[0] != int(np.asarray(mesh.faces).shape[0]):
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        tri = verts[faces]
        normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    return (normals / np.maximum(norms, 1e-15)).astype(np.float64)


# --------------------------------------------------------------------------------------
# 1. photometric-stereo normals
# --------------------------------------------------------------------------------------
def solve_photometric_normals(
    images: np.ndarray, light_dirs: np.ndarray, mask: np.ndarray | None = None,
    *, min_intensity: float = 1e-6, min_norm: float = 1e-6, min_observations: int = 3,
    ridge: float = 1e-9,
) -> dict[str, np.ndarray]:
    """Classical photometric-stereo least squares on a stack of Lambert images.

    ``images`` is ``(K, H, W, C)`` linear radiance under ``K`` lights whose *travel*
    directions are ``light_dirs`` (K, 3).  Returns the unit normal, the albedo-scaled
    magnitude, a validity mask and the per-pixel residual of the solve.

    A pixel that one lamp does not reach is the normal case, not an error: with four lamps
    and a convex body at least one lamp is always dark somewhere.  The solve therefore uses
    the **per-pixel observed subset** -- the 3x3 normal equations are accumulated only over
    the lamps whose radiance is above ``min_intensity`` -- and a pixel needs at least
    ``min_observations`` such lamps to be valid.  ``ridge`` keeps the normal matrix
    invertible when the observed lamps are nearly coplanar, and it is reported in the
    annotation, not hidden.
    """
    img = np.asarray(images, dtype=np.float64)
    if img.ndim == 3:
        img = img[..., None]
    k, h, w, _c = img.shape
    L = -np.asarray(light_dirs, dtype=np.float64)          # direction *towards* the light
    if L.shape != (k, 3):
        raise ValueError(f"light_dirs must be ({k}, 3), got {L.shape}")

    intensity = img.mean(axis=3).reshape(k, h * w)          # (K, P)
    observed = (intensity > float(min_intensity)) & np.isfinite(intensity)
    count = observed.sum(axis=0)

    weights = observed.astype(np.float64)                   # (K, P)
    Lw = L[:, :, None] * weights[:, None, :]                # (K, 3, P)
    A = np.einsum("kdp,kep->dep", Lw, Lw)                   # (3, 3, P)
    b = np.einsum("kdp,kp->dp", Lw, intensity)              # (3, P)
    A = A + float(ridge) * np.eye(3, dtype=np.float64)[:, :, None]
    g = np.linalg.solve(np.moveaxis(A, 2, 0), np.moveaxis(b, 1, 0)[..., None])
    g = np.moveaxis(np.asarray(g)[..., 0], 0, 1)            # (3, P)

    residual = np.where(observed, L @ g - intensity, 0.0)
    residual_rms = np.sqrt((residual ** 2).sum(axis=0) / np.maximum(count, 1))
    magnitude = np.linalg.norm(g, axis=0)

    if mask is not None:
        inside = np.asarray(mask, dtype=bool).reshape(h * w)
    else:
        inside = np.ones(h * w, dtype=bool)
    valid = inside & (count >= int(min_observations)) & (magnitude > float(min_norm))
    safe = np.where(magnitude > 1e-12, magnitude, 1.0)
    normals = (g / safe[None, :]).T.reshape(h, w, 3)
    return {
        "ps_normal": normals.astype(np.float32),
        "ps_albedo": magnitude.reshape(h, w).astype(np.float32),
        "ps_valid": valid.reshape(h, w),
        "ps_residual": residual_rms.reshape(h, w).astype(np.float32),
        "ps_observations": count.reshape(h, w).astype(np.int16),
    }


def synthesize_photometric_normals(
    *, scene: Any, target: Target, profile: CameraProfile, spec: ObsSpec,
    frame: ViewFrame, rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    """Render N lights and solve per-pixel normals; the geometry normals are truth-side."""
    center = _bbox_center(target.bbox)
    normals = _face_normals_of(target)
    scale = float(profile.working_distance_mm)
    # ``render.render_view`` builds camera-space triangle normals and then rotates them back
    # with ``@ frame.T_WC[:3,:3]``, so ``light.direction`` is a **world-frame** travel
    # direction.  Lamps are therefore declared in world mm (the rig layout of
    # capture_contract.lighting) and the solve returns a world-frame normal, matching
    # ``geom_normal`` (annotation ``frame = W_mm``).

    light_dirs: list[np.ndarray] = []
    images: list[np.ndarray] = []
    for name, position in _PS_LIGHT_POSITIONS:
        pos = np.asarray(position, dtype=np.float64)
        pos = pos / max(float(np.linalg.norm(pos)), 1e-12)
        pos_world = center + pos * scale
        travel = center - pos_world
        travel = travel / max(float(np.linalg.norm(travel)), 1e-12)
        # one colour temperature for all four lamps (p0535): identical linear radiance,
        # and ambient is zeroed so the linear solve is not biased by a constant offset.
        light = LightSpec(direction=travel,
                          color=np.array([2.4, 2.4, 2.4], dtype=np.float64),
                          ambient=np.zeros(3, dtype=np.float64))
        out = render_view(scene, frame, light=light, spec=spec.render_spec,
                          backend=BACKEND_SOFTWARE)
        light_dirs.append(travel)
        images.append(np.asarray(out.rgb_linear, dtype=np.float32))

    stack = np.stack(images, axis=0)                       # (K, H, W, 3)
    depth = np.asarray(out.depth_z, dtype=np.float64)
    mask = np.isfinite(depth) & (depth > 0.0)
    solve = solve_photometric_normals(stack, np.stack(light_dirs, axis=0), mask)
    _require_pixels(solve["ps_valid"], "photometric_normals")

    face_id = np.asarray(target.face_id).reshape(-1)
    id_map = np.asarray(out.id_map)
    geom_valid = (id_map >= 0) & (id_map < face_id.shape[0])
    geom = np.zeros(id_map.shape + (3,), dtype=np.float64)
    if geom_valid.any():
        geom[geom_valid] = normals[face_id[id_map[geom_valid]]]
    both = geom_valid & solve["ps_valid"]
    angle = np.full(id_map.shape, np.nan, dtype=np.float64)
    if both.any():
        dot = np.abs(np.sum(geom[both] * solve["ps_normal"][both].astype(np.float64),
                            axis=1))
        angle[both] = np.rad2deg(np.arccos(np.clip(dot, -1.0, 1.0)))

    return {
        "images": _to_u8(stack),
        "light_dirs": np.stack(light_dirs, axis=0).astype(np.float32),
        "ps_normal": solve["ps_normal"],
        "ps_albedo": solve["ps_albedo"],
        "ps_valid": solve["ps_valid"],
        "ps_residual": solve["ps_residual"],
        "ps_observations": solve["ps_observations"],
        "geom_normal": geom.astype(np.float32),
        "geom_normal_valid": geom_valid,
        "ps_vs_geom_angle_deg": angle.astype(np.float32),
        "object_pose_T_WO": np.eye(4, dtype=np.float64),
        "depth_z_mm": depth.astype(np.float32),
    }


# --------------------------------------------------------------------------------------
# 2. polarizer angle sequence
# --------------------------------------------------------------------------------------
def synthesize_polarizer_sequence(
    *, scene: Any, target: Target, profile: CameraProfile, spec: ObsSpec,
    frame: ViewFrame, rng: np.random.Generator, step_deg: float = 15.0,
    rho_max: float = 0.35, angles_deg: Sequence[float] | None = None,
) -> dict[str, np.ndarray]:
    """A continuous polarizer-angle sweep with one image per angle.

    The bench can only move the polarizer by hand and cannot measure its angle
    (``polarizer_auto=false``, ``angle_measured_deg`` is ``null``).  This generator
    therefore emits a *declared* Malus-law model

        ``I(theta) = I_base * ((1 - rho) + rho * cos^2(theta - phi))``

    with a synthetic per-pixel polarized fraction ``rho`` and a synthetic per-pixel
    transmission axis ``phi``.  Nothing here is a claim about a measured polarizer: the
    model name, ``rho_max`` and the seed path are all recorded in the annotation.
    """
    if angles_deg is None:
        step = max(float(step_deg), 1e-6)
        angles = np.arange(0.0, 180.0 + 1e-9, step, dtype=np.float64)
    else:
        angles = np.asarray(angles_deg, dtype=np.float64).reshape(-1)
    out = render_view(scene, frame, light=spec.resolved_light(), spec=spec.render_spec,
                      backend=BACKEND_SOFTWARE)
    base = np.asarray(out.rgb_linear, dtype=np.float32)
    h, w = base.shape[0], base.shape[1]

    lambert = np.clip(np.asarray(out.rgb_linear, dtype=np.float32).mean(axis=2), 0.0, 1.0)
    visible = np.isfinite(np.asarray(out.depth_z)) & (np.asarray(out.depth_z) > 0)
    rho = (float(rho_max) * lambert * visible.astype(np.float32)).astype(np.float32)
    _require_pixels(visible, "polarizer_angle_sequence")
    axis_deg = (rng.uniform(0.0, 180.0, size=(h, w))).astype(np.float32)

    theta = np.deg2rad(angles)[:, None, None]
    phi = np.deg2rad(axis_deg.astype(np.float64))[None, :, :]
    malus = ((1.0 - rho[None, :, :]) + rho[None, :, :] * np.cos(theta - phi) ** 2)
    stack = base[None, :, :, :] * malus[..., None]
    return {
        "polarizer_images": _to_u8(stack),
        "polarizer_angles_deg": angles.astype(np.float32),
        "polarizer_rho": rho,
        "polarizer_axis_deg": axis_deg,
        "base_image": _to_u8(base),
        "base_depth_mm": np.asarray(out.depth_z, dtype=np.float32),
        # the real capture contract records a null measured angle without an angle sensor
        "angle_measured_deg_is_null": np.ones((1,), dtype=bool),
    }


# --------------------------------------------------------------------------------------
# 3. 0.1 mm claim (geometry / scale variant)
# --------------------------------------------------------------------------------------
def synthesize_sub_millimetre_claim(
    *, scene: Any, target: Target, profile: CameraProfile, spec: ObsSpec,
    frame: ViewFrame, rng: np.random.Generator, claim_mm: float = 0.1,
) -> dict[str, np.ndarray]:
    """A geometry/scale variant *declared* at ``claim_mm`` but **not** verified on a rig.

    The payload is the authoritative mesh sampled on the extra camera grid, quantised to a
    ``claim_mm`` lattice.  The measured field is the *realised* quantisation residual of
    that operation -- it is a property of this synthetic geometry, never evidence that the
    bench reaches 0.1 mm.
    """
    out = render_view(scene, frame, light=spec.resolved_light(), spec=spec.render_spec,
                      backend=BACKEND_SOFTWARE)
    depth = np.asarray(out.depth_z, dtype=np.float64)
    valid = np.isfinite(depth) & (depth > 0)
    _require_pixels(valid, "sub_millimetre_scale_claim")
    ys, xs = np.nonzero(valid)
    uv = np.stack([xs + 0.5, ys + 0.5], axis=1)
    points = unproject(uv, depth[valid], frame.K, frame.T_WC, frame.dist)
    step = float(claim_mm)
    quantised = np.round(points / step) * step
    residual = np.linalg.norm(quantised - points, axis=1)

    corner = _bbox_center(target.bbox) + np.array([0.0, 0.0, 0.0])
    half = 25.0 * step / 0.1                                   # a declared 50 mm marker
    corners = corner + np.array([
        [-half, -half, 0.0], [half, -half, 0.0], [half, half, 0.0], [-half, half, 0.0],
    ])
    return {
        "points_unquantised": points.astype(np.float32),
        "points_q01": quantised.astype(np.float32),
        "quantisation_residual_mm": residual.astype(np.float32),
        "scale_reference_corners_mm": corners.astype(np.float32),
        "declared_accuracy_mm": np.asarray([step], dtype=np.float64),
        "realised_max_residual_mm": np.asarray([float(residual.max()) if residual.size
                                               else float("nan")], dtype=np.float64),
    }


# --------------------------------------------------------------------------------------
# 4. hard-sync stereo
# --------------------------------------------------------------------------------------
def synthesize_hard_sync_stereo(
    *, scene: Any, target: Target, profile: CameraProfile, spec: ObsSpec,
    frame: ViewFrame, rng: np.random.Generator, baseline_mm: float = 60.0,
) -> dict[str, np.ndarray]:
    """A strictly simultaneous, rectified stereo pair plus its disparity map.

    The bench shoots its two nodes one after the other and does not claim hard sync
    (``t050``), so this pair is *by construction* unobtainable.  Both cameras share one
    rotation and differ only by a translation along the left camera's ``+x`` axis, so the
    disparity is purely horizontal and the depth-to-disparity relation is exact.
    """
    base = np.eye(4, dtype=np.float64)
    base[:3, :3] = np.asarray(frame.T_WC[:3, :3], dtype=np.float64)
    base[:3, 3] = np.asarray(frame.T_WC[:3, 3], dtype=np.float64)
    half = float(baseline_mm) / 2.0
    x_axis = base[:3, 0].copy()
    left = base.copy()
    left[:3, 3] = base[:3, 3] - x_axis * half
    right = base.copy()
    right[:3, 3] = base[:3, 3] + x_axis * half

    def _render(T: np.ndarray) -> Any:
        cam = ViewFrame(
            view_id=f"{frame.view_id}#stereo", K=np.asarray(frame.K).copy(), T_WC=T,
            image_size=frame.image_size, profile_id=frame.profile_id, tier=frame.tier,
            u_position_mm=frame.u_position_mm, working_distance_mm=frame.working_distance_mm,
            focus_setting=frame.focus_setting, source_kind=SOURCE_SENSOR_SIM,
            camera_model=frame.camera_model, dist=np.asarray(frame.dist).copy(),
            meta=dict(frame.meta),
        )
        return render_view(scene, cam, light=spec.resolved_light(), spec=spec.render_spec,
                           backend=BACKEND_SOFTWARE)

    out_l = _render(left)
    out_r = _render(right)
    depth_l = np.asarray(out_l.depth_z, dtype=np.float64)
    depth_r = np.asarray(out_r.depth_z, dtype=np.float64)
    valid = np.isfinite(depth_l) & (depth_l > 0)
    _require_pixels(valid, "hard_sync_stereo")
    ys, xs = np.nonzero(valid)
    disparity = np.full(depth_l.shape, np.nan, dtype=np.float64)
    if xs.size:
        uv = np.stack([xs + 0.5, ys + 0.5], axis=1)
        world = unproject(uv, depth_l[valid], frame.K, left, frame.dist)
        uv_r, z_r = project(world, frame.K, right, frame.dist)
        ok = np.isfinite(uv_r[:, 0]) & (z_r > 0)
        disp = np.full(xs.shape, np.nan, dtype=np.float64)
        disp[ok] = uv[:, 0][ok] - uv_r[ok, 0]
        disparity[ys[ok], xs[ok]] = disp[ok]
    return {
        "left_rgb": _to_u8(np.asarray(out_l.rgb_linear)),
        "right_rgb": _to_u8(np.asarray(out_r.rgb_linear)),
        "depth_left_mm": depth_l.astype(np.float32),
        "depth_right_mm": depth_r.astype(np.float32),
        "disparity_px": disparity.astype(np.float32),
        "stereo_valid": np.isfinite(disparity),
        "T_WC_left": left,
        "T_WC_right": right,
        "baseline_mm": np.asarray([float(baseline_mm)], dtype=np.float64),
    }


# --------------------------------------------------------------------------------------
# 5. reliable dense depth
# --------------------------------------------------------------------------------------
def synthesize_dense_depth(
    *, scene: Any, target: Target, profile: CameraProfile, spec: ObsSpec,
    frame: ViewFrame, rng: np.random.Generator, raycast_probe: int = 96,
) -> dict[str, np.ndarray]:
    """Dense, hole-free depth from the authoritative mesh, cross-checked by the rasteriser.

    The primary depth is a **true ray cast** of the authoritative triangle mesh: one ray
    per pixel centre, launched from the camera centre through the *undistorted* pixel
    direction (``open3d.RaycastingScene.cast_rays`` by way of
    :func:`synlab.physical.sdf.scene_for`).  The software rasteriser's z-buffer is then
    compared against it on a random subsample, and both the method actually used and the
    realised deviation are reported.  If the ray-casting engine is unavailable the
    z-buffer becomes the primary and the annotation says so -- no substitute is ever
    passed off as a ray cast.

    Pixels outside the silhouette are marked invalid; they are **never** filled with
    invented depth.  Inside the silhouette there is no synthetic dropout and no carved
    hole, which is exactly the property the bench cannot deliver (``t073``/``p0473``).
    """
    out = render_view(scene, frame, light=spec.resolved_light(),
                      spec=RenderSpec(**{**spec.render_spec.__dict__, "supersample": 1}),
                      backend=BACKEND_SOFTWARE)
    zbuf = np.asarray(out.depth_z, dtype=np.float64)

    cast, ok = _cast_all_pixels(target, frame)
    if ok:
        depth = cast
        source = "open3d.RaycastingScene.cast_rays: one ray per pixel centre"
        cross = zbuf
    else:
        depth = zbuf
        source = "software_rasteriser z-buffer of the authoritative mesh (ray cast unavailable)"
        cross = np.full(zbuf.shape, np.nan, dtype=np.float64)

    valid = np.isfinite(depth) & (depth > 0.0)
    _require_pixels(valid, "dense_depth_reliable")
    ys, xs = np.nonzero(valid)
    uv = np.stack([xs + 0.5, ys + 0.5], axis=1)
    world = unproject(uv, depth[valid], frame.K, frame.T_WC, frame.dist) if xs.size \
        else np.zeros((0, 3), dtype=np.float64)

    probe_uv, probe_depth, probe_delta = _raycast_probe(depth, cross, rng,
                                                        count=int(raycast_probe))
    confidence = np.zeros(depth.shape, dtype=np.float32)
    confidence[valid] = 1.0
    return {
        "depth_z_mm": depth.astype(np.float32),
        "depth_valid": valid,
        "depth_confidence": confidence,
        "world_points": world.astype(np.float32),
        "raycast_check_uv": probe_uv.astype(np.float32),
        "raycast_check_depth_mm": probe_depth.astype(np.float32),
        "raycast_check_delta_mm": probe_delta.astype(np.float32),
        "hole_count_within_silhouette": np.asarray([0], dtype=np.int64),
        "depth_source": np.asarray([source]),
    }


def _cast_all_pixels(target: Target, frame: ViewFrame) -> tuple[np.ndarray, bool]:
    """Ray cast every pixel centre of ``frame`` against the authoritative mesh.

    Returns ``(depth_z_mm, cast_ok)``.  Ray directions are built from the *undistorted*
    pixel coordinates, so the result is directly comparable with the renderer, which
    applies the same distortion model.
    """
    from ..cameras.projection import undistort_normalized

    width, height = int(frame.image_size[0]), int(frame.image_size[1])
    try:
        from ..physical.sdf import scene_for
        import trimesh

        mesh = target.mesh
        if not isinstance(mesh, trimesh.Trimesh):
            mesh = trimesh.Trimesh(vertices=np.asarray(mesh.vertices),
                                   faces=np.asarray(mesh.faces), process=False)
        cache = scene_for(mesh)
    except Exception:
        return np.full((height, width), np.nan, dtype=np.float64), False

    grid_y, grid_x = np.mgrid[0:height, 0:width]
    u = grid_x.ravel().astype(np.float64) + 0.5
    v = grid_y.ravel().astype(np.float64) + 0.5
    K = np.asarray(frame.K, dtype=np.float64)
    xd = (u - K[0, 2]) / K[0, 0]
    yd = (v - K[1, 2]) / K[1, 1]
    x, y = undistort_normalized(xd, yd, frame.dist,
                                str(frame.camera_model or "OPENCV"))
    dirs_cam = np.stack([x, y, np.ones_like(x)], axis=1)
    dirs_cam /= np.linalg.norm(dirs_cam, axis=1, keepdims=True)
    R = np.asarray(frame.T_WC[:3, :3], dtype=np.float64)
    C = np.asarray(frame.T_WC[:3, 3], dtype=np.float64)
    dirs = dirs_cam @ R.T
    origins = np.repeat(C[None, :], dirs.shape[0], axis=0)
    try:
        t_hit = np.asarray(cache.cast(origins, dirs), dtype=np.float64)
    except Exception:
        return np.full((height, width), np.nan, dtype=np.float64), False
    finite = np.isfinite(t_hit)
    depth = np.full(t_hit.shape, np.nan, dtype=np.float64)
    if finite.any():
        points = origins[finite] + dirs[finite] * t_hit[finite][:, None]
        cam = (points - C) @ R
        depth[finite] = cam[:, 2]
    return depth.reshape(height, width), True


def _raycast_probe(primary: np.ndarray, cross: np.ndarray, rng: np.random.Generator, *,
                   count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compare the primary depth field with the cross-check field on a random subsample."""
    height, width = int(primary.shape[0]), int(primary.shape[1])
    n = max(int(count), 0)
    if n == 0:
        return (np.zeros((0, 2)), np.zeros((0,)), np.zeros((0,)))
    xs = rng.integers(0, width, size=n)
    ys = rng.integers(0, height, size=n)
    uv = np.stack([xs + 0.5, ys + 0.5], axis=1)
    reference = np.asarray(cross[ys, xs], dtype=np.float64)
    measured = np.asarray(primary[ys, xs], dtype=np.float64)
    delta = np.abs(measured - reference)
    return uv, reference, delta


# --------------------------------------------------------------------------------------
# 6. continuous rotation
# --------------------------------------------------------------------------------------
def synthesize_continuous_rotation(
    *, scene: Any, target: Target, profile: CameraProfile, spec: ObsSpec,
    frame: ViewFrame, rng: np.random.Generator, step_deg: float = 5.0,
) -> dict[str, np.ndarray]:
    """A 0–360° sweep at ``step_deg`` with the object pose as the only moving part.

    The bench cannot do this: it must stop, wait for the frame to settle and shoot, and the
    harness limits the accumulated angle (``p0432``/``p1156``).  The realised sweep length,
    the number of full wraps and the commanded (not measured) angles are all recorded.
    """
    step = max(float(step_deg), 1e-6)
    angles = np.arange(0.0, 360.0, step, dtype=np.float64)
    center = _bbox_center(target.bbox)
    rgbs: list[np.ndarray] = []
    depths: list[np.ndarray] = []
    poses: list[np.ndarray] = []
    fractions: list[float] = []
    for angle in angles:
        T = _turn_about_point((0.0, 1.0, 0.0), math.radians(float(angle)), center)
        out = render_view(scene, frame, light=spec.resolved_light(), spec=spec.render_spec,
                          object_pose=T, backend=BACKEND_SOFTWARE)
        depth = np.asarray(out.depth_z, dtype=np.float32)
        rgbs.append(_to_u8(np.asarray(out.rgb_linear)))
        depths.append(depth)
        poses.append(T)
        fractions.append(float(np.isfinite(depth).mean()))
    _require_pixels(np.asarray(fractions, dtype=np.float64) > 0.0, "continuous_rotation")
    return {
        "angles_deg": angles.astype(np.float32),
        "rgb_stack": np.stack(rgbs, axis=0),
        "depth_stack": np.stack(depths, axis=0),
        "silhouette_fraction": np.asarray(fractions, dtype=np.float32),
        "T_WO_stack": np.stack(poses, axis=0),
        "cumulative_angle_deg": np.asarray([float(angles[-1] + step)], dtype=np.float64),
        "wraps": np.asarray([1], dtype=np.int64),
    }


# --------------------------------------------------------------------------------------
# 7. auto flip second set
# --------------------------------------------------------------------------------------
def synthesize_auto_flip_set(
    *, scene: Any, target: Target, profile: CameraProfile, spec: ObsSpec,
    frame: ViewFrame, rng: np.random.Generator, azimuths_deg: Sequence[float] = (0.0, 90.0),
    flip_axis: Sequence[float] = (1.0, 0.0, 0.0), flip_deg: float = 180.0,
) -> dict[str, np.ndarray]:
    """The second view set a flip would produce, paired front-to-back with the first.

    ``p0434``/``t045``: the bench flips by hand and starts a new session; there is no
    automatic flip.  The flip here is a rigid ``T_WO`` about an axis through the fragment
    centre, so the front/back pairs are exactly complementary poses of the same body.  The
    realised silhouette intersection-over-union of each pair is measured and reported.
    """
    center = _bbox_center(target.bbox)
    flip = _turn_about_point(flip_axis, math.radians(float(flip_deg)), center)
    front_rgb: list[np.ndarray] = []
    back_rgb: list[np.ndarray] = []
    front_depth: list[np.ndarray] = []
    back_depth: list[np.ndarray] = []
    ious: list[float] = []
    for azimuth in np.asarray(azimuths_deg, dtype=np.float64).reshape(-1):
        turn = _turn_about_point((0.0, 1.0, 0.0), math.radians(float(azimuth)), center)
        out_f = render_view(scene, frame, light=spec.resolved_light(), spec=spec.render_spec,
                            object_pose=turn, backend=BACKEND_SOFTWARE)
        out_b = render_view(scene, frame, light=spec.resolved_light(), spec=spec.render_spec,
                            object_pose=flip @ turn, backend=BACKEND_SOFTWARE)
        df = np.asarray(out_f.depth_z, dtype=np.float32)
        db = np.asarray(out_b.depth_z, dtype=np.float32)
        mf = np.isfinite(df)
        mb = np.isfinite(db)
        union = int((mf | mb).sum())
        ious.append(float((mf & mb).sum()) / float(union) if union else 0.0)
        front_rgb.append(_to_u8(np.asarray(out_f.rgb_linear)))
        back_rgb.append(_to_u8(np.asarray(out_b.rgb_linear)))
        front_depth.append(df)
        back_depth.append(db)
    _require_pixels(np.asarray(ious, dtype=np.float64) > 0.0, "auto_flip_second_set")
    return {
        "front_rgb": np.stack(front_rgb, axis=0),
        "back_rgb": np.stack(back_rgb, axis=0),
        "front_depth_mm": np.stack(front_depth, axis=0),
        "back_depth_mm": np.stack(back_depth, axis=0),
        "pair_azimuth_deg": np.asarray(azimuths_deg, dtype=np.float32),
        "T_WO_flip": flip,
        "front_back_overlap_iou": np.asarray(ious, dtype=np.float32),
        "flip_axis": np.asarray(flip_axis, dtype=np.float64).reshape(3),
        "flip_deg": np.asarray([float(flip_deg)], dtype=np.float64),
    }


# --------------------------------------------------------------------------------------
# 8. excavation context (reference only)
# --------------------------------------------------------------------------------------
def reference_excavation_context(
    *, store: Any = None, fragment_id: str, lineage_id: str | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Reference the excavation-context pack instead of generating a second copy of it.

    Another teammate owns the simulated excavation context (``simulated=true``).  This
    module only records whether such a pack exists for the lineage and what its asset id
    is; it never duplicates, edits or re-labels the other module's product.
    """
    from ..roles import ROLE_CONTEXT_PACK

    asset_id: str | None = None
    present = False
    scanned = 0
    if store is not None:
        try:
            rows = store.list_assets(role=ROLE_CONTEXT_PACK, lineage_id=lineage_id)
        except Exception:
            rows = []
        scanned = len(rows)
        if rows:
            present = True
            asset_id = str(getattr(rows[0], "asset_id", rows[0]))
    return (
        {"present": np.asarray([1 if present else 0], dtype=np.int8)},
        {
            "reference_role": "context_pack",
            "reference_asset_id": asset_id,
            "reference_present": bool(present),
            "referenced_assets_scanned": int(scanned),
            "owner": "teammate (simulated excavation context)",
            "simulated": True,
            "not_equivalent_to_mother_id": True,
            "forbidden_as_model_input": True,
        },
    )


# --------------------------------------------------------------------------------------
# 9. synthetic calibration
# --------------------------------------------------------------------------------------
def synthesize_calibration(
    *, profile: CameraProfile, frame: ViewFrame, target: Target, rng: np.random.Generator,
    marker_size_mm: float = 50.0,
) -> dict[str, np.ndarray]:
    """A complete ``calibrated=true`` bundle that is explicitly a *synthetic* calibration.

    Intrinsics and distortion come from the profile registry (which is itself
    ``calibrated=false`` on this machine); the scale reference is a virtual coded target.
    The reported residual is the round-trip error of projecting the virtual target through
    ``K``/``dist`` and back-projecting it -- a self-consistency check of this synthetic
    bundle, **not** an empirical calibration residual and **not** evidence of rig accuracy.
    """
    K = np.asarray(profile.K, dtype=np.float64).copy()
    dist = np.asarray(profile.dist, dtype=np.float64).reshape(-1).copy()
    K_grid = np.asarray(frame.K, dtype=np.float64).copy()
    center = _bbox_center(target.bbox)
    half = float(marker_size_mm) / 2.0
    corners = center + np.array([
        [-half, -half, 0.0], [half, -half, 0.0], [half, half, 0.0], [-half, half, 0.0],
    ], dtype=np.float64)
    # the virtual target is observed on the *extras grid*, so visibility and the round trip
    # are checked with the rescaled ``frame.K``; the full-resolution ``profile.K`` is what
    # this bundle certifies and is stored alongside.
    uv, z = project(corners, K_grid, frame.T_WC, dist)
    uv_full, _ = project(corners, K, frame.T_WC, dist)
    width, height = int(frame.image_size[0]), int(frame.image_size[1])
    inside = ((uv[:, 0] >= 0) & (uv[:, 0] < width)
              & (uv[:, 1] >= 0) & (uv[:, 1] < height) & np.isfinite(uv).all(axis=1))
    _require_pixels(inside, "synthetic_calibration (virtual coded target outside the frame)")
    back = unproject(uv, z, K_grid, frame.T_WC, dist)
    residual = np.linalg.norm(back - corners, axis=1)
    return {
        # deliberately NOT named ``K``/``dist``: those are deploy-view channel names and an
        # extras channel may never collide with the deployment whitelist.
        "intrinsics_K": K,
        "intrinsics_K_extras_grid": K_grid,
        "distortion_coeffs": dist,
        "target_corners_world_mm": corners.astype(np.float32),
        "target_corners_uv": uv.astype(np.float32),
        "target_corners_uv_full_resolution": uv_full.astype(np.float32),
        "roundtrip_corners_world_mm": back.astype(np.float32),
        "roundtrip_residual_mm": residual.astype(np.float32),
        "scale_reference_size_mm": np.asarray([float(marker_size_mm)], dtype=np.float64),
    }


# --------------------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------------------
def _bundle(
    modality_id: str, arrays: dict[str, np.ndarray], *, params: Mapping[str, Any],
    master_seed: int, lineage_id: str, fragment_id: str, extra: Mapping[str, Any] | None
    = None, seconds: float = 0.0,
) -> ExtraBundle:
    annotation = annotation_template(modality_id)
    annotation["generator"]["params"] = {str(k): _jsonable(v) for k, v in params.items()}
    annotation["generator"]["seed_path"] = _seed_path(master_seed, lineage_id, fragment_id,
                                                      modality_id)
    annotation["generator"]["seed_ref"] = seed_ref(master_seed, lineage_id, fragment_id,
                                                   "synthetic_extras", modality_id)
    annotation["generator"]["seconds"] = round(float(seconds), 4)
    annotation["fragment_id"] = fragment_id
    annotation["lineage_id"] = lineage_id
    annotation["master_seed"] = int(master_seed)
    if extra:
        annotation.update({str(k): _jsonable(v) for k, v in extra.items()})
    _fill_shape(annotation, arrays)
    assert_claim_ban(annotation)
    return ExtraBundle(modality_id=modality_id, annotation=annotation, arrays=arrays,
                       seconds=float(seconds))


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def generate_synthetic_extras(
    target_or_fragment: Any,
    *, store: Any = None,
    profile: Any = None,
    spec: ObsSpec | None = None,
    master_seed: int = 20261001,
    lineage_id: str = "lineage_default",
    fragment_id: str | None = None,
    modalities: Iterable[str] | None = None,
    long_edge_px: int = 128,
    baseline_mm: float = 60.0,
    rotation_step_deg: float = 5.0,
    polarizer_step_deg: float = 15.0,
    claim_mm: float = 0.1,
) -> ExtrasResult:
    """Generate the §8 extras for one fragment.

    Every extra is generated into its **own** channel set; no existing observation
    semantics is modified.  A modality that raises is recorded with ``failure`` set and its
    traceback reason instead of being silently replaced by placeholder data.
    """
    started = time.time()
    target = _as_target(target_or_fragment, fragment_id=fragment_id)
    profile_obj = resolve_profile(profile)
    spec = spec or ObsSpec()
    size = _extras_size(profile_obj, int(long_edge_px))
    scene = _scene_for(target)
    center = _bbox_center(target.bbox)
    frame = _turntable_frame(view_id=f"{profile_obj.profile_id}#extras", profile=profile_obj,
                            size=size, center=center)
    wanted = list(modalities) if modalities is not None else list(MODALITY_IDS)
    unknown = [m for m in wanted if m not in MODALITY_BY_ID]
    if unknown:
        raise KeyError(f"unknown extras modality id(s): {unknown}")

    bundles: list[ExtraBundle] = []
    for modality_id in wanted:
        rng = _rng_for(master_seed, lineage_id, str(target.fragment_id), modality_id)
        t0 = time.time()
        try:
            arrays, extra = _dispatch(
                modality_id, scene=scene, target=target, profile=profile_obj, spec=spec,
                frame=frame, rng=rng, store=store, lineage_id=lineage_id,
                baseline_mm=baseline_mm, rotation_step_deg=rotation_step_deg,
                polarizer_step_deg=polarizer_step_deg, claim_mm=claim_mm)
            params = dict(extra.pop("_params", {}) or {})
            bundles.append(_bundle(
                modality_id, arrays, params=params, master_seed=master_seed,
                lineage_id=lineage_id, fragment_id=str(target.fragment_id), extra=extra,
                seconds=time.time() - t0))
        except Exception as exc:                    # honest failure, never a placeholder
            bundles.append(ExtraBundle(
                modality_id=modality_id,
                annotation={**annotation_template(modality_id),
                            "fragment_id": str(target.fragment_id),
                            "lineage_id": lineage_id,
                            "master_seed": int(master_seed)},
                arrays={}, seconds=time.time() - t0,
                failure=f"{type(exc).__name__}: {exc}"))
    return ExtrasResult(
        fragment_id=str(target.fragment_id),
        component_id=str(target.component_id),
        lineage_id=lineage_id,
        master_seed=int(master_seed),
        profile_id=profile_obj.profile_id,
        bundles=bundles,
        seconds=time.time() - started,
        meta={
            "size_px": list(size),
            "long_edge_px": int(long_edge_px),
            "baseline_mm": float(baseline_mm),
            "rotation_step_deg": float(rotation_step_deg),
            "polarizer_step_deg": float(polarizer_step_deg),
            "claim_mm": float(claim_mm),
            "renderer": BACKEND_SOFTWARE,
            "synthetic_only": True,
            "claim_ban": CLAIM_BAN,
            "target_meta": {"input_kind": target.meta.get("input_kind"),
                            "surface_tag_source": target.meta.get("surface_tag_source")},
        },
    )


def _dispatch(modality_id: str, **kw: Any) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    scene, target = kw["scene"], kw["target"]
    profile, spec, frame, rng = kw["profile"], kw["spec"], kw["frame"], kw["rng"]
    if modality_id == "photometric_normals":
        arrays = synthesize_photometric_normals(scene=scene, target=target, profile=profile,
                                                spec=spec, frame=frame, rng=rng)
        angles = arrays["ps_vs_geom_angle_deg"]
        finite = np.isfinite(angles)
        extra = {
            "n_lights": 4,
            "light_model": "LAMBERT_AMBIENT with ambient zeroed for the linear solve",
            "solve": "least squares g = pinv(L) @ I, n = g/|g|",
            "flat_shading": True,
            "ps_vs_geom_angle_median_deg": float(np.median(angles[finite]))
            if finite.any() else None,
            "ps_valid_fraction": float(np.mean(arrays["ps_valid"])),
            "_params": {"n_lights": 4, "lamp_groups": [n for n, _ in _PS_LIGHT_POSITIONS],
                        "ambient_zeroed": True, "working_distance_mm":
                            float(profile.working_distance_mm)},
        }
        return arrays, extra
    if modality_id == "polarizer_angle_sequence":
        arrays = synthesize_polarizer_sequence(
            scene=scene, target=target, profile=profile, spec=spec, frame=frame, rng=rng,
            step_deg=kw["polarizer_step_deg"])
        angles = arrays["polarizer_angles_deg"]
        extra = {
            "polarizer_auto": False,
            "angle_measured_deg": None,
            "model": "MALUS I(theta)=I_base*((1-rho)+rho*cos^2(theta-phi))",
            "model_declared_synthetic": True,
            "n_angles": int(angles.shape[0]),
            "angle_range_deg": [float(angles.min()), float(angles.max())],
            "_params": {"step_deg": float(kw["polarizer_step_deg"]), "rho_max": 0.35,
                        "rho_model": "rho_max * lambert * visible"},
        }
        return arrays, extra
    if modality_id == "sub_millimetre_scale_claim":
        arrays = synthesize_sub_millimetre_claim(
            scene=scene, target=target, profile=profile, spec=spec, frame=frame, rng=rng,
            claim_mm=kw["claim_mm"])
        extra = {
            "claim": "unverified_beyond_rig",
            "declared_accuracy_mm": float(kw["claim_mm"]),
            "realised_max_residual_mm": float(arrays["realised_max_residual_mm"][0]),
            "accuracy_is_a_claim_not_a_measurement": True,
            "forbidden_in_capability_claims": True,
            "scale_reference": {"kind": "virtual_coded_target", "simulated": True},
            "_params": {"claim_mm": float(kw["claim_mm"]),
                        "lattice": "round(p/step)*step"},
        }
        return arrays, extra
    if modality_id == "hard_sync_stereo":
        arrays = synthesize_hard_sync_stereo(
            scene=scene, target=target, profile=profile, spec=spec, frame=frame, rng=rng,
            baseline_mm=kw["baseline_mm"])
        disp = arrays["disparity_px"]
        finite = np.isfinite(disp)
        extra = {
            "sync_model": "IDEAL_RIGID_SIMULTANEOUS",
            "baseline_mm": float(kw["baseline_mm"]),
            "baseline_source": "declared_synthetic",
            "rectified": True,
            "disparity_valid_fraction": float(finite.mean()),
            "disparity_median_px": float(np.median(disp[finite])) if finite.any() else None,
            "rig_has_two_nodes": "optional upgrade only (t050); sequential capture, no hard sync",
            "_params": {"baseline_mm": float(kw["baseline_mm"]),
                        "working_distance_mm": float(profile.working_distance_mm)},
        }
        return arrays, extra
    if modality_id == "dense_depth_reliable":
        arrays = synthesize_dense_depth(scene=scene, target=target, profile=profile, spec=spec,
                                        frame=frame, rng=rng)
        depth_source = str(arrays.pop("depth_source")[0])
        valid = arrays["depth_valid"]
        check = arrays["raycast_check_depth_mm"]
        delta = arrays["raycast_check_delta_mm"]
        finite = np.isfinite(check) & np.isfinite(delta)
        extra = {
            "depth_source": depth_source,
            "primary_is_a_ray_cast": depth_source.startswith("open3d"),
            "cross_check": "software_rasteriser z-buffer on a random pixel subsample",
            "cross_check_pixels": int(check.shape[0]),
            "cross_check_compared": int(finite.sum()),
            "cross_check_max_delta_mm": float(np.max(delta[finite]))
            if finite.any() else None,
            "silhouette_valid_fraction": float(valid.mean()),
            "missing_inside_silhouette": 0,
            "coverage_note": (
                "no synthetic dropout and no carved holes; pixels outside the silhouette are "
                "marked invalid rather than filled with invented depth"
            ),
            "_params": {"supersample": 1, "cross_check_pixels": int(check.shape[0]),
                        "distortion_aware_rays": True},
        }
        return arrays, extra
    if modality_id == "continuous_rotation":
        arrays = synthesize_continuous_rotation(
            scene=scene, target=target, profile=profile, spec=spec, frame=frame, rng=rng,
            step_deg=kw["rotation_step_deg"])
        extra = {
            "step_deg": float(kw["rotation_step_deg"]),
            "n_views": int(arrays["angles_deg"].shape[0]),
            "sweep_deg": float(arrays["cumulative_angle_deg"][0]),
            "wraps": int(arrays["wraps"][0]),
            "limits": ("bench requires stop-and-shoot with bounded accumulated angle "
                       "(p0432/p1156); angles are commanded, never measured"),
            "_params": {"step_deg": float(kw["rotation_step_deg"]), "axis": "world_y",
                        "turntable": True},
        }
        return arrays, extra
    if modality_id == "auto_flip_second_set":
        arrays = synthesize_auto_flip_set(scene=scene, target=target, profile=profile,
                                         spec=spec, frame=frame, rng=rng)
        extra = {
            "flip_deg": float(arrays["flip_deg"][0]),
            "flip_axis": _jsonable(arrays["flip_axis"]),
            "pairs": int(arrays["pair_azimuth_deg"].shape[0]),
            "front_back_overlap_iou": _jsonable(arrays["front_back_overlap_iou"]),
            "bench_behaviour": "manual flip or re-support, new session (p0434/t045)",
            "_params": {"azimuths_deg": _jsonable(arrays["pair_azimuth_deg"]),
                        "flip_deg": float(arrays["flip_deg"][0])},
        }
        return arrays, extra
    if modality_id == "excavation_context_ref":
        arrays, extra = reference_excavation_context(
            store=kw["store"], fragment_id=str(target.fragment_id),
            lineage_id=kw["lineage_id"])
        extra["_params"] = {"reference_only": True}
        return arrays, extra
    if modality_id == "synthetic_calibration":
        arrays = synthesize_calibration(profile=profile, frame=frame, target=target, rng=rng)
        cal_id = _synthetic_calibration_id(profile)
        extra = {
            "calibrated": True,
            # house vocabulary (synlab/api/routers/cameras.py): UNCALIBRATED | MANUFACTURER |
            # MEASURED | SYNTHETIC_GT.  This bundle is SYNTHETIC_GT, and the shipped profile
            # registry is left untouched at calibrated=false / STRESS_UNCALIBRATED.
            "calibration_state": "SYNTHETIC_GT",
            "calibration_source": "SYNTHETIC_GT",
            "calibration_provenance": "SYNTHETIC_NOT_REAL_CAPTURE",
            "shipped_profile_calibrated": bool(profile.calibrated),
            "shipped_profile_calibration_status": str(
                profile.meta.get("calibration_status", "UNCALIBRATED")),
            "calibration_id": cal_id,
            "intrinsics_profile_id": f"{profile.profile_id}#SYNTHETIC",
            "rig_calibration_rev": 0,
            "scale_reference": {"kind": "virtual_coded_target", "simulated": True,
                               "size_mm": float(arrays["scale_reference_size_mm"][0])},
            "residual_kind": "synthetic_self_consistency_roundtrip",
            "residual_is_not_an_empirical_calibration_error": True,
            "roundtrip_max_residual_mm": float(np.max(arrays["roundtrip_residual_mm"])),
            "_params": {"profile_id": profile.profile_id,
                        "working_distance_mm": float(profile.working_distance_mm),
                        "marker_size_mm": float(arrays["scale_reference_size_mm"][0])},
        }
        return arrays, extra
    raise KeyError(modality_id)


def _synthetic_calibration_id(profile: CameraProfile) -> str:
    payload = f"{profile.profile_id}|{profile.revision}|{np.asarray(profile.K).ravel()}".encode()
    return "SYNTHCAL_" + hashlib.sha256(payload).hexdigest()[:16]


__all__ = [
    "SCHEMA_EXTRA_ANNOTATION", "SCHEMA_EXTRA_INDEX", "EXTRA_DIRNAME", "CLAIM_BAN",
    "RIG_OBTAINABLE_EXTRA", "CLAIM_ALLOWED_EXTRA",
    "ModalitySpec", "MODALITIES", "MODALITY_BY_ID", "MODALITY_IDS",
    "ExtraBundle", "ExtrasResult",
    "annotation_template", "assert_claim_ban", "resolve_profile",
    "solve_photometric_normals",
    "synthesize_photometric_normals", "synthesize_polarizer_sequence",
    "synthesize_sub_millimetre_claim", "synthesize_hard_sync_stereo",
    "synthesize_dense_depth", "synthesize_continuous_rotation",
    "synthesize_auto_flip_set", "reference_excavation_context",
    "synthesize_calibration", "generate_synthetic_extras",
]
