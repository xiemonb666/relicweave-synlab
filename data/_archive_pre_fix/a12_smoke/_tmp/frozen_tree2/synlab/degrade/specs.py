"""Hardware / material catalogue for the *capture rig* of the A12 project, with provenance.

Why this module exists
----------------------
Two new degradation models (:mod:`synlab.degrade.wear`, :mod:`synlab.degrade.rig_error`) are
driven by **physical quantities** instead of free knobs.  A physical quantity is only usable if
the caller can tell where it came from, so every number in this file carries an explicit
:data:`PROVENANCE_KINDS` tag:

``DOCUMENTED``
    written verbatim in the authoritative source (§C3/§C3.2/§C4/§C5/§C5.1 of
    ``RelicWeave_V1.44_Optimized_Complete_Plan.docx``, mirrored into
    ``docs/a12/v144_project_core.md`` and the project-core extract).  The ``ref`` field names the
    location.
``DERIVED``
    computed from DOCUMENTED numbers by a stated formula (kept beside the value).
``CANDIDATE``
    **no measurement exists on this machine.**  The value is a documented-*empty* quantity or a
    literature/typical figure, and every place that consumes it must keep saying so.  The plan
    itself calls these "候选值" and requires "待实测校准" (real-measurement calibration).
``UNKNOWN``
    the document states the quantity is not given and no defensible candidate exists; the field
    is present so the gap is visible rather than silently filled.

The catalogue never *measures* anything: it is the declared input of the two models.  The
measurement runs (``tools``-free scripts in ``reports``) put the measured values beside it.

Authoritative sources
---------------------
* ``docs/a12/v144_project_core.md`` §4.2 (camera / board / optics, p504-p518),
  §4.3 (mechanics, p520-p533), §4.4 (four-zone white light + polarisation, p535-p541),
  §5 (G5 quality vector, p199/p236), §5.6 (3-D engineering floor, p1063).
* ``data/a12/reports/_rig_paras_res.txt``: the raw paragraph hits used to check the numbers
  below (p0041/p0045/p0049/p0504/p0512/p0517/p1223).
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

__all__ = [
    "PROVENANCE_KINDS", "MEASURED", "DOCUMENTED", "DERIVED", "CANDIDATE", "UNKNOWN",
    "SpecValue", "CameraSpec", "LensSpec", "RigMotionSpec", "LightModeSpec",
    "capture_rig_spec", "light_modes", "light_mode", "LIGHT_MODE_NAMES",
    "WORKING_DISTANCES_MM", "RESOLUTION_AT_DISTANCE_MM_PER_PX", "QUALITY_VECTOR_ITEMS",
    "degradation_vector_components", "DEGRADATION_VECTOR_14", "MATERIAL_WEAR_TRAITS",
    "material_wear_traits", "GLAZE_THICKNESS_RANGE_MM",
    "RECON_FLOOR_VALID_FRACTION", "RECON_FLOOR_SIGMA_MM", "RECON_FLOOR_HOLES",
    "RECON_FLOOR_HOLE_RADIUS_MM",
]

MEASURED = "MEASURED"
DOCUMENTED = "DOCUMENTED"
DERIVED = "DERIVED"
CANDIDATE = "CANDIDATE"
UNKNOWN = "UNKNOWN"

#: Kinds in decreasing order of evidential strength.
PROVENANCE_KINDS: tuple[str, ...] = (MEASURED, DOCUMENTED, DERIVED, CANDIDATE, UNKNOWN)


@dataclass(frozen=True)
class SpecValue:
    """One catalogue number plus exactly where it came from."""

    value: Any
    provenance: str
    ref: str = ""
    formula: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.provenance not in PROVENANCE_KINDS:
            raise ValueError(f"unknown provenance {self.provenance!r}; "
                             f"expected one of {PROVENANCE_KINDS}")

    @property
    def is_candidate(self) -> bool:
        return self.provenance in (CANDIDATE, UNKNOWN)

    @property
    def needs_calibration(self) -> bool:
        """True when a real measurement must replace this value before it can be trusted."""
        return self.provenance in (CANDIDATE, UNKNOWN)

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "provenance": self.provenance, "ref": self.ref,
                "formula": self.formula, "note": self.note,
                "needs_calibration": bool(self.needs_calibration)}


# ======================================================================================
# camera / optics
# ======================================================================================
@dataclass(frozen=True)
class LensSpec:
    """The lens side of the rig: everything that turns object space into image space."""

    f_number: SpecValue
    focal_length_mm: SpecValue
    mount: SpecValue
    focus: SpecValue
    shutter: SpecValue

    @property
    def aperture_ratio(self) -> float:
        return float(self.f_number.value)

    @property
    def derived_focal_length_mm(self) -> float:
        return float(self.focal_length_mm.value)


@dataclass(frozen=True)
class CameraSpec:
    """Luckfox Pico RV1103 + SC3336B node, as declared by the project document."""

    board: SpecValue
    module: SpecValue
    sensor_width_px: SpecValue
    sensor_height_px: SpecValue
    sensor_format_inch: SpecValue
    sensor_width_mm: SpecValue
    sensor_height_mm: SpecValue
    pixel_pitch_mm: SpecValue
    fov_h_deg: SpecValue
    interface: SpecValue
    distortion_model: SpecValue
    focus_mode: SpecValue
    shutter: SpecValue
    lens: LensSpec
    #: row readout time of the rolling shutter (see :mod:`synlab.degrade.rig_error`)
    line_time_us: SpecValue
    frame_readout_ms: SpecValue
    #: resolution ladder, keyed by working distance in mm
    resolution_mm_per_px: Mapping[int, SpecValue]
    ideal_coverage_mm: Mapping[int, SpecValue]
    px_per_mm_at_distance: Mapping[int, SpecValue]

    # -- convenience -----------------------------------------------------------------
    def mm_per_px(self, working_distance_mm: float) -> float:
        """Ideal-pinhole mm/px at ``working_distance_mm`` (documented formula, extrapolated).

        The five documented distances are returned verbatim; any other distance is evaluated
        with the same documented formula ``W(d) = 2 d tan(FOV_h/2)``, ``s = W / N_x`` and the
        result is tagged ``DERIVED`` by :meth:`mm_per_px_value`.
        """
        table = {int(k): float(v.value) for k, v in self.resolution_mm_per_px.items()}
        key = int(round(float(working_distance_mm)))
        if key in table:
            return table[key]
        return 2.0 * float(working_distance_mm) * math.tan(
            math.radians(float(self.fov_h_deg.value)) / 2.0) / float(self.sensor_width_px.value)

    def mm_per_px_value(self, working_distance_mm: float) -> SpecValue:
        key = int(round(float(working_distance_mm)))
        if key in self.resolution_mm_per_px:
            return self.resolution_mm_per_px[key]
        return SpecValue(
            float(self.mm_per_px(working_distance_mm)), DERIVED,
            ref="docs/a12/v144_project_core.md §4.2 p512 (formula only)",
            formula="s = 2 d tan(FOV_h/2) / N_x",
            note=(f"{working_distance_mm} mm is not one of the five documented distances "
                  f"(50/100/150/200/250 mm); the same documented pinhole formula is evaluated "
                  f"instead of interpolating the measured table"))

    @property
    def focal_mm(self) -> float:
        """Effective focal length implied by the documented FOV and the 16:9 sensor width."""
        return float(self.lens.focal_length_mm.value)

    @property
    def focal_px(self) -> float:
        """Pixel focal length of the delivered frame (same for x and y under square pixels)."""
        return self.focal_mm / float(self.pixel_pitch_mm.value)

    @property
    def px_per_mm_sensor(self) -> float:
        return 1.0 / float(self.pixel_pitch_mm.value)

    def as_dict(self) -> dict[str, Any]:
        def block(**values: SpecValue) -> dict[str, Any]:
            return {k: v.as_dict() for k, v in sorted(values.items())}

        return {
            "board": self.board.as_dict(), "module": self.module.as_dict(),
            "sensor": block(width_px=self.sensor_width_px, height_px=self.sensor_height_px,
                            format_inch=self.sensor_format_inch,
                            width_mm=self.sensor_width_mm, height_mm=self.sensor_height_mm,
                            pixel_pitch_mm=self.pixel_pitch_mm, fov_h_deg=self.fov_h_deg),
            "interface": self.interface.as_dict(),
            "distortion_model": self.distortion_model.as_dict(),
            "focus_mode": self.focus_mode.as_dict(), "shutter": self.shutter.as_dict(),
            "lens": block(f_number=self.lens.f_number, focal_length_mm=self.lens.focal_length_mm,
                          mount=self.lens.mount, focus=self.lens.focus,
                          shutter=self.lens.shutter),
            "rolling_shutter": block(line_time_us=self.line_time_us,
                                     frame_readout_ms=self.frame_readout_ms),
            "resolution_mm_per_px": {str(k): v.as_dict()
                                     for k, v in sorted(self.resolution_mm_per_px.items())},
            "ideal_coverage_mm": {str(k): v.as_dict()
                                  for k, v in sorted(self.ideal_coverage_mm.items())},
            "focal_px": self.focal_px, "px_per_mm_sensor": self.px_per_mm_sensor,
        }


#: Documented working distances of the §4.2 resolution table.
WORKING_DISTANCES_MM: tuple[int, ...] = (50, 100, 150, 200, 250)

#: Documented mm/px values of the §4.2 table (p512, t051).
RESOLUTION_AT_DISTANCE_MM_PER_PX: dict[int, float] = {
    50: 0.039, 100: 0.078, 150: 0.117, 200: 0.156, 250: 0.195,
}

#: Documented ideal horizontal coverage in mm (the same table).
_IDEAL_COVERAGE_MM: dict[int, float] = {50: 90.0, 100: 180.1, 150: 270.1, 200: 360.2, 250: 450.2}

_RES_REF = "docs/a12/v144_project_core.md §4.2 t051/p512 (逐距离表)"


def _resolution_tables(fov_h_deg: float, width_px: int) -> tuple[dict[int, SpecValue],
                                                                 dict[int, SpecValue],
                                                                 dict[int, SpecValue]]:
    res: dict[int, SpecValue] = {}
    cov: dict[int, SpecValue] = {}
    density: dict[int, SpecValue] = {}
    for distance in WORKING_DISTANCES_MM:
        ideal = 2.0 * distance * math.tan(math.radians(fov_h_deg) / 2.0)
        res[distance] = SpecValue(
            RESOLUTION_AT_DISTANCE_MM_PER_PX[distance], DOCUMENTED, ref=_RES_REF,
            formula="s = W(d)/N_x",
            note=("documented ideal-pinhole value; the document explicitly says 近摄与畸变须实测 "
                  "and does not promise 0.1 mm absolute accuracy"))
        cov[distance] = SpecValue(
            _IDEAL_COVERAGE_MM[distance], DOCUMENTED, ref=_RES_REF, formula="W(d)=2 d tan(84/2)",
            note=f"ideal pinhole; the same formula evaluates to {ideal:.1f} mm here")
        density[distance] = SpecValue(
            width_px / _IDEAL_COVERAGE_MM[distance], DERIVED, ref=_RES_REF,
            formula="N_x / W(d)  [px per mm of object at that distance]",
            note="object-space sampling density of the delivered frame")
    return res, cov, density


def _camera_spec() -> CameraSpec:
    width_px, height_px = 2304, 1296
    fov_h = 84.0
    sensor_format = 2.8                      # 1/2.8 inch, quoted on the vendor product page
    # Optical format -> active diagonal: the classic 1/2.8" active area is 6.46 mm diagonal, i.e.
    # d = 18.08 / format_inch (d = 16 mm for a 1.13" part).  Taking the *arithmetic* 25.4/format
    # would give 9.07 mm and a 2.2 mm lens, i.e. the wrong lens class.
    sensor_diagonal_mm = 18.08 / sensor_format
    sensor_width_mm = sensor_diagonal_mm * 16.0 / math.sqrt(16.0 ** 2 + 9.0 ** 2)
    sensor_height_mm = sensor_width_mm * height_px / width_px
    pitch_mm = sensor_width_mm / width_px
    focal_mm = sensor_width_mm / (2.0 * math.tan(math.radians(fov_h) / 2.0))
    res, cov, density = _resolution_tables(fov_h, width_px)
    # Rolling shutter: the *line time* is not published for the SC3336B.  The value carried here
    # is the IMX415-class line time measured in the public Raspberry Pi camera tuning
    # (2x2-binned 1080p line ~ 8.9 us).  It is a CANDIDATE: the model never assumes it silently,
    # the frame period and row count are documented and stay separate fields.
    line_time_us = 8.9
    frame_readout_ms = line_time_us * height_px / 1000.0
    lens = LensSpec(
        f_number=SpecValue(
            2.0, CANDIDATE, ref="docs/a12/v144_project_core.md §4.2 p513 (镜头/焦距 文档未给出)",
            note=("the document gives no M12 lens model, focal length or f-number; f/2.0 is a "
                  "typical board-lens class value used only to make the defocus model runnable "
                  "— 待实测（用景深/靶标反解实孔径）")),
        focal_length_mm=SpecValue(
            focal_mm, DERIVED, ref=_RES_REF, formula="f = W_sensor / (2 tan(FOV_h/2))",
            note=("consistent with the documented px-focal-length: "
                  f"f/pixel_pitch = {focal_mm / pitch_mm:.1f} px, which is exactly what the "
                  "delivered-resolution maths needs")),
        mount=SpecValue(UNKNOWN, UNKNOWN, ref="p513",
                        note="镜头座规格/感光面覆盖/焦距/模组供电/排线 pinout 均须核实"),
        focus=SpecValue("MANUAL", DOCUMENTED, ref="p504/p513",
                        note="手动对焦；自动调焦未实现时不能让策略选择已知失焦的距离"),
        shutter=SpecValue("ROLLING", DOCUMENTED, ref="p504", formula="",
                          note="滚动快门 (rolling shutter)"),
    )
    return CameraSpec(
        board=SpecValue("Luckfox Pico RV1103", DOCUMENTED, ref="§4.2 p504"),
        module=SpecValue("SC3336B", DOCUMENTED, ref="§4.2 p504 / 附录F p1223"),
        sensor_width_px=SpecValue(width_px, DOCUMENTED, ref="§4.2 p504", formula="",
                                  note="标称 2304×1296；须验证适配器实际输出分辨率"),
        sensor_height_px=SpecValue(height_px, DOCUMENTED, ref="§4.2 p504"),
        sensor_format_inch=SpecValue(
            sensor_format, DOCUMENTED, ref="附录F p1223 (1/2.8 英寸)",
            note="vendor product page quoted by the plan; used only to size the sensor"),
        sensor_width_mm=SpecValue(
            sensor_width_mm, DERIVED, ref="附录F p1223",
            formula="W = (18.08 / format_inch) * 16 / sqrt(16^2+9^2)  [16:9 active area]",
            note=("1/2.8\" active diagonal = 6.46 mm (the classic optical-format relation); the "
                  "vendor page quotes the format, not a width")),
        sensor_height_mm=SpecValue(sensor_height_mm, DERIVED, ref="附录F p1223",
                                   formula="H = W * 1296/2304"),
        pixel_pitch_mm=SpecValue(
            pitch_mm, DERIVED, ref="附录F p1223", formula="p = W / 2304",
            note="≈2.45 µm; the vendor page does not print a pitch"),
        fov_h_deg=SpecValue(fov_h, DOCUMENTED, ref="§4.2 p504 (FOV_h ≈ 84 度)"),
        interface=SpecValue("MIPI 2-lane, one CSI connector", DOCUMENTED, ref="§4.2 p505",
                            note="按一个 CSI 连接口设计，不能用被动一分二排线扩成同时双目"),
        distortion_model=SpecValue(
            "OPENCV fx/fy/cx/cy + distortion, order UNKNOWN", UNKNOWN, ref="§4.2 p382/p487",
            note=("文档未给出显式畸变模型（阶数未明确），只要求按 OpenCV 标定流程保存并每次实测")),
        focus_mode=SpecValue("MANUAL", DOCUMENTED, ref="§4.2 p504/p513"),
        shutter=SpecValue("ROLLING", DOCUMENTED, ref="§4.2 p504"),
        lens=lens,
        line_time_us=SpecValue(
            line_time_us, CANDIDATE,
            ref="§4.2 p504 (只给'滚动快门'，未给行时间)",
            formula="t_row",
            note=("the SC3336B datasheet line time is not in the plan and not measured here; "
                  "8.9 us is an IMX415-class figure.  Every rolling-shutter number derived from "
                  "it is therefore a CANDIDATE and must be re-derived from a real strobe/rotation "
                  "test — 待实测校准")),
        frame_readout_ms=SpecValue(
            frame_readout_ms, DERIVED, ref="§4.2 p504",
            formula="T_read = t_row * N_y",
            note="derived from the candidate line time; the model keeps the two fields separate"),
        resolution_mm_per_px=res, ideal_coverage_mm=cov, px_per_mm_at_distance=density,
    )


# ======================================================================================
# rig motion (turntable / U rail / Z) — the drivers of rolling-shutter shear
# ======================================================================================
@dataclass(frozen=True)
class RigMotionSpec:
    """Declared mechanics that move the scene during one rolling-shutter exposure."""

    turntable: SpecValue
    turntable_rate_dps: SpecValue
    z_axis: SpecValue
    u_rail_travel_mm: SpecValue
    u_repeat_p95_mm: SpecValue
    camera_front_clearance_mm: SpecValue
    dof_declared: SpecValue
    tiers: SpecValue

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k).as_dict()
                for k in ("turntable", "turntable_rate_dps", "z_axis", "u_rail_travel_mm",
                          "u_repeat_p95_mm", "camera_front_clearance_mm", "dof_declared",
                          "tiers")}


_MOTION = RigMotionSpec(
    turntable=SpecValue("low-voltage bipolar stepper + timing belt, independent bearing",
                        DOCUMENTED, ref="§4.3 p520-p524"),
    turntable_rate_dps=SpecValue(
        2.0, CANDIDATE, ref="§4.3 p522 (电机按相电流/扭矩选，未给角速度)",
        note=("the plan freezes no turntable angular rate; 2 deg/s is the low-speed smooth-motion "
              "class the plan asks for ('速度低、加减速平滑').  The rolling-shutter model takes "
              "the rate as an explicit argument, so a measured rate replaces this without "
              "touching the model — 待实测")),
    z_axis=SpecValue("screw rail module, 150-200 mm effective travel", DOCUMENTED, ref="§4.3 p523"),
    u_rail_travel_mm=SpecValue(150.0, DOCUMENTED, ref="§4.3 p530",
                               note="有效行程约 150mm 起步，结构预留 100-200mm"),
    u_repeat_p95_mm=SpecValue(
        0.5, CANDIDATE, ref="§4.3 p533",
        note=("P95 位置误差 0.5mm 仅候选，按景深与密度收紧；步进细分不是实际精度，"
              "无编码器位置为开环估计")),
    camera_front_clearance_mm=SpecValue(
        20.0, CANDIDATE, ref="§4.3 p531",
        note="20mm 仅为候选守卫，按实物尺度冻结，与光学工作距离分字段"),
    dof_declared=SpecValue(
        UNKNOWN, UNKNOWN, ref="§4.2 p404",
        note=("文档未给出数值景深；只给原则'宁可稍远拍高分辨率再裁 ROI'. 景深在本仓库里由 "
              "薄透镜模型 + 实孔径算出，未标定前是候选")),
    tiers=SpecValue(("GLOBAL", "MID", "LOCAL"), DOCUMENTED, ref="§4.2 p406",
                    note="三档工作档 GLOBAL/MID/LOCAL 实测档，动作只选档位 ID"),
)


# ======================================================================================
# light modes (t053)
# ======================================================================================
#: The five documented light states, verbatim from table t053 (§4.4 p455-p463).
LIGHT_MODE_NAMES: tuple[str, ...] = ("WHITE_DIFFUSE", "LEFT_GRAZE", "RIGHT_GRAZE",
                                    "CROSS_POL", "NORMAL_REFLECT")


@dataclass(frozen=True)
class LightModeSpec:
    """One of the five documented light states and what it does to a delivered frame.

    The *documented* part is ``purpose`` / ``groups`` / ``polariser``.  The **imaging effect**
    (which lamp groups radiate, the diffuse/specular mixing weights, the residual specular
    fraction under cross-polarisation) is not printed anywhere in the plan: it is a
    :data:`CANDIDATE` parameter set that the model exposes field by field so that a real
    light-mode pairing capture (A6, p443-p444: 普通光 / 交叉偏振 / 侧光 same piece same pose)
    can replace it.  Nothing here is presented as a measured illumination.
    """

    mode: str
    groups: tuple[str, ...]
    polariser: str
    purpose: str
    ref: str
    #: candidate imaging parameters
    diffuse_weight: SpecValue
    specular_weight: SpecValue
    specular_retained: SpecValue
    key_direction: SpecValue

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "groups": list(self.groups), "polariser": self.polariser,
                "purpose": self.purpose, "ref": self.ref,
                "diffuse_weight": self.diffuse_weight.as_dict(),
                "specular_weight": self.specular_weight.as_dict(),
                "specular_retained": self.specular_retained.as_dict(),
                "key_direction": self.key_direction.as_dict()}


def _light_modes() -> dict[str, LightModeSpec]:
    ref = "docs/a12/v144_project_core.md §4.4 表 t053 (p455-p463)"
    shared = ("灯态的光照几何（哪几组灯亮、漫反射/镜面混合权重、交叉偏振残余镜面比例）在文档里"
              "没有数值；A6 要求同片同姿态采一组 普通光/交叉偏振/侧光 配对图，用它们标定这三个"
              "权重，未标定前全部是候选值")
    return {
        "WHITE_DIFFUSE": LightModeSpec(
            mode="WHITE_DIFFUSE", groups=("left", "right", "upper_front", "upper_back"),
            polariser="lamp-side film removable / removed", purpose="轮廓、颜色和基础纹饰",
            ref=ref,
            diffuse_weight=SpecValue(1.0, CANDIDATE, ref=ref, note=shared),
            specular_weight=SpecValue(0.55, CANDIDATE, ref=ref, note=shared),
            specular_retained=SpecValue(1.0, CANDIDATE, ref=ref,
                                        note="no analyser crossed: all lamp-side specular passes"),
            key_direction=SpecValue([0.0, 0.0, -1.0], CANDIDATE, ref=ref,
                                    note="symmetric multi-lamp; effective key along the optical axis")),
        "LEFT_GRAZE": LightModeSpec(
            mode="LEFT_GRAZE", groups=("left",), polariser="as installed", purpose="断口起伏和裂纹",
            ref=ref,
            diffuse_weight=SpecValue(0.30, CANDIDATE, ref=ref, note=shared),
            specular_weight=SpecValue(0.95, CANDIDATE, ref=ref, note=shared),
            specular_retained=SpecValue(1.0, CANDIDATE, ref=ref, note="analyser not crossed"),
            key_direction=SpecValue([-1.0, 0.0, -0.18], CANDIDATE, ref=ref,
                                    note="low-angle from the left; the low z component is what "
                                         "makes it a grazing key")),
        "RIGHT_GRAZE": LightModeSpec(
            mode="RIGHT_GRAZE", groups=("right",), polariser="as installed",
            purpose="验证另一方向纹理与阴影", ref=ref,
            diffuse_weight=SpecValue(0.30, CANDIDATE, ref=ref, note=shared),
            specular_weight=SpecValue(0.95, CANDIDATE, ref=ref, note=shared),
            specular_retained=SpecValue(1.0, CANDIDATE, ref=ref, note="analyser not crossed"),
            key_direction=SpecValue([1.0, 0.0, -0.18], CANDIDATE, ref=ref,
                                    note="mirror of LEFT_GRAZE")),
        "CROSS_POL": LightModeSpec(
            mode="CROSS_POL", groups=("left", "right", "upper_front", "upper_back"),
            polariser="lamp-side film x lens analyser, axes crossed",
            purpose="降低部分釉面高光 (reduces *part* of the glaze highlight)", ref=ref,
            diffuse_weight=SpecValue(1.0, CANDIDATE, ref=ref, note=shared),
            specular_weight=SpecValue(0.55, CANDIDATE, ref=ref, note=shared),
            specular_retained=SpecValue(
                0.22, CANDIDATE, ref=ref + " (p536 安装顺序)",
                formula="I_spec_after / I_spec_before = k_perp^2 for an ideal analyser",
                note=("the plan says 降低**部分**釉面高光 — not 'removed'.  A perfect crossed pair "
                      "leaves k_perp^2 of the specular return; for real film (k_perp ≈ 0.47 "
                      "amplitude) that is ≈0.22.  Both the ideal value and this one are candidates "
                      "until measured on the actual glaze sample with a grey card — 待实测")),
            key_direction=SpecValue([0.0, 0.0, -1.0], CANDIDATE, ref=ref, note=shared)),
        "NORMAL_REFLECT": LightModeSpec(
            mode="NORMAL_REFLECT", groups=("upper_front", "upper_back"),
            polariser="removed", purpose="保留光泽等材质证据", ref=ref,
            diffuse_weight=SpecValue(0.70, CANDIDATE, ref=ref, note=shared),
            specular_weight=SpecValue(1.25, CANDIDATE, ref=ref, note=shared),
            specular_retained=SpecValue(1.0, CANDIDATE, ref=ref, note="gloss evidence is kept"),
            key_direction=SpecValue([0.0, -0.35, -0.94], CANDIDATE, ref=ref,
                                    note="near-normal white light from the upper front")),
    }


_LIGHT_MODES = _light_modes()


def light_modes() -> tuple[str, ...]:
    """The five documented light states (order of table t053)."""
    return LIGHT_MODE_NAMES


def light_mode(mode: str) -> LightModeSpec:
    """One light state by name; an unknown name is an error, never silently mapped."""
    key = str(mode).upper()
    if key not in _LIGHT_MODES:
        raise KeyError(f"unknown light mode {mode!r}; the documented enumeration is "
                       f"{list(LIGHT_MODE_NAMES)} (docs/a12/v144_project_core.md §4.4 t053)")
    return _LIGHT_MODES[key]


# ======================================================================================
# capture rig
# ======================================================================================
@dataclass(frozen=True)
class CaptureRigSpec:
    """Everything the two models need, in one immutable bundle."""

    camera: CameraSpec
    motion: RigMotionSpec
    lights: Mapping[str, LightModeSpec]
    #: documented four-lamp geometry (positions are *documented qualitatively*: 左/右/前上方/后上方)
    lamp_groups: SpecValue
    colour_temperature: SpecValue
    cri: SpecValue
    polariser_chain: SpecValue
    polariser_auto: SpecValue
    scale_reference: SpecValue
    calibration_per_condition: SpecValue
    absolute_accuracy: SpecValue
    quality_vector: Mapping[str, SpecValue]
    recon_floor: Mapping[str, SpecValue]

    def as_dict(self) -> dict[str, Any]:
        return {
            "camera": self.camera.as_dict(), "motion": self.motion.as_dict(),
            "lights": {k: v.as_dict() for k, v in sorted(self.lights.items())},
            "lamp_groups": self.lamp_groups.as_dict(),
            "colour_temperature": self.colour_temperature.as_dict(),
            "cri": self.cri.as_dict(),
            "polariser_chain": self.polariser_chain.as_dict(),
            "polariser_auto": self.polariser_auto.as_dict(),
            "scale_reference": self.scale_reference.as_dict(),
            "calibration_per_condition": self.calibration_per_condition.as_dict(),
            "absolute_accuracy": self.absolute_accuracy.as_dict(),
            "quality_vector": {k: v.as_dict() for k, v in sorted(self.quality_vector.items())},
            "recon_floor": {k: v.as_dict() for k, v in sorted(self.recon_floor.items())},
        }

    def candidates(self) -> list[dict[str, Any]]:
        """Every candidate/unknown value in the catalogue, with its path (the calibration list)."""
        out: list[dict[str, Any]] = []

        def walk(path: str, node: Any) -> None:
            if isinstance(node, SpecValue):
                if node.needs_calibration:
                    out.append({"path": path, "provenance": node.provenance, "value": node.value,
                                "ref": node.ref, "note": node.note})
                return
            if isinstance(node, Mapping):
                for key in sorted(node, key=str):
                    walk(f"{path}.{key}" if path else str(key), node[key])
                return
            if isinstance(node, (list, tuple)) and not isinstance(node, str):
                for index, item in enumerate(node):
                    walk(f"{path}[{index}]", item)
                return
            if dataclasses.is_dataclass(node) and not isinstance(node, type):
                for entry in dataclasses.fields(node):
                    walk(f"{path}.{entry.name}" if path else entry.name,
                         getattr(node, entry.name))
                return

        walk("", self)
        return out


#: Documented 8-item quality vector of the *real* side (A6, p199/p236; project core line 1086).
QUALITY_VECTOR_ITEMS: tuple[str, ...] = (
    "blur", "exposure", "coverage", "occlusion",
    "reconstruction_confidence", "point_density", "normal_stability", "curvature_stability",
)

#: The 14-component synthetic degradation vector, *verbatim* and in original order (p365).
DEGRADATION_VECTOR_14: tuple[str, ...] = (
    "fracture_smoothing", "edge_rounding", "fracture_missing", "texture_loss", "blur", "glare",
    "exposure", "view_coverage", "point_dropout", "mesh_holes", "depth_noise", "normal_noise",
    "curvature_noise", "calibration_error",
)


def degradation_vector_components() -> tuple[str, ...]:
    """The 14 synthetic vector components in their canonical order."""
    return DEGRADATION_VECTOR_14


# ---------------------------------------------------------------------------- 3-D floor
#: "Q2 当量" engineering floor (p1063) — a *synthetic calibration line*, not a device spec.
RECON_FLOOR_VALID_FRACTION = SpecValue(
    0.50, DOCUMENTED, ref="docs/a12/v144_project_core.md §5.6 p1063",
    formula=">=50 % 有效点保留",
    note=("合成校准线：Gate B 拿到真实扫描后**必须重新标定**；0.10 mm 绝对精度属未来目标，"
          "实拍明确不承诺"))
RECON_FLOOR_SIGMA_MM = SpecValue(0.2, DOCUMENTED, ref="§5.6 p1063",
                                 formula="坐标噪声 sigma <= 0.2 mm")
RECON_FLOOR_HOLES = SpecValue(2, DOCUMENTED, ref="§5.6 p1063",
                              formula="<= 2 个 r <= 3 mm 局部孔洞")
RECON_FLOOR_HOLE_RADIUS_MM = SpecValue(3.0, DOCUMENTED, ref="§5.6 p1063")


# ---------------------------------------------------------------------------- materials
@dataclass(frozen=True)
class WearTraits:
    """Per-material wear behaviour, each number labelled with where it came from.

    ``porosity``
        open porosity of the body.  Documented *nowhere*; the plan's material catalogue fixes
        appearance/roughness classes only.  The value is a literature class figure for the
        material family and is a :data:`CANDIDATE`.
    ``hardness_mohs`` / ``toughness``
        same status.  They enter the model as a *relative* resistance (a softer body wears more
        for the same contact history), which is why an uncalibrated class value is still usable
        — but it is never presented as a measured hardness.
    ``glaze_fraction_of_wall``
        the model measures the wall thickness on the real body and derives the layer thickness
        from it; this fraction is the coupling constant.
    """

    material_id: str
    family: str
    porosity: SpecValue
    hardness_mohs: SpecValue
    toughness: SpecValue
    glaze_fraction_of_wall: SpecValue
    ref: str

    def as_dict(self) -> dict[str, Any]:
        return {"material_id": self.material_id, "family": self.family,
                "porosity": self.porosity.as_dict(),
                "hardness_mohs": self.hardness_mohs.as_dict(),
                "toughness": self.toughness.as_dict(),
                "glaze_fraction_of_wall": self.glaze_fraction_of_wall.as_dict(),
                "ref": self.ref}


_SOFT_REF = ("docs/a12/v144_project_core.md §4 (材料目录只给外观/粗糙度等级) + "
             "docs/a12/mothers_materials.md; 孔隙率/硬度/釉层厚度分数在文档中未给出")
_GLAZE_MEASURED_REF = ("实测依据：L01/L03 GEOMETRIC_LAYER 釉层/涂层厚度 "
                       "0.469-1.173 mm（本项目材料层实测区间，见 docs/a12/mothers_materials.md "
                       "与 data/a12/reports/mother_geometry_audit.json）")

#: Measured glaze / coating layer thickness interval of this project's L01/L03 stacks (mm).
GLAZE_THICKNESS_RANGE_MM: tuple[float, float] = (0.469, 1.173)


def _traits(material_id: str, family: str, porosity: float, hardness: float, toughness: float,
            glaze_fraction: float, *, glaze: bool) -> WearTraits:
    ref = _SOFT_REF + ("; " + _GLAZE_MEASURED_REF if glaze else "")
    return WearTraits(
        material_id=material_id, family=family,
        porosity=SpecValue(porosity, CANDIDATE, ref=ref, formula="open porosity (volume fraction)",
                           note="literature class value for the family; 待实测（吸水率/压汞）"),
        hardness_mohs=SpecValue(hardness, CANDIDATE, ref=ref,
                                note="literature class value; 待实测（划痕/显微硬度）"),
        toughness=SpecValue(toughness, CANDIDATE, ref=ref, formula="relative edge-chipping resistance",
                            note="dimensionless relative resistance used by the chip/blunt rule"),
        glaze_fraction_of_wall=SpecValue(
            glaze_fraction, DERIVED if glaze else CANDIDATE, ref=ref,
            formula="t_glaze = fraction * t_wall(measured on the real body)",
            note=(("the *range of the product* is anchored to the measured 0.469-1.173 mm layer "
                   "interval and clamped there; the fraction itself has no printed source and is "
                   "flagged 待实测") if glaze else "no geometric layer on this material")),
        ref=ref,
    )


_WEAR_TRAITS: dict[str, WearTraits] = {
    # M01 粗陶/夹砂陶 body
    "M01": _traits("M01", "COARSE_EARTHENWARE", 0.18, 3.0, 0.35, 0.16, glaze=False),
    # M02 细陶
    "M02": _traits("M02", "FINE_EARTHENWARE", 0.12, 3.5, 0.45, 0.18, glaze=False),
    # M03 釉陶/原始瓷 (L01 = 坯体+釉)
    "M03": _traits("M03", "GLAZED_STONEWARE", 0.06, 5.5, 0.55, 0.24, glaze=True),
    # M04 泥质陶
    "M04": _traits("M04", "SILTY_EARTHENWARE", 0.16, 3.0, 0.35, 0.15, glaze=False),
    # M05 瓷 (L02 = 坯体+彩绘, appearance only)
    "M05": _traits("M05", "PORCELAIN", 0.02, 6.5, 0.40, 0.12, glaze=True),
    # M06 釉 (L01 top layer material)
    "M06": _traits("M06", "GLAZE_LAYER", 0.01, 5.0, 0.30, 0.30, glaze=True),
    # M07 铜/青铜 (铁锈斑 in the image domain)
    "M07": _traits("M07", "COPPER_ALLOY", 0.00, 3.5, 0.80, 0.00, glaze=False),
    # M08 石质 (L03 = 石质+表面涂层)
    "M08": _traits("M08", "STONE", 0.08, 4.0, 0.45, 0.22, glaze=True),
    # M09 骨/牙
    "M09": _traits("M09", "BONE_IVORY", 0.10, 2.5, 0.30, 0.00, glaze=False),
    # M10 砖瓦/烧结土
    "M10": _traits("M10", "FIRED_CLAY", 0.20, 3.0, 0.30, 0.00, glaze=False),
    # M11 木 (L04 = 木基体+涂饰)
    "M11": _traits("M11", "WOOD", 0.35, 1.5, 0.25, 0.06, glaze=False),
    # M12 未知/混合
    "M12": _traits("M12", "UNKNOWN_MIXED", 0.14, 3.5, 0.40, 0.14, glaze=False),
}


def material_wear_traits(material_id: str) -> WearTraits:
    """Wear traits of one material; an unknown id falls back to M12 and says so."""
    key = str(material_id or "").upper()
    if key in _WEAR_TRAITS:
        return _WEAR_TRAITS[key]
    traits = _WEAR_TRAITS["M12"]
    return WearTraits(
        material_id=key or "UNKNOWN", family=traits.family, porosity=traits.porosity,
        hardness_mohs=traits.hardness_mohs, toughness=traits.toughness,
        glaze_fraction_of_wall=traits.glaze_fraction_of_wall,
        ref=traits.ref + f"; material {material_id!r} is not in M01..M12, M12 traits are used "
                          f"and the substitution is reported",
    )


def capture_rig_spec() -> CaptureRigSpec:
    """The declared capture rig (HW-H0: one node, rotating Z, manual U, four lamps + polariser)."""
    camera = _camera_spec()
    quality = {
        "blur": SpecValue("blur quality item of the A6 quality vector", DOCUMENTED,
                          ref="docs/a12/v144_project_core.md G5 p199/p236 (line 742/1086)"),
        "exposure": SpecValue("exposure quality item", DOCUMENTED, ref="G5 p236"),
        "coverage": SpecValue("coverage quality item", DOCUMENTED, ref="G5 p236"),
        "occlusion": SpecValue("occlusion quality item", DOCUMENTED, ref="G5 p236"),
        "reconstruction_confidence": SpecValue("reconstruction confidence quality item",
                                               DOCUMENTED, ref="G5 p236"),
        "point_density": SpecValue("point density quality item", DOCUMENTED, ref="G5 p236"),
        "normal_stability": SpecValue("normal stability quality item", DOCUMENTED, ref="G5 p236"),
        "curvature_stability": SpecValue("curvature stability quality item", DOCUMENTED,
                                         ref="G5 p236"),
    }
    recon_floor = {
        "valid_point_fraction_min": RECON_FLOOR_VALID_FRACTION,
        "coordinate_sigma_mm_max": RECON_FLOOR_SIGMA_MM,
        "hole_count_max": RECON_FLOOR_HOLES,
        "hole_radius_mm_max": RECON_FLOOR_HOLE_RADIUS_MM,
    }
    return CaptureRigSpec(
        camera=camera, motion=_MOTION, lights=_LIGHT_MODES,
        lamp_groups=SpecValue(("left", "right", "upper_front", "upper_back"), DOCUMENTED,
                              ref="§4.4 p440 (四组同色温白光：左、右、前上方、后上方，单独开关或调光)"),
        colour_temperature=SpecValue(
            UNKNOWN, UNKNOWN, ref="§4.4 p441 (U6/p1031)",
            note="只要求'同色温''同批白光'；具体色温 K 值文档未明确"),
        cri=SpecValue(90.0, CANDIDATE, ref="§4.4 p442",
                      note="标称 CRI 不低于 90 作为候选，实际用色卡及样片检查"),
        polariser_chain=SpecValue(
            ("LED", "diffuser", "lamp-side polariser", "sample", "lens analyser", "camera"),
            DOCUMENTED, ref="§4.4 p443/p536",
            note="安装顺序 LED→柔光片→灯前偏振片→样本→镜头偏振片→相机；柔光位于光源偏振片前"),
        polariser_auto=SpecValue(False, DOCUMENTED, ref="§4.4 p539/p577",
                                 note="capabilities 明确 polarizer_auto=false；不把软件选择模式当作"
                                      "膜已自动旋转（第一版人工抽插/手动转角）"),
        scale_reference=SpecValue(
            "traceable scale reference in every formal capture (ruler / AprilTag / coded target)",
            DOCUMENTED, ref="p1163",
            note="每次正式采集必须包含可追溯尺度基准，并在重建后自动检查绝对尺度漂移"),
        calibration_per_condition=SpecValue(
            "independent intrinsics per stable lens/resolution/focus condition; no blind sharing",
            DOCUMENTED, ref="p1155/p1163",
            note="焦距、镜头或近摄距离明显变化时禁止盲目共享内参；近摄与全局视为两套独立标定工况"),
        absolute_accuracy=SpecValue(
            "NOT promised at 0.1 mm", DOCUMENTED, ref="§5.9 p1093 / §5.6 p1063",
            note="实拍明确不承诺 0.1 mm 绝对精度；0.10mm 属未来 Gate B 目标"),
        quality_vector=quality, recon_floor=recon_floor,
    )


def iter_spec_values(spec: CaptureRigSpec) -> Iterable[tuple[str, SpecValue]]:
    """(path, value) for every catalogue entry (used by the calibration-list test)."""
    out: list[tuple[str, SpecValue]] = []

    def walk(path: str, node: Any) -> None:
        if isinstance(node, SpecValue):
            out.append((path, node))
            return
        if isinstance(node, Mapping):
            for key in sorted(node, key=str):
                walk(f"{path}.{key}" if path else str(key), node[key])
            return
        if isinstance(node, (list, tuple)):
            for index, item in enumerate(node):
                walk(f"{path}[{index}]", item)

    walk("", spec.as_dict())
    return out
