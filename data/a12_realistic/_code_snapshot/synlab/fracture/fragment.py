"""Material-body splitting, fragment bookkeeping, interface patches and the shared auditor.

One fracture event is described by exactly one shared discrete solid ``C``:

* ``M_- = M ∩ C`` and ``M_+ = M \\ C`` are produced with the *same* bytes, tolerance and hash;
* **all** connected components are split out, tiny debris included, and they all stay in the
  conservation denominator (plan 10.3);
* every output face records ``origin_kind`` (mother surface / interface / ambiguous), its
  original mother triangle id, the interface id and the side;
* the interface between a ``-`` leaf and a ``+`` leaf is the complementary set of clipped
  source triangles, sampled on the common patch with barycentric reconstruction and a
  coordinate-residual check (plan 30.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import trimesh

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import (
    ORIGIN_AMBIGUOUS,
    ORIGIN_INTERFACE,
    ORIGIN_MOTHER_SURFACE,
    Fragment,
    InterfacePatch,
)
from ..storage.mesh_io import with_face_attrs
from .booleans import SourceResolver, SourceTaggedResult, mesh_hash
from .spec import (
    AMBIGUITY_AREA_RATIO_MAX,
    INTERFACE_GAP_P95_MM,
    NORMAL_REVERSAL_P95_DEG,
    OVERLAP_RATIO_MAX,
    TINY_DIAMETER_MM,
    TINY_VOLUME_MM3,
    VOLUME_REL_TOL,
)

__all__ = [
    "SplitPart",
    "split_components",
    "compact_mesh",
    "make_fragment",
    "build_interface",
    "overlap_ratio",
    "audit_fracture_result",
]

_EPS = 1.0e-12
#: quantisation used to match vertices across the two boolean outputs (mm)
_MATCH_QUANT = 1.0e-6


def _stable_seed(payload: dict[str, Any]) -> int:
    """Deterministic 63-bit seed from a canonical hash string (``hash_json`` returns text)."""
    digest = hash_json(payload).split(":", 1)[-1]
    return int(digest[:16], 16) % (2 ** 63)


# ---------------------------------------------------------------------------- splitting


@dataclass
class SplitPart:
    """One connected component of a boolean output."""

    faces: np.ndarray            # positions in the parent face array
    mesh: trimesh.Trimesh        # compacted geometry, vertex order preserved
    vertex_index: np.ndarray     # (n_local_vertices,) positions in the parent vertex array
    volume_mm3: float
    area_mm2: float


def compact_mesh(mesh: trimesh.Trimesh, face_ids: np.ndarray) -> tuple[trimesh.Trimesh, np.ndarray]:
    """Extract a face subset, compacting vertices but keeping a parent-index map."""
    faces = np.asarray(mesh.faces, dtype=np.int64)[np.asarray(face_ids, dtype=np.int64)]
    used, inverse = np.unique(faces.reshape(-1), return_inverse=True)
    new_faces = inverse.reshape(-1, 3)
    new_vertices = np.asarray(mesh.vertices, dtype=np.float64)[used]
    return trimesh.Trimesh(vertices=new_vertices, faces=new_faces, process=False), used


def split_components(mesh: trimesh.Trimesh) -> list[SplitPart]:
    """Split *all* connected components with a deterministic stable ordering."""
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if faces.shape[0] == 0:
        return []
    labels = trimesh.graph.connected_component_labels(
        np.asarray(mesh.face_adjacency), node_count=int(faces.shape[0]))
    parts: list[SplitPart] = []
    for label in sorted(set(int(x) for x in labels)):
        face_ids = np.nonzero(labels == label)[0]
        sub, used = compact_mesh(mesh, face_ids)
        parts.append(SplitPart(faces=face_ids, mesh=sub, vertex_index=used,
                               volume_mm3=float(abs(sub.volume)), area_mm2=float(sub.area)))
    parts.sort(key=lambda part: (-round(part.volume_mm3, 9), -round(part.area_mm2, 9),
                                tuple(np.round(np.asarray(part.mesh.bounds), 9).reshape(-1).tolist())))
    return parts


def is_tiny(part: SplitPart) -> bool:
    extent = np.asarray(part.mesh.extents, dtype=np.float64)
    return bool(part.volume_mm3 < TINY_VOLUME_MM3
                or float(np.max(extent)) < TINY_DIAMETER_MM)


# ---------------------------------------------------------------------------- fragments


def _majority_source(faces: np.ndarray, values: np.ndarray, fallback: int = -1) -> np.ndarray:
    """Per-face source id chosen by majority vote of its vertices."""
    out = np.full(faces.shape[0], fallback, dtype=np.int64)
    for index, face in enumerate(faces):
        vertices = np.asarray(face, dtype=np.int64)
        vals = np.asarray(values, dtype=np.int64)[vertices]
        out[index] = int(np.bincount(vals - vals.min()).argmax() + vals.min())
    return out


def make_fragment(
    part: SplitPart,
    *,
    fragment_id: str,
    component_id: int,
    side: int,
    classification: dict[str, Any],
    parent_id: str | None,
    backend: str,
    cutter_hash: str,
    extra_meta: dict[str, Any] | None = None,
) -> Fragment:
    """Attach face-level origin semantics to one component and wrap it as a ``Fragment``."""
    faces = np.asarray(part.mesh.faces, dtype=np.int64)
    parent_faces = np.asarray(classification["_faces"], dtype=np.int64)[part.faces]
    origin_vertex = np.asarray(classification["vertex_origin"], dtype=np.uint8)
    source_vertex = np.asarray(classification["vertex_source_tri"], dtype=np.int64)
    ambiguous_vertex = np.asarray(classification["vertex_ambiguous"], dtype=bool)
    mesh_id_vertex = np.asarray(classification["vertex_mesh_id"], dtype=np.int64)

    face_origin = _majority_source(parent_faces, origin_vertex, ORIGIN_MOTHER_SURFACE).astype(np.uint8)
    face_source = _majority_source(parent_faces, source_vertex, -1).astype(np.int32)
    face_mesh_id = _majority_source(parent_faces, mesh_id_vertex, -1).astype(np.int32)
    face_ambiguous = np.array([
        bool(np.all(ambiguous_vertex[np.asarray(face, dtype=np.int64)])) for face in parent_faces
    ], dtype=bool)
    face_origin[face_ambiguous] = ORIGIN_AMBIGUOUS
    face_mother_source = np.where(face_mesh_id == int(classification["mother_mesh_id"]),
                                  face_source, -1).astype(np.int32)
    face_interface = np.full(faces.shape[0], -1, dtype=np.int32)
    face_side = np.full(faces.shape[0], int(side), dtype=np.int8)

    mesh = trimesh.Trimesh(vertices=np.asarray(part.mesh.vertices, dtype=np.float64),
                           faces=faces, process=False)
    with_face_attrs(
        mesh,
        origin_kind=face_origin,
        source_tri=face_mother_source,
        interface_id=face_interface,
        side=face_side,
        ambiguous=face_ambiguous.astype(np.uint8),
    )
    mesh.metadata = dict(mesh.metadata or {})
    mesh.metadata["fragment_id"] = fragment_id
    mesh.metadata["side"] = int(side)
    mesh.metadata["cutter_hash"] = cutter_hash
    meta = dict(extra_meta or {})
    meta.update({
        "ambiguous_area_mm2": float(np.sum(np.asarray(mesh.area_faces)[face_ambiguous])),
        "interface_area_mm2": float(np.sum(np.asarray(mesh.area_faces)[face_origin == ORIGIN_INTERFACE])),
        "mother_surface_area_mm2": float(np.sum(np.asarray(mesh.area_faces)[face_origin == ORIGIN_MOTHER_SURFACE])),
        "mesh_hash": mesh_hash(mesh),
        "cutter_hash": cutter_hash,
        "mesh_id_per_face": face_mesh_id,
        "source_tri_per_face": face_source,
        "mother_mesh_id": int(classification["mother_mesh_id"]),
        "cutter_mesh_id": int(classification["cutter_mesh_id"]),
    })
    return Fragment(
        fragment_id=fragment_id,
        mesh=mesh,
        volume_mm3=float(abs(mesh.volume)),
        area_mm2=float(mesh.area),
        face_origin_kind=face_origin,
        face_source_tri=face_mother_source,
        face_interface_id=face_interface,
        face_side=face_side,
        component_id=int(component_id),
        is_tiny=is_tiny(part),
        parent_id=parent_id,
        meta=meta,
    )


# ---------------------------------------------------------------------------- interfaces


@dataclass
class _InterfaceGroup:
    source_tris: list[int] = field(default_factory=list)
    faces_a: list[int] = field(default_factory=list)
    faces_b: list[int] = field(default_factory=list)


#: frozen tolerance (mm) for "this output face really lies on the shared discrete cutter surface"
CLIP_ON_SURFACE_TOL_MM = 1.0e-4
#: frozen 2D snapping tolerance (mm) for the clipped polygons; the corrected area is recorded
CLIP_SNAP_TOL_MM = 1.0e-6
#: barycentric slack used when locating the output triangle that owns a clipped sample point
CLIP_BARY_TOL = 1.0e-9
#: per source triangle: at least one sample, at most this many (area-weighted, plan 30.5)
CLIP_MAX_SAMPLES_PER_SOURCE = 40
#: max deviation (mm) for treating both sides' cut faces as one plane in the pair-level measure
PAIR_PLANE_TOL_MM = 1.0e-3
#: cache slot inside ``Fragment.meta``; ``pipeline._commit_fragments`` persists named fields only,
#: so this never reaches an asset
_CLIP_CACHE = "_shared_clip_cache"


def _valid_faces(mesh: trimesh.Trimesh, faces: Any) -> np.ndarray:
    ids = np.asarray(list(faces or ()), dtype=np.int64).reshape(-1)
    if ids.size == 0:
        return ids
    return ids[(ids >= 0) & (ids < len(np.asarray(mesh.faces)))]


def _cutter_key(cutter_mesh: trimesh.Trimesh) -> tuple[int, tuple[float, ...]]:
    bounds = np.round(np.asarray(cutter_mesh.bounds, dtype=np.float64), 6).reshape(-1)
    return (int(len(np.asarray(cutter_mesh.faces))), tuple(float(x) for x in bounds))


def _clip_cache(fragment: Fragment) -> dict[Any, Any]:
    return fragment.meta.setdefault(_CLIP_CACHE, {})


def _nearest_cutter_triangles(mesh: trimesh.Trimesh, faces: np.ndarray,
                              cutter_mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """Nearest cutter triangle of each face centroid plus its distance (plan 30.5 geometric key)."""
    ids = np.asarray(faces, dtype=np.int64)
    if ids.size == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64)
    centres = np.asarray(mesh.triangles_center, dtype=np.float64)[ids]
    _closest, distance, triangle = cutter_mesh.nearest.on_surface(centres)
    return (np.asarray(triangle, dtype=np.int64).reshape(-1),
            np.asarray(distance, dtype=np.float64).reshape(-1))


def _face_source_lookup(fragment: Fragment, cutter_mesh: trimesh.Trimesh,
                        faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-face (nearest cutter triangle, distance) with a per-cutter cache on the fragment."""
    ids = np.asarray(faces, dtype=np.int64)
    table = _clip_cache(fragment).setdefault(("sources", _cutter_key(cutter_mesh)), {})
    missing = np.asarray([int(f) for f in ids if int(f) not in table], dtype=np.int64)
    if missing.size:
        triangle, distance = _nearest_cutter_triangles(fragment.mesh, missing, cutter_mesh)
        for face, source, dist in zip(missing, triangle, distance):
            table[int(face)] = (int(source), float(dist))
    if ids.size == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64)
    source = np.asarray([table[int(f)][0] for f in ids], dtype=np.int64)
    distance = np.asarray([table[int(f)][1] for f in ids], dtype=np.float64)
    return source, distance


def _cut_face_table(fragment: Fragment, cutter_mesh: trimesh.Trimesh
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Every cut face of one fragment that really lies on the shared cutter surface.

    Returns ``(faces, source_triangles, centroids, face_radius_mm)`` where the radius bounds the
    centroid-to-vertex distance, i.e. a face whose centroid is farther than
    ``circumradius(t) + face_radius`` from a cutter triangle cannot overlap it.  Cached per
    fragment and cutter.
    """
    cache = _clip_cache(fragment)
    hit = cache.get(("cut_faces", _cutter_key(cutter_mesh)))
    if hit is not None:
        return hit
    mesh = fragment.mesh
    origin = np.asarray(fragment.face_origin_kind)
    candidate = np.nonzero((origin == ORIGIN_INTERFACE) | (origin == ORIGIN_AMBIGUOUS))[0]
    faces = np.zeros(0, dtype=np.int64)
    sources = np.zeros(0, dtype=np.int64)
    centroids = np.zeros((0, 3), dtype=np.float64)
    radius = 0.0
    if candidate.size:
        triangles = np.asarray(mesh.triangles, dtype=np.float64)[candidate]
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        used = np.unique(np.asarray(mesh.faces, dtype=np.int64)[candidate].reshape(-1))
        distances = np.full(vertices.shape[0], np.inf, dtype=np.float64)
        distances[used] = np.asarray(
            cutter_mesh.nearest.on_surface(vertices[used])[1], dtype=np.float64)
        on_surface = distances[np.asarray(mesh.faces, dtype=np.int64)[candidate]] \
            <= CLIP_ON_SURFACE_TOL_MM
        keep = np.all(on_surface, axis=1)
        if bool(np.any(keep)):
            faces = candidate[keep].astype(np.int64)
            centres = np.asarray(mesh.triangles_center, dtype=np.float64)[faces]
            centroids = centres
            _closest, _distance, triangle = cutter_mesh.nearest.on_surface(centres)
            sources = np.asarray(triangle, dtype=np.int64).reshape(-1)
            local = triangles[keep] - centres[:, None, :]
            radius = float(np.max(np.linalg.norm(local, axis=2))) if faces.size else 0.0
    entry = (faces, sources, centroids, radius)
    cache[("cut_faces", _cutter_key(cutter_mesh))] = entry
    return entry


def _cutter_frame(cutter_mesh: trimesh.Trimesh, source: int
                  ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    """Local orthonormal 2D basis of one source triangle: ``(origin, e1, e2, normal)``."""
    triangle = np.asarray(cutter_mesh.triangles[int(source)], dtype=np.float64)
    normal = np.asarray(cutter_mesh.face_normals[int(source)], dtype=np.float64)
    edge = triangle[1] - triangle[0]
    length = float(np.linalg.norm(edge))
    norm = float(np.linalg.norm(normal))
    if length <= _EPS or norm <= _EPS:
        return None
    e1 = edge / length
    unit_normal = normal / norm
    e2 = np.cross(unit_normal, e1)
    width = float(np.linalg.norm(e2))
    if width <= _EPS:
        return None
    return triangle[0].copy(), e1, e2 / width, unit_normal


def _project(triangles: np.ndarray, frame: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
             ) -> np.ndarray:
    origin, e1, e2, _normal = frame
    rel = np.asarray(triangles, dtype=np.float64).reshape(-1, 3) - origin
    flat = np.stack([rel @ e1, rel @ e2], axis=1)
    return flat.reshape(np.shape(triangles)[0], 3, 2)


def _union_2d(triangles_2d: np.ndarray) -> Any:
    """Planar union of a triangle soup (``None`` when nothing remains)."""
    import shapely

    if triangles_2d.shape[0] == 0:
        return None
    polygons = shapely.polygons(np.asarray(triangles_2d, dtype=np.float64))
    polygons = polygons[~shapely.is_empty(polygons)]
    if polygons.shape[0] == 0:
        return None
    union = shapely.union_all(polygons)
    return None if union.is_empty else union


def _snap_2d(geometry: Any) -> tuple[Any, float]:
    """Snap a clipped polygon onto the frozen tolerance grid, returning the corrected area."""
    import shapely

    area_before = float(shapely.area(geometry))
    if not hasattr(shapely, "set_precision"):
        return geometry, 0.0
    snapped = shapely.set_precision(geometry, CLIP_SNAP_TOL_MM)
    return snapped, abs(float(shapely.area(snapped)) - area_before)


def _partition_triangles(geometry: Any) -> list[Any]:
    """Disjoint shared triangulation of a clipped polygon (plan 30.5)."""
    import shapely
    from shapely.ops import triangulate

    parts = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
    out: list[Any] = []
    for part in parts:
        if part.is_empty or float(shapely.area(part)) <= _EPS:
            continue
        for triangle in triangulate(part):
            if part.covers(triangle.representative_point()):
                out.append(triangle)
    return out


def _barycentric_2d(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """``(N, T, 3)`` barycentric coordinates of every point against every triangle."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    tris = np.asarray(triangles, dtype=np.float64).reshape(-1, 3, 2)
    apex = tris[:, 0, :]
    v0 = tris[:, 1, :] - apex
    v1 = tris[:, 2, :] - apex
    rel = pts[:, None, :] - apex[None, :, :]
    d00 = np.einsum("td,td->t", v0, v0)
    d01 = np.einsum("td,td->t", v0, v1)
    d11 = np.einsum("td,td->t", v1, v1)
    d20 = np.einsum("ntd,td->nt", rel, v0)
    d21 = np.einsum("ntd,td->nt", rel, v1)
    denom = d00 * d11 - d01 * d01
    denom = np.where(np.abs(denom) < 1e-300, 1e-300, denom)
    v = (d11[None, :] * d20 - d01[None, :] * d21) / denom[None, :]
    w = (d00[None, :] * d21 - d01[None, :] * d20) / denom[None, :]
    return np.stack([1.0 - v - w, v, w], axis=-1)


def _triangle_key(triangles_3d: np.ndarray, row: int) -> tuple:
    """Geometry key of one triangle, so coincident duplicates are not counted as ambiguity."""
    rounded = np.round(np.asarray(triangles_3d[row], dtype=np.float64) / CLIP_SNAP_TOL_MM)
    return tuple(sorted(tuple(int(x) for x in vertex) for vertex in rounded))


def _locate_point(point_2d: np.ndarray, triangles_2d: np.ndarray, triangles_3d: np.ndarray
                  ) -> tuple[int, int, str]:
    """Locate the output triangle that owns one clipped point.

    Returns ``(row, owners, reason)``: the chosen triangle (``-1`` when the point lies outside
    every triangle of that side), the number of *geometrically distinct* triangles that contain
    it, and why.  Coincident duplicates of the same triangle count as one owner, not as
    ambiguity: the boolean outputs carry doubled coplanar faces on a cut sheet, and plan 30.5
    asks for ambiguity of *attribution*, not for double bookkeeping.  A point that is genuinely
    on the shared edge of two different triangles, or inside two different triangles, keeps
    ``owners > 1`` and stays ``AMBIGUOUS`` — plan 30.5 explicitly forbids forcing a boundary point
    into a unique match.
    """
    if triangles_2d.shape[0] == 0:
        return -1, 0, "no_output_triangle"
    bary = _barycentric_2d(point_2d.reshape(1, 2), triangles_2d)[0]
    inside = np.nonzero(np.all(bary >= -CLIP_BARY_TOL, axis=1))[0]
    if inside.size == 0:
        return -1, 0, "outside_all_output_triangles"
    distinct: dict[tuple, int] = {}
    for row in inside:
        distinct.setdefault(_triangle_key(triangles_3d, int(row)), int(row))
    if len(distinct) == 1:
        return next(iter(distinct.values())), 1, ""
    # genuine multi-attribution: keep the triangle the point sits deepest inside, deterministically
    best = min(distinct.values(), key=lambda row: (-float(np.min(bary[row])), int(row)))
    return int(best), len(distinct), "multiple_output_triangles"


def _face_keys(mesh: trimesh.Trimesh) -> list[tuple[tuple[int, int, int], ...]]:
    rounded = np.round(np.asarray(mesh.vertices, dtype=np.float64), 6)
    lookup: dict[tuple[float, float, float], int] = {}
    keys: list[tuple[int, int, int]] = []
    for index, vertex in enumerate(rounded):
        key = (float(vertex[0]), float(vertex[1]), float(vertex[2]))
        lookup.setdefault(key, index)
        keys.append(lookup[key])
    return [tuple(int(keys[int(v)]) for v in face) for face in np.asarray(mesh.faces)]


def _pair_components(pairs_a: list[int], pairs_b: list[int], keys_a: list, keys_b: list,
                     ) -> list[tuple[list[int], list[int]]]:
    """Group coincident face pairs into connected interface components."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)

    edge_owner: dict[tuple[int, int], int] = {}
    for index, (face_a, face_b) in enumerate(zip(pairs_a, pairs_b)):
        find(index)
        for keys, face in ((keys_a, face_a), (keys_b, face_b)):
            face_key = keys[face]
            for k in range(3):
                edge = tuple(sorted((face_key[k], face_key[(k + 1) % 3])))
                other = edge_owner.get(edge)
                if other is not None:
                    union(index, other)
                else:
                    edge_owner[edge] = index
    groups: dict[int, tuple[list[int], list[int]]] = {}
    for index in range(len(pairs_a)):
        root = find(index)
        bucket = groups.setdefault(root, ([], []))
        bucket[0].append(pairs_a[index])
        bucket[1].append(pairs_b[index])
    return [groups[key] for key in sorted(groups)]


def build_interface(
    *,
    interface_id: int,
    fragment_a: Fragment,
    fragment_b: Fragment,
    faces_a: list[int],
    faces_b: list[int],
    source_tri: int,
    cutter_mesh: trimesh.Trimesh,
    sample_target: int = 24,
) -> tuple[InterfacePatch, list[tuple[np.ndarray, np.ndarray, int, np.ndarray, int, np.ndarray]]]:
    """Build one shared interface patch the way plan 30.5 prescribes.

    The patch's faces are grouped by their **source cutter triangle**; inside each source
    triangle's local 2D basis both sides' output triangles are collected, the common coverage is
    computed with 2D intersection / difference, the result is split into disjoint polygons,
    triangulated once and sampled area-weighted.  Sample points go back to 3D and are rebuilt on
    *both* sides by barycentric reconstruction, so a point that lies outside the opposite
    triangle can no longer be produced by construction.

    ``area_mm2`` is the measured **common clipped coverage** (the previously reported
    ``0.5 * (area_a + area_b)`` was a pairing artefact).  A source triangle that only one side
    covers, or whose two sides share nothing, contributes no patch area instead of a fake
    interface.

    Ambiguity counts only points that cannot be attributed uniquely: none of that side's output
    triangles contains the point, or two geometrically *distinct* triangles contain it.  A point
    that lands on the shared edge of two neighbouring triangles of one triangulation is not
    genuine ambiguity and is resolved deterministically.
    """
    import shapely

    mesh_a, mesh_b = fragment_a.mesh, fragment_b.mesh
    ids_a = _valid_faces(mesh_a, faces_a)
    ids_b = _valid_faces(mesh_b, faces_b)
    source_a, _distance_a = _face_source_lookup(fragment_a, cutter_mesh, ids_a)
    source_b, _distance_b = _face_source_lookup(fragment_b, cutter_mesh, ids_b)

    groups: dict[int, list[list[int]]] = {}
    for face, source in zip(ids_a, source_a):
        if int(source) >= 0:
            groups.setdefault(int(source), [[], []])[0].append(int(face))
    for face, source in zip(ids_b, source_b):
        if int(source) >= 0:
            groups.setdefault(int(source), [[], []])[1].append(int(face))

    triangles_a = np.asarray(mesh_a.triangles, dtype=np.float64)
    triangles_b = np.asarray(mesh_b.triangles, dtype=np.float64)

    total_area = 0.0
    only_a_area = 0.0
    only_b_area = 0.0
    snapped_area = 0.0
    one_sided_sources: list[int] = []
    source_areas: dict[str, float] = {}
    blocks: list[dict[str, Any]] = []
    for source in sorted(groups):
        mine_a, mine_b = groups[source]
        frame = _cutter_frame(cutter_mesh, source)
        if frame is None or not mine_a or not mine_b:
            if mine_a or mine_b:
                one_sided_sources.append(int(source))
                only_a_area += float(np.sum(np.asarray(mesh_a.area_faces)[mine_a])) if mine_a else 0.0
                only_b_area += float(np.sum(np.asarray(mesh_b.area_faces)[mine_b])) if mine_b else 0.0
            continue
        tri_a = triangles_a[np.asarray(mine_a, dtype=np.int64)]
        tri_b = triangles_b[np.asarray(mine_b, dtype=np.int64)]
        two_d_a = _project(tri_a, frame)
        two_d_b = _project(tri_b, frame)
        union_a = _union_2d(two_d_a)
        union_b = _union_2d(two_d_b)
        if union_a is None or union_b is None:
            continue
        common = shapely.intersection(union_a, union_b)
        if common.is_empty:
            only_a_area += float(shapely.area(union_a))
            only_b_area += float(shapely.area(union_b))
            continue
        only_a_area += float(shapely.area(shapely.difference(union_a, union_b)))
        only_b_area += float(shapely.area(shapely.difference(union_b, union_a)))
        common, corrected = _snap_2d(common)
        snapped_area += float(corrected)
        area = float(shapely.area(common))
        if area <= _EPS:
            continue
        polygons = _partition_triangles(common)
        if not polygons:
            continue
        total_area += area
        source_areas[str(int(source))] = float(area)
        blocks.append({"source": int(source), "frame": frame, "area": float(area),
                       "polygons": polygons, "faces_a": mine_a, "faces_b": mine_b})

    if not blocks:
        empty = np.zeros((0, 3), dtype=np.float64)
        patch = InterfacePatch(
            interface_id=int(interface_id), fragment_a=fragment_a.fragment_id,
            fragment_b=fragment_b.fragment_id, area_mm2=0.0,
            sample_points_a=empty, sample_points_b=empty, normals_a=empty, normals_b=empty,
            gap_p95_mm=0.0, normal_angle_p95_deg=0.0, ambiguity_area_ratio=1.0,
            ambiguous_area_mm2=0.0,
            meta={
                "empty_patch": True, "source_triangles": [int(source_tri)],
                "common_clip_area_mm2": 0.0,
                "one_sided_source_triangles": one_sided_sources,
                "only_a_area_mm2": float(only_a_area), "only_b_area_mm2": float(only_b_area),
                "reason": "no_common_clipped_coverage (cavity / one side only)",
            },
        )
        return patch, []

    points_3d: list[np.ndarray] = []
    points_other: list[np.ndarray] = []
    normals_first: list[np.ndarray] = []
    normals_second: list[np.ndarray] = []
    barys_first: list[np.ndarray] = []
    barys_second: list[np.ndarray] = []
    faces_first: list[np.ndarray] = []
    faces_second: list[np.ndarray] = []
    weights: list[np.ndarray] = []
    ambiguous: list[np.ndarray] = []
    reasons: dict[str, int] = {}
    ambiguous_area = 0.0
    bary_clamp = 0.0

    for block_index, block in enumerate(blocks):
        frame = block["frame"]
        triangles_2d = np.asarray([np.asarray(t.exterior.coords)[:3] for t in block["polygons"]],
                                  dtype=np.float64)
        if triangles_2d.shape[0] == 0:
            continue
        areas_2d = np.abs(0.5 * ((triangles_2d[:, 1, 0] - triangles_2d[:, 0, 0])
                                 * (triangles_2d[:, 2, 1] - triangles_2d[:, 0, 1])
                                 - (triangles_2d[:, 2, 0] - triangles_2d[:, 0, 0])
                                 * (triangles_2d[:, 1, 1] - triangles_2d[:, 0, 1])))
        usable = areas_2d > _EPS
        triangles_2d = triangles_2d[usable]
        areas_2d = areas_2d[usable]
        if areas_2d.size == 0:
            continue
        budget = int(np.clip(np.ceil(float(sample_target) * float(block["area"])
                                     / max(total_area, _EPS)), 1, CLIP_MAX_SAMPLES_PER_SOURCE))
        rng = np.random.Generator(np.random.PCG64(_stable_seed(
            {"i": int(interface_id), "s": int(block["source"]), "b": int(block_index)})))
        # area-weighted sampling of the disjoint shared triangulation (plan 30.5)
        pick = rng.choice(areas_2d.shape[0], size=budget, p=areas_2d / float(areas_2d.sum()))
        u = rng.random(budget)
        v = rng.random(budget)
        flip = u + v > 1.0
        u[flip], v[flip] = 1.0 - u[flip], 1.0 - v[flip]
        chosen = triangles_2d[pick]
        flat = (chosen[:, 0, :] + (chosen[:, 1, :] - chosen[:, 0, :]) * u[:, None]
                + (chosen[:, 2, :] - chosen[:, 0, :]) * v[:, None])
        row_area = np.full(flat.shape[0], float(block["area"]) / float(flat.shape[0]))

        side_first = _rebuild_side(triangles_a, block["faces_a"], frame, flat)
        side_second = _rebuild_side(triangles_b, block["faces_b"], frame, flat)
        if side_first is None or side_second is None:
            continue
        bary_first, face_first, rebuilt_first, flags_first, clamp_first, why_first = side_first
        bary_second, face_second, rebuilt_second, flags_second, clamp_second, why_second = \
            side_second
        bary_clamp += float(clamp_first) + float(clamp_second)
        row_ambiguous = flags_first | flags_second
        for side, flags, why in (("a", flags_first, why_first), ("b", flags_second, why_second)):
            for row in np.nonzero(flags)[0]:
                key = f"{why[row]}_on_side_{side}"
                reasons[key] = reasons.get(key, 0) + 1

        # plan 30.5: the sample goes back to 3D and is rebuilt *by barycentric* on each side
        points_3d.append(rebuilt_first)
        points_other.append(rebuilt_second)
        normals_first.append(np.asarray(mesh_a.face_normals, dtype=np.float64)[
            np.clip(face_first, 0, len(mesh_a.faces) - 1)])
        normals_second.append(np.asarray(mesh_b.face_normals, dtype=np.float64)[
            np.clip(face_second, 0, len(mesh_b.faces) - 1)])
        barys_first.append(bary_first)
        barys_second.append(bary_second)
        faces_first.append(face_first)
        faces_second.append(face_second)
        weights.append(row_area)
        ambiguous.append(row_ambiguous)
        ambiguous_area += float(np.sum(row_area[row_ambiguous]))

    if not points_3d:
        empty = np.zeros((0, 3), dtype=np.float64)
        patch = InterfacePatch(
            interface_id=int(interface_id), fragment_a=fragment_a.fragment_id,
            fragment_b=fragment_b.fragment_id, area_mm2=float(total_area),
            sample_points_a=empty, sample_points_b=empty, normals_a=empty, normals_b=empty,
            gap_p95_mm=0.0, normal_angle_p95_deg=0.0, ambiguity_area_ratio=1.0,
            ambiguous_area_mm2=float(ambiguous_area),
            meta={"empty_patch": True, "source_triangles": [int(source_tri)],
                  "common_clip_area_mm2": float(total_area),
                  "reason": "common_coverage_without_sampleable_polygon"},
        )
        return patch, []

    points_a = np.concatenate(points_3d, axis=0)
    points_b = np.concatenate(points_other, axis=0)
    bary_a = np.concatenate(barys_first, axis=0)
    bary_b = np.concatenate(barys_second, axis=0)
    face_a = np.concatenate(faces_first, axis=0)
    face_b = np.concatenate(faces_second, axis=0)
    normals_a = np.concatenate(normals_first, axis=0)
    normals_b = np.concatenate(normals_second, axis=0)
    weights_all = np.concatenate(weights, axis=0)
    ambiguous_all = np.concatenate(ambiguous, axis=0)
    gap = np.linalg.norm(points_a - points_b, axis=1)
    angle = _reversal_angles(normals_a, normals_b)
    sampled_area = float(np.sum(weights_all))
    area_a_side = float(total_area) + float(only_a_area)
    area_b_side = float(total_area) + float(only_b_area)
    pair = _pair_common_clip_area(fragment_a, fragment_b, cutter_mesh)

    patch = InterfacePatch(
        interface_id=int(interface_id),
        fragment_a=fragment_a.fragment_id,
        fragment_b=fragment_b.fragment_id,
        area_mm2=float(total_area),
        sample_points_a=points_a,
        sample_points_b=points_b,
        normals_a=normals_a,
        normals_b=normals_b,
        gap_p95_mm=float(np.percentile(gap, 95)) if gap.size else 0.0,
        normal_angle_p95_deg=float(np.percentile(angle, 95)) if angle.size else 0.0,
        ambiguity_area_ratio=float(ambiguous_area / max(float(total_area), _EPS)),
        ambiguous_area_mm2=float(ambiguous_area),
        meta={
            "source_triangles": sorted({int(b["source"]) for b in blocks}),
            "faces_a": [int(x) for x in ids_a],
            "faces_b": [int(x) for x in ids_b],
            "area_a_mm2": area_a_side,
            "area_b_mm2": area_b_side,
            "area_rel_error": float(abs(area_a_side - area_b_side)
                                    / max(area_a_side, area_b_side, _EPS)),
            "common_clip_area_mm2": float(total_area),
            "pair_common_clip_area_mm2": float(pair["common_area_mm2"]),
            "pair_common_clip_sources": int(pair["shared_sources"]),
            "pair_clip_method": str(pair.get("method", "")),
            "pair_clip_one_sided_sources": int(pair.get("one_sided_sources", 0)),
            "pair_clip_a_only_area_mm2": float(pair.get("a_only_area_mm2", 0.0)),
            "pair_clip_b_only_area_mm2": float(pair.get("b_only_area_mm2", 0.0)),
            "pair_clip_plane_deviation_mm": pair.get("plane_deviation_mm"),
            "only_a_area_mm2": float(only_a_area),
            "only_b_area_mm2": float(only_b_area),
            "one_sided_source_triangles": one_sided_sources,
            "source_triangle_areas_mm2": source_areas,
            "snapped_area_mm2": float(snapped_area),
            "barycentric_clamp_total": float(bary_clamp),
            "clip_on_surface_tolerance_mm": CLIP_ON_SURFACE_TOL_MM,
            "clip_snap_tolerance_mm": CLIP_SNAP_TOL_MM,
            "samples": int(points_a.shape[0]),
            "sampled_area_mm2": sampled_area,
            "ambiguous_samples": int(np.sum(ambiguous_all)),
            "ambiguous_reasons": reasons,
            "weights_mm2": weights_all,
            "bary_a": bary_a,
            "bary_b": bary_b,
            "gap_max_mm": float(gap.max()) if gap.size else 0.0,
            "gap_p95_mm": float(np.percentile(gap, 95)) if gap.size else 0.0,
            "normal_angle_p95_deg": float(np.percentile(angle, 95)) if angle.size else 0.0,
            "normal_angle_max_deg": float(angle.max()) if angle.size else 0.0,
            "ambiguous_mask": ambiguous_all,
            "bary_min_a": float(np.min(bary_a)) if bary_a.size else 0.0,
            "bary_min_b": float(np.min(bary_b)) if bary_b.size else 0.0,
        },
    )
    rows = [
        (points_a[row], points_b[row], int(face_a[row]), bary_a[row],
         int(face_b[row]), bary_b[row], bool(ambiguous_all[row]))
        for row in range(points_a.shape[0])
    ]
    return patch, rows


def _rebuild_side(triangles: np.ndarray, faces: Sequence[int],
                  frame: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
                  points_2d: np.ndarray,
                  ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float] | None:
    """Rebuild clipped 2D points on one side by barycentric reconstruction (plan 30.5).

    Returns ``(barycentric, face ids, rebuilt 3D points, ambiguous flags, clamped amount)``.  A
    point counts as ambiguous when no output triangle of this side contains it or when two
    geometrically distinct triangles do; a point that merely touches the shared edge of two
    neighbouring triangles of the *same* triangulation is resolved deterministically, exactly
    like the coincident duplicate faces the boolean output carries on a cut sheet.
    """
    ids = np.asarray(list(faces), dtype=np.int64).reshape(-1)
    if ids.size == 0 or points_2d.shape[0] == 0:
        return None
    block = triangles[ids]
    two_d = _project(block, frame)
    bary = np.zeros((points_2d.shape[0], 3), dtype=np.float64)
    owner = np.full(points_2d.shape[0], -1, dtype=np.int64)
    flagged = np.zeros(points_2d.shape[0], dtype=bool)
    reasons = np.zeros(points_2d.shape[0], dtype=object)
    reasons[:] = ""
    rebuilt = np.zeros((points_2d.shape[0], 3), dtype=np.float64)
    clamped = 0.0
    for row in range(points_2d.shape[0]):
        chosen, owners, why = _locate_point(points_2d[row], two_d, block)
        if chosen < 0:
            flagged[row] = True
            reasons[row] = why
            continue
        if owners != 1:
            flagged[row] = True
            reasons[row] = why
        local = _barycentric_on_triangle(
            _plane_point(points_2d[row], frame).reshape(1, 3), block[chosen])[0]
        clamped += float(np.sum(np.abs(np.minimum(local, 0.0))))
        local = np.clip(local, 0.0, None)
        total = float(np.sum(local))
        if total <= _EPS:
            flagged[row] = True
            reasons[row] = "degenerate_reconstruction"
            continue
        local = local / total
        bary[row] = local
        owner[row] = int(ids[chosen])
        rebuilt[row] = local @ block[chosen]
    return bary, owner, rebuilt, flagged, clamped, reasons


def _plane_point(point_2d: np.ndarray,
                 frame: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    """Back to 3D inside the source triangle's own plane."""
    origin, e1, e2, _normal = frame
    return origin + float(point_2d[0]) * e1 + float(point_2d[1]) * e2


def _shared_plane(triangles_a: np.ndarray, triangles_b: np.ndarray,
                  tolerance_mm: float) -> tuple[tuple[np.ndarray, np.ndarray, np.ndarray,
                                                      np.ndarray], float] | None:
    """One orthonormal 2D basis for two near-coplanar triangle sets (``None`` when not planar).

    A plane cut leaves both fragments' cut faces exactly coplanar, and then the pair's common
    clipped coverage is a single 2D union/intersection instead of hundreds of per-triangle ones.
    """
    points = np.concatenate([np.asarray(triangles_a, dtype=np.float64).reshape(-1, 3),
                             np.asarray(triangles_b, dtype=np.float64).reshape(-1, 3)], axis=0)
    if points.shape[0] < 3:
        return None
    origin = points.mean(axis=0)
    centred = points - origin
    _u, singular, vt = np.linalg.svd(centred, full_matrices=False)
    if singular.size < 3:
        return None
    deviation = float(np.max(np.abs(centred @ vt[2])))
    if deviation > float(tolerance_mm):
        return None
    e1, e2 = vt[0], vt[1]
    normal = np.cross(e1, e2)
    norm = float(np.linalg.norm(normal))
    if norm <= _EPS:
        return None
    return (origin, e1, e2, normal / norm), deviation


def _pair_common_clip_area(fragment_a: Fragment, fragment_b: Fragment,
                           cutter_mesh: trimesh.Trimesh) -> dict[str, Any]:
    """Common clipped coverage of the **whole fragment pair** (plan 30.5).

    One fragment pair shares one new fracture surface, while the event records it as several
    sampling chunks; the R2 area verdict therefore needs the pair-level measurement:

    ``area( shared cutter surface ∩ material(A) ∩ material(B) )``.

    A coplanar pair (every plane backend) is measured with one 2D union/intersection of both
    full cut sheets.  Otherwise every source cutter triangle is clipped in its own local basis,
    so cavity adjacency, one-sided coverage and different components never become a fake
    interface.  Cached per fragment pair and cutter, because it does not depend on the chunking.
    """
    key = ("pair_clip", str(fragment_b.fragment_id), _cutter_key(cutter_mesh))
    cache = _clip_cache(fragment_a)
    hit = cache.get(key)
    if hit is not None:
        return hit
    faces_a, source_a, centres_a, radius_a = _cut_face_table(fragment_a, cutter_mesh)
    faces_b, source_b, centres_b, radius_b = _cut_face_table(fragment_b, cutter_mesh)
    triangles_a = np.asarray(fragment_a.mesh.triangles, dtype=np.float64)
    triangles_b = np.asarray(fragment_b.mesh.triangles, dtype=np.float64)
    result: dict[str, Any] = {
        "common_area_mm2": 0.0, "shared_sources": 0, "one_sided_sources": 0,
        "a_only_area_mm2": 0.0, "b_only_area_mm2": 0.0, "snapped_area_mm2": 0.0,
        "faces_a": int(faces_a.shape[0]), "faces_b": int(faces_b.shape[0]),
        "method": "none", "plane_deviation_mm": None,
    }
    if faces_a.size == 0 or faces_b.size == 0:
        cache[key] = result
        return result
    import shapely

    block_a = triangles_a[faces_a]
    block_b = triangles_b[faces_b]
    plane = _shared_plane(block_a, block_b, PAIR_PLANE_TOL_MM)
    if plane is not None:
        frame, deviation = plane
        union_a = _union_2d(_project(block_a, frame))
        union_b = _union_2d(_project(block_b, frame))
        if union_a is not None and union_b is not None:
            common = shapely.intersection(union_a, union_b)
            only_a = shapely.difference(union_a, union_b)
            only_b = shapely.difference(union_b, union_a)
            common, corrected = _snap_2d(common)
            result.update({
                "common_area_mm2": float(shapely.area(common)),
                "shared_sources": int(len({int(s) for s in source_a} & {int(s) for s in source_b})),
                "a_only_area_mm2": float(shapely.area(only_a)),
                "b_only_area_mm2": float(shapely.area(only_b)),
                "snapped_area_mm2": float(corrected),
                "method": "shared_plane",
                "plane_deviation_mm": float(deviation),
            })
            cache[key] = result
            return result

    from scipy.spatial import cKDTree

    tree_a = cKDTree(centres_a)
    tree_b = cKDTree(centres_b)
    # every source triangle either side touches: a triangle that only *one* side's faces are
    # nearest to must still be measured, otherwise its coverage is silently dropped
    sources = sorted({int(s) for s in source_a} | {int(s) for s in source_b})
    common_total = 0.0
    only_a_total = 0.0
    only_b_total = 0.0
    snapped_total = 0.0
    one_sided = 0
    for source in sources:
        frame = _cutter_frame(cutter_mesh, source)
        if frame is None:
            continue
        triangle = np.asarray(cutter_mesh.triangles[int(source)], dtype=np.float64)
        centre = triangle.mean(axis=0)
        span = float(np.max(np.linalg.norm(triangle - centre, axis=1)))
        region = shapely.polygons(_project(triangle[None, :, :], frame)[0])
        near_a = tree_a.query_ball_point(centre, span + radius_a)
        near_b = tree_b.query_ball_point(centre, span + radius_b)
        union_a = _union_2d(_project(
            triangles_a[np.asarray(sorted(near_a), dtype=np.int64)], frame)) if near_a else None
        union_b = _union_2d(_project(
            triangles_b[np.asarray(sorted(near_b), dtype=np.int64)], frame)) if near_b else None
        cover_a = None if union_a is None else shapely.intersection(union_a, region)
        cover_b = None if union_b is None else shapely.intersection(union_b, region)
        if cover_a is None or cover_b is None or cover_a.is_empty or cover_b.is_empty:
            one_sided += 1
            continue
        only_a_total += float(shapely.area(shapely.difference(cover_a, cover_b)))
        only_b_total += float(shapely.area(shapely.difference(cover_b, cover_a)))
        piece = shapely.intersection(cover_a, cover_b)
        if piece.is_empty:
            continue
        piece, corrected = _snap_2d(piece)
        snapped_total += float(corrected)
        area = float(shapely.area(piece))
        if area <= _EPS:
            continue
        common_total += area
    result.update({
        "common_area_mm2": float(common_total),
        "shared_sources": int(len({int(s) for s in source_a} & {int(s) for s in source_b})),
        "one_sided_sources": int(one_sided),
        "a_only_area_mm2": float(only_a_total),
        "b_only_area_mm2": float(only_b_total),
        "snapped_area_mm2": float(snapped_total),
        "method": "per_source_triangle",
    })
    cache[key] = result
    return result


def _barycentric_on_triangle(points: np.ndarray, tri: np.ndarray) -> np.ndarray:
    a, b, c = tri[0], tri[1], tri[2]
    v0, v1, v2 = b - a, c - a, points - a
    d00 = float(v0 @ v0)
    d01 = float(v0 @ v1)
    d11 = float(v1 @ v1)
    d20 = v2 @ v0
    d21 = v2 @ v1
    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-300:  # pragma: no cover - degenerate source triangle
        return np.tile(np.array([1.0, 0.0, 0.0]), (points.shape[0], 1))
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    u = 1.0 - v - w
    return np.stack([u, v, w], axis=1)


def _reversal_angles(normals_a: np.ndarray, normals_b: np.ndarray) -> np.ndarray:
    """``angle(n_A, -n_B)`` in degrees, with a numerically safe arccos."""
    dot = np.clip(np.einsum("ni,ni->n", normals_a, -normals_b), -1.0, 1.0)
    return np.degrees(np.arccos(dot))


# ---------------------------------------------------------------------------- audit


def overlap_ratio(mesh_a: trimesh.Trimesh, mesh_b: trimesh.Trimesh, *,
                  samples: int = 512, seed: int = 0) -> float:
    """Fraction of sampled interior points of ``A`` that also lie inside ``B``."""
    if mesh_a.faces.shape[0] == 0 or mesh_b.faces.shape[0] == 0:
        return 0.0
    rng = np.random.Generator(np.random.PCG64(int(seed)))
    faces = np.asarray(mesh_a.faces, dtype=np.int64)
    areas = np.asarray(mesh_a.area_faces, dtype=np.float64)
    pick = rng.choice(faces.shape[0], size=int(samples), p=areas / max(areas.sum(), _EPS))
    tri = np.asarray(mesh_a.triangles, dtype=np.float64)[pick]
    u = rng.random(samples)
    v = rng.random(samples)
    flip = u + v > 1.0
    u[flip], v[flip] = 1.0 - u[flip], 1.0 - v[flip]
    points = (tri[:, 0] + (tri[:, 1] - tri[:, 0]) * u[:, None]
              + (tri[:, 2] - tri[:, 0]) * v[:, None])
    normals = np.asarray(mesh_a.face_normals, dtype=np.float64)[pick]
    inward = points - normals * 1.0e-3
    if not bool(mesh_b.is_watertight):
        return 0.0
    inside = mesh_b.contains(inward)
    return float(np.mean(inside))


def interface_distance_stats(fragment_a: Fragment, fragment_b: Fragment,
                             patch: InterfacePatch) -> dict[str, float]:
    """Direct vertex-identity evidence plus a sampled nearest-surface distance."""
    mesh_a, mesh_b = fragment_a.mesh, fragment_b.mesh
    face_a = np.asarray(patch.meta.get("faces_a", []), dtype=np.int64)
    face_b = np.asarray(patch.meta.get("faces_b", []), dtype=np.int64)
    if face_a.size == 0 or face_b.size == 0:
        return {"vertex_identity_ratio": 0.0, "nearest_p95_mm": float("inf"),
                "nearest_max_mm": float("inf")}
    verts_a = np.unique(np.asarray(mesh_a.faces, dtype=np.int64)[face_a].reshape(-1))
    verts_b = np.unique(np.asarray(mesh_b.faces, dtype=np.int64)[face_b].reshape(-1))
    points_a = np.asarray(mesh_a.vertices, dtype=np.float64)[verts_a]
    points_b = np.asarray(mesh_b.vertices, dtype=np.float64)[verts_b]
    quant = np.round(points_a / _MATCH_QUANT).astype(np.int64)
    set_b = {tuple(int(x) for x in row) for row in np.round(points_b / _MATCH_QUANT).astype(np.int64)}
    identity = float(np.mean([tuple(int(x) for x in row) in set_b for row in quant]))
    nearest = mesh_b.nearest.on_surface(points_a)[1]
    return {
        "vertex_identity_ratio": identity,
        "vertices_a": int(points_a.shape[0]),
        "vertices_b": int(points_b.shape[0]),
        "nearest_p95_mm": float(np.percentile(nearest, 95)),
        "nearest_max_mm": float(np.max(nearest)),
    }


def audit_fracture_result(result: Any, mother: Any) -> dict[str, Any]:
    """Quantified conservation / overlap / interface / source audit (plan 10.1 step 7)."""
    mother_volume = float(np.sum([f.volume_mm3 for f in result.fragments]))
    reference = float(abs(mother.mesh.volume))
    volume_rel = abs(mother_volume - reference) / max(reference, _EPS)
    overlap = 0.0
    if len(result.fragments) >= 2:
        minus = [f for f in result.fragments if f.face_side.size and int(f.face_side[0]) < 0]
        plus = [f for f in result.fragments if f.face_side.size and int(f.face_side[0]) > 0]
        worst = 0.0
        for frag_a in minus[:4]:
            for frag_b in plus[:4]:
                # a *stable* seed: ``hash(str)`` is randomised per process (PYTHONHASHSEED), which
                # made this audit flip between pass and fail on identical geometry
                worst = max(worst, overlap_ratio(frag_a.mesh, frag_b.mesh,
                                                 seed=_stable_seed(
                                                     {"overlap": frag_a.fragment_id,
                                                      "with": frag_b.fragment_id}) % 1000))
        overlap = worst
    gaps, angles, ambiguities, area_rel = [], [], [], []
    for patch in result.interfaces:
        if patch.sample_points_a.shape[0] == 0:
            continue
        gaps.append(patch.gap_p95_mm)
        angles.append(patch.normal_angle_p95_deg)
        ambiguities.append(patch.ambiguity_area_ratio)
        area_rel.append(float(patch.meta.get("area_rel_error", 0.0)))
    # source mapping coverage: every face must carry an origin kind and, for mother-surface
    # faces, a valid mother triangle id
    total_faces = 0
    mapped = 0
    ambiguous_area = 0.0
    total_area = 0.0
    for fragment in result.fragments:
        origin = np.asarray(fragment.face_origin_kind)
        source = np.asarray(fragment.face_source_tri)
        areas = np.asarray(fragment.mesh.area_faces, dtype=np.float64)
        total_faces += origin.shape[0]
        mapped += int(np.sum((origin == ORIGIN_MOTHER_SURFACE) & (source >= 0)))
        mapped += int(np.sum(origin == ORIGIN_INTERFACE))
        ambiguous_area += float(np.sum(areas[origin == ORIGIN_AMBIGUOUS]))
        total_area += float(np.sum(areas))
    interface_faces = sum(int(np.sum(np.asarray(f.face_origin_kind) == ORIGIN_INTERFACE))
                          for f in result.fragments)
    coverage = float(mapped / max(total_faces, 1))
    ambiguous_ratio = float(ambiguous_area / max(total_area, _EPS))
    qa = {
        "mother_volume_mm3": reference,
        "fragment_volume_sum_mm3": mother_volume,
        "volume_rel_diff": float(volume_rel),
        "volume_tolerance": VOLUME_REL_TOL,
        "overlap_ratio": float(overlap),
        "overlap_tolerance": OVERLAP_RATIO_MAX,
        "interface_count": len(result.interfaces),
        "interface_faces": int(interface_faces),
        "gap_p95_mm_max": float(max(gaps)) if gaps else 0.0,
        "gap_tolerance_mm": INTERFACE_GAP_P95_MM,
        "normal_angle_p95_deg_max": float(max(angles)) if angles else 0.0,
        "normal_angle_tolerance_deg": NORMAL_REVERSAL_P95_DEG,
        "source_coverage": coverage,
        "ambiguous_area_ratio_max": float(max(ambiguities)) if ambiguities else 0.0,
        "ambiguous_area_ratio_total": ambiguous_ratio,
        "ambiguity_tolerance": AMBIGUITY_AREA_RATIO_MAX,
        "interface_area_rel_error_max": float(max(area_rel)) if area_rel else 0.0,
        "faces_total": int(total_faces),
        "tiny_fragments": int(sum(1 for f in result.fragments if f.is_tiny)),
        "fragment_count": len(result.fragments),
    }
    failures: list[str] = []
    if volume_rel > VOLUME_REL_TOL:
        failures.append(
            f"volume_rel_diff {volume_rel:.6g} > {VOLUME_REL_TOL}")
    if overlap > OVERLAP_RATIO_MAX:
        failures.append(f"overlap_ratio {overlap:.6g} > {OVERLAP_RATIO_MAX}")
    if qa["gap_p95_mm_max"] > INTERFACE_GAP_P95_MM:
        failures.append(
            f"interface gap p95 {qa['gap_p95_mm_max']:.6g} mm > {INTERFACE_GAP_P95_MM} mm")
    if qa["normal_angle_p95_deg_max"] > NORMAL_REVERSAL_P95_DEG:
        failures.append(
            f"normal reversal p95 {qa['normal_angle_p95_deg_max']:.6g} deg > "
            f"{NORMAL_REVERSAL_P95_DEG} deg")
    if coverage < 0.999:
        failures.append(f"source coverage {coverage:.6g} < 0.999")
    if ambiguous_ratio > AMBIGUITY_AREA_RATIO_MAX:
        failures.append(
            f"ambiguous area ratio {ambiguous_ratio:.6g} > {AMBIGUITY_AREA_RATIO_MAX}")
    if result.meta.get("cutter_hash_conflict"):
        failures.append("the two sides did not consume the same cutter hash")
    qa["failures"] = failures
    qa["passed"] = not failures
    # ``synlab/pipeline.py`` branches on ``audit.get("ok", ...)`` while this auditor has always
    # reported ``passed``; both keys are published with the same value so no caller has to guess.
    qa["ok"] = not failures
    # measured plan 30.5 coverage: the pair-level common clipped area per fragment pair, next to
    # the chunk sums the event actually sampled (reported, never substituted for the measurement)
    pair_areas: dict[tuple[str, str], float] = {}
    methods: set[str] = set()
    chunk_sum = 0.0
    for patch in result.interfaces:
        chunk_sum += float(patch.meta.get("common_clip_area_mm2", patch.area_mm2))
        value = patch.meta.get("pair_common_clip_area_mm2")
        if value is not None:
            key = tuple(sorted((str(patch.fragment_a), str(patch.fragment_b))))
            pair_areas[key] = float(value)
        if patch.meta.get("pair_clip_method"):
            methods.add(str(patch.meta["pair_clip_method"]))
    qa["interface_common_clip_area_mm2"] = float(chunk_sum)
    qa["interface_pair_common_clip_area_mm2"] = float(sum(pair_areas.values()))
    qa["interface_pair_clip_method"] = ",".join(sorted(methods))
    if failures:
        raise SynLabError(
            ErrorCode.FRACTURE_CONSERVATION_FAIL,
            "fracture audit failed: " + "; ".join(failures),
            stage="fracture.audit",
            measurements=qa,
        )
    return qa
