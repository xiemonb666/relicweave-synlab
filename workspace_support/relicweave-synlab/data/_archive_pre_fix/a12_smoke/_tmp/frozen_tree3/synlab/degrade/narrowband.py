"""Edge-local narrow-band kernels for the P02 / P03 / P04 geometry axes.

Why this module exists (measured, not assumed)
----------------------------------------------
``synlab.physical.operators`` extracts every geometry axis through one **global uniform** grid
(``SdfContext``) whose spacing is frozen by ``choose_spacing`` as
``min(min_wall_thickness/6, shortest_structure/4)``.  On the built-in probe body
(24 x 18 x 3.2 mm slab) the measured thickness is ``min_mm = 1.2446 mm``, so
``spacing = 0.5246 mm`` and the grid is 51 x 40 x 12 nodes.  Two axes declare effects **below**
that spacing:

* ``P02``: a 90 deg edge with ``edge_width_mm = 0.4`` needs a recession of
  ``r/sin(psi) - r = 0.1657 mm`` -- 0.32 of one grid spacing.
* ``P03``: ``depth_mm`` levels 0.05 / 0.1 / 0.25 mm -- 0.10 / 0.19 / 0.48 of one grid spacing.

A level set perturbed by less than half a cell does not produce a closed marching-cubes surface,
so ``intersect_with_source`` receives an open mesh and the ``manifold`` engine rejects it with
``ValueError: Not all meshes are volumes!``.  That is the measured ``PRECISION_NOT_REALIZED`` of
the shipped audit (146 PASS / 9 FAIL / 0 NA).  Raising the node budget alone does not help: the
*surface* a coarse extraction produces drifts from the real surface by far more than the
declared recession (measured at spacing 0.25 mm on the probe: 3.01 mm3 of spurious loss against a
declared 0.28 mm3).

Two rejected alternatives (kept here as negative evidence)
----------------------------------------------------------
1. *Global level set at a finer spacing.*  Spacing 0.05 mm over the probe needs 12.3 M nodes;
   spacing 0.12 mm still fails the intersection, and the volume error stays ~10x the declared
   effect.
2. *Analytic fillet prism subtracted from the source.*  The section geometry itself is exact
   (verified: 90 deg / r=0.4 -> depth 0.165685 mm, contact 0.4 mm, area 0.034336 mm2), but the
   subtraction is not usable here:
   ``manifold`` needs an inset of about ``1e-3 * r`` before the result is watertight (measured:
   inset 0 and 1e-4 -> non-manifold edges; inset 1e-3 -> watertight), and that inset then leaves
   large parts of the cutter *outside* the source, because the probe's interface carries a real
   0.18 mm roughness while the cutter is built from the ideal face planes.  Measured cutter
   leakage outside the source: 37 % of the cutter surface, up to 0.147 mm.  A 0.066 mm fillet
   cannot be cut into a surface whose own roughness is 0.18 mm.

What this module does instead (plan 12.1/12.2 "narrow band / adaptive", 30.7)
-----------------------------------------------------------------------------
Both axes are evaluated **only where the declared effect is non-zero**, and the result is a
*closed body* obtained by moving the affected surface along its own vertex normals:

* ``recessed_body`` (P03, plan 12.2 "坯体侵蚀") applies a non-negative smooth depth field pinned
  to zero on the ROI rim;
* ``edge_recession_body`` (P02, plan 12.2 "边缘磨圆") applies the analytic inward rolling-ball
  profile, keyed by the lateral distance to the convex edges **on the boundary of the ROI**, so
  the perturbation has compact support and the rim never moves.

The body stays closed by construction, the untouched surface keeps the *original* triangles (so
there is no extraction drift at all) and the membership claim ``damaged ⊆ clean`` holds to 1e-6
mm (measured).  No level set, no marching cubes and no signed-distance query is re-implemented
here; booleans and measurements come from ``trimesh``/``synlab.physical``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import trimesh

from ..errors import ErrorCode, SynLabError
from ..physical import fields as F
from ..physical import sdf as S

__all__ = [
    "roi_boundary_edges",
    "roi_rim_vertices",
    "edge_sections",
    "edge_recession_body",
    "recessed_body",
    "paired_thickness",
    "assert_watertight",
]

#: Default minimum dihedral angle (deg) for an edge to count as a sharp convex ROI boundary edge.
MIN_EDGE_ANGLE_DEG = 45.0


# ---------------------------------------------------------------------------- ROI edges
def roi_boundary_edges(mesh: trimesh.Trimesh, roi_faces: np.ndarray, *,
                       min_angle_deg: float = MIN_EDGE_ANGLE_DEG
                       ) -> tuple[list[tuple[int, int, int, int]], dict[str, Any]]:
    """Sharp convex edges **on the boundary of the ROI face set**.

    An edge counts when exactly one of its two adjacent faces belongs to ``roi_faces`` and the
    dihedral angle between those faces exceeds ``min_angle_deg``.  For the probe's tagged
    interface this is the closed 96-segment perimeter loop of the rough top face (measured: 210
    sharp edges in the whole body, 210/210 above 45 deg, of which 96 are ROI boundary and 114 are
    away from it; total boundary length 84.172 mm, every endpoint has degree 2).

    Returns ``[(face_a, face_b, vertex_a, vertex_b), ...]`` plus the measurement dict.
    """
    faces = np.asarray(mesh.faces, dtype=np.int64)
    inside = np.zeros(len(faces), dtype=bool)
    inside[np.asarray(roi_faces, dtype=np.int64)] = True
    adjacency = np.asarray(mesh.face_adjacency, dtype=np.int64)
    # trimesh 5.x: face_adjacency_angles is in RADIANS (0..pi).  Reading it as degrees silently
    # yields an empty edge set, so convert explicitly.
    angles = np.rad2deg(np.asarray(mesh.face_adjacency_angles, dtype=np.float64))
    edge_ids = np.asarray(mesh.face_adjacency_edges, dtype=np.int64)
    out: list[tuple[int, int, int, int]] = []
    boundary_angles: list[float] = []
    for index in range(len(adjacency)):
        a, b = int(adjacency[index][0]), int(adjacency[index][1])
        if bool(inside[a]) == bool(inside[b]):
            continue
        boundary_angles.append(float(angles[index]))
        if float(angles[index]) < float(min_angle_deg):
            continue
        edge = edge_ids[index]
        out.append((a, b, int(edge[0]), int(edge[1])))
    info = {
        "roi_faces": int(len(roi_faces)),
        "sharp_edges_total": int(np.sum(angles >= float(min_angle_deg))),
        "boundary_edges_any_angle": int(len(boundary_angles)),
        "boundary_edges": len(out),
        "min_angle_deg": float(min_angle_deg),
        "median_dihedral_deg": float(np.median(boundary_angles)) if boundary_angles else 0.0,
        "angle_units": "deg (converted from trimesh's radians)",
    }
    return out, info


def roi_rim_vertices(mesh: trimesh.Trimesh, roi_faces: np.ndarray) -> np.ndarray:
    """Vertices shared by the ROI face set and the rest of the surface (the fixed rim)."""
    faces = np.asarray(mesh.faces, dtype=np.int64)
    inside = np.zeros(len(faces), dtype=bool)
    inside[np.asarray(roi_faces, dtype=np.int64)] = True
    adjacency = np.asarray(mesh.face_adjacency, dtype=np.int64)
    edge_ids = np.asarray(mesh.face_adjacency_edges, dtype=np.int64)
    rim: set[int] = set()
    for index in range(len(adjacency)):
        a, b = int(adjacency[index][0]), int(adjacency[index][1])
        if bool(inside[a]) == bool(inside[b]):
            continue
        rim.add(int(edge_ids[index][0]))
        rim.add(int(edge_ids[index][1]))
    # deterministic order so every level pins the same vertices
    return np.asarray(sorted(rim), dtype=np.int64)


# ---------------------------------------------------------------------------- sections
def edge_sections(mesh: trimesh.Trimesh, edges: list[tuple[int, int, int, int]]
                  ) -> dict[str, Any]:
    """Per-edge inward rolling-ball section: segment, bisector, wedge half-angle, depth.

    ``psi`` is the wedge **half-angle** measured between the two inward face directions
    (``theta = 2*psi``).  The ball of radius ``r`` touches each face at ``r/tan(psi)`` from the
    edge and reaches ``r/sin(psi) - r`` along the bisector -- the exact value the shipped P02
    depth rule computes (probe: 0.1657 mm at ``edge_width_mm = 0.4``).

    Both inward directions are projected onto the plane perpendicular to the edge first: the
    probe's rough top face tilts by up to ~8 deg, and using the raw normals sheared the section
    along the edge.
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    starts: list[np.ndarray] = []
    ends: list[np.ndarray] = []
    bisectors: list[np.ndarray] = []
    psis: list[float] = []
    for face_a, face_b, vertex_a, vertex_b in edges:
        p = vertices[vertex_a]
        q = vertices[vertex_b]
        length = float(np.linalg.norm(q - p))
        if length <= 1e-9:
            continue
        axis = (q - p) / length
        inward = []
        ok = True
        for face in (face_a, face_b):
            value = normals[face] - float(normals[face] @ axis) * axis
            norm = float(np.linalg.norm(value))
            if norm < 1e-9:
                ok = False
                break
            inward.append(-value / norm)
        if not ok:
            continue
        cos_theta = float(np.clip(inward[0] @ inward[1], -1.0, 1.0))
        theta = float(np.arccos(cos_theta))
        if theta <= 1e-6 or theta >= np.pi - 1e-6:
            continue
        bisector = inward[0] + inward[1]
        bisector = bisector / max(float(np.linalg.norm(bisector)), 1e-12)
        starts.append(p)
        ends.append(q)
        bisectors.append(bisector)
        psis.append(theta / 2.0)
    if not starts:
        return {"segments": np.zeros((0, 2, 3)), "bisectors": np.zeros((0, 3)),
                "psi_rad": np.zeros(0), "max_depth_mm": 0.0, "contact_mm": 0.0,
                "theta_median_deg": 0.0, "count": 0}
    psis_arr = np.asarray(psis, dtype=np.float64)
    return {
        "segments": np.stack([np.asarray(starts), np.asarray(ends)], axis=1),
        "bisectors": np.asarray(bisectors, dtype=np.float64),
        "psi_rad": psis_arr,
        "count": int(len(starts)),
        "max_depth_mm": float(1.0 / np.sin(psis_arr.min()) - 1.0),
        "min_depth_mm": float(1.0 / np.sin(psis_arr.max()) - 1.0),
        "contact_mm": float(1.0 / np.tan(psis_arr.min())),
        "theta_median_deg": float(np.degrees(2.0 * np.median(psis_arr))),
        "theta_min_deg": float(np.degrees(2.0 * psis_arr.min())),
        "theta_max_deg": float(np.degrees(2.0 * psis_arr.max())),
        "edge_length_total_mm": float(np.sum(np.linalg.norm(
            np.asarray(ends) - np.asarray(starts), axis=1))),
    }


def edge_recession_depth(points: np.ndarray, sections: dict[str, Any], radius: float
                         ) -> tuple[np.ndarray, dict[str, float]]:
    """Removed depth at every point for an inward rolling-ball fillet of ``radius``.

    ``rho`` is the lateral distance to the nearest edge segment and ``eta`` the signed component
    along that segment's bisector.  Inside the affected band the removed material is the part of
    the cross-section that lies **between the edge and the tangent line at distance rho** along
    the bisector, so the depth is ``r/sin(psi) - r/cos(alpha)`` with ``sin(alpha) = rho/r``.
    The depth vanishes at ``rho >= r``, where the tangent line has been swept away -- that is the
    compact support which keeps the rim fixed.
    """
    pts = np.asarray(points, dtype=np.float64)
    segments = np.asarray(sections["segments"], dtype=np.float64)
    bisectors = np.asarray(sections["bisectors"], dtype=np.float64)
    psis = np.asarray(sections["psi_rad"], dtype=np.float64)
    radius = float(radius)
    if pts.size == 0 or len(segments) == 0 or radius <= 0:
        return np.zeros(len(pts), dtype=np.float64), {
            "points": int(len(pts)), "affected": 0, "max_depth_mm": 0.0}
    best_rho = np.full(len(pts), np.inf)
    best_eta = np.zeros(len(pts), dtype=np.float64)
    best_psi = np.full(len(pts), np.pi / 4.0)
    for index in range(len(segments)):
        a = segments[index, 0]
        b = segments[index, 1]
        ab = b - a
        length = float(np.linalg.norm(ab))
        if length <= 1e-12:
            continue
        direction = ab / length
        rel = pts - a[None, :]
        t = np.clip(rel @ direction, 0.0, length)
        offset = rel - t[:, None] * direction[None, :]
        rho = np.linalg.norm(offset, axis=1)
        better = rho < best_rho
        if not bool(np.any(better)):
            continue
        best_rho[better] = rho[better]
        best_eta[better] = offset[better] @ bisectors[index]
        best_psi[better] = psis[index]
    contact = radius / np.tan(best_psi)
    max_depth = radius / np.sin(best_psi) - radius
    ratio = np.clip(best_rho / radius, 0.0, 1.0)
    sin_alpha = np.sqrt(np.maximum(1.0 - ratio ** 2, 0.0))
    tangent_line = np.where(sin_alpha > 1e-12, radius / np.maximum(sin_alpha, 1e-12), radius)
    depth = np.maximum(max_depth - (tangent_line - radius), 0.0)
    inside = (best_rho < radius) & (best_eta > -1e-9)
    depth = np.where(inside, np.minimum(depth, max_depth), 0.0)
    depth = np.where(np.isfinite(depth), depth, 0.0)
    return depth, {
        "points": int(len(pts)), "affected": int(np.count_nonzero(depth > 0)),
        "max_depth_mm": float(depth.max()), "contact_mm": float(np.max(contact)),
        "median_psi_deg": float(np.degrees(np.median(best_psi))),
    }


# ---------------------------------------------------------------------------- bodies
def _offset_body(mesh: trimesh.Trimesh, depth: np.ndarray) -> trimesh.Trimesh:
    """Move every vertex along its own area-weighted vertex normal by ``depth`` (mm, inward)."""
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    vertex_normal = np.zeros((len(vertices), 3), dtype=np.float64)
    for corner in range(3):
        np.add.at(vertex_normal, faces[:, corner], normals * areas[:, None])
    norms = np.linalg.norm(vertex_normal, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1.0
    vertex_normal = vertex_normal / norms
    depth = np.asarray(depth, dtype=np.float64).reshape(-1).copy()
    moved = np.zeros_like(depth)
    positive = depth > 0.0
    moved[positive] = depth[positive]
    out = trimesh.Trimesh(vertices=vertices - vertex_normal * moved[:, None], faces=faces,
                          process=False)
    trimesh.repair.fix_winding(out)
    trimesh.repair.fix_inversion(out)
    return out


def edge_recession_body(mesh: trimesh.Trimesh, edges: list[tuple[int, int, int, int]],
                        radius: float) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    """Body with the inward rolling-ball recession applied on the ROI boundary edges."""
    sections = edge_sections(mesh, edges)
    if sections["count"] == 0:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE,
                          "no usable convex ROI boundary edge section for P02",
                          stage="degrade.narrowband.edge_recession_body")
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    depth, stats = edge_recession_depth(vertices, sections, radius)
    if not bool(np.any(depth > 0)):
        raise SynLabError(ErrorCode.DAMAGE_EFFECT_MISSING,
                          f"P02: the fillet radius {radius:.4g} mm moves no vertex "
                          f"(smallest edge vertex spacing exceeds the contact width)",
                          stage="degrade.narrowband.edge_recession_body",
                          measurements={"radius_mm": radius, **stats})
    body = _offset_body(mesh, depth)
    info = {"method": "per-vertex inward normal offset by the analytic rolling-ball edge "
                      "profile (compact support, rim pinned)",
            "radius_mm": float(radius), "edges": int(sections["count"]),
            "edge_length_total_mm": float(sections["edge_length_total_mm"]),
            "theta_median_deg": float(sections["theta_median_deg"]),
            "vertex_depth_stats": stats,
            "max_depth_analytic_mm": float(radius * sections["max_depth_mm"]),
            "contact_analytic_mm": float(radius * sections["contact_mm"]),
            "affected_vertices": int(np.count_nonzero(depth > 0)),
            "moved_vertices_fraction": float(np.count_nonzero(depth > 0) / max(len(vertices), 1))}
    return body, info


def recessed_body(mesh: trimesh.Trimesh, roi_faces: np.ndarray, amplitude: np.ndarray,
                  basis: dict[str, Any]) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    """Subtract a non-negative smooth depth field from the ROI surface (plan 12.2 P03).

    ``basis`` carries the frozen field (``{"field": FourierField.payload()}``) so that all five
    levels of a run share one field and stay nested; ``amplitude[face]`` is that field
    normalised to ``[0, 1]`` over the ROI.  The depth applied to a vertex is the area-weighted
    mean of its adjacent ROI faces (vertices shared with the rest of the body therefore get the
    ROI-side value, not the value of the far surface), and the rim vertices are pinned to zero
    so the perturbation has compact support exactly on the ROI.
    """
    faces = np.asarray(mesh.faces, dtype=np.int64)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    roi = np.asarray(roi_faces, dtype=np.int64)
    if len(roi) == 0:
        raise SynLabError(ErrorCode.NA_NOT_APPLICABLE, "ROI selects no face",
                          stage="degrade.narrowband.recessed_body")
    amplitude = np.asarray(amplitude, dtype=np.float64).reshape(-1)
    if amplitude.shape[0] != len(faces):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"amplitude has {amplitude.shape[0]} entries for {len(faces)} faces",
                          stage="degrade.narrowband.recessed_body")
    weighted = np.zeros(len(vertices), dtype=np.float64)
    weights = np.zeros(len(vertices), dtype=np.float64)
    for corner in range(3):
        np.add.at(weighted, faces[roi][:, corner], amplitude[roi] * areas[roi])
        np.add.at(weights, faces[roi][:, corner], areas[roi])
    rho = np.zeros(len(vertices), dtype=np.float64)
    present = weights > 0
    rho[present] = weighted[present] / weights[present]
    rim = roi_rim_vertices(mesh, roi)
    rho[rim] = 0.0
    body = _offset_body(mesh, rho)
    return body, {
        "method": "per-vertex normal offset by an area-averaged smooth depth field",
        "roi_faces": int(len(roi)), "roi_vertices": int(present.sum()),
        "rim_vertices_pinned": int(len(rim)),
        "rho_min": float(rho[present].min()) if present.any() else 0.0,
        "rho_max": float(rho[present].max()) if present.any() else 0.0,
        "normalised": True,
        "vertex_depth_field": rho,
    }


def paired_thickness(body: trimesh.Trimesh, source: trimesh.Trimesh, *, n_samples: int = 400,
                     seed: int = 0, eps_mm: float = 1e-3,
                     face_mask: np.ndarray | None = None) -> dict[str, float]:
    """Wall thickness **at the same material points** before and after the erosion.

    Two problems with a plain ``S.ray_thickness`` comparison are measured on the rough probe:

    1. it re-samples the surface every call, so its *minimum* jumps between unrelated thin
       features (undamaged min 0.8462 mm vs 0.1353 mm for a declared 0.05 mm cut);
    2. the rough interface creates near-vertical micro-walls, so a ray cast inward from a
       surface point frequently hits a neighbouring rough peak and reports a 0.02 mm "wall"
       that is not a wall at all.

    Both are avoided here: the sample points are drawn **once on the source** (restricted to
    ``face_mask`` when given), and each ray is cast from ``point + n*eps`` -- i.e. from *inside*
    the body, where the signed distance is negative -- so the reported thickness is the distance
    to the opposite surface rather than to the roughness next door.  ``drop`` is then a real
    local thickness loss at a fixed material point.
    """
    points, face_ids = trimesh.sample.sample_surface(source, int(n_samples),
                                                     seed=int(seed) % (2 ** 31))
    if face_mask is not None:
        mask = np.asarray(face_mask, dtype=bool)
        keep = mask[np.asarray(face_ids, dtype=np.int64)]
        points = np.asarray(points, dtype=np.float64)[keep]
        face_ids = np.asarray(face_ids, dtype=np.int64)[keep]
    if len(points) == 0:
        return {"samples": 0, "paired": 0, "min_source_mm": 0.0, "min_damaged_mm": 0.0,
                "max_drop_mm": 0.0, "max_drop_rel": 0.0, "violations": 0,
                "violation_fraction": 0.0}
    normals = np.asarray(source.face_normals, dtype=np.float64)[np.asarray(face_ids)]
    origins = np.asarray(points, dtype=np.float64) + normals * float(eps_mm)
    src_hit = S.scene_for(source).cast(origins, -normals)
    dst_hit = S.scene_for(body).cast(origins, -normals)
    src = np.where(np.isfinite(src_hit) & (src_hit > 0), src_hit + eps_mm, 0.0)
    dst = np.where(np.isfinite(dst_hit) & (dst_hit > 0), dst_hit + eps_mm, 0.0)
    both = (src > 0) & (dst > 0)
    if not bool(np.any(both)):
        return {"samples": int(n_samples), "paired": 0, "min_source_mm": 0.0,
                "min_damaged_mm": 0.0, "max_drop_mm": 0.0, "max_drop_rel": 0.0,
                "violations": 0, "violation_fraction": 0.0}
    s = src[both]
    d = dst[both]
    drop = s - d
    rel = drop / np.maximum(s, 1e-9)
    return {"samples": int(n_samples), "paired": int(both.sum()),
            "min_source_mm": float(s.min()), "min_damaged_mm": float(d.min()),
            "p05_source_mm": float(np.percentile(s, 5)),
            "p05_damaged_mm": float(np.percentile(d, 5)),
            "max_drop_mm": float(drop.max()), "max_drop_rel": float(rel.max()),
            "violations": int(np.count_nonzero(drop > np.maximum(s, 1e-9) * 0.5)),
            "violation_fraction": float(np.mean(drop > np.maximum(s, 1e-9) * 0.5))}


def assert_watertight(mesh: trimesh.Trimesh, *, label: str, stage: str) -> dict[str, Any]:
    """A narrow-band result that is not a closed volume must fail structurally, never pass."""
    report = S.watertight_report(mesh)
    if not report["watertight"] or not report["positive_volume"]:
        raise SynLabError(
            ErrorCode.PRECISION_NOT_REALIZED,
            f"{label}: the narrow-band result is not a closed positive volume "
            f"(watertight={report['watertight']}, volume={report['volume_mm3']:.6f} mm3)",
            stage=stage, measurements=report)
    return report
