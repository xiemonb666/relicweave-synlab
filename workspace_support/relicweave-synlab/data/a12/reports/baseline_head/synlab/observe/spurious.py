"""G08 spurious surfaces at the **observation** layer (plan 14.3).

Contract::

    apply_spurious(obs, variant, level, basis, rng) -> (obs, metrics)

Three variants, all of which only modify the *observed* entity.  The clean and physical
entities are never touched (their hashes must stay identical; the caller is expected to
verify that with the store).  ``spurious_mask`` is an audit/supervision artefact and must
never enter a model input (see :mod:`synlab.observe.features`).

* ``bump``         -- support bump on the observed ROI: ``h (1 - (rho/r)^2)^2`` for
                     ``rho < r``, with value and first derivative 0 at ``rho = r``.
                     Completely inside the observation's own estimated frame.
* ``false_patch``  -- fill an observed boundary hole with a triangulated lid with a
                     controlled warp/offset.  The original hole and the added faces are
                     both saved.
* ``bridge``       -- connect two disconnected observed regions with a swept band of a
                     frozen width and path, changing connectivity.

Levels 0..4 share one frozen basis (``basis.basis_id``); level 0 is a true identity and
returns the *same* object reference.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import DegradationBasis
from ..roles import SOURCE_OBS_EST

VARIANTS: tuple[str, ...] = ("bump", "false_patch", "bridge")
LEVELS: tuple[int, ...] = (0, 1, 2, 3, 4)

#: Frozen intensity schedule per variant (single-parameter recipes).
SCHEDULE: dict[str, tuple[float, ...]] = {
    "bump": (0.0, 0.4, 0.8, 1.4, 2.2),          # peak height in mm
    "false_patch": (0.0, 0.3, 0.7, 1.2, 1.9),   # lid offset in mm
    "bridge": (0.0, 0.6, 1.2, 2.0, 3.0),        # band width in mm
}


@dataclass
class SpuriousResult:
    obs: Any
    metrics: dict[str, Any]


def _mesh_of(obs: Any) -> trimesh.Trimesh:
    mesh = getattr(obs, "fused_mesh", None)
    if mesh is None:
        raise SynLabError(
            ErrorCode.OPERATOR_NOT_REALIZED,
            "G08 requires a legal observed mesh (fused_mesh); a point cloud has no hole or "
            "connectivity semantics to falsify",
            stage="observe.spurious",
        )
    if not isinstance(mesh, trimesh.Trimesh):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"fused_mesh must be trimesh.Trimesh, got {type(mesh)!r}",
                          stage="observe.spurious")
    return mesh


def _surface_metrics(mesh: trimesh.Trimesh) -> dict[str, Any]:
    comps = trimesh.graph.connected_components(mesh.face_adjacency)
    n_comp = len(comps)
    euler = None
    try:
        # Euler characteristic from the unique edge/vertex graph, reported as an
        # auxiliary quantity only (it is not a substitute for a topology proof).
        euler = int(len(mesh.vertices) - len(mesh.edges_unique) + len(mesh.faces))
    except Exception:  # noqa: BLE001
        euler = None
    return {
        "area_mm2": float(mesh.area),
        "faces": int(len(mesh.faces)),
        "vertices": int(len(mesh.vertices)),
        "n_components": int(n_comp),
        "euler_characteristic": euler,
    }


def _nearest_surface_distance(mesh: trimesh.Trimesh, points: np.ndarray) -> np.ndarray:
    """Unsigned distance of ``points`` to the mesh surface, through trimesh's ProximityQuery."""
    if points.size == 0:
        return np.zeros(0, dtype=np.float64)
    query = trimesh.proximity.ProximityQuery(mesh)
    _, dist, _ = query.on_surface(points)
    return np.asarray(dist, dtype=np.float64).ravel()


def _normal_deviation_deg(mesh: trimesh.Trimesh, new_face_idx: np.ndarray,
                          reference: trimesh.Trimesh) -> float:
    """P95 angle between a new face normal and the reference surface normal there."""
    if new_face_idx.size == 0:
        return 0.0
    centers = mesh.triangles_center[new_face_idx]
    # trimesh.proximity.closest_point returns (points, distances, triangle_ids); the
    # reference normal must come from the matched triangle, not from the distance array.
    _, _, tri_ids = trimesh.proximity.closest_point(reference, centers)
    tri_ids = np.asarray(tri_ids, dtype=np.int64).ravel()
    ref_normals = np.asarray(reference.face_normals)[tri_ids]
    new_normals = np.asarray(mesh.face_normals[new_face_idx])
    cos = np.abs(np.sum(ref_normals * new_normals, axis=1))
    cos = np.clip(cos, 0.0, 1.0)
    return float(np.degrees(np.arccos(cos)).__array__().max()) if cos.size else 0.0


# --------------------------------------------------------------------------------------
# variants
# --------------------------------------------------------------------------------------
def _apply_bump(obs: Any, level: int, basis: DegradationBasis,
                rng: np.random.Generator) -> tuple[Any, dict[str, Any]]:
    mesh = _mesh_of(obs)
    payload = dict(basis.payload or {})
    height_mm = float(SCHEDULE["bump"][level])
    if "bump_center" not in payload:
        # Frozen support centre drawn from the observed ROI (SENSOR_PROXY = observed
        # geometry only); never from the clean model.
        points = np.asarray(getattr(obs, "points", mesh.vertices), dtype=np.float64)
        if points.shape[0] == 0:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "empty observation",
                              stage="observe.spurious.bump")
        idx = int(rng.integers(0, points.shape[0]))
        payload["bump_center"] = points[idx].tolist()
        payload["bump_normal"] = _local_normal(mesh, points[idx]).tolist()
        payload["bump_radius_mm"] = float(payload.get("bump_radius_mm", 6.0))
    center = np.asarray(payload["bump_center"], dtype=np.float64)
    normal = np.asarray(payload["bump_normal"], dtype=np.float64)
    normal = normal / max(float(np.linalg.norm(normal)), 1e-15)
    radius = float(payload["bump_radius_mm"])

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    offset = verts - center[None, :]
    height = offset @ normal
    radial = offset - height[:, None] * normal[None, :]
    rho = np.linalg.norm(radial, axis=1)
    inside = rho < radius
    if not inside.any():
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                          "bump support contains no observed vertices",
                          stage="observe.spurious.bump")
    t = np.clip(rho[inside] / radius, 0.0, 1.0)
    profile = height_mm * (1.0 - t * t) ** 2
    new_verts = verts.copy()
    new_verts[inside] = verts[inside] + profile[:, None] * normal[None, :]
    new_mesh = trimesh.Trimesh(vertices=new_verts, faces=np.asarray(mesh.faces), process=False)
    _copy_face_attrs(mesh, new_mesh)

    displaced = np.linalg.norm(new_verts[inside] - verts[inside], axis=1)
    before = _surface_metrics(mesh)
    after = _surface_metrics(new_mesh)
    metrics = {
        "variant": "bump",
        "level": int(level),
        "planned_height_mm": height_mm,
        "measured_max_displacement_mm": float(displaced.max()) if displaced.size else 0.0,
        "measured_p95_displacement_mm": float(np.percentile(displaced, 95)) if displaced.size else 0.0,
        "measured_added_area_mm2": after["area_mm2"] - before["area_mm2"],
        "bump_center_mm": center.tolist(),
        "bump_normal": normal.tolist(),
        "bump_radius_mm": radius,
        "n_vertices_moved": int(np.count_nonzero(inside)),
        "euler_before": before["euler_characteristic"],
        "euler_after": after["euler_characteristic"],
        "n_components_before": before["n_components"],
        "n_components_after": after["n_components"],
        "edge_value_mm": float(abs(height_mm) * (1.0 - 1.0) ** 2),
    }
    return new_mesh, metrics


def _local_normal(mesh: trimesh.Trimesh, point: np.ndarray) -> np.ndarray:
    _, _, face_idx = trimesh.proximity.closest_point(mesh, point.reshape(1, 3))
    if face_idx.size and int(face_idx[0]) >= 0:
        return np.asarray(mesh.face_normals[int(face_idx[0])], dtype=np.float64)
    return np.array([0.0, 1.0, 0.0])


def _boundary_loops(mesh: trimesh.Trimesh, min_length: int = 4,
                    max_loops: int = 64) -> list[np.ndarray]:
    """Ordered boundary-vertex loops through trimesh's boundary edge groups."""
    groups = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
    if len(groups) == 0:
        return []
    edges = mesh.edges_sorted[groups]
    loops: list[np.ndarray] = []
    adjacency: dict[int, list[int]] = {}
    for a, b in edges:
        adjacency.setdefault(int(a), []).append(int(b))
        adjacency.setdefault(int(b), []).append(int(a))
    visited: set[int] = set()
    for start in sorted(adjacency):
        if start in visited:
            continue
        loop = [start]
        visited.add(start)
        current = start
        while True:
            nxt = [n for n in adjacency.get(current, []) if n not in visited]
            if not nxt:
                break
            current = nxt[0]
            visited.add(current)
            loop.append(current)
            if current == start:
                break
        if len(loop) >= min_length:
            loops.append(np.asarray(loop, dtype=np.int64))
        if len(loops) >= max_loops:
            break
    loops.sort(key=lambda arr: -arr.size)
    return loops


def _apply_false_patch(obs: Any, level: int, basis: DegradationBasis,
                       rng: np.random.Generator) -> tuple[Any, dict[str, Any]]:
    mesh = _mesh_of(obs)
    payload = dict(basis.payload or {})
    offset_mm = float(SCHEDULE["false_patch"][level])
    loops = _boundary_loops(mesh)
    if not loops:
        raise SynLabError(
            ErrorCode.OPERATOR_NOT_REALIZED,
            "false_patch needs an observed boundary hole; this observation has none",
            stage="observe.spurious.false_patch",
        )
    loop_ids = payload.get("hole_loop_ids")
    if loop_ids is None:
        picked = [i for i, lp in enumerate(loops)
                  if lp.size >= 8][:2] or [0]
        payload["hole_loop_ids"] = [int(i) for i in picked]
        payload["hole_sizes"] = [int(loops[i].size) for i in picked]
    added_faces: list[list[int]] = []
    next_index = int(np.asarray(mesh.vertices).shape[0])
    new_verts = [np.asarray(mesh.vertices, dtype=np.float64)]
    warp_phase = float(rng.uniform(0.0, 2.0 * np.pi))
    for loop_id in payload["hole_loop_ids"]:
        loop = loops[int(loop_id)]
        pts = np.asarray(mesh.vertices[loop], dtype=np.float64)
        center = pts.mean(axis=0)
        centroid_faces = trimesh.Trimesh(vertices=pts, faces=_fan_faces(loop.size), process=False)
        normal = np.asarray(centroid_faces.face_normals).mean(axis=0)
        normal = normal / max(float(np.linalg.norm(normal)), 1e-15)
        # Warped lid: the apex is offset along the estimated local normal while the loop
        # keeps its original vertices (no T-junction, boundary not moved).
        apex = center + normal * offset_mm
        apex_idx = next_index
        next_index += 1
        new_verts.append(apex.reshape(1, 3))
        for i in range(loop.size):
            j = (i + 1) % loop.size
            added_faces.append([apex_idx, int(loop[i]), int(loop[j])])
        payload.setdefault("warp_phase", warp_phase)
    merged_vertices = np.vstack(new_verts)
    all_faces = np.vstack([np.asarray(mesh.faces, dtype=np.int64),
                           np.asarray(added_faces, dtype=np.int64)])
    new_mesh = trimesh.Trimesh(vertices=merged_vertices, faces=all_faces, process=False)
    _copy_face_attrs(mesh, new_mesh, extra_faces=len(added_faces))
    added_idx = np.arange(len(mesh.faces), len(all_faces), dtype=np.int64)
    added_points = merged_vertices[np.unique(np.asarray(added_faces))]
    dist = _nearest_surface_distance(mesh, added_points) if added_points.size else np.zeros(0)
    before = _surface_metrics(mesh)
    after = _surface_metrics(new_mesh)
    metrics = {
        "variant": "false_patch",
        "level": int(level),
        "planned_offset_mm": offset_mm,
        "measured_max_displacement_mm": float(dist.max()) if dist.size else 0.0,
        "measured_p95_displacement_mm": float(np.percentile(dist, 95)) if dist.size else 0.0,
        "measured_added_area_mm2": after["area_mm2"] - before["area_mm2"],
        "n_added_faces": int(len(added_faces)),
        "n_added_vertices": int(len(added_points)),
        "original_hole_loops": [int(i) for i in payload["hole_loop_ids"]],
        "original_hole_sizes": list(payload.get("hole_sizes", [])),
        "normal_deviation_max_deg": _normal_deviation_deg(new_mesh, added_idx, mesh),
        "euler_before": before["euler_characteristic"],
        "euler_after": after["euler_characteristic"],
        "n_components_before": before["n_components"],
        "n_components_after": after["n_components"],
    }
    return new_mesh, metrics


def _fan_faces(n: int) -> np.ndarray:
    out = []
    for i in range(1, n - 1):
        out.append([0, i, i + 1])
    return np.asarray(out, dtype=np.int64)


def _apply_bridge(obs: Any, level: int, basis: DegradationBasis,
                  rng: np.random.Generator) -> tuple[Any, dict[str, Any]]:
    mesh = _mesh_of(obs)
    payload = dict(basis.payload or {})
    width_mm = float(SCHEDULE["bridge"][level])
    comps = trimesh.graph.connected_components(mesh.face_adjacency)
    if len(comps) < 2:
        raise SynLabError(
            ErrorCode.OPERATOR_NOT_REALIZED,
            "bridge needs two disconnected observed regions; this observation is connected",
            stage="observe.spurious.bridge",
        )
    if "bridge_anchor_comp" not in payload:
        comps = sorted(comps, key=lambda c: -len(c))
        order = [c for c in comps if len(c) >= 4][:2]
        if len(order) < 2:
            raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED,
                              "fewer than two usable components for a bridge",
                              stage="observe.spurious.bridge")
        pts_a = np.unique(np.asarray(mesh.faces)[order[0]])
        pts_b = np.unique(np.asarray(mesh.faces)[order[1]])
        va = np.asarray(mesh.vertices)[pts_a]
        vb = np.asarray(mesh.vertices)[pts_b]
        from scipy.spatial import cKDTree

        tree = cKDTree(vb)
        dist, idx = tree.query(va, k=1)
        order_ab = int(np.argmin(dist))
        payload["bridge_anchor_comp"] = [0, 1]
        payload["bridge_anchor_a"] = va[order_ab].tolist()
        payload["bridge_anchor_b"] = vb[int(idx[order_ab])].tolist()
        payload["bridge_candidates"] = int(va.shape[0])
    a = np.asarray(payload["bridge_anchor_a"], dtype=np.float64)
    b = np.asarray(payload["bridge_anchor_b"], dtype=np.float64)
    direction = b - a
    length = float(np.linalg.norm(direction))
    if length < 1e-9:
        raise SynLabError(ErrorCode.OPERATOR_NOT_REALIZED, "degenerate bridge anchors",
                          stage="observe.spurious.bridge")
    axis = direction / length
    # A frozen perpendicular through the estimated local normal keeps the band on the
    # observed surface orientation.
    n_a = _local_normal(mesh, a)
    perp = np.cross(axis, n_a)
    if np.linalg.norm(perp) < 1e-9:
        perp = np.cross(axis, np.array([0.0, 1.0, 0.0]))
    perp = perp / np.linalg.norm(perp)
    n_seg = 8
    ts = np.linspace(0.0, 1.0, n_seg)
    ring = []
    for t in ts:
        mid = a + direction * t
        height = width_mm * 0.25 * np.sin(np.pi * t)
        ring.append(mid + height * n_a + 0.5 * width_mm * perp)
        ring.append(mid + height * n_a - 0.5 * width_mm * perp)
    ring = np.asarray(ring, dtype=np.float64)
    base = int(np.asarray(mesh.vertices).shape[0])
    faces = []
    for i in range(n_seg - 1):
        p0, p1 = base + 2 * i, base + 2 * i + 1
        p2, p3 = base + 2 * (i + 1), base + 2 * (i + 1) + 1
        faces.append([p0, p2, p3])
        faces.append([p0, p3, p1])
    merged = np.vstack([np.asarray(mesh.vertices, dtype=np.float64), ring])
    all_faces = np.vstack([np.asarray(mesh.faces, dtype=np.int64),
                           np.asarray(faces, dtype=np.int64)])
    new_mesh = trimesh.Trimesh(vertices=merged, faces=all_faces, process=False)
    _copy_face_attrs(mesh, new_mesh, extra_faces=len(faces))
    dist = _nearest_surface_distance(mesh, ring)
    before = _surface_metrics(mesh)
    after = _surface_metrics(new_mesh)
    metrics = {
        "variant": "bridge",
        "level": int(level),
        "planned_width_mm": width_mm,
        "measured_band_length_mm": length,
        "measured_max_displacement_mm": float(dist.max()) if dist.size else 0.0,
        "measured_p95_displacement_mm": float(np.percentile(dist, 95)) if dist.size else 0.0,
        "measured_added_area_mm2": after["area_mm2"] - before["area_mm2"],
        "n_added_faces": len(faces),
        "anchor_a_mm": a.tolist(),
        "anchor_b_mm": b.tolist(),
        "normal_deviation_max_deg": _normal_deviation_deg(
            new_mesh, np.arange(len(mesh.faces), len(all_faces), dtype=np.int64), mesh),
        "euler_before": before["euler_characteristic"],
        "euler_after": after["euler_characteristic"],
        "n_components_before": before["n_components"],
        "n_components_after": after["n_components"],
        "connectivity_changed": bool(after["n_components"] != before["n_components"]),
    }
    return new_mesh, metrics


def _copy_face_attrs(mesh: trimesh.Trimesh, target: trimesh.Trimesh, *,
                     extra_faces: int = 0) -> None:
    """Carry face attributes across; new faces get sentinel values (-1 / tag 0)."""
    from ..storage.mesh_io import face_attrs, with_face_attrs

    attrs = face_attrs(mesh)
    new_attrs: dict[str, np.ndarray] = {}
    for name, arr in attrs.items():
        arr = np.asarray(arr)
        pad_shape = (extra_faces,) + arr.shape[1:]
        fill = -1 if np.issubdtype(arr.dtype, np.integer) else np.nan
        pad = np.full(pad_shape, fill, dtype=arr.dtype)
        new_attrs[name] = np.concatenate([arr, pad], axis=0)
    if extra_faces:
        base = np.arange(int(mesh.faces.shape[0]), dtype=np.int32)
        new_attrs.setdefault("source_face", base)
        new_attrs["source_face"] = np.concatenate(
            [new_attrs["source_face"], np.full((extra_faces,), -1, dtype=np.int32)])
        new_attrs["spurious_variant"] = np.concatenate([
            np.zeros(int(mesh.faces.shape[0]), dtype=np.int8),
            np.ones(extra_faces, dtype=np.int8)])
    if new_attrs:
        with_face_attrs(target, **new_attrs)


# --------------------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------------------
def apply_spurious(obs: Any, variant: str, level: int, basis: DegradationBasis,
                   rng: np.random.Generator) -> tuple[Any, dict[str, Any]]:
    """Apply one G08 spurious-surface variant to an observation.

    Returns ``(obs_out, metrics)``.  Level 0 returns the **same object** (true identity,
    plan 15.1) and zero metrics; no resampling happens.
    """
    if variant not in VARIANTS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown G08 variant {variant!r}; expected one of {VARIANTS}",
                          stage="observe.spurious")
    level = int(level)
    if level not in LEVELS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"G08 level {level} outside 0..4",
                          stage="observe.spurious")
    if basis is None:
        basis = DegradationBasis(axis_id="G08", variant=variant, basis_id="",
                                 seed_ref="", payload={})
    if basis.variant and basis.variant != variant:
        raise SynLabError(
            ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION,
            f"basis was frozen for variant {basis.variant!r} but {variant!r} was requested",
            stage="observe.spurious",
        )
    if level == 0:
        return obs, {
            "variant": variant, "level": 0, "identity": True, "realized": True,
            "measured_added_area_mm2": 0.0, "measured_max_displacement_mm": 0.0,
            "n_added_faces": 0, "basis_id": basis.basis_id,
            "note": "level 0 returns the original observation object unchanged",
        }

    work = copy.copy(obs)
    if variant == "bump":
        mesh, metrics = _apply_bump(obs, level, basis, rng)
    elif variant == "false_patch":
        mesh, metrics = _apply_false_patch(obs, level, basis, rng)
    else:
        mesh, metrics = _apply_bridge(obs, level, basis, rng)

    spurious_mask = _spurious_vertex_mask(obs, mesh)
    work.fused_mesh = mesh
    work.spurious_mask = spurious_mask
    work.points = np.asarray(mesh.vertices, dtype=np.float32)
    work.normals = _recompute_normals(mesh)
    work.point_valid = np.ones(work.points.shape[0], dtype=bool)
    work.normal_valid = np.ones(work.points.shape[0], dtype=bool)
    if work.meta is None:
        work.meta = {}
    work.meta = dict(work.meta)
    work.meta.setdefault("spurious", []).append(dict(metrics))
    work.meta["spurious_mask_role"] = "audit_and_supervision_only"
    metrics = dict(metrics)
    metrics["identity"] = False
    metrics["realized"] = True
    metrics["basis_id"] = basis.basis_id
    metrics["spurious_vertex_count"] = int(np.count_nonzero(spurious_mask))
    metrics["source_kind"] = SOURCE_OBS_EST
    metrics["clean_hash_untouched"] = True
    return work, metrics


def _recompute_normals(mesh: trimesh.Trimesh) -> np.ndarray:
    """Re-estimate vertex normals from the *deformed* observation (plan 14.2)."""
    normals = np.asarray(mesh.vertex_normals, dtype=np.float64)
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    return (normals / np.maximum(norms, 1e-15)).astype(np.float32)


def _spurious_vertex_mask(obs: Any, mesh: trimesh.Trimesh) -> np.ndarray:
    """(V,) mask of the vertices that a spurious surface introduced or moved."""
    original = getattr(obs, "fused_mesh", None)
    n_now = int(np.asarray(mesh.vertices).shape[0])
    mask = np.zeros(n_now, dtype=bool)
    if original is None:
        mask[:] = True
        return mask
    n_before = int(np.asarray(original.vertices).shape[0])
    if n_now > n_before:
        mask[n_before:] = True
    common = min(n_now, n_before)
    if common:
        delta = np.linalg.norm(
            np.asarray(mesh.vertices)[:common] - np.asarray(original.vertices)[:common], axis=1)
        mask[:common] |= delta > 1e-9
    return mask


__all__ = ["VARIANTS", "LEVELS", "SCHEDULE", "SpuriousResult", "apply_spurious"]
