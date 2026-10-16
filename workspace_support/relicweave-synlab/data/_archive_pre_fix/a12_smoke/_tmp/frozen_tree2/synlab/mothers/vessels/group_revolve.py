"""Revolved vessel family: V01 bowl, V02 deep dish, V03 saucer, V04 cup, V05 stemmed cup,
V06 jar, V07 bottle, V08 amphora, V11 vat, V12 basin.

Each registry entry owns its parameter model and its own construction entry point; the
shared part is only the thick-profile kernel (``shell_profile`` / ``revolve_body``) that
the plan mandates ([R15] SciPy PCHIP + ``trimesh.creation.revolve``).  Every builder below
passes **absolute millimetre** control points, so a parameter that changes the silhouette
changes the mesh; ``applicable["shape_parameters"]`` names the parameters that do.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import Point

from ...errors import ErrorCode, SynLabError
from ...registry import register_vessel
from ..assemblies import (Part, build_vessel, cavity_probe_points, constant_tags,
                          revolve_body)
from ..solids import boolean_union, sweep_tube
from ..tagging import TAG_INDEX, tag_by_polyline
from ..warp import WarpSpec, warp_spec_from_rng
from .common import revolve_charts, shell_profile, wall_points

STAGE = "mothers.vessels.revolve"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diameter_mm: float = Field(..., ge=60.0, le=320.0, description="outer diameter in mm")
    wall_mm: float = Field(4.0, ge=0.15, le=60.0, description="wall thickness in mm")
    base_mm: float = Field(6.5, ge=0.15, le=80.0, description="base thickness in mm")
    warp_amplitude: float = Field(0.02, ge=0.0, le=0.08)
    warp_eccentricity_mm: float = Field(0.8, ge=0.0, le=8.0)
    warp_lobes: int = Field(2, ge=2, le=6)

    def warp(self, rng: np.random.Generator, z_min: float, z_max: float) -> WarpSpec:
        return warp_spec_from_rng(rng, z_min=z_min, z_max=z_max,
                                  amplitude_max=float(self.warp_amplitude),
                                  eccentricity_max_mm=float(self.warp_eccentricity_mm),
                                  allowed_lobes=(int(self.warp_lobes), int(self.warp_lobes) + 1))


def _require_neck(neck_r_mm: float, wall_mm: float, vessel: str) -> None:
    if neck_r_mm <= float(wall_mm) + 0.8:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            f"{vessel}: the neck radius {neck_r_mm:.2f} mm cannot hold a {wall_mm:.2f} mm wall",
            stage=STAGE,
            measurements={"neck_r_mm": float(neck_r_mm), "wall_mm": float(wall_mm),
                          "note": "the cavity must stay open, so a collapsing neck is rejected"},
        )


def base_thickness_limit(depth_mm: float, wall_mm: float, *, fill: float = 2.4) -> float:
    """Largest base thickness that still leaves a cavity in a bowl of this depth.

    A base plate of half the depth fills the dish: the plan's "敞口空腔保留" rule means such a
    request has to be refused.  The limit is stated in millimetres so the failure names the
    parameter instead of surfacing later as a curvature error.
    """
    return max(0.25 * float(depth_mm), float(fill) * float(wall_mm))


def clamp_base_thickness(t_base_mm: float, depth_mm: float, wall_mm: float, *,
                         vessel: str) -> float:
    limit = base_thickness_limit(depth_mm, wall_mm)
    if float(t_base_mm) > limit:
        raise SynLabError(
            ErrorCode.MOTHER_INVALID,
            f"{vessel}: base thickness {t_base_mm:.2f} mm leaves no cavity in a "
            f"{depth_mm:.2f} mm deep vessel (limit {limit:.2f} mm)",
            stage=STAGE,
            measurements={"base_mm": float(t_base_mm), "depth_mm": float(depth_mm),
                          "wall_mm": float(wall_mm), "limit_mm": limit},
        )
    return float(t_base_mm)


def _jsonable_metrics(profile) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in profile.metrics.items():
        if isinstance(value, (bool, np.bool_)):
            out[key] = bool(value)
        elif isinstance(value, (int, float, np.floating, np.integer)):
            out[key] = float(value)
    return out


# ------------------------------------------------------------------------------ V01 bowl
class BowlParams(_Base):
    depth_ratio: float = Field(0.42, ge=0.18, le=0.80, description="depth / diameter")
    rim_flare: float = Field(0.10, ge=-0.45, le=0.60, description="outward rim flare fraction of R")
    foot_ring_ratio: float = Field(0.62, ge=0.0, le=0.92, description="foot ring inner radius / R")
    foot_height_ratio: float = Field(0.06, ge=0.0, le=0.30, description="foot ring height / depth")
    belly: float = Field(0.75, ge=0.35, le=1.6, description="wall shape exponent")


@register_vessel("V01", "碗", param_model=BowlParams,
                 version="1.1",
                 applicable={"family": "revolve", "requires_cavity": True, "min_wall_mm": 1.0,
                             "scale_mm": [80, 300], "components": ["body"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm",
                                                  "depth_ratio", "rim_flare", "foot_ring_ratio",
                                                  "foot_height_ratio", "belly"]},
                 notes="thick revolved bowl, foot ring kept as a real contact band")
def build_bowl(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = BowlParams.model_validate(params)
    R = float(p.diameter_mm) / 2.0
    depth = float(p.depth_ratio) * float(p.diameter_mm)
    t_w = float(p.wall_mm)
    t_b = clamp_base_thickness(float(p.base_mm), depth, t_w, vessel="V01")
    h_foot = float(p.foot_height_ratio) * depth
    z_rim = h_foot + depth
    r_fo = min(0.72 * R, R - t_w - 0.5)
    r_fi = float(p.foot_ring_ratio) * r_fo
    base_pts = [(0.0, t_b / 2.0 + h_foot), (0.45 * r_fi, t_b / 2.0 + 0.97 * h_foot)]
    if h_foot > 0.25 and r_fi > 0.06 * R:
        base_pts += [(0.92 * r_fi, t_b / 2.0 + 0.25 * h_foot),
                     (0.5 * (r_fi + r_fo), t_b / 2.0),
                     (r_fo, t_b / 2.0 + 0.35 * h_foot)]
    else:
        base_pts += [(0.35 * r_fo, t_b / 2.0), (r_fo, t_b / 2.0 + 0.02 * h_foot)]
    wall = wall_points(r_start_mm=r_fo, R_mm=R, z_start=t_b / 2.0 + 0.35 * h_foot,
                       z_rim_mm=z_rim, count=6, exponent=float(p.belly),
                       flare_mm=float(p.rim_flare) * 0.5 * R, flare_from=0.7)
    profile = shell_profile(R_mm=R, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="rounded", rim_bulge=0.35,
                            belly_thickness=1.04, min_wall_mm=1.0, stage=STAGE)
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    return build_vessel(
        [revolve_body(profile)], union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(mesh, tags, profile),
        construct={"kind": "revolve", "profile": "bowl", "wall_pts": wall, "base_pts": base_pts,
                   "R_mm": R, "z_rim_mm": z_rim, "t_wall_mm": t_w, "t_base_mm": t_b},
        meta={"vessel": "V01", "profile_metrics": _jsonable_metrics(profile)},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(profile),
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=1.0, max_wall_mm=max(3.0 * t_b, 40.0), stage="mothers.vessels.V01")


# ------------------------------------------------------------------------- V02 deep dish
class DeepDishParams(_Base):
    depth_mm: float = Field(34.0, ge=8.0, le=120.0)
    base_width_ratio: float = Field(0.42, ge=0.08, le=0.9, description="base width / diameter")
    wall_angle_deg: float = Field(62.0, ge=15.0, le=88.0, description="wall angle from horizontal")
    rim_lip_mm: float = Field(1.6, ge=0.0, le=12.0, description="thickened rim lip")


@register_vessel("V02", "深盘", param_model=DeepDishParams,
                 version="1.1",
                 applicable={"family": "revolve", "requires_cavity": True, "min_wall_mm": 1.0,
                             "scale_mm": [80, 300], "components": ["body"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm", "depth_mm",
                                                  "base_width_ratio", "wall_angle_deg",
                                                  "rim_lip_mm"]},
                 notes="deep dish: conical wall controlled by a real wall angle")
def build_deep_dish(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = DeepDishParams.model_validate(params)
    R = float(p.diameter_mm) / 2.0
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    depth = float(p.depth_mm)
    r_base = float(p.base_width_ratio) * R
    ang = np.deg2rad(float(p.wall_angle_deg))
    r_top = min(R, r_base + depth / max(np.tan(ang), 1e-3))
    r_top = max(r_top, r_base + t_w + 1.0)
    z_rim = t_b / 2.0 + depth
    base_pts = [(0.0, t_b / 2.0), (0.55 * r_base, t_b / 2.0 + 0.55 * t_b)]
    wall = wall_points(r_start_mm=r_base, R_mm=r_top, z_start=t_b / 2.0 + 0.6 * t_b,
                       z_rim_mm=z_rim, count=5, exponent=1.35,
                       flare_mm=float(p.rim_lip_mm) * 0.5, flare_from=0.75)
    profile = shell_profile(R_mm=r_top, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="bevel", rim_bulge=0.25,
                            taper_top=1.0 + float(p.rim_lip_mm) / max(t_w, 1e-6) * 0.25,
                            min_wall_mm=1.0, stage=STAGE)
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    return build_vessel(
        [revolve_body(profile)], union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(mesh, tags, profile),
        construct={"kind": "revolve", "profile": "deep_dish",
                   "wall_angle_deg": float(p.wall_angle_deg), "r_base_mm": r_base,
                   "r_top_mm": r_top, "z_rim_mm": z_rim},
        meta={"vessel": "V02", "profile_metrics": _jsonable_metrics(profile)},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(profile),
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=1.0, max_wall_mm=max(3.0 * t_b, 44.0), stage="mothers.vessels.V02")


# --------------------------------------------------------------------------- V03 saucer
class SaucerParams(_Base):
    depth_mm: float = Field(14.0, ge=4.0, le=45.0)
    rim_wave_mm: float = Field(1.2, ge=0.0, le=10.0, description="non-axisymmetric rim undulation")
    rim_wave_lobes: int = Field(6, ge=3, le=12)
    base_curvature: float = Field(0.35, ge=0.0, le=1.0, description="dished base fraction of depth")
    rim_lip_ratio: float = Field(0.10, ge=0.0, le=0.4)


@register_vessel("V03", "浅碟", param_model=SaucerParams,
                 version="1.1",
                 applicable={"family": "revolve", "requires_cavity": True, "min_wall_mm": 0.9,
                             "scale_mm": [80, 260], "components": ["body"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm", "depth_mm",
                                                  "rim_wave_mm", "rim_wave_lobes",
                                                  "base_curvature", "rim_lip_ratio"]},
                 notes="shallow saucer with a dished base and a wavy rim")
def build_saucer(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = SaucerParams.model_validate(params)
    R = float(p.diameter_mm) / 2.0
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    depth = float(p.depth_mm)
    # A base plate of half the depth fills the dish: the plan's open-cavity rule means such a
    # request is refused here, naming the parameter instead of surfacing as a curvature error.
    t_b = clamp_base_thickness(t_b, depth, t_w, vessel="V03")
    dip = float(p.base_curvature) * depth
    z_rim = t_b / 2.0 + depth
    base_pts = [(0.0, t_b / 2.0 - dip), (0.35 * R, t_b / 2.0 - dip * 0.75),
                (0.62 * R, t_b / 2.0 - dip * 0.25), (0.82 * R, t_b / 2.0)]
    wall = wall_points(r_start_mm=0.82 * R, R_mm=R, z_start=t_b / 2.0, z_rim_mm=z_rim, count=4,
                       exponent=0.65, flare_mm=float(p.rim_lip_ratio) * R, flare_from=0.7)
    profile = shell_profile(R_mm=R, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="rounded", rim_bulge=0.5,
                            min_wall_mm=0.9, stage=STAGE)
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    warp.rim_wave_mm = float(p.rim_wave_mm)
    warp.rim_wave_lobes = int(p.rim_wave_lobes)
    warp.meta["rim_wave_source"] = "SaucerParams.rim_wave_mm"
    return build_vessel(
        [revolve_body(profile)], union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(mesh, tags, profile),
        construct={"kind": "revolve", "profile": "saucer", "base_dip_mm": dip,
                   "rim_wave_mm": float(p.rim_wave_mm),
                   "rim_wave_lobes": int(p.rim_wave_lobes)},
        meta={"vessel": "V03", "profile_metrics": _jsonable_metrics(profile)},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(profile),
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=0.9, max_wall_mm=max(3.0 * t_b, 30.0), stage="mothers.vessels.V03")


# ------------------------------------------------------------------------------- V04 cup
class CupParams(_Base):
    height_mm: float = Field(95.0, ge=30.0, le=240.0)
    belly_ratio: float = Field(1.0, ge=0.6, le=1.35, description="belly diameter / mouth diameter")
    with_handle: bool = Field(True)
    handle_thickness_mm: float = Field(7.0, ge=3.0, le=20.0)
    handle_span_ratio: float = Field(0.85, ge=0.35, le=1.2)


@register_vessel("V04", "杯", param_model=CupParams,
                 version="1.1",
                 applicable={"family": "revolve+attachment", "requires_cavity": True,
                             "min_wall_mm": 1.0, "scale_mm": [50, 200],
                             "components": ["body", "handle"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm",
                                                  "height_mm", "belly_ratio",
                                                  "handle_thickness_mm", "handle_span_ratio"]},
                 notes="revolved cup with an optional swept handle (volumetric overlap at the root)")
def build_cup(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = CupParams.model_validate(params)
    R = float(p.diameter_mm) / 2.0
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    h = float(p.height_mm)
    r_belly = max(R * float(p.belly_ratio), R * 0.6)
    z_rim = t_b / 2.0 + h
    base_pts = [(0.0, t_b / 2.0), (0.45 * R, t_b / 2.0 + 0.14 * t_b)]
    wall = wall_points(r_start_mm=0.45 * R, R_mm=r_belly, z_start=t_b / 2.0 + 0.18 * t_b,
                       z_rim_mm=z_rim, count=6, exponent=0.85)
    profile = shell_profile(R_mm=r_belly, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="flat",
                            min_wall_mm=1.0, stage=STAGE)
    parts = [revolve_body(profile)]
    attachment_paths: list[dict[str, Any]] = []
    if bool(p.with_handle):
        handle, path = _handle_part(r_belly, t_b / 2.0 + float(p.handle_span_ratio) * h,
                                    float(p.handle_span_ratio), float(p.handle_thickness_mm),
                                    component_id=1)
        parts.append(handle)
        attachment_paths.append({"name": "handle", "path_xyz": path, "component_id": 1,
                                 "tol_mm": float(p.handle_thickness_mm) * 1.1})
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    return build_vessel(
        parts, union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(
            mesh, tags, profile, attachment_paths=attachment_paths),
        construct={"kind": "revolve+attachment", "profile": "cup",
                   "handle": bool(p.with_handle),
                   "handle_thickness_mm": float(p.handle_thickness_mm),
                   "attachment_paths": attachment_paths},
        meta={"vessel": "V04", "profile_metrics": _jsonable_metrics(profile),
              "attachments": [a["name"] for a in attachment_paths]},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(profile),
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=1.0, max_wall_mm=max(4.0 * t_b, 46.0), stage="mothers.vessels.V04")


def _handle_part(R_mm: float, z_attach: float, span_ratio: float, thickness_mm: float, *,
                 component_id: int = 1, name: str = "handle") -> tuple[Part, np.ndarray]:
    """Closed swept handle whose two ends overlap the body volume (root thickness is real)."""
    R = float(R_mm)
    r_tube = max(0.5 * float(thickness_mm), 1.5)
    z0 = float(z_attach)
    reach = R * (1.0 + 0.55 * float(span_ratio))
    n = 18
    t = np.linspace(0.0, 1.0, n)
    ang = np.pi * t
    path = np.column_stack([
        R * 0.97 + (reach - R * 0.97) * np.sin(ang) ** 1.1,
        np.zeros(n),
        z0 + (reach - R) * 0.85 * (1.0 - np.cos(ang)) * 0.5,
    ])
    path[0, 0] = R * 0.86
    path[-1, 0] = R * 0.86
    path[-1, 2] = z0 - R * 0.55
    mesh = sweep_tube(Point(0.0, 0.0).buffer(r_tube, quad_segs=10), path, cap=True,
                      stage="mothers.vessels.handle")
    return Part(mesh=mesh, tags=constant_tags(mesh, "attachment"), component_id=int(component_id),
                name=name), path


# ------------------------------------------------------------------------ V05 stemmed cup
class StemmedCupParams(_Base):
    cup_depth_ratio: float = Field(0.55, ge=0.2, le=0.95, description="cup depth / cup diameter")
    belly_ratio: float = Field(0.95, ge=0.55, le=1.3)
    stem_height_ratio: float = Field(0.55, ge=0.12, le=1.4, description="stem height / cup diameter")
    stem_root_ratio: float = Field(0.30, ge=0.08, le=0.7, description="stem waist / cup radius")
    foot_disc_ratio: float = Field(0.55, ge=0.2, le=0.95, description="foot disc radius / cup radius")


@register_vessel("V05", "高足杯", param_model=StemmedCupParams,
                 version="1.1",
                 applicable={"family": "revolve+revolve", "requires_cavity": True,
                             "min_wall_mm": 1.0, "scale_mm": [60, 260],
                             "components": ["cup", "stem"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm",
                                                  "cup_depth_ratio", "belly_ratio",
                                                  "stem_height_ratio", "stem_root_ratio",
                                                  "foot_disc_ratio"]},
                 notes="cup shell on a closed high stem with a flared foot disc")
def build_stemmed_cup(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = StemmedCupParams.model_validate(params)
    R = float(p.diameter_mm) / 2.0
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    depth = float(p.cup_depth_ratio) * float(p.diameter_mm)
    stem_h = float(p.stem_height_ratio) * float(p.diameter_mm)
    r_waist = max(float(p.stem_root_ratio) * R, t_w * 1.4)
    r_foot = max(float(p.foot_disc_ratio) * R, r_waist * 1.3)
    r_belly = max(R * float(p.belly_ratio), R * 0.55)
    z_cup_bottom = stem_h
    cup_base = [(0.0, z_cup_bottom + t_b / 2.0),
                (0.45 * r_belly, z_cup_bottom + t_b / 2.0 + 0.16 * t_b)]
    cup_wall = wall_points(r_start_mm=0.45 * r_belly, R_mm=r_belly,
                           z_start=z_cup_bottom + t_b / 2.0 + 0.2 * t_b,
                           z_rim_mm=z_cup_bottom + depth, count=5, exponent=0.8)
    cup = shell_profile(R_mm=r_belly, z_rim_mm=z_cup_bottom + depth, base_pts=cup_base,
                        wall_pts=cup_wall,
                        t_base_mm=clamp_base_thickness(t_b, depth, t_w, vessel="V05"),
                        t_wall_mm=t_w, rim_mode="flat", min_wall_mm=1.0,
                        stage="mothers.vessels.V05")
    # closed stem: a solid rod with a flared foot disc, revolved as a closed region
    stem_closed = np.array([
        [0.0, 0.0], [r_foot, 0.0], [r_foot, 0.62 * t_b], [r_waist, 0.62 * stem_h],
        [r_waist * 1.18, stem_h + 0.45 * t_b], [0.0, stem_h + 0.45 * t_b],
    ], dtype=np.float64)
    seg = np.linalg.norm(np.diff(stem_closed, axis=0), axis=1)
    from ..geometry import LabelledPolyline

    poly = LabelledPolyline(stem_closed, np.array(["outer_wall"] * len(seg), dtype=object),
                            np.concatenate([[0.0], np.cumsum(seg)]))
    stem_mesh = trimesh.creation.revolve(stem_closed, sections=96)
    stem_mesh, _ = _cleanup(stem_mesh)
    stem_tags, _ = tag_by_polyline(stem_mesh, poly, mode="revolve")
    stem_tags = np.where(stem_tags == TAG_INDEX["outer_wall"], TAG_INDEX["attachment"],
                         stem_tags).astype(np.int32)
    stem = Part(mesh=stem_mesh, tags=stem_tags, component_id=1, name="stem")
    warp = p.warp(rng, 0.0, cup.z_rim)
    cut = np.linspace(0.0, 1.0, 9)
    stem_path = np.column_stack([
        r_waist * (1.0 + 0.25 * np.sin(np.pi * cut)),
        np.zeros_like(cut),
        stem_h * cut,
    ])
    stem_paths = [{"name": "stem", "path_xyz": stem_path, "component_id": 1,
                   "tol_mm": max(r_waist * 0.6, 4.0)}]
    return build_vessel(
        [revolve_body(cup), stem], union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(
            mesh, tags, cup, attachment_paths=stem_paths),
        construct={"kind": "revolve+revolve", "profile": "stemmed_cup",
                   "stem_height_mm": stem_h, "stem_waist_mm": r_waist, "foot_disc_mm": r_foot,
                   "attachment_paths": [{"name": "stem", "component_id": 1}]},
        meta={"vessel": "V05", "profile_metrics": _jsonable_metrics(cup),
              "attachments": ["stem"]},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(cup),
        design_thickness=(cup.thickness_min_mm, cup.thickness_max_mm),
        min_wall_mm=1.0, max_wall_mm=max(4.0 * t_b, 46.0), stage="mothers.vessels.V05")


def _cleanup(mesh: trimesh.Trimesh):
    from ..solids import cleanup

    return cleanup(mesh)


# ------------------------------------------------------------------------------- V06 jar
class JarParams(_Base):
    height_mm: float = Field(180.0, ge=60.0, le=420.0)
    belly_ratio: float = Field(1.0, ge=0.6, le=1.4, description="belly diameter / mouth diameter")
    shoulder_position: float = Field(0.62, ge=0.3, le=0.9, description="shoulder height fraction")
    mouth_ratio: float = Field(0.55, ge=0.25, le=0.95, description="mouth diameter / belly diameter")


@register_vessel("V06", "罐", param_model=JarParams,
                 version="1.1",
                 applicable={"family": "revolve", "requires_cavity": True, "min_wall_mm": 1.2,
                             "scale_mm": [80, 340], "components": ["body"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm",
                                                  "height_mm", "belly_ratio",
                                                  "shoulder_position", "mouth_ratio"]},
                 notes="shoulder-belly-mouth jar profile with a real shoulder position")
def build_jar(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = JarParams.model_validate(params)
    mouth = float(p.diameter_mm)
    r_belly = 0.5 * mouth * float(p.belly_ratio)
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    h = float(p.height_mm)
    r_mouth = 0.5 * mouth * float(p.mouth_ratio)
    _require_neck(r_mouth, t_w, "V06")
    z_sh = t_b / 2.0 + float(p.shoulder_position) * h
    z_rim = t_b / 2.0 + h
    r_base = 0.55 * r_belly
    base_pts = [(0.0, t_b / 2.0), (0.55 * r_base, t_b / 2.0 + 0.55 * t_b)]
    belly_wall = wall_points(r_start_mm=r_base, R_mm=r_belly, z_start=t_b / 2.0 + 0.6 * t_b,
                             z_rim_mm=z_sh, count=4, exponent=0.62)
    shoulder = _shoulder_cone(r_belly, r_mouth, z_sh, z_rim, t_w)
    wall = belly_wall + shoulder
    profile = shell_profile(R_mm=r_belly, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="rounded", rim_bulge=0.45,
                            min_wall_mm=1.2, stage="mothers.vessels.V06")
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    return build_vessel(
        [revolve_body(profile)], union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(mesh, tags, profile),
        construct={"kind": "revolve", "profile": "jar", "belly_r_mm": r_belly,
                   "shoulder_z_mm": z_sh, "mouth_r_mm": r_mouth, "wall_pts": wall},
        meta={"vessel": "V06", "profile_metrics": _jsonable_metrics(profile)},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(profile),
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=1.2, max_wall_mm=max(3.0 * t_b, 50.0), stage="mothers.vessels.V06")


def _shoulder_cone(r_belly: float, r_top: float, z_sh: float, z_rim: float,
                   t_wall: float) -> list[tuple[float, float]]:
    """Monotone control points of a real shoulder cone from the belly up to the mouth."""
    span = max(z_rim - z_sh, t_wall)
    pts: list[tuple[float, float]] = []
    for i in range(1, 4):
        u = i / 3.0
        pts.append((float(r_belly + (r_top - r_belly) * (u ** 0.7)), float(z_sh + span * u)))
    return pts


# ----------------------------------------------------------------------------- V07 bottle
class BottleParams(_Base):
    height_mm: float = Field(240.0, ge=80.0, le=520.0)
    belly_ratio: float = Field(1.0, ge=0.6, le=1.5)
    neck_length_ratio: float = Field(0.32, ge=0.08, le=0.6, description="neck length / height")
    neck_ratio: float = Field(0.30, ge=0.12, le=0.7, description="neck diameter / belly diameter")
    shoulder_angle_deg: float = Field(52.0, ge=15.0, le=85.0)


@register_vessel("V07", "瓶", param_model=BottleParams,
                 version="1.1",
                 applicable={"family": "revolve", "requires_cavity": True, "min_wall_mm": 1.2,
                             "scale_mm": [100, 380], "components": ["body"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm",
                                                  "height_mm", "belly_ratio",
                                                  "neck_length_ratio", "neck_ratio",
                                                  "shoulder_angle_deg"]},
                 notes="neck-shoulder-belly bottle; the cavity must survive the long neck")
def build_bottle(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = BottleParams.model_validate(params)
    belly = float(p.diameter_mm)
    r_belly = 0.5 * belly * float(p.belly_ratio)
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    h = float(p.height_mm)
    neck_len = float(p.neck_length_ratio) * h
    z_neck = t_b / 2.0 + h - neck_len
    z_rim = t_b / 2.0 + h
    r_neck = 0.5 * float(p.neck_ratio) * belly
    _require_neck(r_neck, t_w, "V07")
    r_base = 0.6 * r_belly
    ang = np.deg2rad(float(p.shoulder_angle_deg))
    shoulder_rise = max((r_belly - r_neck) * np.tan(ang) * 0.35, 1e-3)
    z_shoulder_end = max(min(z_neck, t_b / 2.0 + shoulder_rise + t_b), t_b / 2.0 + 2.0)
    base_pts = [(0.0, t_b / 2.0), (0.55 * r_base, t_b / 2.0 + 0.55 * t_b)]
    wall = wall_points(r_start_mm=r_base, R_mm=r_belly, z_start=t_b / 2.0 + 0.6 * t_b,
                       z_rim_mm=z_shoulder_end, count=4, exponent=0.72)
    wall += _shoulder_cone(r_belly, r_neck, z_shoulder_end, z_rim, t_w)
    profile = shell_profile(R_mm=r_belly, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="bevel", rim_bulge=1.2,
                            belly_thickness=1.02, min_wall_mm=1.2,
                            stage="mothers.vessels.V07")
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    return build_vessel(
        [revolve_body(profile)], union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(mesh, tags, profile),
        construct={"kind": "revolve", "profile": "bottle", "belly_r_mm": r_belly,
                   "neck_r_mm": r_neck, "neck_z_mm": z_neck,
                   "shoulder_angle_deg": float(p.shoulder_angle_deg), "wall_pts": wall},
        meta={"vessel": "V07", "profile_metrics": _jsonable_metrics(profile)},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(profile),
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=1.2, max_wall_mm=max(3.0 * t_b, 55.0), stage="mothers.vessels.V07")


# -------------------------------------------------------------------------- V08 amphora
class AmphoraParams(_Base):
    height_mm: float = Field(230.0, ge=80.0, le=480.0)
    belly_ratio: float = Field(1.0, ge=0.6, le=1.5)
    neck_ratio: float = Field(0.34, ge=0.14, le=0.7)
    ear_arc_deg: float = Field(190.0, ge=80.0, le=300.0, description="ear sweep angle")
    ear_rise_ratio: float = Field(0.62, ge=0.15, le=0.95, description="ear height / neck+shoulder")
    ear_root_mm: float = Field(9.0, ge=3.0, le=26.0, description="ear root cross-section")


@register_vessel("V08", "双耳瓶", param_model=AmphoraParams,
                 version="1.1",
                 applicable={"family": "revolve+attachment", "requires_cavity": True,
                             "min_wall_mm": 1.2, "scale_mm": [90, 380],
                             "components": ["body", "ear_l", "ear_r"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm",
                                                  "height_mm", "belly_ratio", "neck_ratio",
                                                  "ear_arc_deg", "ear_rise_ratio", "ear_root_mm"]},
                 notes="bottle body with two swept ears; every ear has a volumetric root")
def build_amphora(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = AmphoraParams.model_validate(params)
    belly = float(p.diameter_mm)
    r_belly = 0.5 * belly * float(p.belly_ratio)
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    h = float(p.height_mm)
    r_neck = 0.5 * float(p.neck_ratio) * belly
    _require_neck(r_neck, t_w, "V08")
    z_rim = t_b / 2.0 + h
    z_shoulder = t_b / 2.0 + 0.55 * h
    r_base = 0.5 * r_belly
    base_pts = [(0.0, t_b / 2.0), (0.55 * r_base, t_b / 2.0 + 0.6 * t_b)]
    wall = wall_points(r_start_mm=r_base, R_mm=r_belly, z_start=t_b / 2.0 + 0.7 * t_b,
                       z_rim_mm=z_shoulder, count=4, exponent=0.65)
    wall += _shoulder_cone(r_belly, r_neck, z_shoulder, z_rim, t_w)
    profile = shell_profile(R_mm=r_belly, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="rounded", rim_bulge=0.5,
                            min_wall_mm=1.2, stage="mothers.vessels.V08")
    parts = [revolve_body(profile)]
    paths: list[dict[str, Any]] = []
    z_root = max(z_rim - float(p.ear_rise_ratio) * (z_rim - z_shoulder), z_shoulder + t_b)
    for sign, name in ((+1.0, "ear_r"), (-1.0, "ear_l")):
        ear, path = _ear_part(r_belly, z_root, z_rim, float(p.ear_arc_deg),
                              float(p.ear_root_mm), sign=sign, component_id=len(parts),
                              name=name)
        parts.append(ear)
        paths.append({"name": name, "path_xyz": path, "component_id": len(parts) - 1,
                      "tol_mm": float(p.ear_root_mm) * 1.2})
    cavity = cavity_probe_points(profile)
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    return build_vessel(
        parts, union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(
            mesh, tags, profile, attachment_paths=paths),
        construct={"kind": "revolve+attachment", "profile": "amphora",
                   "belly_r_mm": r_belly, "neck_r_mm": r_neck, "ear_root_mm": float(p.ear_root_mm),
                   "ear_arc_deg": float(p.ear_arc_deg), "attachment_paths": paths},
        meta={"vessel": "V08", "profile_metrics": _jsonable_metrics(profile),
              "attachments": [a["name"] for a in paths]},
        requires_cavity=True, cavity_probe_points=cavity,
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=1.2, max_wall_mm=max(4.0 * t_b, 60.0), stage="mothers.vessels.V08")


def _ear_part(r_belly: float, z_root: float, z_rim: float, arc_deg: float, root_mm: float, *,
              sign: float = 1.0, component_id: int = 1,
              name: str = "ear") -> tuple[Part, np.ndarray]:
    """Swept ear handle whose two roots sit inside the body wall (volumetric overlap).

    The path leaves the wall radially (``y = 0`` at both ends, ``y`` growing outwards in the
    middle) and drops from the neck down to the shoulder, so the swept tube crosses the wall
    surface instead of only touching it: the boolean union then has a real root cross-section
    to measure, and the ear is a closed volumetric attachment rather than a decal.
    """
    r_tube = max(0.5 * float(root_mm), 1.8)
    rise = max(float(z_rim) - float(z_root), 2.4 * r_tube)
    n = 24
    phi = np.linspace(0.0, np.pi, n)
    reach = max(float(r_belly) * 0.55, 2.2 * r_tube)
    y_out = reach * (float(arc_deg) / 180.0)
    x = np.full(n, float(sign) * (float(r_belly) - 0.5 * float(root_mm)))
    path = np.column_stack([x, y_out * np.sin(phi), float(z_rim) - rise * phi / np.pi])
    mesh = sweep_tube(Point(0.0, 0.0).buffer(r_tube, quad_segs=10), path, cap=True,
                      stage="mothers.vessels.ear")
    return Part(mesh=mesh, tags=constant_tags(mesh, "attachment"),
                component_id=int(component_id), name=name), path


# -------------------------------------------------------------------------------- V11 vat
class VatParams(_Base):
    height_mm: float = Field(210.0, ge=70.0, le=420.0)
    body_to_mouth_ratio: float = Field(1.85, ge=1.05, le=3.2, description="belly / mouth diameter")
    shoulder_arc: float = Field(0.55, ge=0.1, le=0.95, description="shoulder roundness fraction")
    base_ratio: float = Field(0.45, ge=0.12, le=0.85, description="base diameter / mouth diameter")


@register_vessel("V11", "坛", param_model=VatParams,
                 version="1.1",
                 applicable={"family": "revolve", "requires_cavity": True, "min_wall_mm": 1.4,
                             "scale_mm": [100, 360], "components": ["body"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm",
                                                  "height_mm", "body_to_mouth_ratio",
                                                  "shoulder_arc", "base_ratio"]},
                 notes="large belly with a short neck; belly/mouth ratio and shoulder arc are real")
def build_vat(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = VatParams.model_validate(params)
    mouth = float(p.diameter_mm)
    r_mouth = 0.5 * mouth
    r_belly = r_mouth * float(p.body_to_mouth_ratio)
    r_base = 0.5 * float(p.base_ratio) * mouth
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    h = float(p.height_mm)
    _require_neck(r_mouth, t_w, "V11")
    z_rim = t_b / 2.0 + h
    arc = float(p.shoulder_arc)
    z_shoulder = t_b / 2.0 + (1.0 - 0.35 * arc) * h
    base_pts = [(0.0, t_b / 2.0), (0.55 * r_base, t_b / 2.0 + 0.6 * t_b)]
    wall = wall_points(r_start_mm=r_base, R_mm=r_belly, z_start=t_b / 2.0 + 0.7 * t_b,
                       z_rim_mm=z_shoulder, count=4, exponent=0.55)
    wall += _shoulder_cone(r_belly, r_mouth, z_shoulder, z_rim, t_w)
    profile = shell_profile(R_mm=r_belly, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="rounded", rim_bulge=0.4,
                            min_wall_mm=1.4, stage="mothers.vessels.V11")
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    return build_vessel(
        [revolve_body(profile)], union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(mesh, tags, profile),
        construct={"kind": "revolve", "profile": "vat", "belly_r_mm": r_belly,
                   "mouth_r_mm": r_mouth, "base_r_mm": r_base, "shoulder_z_mm": z_shoulder},
        meta={"vessel": "V11", "profile_metrics": _jsonable_metrics(profile)},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(profile),
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=1.4, max_wall_mm=max(3.0 * t_b, 60.0), stage="mothers.vessels.V11")


# ------------------------------------------------------------------------------ V12 basin
class BasinParams(_Base):
    depth_mm: float = Field(70.0, ge=20.0, le=200.0)
    base_to_mouth_ratio: float = Field(0.55, ge=0.12, le=0.95, description="base diameter / mouth")
    foot_height_ratio: float = Field(0.05, ge=0.0, le=0.25)
    rim_thickness_factor: float = Field(1.25, ge=0.8, le=3.0)


@register_vessel("V12", "盆", param_model=BasinParams,
                 version="1.1",
                 applicable={"family": "revolve", "requires_cavity": True, "min_wall_mm": 1.0,
                             "scale_mm": [120, 360], "components": ["body"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm", "depth_mm",
                                                  "base_to_mouth_ratio", "foot_height_ratio",
                                                  "rim_thickness_factor"]},
                 notes="wide thin-walled basin: base/mouth ratio and rim thickening are real")
def build_basin(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = BasinParams.model_validate(params)
    R = float(p.diameter_mm) / 2.0
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    depth = float(p.depth_mm)
    r_base = float(p.base_to_mouth_ratio) * R
    h_foot = float(p.foot_height_ratio) * depth
    z_rim = h_foot + depth
    base_pts = [(0.0, t_b / 2.0 + h_foot), (0.6 * r_base, t_b / 2.0 + 0.85 * h_foot)]
    if h_foot > 0.25:
        base_pts += [(0.85 * r_base, t_b / 2.0), (r_base, t_b / 2.0 + 0.25 * h_foot)]
    else:
        base_pts += [(r_base, t_b / 2.0)]
    wall = wall_points(r_start_mm=r_base, R_mm=R, z_start=t_b / 2.0 + 0.3 * h_foot + 0.6,
                       z_rim_mm=z_rim, count=5, exponent=0.72, flare_mm=0.03 * R, flare_from=0.8)
    profile = shell_profile(R_mm=R, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="rounded", rim_bulge=0.3,
                            taper_top=float(p.rim_thickness_factor), min_wall_mm=1.0,
                            stage="mothers.vessels.V12")
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    return build_vessel(
        [revolve_body(profile)], union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(mesh, tags, profile),
        construct={"kind": "revolve", "profile": "basin", "base_r_mm": r_base,
                   "z_rim_mm": z_rim, "foot_height_mm": h_foot},
        meta={"vessel": "V12", "profile_metrics": _jsonable_metrics(profile)},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(profile),
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=1.0, max_wall_mm=max(3.0 * t_b, 42.0), stage="mothers.vessels.V12")


__all__ = [
    "BowlParams", "DeepDishParams", "SaucerParams", "CupParams", "StemmedCupParams",
    "JarParams", "BottleParams", "AmphoraParams", "VatParams", "BasinParams",
    "build_bowl", "build_deep_dish", "build_saucer", "build_cup", "build_stemmed_cup",
    "build_jar", "build_bottle", "build_amphora", "build_vat", "build_basin",
]
