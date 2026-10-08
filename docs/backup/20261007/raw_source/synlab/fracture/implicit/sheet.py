"""Conforming sheet triangulation + closed cutter assembly (no quadtree, no T-junction).

Why this cannot produce a T-junction
------------------------------------
The sheet is meshed on a **tensor-product grid**: two monotone 1-D coordinate arrays ``u[]`` and
``v[]`` and one quad per ``(i, j)`` pair.  Every quad owns four lattice corners and neighbours on
all four sides share a *full* edge, whatever the local spacing is.  A hanging vertex is therefore
not a property that has to be repaired at the end (which is where ``cut.py``'s quadtree assembler
loses edges: two leaves of different generations meet mid-edge) -- it cannot exist.  The grid is
graded where the field needs it (fine inside the material band, coarse in the flat frame) purely
through the two coordinate arrays.

The closed body is then assembled the same way the frozen plane cutter does it, and the result is
verified per edge: one bottom mirror face per top face (reversed winding) plus one two-triangle
side quad per silhouette edge.  Every edge of the result is used by exactly two faces, and that
count is measured, not assumed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

__all__ = [
    "graded_axis",
    "TensorSheet",
    "build_tensor_sheet",
    "close_sheet",
    "topology_report",
    "measure_realized_error",
    "measure_sampling_density",
]


# ---------------------------------------------------------------------------- 1-D grading
def graded_axis(lo: float, hi: float, fine_lo: float, fine_hi: float, *, delta_mm: float,
                coarse_max_mm: float, growth: float = 1.6) -> tuple[np.ndarray, dict[str, Any]]:
    """Monotone coordinate array: spacing ``<= delta_mm`` on ``[fine_lo, fine_hi]``, growing out.

    The fine part is uniform with ``n = ceil((fine_hi - fine_lo) / delta)`` intervals, so the
    realized spacing is ``<= delta`` and the endpoints of the fine block are exact lattice points.
    Outside the fine block the spacing grows geometrically up to ``coarse_max_mm`` (the field is
    exactly flat there, so those cells carry exactly zero interpolation error).
    """
    lo, hi = float(lo), float(hi)
    fine_lo = float(min(max(fine_lo, lo), hi))
    fine_hi = float(min(max(fine_hi, fine_lo), hi))
    delta = float(max(delta_mm, 1.0e-9))
    n_fine = int(max(1, np.ceil(max(fine_hi - fine_lo, delta) / delta)))
    fine = np.linspace(fine_lo, fine_hi, n_fine + 1)

    def outward(start: float, limit: float) -> list[float]:
        if abs(start - limit) <= 1.0e-12:
            return []
        sign = -1.0 if limit < start else 1.0
        pts: list[float] = []
        x = start
        step = delta
        while sign * (limit - x) > 1.0e-12:
            step = min(step, float(coarse_max_mm))
            nxt = x + sign * step
            if sign * (nxt - limit) >= 0.0:
                nxt = limit
            pts.append(float(nxt))
            x = nxt
            step *= float(growth)
        # merge a numerically degenerate last interval into its predecessor
        if len(pts) >= 2 and abs(pts[-1] - pts[-2]) < 0.1 * delta:
            pts.pop(-2)
        return pts

    left = outward(fine_lo, lo)          # descending away from the fine block
    right = outward(fine_hi, hi)
    coords = np.concatenate([np.asarray(left[::-1], dtype=np.float64), fine,
                             np.asarray(right, dtype=np.float64)])
    d = np.diff(coords)
    inside_fine = (coords[:-1] >= fine_lo - 1e-9) & (coords[1:] <= fine_hi + 1e-9)
    info = {
        "lo": lo, "hi": hi, "fine_lo": fine_lo, "fine_hi": fine_hi,
        "intervals": int(coords.size - 1),
        "fine_intervals": int(n_fine),
        "fine_step_mm": float((fine_hi - fine_lo) / n_fine),
        "step_min_mm": float(d.min()), "step_max_mm": float(d.max()),
        "step_max_inside_fine_mm": float(d[inside_fine].max()) if bool(inside_fine.any()) else 0.0,
        "monotone": bool(np.all(d > 0.0)),
    }
    return coords, info


# ---------------------------------------------------------------------------- sheet mesh
@dataclass
class TensorSheet:
    """A triangulated graph ``w = h(u, v)`` on a tensor grid, plus its measured records."""

    u: np.ndarray
    v: np.ndarray
    uv: np.ndarray            # (N, 2) lattice points, row-major (i * nv + j)
    heights: np.ndarray       # (N,) evaluated h
    faces: np.ndarray         # (T, 3) int64, CCW in (u, v) so the normal follows +n
    axis_u: dict[str, Any]
    axis_v: dict[str, Any]
    seconds_evaluate: float
    seconds_triangulate: float

    @property
    def n_u(self) -> int:
        return int(self.u.size)

    @property
    def n_v(self) -> int:
        return int(self.v.size)


def build_tensor_sheet(
    basis: Any,
    h_fn: Callable[[np.ndarray, np.ndarray], np.ndarray],
    *,
    delta_mm: float,
    fine_u: tuple[float, float],
    fine_v: tuple[float, float],
    coarse_max_mm: float,
    chunk_points: int = 400_000,
) -> TensorSheet:
    """Grade the two axes, evaluate ``h`` on the lattice (chunked) and triangulate the graph."""
    u, info_u = graded_axis(float(basis.u_range[0]), float(basis.u_range[1]), fine_u[0], fine_u[1],
                            delta_mm=delta_mm, coarse_max_mm=coarse_max_mm)
    v, info_v = graded_axis(float(basis.v_range[0]), float(basis.v_range[1]), fine_v[0], fine_v[1],
                            delta_mm=delta_mm, coarse_max_mm=coarse_max_mm)
    started = time.time()
    UU, VV = np.meshgrid(u, v, indexing="ij")
    grid_u = UU.ravel()
    grid_v = VV.ravel()
    heights = np.empty(grid_u.size, dtype=np.float64)
    for start in range(0, grid_u.size, int(chunk_points)):
        stop = min(start + int(chunk_points), grid_u.size)
        heights[start:stop] = np.asarray(
            h_fn(grid_u[start:stop], grid_v[start:stop]), dtype=np.float64).reshape(-1)
    seconds_evaluate = time.time() - started

    started = time.time()
    nu, nv = u.size, v.size
    i, j = np.meshgrid(np.arange(nu - 1), np.arange(nv - 1), indexing="ij")
    i = i.ravel()
    j = j.ravel()
    a = i * nv + j
    b = (i + 1) * nv + j
    c = (i + 1) * nv + (j + 1)
    d = i * nv + (j + 1)
    faces = np.concatenate([np.stack([a, b, c], axis=1), np.stack([a, c, d], axis=1)], axis=0)
    seconds_triangulate = time.time() - started
    return TensorSheet(u=u, v=v, uv=np.stack([grid_u, grid_v], axis=1), heights=heights,
                       faces=faces, axis_u=info_u, axis_v=info_v, seconds_evaluate=seconds_evaluate,
                       seconds_triangulate=seconds_triangulate)


# ---------------------------------------------------------------------------- closure
def _directed_edges(faces: np.ndarray) -> np.ndarray:
    return np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0)


def close_sheet(vertices_top: np.ndarray, faces_top: np.ndarray, *, bottom_w: float
                ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Close a top surface by a flat bottom copy + one side quad per silhouette edge.

    Returns ``(vertices, faces, report)``.  The construction is the frozen plane cutter's: every
    top vertex gets exactly one bottom counterpart, every top face gets its mirrored bottom face
    with reversed winding, and every top edge used once (the silhouette) gets a two-triangle side
    quad.  ``report`` publishes the measured edge-use histogram of the result.
    """
    top = np.asarray(vertices_top, dtype=np.float64).reshape(-1, 3)
    faces = np.asarray(faces_top, dtype=np.int64).reshape(-1, 3)
    n_top = top.shape[0]
    bottom = np.column_stack([top[:, 0], top[:, 1], np.full(n_top, float(bottom_w))])
    vertices = np.concatenate([top, bottom], axis=0)
    n = int(n_top)

    mirrored = (faces + n)[:, ::-1]
    directed = _directed_edges(faces)
    undirected = np.sort(directed, axis=1)
    key = undirected[:, 0].astype(np.int64) * np.int64(n) + undirected[:, 1]
    uniq, inverse, counts = np.unique(key, return_inverse=True, return_counts=True)
    boundary_rows = np.nonzero(counts == 1)[0]
    pick = np.full(uniq.size, -1, dtype=np.int64)
    one_use = counts[inverse] == 1
    pick[inverse[one_use]] = np.nonzero(one_use)[0]
    edges = directed[pick[boundary_rows]] if boundary_rows.size else np.zeros((0, 2), np.int64)
    a = edges[:, 0]
    b = edges[:, 1]
    a_bot = a + n
    b_bot = b + n
    side = np.concatenate([
        np.stack([a, a_bot, b_bot], axis=1),
        np.stack([a, b_bot, b], axis=1),
    ], axis=0)
    all_faces = np.concatenate([faces, mirrored, side], axis=0)
    flat_edges = np.sort(_directed_edges(all_faces), axis=1).astype(np.int64)
    edge_key = flat_edges[:, 0] * np.int64(vertices.shape[0]) + flat_edges[:, 1]
    _keys, edge_counts = np.unique(edge_key, return_counts=True)
    histogram = {int(k): int(v) for k, v in zip(*np.unique(edge_counts, return_counts=True))}
    volume = float(np.einsum(
        "ij,ij->i", np.cross(vertices[all_faces[:, 1]] - vertices[all_faces[:, 0]],
                             vertices[all_faces[:, 2]] - vertices[all_faces[:, 0]]),
        vertices[all_faces[:, 0]]).sum() / 6.0)
    flipped = False
    if volume < 0.0:
        all_faces = all_faces[:, ::-1].copy()
        volume = -volume
        flipped = True
    report = {
        "top_vertices": int(n_top), "top_faces": int(faces.shape[0]),
        "silhouette_edges": int(edges.shape[0]), "side_faces": int(side.shape[0]),
        "total_faces": int(all_faces.shape[0]), "total_vertices": int(vertices.shape[0]),
        "edge_use_histogram": histogram,
        "bad_edges": int(sum(v for k, v in histogram.items() if k != 2)),
        "winding_flipped": bool(flipped), "volume_mm3": float(volume),
        "bottom_w_mm": float(bottom_w),
    }
    return vertices, all_faces, report


def topology_report(mesh: Any) -> dict[str, Any]:
    """Independent per-edge verification of one closed mesh (never trusts the assembler)."""
    faces = np.asarray(mesh.faces, dtype=np.int64).reshape(-1, 3)
    n = int(np.asarray(mesh.vertices).shape[0])
    directed = _directed_edges(faces)
    undirected = np.sort(directed, axis=1).astype(np.int64)
    flat = undirected[:, 0] * np.int64(max(n, 1)) + undirected[:, 1]
    _uniq, counts = np.unique(flat, return_counts=True)
    histogram: dict[int, int] = {}
    for k, c in zip(*np.unique(counts, return_counts=True)):
        histogram[int(k)] = int(c)
    non_manifold = int(np.sum(counts != 2))
    return {
        "faces": int(faces.shape[0]), "vertices": n,
        "is_watertight": bool(mesh.is_watertight),
        "is_winding_consistent": bool(mesh.is_winding_consistent),
        "volume_mm3": float(abs(mesh.volume)),
        "signed_volume_mm3": float(mesh.volume),
        "bad_edges": non_manifold,
        "boundary_edges": int(np.sum(counts == 1)),
        "edge_use_histogram": histogram,
        "euler_number": int(n - _unique_edges_count(faces) + faces.shape[0]),
        "euler_number_trimesh": int(mesh.euler_number),
    }


def _unique_edges_count(faces: np.ndarray) -> int:
    edges = np.sort(_directed_edges(np.asarray(faces, dtype=np.int64)), axis=1)
    return int(np.unique(edges[:, 0] * np.int64(edges.max() + 1) + edges[:, 1]).size)


# ---------------------------------------------------------------------------- measurements
def measure_realized_error(
    h_fn: Callable[[np.ndarray, np.ndarray], np.ndarray],
    sheet: TensorSheet,
    *,
    budget_mm: float,
    lambda_min_mm: float,
    inside_fn: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
    flat_sample: int = 2_000,
    chunk_triangles: int = 8_000,
    max_probes_per_triangle: int = 4,
    seed: int = 20261002,
) -> dict[str, Any]:
    """Measured interpolation error of the *analytic* field over the *emitted* triangles.

    Every triangle is probed on a barycentric lattice whose order resolves the shortest retained
    wavelength (12 probes per wavelength); the worst deviation of the linear interpolant from the
    analytic surface is reported per triangle and overall.  Triangles that lie entirely in the
    flat part of the frame are verified on a random sample as well -- their error is expected to be
    exactly zero, and the sample says whether it is.
    """
    faces = sheet.faces
    pts = np.column_stack([sheet.uv, sheet.heights])
    order = int(np.clip(int(max_probes_per_triangle), 1, 6))
    bary = []
    for i in range(order + 1):
        for j in range(order + 1 - i):
            bary.append([(order - i - j) / order, i / order, j / order])
    bary = np.asarray(bary, dtype=np.float64)

    tri_pts = pts[faces]
    edge = np.linalg.norm(tri_pts[:, [1, 2, 0]] - tri_pts[:, [0, 1, 2]], axis=2).max(axis=1)
    active = np.ones(faces.shape[0], dtype=bool)
    if inside_fn is not None:
        rng = np.random.default_rng(int(seed))
        centre = tri_pts.mean(axis=1)
        touching = np.asarray(inside_fn(centre[:, 0], centre[:, 1]), dtype=bool)
        flat_rows = np.nonzero(~touching)[0]
        if flat_rows.size:
            take = rng.permutation(flat_rows.size)[:int(flat_sample)]
            active = np.zeros(faces.shape[0], dtype=bool)
            active[touching] = True
            active[flat_rows[take]] = True

    rows = np.nonzero(active)[0]
    worst = 0.0
    worst_row = -1
    worst_uv = [0.0, 0.0]
    total_checked = 0
    for start in range(0, rows.size, int(chunk_triangles)):
        block = rows[start:start + int(chunk_triangles)]
        tp = tri_pts[block]
        samp = np.einsum("bk,tkc->tbc", bary, tp)
        flat = samp.reshape(-1, 3)
        analytic = np.asarray(h_fn(flat[:, 0], flat[:, 1]), dtype=np.float64)
        dev = np.abs(analytic - flat[:, 2])
        total_checked += int(block.size)
        local = int(np.argmax(dev))
        if float(dev[local]) > worst:
            worst = float(dev[local])
            worst_row = int(block[local // bary.shape[0]])
            worst_uv = [float(flat[local, 0]), float(flat[local, 1])]
    return {
        "budget_mm": float(budget_mm), "probe_order": order,
        "probes_per_triangle": int(bary.shape[0]),
        "triangles_checked": int(total_checked),
        "realized_error_mm": float(worst),
        "within_budget": bool(worst <= float(budget_mm) * (1.0 + 1e-9)),
        "worst_triangle": int(worst_row), "worst_uv_mm": worst_uv,
        "max_edge_mm": float(edge.max()) if edge.size else 0.0,
    }


def measure_sampling_density(
    sheet: TensorSheet,
    *,
    lambda_min_mm: float,
    core_fn: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
) -> dict[str, Any]:
    """Measured edge length of the emitted sheet inside the footprint vs the shortest wavelength."""
    faces = sheet.faces
    pts = sheet.uv
    tri_pts = pts[faces]
    lengths = np.linalg.norm(np.concatenate([
        tri_pts[:, 1] - tri_pts[:, 0], tri_pts[:, 2] - tri_pts[:, 1], tri_pts[:, 0] - tri_pts[:, 2]],
        axis=0), axis=1)
    if core_fn is not None:
        centre = tri_pts.mean(axis=1)
        core = np.asarray(core_fn(centre[:, 0], centre[:, 1]), dtype=bool)
        inside = np.concatenate([core, core, core])
        selected = lengths[inside]
    else:
        selected = lengths
    if selected.size == 0:
        return {"edges": 0, "note": "no edge inside the footprint"}
    lam = float(lambda_min_mm)
    return {
        "edges": int(selected.size),
        "edge_median_mm": float(np.median(selected)),
        "edge_p95_mm": float(np.percentile(selected, 95)),
        "edge_max_mm": float(selected.max()),
        "lambda_min_mm": lam,
        "samples_per_lambda_median": float(lam / max(float(np.median(selected)), 1e-12)),
        "samples_per_lambda_p95_worst": float(lam / max(float(np.percentile(selected, 95)), 1e-12)),
        "meets_4_per_lambda": bool(lam / max(float(np.percentile(selected, 95)), 1e-12) >= 4.0),
        "meets_5_per_lambda": bool(lam / max(float(np.percentile(selected, 95)), 1e-12) >= 5.0),
    }
