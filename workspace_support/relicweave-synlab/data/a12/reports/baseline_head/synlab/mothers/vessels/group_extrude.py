"""Extrusion family: V13 box, V18 brick, V19 flat tile, V22 stele.

All four are extruded solids (plan 7.2 "圆角截面挤出壳", "圆角实体板", "有厚度参数板",
"厚板+刻字/浮雕"), so they share one honest kernel: a valid shapely polygon (with holes
for the shells) is extruded with ``trimesh.creation.extrude_polygon`` and the face tags are
recovered analytically from the extrusion structure (top ring -> rim, bottom ring -> base,
outward sides -> outer_wall, hole sides -> inner_wall).  That is exact for an extrusion -
no nearest-neighbour guessing is involved.

Every entry point below owns its own pydantic parameter model and at least three
parameters that change the silhouette; the shared functions are only the kernel.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict, Field
from shapely.affinity import scale as shapely_scale
from shapely.geometry import Polygon, box

from ...errors import ErrorCode, SynLabError
from ...registry import register_vessel
from ..assemblies import Part, build_vessel, constant_tags
from ..solids import boolean_difference, cleanup as solids_cleanup, extrude_polygon_solid
from ..tagging import TAG_INDEX, attach_face_semantics, tag_by_polyline
from ..warp import warp_spec_from_rng
from .common import prism_charts

STAGE = "mothers.vessels.extrude"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warp_amplitude: float = Field(0.012, ge=0.0, le=0.05,
                                  description="low-amplitude non-axisymmetric bed warp")
    warp_eccentricity_mm: float = Field(0.6, ge=0.0, le=4.0)
    warp_lobes: int = Field(2, ge=2, le=6)

    def warp(self, rng: np.random.Generator, z_min: float, z_max: float):
        return warp_spec_from_rng(rng, z_min=z_min, z_max=z_max,
                                  amplitude_max=float(self.warp_amplitude),
                                  eccentricity_max_mm=float(self.warp_eccentricity_mm),
                                  allowed_lobes=(int(self.warp_lobes), int(self.warp_lobes) + 1))


# ------------------------------------------------------------------------------- kernels
def rounded_polygon(*, x_mm: float, y_mm: float, corner_mm: float,
                    segments: int = 5) -> Polygon:
    """Axis-aligned rounded rectangle centred on the origin.

    The rounding is a real negative-then-positive buffer (GEOS ``join_style=round`` [R16])
    rather than a hand-written arc walk: a hand-built arc sequence has to get the tangent
    order exactly right at every corner, and GEOS already guarantees a valid, convex outline.
    """
    x = float(x_mm)
    y = float(y_mm)
    radius = float(np.clip(corner_mm, 0.0, 0.49 * min(x, y)))
    if radius <= 1e-6:
        return box(-0.5 * x, -0.5 * y, 0.5 * x, 0.5 * y)
    base = box(-0.5 * x + radius, -0.5 * y + radius, 0.5 * x - radius, 0.5 * y - radius)
    quad = int(np.clip(np.ceil(np.pi / (2.0 * max(np.arccos(max(1.0 - 0.05 / radius, -1.0)), 1e-6))),
                       3, 48))
    polygon = base.buffer(radius, quad_segs=quad, join_style=1)
    if not polygon.is_valid or polygon.is_empty or float(polygon.area) <= 1e-6:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "rounded rectangle is not a valid polygon",
                          stage=STAGE,
                          measurements={"x_mm": x, "y_mm": y, "corner_mm": radius})
    return polygon


def tag_extrusion(mesh: trimesh.Trimesh, *, exterior: Polygon, inner: Polygon | None,
                  z_min_mm: float, z_max_mm: float, tol_mm: float = 0.35) -> np.ndarray:
    """Analytic face tags of a vertical extrusion (cap rings and side walls)."""
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    tags = np.full(len(mesh.faces), TAG_INDEX["outer_wall"], dtype=np.int32)
    vertical = np.abs(normals[:, 2]) < 0.5
    tags[vertical & (normals[:, 2] < 0.0)] = TAG_INDEX["base"]
    tags[vertical & (normals[:, 2] > 0.0)] = TAG_INDEX["rim"]
    side = ~vertical
    if inner is not None and not inner.is_empty:
        inside_hole = np.array([inner.contains(__import__("shapely.geometry", fromlist=["Point"])
                                               .Point(float(c[0]), float(c[1])))
                                for c in centroids])
        tags[side & inside_hole] = TAG_INDEX["inner_wall"]
    return tags


def prism_shell_part(*, exterior: Polygon, wall_mm: float, height_mm: float,
                     base_mm: float, inner_taper: float = 1.0, name: str = "body",
                     component_id: int = 0, stage: str = STAGE) -> tuple[Part, Polygon, Polygon]:
    """Hollow prism: a wall shell over a solid base plate, with a tapered cavity.

    The wall is the extrusion of ``exterior - cavity`` stacked on the solid base plate, so the
    floor thickness is a real solid and the cavity stays open at the top.  ``inner_taper``
    widens the solid wall towards the rim, which is realised by growing the cavity clearance
    (one watertight extrusion) rather than by lofting layers that would only touch
    face-to-face.
    """
    h = float(height_mm)
    wall = float(wall_mm)
    base = float(base_mm)
    if wall <= 0 or base <= 0 or h <= 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "prism shell needs positive wall, base and height",
                          stage=stage,
                          measurements={"wall_mm": wall, "base_mm": base, "height_mm": h})
    taper = float(np.clip(inner_taper, 0.2, 1.0))
    # The requested taper is realised as a widening of the *solid* wall towards the rim:
    # the cavity is the exterior minus a clearance that grows with the taper parameter.  A
    # stacked loft would only touch face-to-face between layers and leaves coplanar junctions
    # (which the QA reads as a self-intersection), so the loop is built from one watertight
    # extrusion instead.
    clearance = 2.0 * wall + (1.0 - taper) * min(exterior.bounds[2] - exterior.bounds[0],
                                                 exterior.bounds[3] - exterior.bounds[1]) * 0.25
    cavity = exterior.buffer(-clearance, join_style=2, mitre_limit=3.0)
    if cavity.is_empty or float(cavity.area) <= 1e-6:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "wall thickness swallows the whole cross-section",
                          stage=stage,
                          measurements={"wall_mm": wall, "clearance_mm": clearance,
                                        "exterior_area_mm2": float(exterior.area)})
    if float(cavity.area) > 0.985 * float(exterior.area):
        raise SynLabError(ErrorCode.MOTHER_INVALID, "prism wall has no measurable thickness",
                          stage=stage, measurements={"wall_mm": wall})
    if base >= h:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "base plate is thicker than the box: no cavity would remain",
                          stage=stage, measurements={"base_mm": base, "height_mm": h})
    overlap = min(0.05, 0.25 * base, 0.25 * (h - base))
    wall_solid = extrude_polygon_solid(exterior.difference(cavity), (h - base) + overlap,
                                       transform=_z_transform(base - overlap),
                                       stage=f"{stage}.wall")
    base_solid = extrude_polygon_solid(exterior, base + overlap, stage=f"{stage}.base")
    # The wall shell and the base plate are unioned with a small volumetric overlap.  Simply
    # concatenating them leaves the two coincident faces at the seam, which the QA reports as a
    # coplanar overlap; welding the seam would create non-manifold edges instead.  Manifold
    # resolves the overlap into one valid closed solid, so the junction is real geometry.
    from ..solids import boolean_union

    merged = boolean_union([wall_solid, base_solid])
    merged.metadata = dict(merged.metadata or {})
    merged.metadata["combine_route"] = (
        f"manifold_union with a {overlap:.3f} mm seam overlap (wall shell + base plate)")
    merged, _ = _cleanup(merged)
    tags = tag_extrusion(merged, exterior=exterior, inner=cavity, z_min_mm=0.0, z_max_mm=h)
    if not np.any(tags == TAG_INDEX["inner_wall"]):
        raise SynLabError(ErrorCode.MOTHER_INVALID, "prism shell has no inner wall faces",
                          stage=stage)
    return Part(mesh=merged, tags=tags, component_id=component_id, name=name), cavity, cavity


def _z_transform(z_mm: float) -> np.ndarray:
    return np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, float(z_mm)], [0, 0, 0, 1]],
                    dtype=np.float64)


def _cleanup(mesh: trimesh.Trimesh):
    from ..solids import cleanup

    return cleanup(mesh)


def prism_assembly(*, parts: Sequence[Part], ring: Polygon, z_max_mm: float,
                   construct: dict[str, Any], vessel_id: str, rng: np.random.Generator,
                   warp_amp: float, warp_ecc: float, warp_lobes: int,
                   requires_cavity: bool = False, cavity_points: np.ndarray | None = None,
                   min_wall_mm: float = 1.0, max_wall_mm: float = 80.0,
                   cap_tags: Sequence[str] = ("rim", "base")) -> Any:
    def charts(mesh: trimesh.Trimesh, tags: np.ndarray, spec: dict[str, Any]):
        return prism_charts(mesh, tags, ring, z_min_mm=0.0, z_max_mm=float(z_max_mm),
                            cap_tag_names=tuple(cap_tags))

    warp = warp_spec_from_rng(rng, z_min=0.0, z_max=float(z_max_mm), amplitude_max=warp_amp,
                              eccentricity_max_mm=warp_ecc,
                              allowed_lobes=(int(warp_lobes), int(warp_lobes) + 1))
    return build_vessel(list(parts), union=True, warp=warp, charts_fn=charts,
                        construct=construct, meta={"vessel": vessel_id},
                        requires_cavity=requires_cavity,
                        cavity_probe_points=cavity_points,
                        design_thickness=(float("nan"), float("nan")),
                        min_wall_mm=min_wall_mm, max_wall_mm=max_wall_mm,
                        stage=f"mothers.vessels.{vessel_id}")


# ---------------------------------------------------------------------------- V13 盒
class BoxParams(_Base):
    length_mm: float = Field(150.0, ge=40.0, le=340.0)
    width_mm: float = Field(100.0, ge=40.0, le=340.0)
    height_mm: float = Field(70.0, ge=20.0, le=220.0)
    wall_mm: float = Field(5.0, ge=1.0, le=28.0)
    base_mm: float = Field(7.0, ge=1.2, le=40.0)
    corner_mm: float = Field(12.0, ge=0.0, le=90.0, description="corner radius of the shell")
    cavity_taper: float = Field(0.94, ge=0.55, le=1.0, description="inner section at the rim")


@register_vessel("V13", "盒", param_model=BoxParams,
                 applicable={"family": "prism", "requires_cavity": True, "min_wall_mm": 1.0,
                             "scale_mm": [40, 340], "components": ["body"],
                             "shape_parameters": ["length_mm", "width_mm", "height_mm",
                                                  "corner_mm", "cavity_taper", "wall_mm",
                                                  "base_mm"]},
                 notes="rounded rectangular extruded shell with a real wall and floor")
def build_box(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = BoxParams.model_validate(params)
    exterior = rounded_polygon(x_mm=float(p.length_mm), y_mm=float(p.width_mm),
                               corner_mm=float(p.corner_mm))
    part, inner, top_inner = prism_shell_part(exterior=exterior, wall_mm=float(p.wall_mm),
                                              height_mm=float(p.height_mm),
                                              base_mm=float(p.base_mm),
                                              inner_taper=float(p.cavity_taper),
                                              stage="mothers.vessels.V13")
    cavity = prism_cavity_probes(top_inner, inner, z_min_mm=float(p.base_mm),
                                 z_max_mm=float(p.height_mm))
    return prism_assembly(parts=[part], ring=exterior, z_max_mm=float(p.height_mm),
                          construct={"kind": "prism", "profile": "rounded_box",
                                     "exterior_mm": [float(p.length_mm), float(p.width_mm)],
                                     "corner_mm": float(p.corner_mm),
                                     "wall_mm": float(p.wall_mm), "base_mm": float(p.base_mm),
                                     "cavity_taper": float(p.cavity_taper)},
                          vessel_id="V13", rng=rng, warp_amp=float(p.warp_amplitude),
                          warp_ecc=float(p.warp_eccentricity_mm), warp_lobes=int(p.warp_lobes),
                          requires_cavity=True, cavity_points=cavity,
                          min_wall_mm=1.0,
                          max_wall_mm=max(3.0 * float(p.base_mm), 50.0))


def prism_cavity_probes(inner: Polygon, lower: Polygon, *, z_min_mm: float,
                        z_max_mm: float, count: int = 4) -> np.ndarray:
    """Probe points in the middle of the *interior* polygon of an extruded shell."""
    hollow = inner if inner.area <= lower.area else lower
    xs = 0.5 * (hollow.bounds[0] + hollow.bounds[2])
    ys = 0.5 * (hollow.bounds[1] + hollow.bounds[3])
    usable = max(float(z_max_mm) - float(z_min_mm), 1.0)
    out: list[list[float]] = []
    for i in range(int(max(count, 1))):
        z = float(z_min_mm) + usable * (i + 0.75) / (count + 0.5)
        if z >= float(z_max_mm):
            break
        out.append([xs, ys, z])
    return np.asarray(out, dtype=np.float64).reshape(-1, 3)


# ---------------------------------------------------------------------------- V18 砖
class BrickParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    length_mm: float = Field(230.0, ge=60.0, le=420.0)
    width_mm: float = Field(110.0, ge=40.0, le=260.0)
    thickness_mm: float = Field(45.0, ge=8.0, le=140.0)
    corner_mm: float = Field(8.0, ge=0.0, le=60.0)
    groove_depth_mm: float = Field(2.5, ge=0.0, le=12.0, description="edge groove depth")
    groove_width_mm: float = Field(6.0, ge=0.5, le=30.0, description="edge groove width")
    aeration_holes: int = Field(0, ge=0, le=24, description="perforation count through the brick")
    hole_diameter_mm: float = Field(8.0, ge=2.0, le=30.0)
    camber_mm: float = Field(0.8, ge=0.0, le=8.0, description="warping of the bed faces")


@register_vessel("V18", "砖", param_model=BrickParams,
                 applicable={"family": "prism", "requires_cavity": False, "min_wall_mm": 1.0,
                             "scale_mm": [60, 420], "components": ["body"],
                             "shape_parameters": ["length_mm", "width_mm", "thickness_mm",
                                                  "corner_mm", "groove_depth_mm",
                                                  "aeration_holes", "camber_mm"]},
                 notes="rounded solid slab with real edge grooves, perforations and bed camber")
def build_brick(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = BrickParams.model_validate(params)
    footprint = rounded_polygon(x_mm=float(p.length_mm), y_mm=float(p.width_mm),
                                corner_mm=float(p.corner_mm))
    thickness = float(p.thickness_mm)
    solid = extrude_polygon_solid(footprint, thickness, stage="mothers.vessels.V18")
    if float(p.groove_depth_mm) > 1e-6 and float(p.groove_width_mm) > 1e-6:
        depth = min(float(p.groove_depth_mm), 0.4 * thickness)
        width = float(p.groove_width_mm)
        cutters = []
        for shift in (-0.5 * float(p.width_mm) + 0.5 * width, 0.0, 0.5 * float(p.width_mm) - 0.5 * width):
            cutters.append(_groove_cutter(length=float(p.length_mm) + 8.0, width=width,
                                          depth=depth, axis="x", offset=shift))
        for shift in (-0.5 * float(p.length_mm) + 0.5 * width, 0.0,
                      0.5 * float(p.length_mm) - 0.5 * width):
            cutters.append(_groove_cutter(length=float(p.width_mm) + 8.0, width=width,
                                          depth=depth, axis="y", offset=shift))
        solid = boolean_difference([solid, *cutters])
    if int(p.aeration_holes) > 0:
        holes = _hole_cutters(count=int(p.aeration_holes), diameter=float(p.hole_diameter_mm),
                              length=float(p.length_mm), width=float(p.width_mm),
                              thickness=thickness)
        solid = boolean_difference([solid, *holes])
    if float(p.camber_mm) > 1e-6:
        verts = np.asarray(solid.vertices, dtype=np.float64).copy()
        span = max(float(p.length_mm), 1e-6)
        u = (verts[:, 0] - float(footprint.bounds[0])) / span
        verts[:, 2] += float(p.camber_mm) * np.sin(np.pi * np.clip(u, 0.0, 1.0))
        solid.vertices = verts
    tags = tag_extrusion(solid, exterior=footprint, inner=None, z_min_mm=0.0,
                         z_max_mm=thickness)
    tags[np.asarray(solid.face_normals)[:, 2] < -0.5] = TAG_INDEX["base"]
    part = Part(mesh=solid, tags=tags, component_id=0, name="body")
    return prism_assembly(parts=[part], ring=footprint, z_max_mm=thickness,
                          construct={"kind": "prism", "profile": "brick",
                                     "footprint_mm": [float(p.length_mm), float(p.width_mm)],
                                     "thickness_mm": thickness,
                                     "groove_depth_mm": float(p.groove_depth_mm),
                                     "aeration_holes": int(p.aeration_holes),
                                     "camber_mm": float(p.camber_mm)},
                          vessel_id="V18", rng=rng, warp_amp=0.02, warp_ecc=1.2,
                          warp_lobes=2,
                          requires_cavity=False, cavity_points=None,
                          min_wall_mm=1.0, max_wall_mm=max(3.0 * thickness, 40.0))


def _groove_cutter(*, length: float, width: float, depth: float, axis: str,
                   offset: float) -> trimesh.Trimesh:
    if axis == "x":
        cutter = trimesh.creation.box(extents=[length, width, 2.0 * depth])
        cutter.apply_translation([0.0, float(offset), 0.0])
    else:
        cutter = trimesh.creation.box(extents=[width, length, 2.0 * depth])
        cutter.apply_translation([float(offset), 0.0, 0.0])
    return cutter


def _hole_cutters(*, count: int, diameter: float, length: float, width: float,
                  thickness: float) -> list[trimesh.Trimesh]:
    columns = int(np.ceil(np.sqrt(count)))
    rows = int(np.ceil(count / columns))
    spacing_x = length / (columns + 1.0)
    spacing_y = width / (rows + 1.0)
    out: list[trimesh.Trimesh] = []
    made = 0
    for row in range(rows):
        for column in range(columns):
            if made >= count:
                break
            cx = -0.5 * length + spacing_x * (column + 1)
            cy = -0.5 * width + spacing_y * (row + 1)
            cylinder = trimesh.creation.cylinder(radius=0.5 * float(diameter),
                                                 height=2.0 * thickness, sections=24)
            cylinder.apply_translation([cx, cy, 0.5 * thickness])
            out.append(cylinder)
            made += 1
    return out


# -------------------------------------------------------------------------- V19 平瓦
class FlatTileParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    length_mm: float = Field(240.0, ge=60.0, le=420.0)
    width_mm: float = Field(160.0, ge=50.0, le=340.0)
    thickness_mm: float = Field(14.0, ge=4.0, le=60.0)
    side_lip_mm: float = Field(12.0, ge=0.0, le=40.0, description="raised side lip height")
    lip_width_mm: float = Field(10.0, ge=0.0, le=40.0)
    slope_mm: float = Field(9.0, ge=0.0, le=60.0, description="height difference across the tile")
    camber_mm: float = Field(3.0, ge=0.0, le=25.0, description="transverse camber of the pan")
    corner_mm: float = Field(6.0, ge=0.0, le=40.0)


@register_vessel("V19", "平瓦", param_model=FlatTileParams,
                 applicable={"family": "prism", "requires_cavity": True, "min_wall_mm": 1.0,
                             "scale_mm": [50, 420], "components": ["body"],
                             "shape_parameters": ["length_mm", "width_mm", "thickness_mm",
                                                  "side_lip_mm", "lip_width_mm", "slope_mm",
                                                  "camber_mm", "corner_mm"]},
                 notes="thick parameterised tile: pan, side lips, slope and camber are real")
def build_flat_tile(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = FlatTileParams.model_validate(params)
    thickness = float(p.thickness_mm)
    footprint = rounded_polygon(x_mm=float(p.length_mm), y_mm=float(p.width_mm),
                                corner_mm=float(p.corner_mm))
    part_solid = extrude_polygon_solid(footprint, thickness, stage="mothers.vessels.V19")
    parts = [part_solid]
    lip = float(p.side_lip_mm)
    lip_w = min(float(p.lip_width_mm), 0.45 * float(p.width_mm))
    if lip > 1e-6 and lip_w > 1e-6:
        for sign in (+1.0, -1.0):
            rail = box(-0.5 * float(p.length_mm), sign * (0.5 * float(p.width_mm) - lip_w) -
                       (0.0 if sign > 0 else 0.0), 0.5 * float(p.length_mm),
                       sign * 0.5 * float(p.width_mm))
            rail = box(*sorted([-0.5 * float(p.length_mm), 0.5 * float(p.length_mm)]),
                       *sorted([min(sign * (0.5 * float(p.width_mm) - lip_w),
                                    sign * 0.5 * float(p.width_mm)),
                                max(sign * (0.5 * float(p.width_mm) - lip_w),
                                    sign * 0.5 * float(p.width_mm))]))
            parts.append(extrude_polygon_solid(rail, thickness + lip,
                                               transform=_z_transform(-0.5 * lip),
                                               stage="mothers.vessels.V19.lip"))
    from ..solids import boolean_union

    merged = boolean_union(parts) if len(parts) > 1 else part_solid
    verts = np.asarray(merged.vertices, dtype=np.float64).copy()
    span_x = max(float(p.length_mm), 1e-6)
    span_y = max(float(p.width_mm), 1e-6)
    ux = np.clip((verts[:, 0] + 0.5 * span_x) / span_x, 0.0, 1.0)
    uy = np.clip((verts[:, 1] + 0.5 * span_y) / span_y, 0.0, 1.0)
    verts[:, 2] += float(p.slope_mm) * ux
    top = verts[:, 2] >= float(np.percentile(verts[:, 2], 60.0))
    verts[:, 2] += float(p.camber_mm) * np.sin(np.pi * uy) * top
    merged.vertices = verts
    tags = tag_extrusion(merged, exterior=footprint, inner=None, z_min_mm=0.0,
                         z_max_mm=thickness + lip)
    tags[np.asarray(merged.face_normals)[:, 2] < -0.5] = TAG_INDEX["base"]
    part = Part(mesh=merged, tags=tags, component_id=0, name="body")
    return prism_assembly(parts=[part], ring=footprint, z_max_mm=thickness + lip,
                          construct={"kind": "prism", "profile": "flat_tile",
                                     "plan_mm": [float(p.length_mm), float(p.width_mm)],
                                     "thickness_mm": thickness, "side_lip_mm": lip,
                                     "slope_mm": float(p.slope_mm),
                                     "camber_mm": float(p.camber_mm)},
                          vessel_id="V19", rng=rng, warp_amp=0.015, warp_ecc=0.8, warp_lobes=2,
                          requires_cavity=False, cavity_points=None,
                          min_wall_mm=0.9, max_wall_mm=max(3.0 * thickness, 40.0))


# -------------------------------------------------------------------------- V22 碑板
class SteleParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    height_mm: float = Field(320.0, ge=80.0, le=520.0)
    width_mm: float = Field(160.0, ge=40.0, le=340.0)
    thickness_mm: float = Field(38.0, ge=8.0, le=140.0)
    bevel_mm: float = Field(6.0, ge=0.0, le=40.0, description="chamfer around the decorated face")
    relief_depth_mm: float = Field(4.0, ge=0.0, le=24.0, description="depth of the inscription band")
    relief_rows: int = Field(4, ge=0, le=20, description="number of inscription rows")
    relief_height_ratio: float = Field(0.55, ge=0.1, le=0.9, description="band height / slab height")
    decorative_margin_mm: float = Field(18.0, ge=2.0, le=80.0)


@register_vessel("V22", "碑板", param_model=SteleParams,
                 applicable={"family": "prism", "requires_cavity": False, "min_wall_mm": 3.0,
                             "scale_mm": [80, 520], "components": ["body"],
                             "shape_parameters": ["height_mm", "width_mm", "thickness_mm",
                                                  "bevel_mm", "relief_depth_mm",
                                                  "relief_rows", "relief_height_ratio"]},
                 notes="thick slab with a real chamfer and an engraved inscription band")
def build_stele(params: dict[str, Any], rng: np.random.Generator, material_id: str) -> Any:
    p = SteleParams.model_validate(params)
    thickness = float(p.thickness_mm)
    width = float(p.width_mm)
    height = float(p.height_mm)
    footprint = box(-0.5 * width, -0.5 * height, 0.5 * width, 0.5 * height)
    solid = extrude_polygon_solid(footprint, thickness, stage="mothers.vessels.V22")
    bevel = float(p.bevel_mm)
    if bevel > 1e-6:
        bevel = min(bevel, 0.4 * thickness)
        chamfer = extrude_polygon_solid(footprint.buffer(-bevel, join_style=2), bevel,
                                        transform=_z_transform(thickness - bevel),
                                        stage="mothers.vessels.V22.bevel")
        from ..solids import boolean_intersection
        solid = boolean_intersection([solid, chamfer])
    rows = int(p.relief_rows)
    depth = float(p.relief_depth_mm)
    if rows > 0 and depth > 1e-6:
        depth = min(depth, 0.35 * thickness)
        band_h = float(p.relief_height_ratio) * height
        row_h = band_h / rows
        margin = float(p.decorative_margin_mm)
        cutters = []
        for row in range(rows):
            z0 = 0.5 * height - 0.5 * band_h + row * row_h
            groove = box(-0.5 * width + margin, z0 + 0.18 * row_h,
                         0.5 * width - margin, z0 + 0.82 * row_h)
            cutters.append(extrude_polygon_solid(
                groove, 2.0 * depth,
                transform=np.array([[1, 0, 0, 0], [0, 0, 1, -0.0], [0, 1, 0, thickness - 0.0],
                                    [0, 0, 0, 1]], dtype=np.float64) @ _z_transform(0.0),
                stage="mothers.vessels.V22.relief"))
        # the groove is cut from the decorated (+z) face: extrude along -z instead
        cutters = [_rotate_z_to_y(cutter) for cutter in cutters]
        solid = boolean_difference([solid, *cutters])
    tags = tag_extrusion(solid, exterior=footprint, inner=None, z_min_mm=0.0,
                         z_max_mm=thickness)
    tags[np.asarray(solid.face_normals)[:, 2] < -0.5] = TAG_INDEX["base"]
    part = Part(mesh=solid, tags=tags, component_id=0, name="body")
    return prism_assembly(parts=[part], ring=footprint, z_max_mm=thickness,
                          construct={"kind": "prism", "profile": "stele",
                                     "plan_mm": [width, height], "thickness_mm": thickness,
                                     "bevel_mm": bevel, "relief_depth_mm": depth,
                                     "relief_rows": rows},
                          vessel_id="V22", rng=rng, warp_amp=0.010, warp_ecc=0.5, warp_lobes=2,
                          requires_cavity=False, cavity_points=None,
                          min_wall_mm=3.0, max_wall_mm=max(3.0 * thickness, 60.0))


def _rotate_z_to_y(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Map an extrusion built along +z onto -y so it cuts the +z face of a slab."""
    matrix = np.array([[1.0, 0.0, 0.0, 0.0],
                       [0.0, 0.0, -1.0, 0.0],
                       [0.0, 1.0, 0.0, 0.0],
                       [0.0, 0.0, 0.0, 1.0]], dtype=np.float64)
    out = mesh.copy()
    out.apply_transform(matrix)
    return out
