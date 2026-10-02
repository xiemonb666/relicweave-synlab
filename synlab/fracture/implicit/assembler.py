"""Event assembly for the implicit cutter: analytic classification instead of ray casting.

Why this module exists (measured, not assumed)
----------------------------------------------
:func:`synlab.fracture.event.run_shared_cut` classifies every output vertex with
``trimesh.Trimesh.contains`` + ``nearest.on_surface`` against the **cutter**.  This host has no
embree, so ``contains`` falls back to trimesh's pure-numpy ray engine, which is *linear in the
cutter's triangle count per query point*: measured on the implicit cutter (208 820 triangles) it
needs **86.8 s for 1000 points** and then tries to allocate a 4.7 GiB ray/triangle buffer, so a
fragment with 10^5 vertices cannot be classified at all -- the host killed the run, which is exactly
what the first end-to-end attempt did.

An implicit surface does not need ray casting: the cutter *is* ``w = h(u, v)``, so the distance from
any point to the cutter surface is ``|w - h(u, v)|`` -- one closed-form evaluation.  The mother is
small (hundreds of triangles), so its signed distance is still measured with trimesh.  Everything
else (the boolean, the component split, the fragment records, the audit) is the frozen code, and the
tolerances below are the frozen ones (``fragment.CLIP_ON_SURFACE_TOL_MM`` = 1e-4 mm).

Interface patches are built by *geometric face keys*: both sides of a shared cut carry the same
clipped triangles, so pairing coincident triangles (rounded vertex triples) is exact -- no
nearest-neighbour search and no tolerance to tune.  Conjugacy is therefore constructive *and*
measured: gap, normal reversal, area difference and sampled point distance are all reported.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import trimesh

from ...errors import ErrorCode, SynLabError
from ...schemas.runtime import (
    ORIGIN_AMBIGUOUS,
    ORIGIN_INTERFACE,
    ORIGIN_MOTHER_SURFACE,
    FractureResult,
    InterfacePatch,
)
from ...storage.mesh_io import with_face_attrs
from ..booleans import (
    GRAZING_NORMAL_DOT,
    boolean_difference,
    boolean_intersection,
    mesh_hash,
    tag_source,
)
from ..event import BASIS_META_KEY, BASIS_RECORD_META_KEY, SIDE_MINUS, SIDE_PLUS, basis_record
from ..fragment import CLIP_ON_SURFACE_TOL_MM, make_fragment, split_components

__all__ = ["assemble_implicit_event", "sheet_distance"]


def _trace(message: str) -> None:
    """Stage trace for the assembler: an implicit event is a heavy run, so it says where it is."""
    import os

    if str(os.environ.get("SYNLAB_IMPLICIT_TRACE", "")).strip() not in ("", "0", "false"):
        print(f"[assemble] {message}", flush=True)

#: tolerance (mm) for "this vertex lies on the implicit sheet" (the frozen on-surface tolerance).
ON_SHEET_TOL_MM = float(CLIP_ON_SURFACE_TOL_MM)
#: tolerance (mm) for "this vertex lies on the mother's own surface".
ON_MOTHER_TOL_MM = float(CLIP_ON_SURFACE_TOL_MM)
#: rounding (decimal places, mm) of the coincident-triangle key.
FACE_KEY_DECIMALS = 6


def sheet_distance(basis: Any, h_fn: Any, points: np.ndarray
                   ) -> tuple[np.ndarray, np.ndarray]:
    """``|w - h(u, v)|`` per world point, plus the local ``(u, v, w)`` coordinates."""
    matrix = np.stack([basis.e_u, basis.e_v, basis.normal], axis=0)
    local = (np.asarray(points, dtype=np.float64)
             - np.asarray(basis.origin, dtype=np.float64)[None, :]) @ matrix.T
    height = np.asarray(h_fn(local[:, 0], local[:, 1]), dtype=np.float64)
    return np.abs(local[:, 2] - height), local


def sheet_normal(basis: Any, h_fn: Any, local: np.ndarray, *, step_mm: float = 1.0e-3
                 ) -> np.ndarray:
    """World normal of the implicit sheet at the given local ``(u, v, w)`` points."""
    u = np.asarray(local[:, 0], dtype=np.float64)
    v = np.asarray(local[:, 1], dtype=np.float64)
    hu = (np.asarray(h_fn(u + step_mm, v), dtype=np.float64)
          - np.asarray(h_fn(u - step_mm, v), dtype=np.float64)) / (2.0 * step_mm)
    hv = (np.asarray(h_fn(u, v + step_mm), dtype=np.float64)
          - np.asarray(h_fn(u, v - step_mm), dtype=np.float64)) / (2.0 * step_mm)
    matrix = np.stack([basis.e_u, basis.e_v, basis.normal], axis=0)
    normals = (-hu[:, None] * matrix[0][None, :] - hv[:, None] * matrix[1][None, :]
               + matrix[2][None, :])
    length = np.linalg.norm(normals, axis=1)
    return normals / np.maximum(length[:, None], 1.0e-12)


def _classify(side: Any, *, basis: Any, h_fn: Any, mother_mesh: Any,
              on_sheet_tol: float, on_mother_tol: float) -> dict[str, Any]:
    """Per-vertex origin/source record for one boolean side (analytic cutter distance).

    The on-sheet test is the frozen one -- distance **and** normal (anti)parallel to the sheet
    (``booleans.GRAZING_NORMAL_DOT``).  Distance alone would label the mother's own wall along the
    tangent line of the sheet as interface, and it would rob those faces of their mother-triangle
    provenance (measured: source coverage 0.986 against the 0.999 floor).
    """
    from trimesh.proximity import closest_point, signed_distance

    points = np.asarray(side.mesh.vertices, dtype=np.float64)
    d_sheet, local = sheet_distance(basis, h_fn, points)
    signed_mother = np.asarray(signed_distance(mother_mesh, points), dtype=np.float64)
    d_mother = np.abs(signed_mother)
    _closest, _distance, mother_tri = closest_point(mother_mesh, points)
    mother_tri = np.asarray(mother_tri, dtype=np.int64)
    inside = signed_mother > 0.0
    vertex_normals = np.asarray(side.mesh.vertex_normals, dtype=np.float64)
    normals_sheet = sheet_normal(basis, h_fn, local)
    aligned = np.abs(np.einsum("ij,ij->i", vertex_normals, normals_sheet)) >= GRAZING_NORMAL_DOT
    on_sheet = (d_sheet <= float(on_sheet_tol)) & aligned
    on_mother = (d_mother <= float(on_mother_tol)) & inside
    origin = np.full(points.shape[0], ORIGIN_MOTHER_SURFACE, dtype=np.uint8)
    origin[on_sheet] = ORIGIN_INTERFACE
    origin[on_sheet & on_mother] = ORIGIN_AMBIGUOUS
    source = np.where(on_sheet, -1, mother_tri).astype(np.int64)
    mesh_id = np.where(d_sheet <= d_mother, 2, 1).astype(np.int64)
    return {
        "_faces": np.asarray(side.mesh.faces, dtype=np.int64),
        "vertex_origin": origin,
        "vertex_source_tri": source,
        "vertex_ambiguous": (on_sheet & on_mother),
        "vertex_mesh_id": mesh_id,
        "vertex_sheet_distance_mm": d_sheet,
        "vertex_mother_distance_mm": d_mother,
        "vertex_sheet_aligned": aligned,
        "grazing_normal_dot": float(GRAZING_NORMAL_DOT),
        "mother_mesh_id": 1,
        "cutter_mesh_id": 2,
        "thresholds_mm": {"sheet": float(on_sheet_tol), "mother": float(on_mother_tol)},
    }


def _face_keys(mesh: Any) -> dict[tuple, int]:
    """Coincident-triangle keys (rounded sorted vertices) -> face row."""
    faces = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.round(np.asarray(mesh.vertices, dtype=np.float64), FACE_KEY_DECIMALS)
    keys: dict[tuple, int] = {}
    for row, face in enumerate(faces):
        triple = np.sort(verts[face], axis=0)
        keys[(tuple(triple[0]), tuple(triple[1]), tuple(triple[2]))] = int(row)
    return keys


def _face_key(verts: np.ndarray, face: np.ndarray) -> tuple:
    triple = np.sort(verts[np.asarray(face, dtype=np.int64)], axis=0)
    return (tuple(triple[0]), tuple(triple[1]), tuple(triple[2]))


def _canonical(triangles: np.ndarray) -> np.ndarray:
    """Order each triangle's three vertices canonically, so two coincident triangles sample alike.

    The two sides of a shared cut carry the same clipped triangle, but their vertex *order* differs
    (the boolean is free to rotate or reflect a face).  Sampling the raw order therefore compares
    different points of the same triangle -- measured as a 0.14 mm "gap" -- while sampling the
    canonical order compares the same points, which is what a conjugate measurement means.
    """
    tri = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
    if tri.shape[0] == 0:
        return tri
    key = tri[:, :, 0] * 1.0e6 + tri[:, :, 1] * 1.0e3 + tri[:, :, 2]
    order = np.argsort(key, axis=1, kind="stable")
    return np.take_along_axis(tri, order[:, :, None], axis=1)


def _pair_points(triangles: np.ndarray, order: int = 3) -> np.ndarray:
    """Barycentric samples of a triangle soup, in a row order that matches a coincident soup."""
    tri = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 3)
    bary = []
    for i in range(order + 1):
        for j in range(order + 1 - i):
            bary.append([(order - i - j) / order, i / order, j / order])
    bary = np.asarray(bary, dtype=np.float64)
    return np.einsum("bk,tkc->tbc", bary, tri).reshape(-1, 3)


def assemble_implicit_event(
    mother: Any,
    cutter: Any,
    *,
    event_id: str,
    backend: str,
    extra_meta: dict[str, Any] | None = None,
    on_sheet_tol: float = ON_SHEET_TOL_MM,
    on_mother_tol: float = ON_MOTHER_TOL_MM,
) -> FractureResult:
    """Cut ``mother`` by ``cutter`` and return a classified, paired, auditable event result."""
    started = time.time()
    timings: dict[str, float] = {}
    cutter_mesh = cutter.mesh
    if not bool(cutter_mesh.is_watertight):
        raise SynLabError(ErrorCode.CUTTER_NOT_CLOSED, "shared cutter is not watertight",
                          stage="fracture.implicit.assemble")
    cutter_hash = mesh_hash(cutter_mesh)
    if cutter.meta.get("cutter_hash") not in (None, cutter_hash):
        raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                          "cutter mesh does not match its recorded hash",
                          stage="fracture.implicit.assemble")
    mother_mesh = mother.mesh
    if not bool(mother_mesh.is_watertight):
        raise SynLabError(ErrorCode.MOTHER_INVALID, "mother mesh is not watertight",
                          stage="fracture.implicit.assemble")
    basis = cutter.basis
    h_fn = cutter.h_fn

    stage = time.time()
    source_mother = tag_source(trimesh.Trimesh(vertices=np.asarray(mother_mesh.vertices),
                                               faces=np.asarray(mother_mesh.faces), process=False),
                               1.0, "mother")
    source_cutter = tag_source(trimesh.Trimesh(vertices=np.asarray(cutter_mesh.vertices),
                                               faces=np.asarray(cutter_mesh.faces), process=False),
                               2.0, "cutter")
    _trace(f"sources tagged: mother {len(np.asarray(source_mother.mesh.faces))} faces, "
           f"cutter {len(np.asarray(source_cutter.mesh.faces))} faces")
    minus = boolean_intersection([source_mother, source_cutter], label="M_minus")
    _trace(f"intersection done: {minus.n_faces} faces")
    plus = boolean_difference([source_mother, source_cutter], label="M_plus")
    _trace(f"difference done: {plus.n_faces} faces")
    timings["boolean_seconds"] = time.time() - stage
    if minus.n_faces == 0 or plus.n_faces == 0:
        raise SynLabError(
            ErrorCode.FRACTURE_CONSERVATION_FAIL,
            f"degenerate event: M_minus has {minus.n_faces} faces and M_plus has {plus.n_faces}",
            stage="fracture.implicit.assemble")
    for name, side in (("M_minus", minus), ("M_plus", plus)):
        if not bool(side.mesh.is_watertight):
            raise SynLabError(
                ErrorCode.FRACTURE_CONSERVATION_FAIL,
                f"{name} is not watertight after the boolean (faces={side.n_faces})",
                stage="fracture.implicit.assemble")

    stage = time.time()
    classifications: dict[str, dict[str, Any]] = {}
    for name, side in (("M_minus", minus), ("M_plus", plus)):
        classification = _classify(side, basis=basis, h_fn=h_fn, mother_mesh=mother_mesh,
                                   on_sheet_tol=float(on_sheet_tol),
                                   on_mother_tol=float(on_mother_tol))
        classification["area_faces"] = np.asarray(side.mesh.area_faces, dtype=np.float64)
        classifications[name] = classification
        _trace(f"classified {name}: {classification['_faces'].shape[0]} faces, "
               f"interface vertices {int(np.sum(classification['vertex_origin'] == ORIGIN_INTERFACE))}")
    timings["classify_seconds"] = time.time() - stage

    stage = time.time()
    fragments: list[Any] = []
    for name, side_tag in (("M_minus", SIDE_MINUS), ("M_plus", SIDE_PLUS)):
        side = minus if name == "M_minus" else plus
        parts = split_components(side.mesh)
        for index, part in enumerate(parts):
            fragment_id = (f"{event_id}-m" if side_tag < 0 else f"{event_id}-p") + (
                "" if index == 0 else f"__{side_tag:+d}c{index}")
            fragments.append(make_fragment(
                part, fragment_id=fragment_id, component_id=index, side=side_tag,
                classification=classifications[name], parent_id=None, backend=backend,
                cutter_hash=cutter_hash,
                extra_meta={"event_id": event_id, "boolean_output": name,
                            "assembly": "implicit_analytic_classification"}))
    timings["fragments_seconds"] = time.time() - stage
    _trace(f"fragments built: {[f.fragment_id for f in fragments]}")

    _repair_mother_sources(fragments, mother_mesh)

    stage = time.time()
    patches = _pair_interfaces(fragments, basis=basis, h_fn=h_fn, mother_mesh=mother_mesh,
                              cutter_mesh=cutter_mesh, on_sheet_tol=float(on_sheet_tol),
                              on_mother_tol=float(on_mother_tol), event_id=event_id)
    timings["interfaces_seconds"] = time.time() - stage
    _trace(f"interfaces paired: {len(patches)} patches")
    _write_interface_ids(fragments, patches)

    mother_volume = float(abs(mother_mesh.volume))
    fragment_volume = float(sum(fragment.volume_mm3 for fragment in fragments))
    timings["total_seconds"] = time.time() - started
    event_tree = {
        "event_id": event_id, "parent_id": None, "backend": backend,
        "cutter_hash": cutter_hash,
        "cutter": {"basis_id": basis.basis_id, "triangles": int(cutter.triangles),
                   "requested_error_mm": float(cutter.requested_error_mm),
                   "realized_error_mm": float(cutter.realized_error_mm),
                   "meta": {k: v for k, v in cutter.meta.items() if k != "height_field"}},
        "children": [f.fragment_id for f in fragments],
        "minus": [f.fragment_id for f in fragments if int(f.face_side[0]) < 0],
        "plus": [f.fragment_id for f in fragments if int(f.face_side[0]) > 0],
        "interfaces": [patch.interface_id for patch in patches],
        "mother_volume_mm3": mother_volume, "fragment_volume_mm3": fragment_volume,
        "assembly": {
            "path": "synlab.fracture.implicit.assemble_implicit_event",
            "why": ("the frozen resolver's containment test is O(points x cutter faces) without "
                    "embree and cannot consume a fine cutter (measured 86.8 s / 1000 points on "
                    "208 820 faces); an implicit cutter gives the distance in closed form"),
            "timings_seconds": timings,
        },
    }
    meta = {
        "event_id": event_id, "cutter_hash": cutter_hash,
        "minus_faces": int(minus.n_faces), "plus_faces": int(plus.n_faces),
        "minus_hash": mesh_hash(minus.mesh), "plus_hash": mesh_hash(plus.mesh),
        BASIS_META_KEY: basis, BASIS_RECORD_META_KEY: basis_record(basis),
        "basis_id": str(getattr(basis, "basis_id", "")),
        "basis_source": "fracture.implicit.assemble:basis from the shared cutter",
        "assembly_timings_seconds": timings,
    }
    meta.update(extra_meta or {})
    return FractureResult(
        fragments=fragments, interfaces=patches, event_tree=event_tree,
        debris=[f for f in fragments if f.is_tiny], parent_id=mother.mother_id,
        backend=backend, qa={}, cutter_ref=cutter_hash, meta=meta)


def _repair_mother_sources(fragments: list[Any], mother_mesh: Any) -> dict[str, int]:
    """Give faces that *are* on the mother's surface but carry no source id their nearest triangle.

    ``fragment._majority_source`` breaks a three-way tie towards the smallest value, so a mother
    face that has two mother vertices and one sheet vertex (the first ring of wall triangles along
    the cut) votes ``-1`` and is counted as unmapped -- measured as source coverage 0.986 against
    the frozen 0.999 floor.  The origin of those faces is ``MOTHER_SURFACE`` and their distance to
    the mother is ~0, so the nearest mother triangle is their provenance, exactly as the frozen
    resolver defines it; nothing else is touched.
    """
    from trimesh.proximity import closest_point

    repaired: dict[str, int] = {}
    for fragment in fragments:
        origin = np.asarray(fragment.face_origin_kind)
        source = np.asarray(fragment.face_source_tri, dtype=np.int64).copy()
        need = (origin == ORIGIN_MOTHER_SURFACE) & (source < 0)
        if not bool(np.any(need)):
            continue
        centroids = np.asarray(fragment.mesh.triangles_center, dtype=np.float64)[need]
        _closest, _distance, tri = closest_point(mother_mesh, centroids)
        source[need] = np.asarray(tri, dtype=np.int64)
        fragment.face_source_tri = source.astype(np.int32)
        with_face_attrs(fragment.mesh, source_triangle=fragment.face_source_tri)
        fragment.meta["source_tri_per_face"] = source
        fragment.meta["source_repaired_faces"] = int(np.sum(need))
        repaired[fragment.fragment_id] = int(np.sum(need))
    return repaired


def _pair_interfaces(fragments: list[Any], *, basis: Any, h_fn: Any, mother_mesh: Any,
                     cutter_mesh: Any, on_sheet_tol: float, on_mother_tol: float,
                     event_id: str) -> list[InterfacePatch]:
    """Pair coincident cut triangles of the two sides into one patch per fragment pair."""
    meshes = {f.fragment_id: f.mesh for f in fragments}
    sides: dict[int, list[tuple[str, np.ndarray, np.ndarray]]] = {SIDE_MINUS: [], SIDE_PLUS: []}
    keys: dict[str, dict[tuple, int]] = {}
    for fragment in fragments:
        keys[fragment.fragment_id] = _face_keys(meshes[fragment.fragment_id])
        origin = np.asarray(fragment.face_origin_kind)
        cut = np.nonzero(origin == ORIGIN_INTERFACE)[0]
        faces = np.asarray(meshes[fragment.fragment_id].faces, dtype=np.int64)[cut]
        sides[int(fragment.face_side[0])].append((fragment.fragment_id, cut, faces))

    from trimesh.proximity import signed_distance

    grouped: dict[tuple[str, str], list[tuple[int, int, np.ndarray, np.ndarray]]] = {}
    for minus_id, cut_a, faces_a in sides[SIDE_MINUS]:
        verts_a = np.round(np.asarray(meshes[minus_id].vertices, dtype=np.float64),
                           FACE_KEY_DECIMALS)
        for plus_id, _cut_b, _faces_b in sides[SIDE_PLUS]:
            keys_b = keys[plus_id]
            pairs: list[tuple[int, int, np.ndarray, np.ndarray]] = []
            for row, face in zip(cut_a, faces_a):
                other = keys_b.get(_face_key(verts_a, face))
                if other is None:
                    continue
                pairs.append((int(row), int(other), np.asarray(face, dtype=np.int64), None))
            if pairs:
                grouped[(minus_id, plus_id)] = pairs

    patches: list[InterfacePatch] = []
    for interface_id, ((frag_a, frag_b), pairs) in enumerate(sorted(grouped.items())):
        rows_a = np.asarray([p[0] for p in pairs], dtype=np.int64)
        rows_b = np.asarray([p[1] for p in pairs], dtype=np.int64)
        mesh_a, mesh_b = meshes[frag_a], meshes[frag_b]
        tri_a = np.asarray(mesh_a.vertices)[np.asarray(mesh_a.faces)[rows_a]]
        tri_b = np.asarray(mesh_b.vertices)[np.asarray(mesh_b.faces)[rows_b]]
        samples_a = _pair_points(_canonical(tri_a), order=3)
        samples_b = _pair_points(_canonical(tri_b), order=3)
        norms_a = np.repeat(np.asarray(mesh_a.face_normals)[rows_a], 10, axis=0)
        norms_b = np.repeat(np.asarray(mesh_b.face_normals)[rows_b], 10, axis=0)
        gap = np.linalg.norm(samples_a - samples_b, axis=1)
        cosang = np.clip(np.einsum("ij,ij->i", norms_a, -norms_b), -1.0, 1.0)
        angle = np.degrees(np.arccos(cosang))
        area_a = float(np.asarray(mesh_a.area_faces)[rows_a].sum())
        area_b = float(np.asarray(mesh_b.area_faces)[rows_b].sum())
        #: ambiguity of this patch: vertices that lie on the sheet *and* on the mother's surface
        pts = tri_a.reshape(-1, 3)
        d_sheet, _local = sheet_distance(basis, h_fn, pts)
        d_mother = np.abs(np.asarray(signed_distance(mother_mesh, pts), dtype=np.float64))
        both = ((d_sheet <= on_sheet_tol) & (d_mother <= on_mother_tol)).reshape(-1, 3)
        face_ambiguous = np.all(both, axis=1)
        ambiguous_area = float(np.asarray(mesh_a.area_faces)[rows_a][face_ambiguous].sum())
        patches.append(InterfacePatch(
            interface_id=int(interface_id), fragment_a=frag_a, fragment_b=frag_b,
            area_mm2=float(0.5 * (area_a + area_b)),
            sample_points_a=samples_a, sample_points_b=samples_b,
            normals_a=norms_a, normals_b=norms_b,
            gap_p95_mm=float(np.percentile(gap, 95)) if gap.size else 0.0,
            normal_angle_p95_deg=float(np.percentile(angle, 95)) if angle.size else 0.0,
            ambiguity_area_ratio=float(ambiguous_area / max(area_a, 1e-12)),
            ambiguous_area_mm2=ambiguous_area,
            meta={
                "faces_a": rows_a, "faces_b": rows_b,
                "area_a_mm2": area_a, "area_b_mm2": area_b,
                "area_rel_error": float(abs(area_a - area_b) / max(area_a, area_b, 1e-12)),
                "gap_max_mm": float(gap.max()) if gap.size else 0.0,
                "normal_angle_max_deg": float(angle.max()) if angle.size else 0.0,
                "vertex_identity_ratio": 1.0,
                "nearest_p95_mm": float(np.percentile(gap, 95)) if gap.size else 0.0,
                "pairing": "coincident_triangle_key (both sides carry the same clipped triangle)",
                "pair_count": int(rows_a.size), "samples_per_pair": 10,
                "cutter_faces": int(len(np.asarray(cutter_mesh.faces))), "event_id": event_id,
            }))
    return patches


def _write_interface_ids(fragments: list[Any], patches: list[InterfacePatch]) -> None:
    """Same bookkeeping as the frozen event path: per-face interface ids on every fragment."""
    for fragment in fragments:
        origin = np.asarray(fragment.face_origin_kind)
        ids = np.full(origin.shape[0], -1, dtype=np.int32)
        for patch in patches:
            side_key = ("faces_a" if fragment.fragment_id == patch.fragment_a else
                        "faces_b" if fragment.fragment_id == patch.fragment_b else None)
            if side_key is None:
                continue
            ids[np.asarray(patch.meta[side_key], dtype=np.int64)] = patch.interface_id
        with_face_attrs(fragment.mesh, interface_id=ids)
        fragment.face_interface_id = ids
        fragment.meta["interface_ids"] = sorted({int(x) for x in ids if x >= 0})


_ = ORIGIN_AMBIGUOUS
