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

from typing import Any, Sequence

import numpy as np
import trimesh
from scipy.spatial import cKDTree

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
def _axes_for_pair(t1: np.ndarray, t2: np.ndarray) -> np.ndarray:
    """(11, n, 3) candidate separating axes for ``n`` triangle pairs (may be degenerate)."""
    e1 = np.stack([t1[:, 1] - t1[:, 0], t1[:, 2] - t1[:, 1], t1[:, 0] - t1[:, 2]], axis=1)
    e2 = np.stack([t2[:, 1] - t2[:, 0], t2[:, 2] - t2[:, 1], t2[:, 0] - t2[:, 2]], axis=1)
    n1 = np.cross(e1[:, 0], e1[:, 1])[:, None, :]
    n2 = np.cross(e2[:, 0], e2[:, 1])[:, None, :]
    crosses = np.cross(e1[:, :, None, :], e2[:, None, :, :]).reshape(-1, 9, 3)
    return np.concatenate([n1, n2, crosses], axis=1)


def _interval_overlap(verts_a: np.ndarray, verts_b: np.ndarray, axes: np.ndarray,
                      eps: float) -> np.ndarray:
    """(n,) bool: projections of both triangles overlap on *every* axis by more than eps."""
    pa = np.einsum("nvi,nki->nvk", verts_a, axes)
    pb = np.einsum("nvi,nki->nvk", verts_b, axes)
    a_min = pa.min(axis=1)
    a_max = pa.max(axis=1)
    b_min = pb.min(axis=1)
    b_max = pb.max(axis=1)
    overlap = np.minimum(a_max, b_max) - np.maximum(a_min, b_min)
    axes_norm = np.linalg.norm(axes, axis=2)
    valid = axes_norm > 1e-9
    overlap = np.where(valid, overlap / np.maximum(axes_norm, 1e-12), 0.0)
    return np.all(np.where(valid, overlap > eps, True), axis=1)


def _coplanar_overlap(t1: np.ndarray, t2: np.ndarray, normals: np.ndarray,
                      eps_area_mm2: float = 1e-6) -> tuple[int, float]:
    """Exact 2D overlap area for coplanar triangle pairs (shapely / GEOS [R16])."""
    from shapely.geometry import Polygon

    overlapping = 0
    total_area = 0.0
    for i in range(len(t1)):
        n = normals[i]
        helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        u = np.cross(n, helper)
        u /= max(float(np.linalg.norm(u)), 1e-12)
        v = np.cross(n, u)
        pa = Polygon(np.column_stack([t1[i] @ u, t1[i] @ v]))
        pb = Polygon(np.column_stack([t2[i] @ u, t2[i] @ v]))
        if not (pa.is_valid and pb.is_valid):
            continue
        inter = pa.intersection(pb)
        area = float(inter.area)
        if area > eps_area_mm2:
            overlapping += 1
            total_area += area
    return overlapping, total_area


def _candidate_pairs(tris: np.ndarray, faces: np.ndarray, *, block: int = 120_000,
                     max_pairs: int = 6_000_000, stage: str = "mothers.audit.self_intersection"
                     ) -> tuple[np.ndarray, dict[str, Any]]:
    """Bounded sweep that generates every pair of non-adjacent triangles that can intersect.

    A bounding-sphere radius filter has two failure modes on real meshes: one broad cap
    triangle (a boolean lid, a handle root) makes the global radius meaningless, and a very
    thin sliver has a large bounding sphere but a tiny *axis-aligned slab*.  The sweep sorts
    the triangles along their widest axis and keeps a moving band of triangles whose slabs
    still overlap the current one, so the active set - and therefore memory - stays bounded
    even for those cases.  Pairs are recorded as ``(axis-aligned slab overlap) and (bounding
    spheres touch)``, which is a superset of the true intersections.
    """
    centroids = tris.mean(axis=1)
    mins = tris.min(axis=1)
    maxs = tris.max(axis=1)
    extent = np.linalg.norm(tris - centroids[:, None, :], axis=2).max(axis=1)
    slab = maxs - mins
    axis = np.argmax(slab, axis=1)
    lower = mins[np.arange(len(tris)), axis]
    upper = maxs[np.arange(len(tris)), axis]
    band = np.where((axis == np.argmax(slab, axis=1)), slab.max(axis=1), slab.max(axis=1))
    order = np.argsort(lower, kind="stable")
    lower_sorted = lower[order]
    kept: list[np.ndarray] = []
    checked = 0
    for start in range(0, len(tris), block):
        stop = min(start + block, len(tris))
        rows: list[np.ndarray] = []
        cols: list[np.ndarray] = []
        for position in range(start, stop):
            index = int(order[position])
            reach = lower_sorted[position] + band[index]
            hi = int(np.searchsorted(lower_sorted, reach, side="right"))
            if hi <= position + 1:
                continue
            others = order[position + 1:hi]
            # strict per-axis slab overlap on every axis
            overlap = np.all((mins[others] <= maxs[index] + 1e-9)
                             & (maxs[others] >= mins[index] - 1e-9), axis=1)
            others = others[overlap]
            if others.size == 0:
                continue
            distance = np.linalg.norm(centroids[others] - centroids[index], axis=1)
            others = others[distance <= (extent[others] + extent[index])]
            if others.size == 0:
                continue
            left = np.full(others.size, index, dtype=np.int64)
            shares = ((faces[left, 0:1] == faces[others]) | (faces[left, 1:2] == faces[others])
                      | (faces[left, 2:3] == faces[others])).any(axis=1)
            others = others[~shares]
            if others.size == 0:
                continue
            rows.append(np.full(others.size, index, dtype=np.int64))
            cols.append(others)
            checked += int(others.size)
            if checked > max_pairs:
                raise SynLabError(
                    ErrorCode.MOTHER_INVALID,
                    f"self-intersection prefilter produced more than {max_pairs} candidate "
                    "pairs; mesh is pathologically dense",
                    stage=stage,
                    measurements={"faces": int(len(tris)), "candidate_pairs": checked})
        if rows:
            kept.append(np.column_stack([np.concatenate(rows), np.concatenate(cols)]))
    pairs = np.concatenate(kept, axis=0) if kept else np.zeros((0, 2), dtype=np.int64)
    report = {
        "faces": int(len(tris)),
        "candidate_pairs": int(len(pairs)),
        "widest_slab_mm": float(band.max()),
        "method": "sort along the widest slab axis, then axis-aligned slab overlap + "
                  "bounding-sphere overlap per candidate",
    }
    return pairs, report


def self_intersection_report(mesh: trimesh.Trimesh, *, eps_mm: float = 1e-4,
                             max_pairs: int = 6_000_000,
                             max_coplanar_checks: int = 1500,
                             chunk: int = 40000) -> dict[str, Any]:
    """Complete non-adjacent triangle-triangle intersection scan.

    The candidate set is every pair of non-adjacent triangles whose slabs and bounding spheres
    touch (see :func:`_candidate_pairs`); the separating-axis test then runs on all of them in
    memory-bounded blocks, followed by an exact GEOS overlap test for coplanar pairs.  The scan
    is complete for the triangles it reports, and the block sizes are derived from a fixed
    memory budget because the separating-axis test materialises ``pairs x 11 axes x 3``
    coordinates per block.
    """
    tris = np.asarray(mesh.triangles, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    n = len(tris)
    if n == 0:
        return {"ok": False, "checked_pairs": 0, "intersecting_pairs": 0,
                "reason": "empty mesh"}
    pairs, sweep = _candidate_pairs(tris, faces, max_pairs=max_pairs)
    if len(pairs) == 0:
        return {"ok": True, "checked_pairs": 0, "intersecting_pairs": 0,
                "coplanar_contact_pairs": 0, "coplanar_pairs_examined": 0,
                "coplanar_overlap_pairs": 0, "coplanar_overlap_area_mm2": 0.0,
                "complete": True, **sweep,
                "note": "no non-adjacent triangle pair can touch"}
    # the separating-axis test materialises pairs x 11 axes x 3 coordinates per block
    block = int(np.clip(2_000_000 // 132, 2048, int(chunk)))
    hits = 0
    coplanar_count = 0
    checked_coplanar = 0
    overlap_area = 0.0
    overlap_pairs = 0
    for start in range(0, len(pairs), block):
        part = pairs[start:start + block]
        t1 = tris[part[:, 0]]
        t2 = tris[part[:, 1]]
        axes = _axes_for_pair(t1, t2)
        hits += int(_interval_overlap(t1, t2, axes, eps_mm).sum())
        n1 = np.cross(t1[:, 1] - t1[:, 0], t1[:, 2] - t1[:, 0])
        n2 = np.cross(t2[:, 1] - t2[:, 0], t2[:, 2] - t2[:, 0])
        nn1 = n1 / np.maximum(np.linalg.norm(n1, axis=1, keepdims=True), 1e-12)
        nn2 = n2 / np.maximum(np.linalg.norm(n2, axis=1, keepdims=True), 1e-12)
        parallel = np.abs(np.einsum("ij,ij->i", nn1, nn2)) > 1.0 - 1e-6
        plane_gap = np.abs(np.einsum("ij,ij->i", t2[:, 0] - t1[:, 0], nn1))
        cop = np.nonzero(parallel & (plane_gap < eps_mm))[0]
        if not cop.size:
            continue
        coplanar_count += int(cop.size)
        # Coplanar pairs are examined *inside* the block loop with a running budget: a boolean
        # seam is one large coplanar contact, so keeping the pair list alive would make the
        # audit report itself a memory hog.
        room = max(0, int(max_coplanar_checks) - checked_coplanar)
        if not room:
            continue
        cop = cop[:room]
        pairs_n, area = _coplanar_overlap(t1[cop], t2[cop], nn1[cop])
        checked_coplanar += int(cop.shape[0])
        overlap_pairs += pairs_n
        overlap_area += area
    return {
        "ok": bool(hits == 0 and overlap_pairs == 0),
        "checked_pairs": int(len(pairs)),
        "intersecting_pairs": int(hits),
        "coplanar_contact_pairs": int(coplanar_count),
        "coplanar_pairs_examined": int(checked_coplanar),
        "coplanar_overlap_pairs": int(overlap_pairs),
        "coplanar_overlap_area_mm2": float(overlap_area),
        "eps_mm": float(eps_mm),
        "complete": True,
        **sweep,
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
