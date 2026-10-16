"""P01–P08 only-remove-material algorithms (plan 12.2, 12.3, 30.7).

Every geometry axis follows the frozen pipeline: ROI → halo (> maximum erosion depth +
isosurface halo) → uniform grid origin/spacing → ``d0`` → add the non-negative field →
marching cubes → shared seam nodes → merge/clean → intersect with the source → QA.  The
appearance axes (P05, P06 appearance variant, P08 paint variant) never touch geometry and
report the geometry hash they measured instead of claiming it.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from ..errors import ErrorCode, SynLabError
from . import fields as F
from . import sdf as S
from .recipe import DamageOutcome, DamageRecipe

DEG = 180.0 / np.pi


# ---------------------------------------------------------------------------- context


class SdfContext:
    """Uniform grid + signed distance + ROI weight machinery shared by the geometry axes."""

    def __init__(self, mesh: trimesh.Trimesh, recipe: DamageRecipe, *, fragment: Any = None) -> None:
        self.mesh = mesh
        self.recipe = recipe
        self.fragment = fragment
        thickness = S.ray_thickness(mesh, n_samples=160, seed=int(recipe.basis.get("seed", 0)) % 997)
        structure = float(recipe.meta.get("shortest_structure_mm", 0.0) or 0.0)
        extent = np.asarray(mesh.bounds[1]) - np.asarray(mesh.bounds[0])
        if structure <= 0:
            structure = float(np.min(extent))
        grid_spec = dict(recipe.grid or {})
        spacing_choice = S.choose_spacing(
            min_wall_thickness_mm=max(thickness["p05_mm"], 1e-3),
            shortest_structure_mm=structure,
            requested_mm=grid_spec.get("spacing_mm"),
            max_nodes=int(grid_spec.get("max_nodes", 1_500_000)),
            bbox_mm=tuple(float(v) for v in extent),
        )
        self.spacing_info = {**spacing_choice, "measured_thickness": thickness}
        self.spacing = float(spacing_choice["spacing_mm"])
        self.pad_mm = float(grid_spec.get("pad_mm", max(1.0, 2.0 * self.spacing)))
        self.grid = S.grid_for_mesh(mesh, self.spacing, pad_mm=self.pad_mm,
                                    backend=recipe.sdf_backend or S.DEFAULT_SDF_BACKEND)
        self.d0, self.sdf_info = S.signed_distance_field(
            mesh, self.grid, backend=recipe.sdf_backend,
            surface_check_samples=int(grid_spec.get("surface_check_samples", 800)),
            seed=int(recipe.basis.get("seed", 1)) % 1024)
        self.roi_ids, self.roi_info = F.roi_faces(mesh, fragment, recipe.roi)
        density = float(grid_spec.get("roi_density_mm", max(self.spacing, 0.4)))
        self.anchors = F.roi_anchor_points(mesh, self.roi_ids, density_mm=density)
        self.anchor_normals = np.asarray(mesh.face_normals, dtype=np.float64)[self.roi_ids]
        self.anchor_points = np.asarray(mesh.triangles_center, dtype=np.float64)[self.roi_ids]
        self.interface_area_mm2 = float(np.sum(np.asarray(mesh.area_faces, dtype=np.float64)[self.roi_ids]))
        self.tree = cKDTree(self.anchors)

    # ------------------------------------------------------------------ weights
    def weight(self, points: np.ndarray, *, core_mm: float, halo_mm: float) -> np.ndarray:
        dist, _ = self.tree.query(np.asarray(points, dtype=np.float64), workers=1)
        return F.smoothstep((float(halo_mm) - dist) / max(float(halo_mm) - float(core_mm), 1e-9))

    def nearest_anchor(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        dist, idx = self.tree.query(np.asarray(points, dtype=np.float64), workers=1)
        return dist, idx

    def contact_state(self, body: trimesh.Trimesh, *, eps_mm: float = 2e-3) -> dict[str, float]:
        """Residual contact of the original interface patch (measured by occupancy)."""
        return F.interface_contact(self.mesh, self.fragment, self.recipe.roi, body, eps_mm=eps_mm,
                                   density_mm=float(self.recipe.grid.get("roi_density_mm", 0.5)))

    # ------------------------------------------------------------------ extraction
    def extract(self, b_fn: Callable[[np.ndarray], np.ndarray], *, t: float, core_mm: float,
                halo_mm: float, label: str = "") -> tuple[trimesh.Trimesh, dict[str, Any]]:
        """``M_t = {d0 + t·α·b ≤ 0}``, then intersect with the source and fix nesting."""
        if t <= 0:
            raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING,
                              f"{label}: zero-strength extraction requested", stage="physical.extract")
        tree = self.tree
        halo = float(halo_mm)
        core = float(core_mm)

        def pointwise(points: np.ndarray) -> np.ndarray:
            dist, _ = tree.query(points, workers=1)
            alpha = F.smoothstep((halo - dist) / max(halo - core, 1e-9))
            return float(t) * alpha * np.maximum(np.asarray(b_fn(points), dtype=np.float64), 0.0)

        field, chunk_info = S.evaluate_field(self.grid, pointwise, base=self.d0,
                                             chunk=int(self.recipe.grid.get("chunk", 24)),
                                             halo=int(self.recipe.grid.get("halo", 1)))
        applied = field - self.d0
        roi_nodes = applied > 0
        candidate = S.marching_cubes_mesh(field, self.grid)
        accepted, clip_info = S.intersect_with_source(candidate, self.mesh)
        nesting_info = {"applied": False, "removed_volume_mm3": 0.0, "removed_area_mm2": 0.0}
        previous = self.recipe.previous_mesh
        if previous is not None and bool((self.recipe.nesting or {}).get("correct", True)):
            before_v = float(abs(accepted.volume))
            before_a = float(accepted.area)
            nested = S.boolean_op("intersection", [accepted, previous])
            removed_v = max(0.0, before_v - float(abs(nested.volume)))
            removed_a = max(0.0, before_a - float(nested.area))
            budget_rel = float((self.recipe.nesting or {}).get("budget_rel", 0.02))
            base_v = max(float(abs(previous.volume)), 1e-9)
            nesting_info = {
                "applied": True, "removed_volume_mm3": removed_v, "removed_area_mm2": removed_a,
                "removed_volume_rel": removed_v / base_v,
                "budget_rel": budget_rel,
                "within_budget": bool(removed_v / base_v <= budget_rel),
            }
            accepted = nested
        info = {
            "label": label, "t": float(t), "core_mm": core, "halo_mm": halo,
            "field_max_mm": float(applied.max()), "field_mean_roi_mm": float(applied[roi_nodes].mean())
            if roi_nodes.any() else 0.0,
            "field_nodes_nonzero": int(roi_nodes.sum()),
            "chunk": chunk_info, "clip": clip_info, "nesting": nesting_info,
            "sdf": {k: v for k, v in self.sdf_info.items() if k != "grid"},
            "grid": self.grid.as_dict(), "spacing": self.spacing_info,
            "roi": self.roi_info, "mesh": S.watertight_report(accepted),
        }
        return accepted, info


# ---------------------------------------------------------------------------- helpers


def _lattice_from_points(points: np.ndarray, model: F.HeightModel) -> F.HeightModel:
    """Rebuild a height lattice on the *same* frame/lattice from another point set."""
    pts = np.asarray(points, dtype=np.float64)
    uvw = model.frame.to_uvw(pts)
    iu = np.rint((uvw[:, 0] - model.u0) / model.du).astype(np.int64)
    iv = np.rint((uvw[:, 1] - model.v0) / model.dv).astype(np.int64)
    ok = (iu >= 0) & (iu < model.shape[0]) & (iv >= 0) & (iv < model.shape[1])
    iu, iv, w = iu[ok], iv[ok], uvw[ok, 2]
    f = np.full(model.shape, -np.inf, dtype=np.float64)
    lo = np.full(model.shape, np.inf, dtype=np.float64)
    np.maximum.at(f, (iu, iv), w)
    np.minimum.at(lo, (iu, iv), w)
    valid = np.isfinite(f)
    spread = np.where(valid, f - lo, 0.0)
    return F.HeightModel(frame=model.frame, u0=model.u0, v0=model.v0, du=model.du, dv=model.dv,
                         f=np.where(valid, f, 0.0), valid=valid, w_spread_mm=spread,
                         multi_valued_mm=model.multi_valued_mm, source="damaged_surface")


def _interface_surface_points(mesh: trimesh.Trimesh, ctx: SdfContext, *, halo_mm: float,
                              n: int = 4000, seed: int = 0) -> np.ndarray:
    """Surface samples of ``mesh`` inside the ROI band (used to re-measure the height map)."""
    pts, _fid = trimesh.sample.sample_surface(mesh, int(n), seed=int(seed) % (2**31))
    pts = np.asarray(pts, dtype=np.float64)
    dist, _ = ctx.tree.query(pts, workers=1)
    return pts[dist <= float(halo_mm)]


def _removed_surface_points(body: trimesh.Trimesh, ctx: SdfContext, *, n: int = 3000,
                            seed: int = 0) -> np.ndarray:
    """Original surface samples whose material is gone in ``body`` (spatial loss map)."""
    pts, _fid = trimesh.sample.sample_surface(ctx.mesh, int(n), seed=int(seed) % (2**31))
    pts = np.asarray(pts, dtype=np.float64)
    inside = S.scene_for(body).occupancy(pts)
    return pts[~inside]


def _edge_localization(removed: np.ndarray, edge_points: np.ndarray, radius: float) -> dict[str, float]:
    if len(removed) == 0 or len(edge_points) == 0:
        return {"removed_samples": float(len(removed)), "within_2r_fraction": 0.0}
    tree = cKDTree(edge_points)
    dist, _ = tree.query(removed, workers=1)
    return {"removed_samples": float(len(removed)),
            "within_2r_fraction": float((dist <= 2.0 * radius).mean()),
            "edge_distance_mean_mm": float(dist.mean())}


def _thickness_guarded(extract: Callable[[float], tuple[trimesh.Trimesh, dict[str, Any]]],
                       *, guard_mm: float | None, max_iterations: int = 3,
                       seed: int = 0) -> tuple[trimesh.Trimesh, dict[str, Any], dict[str, Any]]:
    """Reduce the depth until the measured minimum wall thickness respects the guard."""
    info: dict[str, Any] = {"guard_mm": guard_mm, "iterations": 0}
    if not guard_mm:
        body, detail = extract(1.0)
        info["iterations"] = 1
        info["thickness"] = S.ray_thickness(body, n_samples=200, seed=seed)["min_mm"]
        info["satisfied"] = True
        return body, detail, info
    scale = 1.0
    body, detail = extract(scale)
    thickness = S.ray_thickness(body, n_samples=200, seed=seed)
    info["iterations"] = 1
    while thickness["min_mm"] < float(guard_mm) and info["iterations"] < max_iterations:
        scale *= 0.5
        body, detail = extract(scale)
        thickness = S.ray_thickness(body, n_samples=200, seed=seed)
        info["iterations"] += 1
    info["thickness"] = thickness
    info["final_scale"] = scale
    info["satisfied"] = bool(thickness["min_mm"] >= float(guard_mm))
    return body, detail, info


# ---------------------------------------------------------------------------- P01


def polish_interface(mesh: trimesh.Trimesh, recipe: DamageRecipe, *, fragment: Any = None) -> DamageOutcome:
    """P01: own-outward height low-pass with ``target = g + c ≤ f`` (plan 12.2, 30.7)."""
    ctx = SdfContext(mesh, recipe, fragment=fragment)
    strength = float(recipe.parameter("recession_strength", 0.0))
    radius_mm = float(recipe.parameter("radius_mm", recipe.meta.get("radius_mm", 1.0)))
    if strength <= 0:
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING, "P01 recession_strength must be > 0",
                          stage="physical.P01")
    surface = _interface_surface_points(ctx.mesh, ctx, halo_mm=max(3.0 * radius_mm, 1.0),
                                        n=int(recipe.meta.get("samples", 6000)),
                                        seed=int(recipe.basis.get("seed", 0)))
    if len(surface) < 32:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                          f"P01 needs a single-valued patch with >= 32 interface samples, got {len(surface)}",
                          stage="physical.P01")
    normals = None
    dist, idx = ctx.tree.query(surface, workers=1)
    if len(ctx.anchors):
        normals = np.asarray(mesh.face_normals, dtype=np.float64)[ctx.roi_ids][
            np.clip(idx, 0, len(ctx.roi_ids) - 1)]
    cell_mm = float(recipe.meta.get("cell_mm", max(0.25, radius_mm / 2.0)))
    model = F.height_model(surface, normals, cell_mm=cell_mm,
                           multi_valued_mm=float(recipe.meta.get("multi_valued_mm", 2.0)))
    sigma_cells = max(1.0, radius_mm / max(0.5 * (model.du + model.dv), 1e-6))
    model_single = model.single_valued_fraction >= float(recipe.meta.get("single_valued_min", 0.9))
    fallback = None
    if model_single:
        target, target_info = model.static_target(sigma_cells)
        recession = np.maximum(model.f - target, 0.0)
        recession = np.where(model.valid, recession, 0.0)
        recession_model = replace(model, f=recession)
        max_recession = float(recession[model.valid].max()) if model.valid.any() else 0.0
        if max_recession <= 0:
            raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING,
                              "P01: the low-pass target equals the source height everywhere "
                              "(no high-frequency content in the frozen band)",
                              stage="physical.P01")

        def b_fn(points: np.ndarray) -> np.ndarray:
            values, hit = recession_model.sample(points)
            return np.where(hit, values, 0.0)
    else:
        # multi-valued / high curvature patch: local SDF morphological opening (plan 12.2)
        fallback = {"reason": "patch not single-valued",
                    "single_valued_fraction": model.single_valued_fraction,
                    "multi_valued_cells": model.multi_valued_cells}
        erosion_depth = float(recipe.parameter("radius_mm", 1.0)) * 0.25 * strength
        b_fn = lambda points: np.full(len(points), erosion_depth)  # noqa: E731
        target, target_info = None, {"fallback": True, "erosion_depth_mm": erosion_depth}
        max_recession = erosion_depth
    halo = max(2.5 * radius_mm, max_recession + 2.0 * ctx.spacing)
    body, detail = ctx.extract(b_fn, t=strength, core_mm=0.0, halo_mm=halo, label="P01")
    damaged_surface = _interface_surface_points(body, ctx, halo_mm=halo,
                                                n=int(recipe.meta.get("samples", 6000)),
                                                seed=int(recipe.basis.get("seed", 0)) + 1)
    after = _lattice_from_points(damaged_surface, model)
    shared = model.valid & after.valid
    hf_before = model.high_frequency_rms(sigma_cells, mask=shared) if shared.any() else 0.0
    hf_after = after.high_frequency_rms(sigma_cells, mask=shared) if shared.any() else 0.0
    removed = _removed_surface_points(body, ctx, n=2500, seed=int(recipe.basis.get("seed", 0)) + 2)
    thickness = S.ray_thickness(body, n_samples=200, seed=3)
    measurements = {
        "recession_strength": strength,
        "radius_mm": radius_mm,
        "target_le_f": 1.0 if target_info.get("target_le_f", True) else 0.0,
        "static_target_c_mm": float(target_info.get("c_mm", 0.0)),
        "max_recession_mm": max_recession,
        "mean_recession_mm": float(target_info.get("recession_mean_mm", max_recession)),
        "hf_rms_before_mm": float(hf_before),
        "hf_rms_after_mm": float(hf_after),
        "hf_rms_reduction": float(hf_before - hf_after),
        "hf_rms_reduction_rel": float((hf_before - hf_after) / hf_before) if hf_before > 1e-12 else 0.0,
        "shared_cells": float(int(shared.sum())),
        "single_valued_fraction": float(model.single_valued_fraction),
        "fallback_used": 1.0 if fallback else 0.0,
        "lost_volume_mm3": float(abs(ctx.mesh.volume) - abs(body.volume)),
        "min_thickness_mm": thickness["min_mm"],
        "p05_thickness_mm": thickness["p05_mm"],
        "roi_external_drift_mm": _roi_external_drift(body, ctx, halo_mm=halo),
    }
    measurements["edge_localization_within_2r"] = _edge_localization(
        removed, _roi_edge_samples(ctx), radius_mm)["within_2r_fraction"]
    details = {"sdf_pipeline": detail, "height_model": {"shape": list(model.shape),
                                                        "coverage": model.coverage,
                                                        "cell_mm": [model.du, model.dv],
                                                        "sigma_cells": sigma_cells},
               "target_info": target_info, "fallback": fallback,
               "removed_samples": int(len(removed))}
    realized = bool(hf_before - hf_after > 1e-6 and measurements["lost_volume_mm3"] > 0)
    return DamageOutcome(mesh=body, measurements=measurements,
                         units={"max_recession_mm": "mm", "hf_rms_before_mm": "mm",
                                "hf_rms_after_mm": "mm", "hf_rms_reduction": "mm",
                                "lost_volume_mm3": "mm3", "min_thickness_mm": "mm",
                                "roi_external_drift_mm": "mm"},
                         details=details, realized=realized)


def _roi_edge_samples(ctx: SdfContext, *, min_angle_deg: float = 25.0) -> np.ndarray:
    edges = F.convex_edges(ctx.mesh, min_angle_deg=min_angle_deg, face_ids=ctx.roi_ids)
    return F.edge_sample_points(ctx.mesh, edges, density_mm=max(ctx.spacing, 0.3))


def _roi_external_drift(body: trimesh.Trimesh, ctx: SdfContext, *, halo_mm: float,
                        n: int = 1500, seed: int = 7) -> float:
    """Max displacement of the *non-ROI* surface: must stay ~0 (plan 12.2 P03/P07)."""
    pts, _fid = trimesh.sample.sample_surface(ctx.mesh, int(n), seed=int(seed))
    pts = np.asarray(pts, dtype=np.float64)
    dist, _ = ctx.tree.query(pts, workers=1)
    outside = pts[dist > float(halo_mm)]
    if len(outside) == 0:
        return 0.0
    inside = S.scene_for(body).occupancy(outside)
    moved = outside[~inside]
    if len(moved) == 0:
        return 0.0
    return float(S.scene_for(body).unsigned_distance(moved).max())


# ---------------------------------------------------------------------------- P02


def round_edge(mesh: trimesh.Trimesh, recipe: DamageRecipe, *, fragment: Any = None) -> DamageOutcome:
    """P02: edge-distance driven inward fillet; never a whole-patch Laplacian (plan 12.2)."""
    ctx = SdfContext(mesh, recipe, fragment=fragment)
    strength = float(recipe.parameter("recession_strength", 0.0))
    radius_mm = float(recipe.parameter("edge_width_mm", recipe.meta.get("edge_width_mm", 0.4)))
    variant = recipe.variant or "sdf_fillet"
    if strength <= 0:
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING, "P02 recession_strength must be > 0",
                          stage="physical.P02")
    edges = F.convex_edges(ctx.mesh, min_angle_deg=float(recipe.meta.get("min_edge_angle_deg", 25.0)),
                           face_ids=ctx.roi_ids)
    if len(edges) == 0:
        edges = F.convex_edges(ctx.mesh, min_angle_deg=float(recipe.meta.get("min_edge_angle_deg", 25.0)))
    edge_points = F.edge_sample_points(ctx.mesh, edges, density_mm=max(ctx.spacing * 0.5, 0.2))
    if len(edge_points) < 4:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                          "P02 needs convex edges on the ROI boundary; none found",
                          stage="physical.P02")
    angles = F.dihedral_angles_at_edges(ctx.mesh, edges)
    if len(angles) == len(edges) and len(edges):
        seg_mid = np.asarray(ctx.mesh.vertices, dtype=np.float64)[edges].mean(axis=1)
        angle_tree = cKDTree(seg_mid)
        _d, nearest = angle_tree.query(edge_points, workers=1)
        edge_angle = angles[np.clip(nearest, 0, len(angles) - 1)]
    else:
        edge_angle = np.full(len(edge_points), 90.0)
    half = np.radians(np.clip(edge_angle, 5.0, 175.0)) / 2.0
    depth_needed = np.clip(radius_mm * (1.0 / np.maximum(np.sin(half), 1e-3) - 1.0), 0.0, 4.0 * radius_mm)
    chamfer = variant == "chamfer"
    if chamfer:
        # planar chamfer: linear profile, generates a new edge (must be declared, plan 30.7)
        profile = lambda rho, r: np.clip(1.0 - np.asarray(rho) / max(r, 1e-9), 0.0, 1.0)  # noqa: E731
    else:
        profile = F.bump_profile
    tree = cKDTree(edge_points)

    def b_fn(points: np.ndarray) -> np.ndarray:
        dist, idx = tree.query(np.asarray(points, dtype=np.float64), workers=1)
        return depth_needed[np.clip(idx, 0, len(depth_needed) - 1)] * profile(dist, radius_mm)

    body, detail = ctx.extract(b_fn, t=strength, core_mm=0.0, halo_mm=2.0 * radius_mm + 2.0 * ctx.spacing,
                               label="P02")
    removed = _removed_surface_points(body, ctx, n=2500, seed=int(recipe.basis.get("seed", 0)) + 5)
    localization = _edge_localization(removed, edge_points, radius_mm)
    after_edges = F.convex_edges(body, min_angle_deg=float(recipe.meta.get("min_edge_angle_deg", 25.0)),
                                 face_ids=None)
    after_angles = F.dihedral_angles_at_edges(body, after_edges) if len(after_edges) else np.zeros(0)
    sharp_before = int(np.sum(np.asarray(angles) >= 30.0)) if len(angles) else 0
    sharp_after = int(np.sum(after_angles >= 30.0)) if len(after_angles) else 0
    measurements = {
        "recession_strength": strength,
        "edge_width_mm": radius_mm,
        "max_recession_mm": float(np.max(depth_needed)) if len(depth_needed) else 0.0,
        "mean_recession_mm": float(np.mean(depth_needed)) if len(depth_needed) else 0.0,
        "edge_samples": float(len(edge_points)),
        "edge_dihedral_median_deg": float(np.median(edge_angle)) if len(edge_angle) else 0.0,
        "lost_volume_mm3": float(abs(ctx.mesh.volume) - abs(body.volume)),
        "lost_area_mm2": float(ctx.mesh.area - body.area),
        "removed_within_2r_fraction": float(localization["within_2r_fraction"]),
        "sharp_edges_before": float(sharp_before),
        "sharp_edges_after": float(sharp_after),
        "new_sharp_edge_ratio": float(sharp_after / max(sharp_before, 1)),
        "chamfer_variant": 1.0 if chamfer else 0.0,
        "min_thickness_mm": S.ray_thickness(body, n_samples=160, seed=4)["min_mm"],
        "roi_external_drift_mm": _roi_external_drift(body, ctx, halo_mm=2.0 * radius_mm + ctx.spacing),
    }
    realized = bool(measurements["lost_volume_mm3"] > 0 and localization["within_2r_fraction"] > 0.5)
    details = {"sdf_pipeline": detail, "edges_before": int(len(edges)), "edges_after": int(len(after_edges)),
               "variant": variant}
    return DamageOutcome(mesh=body, measurements=measurements,
                         units={"max_recession_mm": "mm", "lost_volume_mm3": "mm3",
                                "edge_width_mm": "mm", "min_thickness_mm": "mm",
                                "roi_external_drift_mm": "mm"},
                         details=details, realized=realized)


# ---------------------------------------------------------------------------- P03 / P07


def _smooth_recession(mesh: trimesh.Trimesh, recipe: DamageRecipe, *, fragment: Any,
                      depth_mm: float, label: str, roi: dict[str, Any] | None,
                      thickness_guard_mm: float | None) -> DamageOutcome:
    if roi is not None:
        recipe = replace(recipe, roi=roi)
    ctx = SdfContext(mesh, recipe, fragment=fragment)
    field = F.FourierField.from_payload(recipe.basis["field"])
    scale_mm = float(recipe.parameter("corr_length_mm", recipe.meta.get("corr_length_mm", 6.0)))
    anchor_values = np.clip(field(ctx.anchors), 0.0, 1.0)
    normalizer = float(max(np.percentile(anchor_values, 99.0), 1e-6))

    def b_fn(points: np.ndarray) -> np.ndarray:
        return float(depth_mm) * np.clip(field(points) / normalizer, 0.0, 1.0)

    halo = float(depth_mm) * 2.0 + float(recipe.meta.get("halo_mm", 3.0 * ctx.spacing + 1.0))

    def extract(scale: float) -> tuple[trimesh.Trimesh, dict[str, Any]]:
        return ctx.extract(b_fn, t=float(scale), core_mm=0.0, halo_mm=halo, label=label)

    body, detail, guard = _thickness_guarded(extract, guard_mm=thickness_guard_mm,
                                             seed=int(recipe.basis.get("seed", 0)) + 9)
    removed = _removed_surface_points(body, ctx, n=2500, seed=int(recipe.basis.get("seed", 0)) + 6)
    thickness = guard.get("thickness") or S.ray_thickness(body, n_samples=200, seed=6)
    contact = ctx.contact_state(body)
    measurements = {
        "depth_mm": float(depth_mm),
        "corr_length_mm": scale_mm,
        "field_normalizer": normalizer,
        "realized_max_recession_mm": float(detail["field_max_mm"]),
        "realized_mean_recession_mm": float(detail["field_mean_roi_mm"]),
        "lost_volume_mm3": float(abs(ctx.mesh.volume) - abs(body.volume)),
        "lost_volume_ratio": float(1.0 - abs(body.volume) / max(abs(ctx.mesh.volume), 1e-12)),
        "roi_external_drift_mm": _roi_external_drift(body, ctx, halo_mm=halo),
        "contact_lost_fraction": float(contact["lost_fraction"]),
        "contact_residual_area_mm2": float(contact["residual_area_mm2"]),
        "min_thickness_mm": thickness["min_mm"],
        "thickness_guard_satisfied": 1.0 if guard.get("satisfied", True) else 0.0,
        "thickness_guard_iterations": float(guard.get("iterations", 1)),
        "removed_samples": float(len(removed)),
    }
    realized = bool(measurements["lost_volume_mm3"] > 1e-9)
    details = {"sdf_pipeline": detail, "thickness_guard": guard, "field_id": field.field_id,
               "roi": ctx.roi_info}
    return DamageOutcome(mesh=body, measurements=measurements,
                         units={"depth_mm": "mm", "lost_volume_mm3": "mm3",
                                "realized_max_recession_mm": "mm", "min_thickness_mm": "mm",
                                "roi_external_drift_mm": "mm",
                                "contact_residual_area_mm2": "mm2"},
                         details=details, realized=realized)


def erode_interface(mesh: trimesh.Trimesh, recipe: DamageRecipe, *, fragment: Any = None) -> DamageOutcome:
    """P03: smooth non-negative recession over the interface ROI, wall thickness guarded."""
    depth = float(recipe.parameter("depth_mm", 0.0))
    if depth <= 0:
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING, "P03 depth_mm must be > 0",
                          stage="physical.P03")
    return _smooth_recession(mesh, recipe, fragment=fragment, depth_mm=depth, label="P03", roi=None,
                             thickness_guard_mm=recipe.qa.get("min_wall_thickness_mm"))


def erode_outer(mesh: trimesh.Trimesh, recipe: DamageRecipe, *, fragment: Any = None) -> DamageOutcome:
    """P07: erosion of the original outer-wall ROI only, no hidden-surface backfill."""
    depth = float(recipe.parameter("depth_mm", 0.0))
    if depth <= 0:
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING, "P07 depth_mm must be > 0",
                          stage="physical.P07")
    roi = dict(recipe.roi or {})
    if roi.get("kind") in (None, "interface"):
        roi = {"kind": "outer", "direction": roi.get("direction", [0.0, 0.0, 1.0]),
               "cos_min": roi.get("cos_min", 0.25)}
    outcome = _smooth_recession(mesh, recipe, fragment=fragment, depth_mm=depth, label="P07", roi=roi,
                                thickness_guard_mm=recipe.qa.get("min_wall_thickness_mm"))
    outcome.measurements["outer_only_roi"] = 1.0
    return outcome


# ---------------------------------------------------------------------------- P04


def _cutter_ellipsoid(center: np.ndarray, axes: np.ndarray, radii: np.ndarray,
                      *, subdivisions: int = 2) -> trimesh.Trimesh:
    sphere = trimesh.creation.icosphere(subdivisions=int(subdivisions), radius=1.0)
    transform = np.eye(4)
    transform[:3, :3] = np.asarray(axes, dtype=np.float64) @ np.diag(np.asarray(radii, dtype=np.float64))
    transform[:3, 3] = np.asarray(center, dtype=np.float64)
    sphere.apply_transform(transform)
    return S.clean_mesh(sphere)


def chip_material(mesh: trimesh.Trimesh, recipe: DamageRecipe, *, fragment: Any = None) -> DamageOutcome:
    """P04: fixed cutter position/direction, size found by a 1-D geometric search (plan 30.7)."""
    ctx = SdfContext(mesh, recipe, fragment=fragment)
    target = float(recipe.parameter("contact_loss_target", 0.0))
    if target <= 0:
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING, "P04 target must be > 0", stage="physical.P04")
    variant = recipe.variant or "contact_loss"
    basis = dict(recipe.basis or {})
    center = np.asarray(basis["center_mm"], dtype=np.float64)
    direction = np.asarray(basis["direction"], dtype=np.float64)
    direction = direction / max(np.linalg.norm(direction), 1e-12)
    e1 = np.cross(direction, np.array([0.0, 0.0, 1.0]))
    if np.linalg.norm(e1) < 1e-6:
        e1 = np.cross(direction, np.array([0.0, 1.0, 0.0]))
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(direction, e1)
    base_radii = np.asarray(basis.get("radii_mm", [1.0, 1.0, 1.0]), dtype=np.float64)
    source_volume = float(abs(mesh.volume))
    min_ratio = float(recipe.meta.get("min_representative_ratio", 0.05))

    def build(scale: float) -> trimesh.Trimesh:
        radii = np.maximum(base_radii * float(scale), 1e-4)
        return _cutter_ellipsoid(center, np.stack([e1, e2, direction], axis=1), radii)

    def evaluate(scale: float) -> dict[str, Any]:
        cutter = build(scale)
        body = S.boolean_op("difference", [mesh, cutter])
        contact = ctx.contact_state(body)
        parts = S.component_split(body)
        volumes = [float(abs(p.volume)) for p in parts]
        return {"scale": float(scale), "body": body, "contact": contact,
                "components": parts, "volumes": volumes,
                "volume_ratio": (max(volumes) / max(source_volume, 1e-12)) if volumes else 0.0}

    def loss_of(scale: float) -> tuple[float, dict[str, Any]]:
        state = evaluate(scale)
        if variant == "volume_loss" or len(ctx.anchor_points) == 0:
            loss = 1.0 - float(abs(state["body"].volume)) / max(source_volume, 1e-12)
        else:
            loss = float(state["contact"]["lost_fraction"])
        return loss, state

    # 1-D search: the cutter family is nested in ``scale`` so the loss is monotone
    lo, hi = 0.0, 1.0
    state_hi = evaluate(hi)
    guard = 0
    while state_hi["volume_ratio"] > min_ratio and loss_of(hi)[0] < target and guard < 8:
        lo, hi = hi, hi * 2.0
        state_hi = evaluate(hi)
        guard += 1
    loss_hi, state_hi = loss_of(hi)
    trace = [{"scale": hi, "loss": loss_hi, "volume_ratio": state_hi["volume_ratio"]}]
    if loss_hi < target - float(recipe.meta.get("target_tol", 0.01)):
        raise SynLabError(
            ErrorCode.TARGET_INFEASIBLE,
            f"P04 target {target:.3f} unreachable: the largest nested cutter that keeps the "
            f"representative body ({min_ratio:.2f} of the source volume) only removes "
            f"{loss_hi:.3f} of the contact ({variant})",
            stage="physical.P04",
            measurements={"target": target, "achieved_max": loss_hi,
                          "scale_max": hi, "search_grow_steps": guard})
    best_state = state_hi
    best_loss = loss_hi
    for _iteration in range(int(recipe.meta.get("bisection_iterations", 12))):
        mid = 0.5 * (lo + hi)
        loss_mid, state_mid = loss_of(mid)
        trace.append({"scale": mid, "loss": loss_mid, "volume_ratio": state_mid["volume_ratio"]})
        if state_mid["volume_ratio"] < min_ratio:
            hi = mid
            continue
        if loss_mid >= target:
            hi, best_loss, best_state = mid, loss_mid, state_mid
        else:
            lo = mid
        if abs(loss_mid - target) <= float(recipe.meta.get("target_tol", 0.01)) * 0.5:
            break
    body = best_state["body"]
    if best_state["volume_ratio"] < min_ratio:
        raise SynLabError(ErrorCode.TARGET_INFEASIBLE,
                          f"P04 target {target:.3f} would eliminate the representative body "
                          f"(largest component {best_state['volume_ratio']:.3f} of source volume)",
                          stage="physical.P04", measurements={"target": target,
                                                              "volume_ratio": best_state["volume_ratio"]})
    parts = best_state["components"]
    volumes = best_state["volumes"]
    contact = best_state["contact"]
    measurements = {
        "contact_loss_target": target,
        "achieved_contact_loss": float(contact["lost_fraction"]),
        "target_abs_error": float(abs(contact["lost_fraction"] - target)),
        "contact_lost_area_mm2": float(contact["lost_area_mm2"]),
        "contact_residual_area_mm2": float(contact["residual_area_mm2"]),
        "cutter_scale": float(best_state["scale"]),
        "cutter_radius_mm": float(np.max(base_radii * best_state["scale"])),
        "search_iterations": float(len(trace)),
        "lost_volume_mm3": float(source_volume - sum(volumes)),
        "components": float(len(parts)),
        "largest_component_ratio": float(best_state["volume_ratio"]),
        "min_thickness_mm": S.ray_thickness(body, n_samples=160, seed=11)["min_mm"],
    }
    details = {"sdf_pipeline": {"roi": ctx.roi_info, "spacing": ctx.spacing_info}, "search": trace,
               "variant": variant, "cutter": {"center_mm": [float(v) for v in center],
                                              "direction": [float(v) for v in direction],
                                              "base_radii_mm": [float(v) for v in base_radii]}}
    realized = bool(measurements["lost_volume_mm3"] > 1e-9)
    return DamageOutcome(mesh=body, measurements=measurements,
                         units={"achieved_contact_loss": "1", "contact_lost_area_mm2": "mm2",
                                "cutter_radius_mm": "mm", "lost_volume_mm3": "mm3",
                                "min_thickness_mm": "mm"},
                         details=details, realized=realized)


# ---------------------------------------------------------------------------- appearance


def _appearance_payload(recipe: DamageRecipe, fragment: Any) -> dict[str, Any]:
    appearance = None
    if fragment is not None:
        appearance = (getattr(fragment, "meta", None) or {}).get("appearance")
    appearance = appearance or recipe.meta.get("appearance") or recipe.basis.get("appearance")
    if not appearance:
        raise SynLabError(
            ErrorCode.NA_NOT_APPLICABLE,
            f"{recipe.axis_id}: appearance axes need texel channels "
            "(texel_albedo/texel_substrate_albedo/texel_area_mm2/texel_layer)",
            stage="physical.appearance")
    for key in ("texel_albedo", "texel_substrate_albedo", "texel_area_mm2"):
        if key not in appearance:
            raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                              f"{recipe.axis_id}: appearance payload misses {key}",
                              stage="physical.appearance")
    return appearance


def remove_paint(mesh: trimesh.Trimesh, recipe: DamageRecipe, *, fragment: Any = None) -> DamageOutcome:
    """P05: nested paint masks from a frozen continuous rank field; glaze/body shows through."""
    appearance = _appearance_payload(recipe, fragment)
    retained = float(recipe.parameter("retained_fraction", 1.0))
    albedo = np.asarray(appearance["texel_albedo"], dtype=np.float32)
    substrate = np.asarray(appearance["texel_substrate_albedo"], dtype=np.float32)
    area = np.asarray(appearance["texel_area_mm2"], dtype=np.float64)
    layer = np.asarray(appearance.get("texel_layer", np.zeros(len(albedo), dtype=np.int32)))
    field = F.FourierField.from_payload(recipe.basis["rank_field"])
    rank = np.clip(field(np.asarray(appearance["texel_positions"], dtype=np.float64)), 0.0, 1.0)
    paint_texels = layer > 0
    threshold = float(np.quantile(rank[paint_texels], 1.0 - retained)) if paint_texels.any() else 0.0
    removed_mask = paint_texels & (rank <= threshold) if retained < 1.0 else np.zeros(len(rank), dtype=bool)
    if retained >= 1.0:
        removed_mask[:] = False
    new_albedo = np.array(albedo, copy=True)
    new_albedo[removed_mask] = substrate[removed_mask]
    removed_area = float(area[removed_mask].sum())
    total_paint_area = float(area[paint_texels].sum())
    residual = 1.0 - (removed_area / max(total_paint_area, 1e-12))
    measurements = {
        "retained_fraction": retained,
        "paint_texels": float(int(paint_texels.sum())),
        "removed_texels": float(int(removed_mask.sum())),
        "paint_total_area_mm2": total_paint_area,
        "paint_removed_area_mm2": removed_area,
        "paint_residual_fraction": float(residual),
        "revealed_substrate_fraction": float(removed_area / max(total_paint_area, 1e-12)),
        "mean_albedo_delta": float(np.abs(new_albedo - albedo).mean()),
        "geometry_hash_unchanged": 1.0,
        "paint_visible_residual_area_mm2": float(residual * total_paint_area),
    }
    details = {"rank_field_id": field.field_id, "rank_threshold": threshold,
               "mask_nested": True, "geometry": S.mesh_summary(mesh)}
    realized = bool(removed_area > 0)
    return DamageOutcome(mesh=mesh, appearance={"texel_albedo": new_albedo,
                                               "paint_mask_retained": paint_texels & ~removed_mask,
                                               "paint_mask_removed": removed_mask},
                         measurements=measurements,
                         units={"paint_removed_area_mm2": "mm2", "paint_total_area_mm2": "mm2"},
                         details=details, realized=realized)


def dirt_cover(mesh: trimesh.Trimesh, recipe: DamageRecipe, *, fragment: Any = None) -> DamageOutcome:
    """P06: smooth patch coverage; the core variant changes appearance only (plan 12.3)."""
    appearance = _appearance_payload(recipe, fragment)
    coverage = float(recipe.parameter("coverage", 0.0))
    field = F.FourierField.from_payload(recipe.basis["dirt_field"])
    albedo = np.asarray(appearance["texel_albedo"], dtype=np.float32)
    roughness = np.asarray(appearance.get("texel_roughness", np.full(len(albedo), 0.6)),
                           dtype=np.float32)
    area = np.asarray(appearance["texel_area_mm2"], dtype=np.float64)
    dirt_color = np.asarray(recipe.basis.get("dirt_color", [0.22, 0.18, 0.13]), dtype=np.float32)
    dirt_roughness = float(recipe.basis.get("dirt_roughness", 0.95))
    values = np.clip(field(np.asarray(appearance["texel_positions"], dtype=np.float64)), 0.0, 1.0)
    threshold = F.threshold_for_fraction(values, coverage)
    covered = values <= threshold if coverage > 0 else np.zeros(len(values), dtype=bool)
    new_albedo = np.array(albedo, copy=True)
    new_roughness = np.array(roughness, copy=True)
    new_albedo[covered] = 0.5 * new_albedo[covered] + 0.5 * dirt_color[None, :]
    new_roughness[covered] = dirt_roughness
    covered_area = float(area[covered].sum())
    total_area = float(area.sum())
    pattern = np.asarray(appearance.get("pattern_region", np.zeros(len(albedo), dtype=bool)))
    interface = np.asarray(appearance.get("interface_region", np.zeros(len(albedo), dtype=bool)))
    variant = recipe.variant or "dirt_appearance"
    measurements = {
        "coverage": coverage,
        "realized_coverage": float(covered_area / max(total_area, 1e-12)),
        "covered_area_mm2": covered_area,
        "covered_texels": float(int(covered.sum())),
        "pattern_visibility_reduction": float(pattern[covered].sum() / max(pattern.sum(), 1)) if pattern.any() else 0.0,
        "interface_visibility_reduction": float(interface[covered].sum() / max(interface.sum(), 1)) if interface.any() else 0.0,
        "mean_albedo_delta": float(np.abs(new_albedo - albedo).mean()),
        "roughness_delta": float(np.abs(new_roughness - roughness).mean()),
        "geometry_hash_unchanged": 1.0 if variant == "dirt_appearance" else 0.0,
        "contamination_entity": 1.0 if variant == "dirt_geometry" else 0.0,
    }
    details = {"field_id": field.field_id, "threshold": threshold, "variant": variant}
    added_bodies: list[Any] = []
    outcome_mesh = mesh
    if variant == "dirt_geometry":
        thickness = float(recipe.parameter("layer_thickness_mm", 0.3))
        # explicit contamination shell over the covered region, registered as its own entity
        shell = _contamination_shell(mesh, recipe, covered_area=covered_area, thickness_mm=thickness,
                                     total_area=total_area)
        if shell is not None:
            added_bodies.append(shell)
            measurements["contamination_volume_mm3"] = float(abs(shell.volume))
            measurements["contamination_area_mm2"] = float(shell.area)
            measurements["geometry_hash_unchanged"] = 0.0
    return DamageOutcome(mesh=outcome_mesh,
                         appearance={"texel_albedo": new_albedo, "texel_roughness": new_roughness,
                                     "dirt_mask": covered},
                         measurements=measurements,
                         units={"covered_area_mm2": "mm2", "contamination_volume_mm3": "mm3"},
                         details=details, realized=bool(covered.any()), added_bodies=added_bodies)


def _contamination_shell(mesh: trimesh.Trimesh, recipe: DamageRecipe, *, covered_area: float,
                         thickness_mm: float, total_area: float) -> trimesh.Trimesh | None:
    """Outward offset shell over the covered fraction; a separate contamination body."""
    if covered_area <= 0 or total_area <= 0:
        return None
    fraction = float(np.clip(covered_area / total_area, 0.0, 1.0))
    spacing = float(recipe.grid.get("spacing_mm") or 0.0) or max(thickness_mm / 3.0, 0.2)
    grid = S.grid_for_mesh(mesh, spacing, pad_mm=float(thickness_mm) + 2.0 * spacing)
    d0, _info = S.signed_distance_field(mesh, grid, surface_check_samples=200,
                                        seed=int(recipe.basis.get("seed", 0)) % 512)
    field = F.FourierField.from_payload(recipe.basis["dirt_field"])
    anchors, _fid = trimesh.sample.sample_surface(mesh, 1200, seed=5)
    values = np.clip(field(np.asarray(anchors, dtype=np.float64)), 0.0, 1.0)
    threshold = F.threshold_for_fraction(values, fraction)

    def b_fn(points: np.ndarray) -> np.ndarray:
        vals = np.clip(field(points), 0.0, 1.0)
        mask = (vals <= threshold).astype(np.float64)
        return float(thickness_mm) * mask

    out, _chunk = S.evaluate_field(grid, b_fn, base=d0, chunk=24, halo=1)
    shell_mesh = S.marching_cubes_mesh(out, grid)
    shell_mesh, _clip = S.intersect_with_source(shell_mesh, mesh)
    try:
        grown = S.boolean_op("difference", [shell_mesh, mesh])
    except SynLabError:
        return None
    return grown


# ---------------------------------------------------------------------------- P08


def crack_or_coat_loss(mesh: trimesh.Trimesh, recipe: DamageRecipe, *, fragment: Any = None) -> DamageOutcome:
    """P08: three separately registered variants (plan 12.3, 30.9)."""
    variant = recipe.variant or "geometry_crack"
    affected = float(recipe.parameter("affected_area", 0.0))
    if variant == "paint_coat_loss":
        coat_layer = int(recipe.basis.get("coat_layer_id", 1))
        appearance = _appearance_payload(recipe, fragment)
        layer = np.asarray(appearance.get("texel_layer", np.zeros(len(appearance["texel_albedo"]),
                                                               dtype=np.int32)))
        coat = layer == coat_layer
        area = np.asarray(appearance["texel_area_mm2"], dtype=np.float64)
        field = F.FourierField.from_payload(recipe.basis["rank_field"])
        rank = np.clip(field(np.asarray(appearance["texel_positions"], dtype=np.float64)), 0.0, 1.0)
        threshold = float(np.quantile(rank[coat], 1.0 - affected)) if coat.any() else 0.0
        removed = coat & (rank <= threshold)
        substrate = np.asarray(appearance["texel_substrate_albedo"], dtype=np.float32)
        albedo = np.array(appearance["texel_albedo"], copy=True)
        albedo[removed] = substrate[removed]
        coat_area = float(area[coat].sum())
        removed_area = float(area[removed].sum())
        measurements = {
            "affected_area": affected,
            "coat_total_area_mm2": coat_area,
            "coat_removed_area_mm2": removed_area,
            "coat_residual_fraction": float(1.0 - removed_area / max(coat_area, 1e-12)),
            "realized_affected_fraction": float(removed_area / max(coat_area, 1e-12)),
            "geometry_hash_unchanged": 1.0,
        }
        return DamageOutcome(mesh=mesh, appearance={"texel_albedo": albedo, "coat_mask_removed": removed},
                             measurements=measurements, units={"coat_removed_area_mm2": "mm2"},
                             details={"variant": variant, "threshold": threshold},
                             realized=bool(removed_area > 0))
    if variant == "geometric_coat_loss":
        ctx = SdfContext(mesh, recipe, fragment=fragment)
        thickness = float(recipe.parameter("layer_thickness_mm", recipe.meta.get("layer_thickness_mm", 0.3)))
        field = F.FourierField.from_payload(recipe.basis["rank_field"])
        anchors = np.asarray(np.asarray(mesh.triangles_center, dtype=np.float64)[ctx.roi_ids])
        values = np.clip(field(anchors), 0.0, 1.0)
        threshold = F.threshold_for_fraction(values, affected)
        normals = np.asarray(mesh.face_normals, dtype=np.float64)[ctx.roi_ids]
        anchor_tree = cKDTree(anchors)

        def b_fn(points: np.ndarray) -> np.ndarray:
            vals = np.clip(field(points), 0.0, 1.0)
            _d, idx = anchor_tree.query(points, workers=1)
            face_normal_ok = True
            mask = (vals <= threshold).astype(np.float64)
            return float(thickness) * mask * (1.0 if face_normal_ok else 1.0)

        body, detail = ctx.extract(b_fn, t=1.0, core_mm=0.0,
                                   halo_mm=thickness + 2.0 * ctx.spacing, label="P08_coat")
        removed = _removed_surface_points(body, ctx, n=2000, seed=int(recipe.basis.get("seed", 0)) + 8)
        removed_uv = np.asarray(mesh.triangles_center, dtype=np.float64)[ctx.roi_ids]
        coat_area = float(ctx.interface_area_mm2)
        measurements = {
            "affected_area": affected,
            "layer_thickness_mm": thickness,
            "coat_total_area_mm2": coat_area,
            "coat_removed_area_mm2": float(len(removed)),
            "lost_volume_mm3": float(abs(ctx.mesh.volume) - abs(body.volume)),
            "realized_lost_volume_over_area_mm": float(
                (abs(ctx.mesh.volume) - abs(body.volume)) / max(coat_area, 1e-12)),
            "geometry_hash_unchanged": 0.0,
            "min_thickness_mm": S.ray_thickness(body, n_samples=160, seed=12)["min_mm"],
        }
        details = {"sdf_pipeline": detail, "variant": variant, "threshold": threshold,
                   "anchor_faces": int(len(removed_uv))}
        return DamageOutcome(mesh=body, measurements=measurements,
                             units={"lost_volume_mm3": "mm3", "layer_thickness_mm": "mm"},
                             details=details,
                             realized=bool(measurements["lost_volume_mm3"] > 1e-9))
    if variant != "geometry_crack":
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown P08 variant {variant!r}",
                          stage="physical.P08")
    return _geometry_crack(mesh, recipe, fragment=fragment)


def _geometry_crack(mesh: trimesh.Trimesh, recipe: DamageRecipe, *, fragment: Any = None) -> DamageOutcome:
    """Finite-width cutter that really removes material; may split the body (plan 30.8)."""
    ctx = SdfContext(mesh, recipe, fragment=fragment)
    target = float(recipe.parameter("affected_area", 0.0))
    if target <= 0:
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING, "P08 geometry_crack needs affected_area > 0",
                          stage="physical.P08")
    basis = dict(recipe.basis or {})
    direction = np.asarray(basis.get("crack_direction", ctx.mesh.face_normals[ctx.roi_ids].mean(axis=0)),
                           dtype=np.float64)
    direction /= max(np.linalg.norm(direction), 1e-12)
    length_dir = np.asarray(basis.get("crack_length_dir", [1.0, 0.0, 0.0]), dtype=np.float64)
    length_dir -= direction * float(length_dir @ direction)
    if np.linalg.norm(length_dir) < 1e-6:
        length_dir = np.cross(direction, np.array([0.0, 0.0, 1.0]))
    length_dir /= np.linalg.norm(length_dir)
    depth_dir = np.cross(direction, length_dir)
    center = np.asarray(basis.get("crack_center_mm", ctx.anchor_points.mean(axis=0)), dtype=np.float64)
    extent = np.asarray(ctx.mesh.bounds[1]) - np.asarray(ctx.mesh.bounds[0])
    length = float(basis.get("crack_length_mm", np.linalg.norm(extent) * 1.2))
    depth = float(basis.get("crack_depth_mm", float(np.max(extent)) * 1.5))
    source_volume = float(abs(mesh.volume))
    min_ratio = float(recipe.meta.get("min_representative_ratio", 0.05))

    def build(width: float) -> trimesh.Trimesh:
        box = trimesh.creation.box(extents=(max(width, 1e-4), length, depth))
        transform = np.eye(4)
        transform[:3, :3] = np.stack([depth_dir, length_dir, direction], axis=1)
        transform[:3, 3] = center
        box.apply_transform(transform)
        return S.clean_mesh(box)

    def evaluate(width: float) -> dict[str, Any]:
        body = S.boolean_op("difference", [mesh, build(width)])
        contact = ctx.contact_state(body)
        parts = S.component_split(body)
        volumes = [float(abs(p.volume)) for p in parts]
        return {"width": float(width), "body": body, "contact": contact, "components": parts,
                "volumes": volumes,
                "volume_ratio": (max(volumes) / max(source_volume, 1e-12)) if volumes else 0.0}

    def loss_of(width: float) -> tuple[float, dict[str, Any]]:
        state = evaluate(width)
        area_fraction = float(len(ctx.anchor_points) and state["contact"]["lost_fraction"])
        return area_fraction, state

    lo, hi = 1e-3, max(float(ctx.spacing), 0.05)
    state_hi = evaluate(hi)
    guard = 0
    while loss_of(hi)[0] < target and state_hi["volume_ratio"] > min_ratio and guard < 12:
        lo, hi = hi, hi * 1.8
        state_hi = evaluate(hi)
        guard += 1
    loss_hi, state_hi = loss_of(hi)
    trace = [{"width": hi, "loss": loss_hi, "volume_ratio": state_hi["volume_ratio"]}]
    if loss_hi < target - 0.01:
        raise SynLabError(
            ErrorCode.TARGET_INFEASIBLE,
            f"P08 geometry_crack: target affected area {target:.3f} unreachable with the frozen "
            f"crack line (max {loss_hi:.3f} before the representative body is lost)",
            stage="physical.P08", measurements={"target": target, "achieved_max": loss_hi,
                                                 "width_max_mm": hi})
    best = state_hi
    best_loss = loss_hi
    for _iteration in range(12):
        mid = 0.5 * (lo + hi)
        loss_mid, state_mid = loss_of(mid)
        trace.append({"width": mid, "loss": loss_mid, "volume_ratio": state_mid["volume_ratio"]})
        if state_mid["volume_ratio"] < min_ratio:
            hi = mid
            continue
        if loss_mid >= target:
            hi, best, best_loss = mid, state_mid, loss_mid
        else:
            lo = mid
        if abs(loss_mid - target) <= 0.005:
            break
    body = best["body"]
    parts = best["components"]
    volumes = best["volumes"]
    measurements = {
        "affected_area": target,
        "achieved_affected_area_fraction": float(best["contact"]["lost_fraction"]),
        "crack_width_mm": float(best["width"]),
        "crack_length_mm": length,
        "crack_depth_mm": depth,
        "contact_lost_area_mm2": float(best["contact"]["lost_area_mm2"]),
        "lost_volume_mm3": float(source_volume - sum(volumes)),
        "components_after": float(len(parts)),
        "largest_component_ratio": float(best["volume_ratio"]),
        "search_iterations": float(len(trace)),
        "geometry_hash_unchanged": 0.0,
        "min_thickness_mm": S.ray_thickness(body, n_samples=160, seed=13)["min_mm"],
    }
    details = {"sdf_pipeline": {"roi": ctx.roi_info, "spacing": ctx.spacing_info}, "search": trace,
               "crack": {"center_mm": [float(v) for v in center],
                         "direction": [float(v) for v in direction],
                         "length_dir": [float(v) for v in length_dir]},
               "components": [S.mesh_summary(p) for p in parts]}
    realized = bool(measurements["lost_volume_mm3"] > 1e-9)
    return DamageOutcome(mesh=body, measurements=measurements,
                         units={"crack_width_mm": "mm", "contact_lost_area_mm2": "mm2",
                                "lost_volume_mm3": "mm3", "min_thickness_mm": "mm"},
                         details=details, realized=realized)


# ---------------------------------------------------------------------------- dispatch

GEOMETRY_DISPATCH: dict[str, Callable[..., DamageOutcome]] = {
    "P01": polish_interface,
    "P02": round_edge,
    "P03": erode_interface,
    "P04": chip_material,
    "P05": remove_paint,
    "P06": dirt_cover,
    "P07": erode_outer,
    "P08": crack_or_coat_loss,
}


def run_damage(mesh: trimesh.Trimesh, recipe: DamageRecipe, *, fragment: Any = None) -> DamageOutcome:
    """Run one level of one P axis and return the damaged body plus measured quantities."""
    handler = GEOMETRY_DISPATCH.get(recipe.axis_id)
    if handler is None:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{recipe.axis_id} is not a physical damage axis", stage="physical.run")
    return handler(mesh, recipe, fragment=fragment)
