"""Composite family: V09 ewer, V10 lidded pot, V14 lid, V15 lamp, V16 censer, V17 flower pot,
V23 figurine.

These vessels need a second closed body (spout, lid, legs, spout lip) or a boolean
operation (drainage holes, censer vents), so each builder prepares several *parts* with
their own face tags and hands them to :func:`synlab.mothers.assemblies.build_vessel`:

* a spout keeps a real bore (a holed cross-section swept along the path), so the tube is not
  a solid rod and the cavity stays open (plan 7.2);
* a lid is an independent pre-break component: it is a separate part with its own
  ``component_id`` and its own contact band, so the original contact is never reported as a
  fresh fracture R2 relation (plan 7.2);
* feet and handles are closed bodies that overlap the belly volume, so the boolean union has
  a real root cross-section to measure.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import Point, Polygon

from ...errors import ErrorCode, SynLabError
from ...registry import register_vessel
from ..assemblies import (Part, build_vessel, cavity_probe_points, constant_tags,
                          revolve_body)
from ..solids import (boolean_difference, cleanup, combine_solids, manifold_status,
                      sweep_tube)
from ..tagging import TAG_INDEX
from ..warp import warp_spec_from_rng
from .common import revolve_charts, shell_profile, wall_points
from .group_sheet import superquadric

STAGE = "mothers.vessels.composite"


class _WarpBase(BaseModel):
    """The low-amplitude deformation shared by every composite vessel (plan 7.1 step 6)."""

    model_config = ConfigDict(extra="forbid")

    warp_amplitude: float = Field(0.02, ge=0.0, le=0.08)
    warp_eccentricity_mm: float = Field(0.8, ge=0.0, le=8.0)
    warp_lobes: int = Field(2, ge=2, le=6)

    def warp(self, rng: np.random.Generator, z_min: float, z_max: float):
        return warp_spec_from_rng(rng, z_min=z_min, z_max=z_max,
                                  amplitude_max=float(self.warp_amplitude),
                                  eccentricity_max_mm=float(self.warp_eccentricity_mm),
                                  allowed_lobes=(int(self.warp_lobes), int(self.warp_lobes) + 1))


class _Base(_WarpBase):
    diameter_mm: float = Field(..., ge=40.0, le=320.0)
    wall_mm: float = Field(4.0, ge=0.15, le=60.0)
    base_mm: float = Field(6.5, ge=0.15, le=80.0)


def _jsonable_metrics(payload: Any) -> dict[str, Any]:
    """Flatten numpy scalars of a profile metrics mapping (or of a plain dict)."""
    metrics = payload.metrics if hasattr(payload, "metrics") else dict(payload or {})
    out: dict[str, Any] = {}
    for key, value in metrics.items():
        if isinstance(value, (bool, np.bool_)):
            out[key] = bool(value)
        elif isinstance(value, (int, float, np.floating, np.integer)):
            out[key] = float(value)
    return out


def _require_neck(neck_r_mm: float, wall_mm: float, vessel: str) -> None:
    if neck_r_mm <= float(wall_mm) + 0.8:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"{vessel}: the neck radius {neck_r_mm:.2f} mm cannot hold a "
                          f"{wall_mm:.2f} mm wall",
                          stage=STAGE,
                          measurements={"neck_r_mm": float(neck_r_mm), "wall_mm": float(wall_mm)})


def _annulus(outer_r: float, inner_r: float, *, segments: int = 24) -> Polygon:
    outer = Point(0.0, 0.0).buffer(float(outer_r), quad_segs=max(6, segments // 4))
    hole = Point(0.0, 0.0).buffer(float(inner_r), quad_segs=max(6, segments // 4))
    if inner_r <= 1e-6:
        return outer
    return outer.difference(hole)


def _spout_part(*, r_belly: float, z_attach: float, length_mm: float, bore_mm: float,
                angle_deg: float, component_id: int = 1) -> tuple[Part, np.ndarray]:
    """Thick spout: an annular cross-section swept upwards, so the bore stays open."""
    outer_r = max(0.5 * float(bore_mm) + 1.6, 1.8)
    inner_r = max(0.5 * float(bore_mm), 0.6)
    if inner_r >= outer_r - 0.7:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "spout wall would collapse: bore too wide for the requested wall",
                          stage=STAGE,
                          measurements={"bore_mm": float(bore_mm), "outer_r_mm": outer_r})
    angle = np.deg2rad(float(np.clip(angle_deg, 0.0, 80.0)))
    n = 16
    t = np.linspace(0.0, 1.0, n)
    reach = float(length_mm)
    path = np.column_stack([
        float(r_belly) * 0.90 + reach * t * np.sin(angle),
        np.zeros(n),
        float(z_attach) + reach * t * np.cos(angle),
    ])
    # the root sits inside the wall so the union has a volumetric overlap
    path[0, 0] = float(r_belly) * 0.80
    section = _annulus(outer_r, inner_r)
    mesh = sweep_tube(section, path, cap=True, stage="mothers.vessels.spout")
    return Part(mesh=mesh, tags=constant_tags(mesh, "attachment"),
                component_id=int(component_id), name="spout"), path


def _foot_part(*, r_belly: float, theta: float, height_mm: float, root_mm: float,
               component_id: int = 2) -> Part:
    """One closed leg that reaches into the belly volume (real root, no floating contact)."""
    r_leg = max(0.5 * float(root_mm), 1.6)
    height = max(float(height_mm), r_leg)
    cylinder = trimesh.creation.cylinder(radius=r_leg, height=height + 2.0 * r_leg, sections=24)
    tip = max(r_leg * 0.55, 0.6)
    cone = trimesh.creation.cone(radius=r_leg, height=r_leg * 1.6, sections=24)
    cone.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1.0, 0.0, 0.0]))
    cone.apply_translation([0.0, 0.0, -0.5 * height - r_leg * 1.2])
    leg = trimesh.util.concatenate([cylinder, cone])
    leg, _ = cleanup(leg)
    radial = float(r_belly) * 0.62
    leg.apply_translation([radial * np.cos(theta), radial * np.sin(theta),
                           0.5 * height - r_leg * 0.5])
    if not leg.is_watertight:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "censer leg is not watertight", stage=STAGE)
    return Part(mesh=leg, tags=constant_tags(leg, "attachment"),
                component_id=int(component_id), name=f"foot_{int(np.rad2deg(theta))}")


# -------------------------------------------------------------------------------- V09 ewer
class EwerParams(_Base):
    height_mm: float = Field(180.0, ge=60.0, le=380.0)
    belly_ratio: float = Field(1.0, ge=0.55, le=1.4)
    neck_ratio: float = Field(0.42, ge=0.16, le=0.8)
    spout_length_mm: float = Field(70.0, ge=20.0, le=180.0)
    spout_bore_mm: float = Field(14.0, ge=4.0, le=40.0)
    spout_angle_deg: float = Field(38.0, ge=5.0, le=75.0)
    handle_span_ratio: float = Field(0.75, ge=0.3, le=1.3)


@register_vessel("V09", "壶", param_model=EwerParams,
                 version="1.1",
                 applicable={"family": "revolve+attachment", "requires_cavity": True,
                             "min_wall_mm": 1.2, "scale_mm": [60, 320],
                             "components": ["body", "spout", "handle"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm",
                                                  "height_mm", "belly_ratio", "neck_ratio",
                                                  "spout_length_mm", "spout_bore_mm",
                                                  "spout_angle_deg", "handle_span_ratio"]},
                 notes="ewer with a thick handle and a spout that keeps a real bore")
def build_ewer(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = EwerParams.model_validate(params)
    R = float(p.diameter_mm) / 2.0
    r_belly = R * float(p.belly_ratio)
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    h = float(p.height_mm)
    r_neck = r_belly * float(p.neck_ratio)
    _require_neck(r_neck, t_w, "V09")
    z_rim = t_b / 2.0 + h
    z_shoulder = t_b / 2.0 + 0.58 * h
    r_base = 0.55 * r_belly
    base_pts = [(0.0, t_b / 2.0), (0.55 * r_base, t_b / 2.0 + 0.6 * t_b)]
    wall = wall_points(r_start_mm=r_base, R_mm=r_belly, z_start=t_b / 2.0 + 0.7 * t_b,
                       z_rim_mm=z_shoulder, count=4, exponent=0.68)
    for i in range(1, 4):
        u = i / 3.0
        wall.append((float(r_belly + (r_neck - r_belly) * (u ** 0.7)),
                     float(z_shoulder + (z_rim - z_shoulder) * u)))
    profile = shell_profile(R_mm=r_belly, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="bevel", rim_bulge=0.9,
                            min_wall_mm=1.2, stage="mothers.vessels.V09")
    parts = [revolve_body(profile)]
    paths: list[dict[str, Any]] = []
    spout, spout_path = _spout_part(r_belly=r_belly, z_attach=t_b / 2.0 + 0.42 * h,
                                    length_mm=float(p.spout_length_mm),
                                    bore_mm=float(p.spout_bore_mm),
                                    angle_deg=float(p.spout_angle_deg), component_id=1)
    parts.append(spout)
    paths.append({"name": "spout", "path_xyz": spout_path, "component_id": 1,
                  "tol_mm": float(p.spout_bore_mm)})
    handle, handle_path = _handle_part(r_belly, t_b / 2.0 + float(p.handle_span_ratio) * h,
                                       float(p.handle_span_ratio), max(1.6 * t_w, 5.0),
                                       component_id=2, name="handle")
    parts.append(handle)
    paths.append({"name": "handle", "path_xyz": handle_path, "component_id": 2,
                  "tol_mm": max(1.6 * t_w, 5.0) * 1.1})
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    return build_vessel(
        parts, union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(
            mesh, tags, profile, attachment_paths=paths),
        construct={"kind": "revolve+attachment", "profile": "ewer", "belly_r_mm": r_belly,
                   "neck_r_mm": r_neck, "spout_mm": float(p.spout_length_mm),
                   "spout_bore_mm": float(p.spout_bore_mm),
                   "attachment_paths": paths},
        meta={"vessel": "V09", "profile_metrics": _jsonable_metrics(profile),
              "attachments": [a["name"] for a in paths]},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(profile),
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=1.2, max_wall_mm=max(4.0 * t_b, 50.0), stage="mothers.vessels.V09")


def _handle_part(R_mm: float, z_attach: float, span_ratio: float, thickness_mm: float, *,
                 component_id: int = 1, name: str = "handle") -> tuple[Part, np.ndarray]:
    """Closed swept handle whose two ends overlap the body volume."""
    R = float(R_mm)
    r_tube = max(0.5 * float(thickness_mm), 1.6)
    z0 = float(z_attach)
    reach = R * (1.0 + 0.55 * float(span_ratio))
    n = 18
    t = np.linspace(0.0, 1.0, n)
    ang = np.pi * t
    path = np.column_stack([
        R * 0.97 + (reach - R * 0.97) * np.sin(ang) ** 1.1,
        np.zeros(n),
        z0 + max(reach - R, r_tube) * 0.85 * (1.0 - np.cos(ang)) * 0.5,
    ])
    path[0, 0] = R * 0.86
    path[-1, 0] = R * 0.86
    path[-1, 2] = z0 - max(R * 0.55, 2.0 * r_tube)
    mesh = sweep_tube(Point(0.0, 0.0).buffer(r_tube, quad_segs=10), path, cap=True,
                      stage="mothers.vessels.handle")
    return Part(mesh=mesh, tags=constant_tags(mesh, "attachment"),
                component_id=int(component_id), name=name), path


# --------------------------------------------------------------------------- V10 lidded pot
class LiddedPotParams(_Base):
    height_mm: float = Field(170.0, ge=60.0, le=380.0)
    belly_ratio: float = Field(1.0, ge=0.55, le=1.4)
    mouth_ratio: float = Field(0.62, ge=0.25, le=0.98)
    lid_height_ratio: float = Field(0.22, ge=0.06, le=0.6, description="lid height / body height")
    lid_seat_mm: float = Field(4.0, ge=1.0, le=20.0, description="lid skirt overlap into the mouth")
    knob_diameter_mm: float = Field(26.0, ge=6.0, le=70.0)


@register_vessel("V10", "带盖壶", param_model=LiddedPotParams,
                 version="1.1",
                 applicable={"family": "revolve+lid", "requires_cavity": True,
                             "min_wall_mm": 1.2, "scale_mm": [60, 340],
                             "components": ["body", "lid"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm",
                                                  "height_mm", "belly_ratio", "mouth_ratio",
                                                  "lid_height_ratio", "lid_seat_mm",
                                                  "knob_diameter_mm"]},
                 notes="body plus an independent pre-break lid component (contact is not R2)")
def build_lidded_pot(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = LiddedPotParams.model_validate(params)
    R = float(p.diameter_mm) / 2.0
    r_belly = R * float(p.belly_ratio)
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    h = float(p.height_mm)
    r_mouth = r_belly * float(p.mouth_ratio)
    _require_neck(r_mouth, t_w, "V10")
    lid_h = float(p.lid_height_ratio) * h
    seat = float(np.clip(p.lid_seat_mm, 1.0, 0.8 * lid_h))
    z_body_rim = t_b / 2.0 + h
    z_shoulder = t_b / 2.0 + 0.6 * h
    r_base = 0.55 * r_belly
    base_pts = [(0.0, t_b / 2.0), (0.55 * r_base, t_b / 2.0 + 0.6 * t_b)]
    wall = wall_points(r_start_mm=r_base, R_mm=r_belly, z_start=t_b / 2.0 + 0.7 * t_b,
                       z_rim_mm=z_shoulder, count=4, exponent=0.62)
    for i in range(1, 5):
        u = i / 4.0
        wall.append((float(r_belly + (r_mouth - r_belly) * (u ** 0.6)),
                     float(z_shoulder + (z_body_rim - z_shoulder) * u)))
    body_profile = shell_profile(R_mm=r_belly, z_rim_mm=z_body_rim, base_pts=base_pts,
                                 wall_pts=wall, t_base_mm=t_b, t_wall_mm=t_w, rim_mode="flat",
                                 min_wall_mm=1.2, stage="mothers.vessels.V10")
    body = revolve_body(body_profile)
    lid = _lid_part(r_mouth=r_mouth, lid_height_mm=lid_h, seat_mm=seat,
                    knob_r=0.5 * float(p.knob_diameter_mm), t_wall=t_w,
                    z_lid_base=z_body_rim - seat, component_id=1)
    parts = [body, lid]
    cavity = cavity_probe_points(body_profile)
    warp = p.warp(rng, body_profile.z_bottom, z_body_rim + lid_h)
    return build_vessel(
        parts, union=False, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(
            mesh, tags, body_profile,
            attachment_paths=[{"name": "lid", "path_xyz": np.array(
                [[0.0, 0.0, z_body_rim], [0.0, 0.0, z_body_rim + lid_h]]),
                "component_id": 1, "tol_mm": max(lid_h, 6.0)}]),
        construct={"kind": "revolve+lid", "profile": "lidded_pot", "belly_r_mm": r_belly,
                   "mouth_r_mm": r_mouth, "lid_height_mm": lid_h, "lid_seat_mm": seat,
                   "components": ["body", "lid"],
                   "note": "lid is an independent pre-break component; the original contact "
                           "band is not reported as a fresh fracture relation"},
        meta={"vessel": "V10", "profile_metrics": _jsonable_metrics(body_profile),
              "prebreak_components": ["body", "lid"], "attachments": ["lid"]},
        requires_cavity=True, cavity_probe_points=cavity,
        design_thickness=(body_profile.thickness_min_mm, body_profile.thickness_max_mm),
        min_wall_mm=1.2, max_wall_mm=max(4.0 * t_b, 60.0), stage="mothers.vessels.V10")


def _lid_part(*, r_mouth: float, lid_height_mm: float, seat_mm: float, knob_r: float,
              t_wall: float, z_lid_base: float, component_id: int = 1) -> Part:
    """Closed lid: a domed shell with a skirt that overlaps the body mouth by ``seat_mm``."""
    lid_h = max(float(lid_height_mm), 3.0 * float(t_wall))
    r_out = float(r_mouth) + max(0.6 * float(t_wall), 1.0)
    profile = np.array([
        [0.0, 0.0],
        [r_out, 0.0],
        [r_out, 0.85 * lid_h],
        [0.72 * r_out, lid_h],
        [0.30 * knob_r + 0.35 * r_out, lid_h + 0.55 * max(knob_r, 3.0)],
        [0.0, lid_h + 0.85 * max(knob_r, 3.0)],
    ], dtype=np.float64)
    mesh = trimesh.creation.revolve(profile, sections=96)
    mesh, _ = cleanup(mesh)
    if not mesh.is_watertight or float(mesh.volume) <= 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "lid body is not a closed solid",
                          stage="mothers.vessels.V10.lid")
    mesh.apply_translation([0.0, 0.0, float(z_lid_base)])
    # the skirt reaches *below* the mouth plane: a real volumetric lap, not a point contact.
    # It is placed in the lid's own frame (``z_lid_base``), not around the world origin: an
    # un-translated skirt becomes a *second, disconnected body* floating under the vessel
    # (measured on V10/M06 ``LIN0004_V10_M06_PAT03``: a 256-face, 13 045 mm^3 ring at
    # z = -5.06..1.69, i.e. below the base, which the fracture then reports as a fragment of
    # its own).  With ``z_lid_base = 0`` the placement is unchanged.
    skirt = trimesh.creation.cylinder(radius=r_out, height=max(float(seat_mm), 1.0) * 2.0,
                                      sections=64)
    skirt.apply_translation([0.0, 0.0, float(z_lid_base) - 0.5 * max(float(seat_mm), 1.0)])
    mesh = trimesh.util.concatenate([mesh, skirt])
    mesh, _ = cleanup(mesh)
    if not mesh.is_watertight:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "lid skirt broke watertightness",
                          stage="mothers.vessels.V10.lid")
    from ..tagging import tag_by_polyline
    from ..geometry import LabelledPolyline

    seg = np.linalg.norm(np.diff(profile, axis=0), axis=1)
    labels = np.array(["rim"] + ["outer_wall"] * (len(seg) - 1), dtype=object)
    poly = LabelledPolyline(profile, labels, np.concatenate([[0.0], np.cumsum(seg)]))
    tags, _ = tag_by_polyline(mesh, poly, mode="revolve")
    return Part(mesh=mesh, tags=tags, component_id=int(component_id), name="lid")


# --------------------------------------------------------------------------------- V14 lid
class LidParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diameter_mm: float = Field(150.0, ge=40.0, le=320.0)
    thickness_mm: float = Field(9.0, ge=2.0, le=60.0)
    dome_height_mm: float = Field(26.0, ge=0.0, le=140.0, description="dome rise above the rim")
    rim_drop_mm: float = Field(8.0, ge=0.0, le=60.0, description="skirt length below the rim")
    rim_lip_mm: float = Field(3.0, ge=0.0, le=20.0, description="outward lip of the seat")
    knob_diameter_mm: float = Field(30.0, ge=0.0, le=80.0)
    knob_height_mm: float = Field(18.0, ge=0.0, le=70.0)
    sides: int = Field(0, ge=0, le=12, description="0 = round; >2 = regular polygon rim")
    warp_amplitude: float = Field(0.010, ge=0.0, le=0.05,
                                  description="low-amplitude non-axisymmetric rim warp")
    warp_eccentricity_mm: float = Field(0.5, ge=0.0, le=4.0)
    warp_lobes: int = Field(2, ge=2, le=6)


@register_vessel("V14", "盖", param_model=LidParams,
                 applicable={"family": "revolve", "requires_cavity": False, "min_wall_mm": 2.0,
                             "scale_mm": [40, 320], "components": ["body"],
                             "shape_parameters": ["diameter_mm", "thickness_mm",
                                                  "dome_height_mm", "rim_drop_mm", "rim_lip_mm",
                                                  "knob_diameter_mm", "knob_height_mm",
                                                  "sides"]},
                 notes="closed lid solid: dome, seat skirt, real knob and polygon rim")
def build_lid(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = LidParams.model_validate(params)
    R = float(p.diameter_mm) / 2.0
    thickness = float(p.thickness_mm)
    dome = float(p.dome_height_mm)
    drop = float(p.rim_drop_mm)
    lip = float(p.rim_lip_mm)
    knob_r = 0.5 * float(p.knob_diameter_mm)
    knob_h = float(p.knob_height_mm)
    z_rim = drop
    if thickness <= 0 or R <= thickness:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "lid thickness does not fit the diameter",
                          stage="mothers.vessels.V14",
                          measurements={"diameter_mm": 2.0 * R, "thickness_mm": thickness})
    # --- lid body: revolved cross-section with a real chamfer, dome and knob ------------
    # The lid is a solid of revolution whose profile is built directly from the offset
    # cross-section: a chamfered outer edge, a domed top and a cylindrical knob.  That keeps
    # every corner a 45-degree chamfer, so the offset never folds, and the measured minimum
    # thickness stays at the requested value instead of collapsing at a sharp seat corner.
    z_bottom = 0.0
    z_top = max(drop, 0.0) + max(dome, 0.5 * thickness)
    if z_top <= 0:
        z_top = 2.0 * thickness
    body = np.array([
        [0.0, z_bottom],
        [R - thickness, z_bottom],
        [R, z_bottom + thickness],
        [R, z_top - thickness],
        [R - thickness, z_top],
        [max(knob_r, 0.0) if knob_r > 1e-6 else 0.0, z_top + max(knob_h, 0.0)],
        [0.0, z_top + max(knob_h, 0.0)] if knob_r <= 1e-6 else [0.0, z_top + max(knob_h, 0.0) + 0.6 * thickness],
    ], dtype=np.float64)
    if knob_r <= 1e-6:
        body = np.array([
            [0.0, z_bottom],
            [R - thickness, z_bottom],
            [R, z_bottom + thickness],
            [R, z_top - thickness],
            [R - thickness, z_top],
            [0.0, z_top + 0.5 * thickness],
        ], dtype=np.float64)
    else:
        body = np.array([
            [0.0, z_bottom],
            [R - thickness, z_bottom],
            [R, z_bottom + min(thickness, z_top * 0.5)],
            [R, z_top - thickness],
            [R - thickness, z_top],
            [knob_r, z_top + 0.35 * thickness],
            [knob_r, z_top + 0.35 * thickness + max(knob_h, 0.0)],
            [0.0, z_top + 0.35 * thickness + max(knob_h, 0.0) + 0.5 * thickness],
        ], dtype=np.float64)
    if not Polygon(body).is_valid or Polygon(body).area <= 1e-6:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "lid profile is not a valid closed region",
                          stage="mothers.vessels.V14",
                          measurements={"diameter_mm": 2.0 * R, "thickness_mm": thickness})
    mesh = trimesh.creation.revolve(body, sections=128)
    mesh, _ = cleanup(mesh)
    if lip > 1e-6:
        ring = trimesh.creation.cylinder(radius=R + lip, height=max(0.9 * thickness, 1.0),
                                         sections=96)
        ring.apply_translation([0.0, 0.0, float(z_bottom + 0.45 * thickness)])
        mesh = combine_solids([mesh, ring])
        mesh, _ = cleanup(mesh)
    sides = int(p.sides)
    if sides >= 3:
        from shapely.geometry import Polygon as ShPolygon

        angles = np.linspace(0.0, 2.0 * np.pi, sides, endpoint=False)
        ring_shape = ShPolygon([(float((R + lip + 2.0) * np.cos(a)),
                                 float((R + lip + 2.0) * np.sin(a))) for a in angles])
        from ..solids import boolean_intersection, extrude_polygon_solid

        z_lo = float(np.min(body[:, 1])) - 2.0
        z_hi = float(np.max(body[:, 1])) + 2.0
        prism = extrude_polygon_solid(ring_shape, height=z_hi - z_lo,
                                      transform=np.array([[1, 0, 0, 0], [0, 1, 0, 0],
                                                          [0, 0, 1, z_lo], [0, 0, 0, 1]],
                                                         dtype=np.float64),
                                      stage="mothers.vessels.V14.sides")
        mesh = boolean_intersection([mesh, prism])
        mesh, _ = cleanup(mesh)
    if not mesh.is_watertight or float(mesh.volume) <= 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "lid is not a closed positive solid",
                          stage="mothers.vessels.V14",
                          measurements={"faces": int(len(mesh.faces))})
    profile = _lid_profile(body, thickness)
    profile["closed"] = body
    tags = _resemantic_revolution(mesh, z_min=float(np.min(body[:, 1])),
                                 z_max=float(np.max(body[:, 1])))
    part = Part(mesh=mesh, tags=tags, component_id=0, name="body")
    # a real low-amplitude non-axisymmetric warp, so the seed is a shape input here too (the
    # plan's step 6 applies to every mother, not only to the shells)
    warp = warp_spec_from_rng(rng, z_min=float(np.min(body[:, 1])),
                              z_max=float(np.max(body[:, 1])),
                              amplitude_max=float(p.warp_amplitude),
                              eccentricity_max_mm=float(p.warp_eccentricity_mm),
                              allowed_lobes=(int(p.warp_lobes), int(p.warp_lobes) + 1))

    def charts(m: trimesh.Trimesh, t: np.ndarray, spec: dict[str, Any]):
        return _lid_charts(m, t, profile)

    return build_vessel(
        [part], union=False, warp=warp, charts_fn=charts,
        construct={"kind": "revolve", "profile": "lid", "R_mm": R,
                   "thickness_mm": thickness, "dome_height_mm": dome, "rim_drop_mm": drop,
                   "rim_lip_mm": lip, "knob_diameter_mm": float(p.knob_diameter_mm),
                   "knob_height_mm": knob_h, "sides": sides},
        meta={"vessel": "V14", "profile_metrics": _jsonable_metrics(profile)},
        requires_cavity=False, cavity_probe_points=None,
        design_thickness=(thickness, thickness),
        min_wall_mm=min(thickness, 2.0),
        max_wall_mm=max(4.0 * thickness, 40.0), stage="mothers.vessels.V14")


def _lid_profile(body: np.ndarray, thickness: float) -> dict[str, Any]:
    """Metrics of the revolved lid cross-section (thickness, height, chamfer)."""
    pol = Polygon(body)
    edges = np.linalg.norm(np.diff(np.vstack([body, body[:1]]), axis=0), axis=1)
    return {
        "profile_area_mm2": float(pol.area),
        "profile_perimeter_mm": float(edges.sum()),
        "height_mm": float(np.ptp(body[:, 1])),
        "radius_mm": float(np.max(body[:, 0])),
        "chamfer_mm": float(np.min([thickness, 0.5 * max(float(np.ptp(body[:, 1])), 1e-6)])),
    }


def _lid_charts(mesh: trimesh.Trimesh, tags: np.ndarray, profile: dict[str, Any]):
    from ..charts import revolve_chart

    body = np.asarray(profile["closed"], dtype=np.float64)
    seg = np.linalg.norm(np.diff(body, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    profile_rzs = np.column_stack([body[:, 0], body[:, 1], s])
    present = tuple(int(t) for t in np.unique(tags))
    chart = revolve_chart("lid", present, profile_rzs=profile_rzs,
                          r_ref_mm=float(np.max(body[:, 0])),
                          area_mm2=float(mesh.area), tol_mm=2.0,
                          legal_tags=[_tag_name(t) for t in present])
    return [chart]


def _tag_name(tag: int) -> str:
    from ..tagging import TAG_NAMES

    return TAG_NAMES.get(int(tag), "outer_wall")


# -------------------------------------------------------------------------------- V15 lamp
class LampParams(_Base):
    diameter_mm: float = Field(85.0, ge=30.0, le=200.0)
    depth_mm: float = Field(26.0, ge=6.0, le=80.0)
    wall_mm: float = Field(5.0, ge=1.0, le=25.0)
    base_mm: float = Field(7.0, ge=1.2, le=30.0)
    spout_length_mm: float = Field(38.0, ge=10.0, le=120.0, description="wick spout projection")
    spout_angle_deg: float = Field(16.0, ge=0.0, le=60.0, description="spout tilt from the rim")
    foot_height_mm: float = Field(9.0, ge=0.0, le=50.0)


@register_vessel("V15", "灯盏", param_model=LampParams,
                 version="1.1",
                 applicable={"family": "revolve+spout", "requires_cavity": True,
                             "min_wall_mm": 1.0, "scale_mm": [30, 200],
                             "components": ["body", "spout"],
                             "shape_parameters": ["diameter_mm", "depth_mm", "wall_mm", "base_mm",
                                                  "spout_length_mm", "spout_angle_deg",
                                                  "foot_height_mm"]},
                 notes="shallow lamp body with a real wick spout and a foot ring")
def build_lamp(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = LampParams.model_validate(params)
    R = float(p.diameter_mm) / 2.0
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    depth = float(p.depth_mm)
    foot = float(p.foot_height_mm)
    z_rim = foot + depth
    r_fo = min(0.78 * R, R - t_w - 0.4)
    base_pts = [(0.0, t_b / 2.0 + foot), (0.5 * r_fo, t_b / 2.0 + 0.85 * foot)]
    if foot > 0.4:
        base_pts += [(0.85 * r_fo, t_b / 2.0), (r_fo, t_b / 2.0 + 0.3 * foot)]
    else:
        base_pts += [(r_fo, t_b / 2.0)]
    wall = wall_points(r_start_mm=r_fo, R_mm=R, z_start=t_b / 2.0 + 0.3 * foot,
                       z_rim_mm=z_rim, count=4, exponent=0.85, flare_mm=0.06 * R, flare_from=0.8)
    profile = shell_profile(R_mm=R, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="rounded", rim_bulge=0.5,
                            min_wall_mm=1.0, stage="mothers.vessels.V15")
    parts = [revolve_body(profile)]
    spout_len = float(p.spout_length_mm)
    angle = np.deg2rad(float(np.clip(p.spout_angle_deg, 0.0, 80.0)))
    r_tube = max(t_w * 0.9, 2.0)
    n = 12
    t = np.linspace(0.0, 1.0, n)
    spout_path = np.column_stack([
        R * 0.86 + spout_len * t * np.cos(angle) * 0.35,
        np.zeros(n),
        z_rim - depth * 0.45 + spout_len * t * np.sin(angle),
    ])
    spout_mesh = sweep_tube(Point(0.0, 0.0).buffer(r_tube, quad_segs=10), spout_path, cap=True,
                            stage="mothers.vessels.V15.spout")
    parts.append(Part(mesh=spout_mesh, tags=constant_tags(spout_mesh, "attachment"),
                      component_id=1, name="spout"))
    paths = [{"name": "spout", "path_xyz": spout_path, "component_id": 1, "tol_mm": r_tube * 2.5}]
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    return build_vessel(
        parts, union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(
            mesh, tags, profile, attachment_paths=paths),
        construct={"kind": "revolve+spout", "profile": "lamp", "R_mm": R, "depth_mm": depth,
                   "foot_height_mm": foot, "spout_length_mm": spout_len,
                   "spout_angle_deg": float(p.spout_angle_deg)},
        meta={"vessel": "V15", "profile_metrics": _jsonable_metrics(profile),
              "attachments": ["spout"]},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(profile),
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=1.0, max_wall_mm=max(3.0 * t_b, 30.0), stage="mothers.vessels.V15")


# ------------------------------------------------------------------------------ V16 censer
class CenserParams(_Base):
    height_mm: float = Field(120.0, ge=40.0, le=300.0)
    belly_ratio: float = Field(1.0, ge=0.55, le=1.5)
    shoulder_ratio: float = Field(0.62, ge=0.3, le=0.95, description="belly height / total")
    foot_count: int = Field(3, ge=0, le=6)
    foot_height_mm: float = Field(26.0, ge=0.0, le=120.0)
    vent_count: int = Field(0, ge=0, le=24, description="ventilation holes through the shoulder")
    vent_diameter_mm: float = Field(9.0, ge=2.0, le=30.0)


@register_vessel("V16", "香炉", param_model=CenserParams,
                 version="1.1",
                 applicable={"family": "revolve+attachment", "requires_cavity": True,
                             "min_wall_mm": 1.2, "scale_mm": [40, 300],
                             "components": ["body", "feet"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm",
                                                  "height_mm", "belly_ratio", "shoulder_ratio",
                                                  "foot_count", "foot_height_mm", "vent_count",
                                                  "vent_diameter_mm"]},
                 notes="belly on real legs with optional vent holes cut through the shoulder")
def build_censer(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = CenserParams.model_validate(params)
    R = float(p.diameter_mm) / 2.0
    r_belly = R * float(p.belly_ratio)
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    h = float(p.height_mm)
    foot_h = float(p.foot_height_mm)
    shoulder = float(p.shoulder_ratio)
    r_mouth = r_belly * 0.78
    _require_neck(r_mouth, t_w, "V16")
    z_bottom = t_b / 2.0 + foot_h
    z_shoulder = z_bottom + shoulder * h
    z_rim = z_bottom + h
    r_base = 0.6 * r_belly
    base_pts = [(0.0, z_bottom), (0.55 * r_base, z_bottom + 0.5 * t_b)]
    wall = wall_points(r_start_mm=r_base, R_mm=r_belly, z_start=z_bottom + 0.6 * t_b,
                       z_rim_mm=z_shoulder, count=4, exponent=0.6)
    for i in range(1, 4):
        u = i / 3.0
        wall.append((float(r_belly + (r_mouth - r_belly) * (u ** 0.5)),
                     float(z_shoulder + (z_rim - z_shoulder) * u)))
    profile = shell_profile(R_mm=r_belly, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="rounded", rim_bulge=0.4,
                            min_wall_mm=1.2, stage="mothers.vessels.V16")
    body = revolve_body(profile)
    parts: list[Part] = [body]
    paths: list[dict[str, Any]] = []
    foot_count = int(p.foot_count)
    if foot_count > 0 and foot_h > 1.0:
        for index in range(foot_count):
            theta = 2.0 * np.pi * index / float(foot_count) + 0.3
            leg = _foot_part(r_belly=r_belly * 0.8, theta=theta,
                             height_mm=foot_h + t_b, root_mm=max(1.6 * t_w, 6.0),
                             component_id=1 + index)
            parts.append(leg)
            radial = r_belly * 0.8 * 0.62
            paths.append({"name": leg.name, "component_id": 1 + index, "tol_mm": foot_h,
                          "path_xyz": np.array([
                              [radial * np.cos(theta), radial * np.sin(theta), z_bottom],
                              [radial * np.cos(theta), radial * np.sin(theta), 0.0]])})
    vents = int(p.vent_count)
    if vents > 0:
        cutters = _vent_cutters(count=vents, diameter=float(p.vent_diameter_mm),
                                r_belly=r_belly, z_band=(z_bottom + 0.45 * h, z_bottom + 0.8 * h))
        if cutters:
            merged = combine_solids([part.mesh for part in parts])
            merged = boolean_difference([merged, *cutters])
            merged, _ = cleanup(merged)
            tags = _resemantic_revolution(merged, z_min=profile.z_bottom, z_max=profile.z_rim)
            parts = [Part(mesh=merged, tags=tags, component_id=0, name="body")]
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    return build_vessel(
        parts, union=True, warp=warp,
        charts_fn=lambda mesh, tags, construct: revolve_charts(
            mesh, tags, profile, attachment_paths=paths),
        construct={"kind": "revolve+attachment", "profile": "censer", "belly_r_mm": r_belly,
                   "foot_count": foot_count, "foot_height_mm": foot_h, "vent_count": vents,
                   "vent_diameter_mm": float(p.vent_diameter_mm)},
        meta={"vessel": "V16", "profile_metrics": _jsonable_metrics(profile),
              "attachments": ["feet"] if foot_count else []},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(profile),
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=1.2, max_wall_mm=max(4.0 * t_b, 50.0), stage="mothers.vessels.V16")


def _resemantic_revolution(mesh: trimesh.Trimesh, *, z_min: float, z_max: float,
                           z_shoulder: float | None = None) -> np.ndarray:
    """Rebuild face tags of a revolved (possibly pierced) body from its own geometry.

    Used after a boolean that removed material (drainage holes, vents): the tags of the
    surviving faces are recovered from the faces themselves - upward-facing caps are the
    rim, downward-facing caps the base, outward-facing sides the outer wall and
    inward-facing sides the inner wall.  The rule is analytic and reported in the mother
    metadata, not a nearest-neighbour guess.
    """
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    tags = np.full(len(mesh.faces), TAG_INDEX["outer_wall"], dtype=np.int32)
    radial = np.hypot(centroids[:, 0], centroids[:, 1])
    outward = (normals[:, 0] * centroids[:, 0] + normals[:, 1] * centroids[:, 1])
    tags[(radial > 1e-3) & (outward < 0.0)] = TAG_INDEX["inner_wall"]
    cap_up = np.abs(normals[:, 2]) > 0.55
    tags[cap_up & (normals[:, 2] > 0.0)] = TAG_INDEX["rim"]
    tags[cap_up & (normals[:, 2] < 0.0)] = TAG_INDEX["base"]
    if z_shoulder is not None:
        pass
    if not np.any(tags == TAG_INDEX["base"]):
        tags[np.abs(centroids[:, 2] - float(z_min)) < 1e-6] = TAG_INDEX["base"]
    if not np.any(tags == TAG_INDEX["rim"]):
        tags[np.abs(centroids[:, 2] - float(z_max)) < 1e-6] = TAG_INDEX["rim"]
    return tags


def _vent_cutters(*, count: int, diameter: float, r_belly: float,
                  z_band: tuple[float, float]) -> list[trimesh.Trimesh]:
    """Radial drilled vents through the shoulder (real holes, not decals)."""
    r_hole = max(0.5 * float(diameter), 1.0)
    z0, z1 = float(z_band[0]), float(z_band[1])
    out: list[trimesh.Trimesh] = []
    length = 2.4 * float(r_belly)
    for index in range(int(count)):
        theta = 2.0 * np.pi * index / float(count)
        z = z0 + (z1 - z0) * ((index % 3) / 3.0 + 0.17)
        cylinder = trimesh.creation.cylinder(radius=r_hole, height=length, sections=20)
        cylinder.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2.0,
                                                                         [0.0, 1.0, 0.0]))
        cylinder.apply_transform(trimesh.transformations.rotation_matrix(theta, [0.0, 0.0, 1.0]))
        cylinder.apply_translation([0.0, 0.0, z])
        out.append(cylinder)
    return out


# ------------------------------------------------------------------------- V17 flower pot
class FlowerPotParams(_Base):
    depth_mm: float = Field(110.0, ge=30.0, le=240.0)
    base_to_mouth_ratio: float = Field(0.62, ge=0.2, le=0.95, description="base diameter / mouth")
    rim_thickness_factor: float = Field(1.6, ge=0.8, le=3.2, description="thickened rim band")
    hole_count: int = Field(3, ge=0, le=24, description="drainage holes in the floor")
    hole_diameter_mm: float = Field(12.0, ge=2.0, le=45.0)
    foot_height_mm: float = Field(12.0, ge=0.0, le=60.0)


@register_vessel("V17", "花盆", param_model=FlowerPotParams,
                 version="1.1",
                 applicable={"family": "revolve+pierced", "requires_cavity": True,
                             "min_wall_mm": 1.2, "scale_mm": [60, 340], "components": ["body"],
                             "shape_parameters": ["diameter_mm", "wall_mm", "base_mm", "depth_mm",
                                                  "base_to_mouth_ratio", "rim_thickness_factor",
                                                  "hole_count", "hole_diameter_mm",
                                                  "foot_height_mm"]},
                 notes="tapered thick shell with drainage holes cut through the floor")
def build_flower_pot(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = FlowerPotParams.model_validate(params)
    R = float(p.diameter_mm) / 2.0
    t_w, t_b = float(p.wall_mm), float(p.base_mm)
    depth = float(p.depth_mm)
    r_base = float(p.base_to_mouth_ratio) * R
    foot = float(p.foot_height_mm)
    z_rim = foot + depth
    base_pts = [(0.0, t_b / 2.0 + foot), (0.6 * r_base, t_b / 2.0 + max(0.8 * foot, 0.5 * t_b))]
    if foot > 0.5:
        base_pts += [(0.85 * r_base, t_b / 2.0), (r_base, t_b / 2.0 + 0.25 * foot)]
    else:
        base_pts += [(r_base, t_b / 2.0)]
    wall = wall_points(r_start_mm=r_base, R_mm=R, z_start=t_b / 2.0 + max(0.3 * foot, 0.4),
                       z_rim_mm=z_rim, count=5, exponent=1.0)
    profile = shell_profile(R_mm=R, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                            t_base_mm=t_b, t_wall_mm=t_w, rim_mode="bevel", rim_bulge=0.4,
                            taper_top=float(p.rim_thickness_factor), min_wall_mm=1.2,
                            stage="mothers.vessels.V17")
    body = revolve_body(profile)
    holes = int(p.hole_count)
    mesh = body.mesh
    if holes > 0:
        cutters = _drain_cutters(count=holes, diameter=float(p.hole_diameter_mm),
                                 r_floor=r_base * 0.72, z_floor=t_b / 2.0 + foot,
                                 base_mm=t_b)
        mesh = boolean_difference([mesh, *cutters])
        mesh, _ = cleanup(mesh)
    tags = _resemantic_revolution(mesh, z_min=profile.z_bottom, z_max=profile.z_rim)
    part = Part(mesh=mesh, tags=tags, component_id=0, name="body")
    warp = p.warp(rng, profile.z_bottom, profile.z_rim)
    return build_vessel(
        [part], union=True, warp=warp,
        charts_fn=lambda m, tags, construct: revolve_charts(m, tags, profile),
        construct={"kind": "revolve", "profile": "flower_pot", "R_mm": R, "depth_mm": depth,
                   "base_r_mm": r_base, "hole_count": holes,
                   "hole_diameter_mm": float(p.hole_diameter_mm)},
        meta={"vessel": "V17", "profile_metrics": _jsonable_metrics(profile),
              "drainage_holes": holes},
        requires_cavity=True, cavity_probe_points=cavity_probe_points(profile),
        design_thickness=(profile.thickness_min_mm, profile.thickness_max_mm),
        min_wall_mm=1.2, max_wall_mm=max(3.0 * t_b, 40.0), stage="mothers.vessels.V17")


def _drain_cutters(*, count: int, diameter: float, r_floor: float, z_floor: float,
                   base_mm: float) -> list[trimesh.Trimesh]:
    r_hole = max(0.5 * float(diameter), 1.0)
    if 2.0 * r_hole > 0.85 * float(r_floor) and count > 1:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "drainage holes do not fit in the pot floor",
                          stage="mothers.vessels.V17",
                          measurements={"hole_diameter_mm": float(diameter),
                                        "floor_r_mm": float(r_floor)})
    out: list[trimesh.Trimesh] = []
    if count == 1:
        centres = [(0.0, 0.0)]
    else:
        ring_r = max(float(r_floor) - r_hole - 1.0, 0.0)
        centres = [(ring_r * np.cos(2.0 * np.pi * i / count),
                    ring_r * np.sin(2.0 * np.pi * i / count)) for i in range(int(count))]
    for cx, cy in centres:
        cylinder = trimesh.creation.cylinder(radius=r_hole,
                                             height=4.0 * float(base_mm) + 6.0, sections=24)
        cylinder.apply_translation([cx, cy, float(z_floor)])
        out.append(cylinder)
    return out


# ---------------------------------------------------------------------------- V23 figurine
class FigurineParams(_Base):
    height_mm: float = Field(180.0, ge=40.0, le=420.0, description="total height")
    body_width_mm: float = Field(52.0, ge=14.0, le=160.0)
    body_depth_mm: float = Field(38.0, ge=12.0, le=160.0)
    head_ratio: float = Field(0.24, ge=0.10, le=0.45, description="head height / total height")
    neck_ratio: float = Field(0.42, ge=0.15, le=0.9, description="neck radius / head radius")
    torso_taper: float = Field(0.72, ge=0.25, le=1.0, description="waist width / shoulder width")
    arm_count: int = Field(2, ge=0, le=6, description="swept limbs attached to the torso")
    arm_length_ratio: float = Field(0.55, ge=0.15, le=0.95)
    pose_tilt_deg: float = Field(9.0, ge=0.0, le=45.0, description="lean of the whole figure")
    pose_twist_deg: float = Field(12.0, ge=-90.0, le=90.0, description="twist along the height")


@register_vessel("V23", "小雕像", param_model=FigurineParams,
                 applicable={"family": "superquadric", "requires_cavity": False,
                             "min_wall_mm": 2.0, "scale_mm": [40, 420],
                             "components": ["body", "head", "arms"],
                             "shape_parameters": ["height_mm", "body_width_mm", "body_depth_mm",
                                                  "head_ratio", "neck_ratio", "torso_taper",
                                                  "arm_count", "arm_length_ratio",
                                                  "pose_tilt_deg", "pose_twist_deg"]},
                 notes="closed superquadric torso/head plus swept limbs with real root overlap")
def build_figurine(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = FigurineParams.model_validate(params)
    height = float(p.height_mm)
    head_h = float(p.head_ratio) * height
    torso_h = height - head_h
    half_w = 0.5 * float(p.body_width_mm)
    half_d = 0.5 * float(p.body_depth_mm)
    taper = float(p.torso_taper)
    tilt = np.deg2rad(float(p.pose_tilt_deg))
    twist = np.deg2rad(float(p.pose_twist_deg))

    torso = superquadric(a_mm=half_w, b_mm=half_d, c_mm=0.5 * torso_h, e1=0.62, e2=0.72,
                         twist_rad=twist, rings=44, stacks=48, stage="mothers.vessels.V23")
    torso.apply_transform(trimesh.transformations.rotation_matrix(tilt, [0.0, 1.0, 0.0]))
    verts = np.asarray(torso.vertices, dtype=np.float64).copy()
    t = (verts[:, 2] - float(verts[:, 2].min())) / max(torso_h, 1e-6)
    shrink = 1.0 - (1.0 - taper) * np.clip(t, 0.0, 1.0) ** 1.4
    verts[:, 0] *= shrink
    verts[:, 1] *= shrink
    verts[:, 2] += 0.5 * torso_h + 0.15 * head_h
    torso.vertices = verts
    head_c = float(np.max(verts[:, 2])) + 0.30 * head_h
    head = superquadric(a_mm=0.62 * head_h, b_mm=0.58 * head_h, c_mm=0.5 * head_h,
                        e1=0.85, e2=0.9, rings=32, stacks=36, stage="mothers.vessels.V23.head")
    head.apply_translation([0.0, 0.0, head_c])
    neck_r = float(p.neck_ratio) * 0.62 * head_h
    neck = superquadric(a_mm=max(neck_r, 2.0), b_mm=max(neck_r, 2.0), c_mm=0.35 * head_h,
                        e1=0.9, e2=1.0, rings=24, stacks=26,
                        stage="mothers.vessels.V23.neck")
    neck.apply_translation([0.0, 0.0, head_c - 0.55 * head_h])
    parts: list[Part] = []
    merged = combine_solids([torso, neck, head])
    merged, _ = cleanup(merged)
    tags = np.full(len(merged.faces), TAG_INDEX["outer_wall"], dtype=np.int32)
    normals = np.asarray(merged.face_normals, dtype=np.float64)
    tags[normals[:, 2] < -0.55] = TAG_INDEX["base"]
    tags[(normals[:, 2] > 0.55) & (np.asarray(merged.triangles_center)[:, 2] > head_c)] = \
        TAG_INDEX["rim"]
    parts.append(Part(mesh=merged, tags=tags, component_id=0, name="body"))

    arms = int(p.arm_count)
    if arms > 0:
        arm_len = float(p.arm_length_ratio) * torso_h
        for index in range(arms):
            phi = 2.0 * np.pi * index / float(arms)
            z_root = float(np.max(verts[:, 2])) - 0.22 * torso_h
            arm = _limb_part(root_xy=(half_w * 0.55 * np.cos(phi), half_d * 0.55 * np.sin(phi)),
                             z_root=z_root, length_mm=arm_len, radius_mm=max(0.18 * half_w, 2.2),
                             direction=phi)
            parts.append(Part(mesh=arm, tags=constant_tags(arm, "attachment"),
                              component_id=1 + index, name=f"limb_{index}"))
    cavity = None
    return build_vessel(
        parts, union=True, warp=p.warp(rng, 0.0, height),
        charts_fn=lambda m, t, construct: _figurine_charts(m, t, p, height),
        construct={"kind": "superquadric", "profile": "figurine", "height_mm": height,
                   "head_ratio": float(p.head_ratio), "arm_count": arms,
                   "pose_tilt_deg": float(p.pose_tilt_deg),
                   "pose_twist_deg": float(p.pose_twist_deg)},
        meta={"vessel": "V23", "attachments": [f"limb_{i}" for i in range(arms)]},
        requires_cavity=False, cavity_probe_points=cavity,
        design_thickness=(2.0 * max(0.18 * half_w, 2.2) * 0.5, float(half_d)),
        min_wall_mm=2.0, max_wall_mm=max(4.0 * half_d, 60.0), stage="mothers.vessels.V23")


def _limb_part(*, root_xy: tuple[float, float], z_root: float, length_mm: float,
               radius_mm: float, direction: float) -> trimesh.Trimesh:
    """Closed swept limb whose root overlaps the torso volume."""
    r = max(float(radius_mm), 1.6)
    n = 12
    t = np.linspace(0.0, 1.0, n)
    drop = float(length_mm)
    root = 0.55 * r
    path = np.column_stack([
        float(root_xy[0]) + (drop * 0.55 * np.cos(direction)) * t,
        float(root_xy[1]) + (drop * 0.55 * np.sin(direction)) * t,
        float(z_root) - drop * t,
    ])
    path[0, 0] = float(root_xy[0]) * 0.55
    path[0, 1] = float(root_xy[1]) * 0.55
    section = Point(0.0, 0.0).buffer(r * 0.85, quad_segs=8)
    mesh = sweep_tube(section, path, cap=True, stage="mothers.vessels.V23.limb")
    if not mesh.is_watertight:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "figurine limb is not watertight", stage=STAGE)
    return mesh


def _figurine_charts(mesh: trimesh.Trimesh, tags: np.ndarray, p: FigurineParams,
                     height: float):
    from ..charts import planar_chart

    present = tuple(int(t) for t in np.unique(tags))
    return [planar_chart("figurine_plane", present, origin=(0.0, 0.0, 0.0),
                         e_u=(1.0, 0.0, 0.0), e_v=(0.0, 1.0, 0.0), area_mm2=float(mesh.area),
                         extent_u_mm=(-float(p.body_width_mm), float(p.body_width_mm)),
                         extent_v_mm=(-float(p.body_depth_mm), float(p.body_depth_mm)),
                         meta={"definition": "orthographic projection of the figurine",
                               "height_mm": float(height)})]


__all__ = ["EwerParams", "LiddedPotParams", "LidParams", "LampParams", "CenserParams",
           "FlowerPotParams", "FigurineParams", "build_ewer", "build_lidded_pot", "build_lid",
           "build_lamp", "build_censer", "build_flower_pot", "build_figurine"]
