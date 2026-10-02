"""Manifold-backed CSG with explicit per-triangle source bookkeeping (plan 10.2, 30.5).

Every input triangle carries a *source key* ``(mesh_id, triangle_id)`` plus its vertex
position in Manifold's interpolated vertex properties, so an output triangle of ``M ∩ C`` or
``M \\ C`` can be traced back to the exact mother or cutter triangle it came from, and a
clipped vertex can be reconstructed barycentrically on that source triangle.  Nothing here
re-samples a surface: both sides of one event consume the *same* discrete cutter bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import trimesh
from manifold3d import Manifold, Mesh

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import ORIGIN_AMBIGUOUS, ORIGIN_INTERFACE, ORIGIN_MOTHER_SURFACE

__all__ = [
    "SourceMesh",
    "SourceTaggedResult",
    "SourceResolver",
    "tag_source",
    "boolean_intersection",
    "boolean_difference",
    "boolean_union",
    "components",
    "faces_inside",
    "mesh_hash",
    "ORIGIN_MOTHER_SURFACE",
    "ORIGIN_INTERFACE",
    "ORIGIN_AMBIGUOUS",
]

_PROP_COLUMNS = 7  # xyz + mesh_id + tri_id + bary_b + bary_c
#: barycentric slack for "the point's projection lies inside this triangle"
_BARY_TOL = 1.0e-6
#: a face only counts as a *cut* face when its normal agrees with the cutter surface it lies on
#: (|dot| >= cos(60 deg)); below that the surface merely grazes the cutter (plan 10.1 step 1)
GRAZING_NORMAL_DOT = 0.5


@dataclass
class SourceMesh:
    """A tagged input mesh: per-triangle source ids are frozen before any boolean."""

    mesh: trimesh.Trimesh
    mesh_id: float
    label: str
    triangle_ids: np.ndarray  # (F,) int64 in input order

    @property
    def n_triangles(self) -> int:
        return int(np.asarray(self.mesh.faces).shape[0])


@dataclass
class SourceTaggedResult:
    """One boolean output plus per-vertex source reconstruction channels."""

    mesh: trimesh.Trimesh
    point: np.ndarray        # (V,3) reconstructed source-surface position
    mesh_id: np.ndarray      # (V,) provenance mesh id
    source_tri: np.ndarray   # (V,) source triangle id in that mesh
    bary: np.ndarray         # (V,2) barycentric (lambda_b, lambda_c); lambda_a = 1 - sum

    @property
    def n_faces(self) -> int:
        return int(np.asarray(self.mesh.faces).shape[0])

    def face_source_tri(self) -> np.ndarray:
        faces = np.asarray(self.mesh.faces)
        return self.source_tri[faces[:, 0]]

    def face_mesh_id(self) -> np.ndarray:
        faces = np.asarray(self.mesh.faces)
        return self.mesh_id[faces[:, 0]]

    def face_points(self) -> np.ndarray:
        faces = np.asarray(self.mesh.faces)
        return self.point[faces]

    def reconstruction_residual(self) -> np.ndarray:
        """Per-vertex ``|reconstructed - output|`` in mm (should be ~float32 noise)."""
        return np.linalg.norm(self.point - np.asarray(self.mesh.vertices, dtype=np.float64), axis=1)


def tag_source(mesh: trimesh.Trimesh, mesh_id: float, label: str,
               triangle_ids: np.ndarray | None = None) -> SourceMesh:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    ids = (np.arange(faces.shape[0], dtype=np.int64) if triangle_ids is None
           else np.asarray(triangle_ids, dtype=np.int64))
    if ids.shape[0] != faces.shape[0]:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "triangle_ids length must match the face count",
                          stage="fracture.booleans.tag_source")
    return SourceMesh(mesh=mesh, mesh_id=float(mesh_id), label=label, triangle_ids=ids)


def _vertex_properties(source: SourceMesh) -> np.ndarray:
    faces = np.asarray(source.mesh.faces, dtype=np.int64)
    verts = np.asarray(source.mesh.vertices, dtype=np.float64)
    props = np.zeros((verts.shape[0], _PROP_COLUMNS), dtype=np.float32)
    props[:, 0:3] = verts
    props[:, 3] = source.mesh_id
    props[:, 4] = -1.0
    slot_bary = ((1.0, 0.0), (0.0, 1.0), (0.0, 0.0))
    for tri_index, tri in enumerate(faces):
        for slot, vertex in enumerate(tri):
            props[vertex, 4] = float(source.triangle_ids[tri_index])
            props[vertex, 5] = slot_bary[slot][0]
            props[vertex, 6] = slot_bary[slot][1]
    if np.any(props[:, 4] < 0.0):
        missing = int(np.sum(props[:, 4] < 0.0))
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          f"{missing} vertices of {source.label} belong to no triangle",
                          stage="fracture.booleans.tag_source")
    return props


def _to_manifold(source: SourceMesh) -> Manifold:
    return Manifold(Mesh(
        vert_properties=_vertex_properties(source),
        tri_verts=np.asarray(source.mesh.faces, dtype=np.uint32),
    ))


#: Manifold keeps *property-distinct* copies of one position (its boolean only welds vertices
#: whose property block agrees), so a cut that passes through existing vertices comes back with
#: coincident vertices and edges used once.  Output vertices closer than this are the same point
#: (the property channel travels at float32 resolution, which is ~1.5e-5 mm at 200 mm, far below
#: every frozen budget).
_WELD_QUANT_MM = 1.0e-9


def _weld_coincident(vertices: np.ndarray, faces: np.ndarray,
                     channels: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray,
                                                               dict[str, np.ndarray], int]:
    """Merge exactly coincident output vertices, keeping every channel aligned.

    The boolean output is *geometrically* closed but its vertex indices are split where Manifold
    could not weld property-distinct copies; without this merge ``M ∩ C`` / ``M \\ C`` fail the
    ``is_watertight`` gate even though both inputs are clean manifolds (measured: 1248 edges used
    once, 624 duplicate positions on the demo V01 plane cut).  The first occurrence of a position
    wins, deterministically, and the number of merged vertices is returned for the QA record.
    """
    verts = np.asarray(vertices, dtype=np.float64)
    if verts.shape[0] == 0 or faces.size == 0:
        return verts, faces, channels, 0
    keys = np.round(verts / _WELD_QUANT_MM).astype(np.int64)
    unique_keys, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    del unique_keys
    if first.shape[0] == verts.shape[0]:
        return verts, faces, channels, 0
    new_faces = np.asarray(inverse, dtype=np.int64)[np.asarray(faces, dtype=np.int64)]
    welded = {name: np.asarray(value)[first] for name, value in channels.items()}
    return verts[first], new_faces, welded, int(verts.shape[0] - first.shape[0])


def _from_manifold(result: Manifold, *, label: str) -> SourceTaggedResult:
    data = result.to_mesh()
    props = np.asarray(data.vert_properties, dtype=np.float64)
    faces = np.asarray(data.tri_verts, dtype=np.int64)
    if props.ndim != 2 or props.shape[1] < _PROP_COLUMNS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{label}: manifold dropped the source properties "
                          f"(got {props.shape})",
                          stage="fracture.booleans.source")
    channels = {
        "point": props[:, 0:3].copy(),
        "mesh_id": np.round(props[:, 3], 6),
        "source_tri": np.round(props[:, 4]).astype(np.int64),
        "bary": props[:, 5:7].copy(),
    }
    vertices, faces, channels, merged = _weld_coincident(props[:, 0:3], faces, channels)
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices, dtype=np.float64).copy(),
                           faces=np.asarray(faces, dtype=np.int64), process=False)
    mesh.metadata = dict(mesh.metadata or {})
    mesh.metadata["welded_coincident_vertices"] = int(merged)
    return SourceTaggedResult(
        mesh=mesh,
        point=channels["point"],
        mesh_id=channels["mesh_id"],
        source_tri=channels["source_tri"],
        bary=channels["bary"],
    )


def _run(op: str, sources: Iterable[SourceMesh], *, label: str) -> SourceTaggedResult:
    items = [item for item in sources]
    if not items:
        raise SynLabError(ErrorCode.MOTHER_INVALID, f"{label}: no input mesh",
                          stage="fracture.booleans")
    manifolds = [_to_manifold(item) for item in items]
    result = manifolds[0]
    for other in manifolds[1:]:
        if op == "intersection":
            result = result ^ other
        elif op == "difference":
            result = result - other
        elif op == "union":
            result = result + other
        else:  # pragma: no cover - internal guard
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown boolean op {op}",
                              stage="fracture.booleans")
    return _from_manifold(result, label=label)


def boolean_intersection(sources: list[SourceMesh], *, label: str = "intersection",
                         ) -> SourceTaggedResult:
    return _run("intersection", sources, label=label)


def boolean_difference(sources: list[SourceMesh], *, label: str = "difference",
                       ) -> SourceTaggedResult:
    return _run("difference", sources, label=label)


def boolean_union(sources: list[SourceMesh], *, label: str = "union") -> SourceTaggedResult:
    return _run("union", sources, label=label)


def mesh_hash(mesh: trimesh.Trimesh) -> str:
    """Geometry-only content hash (vertices + faces), independent of face attributes."""
    return hash_json({
        "v": np.round(np.asarray(mesh.vertices, dtype=np.float64), 9).tolist(),
        "f": np.asarray(mesh.faces, dtype=np.int64).tolist(),
    })


# ---------------------------------------------------------------------------- source mapping


class _TriangleLocator:
    """Nearest-triangle lookup on one source mesh (proximity BVH + local exact refine)."""

    #: how many extra nearest triangles are tested when checking point/edge ambiguity
    AMBIGUITY_NEIGHBOURS = 12

    def __init__(self, mesh: trimesh.Trimesh):
        self.mesh = mesh
        self.triangles = np.asarray(mesh.triangles, dtype=np.float64)
        self.normals = np.asarray(mesh.face_normals, dtype=np.float64)
        self._tree = None
        self._centroids = None

    def _kdtree(self):
        if self._tree is None:
            from scipy.spatial import cKDTree

            self._centroids = np.asarray(self.mesh.triangles_center, dtype=np.float64)
            self._tree = cKDTree(self._centroids)
        return self._tree

    @staticmethod
    def _point_triangle(points: np.ndarray, tri: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Broadcast point-to-triangle distance and barycentric weights (Ericson).

        ``points`` is ``(N,3)`` and ``tri`` is ``(N,K,3)``: result is ``(N,K)``.
        """
        a, b, c = tri[:, :, 0], tri[:, :, 1], tri[:, :, 2]
        pts = points[:, None, :]
        ab = b - a
        ac = c - a
        ap = pts - a
        d1 = np.einsum("nki,nki->nk", ab, ap)
        d2 = np.einsum("nki,nki->nk", ac, ap)
        bp = pts - b
        d3 = np.einsum("nki,nki->nk", ab, bp)
        d4 = np.einsum("nki,nki->nk", ac, bp)
        cp = pts - c
        d5 = np.einsum("nki,nki->nk", ab, cp)
        d6 = np.einsum("nki,nki->nk", ac, cp)
        va = d3 * d6 - d5 * d4
        vb = d5 * d2 - d1 * d6
        vc = d1 * d4 - d3 * d2
        denom = va + vb + vc
        denom = np.where(np.abs(denom) < 1e-300, 1e-300, denom)
        v = vb / denom
        w = vc / denom
        u = 1.0 - v - w
        closest = u[:, :, None] * a + v[:, :, None] * b + w[:, :, None] * c
        distance = np.linalg.norm(pts - closest, axis=2)
        return distance, np.stack([u, v, w], axis=2)

    def locate(self, points: np.ndarray, *, tolerance_mm: float,
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return ``(primary_tri, ambiguity, distance, barycentric)`` per point.

        The closest triangle is searched in a centroid-KNN fan and then refined exactly.  A point
        is AMBIGUOUS when a *different surface patch* of the same source mesh is equally close:
        candidates that share a vertex with the closest triangle are skipped, because choosing
        between the triangles around one vertex or edge is not a provenance ambiguity — it is the
        normal case for every vertex the boolean inherited from the mother (measured: without
        this rule 95.8% of the demo V01 plane-cut area is flagged ambiguous, which is an artefact,
        while a genuine doubled/tangential surface stays ambiguous).
        """
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        if pts.shape[0] == 0:
            empty = np.zeros(0, dtype=np.int64)
            return empty, np.zeros(0, dtype=bool), np.zeros(0), np.zeros((0, 3))
        tree = self._kdtree()
        k = int(min(self.AMBIGUITY_NEIGHBOURS + 1, self.triangles.shape[0]))
        _, candidates = tree.query(pts, k=k)
        candidates = np.atleast_2d(np.asarray(candidates, dtype=np.int64))
        tri = self.triangles[candidates]                      # (N,K,3,3)
        distance, bary = self._point_triangle(pts, tri)       # (N,K)
        # A triangle owns a point only when the point's projection falls *inside* it; distance
        # alone is not enough because the boolean property channel travels at float32 resolution
        # (measured ~5e-7 mm), which lets a non-containing neighbour win the distance ranking and
        # then look like a competing source.
        contains = np.all(bary >= -_BARY_TOL, axis=2) & np.all(bary <= 1.0 + _BARY_TOL, axis=2)
        order_all = np.argsort(distance, axis=1, kind="stable")
        order_inside = np.argsort(np.where(contains, distance, np.inf), axis=1, kind="stable")
        rows = np.arange(pts.shape[0])
        has_inside = np.any(contains, axis=1)
        best = np.where(has_inside, order_inside[:, 0], order_all[:, 0])
        primary = candidates[rows, best]
        best_distance = distance[rows, best]
        best_bary = bary[rows, best]
        ambiguity = np.zeros(pts.shape[0], dtype=bool)
        if order_all.shape[1] > 1:
            faces = np.asarray(self.mesh.faces, dtype=np.int64)
            candidate_faces = faces[candidates]               # (N,K,3)
            best_faces = candidate_faces[rows, best]          # (N,3)
            decided = np.zeros(pts.shape[0], dtype=bool)
            # only candidates that contain the projection can compete, and only when they are not
            # part of the same surface patch (sharing a vertex with the closest triangle)
            for rank in range(1, order_inside.shape[1]):
                column = order_inside[:, rank]
                eligible = contains[rows, column]
                if not bool(np.any(eligible & ~decided)):
                    continue
                other = candidate_faces[rows, column]         # (N,3)
                shares_vertex = (other[:, :, None] == best_faces[:, None, :]).any(axis=(1, 2))
                take = eligible & (~decided) & (~shares_vertex)
                if not bool(np.any(take)):
                    continue
                gap = distance[rows, column] - best_distance
                ambiguity |= take & (gap <= tolerance_mm)
                decided |= take
        return (primary.astype(np.int64), ambiguity, best_distance, best_bary)


class SourceResolver:
    """Classify output triangles into ``mother_surface`` / ``interface`` / ``ambiguous``."""

    def __init__(self, sources: list[SourceMesh], *, tolerance_mm: float = 1e-3):
        self.sources = {source.mesh_id: source for source in sources}
        self.locators = {source.mesh_id: _TriangleLocator(source.mesh) for source in sources}
        self.tolerance_mm = float(tolerance_mm)

    def classify(self, result: SourceTaggedResult, *, container: trimesh.Trimesh | None = None,
                 container_tolerance_mm: float = 1e-4) -> dict[str, Any]:
        """Return per-vertex origin kind, source triangle, ambiguity and diagnostics."""
        points = result.point
        mesh_ids = result.mesh_id
        count = points.shape[0]
        origin = np.full(count, ORIGIN_MOTHER_SURFACE, dtype=np.uint8)
        source_tri = np.full(count, -1, dtype=np.int64)
        ambiguous = np.zeros(count, dtype=bool)
        locator_distance = np.full(count, np.inf, dtype=np.float64)
        face_normal = np.zeros((count, 3), dtype=np.float64)
        for mesh_id, locator in self.locators.items():
            selected = np.nonzero(np.abs(mesh_ids - mesh_id) < 0.5)[0]
            if selected.size == 0:
                continue
            primary, amb, distance, _ = locator.locate(points[selected],
                                                       tolerance_mm=self.tolerance_mm)
            source_tri[selected] = self.sources[mesh_id].triangle_ids[primary]
            ambiguous[selected] = amb
            locator_distance[selected] = distance
            face_normal[selected] = locator.normals[primary]
        inside = np.zeros(count, dtype=bool)
        on_boundary = np.zeros(count, dtype=bool)
        container_distance = np.full(count, np.inf, dtype=np.float64)
        if container is not None:
            vertex_inside = faces_inside(points, container)
            _closest, nearest, triangle_id = container.nearest.on_surface(points)
            nearest = np.asarray(nearest, dtype=np.float64)
            container_distance = nearest
            touching = nearest <= container_tolerance_mm
            # A cut face lies *on the cutter boundary*, and being inside the cutter says nothing
            # for M- (every one of its vertices is inside C by construction).  Merely touching the
            # cutter is not enough either: a surface that only *grazes* it — the plan's "擦边",
            # e.g. the outer wall along the tangent line of the cut plane — is at distance ~0 while
            # its normal is perpendicular to the cutter's.  Measured on V13 that mislabels
            # 7074 mm^2 of outer wall as the new fracture surface (four times the real shared
            # area).  A genuine cut face is (anti)parallel to the cutter surface it lies on.
            container_normal = np.asarray(container.face_normals, dtype=np.float64)[
                np.asarray(triangle_id, dtype=np.int64)]
            vertex_normal = np.asarray(result.mesh.vertex_normals, dtype=np.float64)
            aligned = np.abs(np.einsum("ij,ij->i", container_normal, vertex_normal)) \
                >= GRAZING_NORMAL_DOT
            on_boundary = touching & aligned
            inside = vertex_inside | touching
            origin[on_boundary] = ORIGIN_INTERFACE
        origin[ambiguous] = ORIGIN_AMBIGUOUS
        return {
            "vertex_origin": origin,
            "vertex_source_tri": source_tri,
            "vertex_ambiguous": ambiguous,
            "vertex_mesh_id": np.round(mesh_ids).astype(np.int64),
            "vertex_locator_distance_mm": locator_distance,
            "vertex_source_normal": face_normal,
            "vertex_inside_container": inside,
            "vertex_on_container": on_boundary,
            "vertex_container_distance_mm": container_distance,
        }


# ---------------------------------------------------------------------------- helpers


def components(mesh: trimesh.Trimesh) -> tuple[np.ndarray, int]:
    """Connected face component labels via the face adjacency graph."""
    labels = trimesh.graph.connected_component_labels(
        np.asarray(mesh.face_adjacency), node_count=int(mesh.faces.shape[0]))
    return np.asarray(labels, dtype=np.int64), int(labels.max()) + 1 if labels.size else 0


def faces_inside(points: np.ndarray, mesh: trimesh.Trimesh) -> np.ndarray:
    """Containment test for query points against a watertight mesh."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if pts.shape[0] == 0:
        return np.zeros(0, dtype=bool)
    return np.asarray(mesh.contains(pts), dtype=bool)


def interior_point(mesh: trimesh.Trimesh) -> np.ndarray:
    """A point strictly inside a watertight mesh (inward chord probe + signed distance)."""
    if mesh.is_empty or len(mesh.faces) == 0:
        raise SynLabError(ErrorCode.MOTHER_INVALID, "empty mesh has no interior point",
                          stage="fracture.booleans.interior_point")
    from trimesh.proximity import signed_distance

    def depth(points: np.ndarray) -> np.ndarray:
        return np.asarray(signed_distance(points, mesh), dtype=np.float64)

    centroid = np.average(np.asarray(mesh.triangles_center, dtype=np.float64),
                          weights=np.asarray(mesh.area_faces, dtype=np.float64), axis=0)
    candidates = [centroid]
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    for point in verts:
        direction = centroid - point
        norm = float(np.linalg.norm(direction))
        if norm <= 0.0:
            continue
        candidates.append(point + direction / norm * (norm * 0.5))
    stacked = np.asarray(candidates, dtype=np.float64)
    values = depth(stacked)
    best = int(np.argmax(values))
    if not np.isfinite(values[best]) or values[best] <= 0.0:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "could not locate a strictly interior point (degenerate mesh)",
                          stage="fracture.booleans.interior_point",
                          measurements={"max_signed_distance": float(values[best])})
    return stacked[best]
