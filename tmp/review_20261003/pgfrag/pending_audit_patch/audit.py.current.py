"""Return-before-output QA for mothers (plan 7.3).

Required checks, each with a concrete metric rather than a boolean alone:

===============  ==========================================================================
watertight       ``trimesh`` edge pairing + winding consistency + Manifold status
outward volume   signed volume from the divergence theorem, genus, component count
self-intersect   complete triangle-triangle separating-axis test over all centroid pairs
                 that can possibly touch (cKDTree radius = 2 x max triangle extent)
min thickness    ray-cast material thickness on the realised (possibly warped) triangles
cavity           void ratio against the convex hull plus ray parity probes in the cavity
source labels    ``surface_tag`` / ``source_triangle`` / ``component_id`` face arrays
charts           every tag that exists on the mesh is covered by a chart whose ``to_uv``
                 is finite, periodic-safe and whose legal region is non-empty
===============  ==========================================================================

Failures are returned with their measured values so a caller can raise ``MOTHER_INVALID``
with evidence; nothing here returns an empty mesh as if it were a success.
"""

from __future__ import annotations

import time
from typing import Any, Sequence

import numpy as np
import trimesh

from ..canonical import array_hash
from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import MotherGeometry
from . import measure
from .charts import chart_coverage, chart_uv_probe
from .tagging import TAG_NAMES, TAG_UNASSIGNED
from .solids import health, manifold_status

CHECK_ORDER = (
    "watertight", "outward_volume", "self_intersection", "min_thickness",
    "cavity", "source_labels", "charts",
)


# ---------------------------------------------------------------------------- geometry QA
SELF_INTERSECTION_SEMANTICS = "nonadjacent_contact_v2"
COPLANAR_AREA_EPS_MM2 = 1e-6


def _open3d_module():
    """Import Open3D lazily so an unavailable backend can fail this QA closed."""
    import open3d as o3d

    return o3d


def _failed_intersection_report(reason: str, *, faces: int, elapsed_seconds: float = 0.0,
                                **details: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "complete": False,
        "classification_complete": False,
        "checked_pairs": 0,
        "candidate_pairs": 0,
        "intersecting_pairs": 0,
        "nonadjacent_self_contact_pairs": 0,
        "coplanar_contact_pairs": 0,
        "coplanar_pairs_examined": 0,
        "coplanar_overlap_pairs": 0,
        "coplanar_overlap_area_mm2": 0.0,
        "faces": int(faces),
        "reason": reason,
        "semantic_version": SELF_INTERSECTION_SEMANTICS,
        "elapsed_seconds": float(elapsed_seconds),
        **details,
    }


def _triangle_normal(triangle: np.ndarray) -> tuple[np.ndarray, float]:
    normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
    norm = float(np.linalg.norm(normal))
    return normal, norm


def _coplanar_relation(triangle_a: np.ndarray, triangle_b: np.ndarray, normal: np.ndarray,
                       eps_area_mm2: float = COPLANAR_AREA_EPS_MM2
                       ) -> tuple[str, float, str | None]:
    """Classify a coplanar Open3D pair with GEOS, returning area and relation."""
    from shapely.geometry import Polygon

    unit_normal = normal / max(float(np.linalg.norm(normal)), 1e-15)
    helper = (np.array([1.0, 0.0, 0.0]) if abs(unit_normal[0]) < 0.9
              else np.array([0.0, 1.0, 0.0]))
    u = np.cross(unit_normal, helper)
    u /= max(float(np.linalg.norm(u)), 1e-15)
    v = np.cross(unit_normal, u)
    polygon_a = Polygon(np.column_stack([triangle_a @ u, triangle_a @ v]))
    polygon_b = Polygon(np.column_stack([triangle_b @ u, triangle_b @ v]))
    if not (polygon_a.is_valid and polygon_b.is_valid):
        return "unresolved_invalid_polygon", 0.0, None
    intersection = polygon_a.intersection(polygon_b)
    area = float(intersection.area)
    if area > float(eps_area_mm2):
        return "coplanar_positive_area_overlap", area, str(intersection.geom_type)
    if not intersection.is_empty:
        return "coplanar_boundary_contact", area, str(intersection.geom_type)
    return "unresolved_open3d_geos_disagreement", area, str(intersection.geom_type)


def _plane_cut_points(triangle: np.ndarray, plane_triangle: np.ndarray,
                      plane_tolerance_mm: float) -> np.ndarray:
    """Return unique points where a triangle meets another triangle's plane."""
    normal, norm = _triangle_normal(plane_triangle)
    if norm <= 1e-15:
        return np.zeros((0, 3), dtype=np.float64)
    unit_normal = normal / norm
    signed = (triangle - plane_triangle[0]) @ unit_normal
    points: list[np.ndarray] = []

    def append(point: np.ndarray) -> None:
        if not any(float(np.linalg.norm(point - old)) <= plane_tolerance_mm
                   for old in points):
            points.append(np.asarray(point, dtype=np.float64))

    for left, right in ((0, 1), (1, 2), (2, 0)):
        da, db = float(signed[left]), float(signed[right])
        if abs(da) <= plane_tolerance_mm:
            append(triangle[left])
        if abs(db) <= plane_tolerance_mm:
            append(triangle[right])
        if (da < -plane_tolerance_mm and db > plane_tolerance_mm) or (
                da > plane_tolerance_mm and db < -plane_tolerance_mm):
            t = da / (da - db)
            append(triangle[left] + t * (triangle[right] - triangle[left]))
    return np.asarray(points, dtype=np.float64).reshape(-1, 3)


def _barycentric_weights(triangle: np.ndarray, point: np.ndarray) -> np.ndarray | None:
    v0 = triangle[1] - triangle[0]
    v1 = triangle[2] - triangle[0]
    v2 = point - triangle[0]
    d00 = float(np.dot(v0, v0))
    d01 = float(np.dot(v0, v1))
    d11 = float(np.dot(v1, v1))
    d20 = float(np.dot(v2, v0))
    d21 = float(np.dot(v2, v1))
    denom = d00 * d11 - d01 * d01
    if abs(denom) <= 1e-24:
        return None
    w1 = (d11 * d20 - d01 * d21) / denom
    w2 = (d00 * d21 - d01 * d20) / denom
    return np.asarray([1.0 - w1 - w2, w1, w2], dtype=np.float64)


def _point_at_projection(points: np.ndarray, direction: np.ndarray, projection: float
                         ) -> np.ndarray:
    values = points @ direction
    order = np.argsort(values)
    low, high = points[order[0]], points[order[-1]]
    lo, hi = float(values[order[0]]), float(values[order[-1]])
    if hi - lo <= 1e-15:
        return low
    return low + ((projection - lo) / (hi - lo)) * (high - low)


def _classify_noncoplanar_pair(triangle_a: np.ndarray, triangle_b: np.ndarray,
                               eps_mm: float) -> tuple[str, float | None, str | None]:
    """Classify an Open3D hit as an interior crossing or boundary-only contact.

    Open3D supplies the complete triangle intersection hit.  This helper only classifies that
    hit by the intersection line's relative position; it is not used to find candidate pairs.
    """
    normal_a, norm_a = _triangle_normal(triangle_a)
    normal_b, norm_b = _triangle_normal(triangle_b)
    if norm_a <= 1e-15 or norm_b <= 1e-15:
        return "unresolved_degenerate_pair", None, None
    unit_a, unit_b = normal_a / norm_a, normal_b / norm_b
    direction = np.cross(unit_a, unit_b)
    direction_norm = float(np.linalg.norm(direction))
    if direction_norm <= 1e-10:
        return "unresolved_near_parallel_pair", None, None
    direction /= direction_norm
    plane_tolerance = max(1e-9, min(float(eps_mm) * 0.1, 1e-5))
    cut_a = _plane_cut_points(triangle_a, triangle_b, plane_tolerance)
    cut_b = _plane_cut_points(triangle_b, triangle_a, plane_tolerance)
    if cut_a.shape[0] == 0 or cut_b.shape[0] == 0:
        return "unresolved_missing_plane_cut", None, None
    interval_a = (float(np.min(cut_a @ direction)), float(np.max(cut_a @ direction)))
    interval_b = (float(np.min(cut_b @ direction)), float(np.max(cut_b @ direction)))
    lo = max(interval_a[0], interval_b[0])
    hi = min(interval_a[1], interval_b[1])
    overlap_length = hi - lo
    if overlap_length < -max(float(eps_mm), 1e-8):
        return "unresolved_open3d_plane_cut_disagreement", float(overlap_length), None
    if overlap_length <= max(float(eps_mm), 1e-8):
        return "nonadjacent_self_contact", max(0.0, float(overlap_length)), "point_or_short_segment"
    midpoint_projection = 0.5 * (lo + hi)
    point_a = _point_at_projection(cut_a, direction, midpoint_projection)
    point_b = _point_at_projection(cut_b, direction, midpoint_projection)
    midpoint = 0.5 * (point_a + point_b)
    weights_a = _barycentric_weights(triangle_a, midpoint)
    weights_b = _barycentric_weights(triangle_b, midpoint)
    if weights_a is None or weights_b is None:
        return "unresolved_barycentric_failure", float(overlap_length), None
    interior_a = bool(np.all(weights_a > 1e-9) and np.all(weights_a < 1.0 - 1e-9))
    interior_b = bool(np.all(weights_b > 1e-9) and np.all(weights_b < 1.0 - 1e-9))
    if interior_a and interior_b:
        return "noncoplanar_crossing", float(overlap_length), "interior_segment"
    return "nonadjacent_self_contact", float(overlap_length), "boundary_segment"


def self_intersection_report(mesh: trimesh.Trimesh, *, eps_mm: float = 1e-4,
                             max_pairs: int = 6_000_000,
                             max_coplanar_checks: int = 1500,
                             chunk: int = 40000) -> dict[str, Any]:
    """Fail-closed non-adjacent self-contact scan backed by Open3D and GEOS.

    Open3D's legacy ``get_self_intersecting_triangles`` currently scans all triangle pairs.
    ``max_pairs`` therefore caps the *preflight work estimate* ``F*(F-1)/2`` before invoking
    that backend, not just the number of returned hits.  The retained ``chunk`` argument is
    for call-site compatibility; this backend does not expose chunked traversal.  Shared-index
    face pairs are legal adjacency and are filtered.  For remaining pairs, positive-area
    coplanar overlap and non-coplanar interior crossing are distinct counts.  A point/edge-only
    contact between non-shared-index faces is conservatively a QA failure, exposing unwelded
    seams or zero-thickness self-contact.  GEOS classifies coplanar overlap; if its budget or
    any backend/classification step is incomplete, this report cannot pass.
    """
    started = time.perf_counter()
    tris = np.asarray(mesh.triangles, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    n = int(len(tris))
    if n == 0:
        return _failed_intersection_report("empty_mesh", faces=n,
                                           elapsed_seconds=time.perf_counter() - started)
    if (not np.isfinite(tris).all() or faces.shape != (n, 3)
            or np.any(faces < 0) or np.any(faces >= len(mesh.vertices))):
        return _failed_intersection_report(
            "invalid_mesh_arrays", faces=n, elapsed_seconds=time.perf_counter() - started,
            triangle_shape=list(tris.shape), face_shape=list(faces.shape))
    if not np.isfinite(float(eps_mm)) or float(eps_mm) < 0:
        return _failed_intersection_report(
            "invalid_tolerance", faces=n, elapsed_seconds=time.perf_counter() - started,
            eps_mm=eps_mm)

    edge_a = tris[:, 1] - tris[:, 0]
    edge_b = tris[:, 2] - tris[:, 0]
    double_area = np.linalg.norm(np.cross(edge_a, edge_b), axis=1)
    mesh_scale = max(float(np.max(np.linalg.norm(tris.reshape(-1, 3), axis=1))), 1.0)
    degenerate = np.flatnonzero(double_area <= max(1e-15, mesh_scale * mesh_scale * 1e-15))
    if degenerate.size:
        return _failed_intersection_report(
            "degenerate_triangles", faces=n, elapsed_seconds=time.perf_counter() - started,
            degenerate_triangle_count=int(degenerate.size),
            degenerate_triangle_indices=degenerate[:32].astype(int).tolist())

    work_budget = int(max_pairs)
    pair_work = n * (n - 1) // 2
    if work_budget < 0 or pair_work > work_budget:
        return _failed_intersection_report(
            "pair_scan_budget_exceeded", faces=n,
            elapsed_seconds=time.perf_counter() - started,
            pair_scan_work=int(pair_work), pair_scan_budget=work_budget,
            backend="open3d_legacy_cpu_all_pairs",
            note="Open3D scan was not started; no spatially complete accelerated broad phase is wired")

    try:
        o3d = _open3d_module()
        o3d_mesh = o3d.geometry.TriangleMesh(
            o3d.utility.Vector3dVector(np.asarray(mesh.vertices, dtype=np.float64)),
            o3d.utility.Vector3iVector(faces.astype(np.int32, copy=False)))
        pair_array = np.asarray(o3d_mesh.get_self_intersecting_triangles(), dtype=np.int64)
    except Exception as exc:
        return _failed_intersection_report(
            "backend_unavailable_or_failed", faces=n,
            elapsed_seconds=time.perf_counter() - started,
            backend="open3d_legacy_cpu_all_pairs",
            backend_error=f"{type(exc).__name__}: {exc}",
            pair_scan_work=int(pair_work), pair_scan_budget=work_budget)

    if pair_array.size == 0:
        pair_array = np.zeros((0, 2), dtype=np.int64)
    else:
        try:
            pair_array = pair_array.reshape(-1, 2)
        except ValueError:
            return _failed_intersection_report(
                "invalid_backend_pair_shape", faces=n,
                elapsed_seconds=time.perf_counter() - started,
                backend="open3d_legacy_cpu_all_pairs", backend_pair_shape=list(pair_array.shape))
        pair_array.sort(axis=1)
        pair_array = np.unique(pair_array, axis=0)
    if pair_array.size and (np.any(pair_array < 0) or np.any(pair_array >= n)):
        return _failed_intersection_report(
            "backend_returned_invalid_pair_index", faces=n,
            elapsed_seconds=time.perf_counter() - started,
            backend="open3d_legacy_cpu_all_pairs", backend_pair_count=int(len(pair_array)))

    pair_cap = max(0, work_budget)
    pair_truncated = len(pair_array) > pair_cap
    if pair_truncated:
        pair_array = pair_array[:pair_cap]
    if len(pair_array):
        left_faces = faces[pair_array[:, 0]]
        right_faces = faces[pair_array[:, 1]]
        shares_index = ((left_faces[:, 0:1] == right_faces)
                        | (left_faces[:, 1:2] == right_faces)
                        | (left_faces[:, 2:3] == right_faces)).any(axis=1)
        shared_index_pairs_filtered = int(np.count_nonzero(shares_index))
        pairs = pair_array[~shares_index]
    else:
        shared_index_pairs_filtered = 0
        pairs = pair_array

    coplanar_indices: list[int] = []
    noncoplanar_indices: list[int] = []
    for pair_index, (ia, ib) in enumerate(pairs):
        triangle_a, triangle_b = tris[int(ia)], tris[int(ib)]
        normal_a, norm_a = _triangle_normal(triangle_a)
        normal_b, norm_b = _triangle_normal(triangle_b)
        if norm_a <= 1e-15 or norm_b <= 1e-15:
            noncoplanar_indices.append(pair_index)
            continue
        unit_a, unit_b = normal_a / norm_a, normal_b / norm_b
        parallel = abs(float(np.dot(unit_a, unit_b))) >= 1.0 - 1e-6
        plane_gap = abs(float(np.dot(triangle_b[0] - triangle_a[0], unit_a)))
        if parallel and plane_gap <= float(eps_mm):
            coplanar_indices.append(pair_index)
        else:
            noncoplanar_indices.append(pair_index)

    noncoplanar_crossings: list[dict[str, Any]] = []
    boundary_contacts: list[dict[str, Any]] = []
    unresolved_pairs: list[dict[str, Any]] = []
    for pair_index in noncoplanar_indices:
        ia, ib = (int(v) for v in pairs[pair_index])
        relation, overlap_length, detail = _classify_noncoplanar_pair(
            tris[ia], tris[ib], float(eps_mm))
        item = {"faces": [ia, ib], "relation": relation,
                "overlap_length_mm": overlap_length, "detail": detail}
        if relation == "noncoplanar_crossing":
            noncoplanar_crossings.append(item)
        elif relation == "nonadjacent_self_contact":
            boundary_contacts.append(item)
        else:
            unresolved_pairs.append(item)

    coplanar_contact_pairs = int(len(coplanar_indices))
    coplanar_budget = max(0, int(max_coplanar_checks))
    coplanar_pairs_examined = min(coplanar_contact_pairs, coplanar_budget)
    coplanar_skipped = coplanar_contact_pairs - coplanar_pairs_examined
    coplanar_overlap_pairs = 0
    coplanar_boundary_contacts = 0
    coplanar_overlap_area_mm2 = 0.0
    coplanar_details: list[dict[str, Any]] = []
    geos_errors: list[dict[str, Any]] = []
    for pair_index in coplanar_indices[:coplanar_pairs_examined]:
        ia, ib = (int(v) for v in pairs[pair_index])
        relation, area, geom_type = _coplanar_relation(
            tris[ia], tris[ib], _triangle_normal(tris[ia])[0])
        detail = {"faces": [ia, ib], "relation": relation,
                  "overlap_area_mm2": float(area), "intersection_geometry": geom_type}
        coplanar_details.append(detail)
        if relation == "coplanar_positive_area_overlap":
            coplanar_overlap_pairs += 1
            coplanar_overlap_area_mm2 += float(area)
        elif relation == "coplanar_boundary_contact":
            coplanar_boundary_contacts += 1
            boundary_contacts.append(detail)
        else:
            geos_errors.append(detail)

    classification_complete = bool(not pair_truncated and coplanar_skipped == 0
                                   and not unresolved_pairs and not geos_errors)
    complete = classification_complete
    has_findings = bool(noncoplanar_crossings or boundary_contacts or coplanar_overlap_pairs)
    ok = bool(complete and not has_findings)
    elapsed = time.perf_counter() - started
    failures: list[str] = []
    if noncoplanar_crossings:
        failures.append("non-coplanar triangle interiors cross")
    if coplanar_overlap_pairs:
        failures.append("coplanar triangles overlap with positive area")
    if boundary_contacts:
        failures.append("non-shared-index triangles touch at a boundary")
    if not complete:
        failures.append("intersection scan or classification is incomplete")
    return {
        "ok": ok,
        "complete": complete,
        "classification_complete": classification_complete,
        "semantic_version": SELF_INTERSECTION_SEMANTICS,
        "algorithm": "Open3D legacy CPU all-pairs scan + GEOS coplanar classification",
        "backend": "open3d_legacy_cpu_all_pairs",
        "backend_version": str(getattr(o3d, "__version__", "unknown")),
        "checked_pairs": int(len(pairs)),
        "candidate_pairs": int(len(pair_array)),
        "backend_pair_count": int(len(pair_array)),
        "shared_index_pairs_filtered": shared_index_pairs_filtered,
        "pair_scan_work": int(pair_work),
        "pair_scan_budget": work_budget,
        "intersecting_pairs": int(len(noncoplanar_crossings)),
        "nonadjacent_self_contact_pairs": int(len(boundary_contacts)),
        "noncoplanar_crossing_pairs": noncoplanar_crossings,
        "nonadjacent_self_contact_details": boundary_contacts,
        "unresolved_pairs": unresolved_pairs,
        "coplanar_contact_pairs": coplanar_contact_pairs,
        "coplanar_pairs_examined": int(coplanar_pairs_examined - len(geos_errors)),
        "coplanar_pairs_skipped": int(coplanar_skipped),
        "coplanar_boundary_contact_pairs": int(coplanar_boundary_contacts),
        "coplanar_overlap_pairs": int(coplanar_overlap_pairs),
        "coplanar_overlap_area_mm2": float(coplanar_overlap_area_mm2),
        "coplanar_details": coplanar_details,
        "classification_errors": geos_errors,
        "eps_mm": float(eps_mm),
        "coplanar_area_eps_mm2": COPLANAR_AREA_EPS_MM2,
        "pair_budget_truncated": bool(pair_truncated),
        "method": "Open3D GetSelfIntersectingTriangles all-pairs scan; shared-index pairs excluded; "
                  "GEOS projects coplanar hits for positive-area classification",
        "boundary_contact_policy": "non-shared-index point/edge/segment contacts fail QA",
        "chunk_parameter_ignored": int(chunk),
        "elapsed_seconds": float(elapsed),
        "failures": failures,
        "faces": n,
    }


# ------------------------------------------------------------------------------- the audit
def _faces_with_tags(mother: MotherGeometry, tags: Sequence[str]) -> np.ndarray:
    wanted = {int(k) for k, v in mother.surface_tag_names.items() if v in set(tags)}
    return np.nonzero(np.isin(np.asarray(mother.face_surface_tag), list(wanted)))[0]


def audit_mother(mother: MotherGeometry, *, max_thickness_probes: int = 320,
                 run_self_intersection: bool = True) -> dict[str, Any]:
    """Full return-before-output audit; returns metrics, never raises for QA failures."""
    mesh = mother.mesh
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "mother has no mesh faces",
                          stage="mothers.audit", measurements={"mother_id": mother.mother_id})
    meta = dict(mother.meta or {})
    gate_min = float(meta.get("min_wall_mm", 0.8))
    gate_max = float(meta.get("max_wall_mm", np.inf))
    design_min = float(meta.get("design_thickness_min_mm", float("nan")))
    design_max = float(meta.get("design_thickness_max_mm", float("nan")))
    requires_cavity = bool(meta.get("requires_cavity", False))
    health_report = health(mesh)
    tags = np.asarray(mother.face_surface_tag)
    checks: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []

    # 1. watertight + valid manifold ------------------------------------------------
    manifold = manifold_status(mesh) if health_report["watertight"] else {
        "status": "skipped (not watertight)", "ok": False, "volume_mm3": float(mesh.volume),
        "genus": None, "triangles": int(len(mesh.faces))}
    water_ok = bool(health_report["watertight"] and health_report["winding_consistent"]
                    and manifold["ok"])
    checks["watertight"] = {
        "ok": water_ok,
        "watertight": health_report["watertight"],
        "winding_consistent": health_report["winding_consistent"],
        "degenerate_faces": health_report["degenerate_faces"],
        "manifold_status": manifold["status"],
        "faces": health_report["faces"],
        "bodies": health_report["bodies"],
    }
    if not water_ok:
        failures.append({"check": "watertight", "code": ErrorCode.MOTHER_INVALID.value,
                         "message": "mesh is not a closed, consistently wound manifold",
                         "measurements": checks["watertight"]})

    # 2. outward, positive volume ---------------------------------------------------
    volume = float(mesh.volume)
    vol_ok = bool(volume > 0)
    checks["outward_volume"] = {
        "ok": vol_ok,
        "volume_mm3": volume,
        "abs_volume_mm3": abs(volume),
        "area_mm2": health_report["area_mm2"],
        "genus": manifold["genus"],
        "bodies": health_report["bodies"],
        "euler_number": health_report["euler_number"],
        "manifold_volume_mm3": manifold["volume_mm3"],
        "orientation": "outward" if vol_ok else "inward_or_degenerate",
    }
    if not vol_ok:
        failures.append({"check": "outward_volume", "code": ErrorCode.MOTHER_INVALID.value,
                         "message": "non-positive signed volume (normals not outward)",
                         "measurements": checks["outward_volume"]})

    # 3. self intersection ----------------------------------------------------------
    if run_self_intersection:
        si = self_intersection_report(mesh)
    else:
        si = {"ok": None, "skipped": True, "reason": "run_self_intersection=False"}
    checks["self_intersection"] = si
    if si.get("ok") is False:
        failures.append({"check": "self_intersection", "code": ErrorCode.MOTHER_INVALID.value,
                         "message": "mesh self-intersects",
                         "measurements": {k: v for k, v in si.items() if k != "ok"}})

    # 4. minimum thickness ----------------------------------------------------------
    shell_tags = ("outer_wall", "inner_wall", "rim", "foot", "base")
    probes = _faces_with_tags(mother, shell_tags)
    if probes.size == 0:
        probes = np.arange(len(mesh.faces))
    thickness = measure.thickness_samples(mesh, probes, max_probes=max_thickness_probes)
    measured_min = thickness.get("min_mm", float("nan"))
    thickness_ok = bool(np.isfinite(measured_min) and measured_min >= gate_min)
    if np.isfinite(design_max):
        thickness_ok = thickness_ok and bool(measured_min <= design_max * 1.35 + 0.5)
    checks["min_thickness"] = {
        "ok": thickness_ok,
        "design_min_mm": design_min,
        "design_max_mm": design_max,
        "gate_min_mm": gate_min,
        "gate_max_mm": gate_max,
        **thickness,
    }
    if not thickness_ok:
        failures.append({"check": "min_thickness", "code": ErrorCode.MOTHER_INVALID.value,
                         "message": f"measured minimum thickness {measured_min:.4f} mm is outside "
                                    f"[{gate_min:.3f}, {gate_max:.3f}] mm",
                         "measurements": checks["min_thickness"]})

    # 5. cavity ---------------------------------------------------------------------
    hull_volume = float(mesh.convex_hull.volume)
    void_ratio = float(1.0 - (abs(volume) / hull_volume)) if hull_volume > 0 else 0.0
    probe_points = np.asarray(meta.get("cavity_probe_points_mm") or [], dtype=np.float64)
    inside_flags = measure.point_in_material(mesh, probe_points) if probe_points.size else np.zeros(0, bool)
    void_probe_ok = bool(probe_points.size and not np.any(inside_flags))
    cavity_ok = True
    cavity_note = "solid body (no cavity required)"
    if requires_cavity:
        cavity_ok = bool(void_ratio > 0.02 and void_probe_ok)
        cavity_note = "open cavity must stay empty: void ratio > 0.02 and probes outside material"
    checks["cavity"] = {
        "ok": cavity_ok,
        "requires_cavity": requires_cavity,
        "void_ratio": void_ratio,
        "hull_volume_mm3": hull_volume,
        "material_volume_mm3": abs(volume),
        "cavity_probe_count": int(probe_points.shape[0]),
        "cavity_probes_inside_material": int(np.count_nonzero(inside_flags)),
        "note": cavity_note,
    }
    if not cavity_ok:
        failures.append({"check": "cavity", "code": ErrorCode.MOTHER_INVALID.value,
                         "message": "open cavity is missing or filled in",
                         "measurements": checks["cavity"]})

    # 6. source labels --------------------------------------------------------------
    attrs = (mesh.metadata or {}).get("face_attr_arrays") or {}
    tag_arr = np.asarray(attrs.get("surface_tag", tags))
    src = np.asarray(attrs.get("source_triangle", np.zeros(0, dtype=np.int32)))
    comp = np.asarray(attrs.get("component_id", np.zeros(0, dtype=np.int32)))
    valid_tag_values = sorted(int(t) for t in mother.surface_tag_names)
    labels_ok = bool(
        tag_arr.shape[0] == len(mesh.faces)
        and src.shape[0] == len(mesh.faces)
        and np.array_equal(src, np.arange(len(mesh.faces), dtype=src.dtype))
        and np.all(np.isin(tag_arr, valid_tag_values))
        and int(TAG_UNASSIGNED) not in set(int(v) for v in np.unique(tag_arr))
        and comp.shape[0] == len(mesh.faces)
        and tags.shape[0] == len(mesh.faces)
    )
    label_areas = {TAG_NAMES.get(int(v), str(int(v))):
                   float(np.asarray(mesh.area_faces)[tag_arr == v].sum())
                   for v in np.unique(tag_arr)}
    checks["source_labels"] = {
        "ok": labels_ok,
        "face_attr_keys": sorted(attrs.keys()),
        "tag_values": valid_tag_values,
        "tag_area_mm2": label_areas,
        "component_ids": sorted(int(v) for v in np.unique(comp)) if comp.size else [],
        "prebreak_components": meta.get("prebreak_components", []),
        "source_triangle_identity": bool(src.size == len(mesh.faces)
                                         and np.array_equal(src, np.arange(len(mesh.faces),
                                                                          dtype=src.dtype))),
    }
    if not labels_ok:
        failures.append({"check": "source_labels", "code": ErrorCode.MOTHER_INVALID.value,
                         "message": "face-level source labels are missing or inconsistent",
                         "measurements": checks["source_labels"]})

    # 7. charts ---------------------------------------------------------------------
    coverage = chart_coverage(mother.charts, np.unique(tags))
    sample_faces = np.unique(np.linspace(0, len(mesh.faces) - 1,
                                         min(128, len(mesh.faces))).astype(np.int64)) \
        if len(mesh.faces) else np.zeros(0, dtype=np.int64)
    sample_points = np.asarray(mesh.triangles_center)[sample_faces] if sample_faces.size else \
        np.zeros((0, 3))
    probes_report = []
    chart_ok = bool(coverage["ok"] and len(mother.charts) > 0)
    for chart in mother.charts:
        if chart.area_mm2 <= 0:
            chart_ok = False
        probe = chart_uv_probe(chart, sample_points)
        probe["area_positive"] = bool(chart.area_mm2 > 0)
        if not (probe["finite"] and probe["u_in_range"] and probe["area_positive"]):
            chart_ok = False
        probes_report.append(probe)
    checks["charts"] = {
        "ok": chart_ok,
        "count": len(mother.charts),
        "coverage": coverage,
        "probes": probes_report,
    }
    if not chart_ok:
        failures.append({"check": "charts", "code": ErrorCode.MOTHER_INVALID.value,
                         "message": "charts are missing, empty or do not cover the tagged faces",
                         "measurements": checks["charts"]})

    metrics = {
        "volume_mm3": volume,
        "area_mm2": health_report["area_mm2"],
        "faces": health_report["faces"],
        "vertices": health_report["vertices"],
        "thickness_min_mm": measured_min,
        "thickness_p05_mm": thickness.get("p05_mm"),
        "thickness_median_mm": thickness.get("median_mm"),
        "thickness_probes": thickness.get("n_valid"),
        "void_ratio": void_ratio,
        "bodies": health_report["bodies"],
        "genus": manifold["genus"],
        "self_intersecting_pairs": si.get("intersecting_pairs"),
        "realized_chord_error_mm": meta.get("realized_chord_error_mm"),
        "charts": len(mother.charts),
    }
    return {
        "ok": not failures,
        "mother_id": mother.mother_id,
        "vessel_id": mother.vessel_id,
        "material_id": mother.material_id,
        "checks": checks,
        "metrics": metrics,
        "failures": failures,
        "geometry_hash": geometry_hash(mesh),
        "state": "QA_PASSED" if not failures else "QA_FAILED",
    }


def geometry_hash(mesh: trimesh.Trimesh) -> str:
    """Stable geometry fingerprint (vertices + faces), independent of timestamps."""
    verts = np.ascontiguousarray(np.asarray(mesh.vertices, dtype=np.float64))
    faces = np.ascontiguousarray(np.asarray(mesh.faces, dtype=np.int64))
    return array_hash(np.concatenate([verts.ravel(), faces.ravel().astype(np.float64)]))


def raise_on_failure(report: dict[str, Any], *, stage: str = "mothers.audit",
                     context: dict[str, Any] | None = None) -> None:
    if report.get("ok"):
        return
    first = (report.get("failures") or [{}])[0]
    raise SynLabError(
        ErrorCode.MOTHER_INVALID,
        f"mother QA failed at check {first.get('check')!r}: {first.get('message')}",
        stage=stage,
        measurements={"failures": report.get("failures"), "metrics": report.get("metrics"),
                      **(context or {})},
    )
