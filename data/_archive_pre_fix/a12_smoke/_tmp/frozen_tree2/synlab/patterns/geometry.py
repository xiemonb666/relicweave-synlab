"""Real geometric relief / engraving on the **complete** mother body (plan 9.1 step 5).

Rules implemented here (honesty rules of the task):

* PAT14 / PAT15 displace real vertices of the whole mother body along the measured vertex
  normals with the signed ``height_mm`` channel.  A normal map is **never** used as a
  substitute; ``appearance_only_normal_map`` stays ``False`` in the recipe.
* The mesh is refined first when the frozen minimum wavelength is not representable
  (plan 9.2: "几何细节不足必须细化或拒绝"); refinement only bisects existing triangles, so the
  refined body is geometrically identical before displacement and every measured volume
  change is caused by the pattern.
* Depth is guarded against the measured wall thickness, faces that flipped are detected,
  and the interpolation error of the displacement field on the mesh is measured.
* Families without geometry return the **same** mother object (true identity).
"""

from __future__ import annotations

import math

from typing import Any

import numpy as np
import trimesh

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import MotherGeometry, PatternRecipe
from .charts import (ChartFrame, region_weight, resolve_frame, tag_index, to_chart_mm,
                     vertex_surface_tags)
from .serialize import geometry_hash

MAX_FACES_AFTER_REFINE = 400_000
#: Mesh samples across the smallest frozen geometric feature (plan 9.2: geometric detail
#: that the mesh cannot carry must be refined or refused, never replaced by a normal map).
GEOMETRY_SAMPLES_PER_FEATURE = 3.0


def _edge_stats(vertices: np.ndarray, faces: np.ndarray) -> dict[str, float]:
    edges = np.vstack([vertices[faces[:, 1]] - vertices[faces[:, 0]],
                       vertices[faces[:, 2]] - vertices[faces[:, 1]],
                       vertices[faces[:, 0]] - vertices[faces[:, 2]]])
    lengths = np.linalg.norm(edges, axis=1)
    return {"p50_mm": float(np.median(lengths)), "min_mm": float(lengths.min()),
            "max_mm": float(lengths.max())}


def measure_wall_thickness(mother: MotherGeometry, tag: int, rng: np.random.Generator,
                           *, n: int = 192) -> dict[str, Any]:
    """Ray-cast the local wall thickness at area-weighted points of one surface tag."""
    mesh = mother.mesh
    mask = np.asarray(mother.face_surface_tag) == int(tag)
    if not np.any(mask):
        return {"min_mm": 0.0, "p05_mm": 0.0, "median_mm": 0.0, "n_hits": 0.0}
    area = np.asarray(mesh.area_faces)[mask]
    prob = area / max(float(area.sum()), 1e-12)
    picks = rng.choice(np.flatnonzero(mask), size=int(n), p=prob)
    tri = np.asarray(mesh.triangles[picks], dtype=np.float64)
    u = rng.random((int(n), 1))
    v = rng.random((int(n), 1))
    flip = (u + v) > 1.0
    u[flip] = 1.0 - u[flip]
    v[flip] = 1.0 - v[flip]
    origins = tri[:, 0] + u * (tri[:, 1] - tri[:, 0]) + v * (tri[:, 2] - tri[:, 0])
    normals = np.asarray(mesh.face_normals[picks], dtype=np.float64)
    eps = 1e-4
    locations, index_ray, _ = mesh.ray.intersects_location(
        ray_origins=origins + normals * eps, ray_directions=-normals, multiple_hits=False)
    thickness = [float(np.linalg.norm(point - origins[ray_index]))
                 for ray_index, point in zip(index_ray, locations)]
    orientation = "outward"
    if len(thickness) < 0.2 * int(n):
        # no (or almost no) inward hit: retry with the opposite orientation instead of
        # reporting a zero wall thickness
        locations2, index_ray2, _ = mesh.ray.intersects_location(
            ray_origins=origins - normals * eps, ray_directions=normals, multiple_hits=False)
        thickness2 = [float(np.linalg.norm(point - origins[ray_index]))
                      for ray_index, point in zip(index_ray2, locations2)]
        if len(thickness2) > len(thickness):
            thickness = thickness2
            orientation = "inverted (face normals point into the material)"
    if len(thickness) < 0.2 * int(n):
        return {"status": "NOT_MEASURED", "min_mm": None, "p05_mm": None, "median_mm": None,
                "n_hits": float(len(thickness)), "n_samples": int(n),
                "normal_orientation": orientation,
                "reason": "fewer than 20% of the inward rays hit another surface; the local "
                          "wall thickness cannot be measured on this body",
                "method": "trimesh ray casting from area-weighted surface samples, both "
                          "orientations"}
    arr = np.asarray(thickness)
    return {
        "status": "OK", "min_mm": float(arr.min()), "p05_mm": float(np.percentile(arr, 5)),
        "median_mm": float(np.median(arr)), "n_hits": float(arr.size), "n_samples": int(n),
        "normal_orientation": orientation,
        "method": "trimesh ray casting inward from area-weighted surface samples",
    }


def _resolve_thickness(mother: MotherGeometry, tag: int, rng: np.random.Generator) -> dict[str, float]:
    declared = None
    if isinstance(mother.meta, dict):
        declared = mother.meta.get("min_wall_thickness_mm")
    if declared is None and isinstance(mother.params, dict):
        declared = mother.params.get("min_wall_thickness_mm")
    if declared is not None:
        return {"status": "OK", "min_mm": float(declared), "p05_mm": float(declared),
                "median_mm": float(declared), "n_hits": -1.0,
                "method": "declared by the mother (meta/params min_wall_thickness_mm)"}
    return measure_wall_thickness(mother, tag, rng)


def _region_bounds(recipe: PatternRecipe) -> dict:
    regions = (recipe.meta or {}).get("regions") or []
    if not regions:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "recipe has no frozen regions; cannot place geometry",
                          stage="patterns.geometry.apply_pattern_geometry")
    return regions[0]


def apply_pattern_geometry(mother: MotherGeometry, recipe: PatternRecipe, rng=None, *,
                           sample_density: float | None = None,
                           channels=None, allow_refine: bool = True,
                           max_faces: int = MAX_FACES_AFTER_REFINE) -> MotherGeometry:
    """Displace the complete mother body with the frozen relief / engraving field."""
    del channels  # channels are recomputed from the frozen recipe; kept for API symmetry
    height = dict((recipe.meta or {}).get("height") or {})
    mode = str(height.get("mode", "none"))
    if mode == "none":
        return mother
    if rng is None:
        rng = np.random.default_rng(0)
    target_tags = [str(t) for t in (height.get("target_tags") or [])]
    if not target_tags:
        target_tags = [str(_region_bounds(recipe).get("surface_tag"))]

    mesh = mother.mesh
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    tags = np.asarray(mother.face_surface_tag)
    hash_before = geometry_hash(vertices, faces)
    volume_before = float(abs(mesh.volume))
    area_before = float(mesh.area)
    edges_before = _edge_stats(vertices, faces)

    spectrum = dict((recipe.meta or {}).get("spectrum") or {})
    min_wavelength = spectrum.get("min_wavelength_mm") or spectrum.get("dominant_wavelength_mm")
    feature_mm = height.get("geometry_feature_mm")
    if sample_density is not None and float(sample_density) > 0:
        target_edge = float(np.sqrt(2.0 / float(sample_density)))
        rule = "sample_density: target edge = sqrt(2/sample_density) mm"
    elif feature_mm and float(feature_mm) > 0:
        target_edge = float(feature_mm) / GEOMETRY_SAMPLES_PER_FEATURE
        rule = (f"frozen geometric feature {float(feature_mm):.3f} mm "
                f"(mask feather / groove width) / {GEOMETRY_SAMPLES_PER_FEATURE:g} "
                "samples per feature")
    elif min_wavelength:
        target_edge = float(min_wavelength) / 6.0
        rule = "min_wavelength/6 from the measured spectrum (no frozen geometric feature)"
    else:
        target_edge = edges_before["p50_mm"]
        rule = "no measured spectrum available: refinement skipped"
    target_edge = max(target_edge, 0.05)
    refine_report: dict[str, object] = {"rule": rule, "target_edge_mm": target_edge,
                                        "edge_before": edges_before}
    if edges_before["p50_mm"] > target_edge:
        if not allow_refine:
            raise SynLabError(
                ErrorCode.PRECISION_NOT_REALIZED,
                f"mesh edge p50 {edges_before['p50_mm']:.3f} mm cannot represent features of "
                f"{target_edge * 6:.3f} mm and refinement is disabled",
                stage="patterns.geometry.apply_pattern_geometry",
                measurements={"edge_p50_mm": edges_before["p50_mm"],
                              "target_edge_mm": target_edge})
        # the face budget is honoured *before* refining: the requested edge is raised to the
        # value the budget allows and the reduction is recorded instead of being hidden
        # conservative estimate: subdivision is driven by the *longest* edges, so the
        # worst case scales with the largest edge present in the mesh
        estimated = faces.shape[0] * (edges_before["max_mm"] / target_edge) ** 2
        limited = False
        if estimated > int(max_faces):
            target_edge = edges_before["max_mm"] / math.sqrt(
                int(max_faces) / max(1.0, float(faces.shape[0])))
            limited = True
            refine_report["limited_by_face_budget"] = True
            refine_report["target_edge_mm"] = float(target_edge)
        try:
            vertices, faces, index = trimesh.remesh.subdivide_to_size(
                vertices, faces, max_edge=target_edge, max_iter=10, return_index=True)
        except ValueError as exc:
            raise SynLabError(
                ErrorCode.PRECISION_NOT_REALIZED,
                f"mesh refinement to {target_edge:.4f} mm did not converge: {exc}",
                stage="patterns.geometry.apply_pattern_geometry",
                measurements={"target_edge_mm": target_edge,
                              "edge_before_mm": edges_before["p50_mm"]}) from exc
        tags = tags[np.asarray(index, dtype=np.int64)]
        achieved = _edge_stats(vertices, faces)
        refine_report.update({"refined": True, "faces_after": int(faces.shape[0]),
                              "vertices_after": int(vertices.shape[0]),
                              "edge_after": achieved, "limited": bool(limited)})
        if faces.shape[0] > int(max_faces):
            raise SynLabError(
                ErrorCode.PRECISION_BUDGET_EXCEEDED,
                f"refinement to {target_edge:.3f} mm needs {faces.shape[0]} faces, above the "
                f"{int(max_faces)} face budget",
                stage="patterns.geometry.apply_pattern_geometry",
                measurements={"faces": int(faces.shape[0]), "target_edge_mm": target_edge})
        if min_wavelength:
            samples_per_wavelength = float(min_wavelength) / max(achieved["p50_mm"], 1e-9)
            refine_report["samples_per_min_wavelength"] = samples_per_wavelength
            if samples_per_wavelength < 2.0:
                raise SynLabError(
                    ErrorCode.PRECISION_BUDGET_EXCEEDED,
                    f"after refinement the mesh samples the {float(min_wavelength):.3f} mm "
                    f"feature with only {samples_per_wavelength:.2f} points per wavelength",
                    stage="patterns.geometry.apply_pattern_geometry",
                    measurements={"min_wavelength_mm": float(min_wavelength),
                                  "achieved_edge_mm": achieved["p50_mm"]})
    else:
        refine_report["refined"] = False

    from .builders import field_context
    from .fields import WarpField
    from .layers import build_field

    field = build_field(recipe.family_id, recipe.params)
    warp = WarpField.from_dict((recipe.meta or {}).get("warp"))
    ctx = field_context(recipe.meta, dict((recipe.meta or {}).get("palette") or {}), warp)
    bounds = _region_bounds(recipe)

    body = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    vertex_normals = np.asarray(body.vertex_normals, dtype=np.float64)
    proxy = MotherGeometry(mesh=body, face_surface_tag=tags,
                           surface_tag_names=dict(mother.surface_tag_names),
                           charts=list(mother.charts), vessel_id=mother.vessel_id,
                           material_id=mother.material_id, params=dict(mother.params),
                           mother_id=mother.mother_id, meta=dict(mother.meta or {}))
    vertex_tags = vertex_surface_tags(proxy)

    displacement = np.zeros(vertices.shape[0], dtype=np.float64)
    per_tag: dict[str, dict[str, float]] = {}
    first_frame: ChartFrame | None = None
    first_tag: int | None = None
    for name in target_tags:
        try:
            tag = tag_index(mother, name)
        except SynLabError:
            continue
        frame = resolve_frame(mother, tag)
        selected = vertex_tags == int(tag)
        if not np.any(selected):
            continue
        x_mm, s_mm = to_chart_mm(frame, vertices[selected])
        weight = region_weight(frame, vertices[selected], x_mm, s_mm, bounds)
        out = field.process(x_mm, s_mm, ctx)
        h = out.height_mm * weight
        displacement[selected] = h
        per_tag[name] = {"n_vertices": int(selected.sum()),
                         "max_abs_mm": float(np.abs(h).max()) if h.size else 0.0,
                         "mean_abs_mm": float(np.abs(h).mean()) if h.size else 0.0}
        if first_frame is None:
            first_frame, first_tag = frame, int(tag)

    max_abs = float(np.abs(displacement).max()) if displacement.size else 0.0
    if max_abs <= 1e-12:
        return _with_evidence(mother, mesh, tags, {
            "mode": mode, "applied": False,
            "reason": "the frozen height field is zero on the target surfaces",
            "geometry_hash_before": hash_before, "geometry_hash_after": hash_before,
            "volume_before_mm3": volume_before, "volume_after_mm3": volume_before,
        })

    thickness = _resolve_thickness(mother, int(first_tag if first_tag is not None else 0), rng)
    max_fraction = float(height.get("max_wall_fraction", 0.25))
    if thickness.get("status", "OK") != "OK" or thickness.get("min_mm") is None:
        # the thin-wall QA of plan 7.1 cannot be evaluated: refuse instead of applying a
        # displacement whose safety is unknown, and say exactly what is missing
        raise SynLabError(
            ErrorCode.INTEGRATION_PENDING,
            "the local wall thickness is neither declared by the mother "
            "(meta/params min_wall_thickness_mm) nor measurable by ray casting, so the "
            "thin-wall guard required for relief/engraving cannot be evaluated",
            stage="patterns.geometry.apply_pattern_geometry",
            measurements={"n_hits": thickness.get("n_hits"),
                          "n_samples": thickness.get("n_samples"),
                          "normal_orientation": thickness.get("normal_orientation"),
                          "reason": str(thickness.get("reason", ""))})
    allowed = max_fraction * float(thickness["min_mm"])
    if max_abs > allowed:
        raise SynLabError(
            ErrorCode.TARGET_INFEASIBLE,
            f"{mode} amplitude {max_abs:.3f} mm exceeds {max_fraction:.2f} of the measured "
            f"wall thickness ({thickness['min_mm']:.3f} mm -> {allowed:.3f} mm allowed)",
            stage="patterns.geometry.apply_pattern_geometry",
            measurements={"max_abs_height_mm": max_abs, "allowed_mm": allowed,
                          "wall_thickness_mm": float(thickness["min_mm"]),
                          "thickness_method": str(thickness.get("method", ""))})

    new_vertices = vertices + vertex_normals * displacement[:, None]
    new_mesh = trimesh.Trimesh(vertices=new_vertices, faces=faces, process=False)
    moved = np.abs(displacement) > 1e-12
    dot = np.einsum("ij,ij->i", np.asarray(body.face_normals), np.asarray(new_mesh.face_normals))
    flipped = int(np.sum(dot < 0.0))
    interpolation = _interpolation_error(field, ctx, recipe, bounds, new_vertices, faces, tags,
                                        displacement, target_tags, mother)
    volume_after = float(abs(new_mesh.volume))
    evidence = {
        "mode": mode,
        "applied": True,
        "refinement": refine_report,
        "vertex_displacement_max_mm": max_abs,
        "vertex_displacement_mean_mm": (float(np.abs(displacement[moved]).mean())
                                        if np.any(moved) else 0.0),
        "n_vertices_displaced": int(moved.sum()),
        "n_vertices_total": int(vertices.shape[0]),
        "n_faces": int(faces.shape[0]),
        "per_tag": per_tag,
        "volume_before_mm3": volume_before,
        "volume_after_mm3": volume_after,
        "volume_delta_mm3": volume_after - volume_before,
        "area_before_mm2": area_before,
        "area_after_mm2": float(new_mesh.area),
        "geometry_hash_before": hash_before,
        "geometry_hash_after": geometry_hash(new_vertices, faces),
        "watertight_after": bool(new_mesh.is_watertight),
        "flipped_faces": flipped,
        "interpolation_error_mm": interpolation,
        "wall_thickness": thickness,
        "wall_fraction_limit": max_fraction,
        "displacement_direction": ("outward along the measured vertex normal for relief, inward "
                                   "for engraving (signed height_mm)"),
        "appearance_only_normal_map": False,
        "boolean_tool_route": ("NOT_IMPLEMENTED (plan 9.3 allows a closed-tool boolean for "
                               "engraving; this implementation uses real vertex displacement)"),
        "units": "mm",
    }
    return _with_evidence(mother, new_mesh, tags, evidence, displacement_mm=displacement)


def _interpolation_error(field, ctx, recipe: PatternRecipe, bounds: dict,
                         vertices: np.ndarray, faces: np.ndarray, face_tags: np.ndarray,
                         displacement: np.ndarray, target_tags: list[str],
                         mother: MotherGeometry) -> dict[str, float]:
    """How well the mesh interpolates the analytic displacement field."""
    worst = 0.0
    checked = 0
    for name in target_tags:
        try:
            tag = tag_index(mother, name)
        except SynLabError:
            continue
        frame = resolve_frame(mother, tag)
        selected = face_tags == int(tag)
        if not np.any(selected):
            continue
        picked = np.flatnonzero(selected)
        # bound the interpolation measurement: at most 20000 faces per tag, recorded
        if picked.size > 20000:
            step = int(np.ceil(picked.size / 20000))
            picked = picked[::step]
        centroids = vertices[faces[picked]].mean(axis=1)
        x_mm, s_mm = to_chart_mm(frame, centroids)
        weight = region_weight(frame, centroids, x_mm, s_mm, bounds)
        analytic = field.process(x_mm, s_mm, ctx).height_mm * weight
        nodal = displacement[faces[picked]].mean(axis=1)
        worst = max(worst, float(np.abs(analytic - nodal).max()))
        checked += int(picked.size)
    return {"max_abs_error_mm": worst, "n_faces_checked": checked,
            "method": "analytic height at face centroids vs mean nodal displacement"}


def _with_evidence(mother: MotherGeometry, mesh, tags: np.ndarray, evidence: dict,
                   displacement_mm: np.ndarray | None = None) -> MotherGeometry:
    meta = dict(mother.meta or {})
    meta["pattern_geometry"] = evidence
    meta["geometry_hash_before"] = evidence.get("geometry_hash_before")
    meta["geometry_hash_after"] = evidence.get("geometry_hash_after")
    if displacement_mm is not None:
        meta["pattern_displacement_mm"] = {
            "min": float(displacement_mm.min()), "max": float(displacement_mm.max()),
            "units": "mm", "direction": "along the vertex normal",
        }
    mesh.metadata = dict(mesh.metadata or {})
    attrs = dict(mesh.metadata.get("face_attr_arrays") or {})
    attrs["surface_tag"] = np.asarray(tags)
    mesh.metadata["face_attr_arrays"] = attrs
    return MotherGeometry(
        mesh=mesh, face_surface_tag=np.asarray(tags),
        surface_tag_names=dict(mother.surface_tag_names), charts=list(mother.charts),
        vessel_id=mother.vessel_id, material_id=mother.material_id,
        params=dict(mother.params), mother_id=mother.mother_id, meta=meta)
