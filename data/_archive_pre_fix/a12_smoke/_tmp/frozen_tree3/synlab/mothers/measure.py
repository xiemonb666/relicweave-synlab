"""Mesh measurements used by the mother QA gate (plan 7.3).

The thickness of a *realised* (possibly warped, possibly boolean-joined) body cannot be
read back from the design parameters, so it is measured on the final triangles with
Manifold's ray casts (``manifold3d.Manifold.ray_cast``, see ``_poc_reuse``):

* wall thickness  - cast each sampled face centroid along the inward normal and take the
  first hit; the hit distance *is* the local material thickness in millimetres;
* void probing    - count the crossings of a ray leaving a point; an even count means the
  point sits in a cavity (used to prove that an open vessel keeps its cavity).

``trimesh``'s own ray engine needs ``rtree``, which is not installed on this host, so the
Manifold engine is the reuse route here.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import trimesh

from .solids import to_manifold


def _stride_indices(count: int, limit: int) -> np.ndarray:
    if count <= limit:
        return np.arange(count)
    return np.unique(np.linspace(0, count - 1, limit).astype(np.int64))


def _confirm_interior(mesh: trimesh.Trimesh, points: np.ndarray, *,
                      chunk: int = 4096) -> np.ndarray:
    """Signed-solid-angle interior test for every point, chunked to bound memory."""
    verts = np.ascontiguousarray(np.asarray(mesh.vertices, dtype=np.float64))
    faces = np.ascontiguousarray(np.asarray(mesh.faces, dtype=np.int64))
    a = verts[faces[:, 0]]
    b = verts[faces[:, 1]]
    c = verts[faces[:, 2]]
    pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
    out = np.zeros(pts.shape[0], dtype=bool)
    for start in range(0, pts.shape[0], int(chunk)):
        block = pts[start:start + chunk]
        d0 = a[None, :, :] - block[:, None, :]
        d1 = b[None, :, :] - block[:, None, :]
        d2 = c[None, :, :] - block[:, None, :]
        la = np.linalg.norm(d0, axis=2)
        lb = np.linalg.norm(d1, axis=2)
        lc = np.linalg.norm(d2, axis=2)
        num = np.einsum("nij,nij->ni", d0, np.cross(d1, d2))
        den = (la * lb * lc
               + np.einsum("nij,nij->ni", d0, d1) * lc
               + np.einsum("nij,nij->ni", d1, d2) * la
               + np.einsum("nij,nij->ni", d2, d0) * lb)
        omega = 2.0 * np.arctan2(num, den)
        out[start:start + chunk] = np.abs(omega.sum(axis=1) / (4.0 * np.pi)) > 0.5
    return out


def thickness_samples(mesh: trimesh.Trimesh, face_indices: np.ndarray, *,
                      max_probes: int = 400, search_mm: float | None = None,
                      start_offset_mm: float = 1e-3,
                      confirm_depth_fraction: float = 0.25,
                      min_measurement_fraction: float = 0.008) -> dict[str, Any]:
    """Measure material thickness along the inward normal of ``face_indices``.

    A face whose inward normal is (nearly) tangential to a *neighbouring* surface reports the
    short distance to that neighbour instead of the local wall thickness - the cambered bed of
    a brick, or the wall of a drainage hole, is exactly such a face.  Each probe is therefore

    * rejected when its distance is below ``min_measurement_fraction`` of the mesh diagonal
      (a pinched sliver at a boolean junction, not a wall), and
    * confirmed with the signed solid-angle test at ``confirm_depth_fraction`` of its own
      measured distance, so only a probe whose interior is still material counts.

    Rejected probes are counted and reported; they are never averaged into the minimum.
    """
    md = to_manifold(mesh)
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    idx = np.asarray(face_indices, dtype=np.int64)
    if idx.size == 0:
        return {"n_valid": 0, "min_mm": float("nan"), "p05_mm": float("nan"),
                "median_mm": float("nan"), "max_mm": float("nan"),
                "max_probes": int(max_probes), "search_mm": None}
    idx = idx[_stride_indices(idx.size, int(max_probes))]
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    diag = float(np.linalg.norm(bounds[1] - bounds[0]))
    length = float(search_mm) if search_mm else diag * 1.05
    min_measurement_mm = float(min_measurement_fraction) * diag
    candidates: list[tuple[int, float, np.ndarray]] = []
    for i in idx:
        p = centroids[i]
        d = -normals[i]
        if not np.all(np.isfinite(d)) or float(np.linalg.norm(d)) < 0.5:
            continue
        origin = p + d * float(start_offset_mm)
        end = p + d * length
        hits = md.ray_cast(origin.tolist(), end.tolist())
        best = None
        for hit in hits:  # manifold returns hits sorted by distance
            hit_pos = np.asarray(hit.position, dtype=np.float64)
            dist = float(np.linalg.norm(hit_pos - p))
            if dist > 1e-4:
                best = dist
                break
        if best is not None and np.isfinite(best):
            candidates.append((int(i), float(best), d))
    confirmed: list[float] = []
    rejected = 0
    too_thin = 0
    survivors: list[tuple[int, float, np.ndarray]] = []
    for index, value, direction in candidates:
        if value < min_measurement_mm:
            # a folded or pinched sliver at a boolean junction produces a hit a fraction of a
            # millimetre away; it is reported as a rejected probe, not as a wall thickness
            too_thin += 1
            continue
        survivors.append((index, value, direction))
    if survivors:
        probes = np.asarray([centroids[i] + d * (float(confirm_depth_fraction) * v)
                             for i, v, d in survivors], dtype=np.float64)
        inside = _confirm_interior(mesh, probes)
        for (index, value, _direction), ok in zip(survivors, inside):
            if bool(ok):
                confirmed.append(value)
            else:
                rejected += 1
    arr = np.asarray(confirmed, dtype=np.float64)
    if arr.size == 0:
        return {"n_valid": 0, "min_mm": float("nan"), "p05_mm": float("nan"),
                "median_mm": float("nan"), "max_mm": float("nan"),
                "max_probes": int(max_probes), "search_mm": length,
                "probes_requested": int(idx.size), "confirmed": 0,
                "rejected_not_interior": int(rejected),
                "rejected_below_min_measurement": int(too_thin),
                "min_measurement_mm": float(min_measurement_mm),
                "note": "every probe sat on a face whose inward normal is tangential to a "
                        "neighbouring surface, so no wall thickness could be measured"}
    return {
        "n_valid": int(arr.size),
        "probes_requested": int(idx.size),
        "confirmed": int(arr.size),
        "rejected_not_interior": int(rejected),
        "rejected_below_min_measurement": int(too_thin),
        "min_measurement_mm": float(min_measurement_mm),
        "min_mm": float(arr.min()),
        "p05_mm": float(np.percentile(arr, 5)),
        "median_mm": float(np.median(arr)),
        "max_mm": float(arr.max()),
        "max_probes": int(max_probes),
        "confirm_depth_fraction": float(confirm_depth_fraction),
        "search_mm": length,
        "method": "Manifold ray cast along the inward normal, confirmed with the signed "
                  "solid-angle interior test; sub-millimetre junction slivers are rejected "
                  "and counted",
    }


def point_in_material(mesh: trimesh.Trimesh, points: np.ndarray, *,
                      search_mm: float | None = None) -> np.ndarray:
    """Exact inside/outside test per point (signed solid angle, all triangles).

    A ray-parity test is fragile precisely where the cavity probes sit: a grazing exit at
    a warped rim reverses the parity, and Manifold's ray cast truncates a ray whose start
    lies outside the bounding box.  The signed solid angle (winding number) of the closed,
    outward-oriented mesh does not have that failure mode: it is ``+1`` for a point in the
    material, ``0`` outside, and its magnitude alone reports how close the point is to a
    decision boundary.  ``search_mm`` is accepted for interface compatibility and ignored.
    """
    verts = np.ascontiguousarray(np.asarray(mesh.vertices, dtype=np.float64))
    faces = np.ascontiguousarray(np.asarray(mesh.faces, dtype=np.int64))
    pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
    if len(faces) == 0:
        raise ValueError("point_in_material needs a non-empty mesh")
    a = verts[faces[:, 0]]
    b = verts[faces[:, 1]]
    c = verts[faces[:, 2]]
    out = np.zeros(pts.shape[0], dtype=bool)
    for i, p in enumerate(pts):
        d0 = a - p
        d1 = b - p
        d2 = c - p
        la = np.linalg.norm(d0, axis=1)
        lb = np.linalg.norm(d1, axis=1)
        lc = np.linalg.norm(d2, axis=1)
        num = np.einsum("ij,ij->i", d0, np.cross(d1, d2))
        den = (la * lb * lc
               + np.einsum("ij,ij->i", d0, d1) * lc
               + np.einsum("ij,ij->i", d1, d2) * la
               + np.einsum("ij,ij->i", d2, d0) * lb)
        omega = 2.0 * np.arctan2(num, den)
        out[i] = bool(abs(float(omega.sum()) / (4.0 * np.pi)) > 0.5)
    return out
