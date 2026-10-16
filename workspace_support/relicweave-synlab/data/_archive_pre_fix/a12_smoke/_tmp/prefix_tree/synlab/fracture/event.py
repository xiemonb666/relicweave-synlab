"""One fracture event on one material body: shared cutter, both sides, all components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np
import trimesh

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import (
    ORIGIN_AMBIGUOUS,
    ORIGIN_INTERFACE,
    ORIGIN_MOTHER_SURFACE,
    CutterResult,
    FractureResult,
    Fragment,
    InterfacePatch,
)
from ..storage.mesh_io import face_attrs, with_face_attrs
from .booleans import (
    SourceResolver,
    boolean_difference,
    boolean_intersection,
    concat_tagged,
    mesh_hash,
    mesh_shells,
    tag_source,
)
from .fragment import (
    SplitPart,
    audit_fracture_result,
    build_interface,
    interface_distance_stats,
    make_fragment,
    split_components,
)
from .spec import (
    AMBIGUITY_AREA_RATIO_MAX,
    DEFAULT_ERROR_BUDGET_MM,
    INTERFACE_GAP_P95_MM,
)

__all__ = ["run_shared_cut", "SIDE_MINUS", "SIDE_PLUS"]

SIDE_MINUS = -1
SIDE_PLUS = 1


@dataclass
class EventBuild:
    """Internal assembly record for one shared-cut event."""

    result: FractureResult
    classifications: dict[str, dict[str, Any]] = field(default_factory=dict)
    pieces: dict[str, SplitPart] = field(default_factory=dict)


def _cut_both_sides(source_mother: Any, source_cutter: Any) -> tuple[Any, Any]:
    """``M_minus = M ∩ C`` and ``M_plus = M \\ C`` for one shared cutter.

    A mother assembled from several *independent* closed shells (V10's body + lid + collar,
    built with ``build_vessel(union=False)``) is **not** a valid single CSG operand: its shells
    interpenetrate by construction -- the lid collar laps the body mouth and the lid dome by a
    real volumetric overlap, which is the documented design ("contact is not R2") -- so the
    winding number of the whole-body input is ambiguous exactly where the shells overlap.
    Manifold then answers with a mesh that is geometrically closed but not a closed *surface*:
    measured on ``LIN0000_V10_M11_PAT15`` the whole-body call returns ``M_minus`` with 69 and
    ``M_plus`` with 124 edges used by four faces (``is_watertight`` False), and the event is
    refused by the conservation gate although its volume is right to 1e-5 mm^3.

    Cutting one shell at a time is the definition that matches the rest of the pipeline -- the
    fragments of an event are already the connected components of each side
    (:func:`synlab.fracture.fragment.split_components`), and the mother volume is the sum of the
    shell volumes -- and it returns closed solids: measured on the same lineage, per-shell
    ``M_minus``/``M_plus`` are watertight with zero non-manifold edges and the same volumes
    (5449360.623305 vs 5449360.623244 mm^3).  A single-shell mother keeps the previous code path
    bit for bit (measured on ``LIN0051_V01_M10_PAT08``: identical vertices and faces), so no
    already-working vessel is affected.  Nothing is relaxed here: both sides still come from the
    same frozen cutter bytes and every result is still audited downstream.
    """
    shells = mesh_shells(source_mother.mesh)
    if len(shells) <= 1:
        return (boolean_intersection([source_mother, source_cutter], label="M_minus"),
                boolean_difference([source_mother, source_cutter], label="M_plus"))
    shell_sources = [
        tag_source(part, 1.0, "mother", triangle_ids=np.asarray(source_mother.triangle_ids)[ids])
        for part, ids in shells
    ]
    return (
        concat_tagged([boolean_intersection([shell, source_cutter], label="M_minus")
                       for shell in shell_sources], label="M_minus"),
        concat_tagged([boolean_difference([shell, source_cutter], label="M_plus")
                       for shell in shell_sources], label="M_plus"),
    )


def _fragment_ids(base: str, parts: list[SplitPart], side: int) -> list[str]:
    return [base if index == 0 else f"{base}__{side:+d}c{index}" for index in range(len(parts))]


def run_shared_cut(
    mother: Any,
    cutter: CutterResult,
    *,
    event_id: str,
    backend: str,
    parent_id: str | None = None,
    extra_meta: dict[str, Any] | None = None,
    ambiguity_tolerance_mm: float = 1.0e-4,
    sample_target: int = 24,
) -> FractureResult:
    """Execute ``M_- = M ∩ C`` and ``M_+ = M \\ C`` with one shared discrete cutter."""
    cutter_mesh = cutter.mesh
    if not bool(cutter_mesh.is_watertight):
        raise SynLabError(ErrorCode.CUTTER_NOT_CLOSED,
                          "shared cutter is not watertight",
                          stage="fracture.event.run_shared_cut")
    cutter_hash = mesh_hash(cutter_mesh)
    if cutter.meta.get("cutter_hash") not in (None, cutter_hash):
        raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                          "cutter mesh does not match its recorded hash",
                          stage="fracture.event.run_shared_cut")
    mother_mesh = mother.mesh
    if not bool(mother_mesh.is_watertight):
        raise SynLabError(ErrorCode.MOTHER_INVALID, "mother mesh is not watertight",
                          stage="fracture.event.run_shared_cut")

    source_mother = tag_source(trimesh.Trimesh(vertices=np.asarray(mother_mesh.vertices),
                                               faces=np.asarray(mother_mesh.faces),
                                               process=False),
                               1.0, "mother")
    source_cutter = tag_source(trimesh.Trimesh(vertices=np.asarray(cutter_mesh.vertices),
                                               faces=np.asarray(cutter_mesh.faces),
                                               process=False),
                               2.0, "cutter")
    minus = boolean_intersection([source_mother, source_cutter], label="M_minus")
    plus = boolean_difference([source_mother, source_cutter], label="M_plus")
    if minus.n_faces == 0 or plus.n_faces == 0:
        raise SynLabError(
            ErrorCode.FRACTURE_CONSERVATION_FAIL,
            f"degenerate event: M_minus has {minus.n_faces} faces and M_plus has "
            f"{plus.n_faces} faces",
            stage="fracture.event.run_shared_cut",
            measurements={"minus_faces": minus.n_faces, "plus_faces": plus.n_faces},
        )
    for name, side in (("M_minus", minus), ("M_plus", plus)):
        if not bool(side.mesh.is_watertight):
            raise SynLabError(
                ErrorCode.FRACTURE_CONSERVATION_FAIL,
                f"{name} is not watertight after the boolean (faces={side.n_faces})",
                stage="fracture.event.run_shared_cut",
            )

    resolver = SourceResolver([source_mother, source_cutter],
                              tolerance_mm=ambiguity_tolerance_mm)
    classifications: dict[str, dict[str, Any]] = {}
    for name, side in (("M_minus", minus), ("M_plus", plus)):
        classification = resolver.classify(side, container=cutter_mesh,
                                           container_tolerance_mm=ambiguity_tolerance_mm)
        classification["_faces"] = np.asarray(side.mesh.faces, dtype=np.int64)
        classification["area_faces"] = np.asarray(side.mesh.area_faces, dtype=np.float64)
        classification["mother_mesh_id"] = 1
        classification["cutter_mesh_id"] = 2
        classifications[name] = classification

    fragments: list[Fragment] = []
    face_lookup: dict[str, np.ndarray] = {}
    for name, side_tag in (("M_minus", SIDE_MINUS), ("M_plus", SIDE_PLUS)):
        side = minus if name == "M_minus" else plus
        parts = split_components(side.mesh)
        ids = _fragment_ids(f"{event_id}-m" if side_tag < 0 else f"{event_id}-p", parts, side_tag)
        for index, (part, fragment_id) in enumerate(zip(parts, ids)):
            fragment = make_fragment(
                part, fragment_id=fragment_id, component_id=index, side=side_tag,
                classification=classifications[name], parent_id=parent_id, backend=backend,
                cutter_hash=cutter_hash,
                extra_meta={"event_id": event_id, "boolean_output": name,
                            "degenerate_output": bool(side.mesh.is_watertight is False)},
            )
            fragments.append(fragment)
            face_lookup[fragment_id] = np.asarray(part.faces, dtype=np.int64)

    interfaces, correspondence, unmatched_faces, unmatched_area, matched_overlap_area = \
        _link_interfaces(
            fragments, minus, plus, classifications, cutter_mesh,
            sample_target=sample_target, ambiguity_tolerance_mm=ambiguity_tolerance_mm,
        )
    _write_interface_ids(fragments, interfaces)

    mother_volume = float(abs(mother_mesh.volume))
    fragment_volume = float(sum(fragment.volume_mm3 for fragment in fragments))
    event_tree = {
        "event_id": event_id,
        "parent_id": parent_id,
        "backend": backend,
        "cutter_hash": cutter_hash,
        "cutter": {
            "basis_id": cutter.basis.basis_id,
            "triangles": int(cutter.triangles),
            "requested_error_mm": float(cutter.requested_error_mm),
            "realized_error_mm": float(cutter.realized_error_mm),
            "meta": {k: v for k, v in cutter.meta.items() if k != "height_field"},
        },
        "children": [fragment.fragment_id for fragment in fragments],
        "minus": [f.fragment_id for f in fragments if int(f.face_side[0]) < 0],
        "plus": [f.fragment_id for f in fragments if int(f.face_side[0]) > 0],
        "interfaces": [patch.interface_id for patch in interfaces],
        "mother_volume_mm3": mother_volume,
        "fragment_volume_mm3": fragment_volume,
    }
    debts = [f for f in fragments if f.is_tiny]
    result = FractureResult(
        fragments=fragments,
        interfaces=interfaces,
        event_tree=event_tree,
        debris=debts,
        parent_id=parent_id or mother.mother_id,
        backend=backend,
        qa={},
        cutter_ref=cutter_hash,
        meta={
            "event_id": event_id,
            "cutter_hash": cutter_hash,
            "correspondence": correspondence,
            "minus_faces": int(minus.n_faces),
            "plus_faces": int(plus.n_faces),
            "minus_hash": mesh_hash(minus.mesh),
            "plus_hash": mesh_hash(plus.mesh),
            "unmatched_interface_faces": int(unmatched_faces),
            "unmatched_interface_area_mm2": float(unmatched_area),
            "matched_interface_overlap_area_mm2": float(matched_overlap_area),
            "unmatched_interface_area_ratio": float(
                unmatched_area / max(unmatched_area + matched_overlap_area, 1.0e-12)),
            "classifications": {
                name: {
                    "ambiguous_vertices": int(np.sum(value["vertex_ambiguous"])),
                    "interface_vertices": int(np.sum(value["vertex_inside_container"])),
                    "vertices": int(value["vertex_origin"].shape[0]),
                } for name, value in classifications.items()
            },
            **dict(extra_meta or {}),
        },
    )
    result.qa = audit_fracture_result(result, mother)
    return result


def _link_interfaces(
    fragments: list[Fragment],
    minus: Any,
    plus: Any,
    classifications: dict[str, dict[str, Any]],
    cutter_mesh: trimesh.Trimesh,
    *,
    sample_target: int,
    ambiguity_tolerance_mm: float,
    max_faces_per_patch: int = 128,
) -> tuple[list[InterfacePatch], list[dict[str, Any]], int, float]:
    """Pair complementary clipped cutter triangles into shared interface patches.

    Both sides of one cut carry the *same* discrete cutter surface clipped by the mother, so a
    genuine complementary pair is geometrically coincident.  The pairing is therefore done by
    face centroid (one-to-one, closest first) inside every (minus-fragment, plus-fragment)
    combination instead of by position in a per-source-triangle list: the list order carries no
    meaning and a positional zip pairs unrelated faces (measured on V18: gap P95 13.6 mm and a
    90 deg normal reversal, i.e. faces that are not complementary at all).  Faces without a
    partner are counted with their area instead of being silently dropped.
    """
    minus_fragments = [f for f in fragments if int(f.face_side[0]) < 0]
    plus_fragments = [f for f in fragments if int(f.face_side[0]) > 0]
    cutter_faces = np.arange(len(np.asarray(cutter_mesh.faces)), dtype=np.int64)
    cutter_centres = np.asarray(cutter_mesh.triangles_center, dtype=np.float64)
    patches: list[InterfacePatch] = []
    correspondence: list[dict[str, Any]] = []
    interface_counter = 0
    unmatched_faces = 0
    unmatched_area = 0.0
    matched_overlap_area = 0.0
    for fragment_a in minus_fragments:
        faces_a, sources_a, centres_a = _interface_faces(fragment_a, cutter_mesh, cutter_faces,
                                                         cutter_centres)
        if faces_a.size == 0:
            continue
        for fragment_b in plus_fragments:
            faces_b, sources_b, centres_b = _interface_faces(fragment_b, cutter_mesh,
                                                             cutter_faces, cutter_centres)
            if faces_b.size == 0:
                continue
            pairs, lost_faces, lost_area, overlap_area = _match_faces_by_overlap(
                fragment_a, faces_a, centres_a, sources_a, fragment_b, faces_b, centres_b,
                sources_b, ambiguity_tolerance_mm)
            unmatched_faces += lost_faces
            unmatched_area += lost_area
            matched_overlap_area += overlap_area
            if not pairs:
                continue
            # bound the sampling cost per patch: chunks of one physical interface are still one
            # patch each, and the auditor reports the worst chunk instead of hiding it
            for start in range(0, len(pairs), max(1, int(max_faces_per_patch))):
                chunk = pairs[start:start + max(1, int(max_faces_per_patch))]
                chunk_a = [int(pair[0]) for pair in chunk]
                chunk_b = [int(pair[1]) for pair in chunk]
                chunk_overlap = float(sum(float(pair[3]) for pair in chunk))
                chunk_sources = sorted({int(pair[2]) for pair in chunk if int(pair[2]) >= 0})
                patch, rows = build_interface(
                    interface_id=interface_counter, fragment_a=fragment_a, fragment_b=fragment_b,
                    faces_a=chunk_a, faces_b=chunk_b,
                    source_tri=(chunk_sources[0] if chunk_sources else -1),
                    cutter_mesh=cutter_mesh, sample_target=sample_target,
                )
                patch.meta["source_triangles"] = chunk_sources
                if patch.area_mm2 <= 0.0:
                    continue
                # the shared area is the *measured* 2D overlap of the paired faces, not the mean
                # of the two sides' face areas (which double counts on non-1:1 pairings)
                patch.meta["build_interface_area_mm2"] = float(patch.area_mm2)
                patch.meta["pair_overlap_area_mm2"] = chunk_overlap
                if chunk_overlap > 0.0:
                    patch.area_mm2 = chunk_overlap
                stats = interface_distance_stats(fragment_a, fragment_b, patch)
                patch.meta.update(stats)
                patches.append(patch)
                for (row_point_a, row_point_b, face_a, bary_a, face_b, bary_b,
                     row_ambiguous) in rows:
                    correspondence.append({
                        "interface_id": interface_counter,
                        "fragment_a": fragment_a.fragment_id,
                        "fragment_b": fragment_b.fragment_id,
                        "point_a_mm": row_point_a,
                        "point_b_mm": row_point_b,
                        "face_a": face_a,
                        "face_b": face_b,
                        "bary_a": bary_a,
                        "bary_b": bary_b,
                        "source_tri": (chunk_sources[0] if chunk_sources else -1),
                        "ambiguous": bool(row_ambiguous),
                        "residual_mm": float(np.linalg.norm(row_point_a - row_point_b)),
                    })
                interface_counter += 1
    return patches, correspondence, unmatched_faces, unmatched_area, matched_overlap_area


def _interface_faces(fragment: Fragment, cutter_mesh: trimesh.Trimesh | None = None,
                     cutter_faces: np.ndarray | None = None,
                     cutter_centres: np.ndarray | None = None,
                     container_tolerance_mm: float = 1.0e-4,
                     normal_dot_min: float = 0.9) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Interface (cut) faces of one fragment: ids, source cutter triangle ids and centroids.

    A face is a cut face only when **all three of its vertices** lie on the cutter surface *and*
    its own normal is (anti)parallel to the cutter normal it lies on.  The vertex-level majority
    rule alone is not enough: a mother face that merely touches the cut plane along one edge has
    two of three vertices exactly on the cutter and is then counted as a cut face — measured on
    V13 that reports 6071 mm² instead of the real ~1900 mm² shared surface, and it is exactly the
    plan's "擦边" case that must not become a fracture surface.  The source triangle is the
    nearest cutter triangle of the face centroid (plan 30.5's documented geometric fallback).
    """
    origin = np.asarray(fragment.face_origin_kind)
    candidate = np.nonzero((origin == ORIGIN_INTERFACE) | (origin == ORIGIN_AMBIGUOUS))[0]
    if candidate.size == 0:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros((0, 3), dtype=np.float64)
    mesh = fragment.mesh
    if cutter_mesh is not None:
        faces_all = np.asarray(mesh.faces, dtype=np.int64)[candidate]
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        used = np.unique(faces_all.reshape(-1))
        distances = np.full(vertices.shape[0], np.inf, dtype=np.float64)
        distances[used] = np.asarray(
            cutter_mesh.nearest.on_surface(vertices[used])[1], dtype=np.float64)
        on_surface = distances[faces_all] <= float(container_tolerance_mm)
        keep = np.all(on_surface, axis=1)
        centres = np.asarray(mesh.triangles_center, dtype=np.float64)[candidate]
        _closest, _distance, triangle_id = cutter_mesh.nearest.on_surface(centres)
        cutter_normal = np.asarray(cutter_mesh.face_normals, dtype=np.float64)[
            np.asarray(triangle_id, dtype=np.int64)]
        face_normal = np.asarray(mesh.face_normals, dtype=np.float64)[candidate]
        aligned = np.abs(np.einsum("ij,ij->i", face_normal, cutter_normal)) >= float(normal_dot_min)
        keep = keep & aligned
        candidate = candidate[keep]
        centres = centres[keep]
    else:
        centres = np.asarray(mesh.triangles_center, dtype=np.float64)[candidate]
    faces = candidate.astype(np.int64)
    if faces.size == 0:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros((0, 3), dtype=np.float64)
    if cutter_faces is None or cutter_centres is None or cutter_centres.shape[0] == 0:
        sources = np.full(faces.shape[0], -1, dtype=np.int64)
    else:
        from scipy.spatial import cKDTree

        _, nearest = cKDTree(np.asarray(cutter_centres, dtype=np.float64)).query(centres, k=1)
        sources = np.asarray(cutter_faces, dtype=np.int64)[np.asarray(nearest, dtype=np.int64)]
    return faces, sources, centres


def _face_area_sum(fragment: Fragment, faces: Sequence[int]) -> float:
    if len(faces) == 0:
        return 0.0
    areas = np.asarray(fragment.mesh.area_faces, dtype=np.float64)
    ids = np.asarray(list(faces), dtype=np.int64)
    ids = ids[(ids >= 0) & (ids < areas.shape[0])]
    return float(np.sum(areas[ids]))


def _match_faces_by_overlap(fragment_a: Fragment, faces_a: np.ndarray, centres_a: np.ndarray,
                            sources_a: np.ndarray, fragment_b: Fragment, faces_b: np.ndarray,
                            centres_b: np.ndarray, sources_b: np.ndarray,
                            tolerance_mm: float, *, max_candidates: int = 8,
                            max_partners_per_face: int = 3,
                            min_overlap_ratio: float = 0.02,
                            ) -> tuple[list[tuple[int, int, int, float]], int, float, float]:
    """Pair complementary cut faces by *measured 2D overlap* (plan 30.5).

    The two sides clip the same discrete cutter surface, but the mother's own triangulation is
    different on each side, so complementary faces are generally **not** 1:1: one face of M⁻ can
    be covered by two or three faces of M⁺.  A centroid-only 1:1 matching therefore leaves most
    of the shared surface unpaired (measured on the demo mothers: 61-94% of the cut area), which
    would silently under-report every R2 area.  Here the faces are projected into one common
    frame and paired by the area of their Shapely triangle intersection, greedily from the
    largest overlap, allowing a face a bounded number of partners (``max_partners_per_face``) and
    stopping a face once its overlap budget is covered.  Returns the accepted pairs with their
    overlap area, the faces that found no overlap at all, and the summed overlap area.
    """
    import shapely
    from scipy.spatial import cKDTree

    triangles_a = np.asarray(fragment_a.mesh.triangles, dtype=np.float64)[faces_a]
    triangles_b = np.asarray(fragment_b.mesh.triangles, dtype=np.float64)[faces_b]
    areas_a = np.asarray(fragment_a.mesh.area_faces, dtype=np.float64)[faces_a]
    areas_b = np.asarray(fragment_b.mesh.area_faces, dtype=np.float64)[faces_b]
    normals_a = np.asarray(fragment_a.mesh.face_normals, dtype=np.float64)[faces_a]
    normals_b = np.asarray(fragment_b.mesh.face_normals, dtype=np.float64)[faces_b]
    normal = normals_a.mean(axis=0) - normals_b.mean(axis=0)
    norm = float(np.linalg.norm(normal))
    if norm < 1.0e-12:                       # pragma: no cover - degenerate input
        return [], int(faces_a.shape[0] + faces_b.shape[0]), \
            float(areas_a.sum() + areas_b.sum()), 0.0
    normal = normal / norm
    helper = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = helper - normal * float(helper @ normal)
    e1 = e1 / max(float(np.linalg.norm(e1)), 1e-12)
    e2 = np.cross(normal, e1)

    def project(triangles: np.ndarray) -> np.ndarray:
        return np.stack([triangles @ e1, triangles @ e2], axis=-1)

    polygons_a = shapely.polygons(project(triangles_a))
    polygons_b = shapely.polygons(project(triangles_b))
    centroids_b = np.asarray(centres_b, dtype=np.float64)
    scale = max(float(np.median(np.max(np.linalg.norm(
        triangles_a - triangles_a[:, 0:1, :], axis=2), axis=1))),
        float(np.median(np.max(np.linalg.norm(
            triangles_b - triangles_b[:, 0:1, :], axis=2), axis=1))))
    tree = cKDTree(centroids_b)
    radius = max(2.0 * scale, max(float(tolerance_mm), 1.0e-3))
    candidates = tree.query_ball_point(np.asarray(centres_a, dtype=np.float64), r=radius)
    pairs: list[tuple[int, int]] = []
    for index, partners in enumerate(candidates):
        if not partners:
            continue
        ranked = sorted(partners, key=lambda partner: float(
            np.linalg.norm(centroids_b[partner] - centres_a[index])))[:int(max_candidates)]
        pairs.extend((index, int(partner)) for partner in ranked)
    if not pairs:
        return [], int(faces_a.shape[0] + faces_b.shape[0]), \
            float(areas_a.sum() + areas_b.sum()), 0.0
    index_a = np.asarray([pair[0] for pair in pairs], dtype=np.int64)
    index_b = np.asarray([pair[1] for pair in pairs], dtype=np.int64)
    overlap = np.asarray(shapely.area(shapely.intersection(polygons_a[index_a],
                                                           polygons_b[index_b])),
                         dtype=np.float64)
    keep = (overlap > 0.0) & (overlap >= float(min_overlap_ratio) * areas_a[index_a]) \
        & (overlap >= float(min_overlap_ratio) * areas_b[index_b]) \
        & (np.einsum("ij,ij->i", normals_a[index_a], normals_b[index_b]) <= -0.5)
    index_a, index_b, overlap = index_a[keep], index_b[keep], overlap[keep]
    accepted: list[tuple[int, int, float]] = []
    covered_a = np.zeros(faces_a.shape[0], dtype=np.float64)
    covered_b = np.zeros(faces_b.shape[0], dtype=np.float64)
    used_a = np.zeros(faces_a.shape[0], dtype=np.int64)
    used_b = np.zeros(faces_b.shape[0], dtype=np.int64)
    for position in np.argsort(-overlap, kind="stable"):
        first, second = int(index_a[position]), int(index_b[position])
        if used_a[first] >= int(max_partners_per_face) \
                or used_b[second] >= int(max_partners_per_face):
            continue
        if covered_a[first] >= 0.99 * areas_a[first] and covered_b[second] >= 0.99 * areas_b[second]:
            continue
        accepted.append((first, second, float(overlap[position])))
        covered_a[first] += float(overlap[position])
        covered_b[second] += float(overlap[position])
        used_a[first] += 1
        used_b[second] += 1
    matched: list[tuple[int, int, int, float]] = [
        (int(faces_a[first]), int(faces_b[second]),
         int(sources_a[first]) if int(sources_a[first]) >= 0 else int(sources_b[second]),
         float(value))
        for first, second, value in accepted]
    unmatched_a = covered_a <= 0.0
    unmatched_b = covered_b <= 0.0
    lost_faces = int(np.sum(unmatched_a)) + int(np.sum(unmatched_b))
    lost_area = _face_area_sum(fragment_a, faces_a[unmatched_a]) \
        + _face_area_sum(fragment_b, faces_b[unmatched_b])
    return matched, lost_faces, lost_area, float(np.sum(overlap))


def _write_interface_ids(fragments: list[Fragment], patches: list[InterfacePatch]) -> None:
    for fragment in fragments:
        origin = np.asarray(fragment.face_origin_kind)
        ids = np.full(origin.shape[0], -1, dtype=np.int32)
        for patch in patches:
            side_key = "faces_a" if fragment.fragment_id == patch.fragment_a else (
                "faces_b" if fragment.fragment_id == patch.fragment_b else None)
            if side_key is None:
                continue
            ids[np.asarray(patch.meta[side_key], dtype=np.int64)] = patch.interface_id
        with_face_attrs(fragment.mesh, interface_id=ids)
        fragment.face_interface_id = ids
        fragment.meta["interface_ids"] = sorted({int(x) for x in ids if x >= 0})
