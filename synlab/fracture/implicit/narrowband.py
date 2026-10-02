"""Fallback path: true 3-D narrow-band signed distance field + marching cubes.

The main path meshes the fracture surface as a **graph** ``w = h(u, v)``.  That is exact for every
surface a height field can express, and it is what makes the tensor grid and the ring closure
possible -- but it cannot express a surface that folds back over itself (a hanging glass shell, an
overhanging conchoidal lip: one vertical line crosses the surface twice).

This module extracts the surface from a genuine 3-D scalar field instead:

* the caller supplies ``sdf_fn(u, v, w)`` in the cut basis' local frame (negative *below* the
  surface), e.g. ``w - h(u, v)`` for the graph case or a folded field for the overhang case;
* the field is sampled on a **narrow band**: the ``(u, v)`` extent is the cutter frame and the
  ``w`` extent is the field's own range plus a margin, so the zero level set never touches the
  top or bottom face of the box (otherwise marching cubes would return a surface with a boundary
  there, which is not a fracture surface);
* ``skimage.measure.marching_cubes`` extracts it, and **the same mesh is then closed** by
  extruding the loop(s) that lie on the frame walls down to ``bottom_w`` -- the identical closure
  contract as the main path, so both halves still consume one instance.

The extracted surface is verified (edge-use histogram, watertightness, winding, volume) exactly
like the main path; a failure is reported, never repaired silently.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import numpy as np

from .sheet import topology_report

__all__ = ["build_narrowband_sheet", "build_narrowband_cutter", "folded_sdf_fn"]

_EPS = 1.0e-12


def folded_sdf_fn(h_fn: Callable[[np.ndarray, np.ndarray], np.ndarray], *,
                  fold_u_mm: float, fold_amplitude_mm: float) -> Callable:
    """A genuinely **non-graph** sheet: the surface folds back across a line ``u = fold_u``.

    ``F(u, v, w) = (w - h(u, v)) * (w - h(u, v) - d(u)) `` with a signed offset ``d`` that changes
    sign across the fold: the zero set is then the union of two sheets that meet along the fold
    line, i.e. exactly the geometry a height field over ``(u, v)`` cannot express.  It exists so
    the fallback path has a real, measurable test case instead of only the graph case the main
    path already covers.
    """

    def sdf(u: np.ndarray, v: np.ndarray, w: np.ndarray) -> np.ndarray:
        uu = np.asarray(u, dtype=np.float64)
        h = np.asarray(h_fn(uu, v), dtype=np.float64)
        side = np.tanh((uu - float(fold_u_mm)) / max(0.25 * abs(float(fold_amplitude_mm)), 1e-6))
        d = float(fold_amplitude_mm) * side
        return (np.asarray(w, dtype=np.float64) - h) * (np.asarray(w, dtype=np.float64) - h - d)

    return sdf


def build_narrowband_sheet(
    *,
    sdf_fn: Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray],
    u_range: tuple[float, float],
    v_range: tuple[float, float],
    w_range: tuple[float, float],
    delta_mm: float,
    pad_cells: int = 3,
    chunk_cells: int = 4_000_000,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Sample the narrow band and extract its zero level set as ``(vertices_local, faces)``."""
    from skimage import measure

    u0 = float(u_range[0]) - pad_cells * delta_mm
    u1 = float(u_range[1]) + pad_cells * delta_mm
    v0 = float(v_range[0]) - pad_cells * delta_mm
    v1 = float(v_range[1]) + pad_cells * delta_mm
    w0 = float(w_range[0])
    w1 = float(w_range[1])
    nu = int(np.ceil((u1 - u0) / delta_mm)) + 1
    nv = int(np.ceil((v1 - v0) / delta_mm)) + 1
    nw = int(np.ceil((w1 - w0) / delta_mm)) + 1
    gu = np.linspace(u0, u1, nu)
    gv = np.linspace(v0, v1, nv)
    gw = np.linspace(w0, w1, nw)
    started = time.time()
    field = np.empty((nu, nv, nw), dtype=np.float32)
    for i0 in range(0, nu, max(1, chunk_cells // max(nv * nw, 1))):
        i1 = min(nu, i0 + max(1, chunk_cells // max(nv * nw, 1)))
        U, V, W = np.meshgrid(gu[i0:i1], gv, gw, indexing="ij")
        field[i0:i1] = np.asarray(sdf_fn(U, V, W), dtype=np.float32)
    seconds_sample = time.time() - started
    started = time.time()
    verts_ijk, faces, _normals, _values = measure.marching_cubes(field, level=0.0)
    seconds_mc = time.time() - started
    verts_local = np.column_stack([
        u0 + verts_ijk[:, 0] * (u1 - u0) / max(nu - 1, 1),
        v0 + verts_ijk[:, 1] * (v1 - v0) / max(nv - 1, 1),
        w0 + verts_ijk[:, 2] * (w1 - w0) / max(nw - 1, 1),
    ])
    info = {
        "grid_shape": [int(nu), int(nv), int(nw)],
        "cells": int(nu * nv * nw), "delta_mm": float(delta_mm),
        "band_w_mm": [float(w0), float(w1)], "band_thickness_mm": float(w1 - w0),
        "vertices": int(verts_local.shape[0]), "faces": int(faces.shape[0]),
        "seconds_sample": float(seconds_sample), "seconds_marching_cubes": float(seconds_mc),
        "u_range_padded": [float(u0), float(u1)], "v_range_padded": [float(v0), float(v1)],
    }
    return verts_local, np.asarray(faces, dtype=np.int64), info


def build_narrowband_cutter(
    basis: Any,
    *,
    sdf_fn: Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray],
    w_range: tuple[float, float],
    delta_mm: float,
    bottom_w: float,
    pad_cells: int = 3,
) -> tuple[Any, dict[str, Any]]:
    """Extract the sheet with marching cubes, close it on ``bottom_w`` and verify the result."""
    import trimesh

    verts_local, faces, info = build_narrowband_sheet(
        sdf_fn=sdf_fn, u_range=(float(basis.u_range[0]), float(basis.u_range[1])),
        v_range=(float(basis.v_range[0]), float(basis.v_range[1])), w_range=w_range,
        delta_mm=float(delta_mm), pad_cells=int(pad_cells))
    matrix = np.stack([basis.e_u, basis.e_v, basis.normal], axis=0)
    world = verts_local @ matrix + np.asarray(basis.origin, dtype=np.float64)[None, :]
    started = time.time()
    vertices, all_faces, closure = _close_loops(world, faces, bottom_w=float(bottom_w))
    info["seconds_closure"] = time.time() - started
    mesh = trimesh.Trimesh(vertices=vertices, faces=all_faces, process=False)
    topology = topology_report(mesh)
    info["closure"] = closure
    info["topology"] = topology
    info["watertight"] = bool(topology["is_watertight"] and topology["bad_edges"] == 0)
    return mesh, info


def _boundary_loops(faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Directed boundary edges of an open surface (each used exactly once)."""
    directed = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0)
    undirected = np.sort(directed, axis=1)
    key = undirected[:, 0].astype(np.int64) * np.int64(undirected.max() + 1) + undirected[:, 1]
    uniq, inverse, counts = np.unique(key, return_inverse=True, return_counts=True)
    single = np.nonzero(counts == 1)[0]
    if single.size == 0:
        return np.zeros((0, 2), dtype=np.int64), uniq
    pick = np.full(uniq.size, -1, dtype=np.int64)
    rows = np.nonzero(counts[inverse] == 1)[0]
    pick[inverse[rows]] = rows
    return directed[pick[single]], uniq


def _close_loops(vertices_top: np.ndarray, faces_top: np.ndarray, *, bottom_w: float
                 ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Close an *arbitrary* open top surface by extruding every boundary loop down to ``bottom_w``.

    The extruded curtain must be oriented consistently with the top surface; both orientations are
    tried and the one that verifies (every edge used exactly twice) is kept.  When neither works
    the closure reports ``bad_edges > 0`` and the caller raises -- a silent repair would hide a
    real topology defect.
    """
    top = np.asarray(vertices_top, dtype=np.float64).reshape(-1, 3)
    faces = np.asarray(faces_top, dtype=np.int64).reshape(-1, 3)
    n_top = top.shape[0]
    bottom = np.column_stack([top[:, 0], top[:, 1], np.full(n_top, float(bottom_w))])
    boundary, _uniq = _boundary_loops(faces)
    best: tuple[int, np.ndarray, dict[str, Any]] | None = None
    for flip in (False, True):
        edges = boundary[:, ::-1] if flip else boundary
        a = edges[:, 0]
        b = edges[:, 1]
        a_bot = a + n_top
        b_bot = b + n_top
        side = np.concatenate([
            np.stack([a, a_bot, b_bot], axis=1),
            np.stack([a, b_bot, b], axis=1),
        ], axis=0)
        vertices = np.concatenate([top, bottom], axis=0)
        all_faces = np.concatenate([faces, side], axis=0)
        flat_edges = np.sort(np.concatenate(
            [all_faces[:, [0, 1]], all_faces[:, [1, 2]], all_faces[:, [2, 0]]], axis=0), axis=1)
        key = flat_edges[:, 0].astype(np.int64) * np.int64(vertices.shape[0]) + flat_edges[:, 1]
        _k, counts = np.unique(key, return_counts=True)
        bad = int(np.sum(counts != 2))
        volume = float(np.einsum(
            "ij,ij->i", np.cross(vertices[all_faces[:, 1]] - vertices[all_faces[:, 0]],
                                 vertices[all_faces[:, 2]] - vertices[all_faces[:, 0]]),
            vertices[all_faces[:, 0]]).sum() / 6.0)
        if volume < 0.0:
            all_faces = all_faces[:, ::-1].copy()
            volume = -volume
        record = {"boundary_edges": int(boundary.shape[0]), "flipped_loops": bool(flip),
                  "side_faces": int(side.shape[0]), "bad_edges": bad,
                  "volume_mm3": float(volume), "bottom_w_mm": float(bottom_w),
                  "top_faces": int(faces.shape[0]), "top_vertices": int(n_top)}
        if best is None or bad < best[0]:
            best = (bad, all_faces, record)
        if bad == 0:
            break
    assert best is not None
    _bad, all_faces, record = best
    record["edge_use_histogram"] = _histogram(all_faces, n_top * 2)
    if _bad != 0:  # distinct bottom vertices per loop vertex would be needed: say so, do not repair
        record["failure"] = ("the closed body still has edges with a face count != 2 "
                             "(open surface with non-manifold boundary)")
    return np.concatenate([top, bottom], axis=0), all_faces, record


def _histogram(faces: np.ndarray, n_vertices: int) -> dict[str, int]:
    flat_edges = np.sort(np.concatenate(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0), axis=1)
    key = flat_edges[:, 0].astype(np.int64) * np.int64(max(n_vertices, 1)) + flat_edges[:, 1]
    _k, counts = np.unique(key, return_counts=True)
    return {str(int(k)): int(v) for k, v in zip(*np.unique(counts, return_counts=True))}
