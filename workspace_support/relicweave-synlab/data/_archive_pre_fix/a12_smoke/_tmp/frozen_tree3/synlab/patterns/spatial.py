"""Periodic chart-space geometry: lattices, Poisson dots and distance queries (plan 9.4).

The chart metric is ``(x_mm, s_mm)``; ``x`` wraps with period ``C_ref`` (the reference
circumference) and ``s`` is open.  All rejection rules below are *audited*: the achieved
minimum separation, retention rate, density and largest gap are measured on the frozen
point set and stored in the recipe.

Reuse: candidates come from ``scipy.stats.qmc.PoissonDisk`` (with native ``l_bounds`` /
``u_bounds`` support, so no anisotropic rescaling is needed) and neighbour checks use
``scipy.spatial.cKDTree``.  The extension only adds the periodic seam condition and the
variable-radius condition that the library does not model; no sampling kernel is
rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import scipy
from scipy.spatial import cKDTree
from scipy.stats import qmc

from ..errors import ErrorCode, SynLabError


# ---------------------------------------------------------------------------------------
# basic periodic distances
# ---------------------------------------------------------------------------------------
def periodic_dx(x_mm: np.ndarray, centre_mm: float, x_period_mm: float) -> np.ndarray:
    return np.mod(np.asarray(x_mm, dtype=np.float64) - float(centre_mm) + 0.5 * float(x_period_mm),
                  float(x_period_mm)) - 0.5 * float(x_period_mm)


def periodic_delta_2d(x_mm: np.ndarray, s_mm: np.ndarray, cx: float, cs: float,
                      x_period_mm: float) -> tuple[np.ndarray, np.ndarray]:
    return periodic_dx(x_mm, cx, x_period_mm), np.asarray(s_mm, dtype=np.float64) - float(cs)


def distance_to_points(x_mm: np.ndarray, s_mm: np.ndarray, centres: np.ndarray,
                       x_period_mm: float, *, workers: int = 1) -> np.ndarray:
    """True periodic Euclidean distance to the nearest centre (chunked for memory)."""
    x = np.asarray(x_mm, dtype=np.float64)
    s = np.asarray(s_mm, dtype=np.float64)
    cx = np.asarray(centres, dtype=np.float64)
    if cx.size == 0 or x.size == 0:
        return np.full(x.shape[0], np.inf)
    copies = np.vstack([cx, cx + np.array([x_period_mm, 0.0]), cx - np.array([x_period_mm, 0.0])])
    tree = cKDTree(copies)
    out = np.empty(x.shape[0], dtype=np.float64)
    step = 65536
    for start in range(0, x.shape[0], step):
        stop = min(start + step, x.shape[0])
        query = np.stack([x[start:stop], s[start:stop]], axis=1)
        dist, _ = tree.query(query, k=1, workers=workers)
        out[start:stop] = dist
    return out


def nearest_neighbour_distance(points: np.ndarray, x_period_mm: float) -> np.ndarray:
    """Nearest *other* dot distance on the periodic chart (cylindrical metric in mm)."""
    pts = np.asarray(points, dtype=np.float64)
    if pts.shape[0] < 2:
        return np.full(pts.shape[0], np.inf)
    copies = np.vstack([pts, pts + np.array([x_period_mm, 0.0]), pts - np.array([x_period_mm, 0.0])])
    labels = np.tile(np.arange(pts.shape[0]), 3)
    tree = cKDTree(copies)
    k = int(min(9, copies.shape[0]))
    dist, idx = tree.query(pts, k=k)
    dist = np.atleast_2d(dist)
    idx = np.atleast_2d(idx)
    out = np.full(pts.shape[0], np.inf)
    for row in range(pts.shape[0]):
        valid = labels[idx[row]] != row
        if np.any(valid):
            out[row] = float(dist[row][valid].min())
    return out


def distance_to_segments(x_mm: np.ndarray, s_mm: np.ndarray, segments: np.ndarray,
                         x_period_mm: float, *, chunk: int = 4096) -> np.ndarray:
    """Exact distance to a polyline set, evaluated with the wrapped copies in x.

    ``segments`` is ``(M,4)`` = ``(x0, s0, x1, s1)``.  Used as the *validation* path for
    the rasterised distance layers (brute force, chunked).
    """
    x = np.asarray(x_mm, dtype=np.float64)
    s = np.asarray(s_mm, dtype=np.float64)
    seg = np.asarray(segments, dtype=np.float64)
    out = np.full(x.shape[0], np.inf)
    if seg.size == 0:
        return out
    for shift in (-x_period_mm, 0.0, x_period_mm):
        p0 = seg[:, 0:2] + np.array([shift, 0.0])
        p1 = seg[:, 2:4] + np.array([shift, 0.0])
        d = p1 - p0
        denom = (d ** 2).sum(axis=1)
        denom = np.where(denom > 0, denom, 1.0)
        for start in range(0, x.shape[0], chunk):
            stop = min(start + chunk, x.shape[0])
            q = np.stack([x[start:stop], s[start:stop]], axis=1)
            rel = q[:, None, :] - p0[None, :, :]
            t = np.clip((rel * d[None, :, :]).sum(axis=2) / denom[None, :], 0.0, 1.0)
            closest = p0[None, :, :] + t[:, :, None] * d[None, :, :]
            dist = np.sqrt(((q[:, None, :] - closest) ** 2).sum(axis=2))
            out[start:stop] = np.minimum(out[start:stop], dist.min(axis=1))
    return out


def polyline_segments(x_mm: np.ndarray, s_mm: np.ndarray) -> np.ndarray:
    x = np.asarray(x_mm, dtype=np.float64)
    s = np.asarray(s_mm, dtype=np.float64)
    return np.stack([x[:-1], s[:-1], x[1:], s[1:]], axis=1)


# ---------------------------------------------------------------------------------------
# lattices with integer azimuthal counts
# ---------------------------------------------------------------------------------------
@dataclass
class DotSet:
    points: np.ndarray                      # (M,3) x_mm, s_mm, radius_mm
    report: dict[str, Any] = field(default_factory=dict)

    def centres(self) -> np.ndarray:
        return self.points[:, :2]

    def radii(self) -> np.ndarray:
        return self.points[:, 2]

    def payload(self) -> list[list[float]]:
        return [[float(a), float(b), float(c)] for a, b, c in self.points]

    @classmethod
    def from_payload(cls, rows: list, report: dict[str, Any] | None = None) -> "DotSet":
        return cls(points=np.asarray(rows, dtype=np.float64).reshape(-1, 3), report=dict(report or {}))


def lattice_dots(*, x_period_mm: float, s_min_mm: float, s_max_mm: float, spacing_mm: float,
                 radius_mm: float, mode: str = "hex", phase_x_mm: float = 0.0,
                 phase_s_mm: float = 0.0) -> DotSet:
    """Hexagonal/square dot lattice with an **integer** number of columns.

    The requested spacing is snapped to ``C_ref / n_columns`` so that the tile closes
    exactly at the seam; the deviation is measured and reported instead of hidden.
    """
    period = float(x_period_mm)
    spacing = float(spacing_mm)
    n_cols = max(1, int(round(period / spacing)))
    dx = period / n_cols
    if mode == "hex":
        ds = spacing * np.sqrt(3.0) / 2.0
    elif mode == "square":
        ds = spacing
    else:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unsupported lattice mode {mode!r}",
                          stage="patterns.spatial.lattice_dots")
    rows = int(np.ceil((float(s_max_mm) - float(s_min_mm)) / ds)) + 2
    cols = np.arange(n_cols, dtype=np.float64)
    row_ids = np.arange(-1, rows, dtype=np.float64)
    gx, gs = np.meshgrid(cols, row_ids, indexing="xy")
    xs = np.mod(gx * dx + phase_x_mm
                + np.where(mode == "hex", 0.5 * dx * np.mod(gs, 2.0), 0.0), period)
    ss = float(s_min_mm) + phase_s_mm + gs * ds
    keep = (ss >= float(s_min_mm)) & (ss <= float(s_max_mm))
    xs, ss = xs[keep], ss[keep]
    radii = np.full(xs.shape[0], float(radius_mm))
    points = np.stack([xs, ss, radii], axis=1)
    get = nearest_neighbour_distance(points[:, :2], period)
    report = {
        "mode": f"lattice_{mode}",
        "requested_spacing_mm": spacing,
        "realized_spacing_x_mm": float(dx),
        "realized_spacing_s_mm": float(ds),
        "spacing_deviation_mm": float(abs(dx - spacing)),
        "n_columns_integer": int(n_cols),
        "seam_closes_exactly": bool(abs(n_cols * dx - period) < 1e-9),
        "radius_mm": float(radius_mm),
        "n_points": int(points.shape[0]),
        "min_neighbour_distance_mm": float(np.nanmin(get)) if get.size else None,
        "median_neighbour_distance_mm": float(np.nanmedian(get)) if get.size else None,
        "density_per_100mm2": float(points.shape[0]
                                     / max(1e-9, (period * (float(s_max_mm) - float(s_min_mm))))
                                     * 100.0),
    }
    return DotSet(points=points, report=report)


def SynlabValueError(mode: str) -> SynLabError:  # pragma: no cover - tiny helper
    return SynLabError(ErrorCode.SCHEMA_INVALID, f"unsupported lattice mode {mode!r}",
                       stage="patterns.spatial.lattice_dots")


# ---------------------------------------------------------------------------------------
# Poisson disk with periodic seam extension (plan 9.4)
# ---------------------------------------------------------------------------------------
def sample_periodic_dots(rng: np.random.Generator, *, x_period_mm: float, s_min_mm: float,
                         s_max_mm: float, radius_mm: float,
                         var_radius_mm: tuple[float, float] | None = None,
                         clearance_mm: float = 0.0, ncandidates: int = 30,
                         density_target_per_100mm2: float | None = None,
                         max_points: int = 4000, max_rounds: int = 3) -> DotSet:
    """Generate a periodic Poisson-disk dot set and audit the real separation.

    Candidate radius is ``2*r_max + clearance`` (the conservative condition the library
    can guarantee); the extension then enforces the true variable-radius condition
    ``d_ij >= r_i + r_j + clearance`` **including across the seam**, in stable index
    order.  Minimum dot spacing is never relaxed: if the requested density cannot be
    reached, a structured ``TARGET_INFEASIBLE`` error is raised with the measured numbers.
    """
    period = float(x_period_mm)
    s0, s1 = float(s_min_mm), float(s_max_mm)
    area = period * max(1e-9, s1 - s0)
    if var_radius_mm is None:
        r_min = r_max = float(radius_mm)
        variable = False
    else:
        r_min, r_max = float(min(var_radius_mm)), float(max(var_radius_mm))
        variable = True
    clearance = max(0.0, float(clearance_mm))
    sampler_radius = 2.0 * r_max + clearance
    # hexagonal packing bound for an exclusion distance of `sampler_radius`
    packing_bound = 1.1547 / (sampler_radius ** 2) * 100.0
    target = (0.35 * packing_bound if density_target_per_100mm2 is None
              else float(density_target_per_100mm2))

    candidates: list[np.ndarray] = []
    rounds_info: list[dict[str, Any]] = []
    for round_index in range(int(max_rounds)):
        engine = qmc.PoissonDisk(2, radius=sampler_radius, ncandidates=int(ncandidates),
                                optimization=None,
                                l_bounds=[0.0, s0], u_bounds=[period, s1], rng=rng)
        got = np.asarray(engine.random(int(max_points)), dtype=np.float64)
        if got.size == 0:
            rounds_info.append({"round": round_index, "candidates": 0})
            continue
        radii = (rng.uniform(r_min, r_max, size=got.shape[0]) if variable
                 else np.full(got.shape[0], float(radius_mm)))
        block = np.stack([got[:, 0], got[:, 1], radii], axis=1)
        candidates.append(block)
        rounds_info.append({"round": round_index, "candidates": int(block.shape[0]),
                            "radius_mm": float(sampler_radius),
                            "bounds": [0.0, s0, period, s1], "ncandidates": int(ncandidates),
                            "optimization": None})
        merged = np.vstack(candidates)
        kept_preview = _enforce_periodic_separation(merged, period, clearance)[0]
        if kept_preview.shape[0] / max(area, 1e-9) * 100.0 >= target:
            break

    merged = np.vstack(candidates) if candidates else np.zeros((0, 3), dtype=np.float64)
    kept, rejection = _enforce_periodic_separation(merged, period, clearance)
    report: dict[str, Any] = {
        "engine": "scipy.stats.qmc.PoissonDisk",
        "scipy_version": scipy.__version__,
        "sampler_radius_mm": float(sampler_radius),
        "sampler_radius_rule": "2*r_max + clearance (library-guaranteed candidate separation)",
        "retention_rule": "d_ij >= r_i + r_j + clearance, periodic in x, stable index order",
        "clearance_mm": float(clearance),
        "radius_mm": None if variable else float(radius_mm),
        "var_radius_mm": ([r_min, r_max] if variable else None),
        "bounds_mm": [0.0, s0, period, s1],
        "ncandidates": int(ncandidates),
        "optimization": None,
        "n_candidates": int(merged.shape[0]),
        "n_kept": int(kept.shape[0]),
        "rounds": rounds_info,
        "max_rounds": int(max_rounds),
        "density_per_100mm2": float(kept.shape[0] / max(area, 1e-9) * 100.0),
        "density_target_per_100mm2": float(target),
        "packing_bound_per_100mm2": float(packing_bound),
        "density_rule": "target = 0.35 * hexagonal bound of the candidate exclusion distance",
        "area_mm2": float(area),
        "seam_extension": {
            "copies": "x +/- C_ref",
            "method": "scipy.spatial.cKDTree on the three periodic copies",
        },
    }
    report.update(rejection)
    if kept.shape[0] >= 2:
        nn = nearest_neighbour_distance(kept[:, :2], period)
        pair_margin = _min_pair_margin(kept, period, clearance)
        report["min_neighbour_distance_mm"] = float(np.nanmin(nn))
        report["median_neighbour_distance_mm"] = float(np.nanmedian(nn))
        report["min_radius_sum_margin_mm"] = float(pair_margin)
    else:
        report["min_neighbour_distance_mm"] = None
        report["median_neighbour_distance_mm"] = None
        report["min_radius_sum_margin_mm"] = None
    gap = max_gap_mm(kept[:, :2], x_period_mm=period, s_min_mm=s0, s_max_mm=s1,
                     probe_step_mm=max(0.5, 0.5 * r_min))
    report.update(gap)
    if report["density_per_100mm2"] < target:
        raise SynLabError(
            ErrorCode.TARGET_INFEASIBLE,
            f"periodic Poisson dot density {report['density_per_100mm2']:.4g}/100mm2 is below "
            f"the requested {target:.4g}/100mm2 after {len(rounds_info)} rounds; "
            "minimum spacing is not relaxed",
            stage="patterns.spatial.sample_periodic_dots",
            measurements={"density_per_100mm2": report["density_per_100mm2"],
                          "target_per_100mm2": target,
                          "n_kept": report["n_kept"],
                          "rejection_rate": report.get("rejection_rate")},
        )
    return DotSet(points=kept, report=report)


def _enforce_periodic_separation(points: np.ndarray, x_period_mm: float,
                                 clearance_mm: float) -> tuple[np.ndarray, dict[str, Any]]:
    """Greedy stable-order thinning that enforces ``d >= r_i + r_j + clearance``.

    Points are visited in their frozen index order.  A point is kept only when it
    satisfies the variable-radius condition against every *already kept* point (recent
    buffer + periodic cKDTree index), so the final set provably satisfies the rule,
    including pairs separated by the periodic seam.
    """
    if points.shape[0] == 0:
        return points, {"n_removed": 0, "n_removed_cross_seam": 0, "n_removed_same_tile": 0,
                        "rejection_rate": 0.0}
    kept: list[np.ndarray] = []
    buffer: list[np.ndarray] = []
    removed = 0
    removed_cross = 0
    tree: cKDTree | None = None
    tree_rows: np.ndarray | None = None
    buffer_limit = 64

    def _conflict(row: np.ndarray) -> np.ndarray | None:
        x, s, r = float(row[0]), float(row[1]), float(row[2])
        for other in buffer:
            if _periodic_distance(x, s, float(other[0]), float(other[1]), x_period_mm) \
                    < r + float(other[2]) + clearance_mm:
                return other
        if tree is not None and tree_rows is not None and tree_rows.shape[0]:
            search = r + float(tree_rows[:, 2].max()) + clearance_mm
            # the index carries the x +/- C copies as well: a planar ball would miss the
            # cross-seam neighbour entirely, which is exactly the pair the periodic
            # contract is about
            for index in tree.query_ball_point([x, s], search):
                other = tree_rows[index]
                if _periodic_distance(x, s, float(other[0]), float(other[1]), x_period_mm) \
                        < r + float(other[2]) + clearance_mm:
                    return other
        return None

    for row in np.asarray(points, dtype=np.float64):
        conflict = _conflict(row)
        if conflict is not None:
            removed += 1
            if abs(float(conflict[0]) - float(row[0])) > 0.5 * float(x_period_mm):
                removed_cross += 1
            continue
        kept.append(row)
        buffer.append(row)
        if len(buffer) >= buffer_limit:
            base = np.asarray(kept, dtype=np.float64)
            tree_rows = np.vstack([base, base + np.array([x_period_mm, 0.0, 0.0]),
                                   base - np.array([x_period_mm, 0.0, 0.0])])
            tree = cKDTree(tree_rows[:, :2])
            buffer = []
    kept_arr = np.asarray(kept, dtype=np.float64).reshape(-1, 3)
    return kept_arr, {
        "n_removed": int(removed),
        "n_removed_cross_seam": int(removed_cross),
        "n_removed_same_tile": int(removed - removed_cross),
        "rejection_rate": float(removed / max(1, points.shape[0])),
        "neighbour_index": "periodic cKDTree over x and x +/- C_ref copies",
    }


def _periodic_distance(x0: float, s0: float, x1: float, s1: float, period: float) -> float:
    dx = (x0 - x1 + 0.5 * period) % period - 0.5 * period
    return float(np.hypot(dx, s0 - s1))


def _min_pair_margin(points: np.ndarray, x_period_mm: float, clearance_mm: float) -> float:
    pts = np.asarray(points, dtype=np.float64)
    if pts.shape[0] < 2:
        return float("inf")
    copies = np.vstack([pts, pts + np.array([x_period_mm, 0.0, 0.0]),
                        pts - np.array([x_period_mm, 0.0, 0.0])])
    tree = cKDTree(copies[:, :2])
    k = int(min(12, copies.shape[0]))
    dist, idx = tree.query(pts[:, :2], k=k)
    dist = np.atleast_2d(dist)
    idx = np.atleast_2d(idx)
    margin = np.inf
    n = pts.shape[0]
    for row in range(n):
        for col in range(dist.shape[1]):
            j = int(idx[row, col]) % n
            if j == row:
                continue
            limit = pts[row, 2] + pts[j, 2] + clearance_mm
            margin = min(margin, float(dist[row, col] - limit))
    return float(margin)


def max_gap_mm(points: np.ndarray, *, x_period_mm: float, s_min_mm: float, s_max_mm: float,
               probe_step_mm: float) -> dict[str, Any]:
    """Largest distance from a probe grid to the nearest frozen dot (periodic metric)."""
    x = np.arange(0.0, float(x_period_mm), float(probe_step_mm)) + 0.5 * float(probe_step_mm)
    s = np.arange(float(s_min_mm), float(s_max_mm), float(probe_step_mm)) + 0.5 * float(probe_step_mm)
    if x.size == 0 or s.size == 0 or points.shape[0] == 0:
        return {"max_gap_mm": None, "gap_probe_grid_mm": float(probe_step_mm),
                "gap_method": "probe grid + periodic cKDTree"}
    gx, gs = np.meshgrid(x, s, indexing="xy")
    d = distance_to_points(gx.reshape(-1), gs.reshape(-1), points, x_period_mm)
    return {
        "max_gap_mm": float(d.max()),
        "gap_probe_grid_mm": float(probe_step_mm),
        "gap_method": "probe grid (step above) + periodic cKDTree nearest distance",
    }
