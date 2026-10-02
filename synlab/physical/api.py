"""Physical damage façade: ``apply_damage`` / ``audit_physical`` (plan 12, 30.7, 30.8)."""

from __future__ import annotations

import weakref
from typing import Any

import numpy as np
import trimesh

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..roles import (
    FRAME_FRAGMENT,
    ROLE_PHYSICAL_COMPONENT,
    ROLE_PHYSICAL_RESULT,
    SCHEMA_PHYSICAL,
    UNIT_MM,
)
from ..schemas.runtime import (
    ORIGIN_AMBIGUOUS,
    ORIGIN_INTERFACE,
    ORIGIN_MOTHER_SURFACE,
    PhysicalComponent,
    PhysicalResult,
)
from . import operators as OPS
from . import sdf as S
from .recipe import APPEARANCE_AXES, P06_VARIANTS, P08_VARIANTS, DamageOutcome, DamageRecipe

#: In-memory source lookup so ``audit_physical(result, clean)`` also works with a CleanTruth
#: (which carries no mesh).  Keyed by the source geometry hash; never serialised.
_SOURCE_MESHES: "weakref.WeakValueDictionary[str, Any]" = weakref.WeakValueDictionary()


def _mesh_of(clean: Any) -> trimesh.Trimesh | None:
    if clean is None:
        return None
    if isinstance(clean, trimesh.Trimesh):
        return clean
    mesh = getattr(clean, "mesh", None)
    if isinstance(mesh, trimesh.Trimesh):
        return mesh
    return None


def _geometry_hash(mesh: trimesh.Trimesh) -> str:
    return hash_json({"vertices": S.geometry_key(mesh), "faces": int(len(mesh.faces)),
                      "area": round(float(mesh.area), 9), "volume": round(float(mesh.volume), 9)})


#: Semantic version of the physical-damage *result* contract (docs/a12/data_semantics_versions.md).
#: ``subset_v2`` means: (1) a delivered body is closed -- sub-micron boundary loops a boolean
#: engine leaves behind are filled and the closure is *proven* with ``is_watertight``; (2) only
#: bodies carrying measurable volume enter the component list, so a connected leftover with
#: exactly 0 mm3 is reported as engine debris instead of becoming a component with a
#: non-positive volume; (3) ``damaged ⊆ clean`` is measured with the exact float64 point-to-mesh
#: instrument below instead of Open3D's approximate signed distance, whose measured floor on the
#: L0 clean fragment is 0.0161 mm / 0.28 % of samples *for the mesh measured against itself*.
DAMAGE_SEMANTICS = "subset_v2"
DAMAGE_SEMANTICS_V1 = "subset_v1_as_shipped"

#: A connected body whose volume is at or below this carries no material: boolean engines emit
#: coincident opposite-winding triangle pairs (measured on the L0 P03 result: 2 bodies with 2
#: faces each and exactly 0.0 mm3) that are leftovers, not debris
#: (data/a12/reports/a09_p03_probe.json).
MIN_MATERIAL_VOLUME_MM3 = 1e-9

#: Boundary loops no larger than this are boolean pinholes (measured: 2 loops of 50 nm / 23 nm
#: bounding-box diagonal and ~0 mm2 area on the L0 P03 body); anything larger is a real hole and
#: is reported instead of being patched.
MAX_PINHOLE_DIAGONAL_MM = 1e-3
MAX_PINHOLE_AREA_MM2 = 1e-6


def _boundary_loops(mesh: trimesh.Trimesh) -> tuple[list[list[int]], dict[str, Any]]:
    """Directed boundary cycles of ``mesh`` (edges used by exactly one face), in vertex order.

    A face (i, j, k) contributes the directed edges i->j, j->k, k->i; an edge whose *undirected*
    key occurs once is on the boundary, and its direction is the direction the surface travels
    there.  A well-formed boundary is a permutation of those directions, so the loops are traced
    by following each vertex's single outgoing edge.
    """
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(faces) == 0:
        return [], {"boundary_edges": 0, "reason": "empty mesh"}
    directed = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0)
    keys = np.sort(directed, axis=1)
    _unique, inverse, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    inverse = np.asarray(inverse).reshape(-1)
    boundary = directed[np.asarray(counts, dtype=np.int64)[inverse] == 1]
    if len(boundary) == 0:
        return [], {"boundary_edges": 0, "reason": "no boundary edge"}
    out_map: dict[int, list[int]] = {}
    in_map: dict[int, list[int]] = {}
    for a, b in boundary:
        out_map.setdefault(int(a), []).append(int(b))
        in_map.setdefault(int(b), []).append(int(a))
    info: dict[str, Any] = {"boundary_edges": int(len(boundary)),
                            "boundary_vertices": int(len(out_map))}
    if (sorted(out_map) != sorted(in_map)
            or any(len(v) != 1 for v in out_map.values())
            or any(len(v) != 1 for v in in_map.values())):
        info["reason"] = "boundary edges do not form simple directed cycles"
        return [], info
    loops: list[list[int]] = []
    visited: set[int] = set()
    for start in sorted(out_map):
        if start in visited:
            continue
        loop = [start]
        visited.add(start)
        cursor = out_map[start][0]
        while cursor != start:
            if cursor in visited:
                info["reason"] = "boundary walk revisited a vertex before closing"
                return [], info
            loop.append(cursor)
            visited.add(cursor)
            cursor = out_map[cursor][0]
        loops.append(loop)
    info["loops"] = len(loops)
    info["loop_sizes"] = [len(loop) for loop in loops]
    return loops, info


def close_numerical_pinholes(mesh: trimesh.Trimesh, *,
                             max_diagonal_mm: float = MAX_PINHOLE_DIAGONAL_MM,
                             max_area_mm2: float = MAX_PINHOLE_AREA_MM2
                             ) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    """Close sub-micron boundary loops so the delivered body is a closed solid.

    A boolean intersection of an extracted body with the source can leave boundary loops at the
    engine's own precision: measured on the L0 P03 result, 6 boundary edges forming 2 loops of
    50 nm and 23 nm bounding-box diagonal with ~0 mm2 area.  ``trimesh.repair.fill_holes`` does
    not repair them in this trimesh build (its ``extend_faces`` call adds no face -- measured:
    data/a12/reports/a09_p03_seam.json), so the patch face is added here directly: the boundary
    is traversed as a directed cycle and closed with the reversed polygon.

    Only loops *smaller than the declared pinhole scale* are filled, the result is accepted only
    when it is watertight, winding-consistent and volume-neutral, and any larger or non-cyclic
    boundary is left exactly as the operator produced it -- a real hole must still fail the
    watertight audit instead of being patched away.
    """
    watertight_before = bool(mesh.is_watertight) and bool(mesh.is_winding_consistent)
    report: dict[str, Any] = {"applied": False, "watertight_before": watertight_before,
                              "faces_added": 0, "volume_delta_mm3": 0.0,
                              "max_pinhole_diagonal_mm": float(max_diagonal_mm),
                              "max_pinhole_area_mm2": float(max_area_mm2)}
    if watertight_before:
        report["reason"] = "already watertight"
        return mesh, report
    loops, loop_info = _boundary_loops(mesh)
    report["boundary"] = loop_info
    if not loops:
        report["reason"] = loop_info.get("reason", "no boundary loop")
        return mesh, report
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    rows = []
    for loop in loops:
        points = vertices[np.asarray(loop, dtype=np.int64)]
        diagonal = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
        normal = np.zeros(3, dtype=np.float64)
        for index in range(len(loop)):   # Newell area of the (planar-ish) loop polygon
            normal += np.cross(points[index], points[(index + 1) % len(loop)])
        area = 0.5 * float(np.linalg.norm(normal))
        rows.append({"vertices": [int(v) for v in loop], "diagonal_mm": diagonal,
                     "area_mm2": area,
                     "fillable": bool(diagonal <= max_diagonal_mm and area <= max_area_mm2)})
    report["loops"] = rows
    if not all(row["fillable"] for row in rows):
        report["reason"] = "boundary loop larger than the declared pinhole scale"
        return mesh, report
    volume_before = float(abs(mesh.volume))
    candidate = mesh.copy()
    # the patch face traverses the boundary in the opposite direction of the surface edge
    # Fan-triangulate each boundary loop: boundary cycles can have different lengths (a 3-edge
    # pinhole next to a 4-edge one), and vstacking the raw cycles raises a shape error.  The fan
    # keeps the reversed winding of the surface edge, so the patch face is oriented inward.
    patches: list[np.ndarray] = []
    for loop in loops:
        rev = np.asarray(loop[::-1], dtype=np.int64)
        if rev.size < 3:
            continue
        for k in range(1, int(rev.size) - 1):
            patches.append(np.array([[int(rev[0]), int(rev[k]), int(rev[k + 1])]],
                                    dtype=np.int64))
    if not patches:
        report["reason"] = "boundary loop had fewer than three vertices"
        return mesh, report
    candidate.faces = np.vstack([np.asarray(mesh.faces, dtype=np.int64)] + patches)
    candidate.merge_vertices()
    candidate.remove_unreferenced_vertices()
    closed = bool(candidate.is_watertight) and bool(candidate.is_winding_consistent)
    report["faces_added"] = int(len(patches))
    report["volume_delta_mm3"] = float(abs(candidate.volume) - volume_before)
    if not closed:
        report["reason"] = ("filling the pinholes did not yield a watertight, "
                            "winding-consistent body")
        return mesh, report
    report["applied"] = True
    report["watertight_after"] = True
    return candidate, report


# ------------------------------------------------------------------- face provenance
#: Face-level provenance of a *damaged* component (see docs/a12/fracture_surface_signal.md).
#: Every damaged face is classified into exactly one of the three origin kinds of
#: :mod:`synlab.schemas.runtime` -- mother surface (0), interface (1) or ambiguous (2) -- from
#: two *measurable* instruments, never from a guess:
#:
#: 1. **source-surface mapping.**  The exact closest point of the damaged face centroid on the
#:    clean source surface (float64 point-to-triangle, ``trimesh.proximity.closest_point``) gives
#:    the clean face it came from.  The mapping is accepted only when the centroid lands within
#:    ``tol_mm`` of that face *and* the two normals agree within ``cos_min``, and then the origin
#:    kind and the interface id of the clean face are inherited.  The tolerance has a measured
#:    basis: the damaged surface is re-extracted on the frozen SDF grid, so a face that is
#:    genuinely the same surface can sit half a cell away from it, plus the recession the operator
#:    actually realized; the default is therefore ``0.5 * spacing + realized_recession`` clipped to
#:    ``[MIN, MAX]`` (all three are recorded with the result).
#: 2. **declared ROI band for SDF-born faces.**  A face that maps to nothing is new geometry
#:    created by the operator.  It is called an interface face only when it lies inside the band
#:    the operator itself declares for its ROI (``halo_mm`` of its own SDF pipeline, the distance
#:    at which its ROI weight reaches zero); every other new face stays ``ORIGIN_AMBIGUOUS`` and
#:    is counted, with the reason, in the provenance report.
ORIGIN_PROVENANCE_VERSION = "origin_provenance_v1"
#: Half a frozen SDF cell: the re-extracted level set of the *unmodified* field can sit this far
#: from the original surface and still be the same surface (measured on the L0 probe).
ORIGIN_COLOCATION_CELL_FRACTION = 0.5
#: Never declare a co-location tighter than this (float32 attribute quantisation, welding).
ORIGIN_COLOCATION_MIN_MM = 0.05
#: Never declare a co-location wider than this: above it the mapping stops being evidence.
ORIGIN_COLOCATION_MAX_MM = 1.0
#: 60 degrees.  A face that crosses the wall (a sliver at a boolean rim) is not "the same surface".
ORIGIN_COLOCATION_COS_MIN = 0.5
#: Fallback ROI band when the operator did not report its own halo.
ORIGIN_ROI_HALO_FALLBACK_MM = 3.0


def origin_colocation_tolerance_mm(*, spacing_mm: float | None = None,
                                   realized_recession_mm: float = 0.0,
                                   min_wall_mm: float | None = None) -> float:
    """Co-location tolerance of the source-surface mapping, in mm (measured inputs only)."""
    tol = ORIGIN_COLOCATION_MIN_MM + max(0.0, float(realized_recession_mm or 0.0))
    if spacing_mm is not None and float(spacing_mm) > 0.0:
        tol += ORIGIN_COLOCATION_CELL_FRACTION * float(spacing_mm)
    tol = min(max(tol, ORIGIN_COLOCATION_MIN_MM), ORIGIN_COLOCATION_MAX_MM)
    if min_wall_mm is not None and float(min_wall_mm) > 0.0:
        # a wall thinner than twice the tolerance would map a face onto the *other* side of it
        tol = min(tol, 0.5 * float(min_wall_mm))
    return float(max(tol, 1e-6))


def classify_face_origin(damaged: trimesh.Trimesh, clean: trimesh.Trimesh, *,
                         origin: np.ndarray, interface_id: np.ndarray,
                         roi_ids: np.ndarray | None = None, tol_mm: float,
                         cos_min: float = ORIGIN_COLOCATION_COS_MIN,
                         roi_tol_mm: float = 0.0) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Classify every face of ``damaged`` against the clean source surface it descends from.

    ``origin`` / ``interface_id`` are the clean face channels (same length as ``clean.faces``);
    ``roi_ids`` are the clean faces of the *declared* ROI (an interface operator's interface
    patch).  Returns ``(origin_kind, interface_id, report)`` with one entry per damaged face.

    The three classes and their evidence are exactly:

    ``0`` inherited mother surface -- centroid within ``tol_mm`` of a clean face whose own origin
    kind is 0, normals agreeing within ``cos_min``; the clean face's ``interface_id`` is kept.
    ``1`` interface -- either inherited from a clean interface face by the same mapping, or born
    in the operator's declared ROI band (``roi_tol_mm`` of the ROI geometry) with no clean face
    within ``tol_mm``.
    ``2`` ambiguous -- new geometry outside the declared ROI band, and every face the mapping
    could not accept; counted in ``report['classes']['ambiguous']['reasons']``.
    """
    faces = int(len(damaged.faces))
    origin_out = np.full(faces, ORIGIN_AMBIGUOUS, dtype=np.uint8)
    iface_out = np.full(faces, -1, dtype=np.int32)
    clean_origin = np.asarray(origin, dtype=np.int64).reshape(-1)
    clean_iface = np.asarray(interface_id, dtype=np.int64).reshape(-1)
    report: dict[str, Any] = {
        "version": ORIGIN_PROVENANCE_VERSION,
        "faces": faces,
        "tol_mm": float(tol_mm),
        "cos_min": float(cos_min),
        "roi_tol_mm": float(roi_tol_mm),
        "instrument": ("trimesh.proximity.closest_point (exact point-to-triangle, float64) "
                       "+ face-normal agreement"),
        "classes": {},
    }
    if faces == 0:
        report["classes"] = {str(ORIGIN_MOTHER_SURFACE): 0, str(ORIGIN_INTERFACE): 0,
                             str(ORIGIN_AMBIGUOUS): 0}
        return origin_out, iface_out, report
    if clean_origin.shape[0] != len(clean.faces) or clean_iface.shape[0] != len(clean.faces):
        report["classes"] = {str(ORIGIN_MOTHER_SURFACE): 0, str(ORIGIN_INTERFACE): 0,
                             str(ORIGIN_AMBIGUOUS): faces}
        report["failure"] = ("clean face channels do not match the clean mesh "
                             f"({clean_origin.shape[0]}/{clean_iface.shape[0]} vs "
                             f"{len(clean.faces)} faces); no face is claimed")
        return origin_out, iface_out, report

    centroids = np.asarray(damaged.triangles_center, dtype=np.float64)
    close, dist, tri = trimesh.proximity.closest_point(clean, centroids)
    tri = np.asarray(tri, dtype=np.int64).reshape(-1)
    dist = np.asarray(dist, dtype=np.float64).reshape(-1)
    d_normals = np.asarray(damaged.face_normals, dtype=np.float64)
    c_normals = np.asarray(clean.face_normals, dtype=np.float64)
    cos = np.abs(np.einsum("ij,ij->i", d_normals, c_normals[tri]))
    mapped = (dist <= float(tol_mm)) & (cos >= float(cos_min))
    origin_out[mapped] = clean_origin[tri[mapped]].astype(np.uint8)
    iface_out[mapped] = clean_iface[tri[mapped]].astype(np.int32)

    new = ~mapped
    roi_near = np.zeros(faces, dtype=bool)
    roi_index = np.full(faces, -1, dtype=np.int64)
    roi = None if roi_ids is None else np.asarray(roi_ids, dtype=np.int64).reshape(-1)
    if roi is not None and roi.size and float(roi_tol_mm) > 0.0 and bool(new.any()):
        roi_mesh = trimesh.Trimesh(vertices=np.asarray(clean.vertices, dtype=np.float64),
                                   faces=np.asarray(clean.faces, dtype=np.int64)[roi],
                                   process=False)
        _closest, roi_dist, roi_tri = trimesh.proximity.closest_point(roi_mesh, centroids[new])
        roi_dist = np.asarray(roi_dist, dtype=np.float64).reshape(-1)
        near_new = roi_dist <= float(roi_tol_mm)
        idx_new = np.flatnonzero(new)
        roi_near[idx_new[near_new]] = True
        roi_index[idx_new[near_new]] = roi[np.asarray(roi_tri, dtype=np.int64).reshape(-1)[near_new]]
    born_in_roi = new & roi_near
    origin_out[born_in_roi] = ORIGIN_INTERFACE
    # the interface id of a new ROI face is the id of the nearest declared-ROI source face; when
    # that source face carries no id (-1: an origin-kind-only ROI) the id stays -1, never invented
    ok = born_in_roi & (roi_index >= 0)
    iface_out[ok] = clean_iface[roi_index[ok]].astype(np.int32)

    reasons: dict[str, int] = {}
    if bool(new.any()):
        reasons["new_face_outside_declared_roi_band"] = int((new & ~roi_near).sum())
        reasons["new_face_in_declared_roi_band"] = int(born_in_roi.sum())
    report["classes"] = {
        str(ORIGIN_MOTHER_SURFACE): int(np.count_nonzero(origin_out == ORIGIN_MOTHER_SURFACE)),
        str(ORIGIN_INTERFACE): int(np.count_nonzero(origin_out == ORIGIN_INTERFACE)),
        str(ORIGIN_AMBIGUOUS): int(np.count_nonzero(origin_out == ORIGIN_AMBIGUOUS)),
    }
    face_area = np.asarray(damaged.area_faces, dtype=np.float64)
    total_area = float(face_area.sum())
    report["class_area_mm2"] = {
        str(kind): float(face_area[origin_out == int(kind)].sum())
        for kind in (ORIGIN_MOTHER_SURFACE, ORIGIN_INTERFACE, ORIGIN_AMBIGUOUS)}
    report["class_area_fraction"] = {
        key: (value / total_area if total_area > 0 else 0.0)
        for key, value in report["class_area_mm2"].items()}
    report["area_mm2"] = total_area
    report["mapped_to_clean_face"] = int(mapped.sum())
    report["mapped_fraction"] = float(mapped.mean())
    report["born_in_declared_roi"] = int(born_in_roi.sum())
    report["ambiguous_reasons"] = reasons
    report["distance_mm"] = {
        "p50": float(np.percentile(dist, 50)), "p90": float(np.percentile(dist, 90)),
        "max": float(dist.max()),
        "mapped_max": float(dist[mapped].max()) if bool(mapped.any()) else None,
    }
    report["inherited_origin_histogram"] = {
        str(int(k)): int(v) for k, v in zip(*np.unique(clean_origin[tri[mapped]],
                                                       return_counts=True))} if bool(mapped.any()) \
        else {}
    report["interface_id_histogram"] = {
        str(int(k)): int(v) for k, v in zip(*np.unique(iface_out, return_counts=True))}
    return origin_out, iface_out, report


def subset_outside_stats(damaged: trimesh.Trimesh, reference: trimesh.Trimesh, *,
                         n_samples: int = 1200, tol_mm: float = 1e-3,
                         seed: int = 0) -> dict[str, Any]:
    """How much of ``damaged``'s surface lies outside ``reference`` -- measured exactly.

    Instrument: sample the damaged surface, then evaluate the *exact* closest point on the
    reference plus a normal-projection sign in float64 (``trimesh.proximity.signed_distance``,
    whose convention is **positive = inside**).  The superseded instrument
    (``sdf.outside_fraction``) uses Open3D's approximate signed distance on float32 points, whose
    measured floor on the L0 clean fragment is ``max_outside_mm = 0.0161`` with 0.28 % of samples
    beyond the 1e-3 mm tolerance *for the mesh measured against itself*; a level-0 identity result
    (whose component **is** the clean mesh object) therefore failed the shipped check, measured:
    data/a12/reports/a09_subset_instrument.json.  The same control with this instrument reports
    1.4e-10 mm and 0 outside samples.  The tolerance is unchanged by the swap, and the superseded
    numbers are returned beside the exact ones so nothing is hidden.
    """
    points, _face_ids = trimesh.sample.sample_surface(
        damaged, int(n_samples), seed=int(seed) % (2 ** 31))
    points = np.asarray(points, dtype=np.float64)
    signed_inside = np.asarray(trimesh.proximity.signed_distance(reference, points),
                               dtype=np.float64)
    outside = -signed_inside                      # >= 0 = outside the reference body
    outside_distance = np.where(outside > 0.0, outside, 0.0)
    stats: dict[str, Any] = {
        "instrument": "trimesh.proximity.signed_distance (exact, float64; positive = inside)",
        "samples": int(len(points)),
        "outside_points": int(np.count_nonzero(outside > float(tol_mm))),
        "outside_fraction": float(np.mean(outside > float(tol_mm))) if len(points) else 0.0,
        "max_outside_mm": float(outside_distance.max()) if len(points) else 0.0,
        "p99_outside_mm": float(np.percentile(outside_distance, 99)) if len(points) else 0.0,
        "signed_max_outside_mm": float(outside.max()) if len(points) else 0.0,
        "tol_mm": float(tol_mm),
    }
    try:  # the superseded instrument, kept beside the exact one so nothing is hidden
        stats["approx_open3d"] = S.outside_fraction(damaged, reference, n_samples=n_samples,
                                                    tol_mm=tol_mm, seed=seed)
    except Exception as exc:  # noqa: BLE001 - reported, never silently dropped
        stats["approx_open3d"] = {"error": f"{type(exc).__name__}: {exc}"}
    return stats


def material_volume_floor(source_volume_mm3: float, override: float | None = None) -> float:
    """Volume at or below which a connected body carries no material (one definition)."""
    return max(float(override if override is not None else MIN_MATERIAL_VOLUME_MM3),
               MIN_MATERIAL_VOLUME_MM3, 1e-12 * max(float(source_volume_mm3), 0.0))


def assemble_damage_bodies(mesh: trimesh.Trimesh, *, source_volume_mm3: float,
                           min_material_volume_mm3: float | None = None
                           ) -> tuple[list[trimesh.Trimesh], dict[str, Any]]:
    """Turn one raw operator body into the delivered bodies of ``damage_semantics = subset_v2``.

    Order matters and is measured: the boolean engine emits coincidence *pairs* of
    opposite-winding triangles with zero volume (2 of them on the L0 P03 result), and those pairs
    share the very vertices of the pinholes in the material body.  Patching the holes first was
    measured to fail -- after the patch the mesh has 2 edges used **four** times (twice by the
    pair, once by the body, once by the patch), so ``is_watertight`` stays False
    (data/a12/reports/a09_p03_probe.json, a09_acceptance_after.json).  Removing the pairs first
    leaves 3 edges used exactly twice, and the patch then closes the body.

    Returns the material bodies (engine debris dropped and counted) plus the assembly record.
    """
    floor = material_volume_floor(source_volume_mm3, min_material_volume_mm3)
    parts = S.component_split(mesh)
    material = [p for p in parts if float(abs(p.volume)) > floor]
    dropped = [p for p in parts if float(abs(p.volume)) <= floor]
    floor_overridden = False
    if parts and not material:      # never deliver an empty body list: fail visibly
        material = [max(parts, key=lambda p: float(abs(p.volume)))]
        dropped = [p for p in parts if p is not material[0]]
        floor_overridden = True
    bodies: list[trimesh.Trimesh] = []
    closures: list[dict[str, Any]] = []
    for part in material:
        closed, closure = close_numerical_pinholes(part)
        bodies.append(closed)
        closures.append(closure)
    record: dict[str, Any] = {
        "connected_bodies": len(parts),
        "material_bodies": len(material),
        "non_material_bodies": len(dropped),
        "non_material_faces": [int(len(p.faces)) for p in dropped],
        "non_material_volume_mm3": float(sum(abs(p.volume) for p in dropped)),
        "material_floor_mm3": float(floor),
        "material_floor_overridden": bool(floor_overridden),
        "pinhole_closures": closures,
        "pinholes_filled": int(sum(int(c.get("faces_added", 0)) for c in closures)),
        "watertight_bodies": int(sum(1 for body in bodies if bool(body.is_watertight))),
        "bodies": len(bodies),
    }
    return bodies, record


def register_components(
    parts: list[trimesh.Trimesh],
    *,
    clean_fragment_id: str,
    source_volume_mm3: float,
    min_support_abs_mm3: float = 1e-3,
    min_support_rel: float = 0.005,
    added_bodies: list[tuple[trimesh.Trimesh, str]] | None = None,
    min_material_volume_mm3: float | None = None,
) -> tuple[list[PhysicalComponent], dict[str, str], dict[str, Any]]:
    """§30.8 identity policy: keep every connected body, choose one representative.

    The representative is the largest *independently supportable* body; ties are broken by
    the frozen geometry key.  Everything else is kept as ``DEBRIS`` and still enters the
    material ledger; same-ancestor sub-fragments are flagged so they are never used as
    ordinary negatives downstream.

    ``damage_semantics = subset_v2``: a connected body with **no measurable volume** is not
    material and is not a component.  Boolean engines emit coincident opposite-winding triangle
    pairs (measured on the L0 P03 result: 2 bodies, 2 faces each, exactly 0.0 mm3), and keeping
    them produced ``NON_POSITIVE_VOLUME`` on a result whose material body was fine.  Such bodies
    are counted in the ledger (``non_material_*``) instead of disappearing, and if a result
    consists of nothing else the largest body is still kept so the failure stays visible.
    """
    threshold = max(float(min_support_abs_mm3), float(min_support_rel) * max(float(source_volume_mm3), 0.0))
    material_floor = material_volume_floor(source_volume_mm3, min_material_volume_mm3)
    entries = []
    for index, part in enumerate(parts):
        volume = float(abs(part.volume))
        entries.append({"mesh": part, "volume": volume, "index": index,
                        "supportable": bool(volume >= threshold), "contamination": False,
                        "key": S.geometry_key(part)})
    for part, material_class in (added_bodies or []):
        volume = float(abs(part.volume))
        entries.append({"mesh": part, "volume": volume, "index": len(entries),
                        "supportable": False, "contamination": True,
                        "material_class": material_class, "key": S.geometry_key(part)})
    material = [e for e in entries if e["volume"] > material_floor]
    dropped = [e for e in entries if e["volume"] <= material_floor]
    floor_overridden = False
    if entries and not material:      # never deliver an empty component list: fail visibly
        material = [max(entries, key=lambda e: e["volume"])]
        dropped = [e for e in entries if e is not material[0]]
        floor_overridden = True
    supportable = [e for e in material if e["supportable"]]
    representative_key = None
    if supportable:
        best = sorted(supportable, key=lambda e: (-e["volume"], e["key"]))[0]
        representative_key = (best["index"], best["key"])
    components: list[PhysicalComponent] = []
    representative_map: dict[str, str] = {}
    for entry in sorted(material, key=lambda e: (-e["volume"], e["key"])):
        component_id = f"{clean_fragment_id}#c{entry['index']}"
        is_representative = (representative_key is not None
                             and entry["index"] == representative_key[0]
                             and entry["key"] == representative_key[1])
        meta = {
            "ancestor": clean_fragment_id,
            "clean_fragment_ancestor": clean_fragment_id,
            "geometry_key": entry["key"],
            "supportable": bool(entry["supportable"]),
            "support_threshold_mm3": threshold,
            "material_class": entry.get("material_class", "ORIGINAL"),
            "is_contamination": bool(entry["contamination"]),
            "same_ancestor_subfragment": not is_representative,
            "not_an_ordinary_negative": not is_representative,
            "source_map": "clean_fragment",
        }
        status = "CORE" if is_representative else "DEBRIS"
        components.append(PhysicalComponent(
            component_id=component_id, clean_fragment_id=clean_fragment_id, mesh=entry["mesh"],
            volume_mm3=float(entry["volume"]), is_representative=bool(is_representative),
            status=status, survivor_patch_ref=None, meta=meta))
        if is_representative:
            representative_map[clean_fragment_id] = component_id
    ledger = {
        "source_volume_mm3": float(source_volume_mm3),
        "component_count": len(material),
        "raw_connected_bodies": len(entries),
        "non_material_body_count": len(dropped),
        "non_material_body_faces": [int(len(e["mesh"].faces)) for e in dropped],
        "non_material_body_volume_mm3": float(sum(e["volume"] for e in dropped)),
        "material_floor_mm3": float(material_floor),
        "material_floor_overridden": bool(floor_overridden),
        "original_component_count": int(sum(1 for e in material if not e["contamination"])),
        "contamination_component_count": int(sum(1 for e in material if e["contamination"])),
        "damaged_volume_mm3": float(sum(e["volume"] for e in material if not e["contamination"])),
        "added_volume_mm3": float(sum(e["volume"] for e in material if e["contamination"])),
        "debris_volume_mm3": float(sum(e["volume"] for e in material if not e["supportable"])),
        "support_threshold_mm3": threshold,
        "representative_component_id": (representative_map.get(clean_fragment_id)
                                        if representative_map else None),
        "representative_available": bool(representative_map),
        "representative_status": ("PENDING" if representative_map else "INPUT_UNAVAILABLE"),
        "evidence_lost": False,
    }
    ledger["lost_volume_mm3"] = max(
        0.0, ledger["source_volume_mm3"] - ledger["damaged_volume_mm3"])
    ledger["conservation_ok"] = bool(
        abs(ledger["source_volume_mm3"] - ledger["damaged_volume_mm3"] - ledger["lost_volume_mm3"]) <= 1e-6
        * max(ledger["source_volume_mm3"], 1.0))
    if len(material) > 1 and not ledger["representative_available"]:
        ledger["representative_status"] = "INPUT_UNAVAILABLE"
    return components, representative_map, ledger


def apply_damage(clean_truth: Any, fragment: Any, recipe: DamageRecipe,
                 rng: np.random.Generator | None = None) -> PhysicalResult:
    """Apply one physical damage level to one clean fragment (plan 12.1, 30.7).

    Level 0 (``recipe.is_identity``) returns the *source asset reference and bytes*: the
    component mesh is the very same object as ``fragment.mesh`` and no resampling,
    re-meshing or re-writing happens.
    """
    mesh = _mesh_of(fragment)
    if mesh is None:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "apply_damage needs a fragment carrying a mesh",
                          stage="physical.apply_damage")
    if not isinstance(recipe, DamageRecipe):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"recipe must be a DamageRecipe, got {type(recipe)!r}",
                          stage="physical.apply_damage")
    clean_fragment_id = str(getattr(fragment, "fragment_id", "") or recipe.meta.get("fragment_id", "fragment"))
    mother_id = str(getattr(clean_truth, "mother_id", "") or recipe.meta.get("mother_id", ""))
    event_id = str(getattr(clean_truth, "event_id", "") or recipe.meta.get("event_id", ""))
    version = int(getattr(clean_truth, "version", 0) or 0)
    clean_ref = f"{mother_id}:{event_id}:v{version}"
    source_volume = float(abs(mesh.volume))
    _SOURCE_MESHES[_geometry_hash(mesh)] = mesh

    declared = recipe.declared()
    if recipe.is_identity:
        ledger_components, representative_map, ledger = register_components(
            [mesh], clean_fragment_id=clean_fragment_id, source_volume_mm3=source_volume)
        for component in ledger_components:
            component.meta["identity"] = True
            component.meta["source_object_is_shared"] = True
        qa = {
            "status": "PASS", "identity": True, "level": 0,
            "source_geometry_hash": _geometry_hash(mesh),
            "result_geometry_hash": _geometry_hash(ledger_components[0].mesh),
            "bytes_identical": True, "resampled": False,
            "damage_semantics": DAMAGE_SEMANTICS,
            "note": "level 0 returns the source asset reference/bytes without resampling",
        }
        identity_provenance = {
            "version": ORIGIN_PROVENANCE_VERSION, "attached": False,
            "reason": ("identity level 0 returns the source object unchanged, so the source's own "
                       "face channels (fragment.face_origin_kind / face_interface_id) stay "
                       "authoritative and are not copied onto a shared object"),
        }
        qa["face_provenance"] = identity_provenance
        return PhysicalResult(
            mother_id=mother_id, clean_ref=clean_ref, event_id=event_id,
            recipe_id=recipe.recipe_id or f"{recipe.axis_id}:{recipe.variant}:L0", version=1,
            components=ledger_components, lost_volume_mm3=0.0, lost_volume_ratio=0.0,
            representative_map=representative_map, physical_truth=None, qa=qa,
            meta={"declared": declared, "identity": True, "ledger": ledger,
                  "source_geometry_hash": _geometry_hash(mesh), "axis_id": recipe.axis_id,
                  "variant": recipe.variant, "level": int(recipe.level),
                  "damage_semantics": DAMAGE_SEMANTICS,
                  "face_provenance": identity_provenance,
                  "geometry_changed": False, "frozen": recipe.frozen()},
        )

    outcome = OPS.run_damage(mesh, recipe, fragment=fragment)
    geometry_changed = outcome.mesh is not None and outcome.mesh is not mesh and recipe.touches_geometry
    damaged_mesh = outcome.mesh if outcome.mesh is not None else mesh
    closure: dict[str, Any] = {"applied": False, "reason": "not a geometry-changing operator"}
    if recipe.touches_geometry and geometry_changed:
        # damage_semantics = subset_v2: the delivered bodies must be closed solids and must carry
        # material.  The boolean engine leaves coincidence triangle pairs with zero volume (which
        # make the material body look open) and sub-micron pinholes; both are handled here, and a
        # larger boundary is left untouched so a real hole still fails the watertight audit.
        parts, closure = assemble_damage_bodies(
            damaged_mesh, source_volume_mm3=source_volume,
            min_material_volume_mm3=recipe.meta.get("min_material_volume_mm3"))
        damaged_mesh = parts[0] if len(parts) == 1 else damaged_mesh
    elif recipe.touches_geometry:
        parts = [mesh]
    else:
        parts = [mesh]
    components, representative_map, ledger = register_components(
        parts, clean_fragment_id=clean_fragment_id, source_volume_mm3=source_volume,
        min_support_rel=float(recipe.meta.get("min_representative_ratio", 0.005)),
        added_bodies=[(body, "CONTAMINATION") for body in outcome.added_bodies])
    if isinstance(closure, dict) and "connected_bodies" in closure:
        # one readable place for the assembly accounting: register_components only ever sees the
        # material bodies, so the engine debris dropped before it must be reported here
        ledger["assembly"] = {
            "connected_bodies": int(closure["connected_bodies"]),
            "material_bodies": int(closure["material_bodies"]),
            "non_material_bodies": int(closure["non_material_bodies"]),
            "non_material_faces": list(closure["non_material_faces"]),
            "non_material_volume_mm3": float(closure["non_material_volume_mm3"]),
            "pinholes_filled": int(closure["pinholes_filled"]),
            "watertight_bodies": int(closure["watertight_bodies"]),
        }
    lost_volume = float(ledger["lost_volume_mm3"])
    qa = {
        "status": "PASS" if outcome.realized else "FAIL",
        "identity": False, "level": int(recipe.level), "realized": bool(outcome.realized),
        "geometry_changed": bool(geometry_changed),
        "source_geometry_hash": _geometry_hash(mesh),
        "result_geometry_hash": _geometry_hash(damaged_mesh),
        "geometry_hash_unchanged": bool(_geometry_hash(damaged_mesh) == _geometry_hash(mesh)),
        "component_count": len(components),
        "ledger": ledger,
        "damage_semantics": DAMAGE_SEMANTICS,
        "assembly": closure,
        "pinhole_closure": closure,
        "sdf_pipeline": outcome.details.get("sdf_pipeline", {}),
        "failure_code": outcome.failure_code,
    }
    if not outcome.realized:
        qa["failure_code"] = qa.get("failure_code") or ErrorCode.OPERATOR_NOT_REALIZED.value
    result = PhysicalResult(
        mother_id=mother_id, clean_ref=clean_ref, event_id=event_id,
        recipe_id=recipe.recipe_id or f"{recipe.axis_id}:{recipe.variant}:L{recipe.level}",
        version=1, components=components, lost_volume_mm3=lost_volume,
        lost_volume_ratio=float(lost_volume / max(source_volume, 1e-12)),
        representative_map=representative_map, physical_truth=None, qa=qa,
        meta={
            "declared": declared, "identity": False, "ledger": ledger,
            "axis_id": recipe.axis_id, "variant": recipe.variant, "level": int(recipe.level),
            "geometry_changed": bool(geometry_changed), "frozen": recipe.frozen(),
            "source_geometry_hash": _geometry_hash(mesh),
            "damage_semantics": DAMAGE_SEMANTICS,
            "assembly": closure,
            "pinhole_closure": closure,
            "measured": dict(outcome.measurements),
            "measurement_units": dict(outcome.units),
            "details": outcome.details,
            "appearance": outcome.appearance,
            "appearance_updated": bool(outcome.appearance),
        },
    )
    if outcome.mesh is not None and geometry_changed:
        provenance = attach_face_provenance(
            result, clean_mesh=mesh, fragment=fragment,
            spacing_mm=_measured_spacing_mm(outcome),
            halo_mm=_measured_roi_halo_mm(outcome))
        result.meta["face_provenance"] = provenance
        result.qa["face_provenance"] = provenance
    else:
        # level 0 / no geometry change: the component *is* the source object and its bytes are
        # returned unchanged (identity contract), so nothing is attached.  The absence is
        # recorded instead of being left to look like "no interface here".
        result.meta["face_provenance"] = {
            "version": ORIGIN_PROVENANCE_VERSION, "attached": False,
            "reason": ("identity level 0 returns the source object unchanged; the source's own "
                       "face channels are authoritative"
                       if not geometry_changed else "the operator returned no mesh"),
        }
    _attach_physical_truth(result, clean_truth)
    return result


def _measured_spacing_mm(outcome: Any) -> float | None:
    """The SDF grid spacing the operator actually used, or ``None`` when it did not report one."""
    pipeline = dict((getattr(outcome, "details", None) or {}).get("sdf_pipeline") or {})
    for key in ("grid", "spacing", "sdf"):
        block = pipeline.get(key)
        if isinstance(block, dict) and block.get("spacing_mm") is not None:
            return float(block["spacing_mm"])
    return None


def _measured_roi_halo_mm(outcome: Any) -> float | None:
    """The operator's own ROI halo (the distance at which its ROI weight reaches zero)."""
    pipeline = dict((getattr(outcome, "details", None) or {}).get("sdf_pipeline") or {})
    value = pipeline.get("halo_mm")
    return None if value is None else float(value)


def _source_face_channels(clean_mesh: Any, fragment: Any) -> tuple[np.ndarray, np.ndarray, dict]:
    """The clean source's ``origin_kind`` / ``interface_id`` face channels (never invented)."""
    from .fields import face_channel

    n = int(len(np.asarray(clean_mesh.faces)))
    origin = face_channel(clean_mesh, fragment, "origin_kind")
    iface = face_channel(clean_mesh, fragment, "interface_id")
    info: dict[str, Any] = {
        "origin_kind_source": None if origin is None else "clean_fragment.origin_kind",
        "interface_id_source": None if iface is None else "clean_fragment.interface_id",
    }
    if origin is None:
        # no origin channel: a missing channel is *not* "everything is the mother surface"
        origin = np.full(n, ORIGIN_AMBIGUOUS, dtype=np.uint8)
        info["origin_kind_source"] = "MISSING"
    if iface is None:
        iface = np.full(n, -1, dtype=np.int32)
        info["interface_id_source"] = "MISSING"
    return (np.asarray(origin, dtype=np.uint8).reshape(-1),
            np.asarray(iface, dtype=np.int32).reshape(-1), info)


def attach_face_provenance(result: PhysicalResult, *, clean_mesh: Any, fragment: Any,
                           spacing_mm: float | None = None,
                           halo_mm: float | None = None) -> dict[str, Any]:
    """Classify every damaged face and attach ``origin_kind`` + ``interface_id`` to each component.

    This is the writer of the face-level provenance of a damaged body.  Contamination bodies are
    handled separately: they are *deposited* material with no source surface on the clean
    fragment, so no face of one is ever mapped to a clean face (mapping a dirt shell onto the wall
    it covers would relabel dirt as the original surface); they are reported as their own class.
    """
    from ..storage.mesh_io import with_face_attrs
    from .fields import face_channel, roi_faces

    declared = dict((result.meta or {}).get("declared") or {})
    roi_spec = dict(declared.get("roi") or {"kind": "interface"})
    source_origin, source_iface, channels = _source_face_channels(clean_mesh, fragment)
    measured = dict((result.meta or {}).get("measured") or {})
    recession = 0.0
    for key in ("realized_max_recession_mm", "depth_mm", "affected_depth_mm"):
        if measured.get(key) is not None:
            recession = float(measured[key])
            break
    tol_mm = origin_colocation_tolerance_mm(
        spacing_mm=spacing_mm, realized_recession_mm=recession,
        min_wall_mm=measured.get("min_thickness_mm"))
    band = float(halo_mm) if halo_mm else ORIGIN_ROI_HALO_FALLBACK_MM
    roi_ids: np.ndarray | None = None
    roi_info: dict[str, Any] = {"roi_kind": None, "roi_source": "unavailable"}
    try:
        roi_ids, roi_info = roi_faces(clean_mesh, fragment, roi_spec)
    except SynLabError as exc:
        roi_info = {"roi_kind": str(roi_spec.get("kind", "")), "roi_source": "NOT_APPLICABLE",
                    "failure_code": getattr(getattr(exc, "code", None), "value", None),
                    "reason": str(exc).splitlines()[0][:300]}

    report: dict[str, Any] = {
        "version": ORIGIN_PROVENANCE_VERSION,
        "attached": True,
        "tol_mm": float(tol_mm),
        "tol_basis": {
            "cell_fraction": ORIGIN_COLOCATION_CELL_FRACTION,
            "spacing_mm": None if spacing_mm is None else float(spacing_mm),
            "realized_recession_mm": float(recession),
            "min_wall_mm": measured.get("min_thickness_mm"),
            "bounds_mm": [ORIGIN_COLOCATION_MIN_MM, ORIGIN_COLOCATION_MAX_MM],
            "rule": "clip(0.05 + 0.5*spacing + realized_recession, [0.05, 1.0]) capped at half the "
                    "measured minimum wall thickness",
        },
        "cos_min": ORIGIN_COLOCATION_COS_MIN,
        "roi_band_mm": float(band),
        "roi": roi_info,
        "roi_faces": None if roi_ids is None else int(len(roi_ids)),
        "source_channels": channels,
        "components": {},
    }
    totals = {str(ORIGIN_MOTHER_SURFACE): 0, str(ORIGIN_INTERFACE): 0, str(ORIGIN_AMBIGUOUS): 0}
    for component in result.components:
        faces = int(len(np.asarray(component.mesh.faces)))
        if component.meta.get("is_contamination"):
            origin = np.full(faces, ORIGIN_AMBIGUOUS, dtype=np.uint8)
            iface = np.full(faces, -1, dtype=np.int32)
            with_face_attrs(component.mesh, origin_kind=origin, interface_id=iface)
            entry = {"class": "CONTAMINATION_UNMAPPED", "faces": faces,
                     "origin_kind_histogram": {str(ORIGIN_AMBIGUOUS): faces},
                     "reason": ("deposited material: it has no source surface on the clean "
                                "fragment, so no face is mapped onto one")}
        else:
            origin, iface, entry = classify_face_origin(
                component.mesh, clean_mesh, origin=source_origin, interface_id=source_iface,
                roi_ids=roi_ids, tol_mm=tol_mm, roi_tol_mm=band)
            with_face_attrs(component.mesh, origin_kind=origin, interface_id=iface)
        entry["component_id"] = str(component.component_id)
        entry["interface_id_histogram"] = {
            str(int(k)): int(v) for k, v in zip(*np.unique(np.asarray(
                (component.mesh.metadata or {}).get("face_attr_arrays", {}).get(
                    "interface_id", np.full(faces, -1)), dtype=np.int64), return_counts=True))}
        report["components"][str(component.component_id)] = entry
        for key, value in (entry.get("origin_kind_histogram") or entry.get("classes") or {}).items():
            totals[str(key)] = totals.get(str(key), 0) + int(value)
    report["totals"] = totals
    report["totals_fraction"] = {k: (v / max(sum(totals.values()), 1)) for k, v in totals.items()}
    return report


def result_recipe(result: PhysicalResult) -> DamageRecipe:
    """Rebuild the (frozen) recipe of a result: axis/variant/level + the declared ROI/params.

    ``ratio``-style readers use this to re-run the same declared ROI selection on the source
    without re-running the operator; nothing here is sampled or invented.
    """
    declared = (result.meta or {}).get("declared") or {}
    frozen = (result.meta or {}).get("frozen") or {}
    return DamageRecipe(
        axis_id=str(declared.get("axis_id", (result.meta or {}).get("axis_id", ""))),
        variant=str(declared.get("variant", (result.meta or {}).get("variant", ""))),
        level=int(declared.get("level", (result.meta or {}).get("level", 0)) or 0),
        roi=dict(declared.get("roi") or {"kind": "interface"}),
        params=dict(declared.get("params") or {}),
        grid={"spacing_mm": None},
        meta={"shortest_structure_mm": None},
    )


def _attach_physical_truth(result: PhysicalResult, clean_truth: Any) -> None:
    """Recompute residual truth through ``synlab.truth.api`` when that module is available."""
    try:  # dependency under parallel development: absence is reported, never faked
        from ..truth.api import update_residual_truth  # type: ignore
    except Exception as exc:  # pragma: no cover - parallel-development dependency
        result.meta["physical_truth_status"] = "PENDING_DEPENDENCY"
        result.meta["physical_truth_dependency"] = f"{type(exc).__name__}: {exc}"
        return
    try:
        result.physical_truth = update_residual_truth(clean_truth, result)
        result.meta["physical_truth_status"] = "UPDATED"
    except Exception as exc:  # pragma: no cover - reported honestly
        result.meta["physical_truth_status"] = "FAILED"
        result.meta["physical_truth_dependency"] = f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------- audit


def _resolve_clean(result: PhysicalResult, clean: Any) -> tuple[trimesh.Trimesh | None, str]:
    mesh = _mesh_of(clean)
    if mesh is not None:
        return mesh, "explicit"
    source_hash = (result.meta or {}).get("source_geometry_hash")
    if source_hash and source_hash in _SOURCE_MESHES:
        return _SOURCE_MESHES[source_hash], "registry"
    if clean is None:
        return None, "missing"
    return None, "unresolvable"


def audit_physical(result: PhysicalResult, clean: Any = None) -> dict[str, Any]:
    """QA for one physical damage result (plan 12.4).

    Checks ``damaged ⊆ clean``, watertightness, positive volume, minimum thickness, lost
    volume/area, source residue and out-of-ROI drift, and refuses to report success when a
    declared change was not measured (``OPERATOR_NOT_REALIZED`` / ``DAMAGE_EFFECT_MISSING``).
    The audit never repairs or re-meshes anything: geometry hashes are compared before and
    after the audit to prove it.
    """
    clean_mesh, clean_source = _resolve_clean(result, clean)
    declared = dict((result.meta or {}).get("declared") or {})
    axis_id = str(declared.get("axis_id", (result.meta or {}).get("axis_id", "")))
    variant = str(declared.get("variant", (result.meta or {}).get("variant", "")))
    level = int(declared.get("level", (result.meta or {}).get("level", 0)) or 0)
    touches_geometry = bool(declared.get("touches_geometry", True))
    measured = dict((result.meta or {}).get("measured") or {})
    appearance_axes = axis_id in APPEARANCE_AXES or (
        axis_id == "P08" and P08_VARIANTS.get(variant) == "APPEARANCE")
    checks: dict[str, Any] = {}
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, float] = {}

    hashes_before = [hash_json({"k": S.geometry_key(c.mesh), "v": float(abs(c.mesh.volume))})
                     for c in result.components]
    clean_hash_before = _geometry_hash(clean_mesh) if clean_mesh is not None else None

    if clean_mesh is None:
        return {
            "status": "NA", "axis_id": axis_id, "variant": variant, "level": level,
            "clean_source": clean_source, "checks": checks, "failure_codes": ["INPUT_UNAVAILABLE"],
            "reason": "clean source geometry unavailable for the subset/watertight audit",
            "measured": metrics, "no_auto_repair": {"geometry_hashes_unchanged": None},
        }

    source_volume = float(abs(clean_mesh.volume))
    damaged_volume = float(sum(c.volume_mm3 for c in result.components if not c.meta.get("is_contamination")))
    added_volume = float(sum(c.volume_mm3 for c in result.components if c.meta.get("is_contamination")))
    metrics.update({
        "source_volume_mm3": source_volume, "damaged_volume_mm3": damaged_volume,
        "added_volume_mm3": added_volume, "lost_volume_mm3": result.lost_volume_mm3,
        "lost_volume_ratio": result.lost_volume_ratio,
        "component_count": float(len(result.components)),
        "declared_level": float(level),
    })

    # ---- damaged ⊆ clean (measured on the damaged surface, tolerance disclosed)
    tol_mm = float((result.qa.get("ledger", {}) or {}).get("outside_tol_mm", 1e-3))
    outside_stats = []
    for component in result.components:
        if component.meta.get("is_contamination"):
            continue
        stats = subset_outside_stats(component.mesh, clean_mesh, n_samples=1200, tol_mm=tol_mm,
                                     seed=len(outside_stats))
        outside_stats.append(stats)
    worst_outside = max((s["max_outside_mm"] for s in outside_stats), default=0.0)
    worst_fraction = max((s["outside_fraction"] for s in outside_stats), default=0.0)
    legacy_outside = [s.get("approx_open3d") or {} for s in outside_stats]
    checks["damaged_subset_clean"] = {
        "tol_mm": tol_mm, "max_outside_mm": worst_outside, "outside_fraction": worst_fraction,
        "samples": int(sum(s["samples"] for s in outside_stats)),
        "outside_points": int(sum(s["outside_points"] for s in outside_stats)),
        "p99_outside_mm": max((s["p99_outside_mm"] for s in outside_stats), default=0.0),
        "instrument": "trimesh.proximity.signed_distance (exact, float64; positive = inside)",
        # the superseded Open3D instrument, kept beside the exact numbers (plan 12.4 evidence):
        # its own floor on this data is 0.0161 mm / 0.28 % for a surface measured against itself
        "approx_open3d_max_outside_mm": max((s.get("max_outside_mm", 0.0)
                                             for s in legacy_outside), default=0.0),
        "pass": bool(worst_outside <= max(tol_mm, 5e-4)),
    }
    metrics["max_outside_mm"] = worst_outside
    if not checks["damaged_subset_clean"]["pass"]:
        failures.append("DAMAGED_NOT_SUBSET_OF_CLEAN")

    # ---- watertight / positive volume / winding
    reports = [(c.component_id, S.watertight_report(c.mesh)) for c in result.components]
    non_watertight = [cid for cid, report in reports if not report["watertight"]]
    non_positive = [cid for cid, report in reports if not report["positive_volume"]]
    checks["watertight"] = {"non_watertight": non_watertight,
                            "pass": bool(not non_watertight or not touches_geometry),
                            "per_component": {cid: report["watertight"] for cid, report in reports}}
    checks["positive_volume"] = {"non_positive": non_positive, "pass": bool(not non_positive)}
    if non_watertight and touches_geometry:
        failures.append("NOT_WATERTIGHT")
    if non_positive:
        failures.append("NON_POSITIVE_VOLUME")

    # ---- thickness
    thickness_rows = []
    for component in result.components:
        if len(component.mesh.faces) < 4:
            continue
        thickness_rows.append((component.component_id,
                               S.ray_thickness(component.mesh, n_samples=200, seed=17)))
    min_thickness = min((row[1]["min_mm"] for row in thickness_rows), default=0.0)
    guard = (result.meta or {}).get("min_wall_thickness_mm")
    checks["min_thickness"] = {"min_mm": min_thickness,
                               "guard_mm": guard,
                               "pass": bool(guard is None or min_thickness >= float(guard) * 0.999),
                               "per_component": {cid: row["min_mm"] for cid, row in thickness_rows}}
    metrics["min_thickness_mm"] = min_thickness
    if guard is not None and min_thickness < float(guard) * 0.999:
        failures.append("THICKNESS_GUARD_VIOLATED")

    # ---- loss bookkeeping
    ledger = dict((result.meta or {}).get("ledger") or {})
    measured_lost = max(0.0, source_volume - damaged_volume)
    loss_error = abs(measured_lost - float(result.lost_volume_mm3))
    checks["loss_accounting"] = {
        "measured_lost_volume_mm3": measured_lost,
        "declared_lost_volume_mm3": float(result.lost_volume_mm3),
        "absolute_error_mm3": loss_error,
        "relative_error": float(loss_error / max(source_volume, 1e-12)),
        "passed = ledger_conservation": bool(ledger.get("conservation_ok", True)),
        "pass": bool(loss_error <= max(1e-6 * source_volume, 1e-6)),
    }
    metrics["measured_lost_volume_mm3"] = measured_lost
    if not checks["loss_accounting"]["pass"]:
        failures.append("LOSS_ACCOUNTING_MISMATCH")

    # ---- source residue and out-of-ROI drift (geometry axes with an interface ROI)
    residue = None
    drift = measured.get("roi_external_drift_mm")
    if touches_geometry and not appearance_axes:
        try:
            from .operators import SdfContext

            ctx = SdfContext(clean_mesh, DamageRecipe(axis_id=axis_id, variant=variant, level=level,
                                                      roi=(result.meta.get("declared", {}) or {}).get("roi")
                                                      or {"kind": "interface"},
                                                      grid={"spacing_mm": None},
                                                      meta={"shortest_structure_mm": None})
                             if False else _context_recipe(result, axis_id, variant, level))
            residue = ctx.contact_state(result.components[0].mesh)
        except Exception as exc:
            residue = {"unavailable": f"{type(exc).__name__}: {exc}"}
    if residue is not None and "unavailable" not in residue:
        metrics["source_residue_fraction"] = float(residue["residual_fraction"])
        checks["source_residue"] = {"residual_fraction": float(residue["residual_fraction"]),
                                    "residual_area_mm2": float(residue["residual_area_mm2"]),
                                    "lost_area_mm2": float(residue["lost_area_mm2"]),
                                    "measured": True}
    elif residue is not None:
        checks["source_residue"] = {"measured": False, "reason": residue["unavailable"]}
    if drift is not None:
        metrics["roi_external_drift_mm"] = float(drift)
        checks["roi_external_drift"] = {"max_mm": float(drift),
                                        "pass": bool(float(drift) <= 1e-3)}

    # ---- appearance axes must not change geometry
    if appearance_axes:
        source_hash = (result.meta or {}).get("source_geometry_hash")
        result_hashes = {_geometry_hash(c.mesh) for c in result.components}
        unchanged = bool(source_hash in result_hashes)
        checks["geometry_hash_unchanged"] = {"source_hash": source_hash,
                                             "component_hashes": sorted(result_hashes),
                                             "pass": unchanged}
        appearance = (result.meta or {}).get("appearance") or {}
        changed_texels = float(np.sum(np.any(
            np.asarray(appearance.get("texel_albedo")) != 0, axis=-1))) if appearance.get("texel_albedo") is not None else 0.0
        metrics["appearance_arrays"] = float(len(appearance))
        metrics["appearance_texels_touched"] = changed_texels
        checks["appearance_effect"] = {"arrays": sorted(appearance), "pass": bool(appearance)}
        if not unchanged:
            failures.append("APPEARANCE_CHANGED_GEOMETRY")
        if level > 0 and not appearance:
            failures.append(ErrorCode.OPERATOR_NOT_REALIZED.value)

    # ---- declared change must be measured
    declared_effect = dict((result.meta or {}).get("declared", {}).get("expected") or {})
    if level > 0:
        effect_present = True
        if appearance_axes:
            effect_present = bool((result.meta or {}).get("appearance"))
        elif touches_geometry:
            effect_present = bool(measured_lost > 1e-12 or added_volume > 1e-12)
        checks["declared_effect_measured"] = {
            "effect_present": effect_present,
            "geometry_changed": bool((result.meta or {}).get("geometry_changed", False)),
            "declared_expectation": declared_effect or None,
            "pass": effect_present,
        }
        if not effect_present:
            failures.append(ErrorCode.OPERATOR_NOT_REALIZED.value)
        target = declared_effect.get("target")
        realized_value = declared_effect.get("realized_key")
        if target is not None and realized_value and realized_value in measured:
            tol = float(declared_effect.get("tolerance", 0.01))
            achieved = float(measured[realized_value])
            deviation = abs(achieved - float(target))
            checks["declared_effect_target"] = {"target": float(target), "achieved": achieved,
                                                "tolerance": tol, "deviation": deviation,
                                                "pass": bool(deviation <= tol)}
            if deviation > tol:
                failures.append(ErrorCode.DAMAGE_EFFECT_MISSING.value)
    else:
        identity_ok = all(c.meta.get("identity", False) for c in result.components)
        checks["identity_level"] = {"pass": bool(identity_ok), "level": level}

    # ---- the audit must not have modified anything
    hashes_after = [hash_json({"k": S.geometry_key(c.mesh), "v": float(abs(c.mesh.volume))})
                    for c in result.components]
    clean_hash_after = _geometry_hash(clean_mesh) if clean_mesh is not None else None
    no_repair = {
        "geometry_hashes_unchanged": bool(hashes_before == hashes_after),
        "clean_hash_unchanged": bool(clean_hash_before == clean_hash_after),
        "repair_applied": False,
    }
    if not no_repair["geometry_hashes_unchanged"] or not no_repair["clean_hash_unchanged"]:
        failures.append("AUDIT_MUTATED_GEOMETRY")

    status = "PASS" if not failures else "FAIL"
    if level > 0 and not measured and not appearance_axes:
        status = "FAIL"
        failures.append(ErrorCode.OPERATOR_NOT_REALIZED.value)
    return {
        "status": status, "axis_id": axis_id, "variant": variant, "level": level,
        "clean_source": clean_source, "checks": checks, "failure_codes": sorted(set(failures)),
        "warnings": warnings, "measured": metrics, "declared": declared,
        "ledger": ledger, "no_auto_repair": no_repair,
        "damage_semantics": str((result.meta or {}).get("damage_semantics", DAMAGE_SEMANTICS_V1)),
        "subset_instrument": checks["damaged_subset_clean"]["instrument"],
        "pinhole_closure": dict((result.meta or {}).get("pinhole_closure") or {}),
        "representative_map": dict(result.representative_map),
        "components": [{"component_id": c.component_id, "status": c.status,
                        "volume_mm3": c.volume_mm3, "is_representative": c.is_representative,
                        "ancestor": c.meta.get("clean_fragment_ancestor"),
                        "same_ancestor_subfragment": c.meta.get("same_ancestor_subfragment", False)}
                       for c in result.components],
    }


def _context_recipe(result: PhysicalResult, axis_id: str, variant: str, level: int) -> DamageRecipe:
    declared = (result.meta or {}).get("declared") or {}
    return DamageRecipe(axis_id=axis_id, variant=variant, level=level,
                        roi=dict(declared.get("roi") or {"kind": "interface"}),
                        params=dict(declared.get("params") or {}),
                        grid={"spacing_mm": None},
                        meta={"shortest_structure_mm": None})


def _component_payload(component: PhysicalComponent) -> dict[str, Any]:
    """Mesh payload of one physical component (one writer for both commit helpers)."""
    from ..storage.mesh_io import mesh_arrays

    return dict(mesh_arrays(component.mesh))


def _jsonable(value: Any) -> Any:
    """JSON-safe copy of a measured structure (numpy scalars/arrays reduced, never guessed)."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.reshape(-1).tolist()]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _component_meta(component: PhysicalComponent, result: PhysicalResult) -> dict[str, Any]:
    """Component metadata; the single place that defines the component asset contract."""
    provenance = dict((result.meta or {}).get("face_provenance") or {})
    own = dict((provenance.get("components") or {}).get(str(component.component_id)) or {})
    return {"component_id": component.component_id, "volume_mm3": component.volume_mm3,
            "is_representative": component.is_representative, "status": component.status,
            "ancestor": component.meta.get("clean_fragment_ancestor"),
            "recipe_id": result.recipe_id, "clean_ref": result.clean_ref,
            "axis_id": result.meta.get("axis_id"), "level": result.meta.get("level"),
            # the delivered mesh is closed/legal under this semantics version
            "damage_semantics": str((result.meta or {}).get("damage_semantics",
                                                            DAMAGE_SEMANTICS_V1)),
            # the evidence behind the face labels of *this* component (tolerances, hit rate,
            # class counts/areas).  The labels themselves are the ``face__origin_kind`` /
            # ``face__interface_id`` arrays of the same asset.
            "face_provenance": _jsonable({
                "version": provenance.get("version", ORIGIN_PROVENANCE_VERSION),
                "attached": bool(provenance.get("attached", False)),
                "reason": provenance.get("reason"),
                "tol_mm": provenance.get("tol_mm"), "tol_basis": provenance.get("tol_basis"),
                "cos_min": provenance.get("cos_min"), "roi_band_mm": provenance.get("roi_band_mm"),
                "roi": provenance.get("roi"), "roi_faces": provenance.get("roi_faces"),
                "source_channels": provenance.get("source_channels"),
                "component": own,
            })}


def commit_physical(store: Any, result: PhysicalResult, *, lineage_id: str | None = None,
                    split: str | None = None, component_index: int = 0,
                    run_id: str | None = None) -> Any:
    """Commit the representative component mesh as a physical asset (role from roles.py).

    ``run_id`` is an optional addition to the frozen signature: written into the asset metadata
    only when supplied, so existing callers keep their exact metadata and asset id.  It is what
    makes the component visible to the run-scoped gate/audit readers, which select assets by
    ``meta["run_id"]``.
    """
    if not result.components:
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING, "physical result has no components",
                          stage="physical.commit")
    representative = None
    for component in result.components:
        if component.is_representative:
            representative = component
            break
    component = representative or result.components[int(component_index)]
    meta = _component_meta(component, result)
    if run_id is not None:
        meta["run_id"] = str(run_id)
    return store.commit_asset(
        role=ROLE_PHYSICAL_COMPONENT, schema=SCHEMA_PHYSICAL, unit=UNIT_MM,
        frame=FRAME_FRAGMENT,
        payload=_component_payload(component),
        meta=meta,
        qa=dict(result.qa), lineage_id=lineage_id, split=split,
        ancestry=[result.clean_ref] if result.clean_ref else [],
    )


#: Units of the metrics ``audit_physical`` measures.  Anything the operator itself measured keeps
#: the unit it declared in ``result.meta["measurement_units"]``; the audit metrics are named by
#: suffix so a new metric cannot silently claim a unit it does not have.
_AUDIT_METRIC_BASE_UNITS = {
    "component_count": "1", "declared_level": "1", "measured_lost_volume_mm3": "mm3",
    "lost_volume_mm3": "mm3", "lost_volume_ratio": "1", "source_residue_fraction": "1",
    "appearance_arrays": "1", "appearance_texels_touched": "px",
}


def _measured_units(name: str, declared: dict[str, Any]) -> str:
    if name in declared:
        return str(declared[name])
    if name in _AUDIT_METRIC_BASE_UNITS:
        return _AUDIT_METRIC_BASE_UNITS[name]
    for suffix, unit in (("_mm3", "mm3"), ("_mm2", "mm2"), ("_mm", "mm"),
                         ("_ratio", "1"), ("_fraction", "1"), ("_px", "px")):
        if name.endswith(suffix):
            return unit
    return "1"


def _audit_verdict(audit: dict[str, Any] | None) -> str:
    """QA verdict of a physical result: only an explicitly measured PASS passes (fail closed)."""
    from ..storage.store import QA_FAIL, QA_PASS

    return QA_PASS if str((audit or {}).get("status", "")) == "PASS" else QA_FAIL


def commit_physical_result(store: Any, result: PhysicalResult, *, audit: dict[str, Any],
                           clean_asset_id: str | None = None, clean_asset_hash: str | None = None,
                           component_asset_id: str | None = None, revision: int | None = None,
                           lineage_id: str | None = None, split: str | None = None,
                           run_id: str | None = None) -> Any:
    """Commit the PhysicalPack *result* asset (plan 4.1, 30.8): recipe + loss + survivors.

    Plan 4.1 requires the PhysicalPack to carry, besides the damaged mesh, the damage recipe,
    the survivor map, the lost volume and a revision/hash that preserves the clean reference.
    ``commit_physical`` commits the *component* (the mesh); this helper commits the result
    record of the same operator run:

    * ``measurement``            -- the metrics ``audit_physical`` actually measured, with units;
    * ``representative_map``     -- clean fragment id -> surviving representative component id;
    * ``components``             -- counts including debris / contamination / supportable;
    * ``lost_volume_mm3`` / ``lost_volume_ratio`` / ``ledger`` -- the material ledger;
    * ``recipe_id`` / ``axis_id`` / ``variant`` / ``level`` / ``recipe`` -- the frozen factor;
    * ``revision`` and the input hash (``source_asset_id`` + ``source_hash`` = the committed
      clean asset the damage was applied to, plus the clean *geometry* hash);
    * ``qa``                     -- the full audit block; the asset verdict is its ``status``.

    Nothing here is a default: without an audit result (a real measurement) the call fails,
    and a level the auditor did not confirm as ``PASS`` is committed as ``QA_FAIL`` instead of
    being promoted by hand.
    """
    if not isinstance(audit, dict) or not audit:
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING,
                          "commit_physical_result needs the audit_physical() measurement",
                          stage="physical.commit_result")
    if not result.components:
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING, "physical result has no components",
                          stage="physical.commit_result")
    measured = {str(k): float(v) for k, v in (audit.get("measured") or {}).items()}
    declared_units = dict((result.meta or {}).get("measurement_units") or {})
    names = sorted(measured)
    payload: dict[str, Any] = {
        "component_volume_mm3": np.asarray([float(c.volume_mm3) for c in result.components],
                                           dtype=np.float64),
        "component_is_representative": np.asarray(
            [bool(c.is_representative) for c in result.components], dtype=bool),
        "component_supportable": np.asarray(
            [bool(c.meta.get("supportable", c.is_representative)) for c in result.components],
            dtype=bool),
        "component_is_contamination": np.asarray(
            [bool(c.meta.get("is_contamination", False)) for c in result.components], dtype=bool),
        "measurement_values": np.asarray([measured[k] for k in names], dtype=np.float64),
    }
    status = str(audit.get("status", ""))
    meta = {
        "layer": "physical",
        "role": "physical_pack_result",
        "recipe_id": result.recipe_id,
        "axis_id": (result.meta or {}).get("axis_id"),
        "variant": (result.meta or {}).get("variant"),
        "level": (result.meta or {}).get("level"),
        "identity": bool((result.meta or {}).get("identity", False)),
        "revision": int(result.version if revision is None else revision),
        "lost_volume_mm3": float(result.lost_volume_mm3),
        "lost_volume_ratio": float(result.lost_volume_ratio),
        "representative_map": {str(k): str(v) for k, v in (result.representative_map or {}).items()},
        "components": {
            "count": len(result.components),
            "core": int(sum(1 for c in result.components if c.status == "CORE")),
            "debris": int(sum(1 for c in result.components if c.status == "DEBRIS")),
            "supportable": int(sum(1 for c in result.components
                                   if c.meta.get("supportable", c.is_representative))),
            "contamination": int(sum(1 for c in result.components
                                     if c.meta.get("is_contamination", False))),
            "component_ids": [c.component_id for c in result.components],
        },
        "clean_ref": result.clean_ref,
        "mother_id": result.mother_id,
        "event_id": result.event_id,
        "source_asset_id": clean_asset_id,
        "source_hash": clean_asset_hash,
        "source_geometry_hash": (result.meta or {}).get("source_geometry_hash"),
        "result_geometry_hash": (result.qa or {}).get("result_geometry_hash"),
        "component_asset_id": component_asset_id,
        "ledger": dict((result.meta or {}).get("ledger") or audit.get("ledger") or {}),
        "recipe": {"params": (result.meta or {}).get("declared", {}).get("params"),
                   "roi": (result.meta or {}).get("declared", {}).get("roi"),
                   "frozen": (result.meta or {}).get("frozen"),
                   "basis_source": ((result.meta or {}).get("frozen") or {}).get("basis_source")},
        "measurement": measured,
        "measurement_names": names,
        "measurement_units": {k: _measured_units(k, declared_units) for k in names},
        "measurement_units_declared": {str(k): str(v) for k, v in declared_units.items()},
        "qa": dict(audit),
        "qa_status_source": "physical.audit_physical.status",
        "qa_fail_closed": True,
        "audit_status": status,
        "audit_failure_codes": list(audit.get("failure_codes") or []),
        # the semantics marker of the damage contract this asset was produced under: a later
        # reader can tell a subset_v1 asset from a subset_v2 one without looking at timestamps
        # (docs/a12/data_semantics_versions.md)
        "damage_semantics": str((result.meta or {}).get("damage_semantics",
                                                        DAMAGE_SEMANTICS_V1)),
        "subset_instrument": ((audit.get("checks") or {}).get("damaged_subset_clean") or {}
                              ).get("instrument"),
        # face-level provenance of the damaged body: the class counts/areas, the declared
        # tolerances and the mapping hit rate behind the ``face__origin_kind`` arrays of the
        # component asset of this result
        "face_provenance": _jsonable((result.meta or {}).get("face_provenance") or {}),
        "face_channel_arrays": ["face__origin_kind", "face__interface_id"],
        "run_id": run_id,
    }
    ancestry = [a for a in (clean_asset_id, component_asset_id) if a]
    record = store.commit_asset(
        role=ROLE_PHYSICAL_RESULT, schema=SCHEMA_PHYSICAL, unit=UNIT_MM, frame=FRAME_FRAGMENT,
        payload=payload, meta=meta, qa=dict(audit), qa_status=_audit_verdict(audit),
        ancestry=ancestry, lineage_id=lineage_id, split=split,
    )
    return record


__all__ = ["apply_damage", "assemble_damage_bodies", "attach_face_provenance", "audit_physical",
           "classify_face_origin", "close_numerical_pinholes", "material_volume_floor",
           "origin_colocation_tolerance_mm", "register_components", "commit_physical",
           "commit_physical_result", "result_recipe", "subset_outside_stats",
           "DAMAGE_SEMANTICS", "DAMAGE_SEMANTICS_V1", "ORIGIN_PROVENANCE_VERSION",
           "DamageRecipe", "DamageOutcome"]
