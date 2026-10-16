"""Geometry primitives for the G axes (plan 15.4, 30.2 rows 7b–8).

The observation-side geometry bundle is the frozen vocabulary of
``synlab.degrade.sources``::

    points (N,3) mm, normals (N,3), point_valid (N,), point_view (N,) int32,
    frames: [{view_id, T_WC (4,4), K (3,3), depth_z (H,W) float32, mask (H,W) bool}],
    mesh (trimesh, fused *observed* surface), roi (N,) bool,
    priority_order (N,) int32 (frozen nested deletion order),
    reference_points (N,3) research reference (audit only), scale_ratio (float),
    K (3,3), dist (k,), clean_geometry_hash (str)

Two rules drive every function below:

* the *observed* entity is the only thing a G axis may touch — the clean/physical hashes
  travel in ``clean_geometry_hash`` and are never rewritten (level 0 returns the source
  bundle object itself, enforced by :class:`synlab.degrade.registry.AxisOperator`);
* nothing is reported that was not measured: distances, Hausdorff errors, connected
  components, residuals and pixel shifts are computed on the real arrays, and a missing
  prerequisite (no per-frame depth, no mesh, no boundary hole) is a structured
  ``NA_NOT_APPLICABLE``/``MISSING_DEPTH`` failure rather than a silent no-op.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..errors import ErrorCode, SynLabError

#: Fixed outlier probability of the G01 depth model (frozen decision, not a free knob).
DEPTH_OUTLIER_PROBABILITY = 0.02


# ---------------------------------------------------------------------------- accessors
def points_of(bundle: Any) -> np.ndarray:
    points = bundle.get("points") if hasattr(bundle, "get") else None
    if points is None:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                          "geometry payload has no 'points'",
                          stage="degrade.geometry.points_of")
    return np.asarray(points, dtype=np.float64)


def normals_of(bundle: Any, n: int) -> np.ndarray:
    normals = bundle.get("normals") if hasattr(bundle, "get") else None
    if normals is None:
        return np.tile(np.array([[0.0, 0.0, 1.0]]), (n, 1))
    normals = np.asarray(normals, dtype=np.float64)
    if len(normals) != n:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"normals length {len(normals)} != points length {n}",
                          stage="degrade.geometry.normals_of")
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    return normals / np.maximum(norms, 1e-12)


def valid_of(bundle: Any, n: int) -> np.ndarray:
    valid = bundle.get("point_valid") if hasattr(bundle, "get") else None
    if valid is None:
        return np.ones(n, dtype=bool)
    valid = np.asarray(valid, dtype=bool).ravel()
    if len(valid) != n:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"point_valid length {len(valid)} != points length {n}",
                          stage="degrade.geometry.valid_of")
    return valid


def order_of(bundle: Any, n: int) -> np.ndarray:
    """Frozen nested deletion order (falls back to the stored point order)."""
    order = bundle.get("priority_order") if hasattr(bundle, "get") else None
    if order is None:
        return np.arange(n, dtype=np.int64)
    order = np.asarray(order, dtype=np.int64).ravel()
    if len(order) != n:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"priority_order length {len(order)} != points length {n}",
                          stage="degrade.geometry.order_of")
    return order


def roi_of(bundle: Any, n: int) -> np.ndarray:
    roi = bundle.get("roi") if hasattr(bundle, "get") else None
    if roi is None:
        return np.ones(n, dtype=bool)
    roi = np.asarray(roi, dtype=bool).ravel()
    if len(roi) != n:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"roi length {len(roi)} != points length {n}",
                          stage="degrade.geometry.roi_of")
    return roi


def frames_of(bundle: Any) -> list[dict[str, Any]]:
    frames = bundle.get("frames") if hasattr(bundle, "get") else None
    return list(frames or [])


def mesh_of(bundle: Any) -> Any:
    """Fused observed mesh, rebuilt from raw arrays when the payload was stored flat."""
    mesh = bundle.get("mesh") if hasattr(bundle, "get") else None
    if mesh is not None and hasattr(mesh, "vertices") and hasattr(mesh, "faces"):
        return mesh
    vertices = bundle.get("vertices") if hasattr(bundle, "get") else None
    faces = bundle.get("faces") if hasattr(bundle, "get") else None
    if vertices is None or faces is None:
        return None
    import trimesh

    from ..storage.mesh_io import with_face_attrs

    built = trimesh.Trimesh(vertices=np.asarray(vertices, dtype=np.float64),
                            faces=np.asarray(faces, dtype=np.int64), process=False)
    attrs = {str(k)[len("face__"):]: np.asarray(v) for k, v in (bundle.payload or {}).items()
             if str(k).startswith("face__")}
    if attrs:
        with_face_attrs(built, **attrs)
    return built


def depth_frames(bundle: Any) -> list[dict[str, Any]]:
    frames = [f for f in frames_of(bundle) if f.get("depth_z") is not None]
    return frames


def frozen_geometry_hash(bundle: Any) -> str:
    return str((bundle.get("clean_geometry_hash") if hasattr(bundle, "get") else "") or "")


# ---------------------------------------------------------------------------- G01
def depth_weight_field(points: np.ndarray, normals: np.ndarray, view_centers: np.ndarray,
                       *, scale_mm: float, rng: np.random.Generator
                       ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Low-frequency correlated field x distance x incidence weight (all frozen once).

    Returns ``(coarse, incidence_factor, info)`` where ``coarse`` is the correlated field in
    ``[-1, 1]`` and ``incidence_factor`` is ``1/cos(theta)`` clipped to the declared band.
    """
    from ..physical.fields import FourierField

    field = FourierField.sample_frozen(rng, scale_mm=float(scale_mm), n_components=8,
                                       field_id="G01_depth_lowfreq")
    coarse = np.clip(field(points), 0.0, 1.0) * 2.0 - 1.0
    if view_centers.size:
        nearest = _nearest_center(points, view_centers)
        direction = nearest - points
        distance = np.linalg.norm(direction, axis=1)
        cos_theta = np.abs(np.sum(_unit(direction) * normals, axis=1))
        incidence = 1.0 / np.clip(cos_theta, 0.35, 1.0)
        distance_factor = distance / max(float(np.median(distance)), 1e-9)
    else:
        distance_factor = np.ones(len(points), dtype=np.float64)
        incidence = np.ones(len(points), dtype=np.float64)
    info = {"lowfreq_scale_mm": float(scale_mm), "field_id": field.field_id,
            "distance_factor_range": [float(distance_factor.min()), float(distance_factor.max())],
            "incidence_factor_range": [float(incidence.min()), float(incidence.max())]}
    return coarse, distance_factor * incidence, info


def _nearest_center(points: np.ndarray, centers: np.ndarray) -> np.ndarray:
    from scipy.spatial import cKDTree

    tree = cKDTree(np.asarray(centers, dtype=np.float64))
    _dist, idx = tree.query(np.asarray(points, dtype=np.float64), k=1, workers=1)
    return np.asarray(centers, dtype=np.float64)[idx]


def _unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-12)


def depth_error(points: np.ndarray, normals: np.ndarray, coarse: np.ndarray,
                weight: np.ndarray, *, target_rms_mm: float, outlier_probability: float,
                rng: np.random.Generator) -> tuple[np.ndarray, dict[str, Any]]:
    """Correlated + incidence-scaled + outlier depth error with a *measured* realized RMS."""
    target = float(target_rms_mm)
    if target <= 0:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                          "G01 target_rms_mm must be > 0 for a non-zero level",
                          stage="degrade.geometry.depth_error")
    base = coarse * weight
    base_rms = float(np.sqrt(np.mean(base ** 2)))
    if base_rms <= 1e-12:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                          "G01 frozen field is degenerate (zero RMS)",
                          stage="degrade.geometry.depth_error")
    delta = base * (target / base_rms)
    outlier_mask = np.zeros(len(points), dtype=bool)
    if outlier_probability > 0 and len(points):
        draw = rng.random(len(points)) < float(outlier_probability)
        if draw.any():
            magnitude = target * rng.uniform(2.0, 5.0, size=int(draw.sum()))
            sign = np.where(rng.random(int(draw.sum())) < 0.5, -1.0, 1.0)
            delta = delta.copy()
            delta[draw] += magnitude * sign
            outlier_mask = draw
    perturbed = points + delta[:, None] * normals
    info = {
        "inlier_rms_mm": float(np.sqrt(np.mean(delta[~outlier_mask] ** 2))) if (~outlier_mask).any() else 0.0,
        "realized_rms_mm": float(np.sqrt(np.mean(delta ** 2))),
        "max_abs_error_mm": float(np.max(np.abs(delta))) if delta.size else 0.0,
        "outlier_fraction": float(np.mean(outlier_mask)) if len(points) else 0.0,
        "outlier_probability_declared": float(outlier_probability),
        "outlier_mean_mm": float(np.mean(np.abs(delta[outlier_mask]))) if outlier_mask.any() else 0.0,
    }
    return perturbed.astype(np.float64), info


def rms_against_reference(points: np.ndarray, reference: np.ndarray) -> dict[str, float]:
    """Independent audit of the realized error against a research reference point set."""
    ref = np.asarray(reference, dtype=np.float64)
    pts = np.asarray(points, dtype=np.float64)
    if ref.shape != pts.shape or ref.size == 0:
        return {"available": 0.0}
    delta = pts - ref
    norms = np.linalg.norm(delta, axis=1)
    return {
        "available": 1.0,
        "rms_mm": float(np.sqrt(np.mean(norms ** 2))),
        "mean_mm": float(norms.mean()),
        "p95_mm": float(np.percentile(norms, 95)),
        "max_mm": float(norms.max()),
    }


# ---------------------------------------------------------------------------- G02
def nested_prefix_count(n_valid: int, fraction: float, *, budget: int | None = None) -> int:
    """Count kept by a *nested prefix* of the frozen order (never an independent draw)."""
    if n_valid <= 0:
        return 0
    f = float(np.clip(fraction, 0.0, 1.0))
    count = int(np.floor(f * n_valid + 1e-9))
    if f >= 1.0:
        count = n_valid
    if budget is not None:
        count = min(count, int(budget))
    return int(max(count, 0))


def sparsify(points: np.ndarray, valid: np.ndarray, order: np.ndarray, count: int
             ) -> tuple[np.ndarray, dict[str, Any]]:
    """Keep the first ``count`` valid points of the frozen order; report the real counts."""
    idx_valid = np.flatnonzero(valid)
    ranked = idx_valid[np.argsort(order[idx_valid], kind="stable")]
    keep = np.sort(ranked[:int(count)])
    mask = np.zeros(len(points), dtype=bool)
    mask[keep] = True
    info = {"valid_before": int(valid.sum()), "kept": int(mask.sum()),
            "dropped": int(valid.sum() - mask.sum()),
            "nested_prefix": True}
    return mask, info


def median_spacing(points: np.ndarray, *, sample: int = 2000) -> float:
    """Median nearest-neighbour spacing of the observed cloud (the lattice cell reference)."""
    from scipy.spatial import cKDTree

    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 2:
        return 1.0
    if len(pts) > sample:
        idx = np.linspace(0, len(pts) - 1, int(sample)).astype(np.int64)
        pts = pts[idx]
    tree = cKDTree(pts)
    dist, _idx = tree.query(pts, k=2, workers=1)
    spacing = float(np.median(dist[:, 1]))
    return max(spacing, 1e-3)


def point_density(points: np.ndarray, roi: np.ndarray | None = None) -> float:
    """Points per mm^2 of the (ROI) extent — the measured density proxy of G02/G03."""
    pts = np.asarray(points, dtype=np.float64)
    if roi is not None and np.any(roi):
        pts = pts[np.asarray(roi, dtype=bool)]
    if len(pts) < 3:
        return 0.0
    extent = pts.max(axis=0) - pts.min(axis=0)
    area = float(extent[0] * extent[1]) if extent[0] > 0 and extent[1] > 0 else float(
        np.prod(np.sort(extent)[-2:]))
    return float(len(pts) / max(area, 1e-9))


# ---------------------------------------------------------------------------- G03
def surface_lattice(points: np.ndarray, *, cell_mm: float
                    ) -> tuple[np.ndarray, tuple[int, int], np.ndarray, dict[str, Any]]:
    """Occupancy lattice of the observed cloud in its own frozen PCA frame.

    Returns ``(ij, shape, occupancy, info)``: ``ij`` are the lattice indices of every point,
    ``occupancy`` is the (H, W) boolean surface support.  The frame is the cloud's own PCA
    frame, i.e. a real surface-parameter grid, not an external reference.
    """
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 8:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                          "G03 needs at least 8 observed points to define regions",
                          stage="degrade.geometry.surface_lattice")
    cell = float(cell_mm)
    if cell <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"cell_mm must be > 0, got {cell}",
                          stage="degrade.geometry.surface_lattice")
    centred = pts - pts.mean(axis=0)
    _u, _s, vt = np.linalg.svd(centred, full_matrices=False)
    uv = centred @ vt[:2].T
    ij = np.floor((uv - uv.min(axis=0)) / cell).astype(np.int64)
    shape = (int(ij[:, 0].max()) + 1, int(ij[:, 1].max()) + 1)
    occupancy = np.zeros(shape, dtype=bool)
    occupancy[ij[:, 0], ij[:, 1]] = True
    return ij, shape, occupancy, {"cell_mm": cell, "lattice_shape": [int(shape[0]), int(shape[1])],
                                  "cell_area_mm2": cell * cell,
                                  "occupancy_cells": int(occupancy.sum()),
                                  "pca_basis": np.asarray(vt[:2], dtype=np.float64).tolist()}


def label_regions(occupancy: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Connected components of the observed surface support (``scipy.ndimage.label``)."""
    from scipy import ndimage

    labels, n_regions = ndimage.label(occupancy, structure=np.ones((3, 3), dtype=bool))
    sizes = np.bincount(labels.ravel(), minlength=n_regions + 1)[1:]
    return labels, {"n_regions": int(n_regions),
                    "region_cells": sorted((int(s) for s in sizes), reverse=True)}


def freeze_hole_seeds(occupancy: np.ndarray, *, n_seeds: int,
                      rng: np.random.Generator) -> list[tuple[int, int]]:
    """Farthest-point sampling of the occupied cells: the frozen hole positions of G03."""
    from scipy.spatial import cKDTree

    cells = np.argwhere(occupancy)
    if len(cells) == 0:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE, "G03 lattice is empty",
                          stage="degrade.geometry.freeze_hole_seeds")
    count = int(min(max(n_seeds, 1), len(cells)))
    chosen = [int(rng.integers(0, len(cells)))]
    distances = cKDTree(cells).query(cells, k=1)[0] if len(cells) == 1 else None
    tree = cKDTree(cells)
    dist = np.linalg.norm(cells - cells[chosen[0]][None, :], axis=1)
    while len(chosen) < count:
        nxt = int(np.argmax(dist))
        chosen.append(nxt)
        dist = np.minimum(dist, np.linalg.norm(cells - cells[nxt][None, :], axis=1))
    del distances, tree
    return [(int(cells[i][0]), int(cells[i][1])) for i in chosen]


def hole_disk_mask(shape: tuple[int, int], seeds: list[tuple[int, int]], radius_cells: float
                   ) -> np.ndarray:
    """Union of connected lattice disks of the given radius around the frozen seeds."""
    rows, cols = np.mgrid[0:shape[0], 0:shape[1]]
    mask = np.zeros(shape, dtype=bool)
    r = float(max(radius_cells, 0.0))
    for seed in seeds:
        mask |= ((rows - seed[0]) ** 2 + (cols - seed[1]) ** 2) <= r * r
    return mask


def measure_holes(removed: np.ndarray, *, cell_area_mm2: float) -> dict[str, Any]:
    """Connected-component measurement of the removed cells (holes, not dropped points)."""
    from scipy import ndimage

    labels, n = ndimage.label(removed, structure=np.ones((3, 3), dtype=bool))
    sizes = np.bincount(labels.ravel(), minlength=n + 1)[1:]
    centroids = ndimage.center_of_mass(removed, labels, index=range(1, n + 1)) if n else []
    return {
        "n_holes": int(n),
        "removed_cells": int(np.count_nonzero(removed)),
        "removed_area_mm2": float(np.count_nonzero(removed) * cell_area_mm2),
        "hole_areas_mm2": [float(s * cell_area_mm2) for s in sorted(sizes, reverse=True)],
        "largest_hole_area_mm2": float(max(sizes) * cell_area_mm2) if n else 0.0,
        "hole_centroids": [[float(c[0]), float(c[1])] for c in centroids],
    }


def remove_holes_to_target(occupancy: np.ndarray, seeds: list[tuple[int, int]], *,
                           retained_coverage: float, cell_area_mm2: float,
                           max_radius_cells: float | None = None,
                           iterations: int = 10) -> tuple[np.ndarray, dict[str, Any]]:
    """Grow the frozen holes until the retained surface fraction reaches the target.

    Nesting is structural: the seed set is frozen and only the radius grows, so the level-``k``
    removed set is contained in the level-``k+1`` one (plan 15.4 G03).
    """
    total = int(np.count_nonzero(occupancy))
    if total == 0:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE, "G03 lattice is empty",
                          stage="degrade.geometry.remove_holes_to_target")
    shape = occupancy.shape
    limit = float(max_radius_cells if max_radius_cells is not None
                  else max(shape[0], shape[1]) * 1.5)
    target_removed = (1.0 - float(np.clip(retained_coverage, 0.0, 1.0))) * total

    def removed_cells(radius: float) -> np.ndarray:
        return hole_disk_mask(shape, seeds, radius) & occupancy

    lo, hi = 0.0, 1.0
    guard = 0
    while int(np.count_nonzero(removed_cells(hi))) < target_removed and hi < limit and guard < 12:
        hi = min(hi * 2.0, limit)
        guard += 1
    best_radius = hi
    best_error = abs(int(np.count_nonzero(removed_cells(hi))) - target_removed)
    for _ in range(int(iterations)):
        mid = 0.5 * (lo + hi)
        count = int(np.count_nonzero(removed_cells(mid)))
        error = abs(count - target_removed)
        if error < best_error:
            best_error, best_radius = error, mid
        if count < target_removed:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 0.25:
            break
    removed = removed_cells(best_radius)
    info = {"radius_cells": float(best_radius),
            "target_removed_cells": float(target_removed),
            "radius_saturated": bool(best_radius >= limit - 1e-9),
            **measure_holes(removed, cell_area_mm2=cell_area_mm2)}
    info["coverage_retained"] = float(1.0 - info["removed_cells"] / total)
    info["target_retained_coverage"] = float(retained_coverage)
    return removed, info


# ---------------------------------------------------------------------------- G04 / G07
def frame_centers(frames: list[dict[str, Any]]) -> np.ndarray:
    centers = []
    for frame in frames:
        T = frame.get("T_WC")
        if T is None:
            continue
        centers.append(np.asarray(T, dtype=np.float64)[:3, 3])
    return np.asarray(centers, dtype=np.float64) if centers else np.zeros((0, 3))


def drift_pose(T_WC: np.ndarray, *, translation_mm: float, rotation_deg: float,
               axis: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """One frozen SE(3) perturbation applied to a single frame pose."""
    T = np.asarray(T_WC, dtype=np.float64).copy()
    if translation_mm:
        direction = _unit(rng.normal(size=(1, 3)))[0]
        T[:3, 3] = T[:3, 3] + direction * float(translation_mm)
    if rotation_deg:
        angle = np.radians(float(rotation_deg))
        k = np.asarray(axis, dtype=np.float64)
        k = k / max(np.linalg.norm(k), 1e-12)
        K_mat = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
        R = np.eye(3) + np.sin(angle) * K_mat + (1.0 - np.cos(angle)) * (K_mat @ K_mat)
        T[:3, :3] = R @ T[:3, :3]
    return T


def refusion(frames: list[dict[str, Any]], *, K_override: dict[int, np.ndarray] | None = None,
             dist_override: np.ndarray | None = None, stride: int = 4,
             max_points: int = 40000) -> tuple[np.ndarray, dict[str, Any]]:
    """Re-fuse the per-view depth maps into one point cloud (the real fusion step).

    Each frame is back-projected through its *own* (possibly drifted or mis-calibrated)
    pose/intrinsics — exactly what a naive fusion would do after the frames changed.  This
    is what makes G04/G07 post-fusion error, not a label edit.
    """
    from ..cameras.api import unproject

    clouds: list[np.ndarray] = []
    per_view: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        depth = frame.get("depth_z")
        if depth is None:
            continue
        depth = np.asarray(depth, dtype=np.float64)
        K = np.asarray((K_override or {}).get(index, frame.get("K")), dtype=np.float64)
        dist = np.asarray(dist_override if dist_override is not None else frame.get("dist", []),
                          dtype=np.float64) if (
            dist_override is not None or frame.get("dist") is not None) else None
        T = np.asarray(frame.get("T_WC"), dtype=np.float64)
        mask = frame.get("mask")
        step = max(int(stride), 1)
        rows, cols = np.mgrid[0:depth.shape[0]:step, 0:depth.shape[1]:step]
        z = depth[rows, cols]
        ok = np.isfinite(z) & (z > 0)
        if mask is not None:
            mask_arr = np.asarray(mask, dtype=bool)
            ok &= mask_arr[rows, cols]
        if not np.any(ok):
            per_view.append({"view_id": frame.get("view_id"), "points": 0})
            continue
        uv = np.stack([cols[ok].astype(np.float64), rows[ok].astype(np.float64)], axis=1)
        world = unproject(uv, z[ok], K, T, dist)
        clouds.append(np.asarray(world, dtype=np.float64))
        per_view.append({"view_id": frame.get("view_id"), "points": int(ok.sum()),
                         "K": K.tolist()})
        if sum(len(c) for c in clouds) >= max_points:
            break
    if not clouds:
        raise SynLabError(
            ErrorCode.NA_NOT_APPLICABLE,
            "no frame carries a usable depth map; G04/G07 need the depth-proxy route's "
            "per-view depth and pose (a fused-only source has no re-fusion step)",
            stage="degrade.geometry.refusion",
        )
    fused = np.vstack(clouds)
    info = {"views_used": len(clouds), "points": int(len(fused)), "per_view": per_view,
            "stride": int(stride)}
    return fused, info


def cloud_residual(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    """Nearest-neighbour residual of one cloud against another (ghosting / deviation)."""
    from scipy.spatial import cKDTree

    ref = np.asarray(reference, dtype=np.float64)
    cand = np.asarray(candidate, dtype=np.float64)
    if ref.size == 0 or cand.size == 0:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                          "empty point cloud in residual measurement",
                          stage="degrade.geometry.cloud_residual")
    tree = cKDTree(cand)
    dist, _idx = tree.query(ref, k=1, workers=1)
    return {"mean_mm": float(dist.mean()), "rms_mm": float(np.sqrt(np.mean(dist ** 2))),
            "p95_mm": float(np.percentile(dist, 95)), "max_mm": float(dist.max()),
            "n_reference": int(len(ref)), "n_candidate": int(len(cand))}


def intrinsics_perturbation(K: np.ndarray, dist: np.ndarray | None, *, variant: str,
                            focal_ratio: float = 0.0, principal_px: float = 0.0,
                            distortion_scale: float = 0.0
                            ) -> tuple[np.ndarray, np.ndarray | None, dict[str, Any]]:
    """Mis-calibration applied *before* back-projection (plan 30.2 row 7b)."""
    K_new = np.asarray(K, dtype=np.float64).copy()
    info: dict[str, Any] = {"variant": variant, "focal_ratio": float(focal_ratio),
                            "principal_px": float(principal_px),
                            "distortion_scale": float(distortion_scale)}
    if focal_ratio:
        K_new[0, 0] *= (1.0 + float(focal_ratio))
        K_new[1, 1] *= (1.0 + float(focal_ratio))
    if principal_px:
        K_new[0, 2] += float(principal_px)
        K_new[1, 2] -= float(principal_px) * 0.5
    dist_new = None if dist is None else np.asarray(dist, dtype=np.float64).copy()
    if distortion_scale and dist_new is not None and dist_new.size:
        dist_new = dist_new * (1.0 + float(distortion_scale))
    info.update({"focal_before": [float(K[0, 0]), float(K[1, 1])],
                 "focal_after": [float(K_new[0, 0]), float(K_new[1, 1])],
                 "principal_before": [float(K[0, 2]), float(K[1, 2])],
                 "principal_after": [float(K_new[0, 2]), float(K_new[1, 2])]})
    return K_new, dist_new, info


def reprojection_error(points: np.ndarray, frames: list[dict[str, Any]], point_view: np.ndarray,
                       K_by_view: dict[int, np.ndarray], dist: np.ndarray | None
                       ) -> dict[str, float]:
    """Measured reprojection residual of the observed points under the perturbed model."""
    from ..cameras.api import project

    errors: list[np.ndarray] = []
    pts = np.asarray(points, dtype=np.float64)
    for index, frame in enumerate(frames):
        if index not in K_by_view:
            continue
        sel = np.flatnonzero(np.asarray(point_view) == index)
        if sel.size == 0:
            continue
        uv, z = project(pts[sel], K_by_view[index], np.asarray(frame["T_WC"], dtype=np.float64), dist)
        valid = np.isfinite(uv[:, 0]) & (z > 0)
        if not np.any(valid):
            continue
        centre = np.array([np.asarray(K_by_view[index])[0, 2], np.asarray(K_by_view[index])[1, 2]])
        radius = np.linalg.norm(uv[valid] - centre[None, :], axis=1)
        errors.append(radius)
    if not errors:
        return {"available": 0.0}
    all_radius = np.concatenate(errors)
    return {"available": 1.0, "mean_radius_px": float(all_radius.mean()),
            "p95_radius_px": float(np.percentile(all_radius, 95)),
            "n_points": int(all_radius.size)}


# ---------------------------------------------------------------------------- G05
def hausdorff_mm(reference: Any, candidate: Any, *, samples: int = 1500, seed: int = 0
                 ) -> dict[str, float]:
    """Sampled two-sided Hausdorff distance between two meshes (independent measurement)."""
    import trimesh

    if reference is None or candidate is None:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE, "Hausdorff needs two meshes",
                          stage="degrade.geometry.hausdorff_mm")
    if len(candidate.faces) == 0 or len(reference.faces) == 0:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE, "empty mesh in Hausdorff measurement",
                          stage="degrade.geometry.hausdorff_mm")
    n = int(max(samples, 100))
    pts_a, _ = trimesh.sample.sample_surface(reference, n, seed=int(seed))
    pts_b, _ = trimesh.sample.sample_surface(candidate, n, seed=int(seed) + 1)
    dist_ab = trimesh.proximity.ProximityQuery(candidate).on_surface(pts_a)[1]
    dist_ba = trimesh.proximity.ProximityQuery(reference).on_surface(pts_b)[1]
    both = np.concatenate([np.asarray(dist_ab, dtype=np.float64).ravel(),
                           np.asarray(dist_ba, dtype=np.float64).ravel()])
    return {"hausdorff_mm": float(both.max()), "mean_mm": float(both.mean()),
            "p95_mm": float(np.percentile(both, 95)), "samples": int(n),
            "direction": "two_sided_sampled"}


def normal_deviation_p95_deg(reference: Any, candidate: Any, *, samples: int = 800,
                             seed: int = 0) -> float:
    """Max angle between a sampled candidate face normal and the reference surface normal."""
    import trimesh

    pts, face_idx = trimesh.sample.sample_surface(candidate, int(samples), seed=int(seed))
    _closest, _dist, tri = trimesh.proximity.closest_point(reference, pts)
    ref_normals = np.asarray(reference.face_normals)[np.asarray(tri, dtype=np.int64)]
    cand_normals = np.asarray(candidate.face_normals)[np.asarray(face_idx, dtype=np.int64)]
    cos = np.abs(np.sum(ref_normals * cand_normals, axis=1))
    cos = np.clip(cos, 0.0, 1.0)
    return float(np.degrees(np.arccos(cos)).max()) if cos.size else 0.0


def decimate(mesh: Any, target_faces: int) -> tuple[Any, dict[str, Any]]:
    """Quadric edge-collapse decimation through Open3D 0.19 (the installable QEM backend)."""
    import open3d as o3d
    import trimesh

    target = int(max(target_faces, 4))
    source_faces = int(len(mesh.faces))
    if target >= source_faces:
        return mesh, {"backend": "IDENTITY", "target_faces": target,
                      "faces_before": source_faces, "faces_after": source_faces}
    o3d_mesh = o3d.geometry.TriangleMesh(
        vertices=o3d.utility.Vector3dVector(np.asarray(mesh.vertices, dtype=np.float64)),
        triangles=o3d.utility.Vector3iVector(np.asarray(mesh.faces, dtype=np.int32)))
    o3d_mesh.remove_duplicated_vertices()
    o3d_mesh.remove_degenerate_triangles()
    simplified = o3d_mesh.simplify_quadric_decimation(target_number_of_triangles=target)
    simplified.remove_degenerate_triangles()
    vertices = np.asarray(simplified.vertices, dtype=np.float64)
    faces = np.asarray(simplified.triangles, dtype=np.int64)
    if faces.size == 0:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                          "QEM decimation produced an empty mesh",
                          stage="degrade.geometry.decimate")
    out = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    info = {"backend": "OPEN3D_SIMPLIFY_QUADRIC_DECIMATION", "target_faces": target,
            "faces_before": source_faces, "faces_after": int(len(out.faces)),
            "vertices_before": int(len(mesh.vertices)), "vertices_after": int(len(out.vertices)),
            "face_attrs_lost": bool((mesh.metadata or {}).get("face_attr_arrays"))}
    return out, info


def roi_faces_from_points(mesh: Any, points: np.ndarray) -> np.ndarray:
    """Faces of ``mesh`` closest to the ROI points (ROI preservation constraint of G05)."""
    import trimesh

    pts = np.asarray(points, dtype=np.float64)
    if pts.size == 0 or len(mesh.faces) == 0:
        return np.zeros(0, dtype=np.int64)
    _closest, _dist, face_idx = trimesh.proximity.closest_point(mesh, pts)
    return np.unique(np.asarray(face_idx, dtype=np.int64))


def roi_retention(mesh: Any, roi_points: np.ndarray, *, tol_mm: float) -> dict[str, float]:
    import trimesh

    pts = np.asarray(roi_points, dtype=np.float64)
    if pts.size == 0:
        return {"available": 0.0, "retained_fraction": 0.0, "max_mm": 0.0, "n": 0}
    _closest, dist, _face = trimesh.proximity.closest_point(mesh, pts)
    dist = np.asarray(dist, dtype=np.float64).ravel()
    return {"available": 1.0, "retained_fraction": float(np.mean(dist <= float(tol_mm))),
            "mean_mm": float(dist.mean()), "max_mm": float(dist.max()), "n": int(len(dist)),
            "tol_mm": float(tol_mm)}


def decimate_with_budget(mesh: Any, *, max_error_mm: float, target_faces: int,
                         roi_points: np.ndarray | None = None, roi_tol_mm: float | None = None,
                         roi_min_fraction: float = 0.95, iterations: int = 5,
                         samples: int = 1200, seed: int = 0) -> tuple[Any, dict[str, Any]]:
    """1-D search on the face budget: measured Hausdorff <= ``max_error_mm`` and ROI kept.

    The budget is the *free* variable; the error and the ROI retention are measured on the
    decimated result (plan 15.4 G05: "独立实际 Hausdorff/normal/ROI 保留").  ROI retention is
    compared against the **source mesh's own** retention at the same tolerance, because the
    observed point set never lies exactly on the fused surface (measured baseline is reported).
    """
    faces_before = int(len(mesh.faces))
    baseline = (roi_retention(mesh, roi_points, tol_mm=roi_tol_mm)
                if roi_points is not None and roi_tol_mm is not None
                else {"available": 0.0, "retained_fraction": 1.0})
    best = None
    history: list[dict[str, Any]] = []
    lo, hi = 4, faces_before
    candidate_target = int(np.clip(target_faces, 4, faces_before))
    for _ in range(int(iterations)):
        candidate, info = decimate(mesh, candidate_target)
        haus = hausdorff_mm(mesh, candidate, samples=samples, seed=seed)
        retention = (roi_retention(candidate, roi_points, tol_mm=roi_tol_mm)
                     if roi_points is not None and roi_tol_mm is not None
                     else {"available": 0.0, "retained_fraction": 1.0})
        relative = float(retention["retained_fraction"]
                         / max(float(baseline["retained_fraction"]), 1e-9))
        normal_dev = normal_deviation_p95_deg(mesh, candidate, samples=min(samples, 400), seed=seed)
        record = {"target_faces": candidate_target, **{f"hausdorff_{k}": v
                                                       for k, v in haus.items()},
                  "roi_retained_fraction": retention["retained_fraction"],
                  "roi_retained_relative": relative,
                  "roi_baseline_fraction": baseline["retained_fraction"],
                  "normal_deviation_deg": normal_dev, "faces": info["faces_after"]}
        history.append(record)
        ok = (haus["hausdorff_mm"] <= float(max_error_mm)
              and relative >= float(roi_min_fraction))
        if ok and (best is None or info["faces_after"] < best[1]["faces_after"]):
            best = (candidate, {**info, "hausdorff": haus, "roi_retention": retention,
                                "roi_retention_relative": relative,
                                "roi_retention_baseline": baseline,
                                "normal_deviation_deg": normal_dev,
                                "max_error_mm": float(max_error_mm), "within_budget": True})
        if ok:
            hi = candidate_target
        else:
            lo = candidate_target
        candidate_target = int(np.clip(0.5 * (lo + hi), 4, faces_before))
        if hi - lo <= max(int(0.02 * faces_before), 2):
            break
    if best is None:
        raise SynLabError(
            ErrorCode.OPERATOR_NOT_REALIZED,
            f"G05 could not decimate within max_error_mm={max_error_mm} while keeping the ROI "
            f"(last measured Hausdorff {history[-1]['hausdorff_hausdorff_mm']:.4f} mm, relative "
            f"ROI retention {history[-1]['roi_retained_relative']:.3f}); the declared error "
            f"budget is not reachable for this mesh",
            stage="degrade.geometry.decimate_with_budget",
            measurements={"history_last": history[-1], "iterations": len(history)})
    mesh_out, info_out = best
    info_out["history"] = history
    return mesh_out, info_out


# ---------------------------------------------------------------------------- G06
def scale_observation(points: np.ndarray, factor: float) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64)
    return (pts * float(factor)).astype(np.float64)


# ---------------------------------------------------------------------------- G08 support
def observation_from_geometry(bundle: Any) -> Any:
    """Build a real :class:`ObservationResult` from a geometry/observation source bundle.

    G08 falsifies the *observed* surface (holes, connectivity, added faces); it consumes the
    same observation record the observation routes produce, so a geometry-only source is
    lifted into that record instead of being handled by a second, divergent code path.
    """
    existing = bundle.get("observation") if hasattr(bundle, "get") else None
    if existing is not None and hasattr(existing, "fused_mesh"):
        return existing
    from ..schemas.runtime import ObservationResult

    mesh = mesh_of(bundle)
    points = bundle.get("points") if hasattr(bundle, "get") else None
    normals = bundle.get("normals") if hasattr(bundle, "get") else None
    if points is None and mesh is not None:
        points = np.asarray(mesh.vertices, dtype=np.float64)
        normals = np.asarray(mesh.vertex_normals, dtype=np.float64)
    if points is None:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                          "G08 needs an observed mesh or point cloud",
                          stage="degrade.geometry.observation_from_geometry")
    points = np.asarray(points, dtype=np.float64)
    normals = (np.asarray(normals, dtype=np.float64) if normals is not None
               else np.tile(np.array([[0.0, 0.0, 1.0]]), (len(points), 1)))
    meta = dict(getattr(bundle, "meta", {}) or {})
    return ObservationResult(
        mother_id=str(meta.get("mother_id", "")), fragment_id=str(getattr(bundle, "fragment_id", "")),
        component_id=str(meta.get("component_id", "")), route=str(meta.get("route", "proxy_scan")),
        input_profile=str(meta.get("input_profile", "SENSOR_PROXY")),
        observation_id=str(meta.get("observation_id", getattr(bundle, "asset_id", "") or "obs")),
        views=list(bundle.get("views") or []), points=points.astype(np.float32),
        normals=normals.astype(np.float32), point_valid=np.ones(len(points), dtype=bool),
        normal_valid=np.ones(len(points), dtype=bool), scale_valid=True,
        frame_id=str(meta.get("frame_id", "S_mm")), quality=dict(meta.get("quality") or {}),
        fused_mesh=mesh, spurious_mask=None, backend_report={}, meta=meta,
    )


__all__ = [
    "DEPTH_OUTLIER_PROBABILITY",
    "points_of", "normals_of", "valid_of", "order_of", "roi_of", "frames_of", "mesh_of",
    "depth_frames", "frozen_geometry_hash",
    "depth_weight_field", "depth_error", "rms_against_reference",
    "nested_prefix_count", "sparsify", "point_density", "median_spacing",
    "surface_lattice", "label_regions", "freeze_hole_seeds", "hole_disk_mask", "measure_holes",
    "remove_holes_to_target",
    "frame_centers", "drift_pose", "refusion", "cloud_residual",
    "intrinsics_perturbation", "reprojection_error",
    "hausdorff_mm", "normal_deviation_p95_deg", "decimate", "roi_faces_from_points",
    "roi_retention", "decimate_with_budget",
    "scale_observation", "observation_from_geometry",
]
