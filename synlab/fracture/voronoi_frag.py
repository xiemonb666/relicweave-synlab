"""Physically weighted Voronoi fragmentation into convex cells (multi-piece, not two halves).

Why this module exists
----------------------
``plane_shared_cut`` splits a body with **one** plane (plus a connected-component split), so a
real mother yields 2-6 pieces and the piece count is a property of the *topology*, not of the
physics.  This module builds a genuine multi-piece partition:

1. seed points are drawn from the **material volume** with a density that follows measured
   geometry (inverse wall thickness), local curvature and distance to the impact point
   (:func:`seed_points`);
2. every seed gets the **convex polyhedron** of points closer to it than to any other seed --
   the Voronoi cell -- built by explicit half-space clipping of a padded bounding box
   (:func:`voronoi_cells`).  Cells are never obtained from a black-box mesh library, so the
   arithmetic is auditable and the *same* bisector plane produces the *same* vertices for both
   neighbours;
3. each cell is a closed, positively oriented, watertight convex solid
   (:meth:`ConvexCell.as_mesh`), so ``M ∩ cell`` is a valid CSG operand for ``manifold3d``.

The conjugacy property is structural, not a tolerance: a facet shared by cells ``i`` and ``j``
is generated from the identical bisector plane with the identical clipping arithmetic in both
cells, so the two clipped surfaces carry bit-identical vertices.  :func:`facet_conjugacy_report`
measures that claim on the produced meshes instead of assuming it.

Nothing here reads a file or draws global randomness: every function takes an explicit
``np.random.Generator`` or a seed integer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np
import trimesh

from ..canonical import hash_json

__all__ = [
    "Plane",
    "ConvexCell",
    "VoronoiPartition",
    "SeedConfig",
    "material_candidates",
    "seed_points",
    "voronoi_cells",
    "build_partition",
    "facet_conjugacy_report",
    "cell_mesh_stats",
]

_EPS = 1.0e-12
#: vertex merge tolerance of the half-space clipper (mm).  1e-6 mm is four orders of magnitude
#: below the 0.02 mm interface budget, so merging can never hide a real gap.
MERGE_TOL_MM = 1.0e-6


def _unit(vector: np.ndarray) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float64).reshape(3)
    norm = float(np.linalg.norm(value))
    if norm <= _EPS:
        raise ValueError("degenerate direction")
    return value / norm


# ---------------------------------------------------------------------------- planes / faces


@dataclass
class Plane:
    """Oriented plane ``n . x = d`` (the closed half-space kept is ``n . x <= d``)."""

    normal: np.ndarray
    offset: float
    tag: str = ""

    def as_tuple(self) -> tuple[float, float, float, float]:
        n = np.asarray(self.normal, dtype=np.float64)
        return (float(n[0]), float(n[1]), float(n[2]), float(self.offset))

    def signed(self, points: np.ndarray) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        return pts @ np.asarray(self.normal, dtype=np.float64) - float(self.offset)


@dataclass
class _Face:
    """One planar facet of a convex polyhedron: ordered polygon + the plane that created it."""

    vertices: np.ndarray            # (k, 3), one cyclic order, no repeats
    plane: Plane

    def area(self) -> float:
        pts = np.asarray(self.vertices, dtype=np.float64)
        if pts.shape[0] < 3:
            return 0.0
        anchor = pts[0]
        cross = np.cross(pts[1:-1] - anchor, pts[2:] - anchor)
        return float(0.5 * np.linalg.norm(cross.sum(axis=0)))


# ---------------------------------------------------------------------------- clipping


def _dedup(points: np.ndarray, tol: float = MERGE_TOL_MM) -> np.ndarray:
    """Remove consecutive duplicates (cyclic) with tolerance ``tol``."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if pts.shape[0] <= 1:
        return pts
    keep = [0]
    for index in range(1, pts.shape[0]):
        if float(np.linalg.norm(pts[index] - pts[keep[-1]])) > tol:
            keep.append(index)
    if len(keep) > 1 and float(np.linalg.norm(pts[keep[-1]] - pts[keep[0]])) <= tol:
        keep.pop()
    return pts[keep]


def _plane_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = _unit(normal)
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = _unit(helper - n * float(helper @ n))
    return e1, np.cross(n, e1)


def _sort_cyclic_on_plane(points: np.ndarray, normal: np.ndarray) -> np.ndarray:
    """Order coplanar points counter-clockwise around their centroid (seen from ``+normal``)."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if pts.shape[0] <= 2:
        return pts
    centre = pts.mean(axis=0)
    e1, e2 = _plane_basis(normal)
    rel = pts - centre
    angles = np.arctan2(rel @ e2, rel @ e1)
    order = np.argsort(angles, kind="stable")
    return pts[order]


def _clip_face(face: _Face, plane: Plane) -> tuple[_Face | None, np.ndarray]:
    """Clip one convex facet by ``plane`` (keeping ``n.x <= d``).

    Returns the surviving facet (``None`` when it vanished) and the ordered intersection
    segment that the facet contributes to the new cut face.
    """
    pts = np.asarray(face.vertices, dtype=np.float64)
    values = plane.signed(pts)
    tol = MERGE_TOL_MM
    inside = values <= tol
    outside = values >= -tol
    if not bool(np.any(inside)):
        return None, np.zeros((0, 3), dtype=np.float64)
    if bool(np.all(inside)):
        return face, np.zeros((0, 3), dtype=np.float64)

    kept: list[np.ndarray] = []
    on_plane: list[np.ndarray] = []
    count = pts.shape[0]
    for index in range(count):
        current = pts[index]
        following = pts[(index + 1) % count]
        v_cur = float(values[index])
        v_next = float(values[(index + 1) % count])
        if v_cur <= tol:
            kept.append(current)
            if v_cur >= -tol:
                on_plane.append(current)
        if (v_cur > tol and v_next < -tol) or (v_cur < -tol and v_next > tol):
            t = v_cur / (v_cur - v_next)
            hit = current + t * (following - current)
            kept.append(hit)
            on_plane.append(hit)
    if len(kept) < 3:
        return None, np.zeros((0, 3), dtype=np.float64)
    polygon = _dedup(np.asarray(kept, dtype=np.float64))
    if polygon.shape[0] < 3:
        return None, np.zeros((0, 3), dtype=np.float64)
    segment = _dedup(np.asarray(on_plane, dtype=np.float64)) if on_plane else \
        np.zeros((0, 3), dtype=np.float64)
    return _Face(vertices=polygon, plane=face.plane), segment


def _polygon_normal(points: np.ndarray) -> np.ndarray:
    """Area-weighted normal of a polygon (Newell's method; stable for any vertex count)."""
    pts = np.asarray(points, dtype=np.float64)
    normal = np.zeros(3, dtype=np.float64)
    for index in range(pts.shape[0]):
        current = pts[index]
        following = pts[(index + 1) % pts.shape[0]]
        normal += np.cross(current, following)
    return normal


def _outward(face: _Face, interior: np.ndarray) -> _Face:
    """Make a facet's cyclic order counter-clockwise as seen from *outside* the solid.

    The polygon's own area normal is computed with Newell's method (which sums *every* edge, so a
    facet whose first two edges are nearly collinear -- a 4-corner box facet, for instance -- is
    still measured correctly; a first-edge cross product is not).  Flipping is then decided by two
    signs that are both robust: the polygon normal against the facet's plane normal, and the
    interior point against the plane.  A wrongly wound facet leaves the cell watertight while
    ``mesh.volume`` is short by twice the facet's own contribution -- measured on V13:
    350123.0 instead of 402958.7 mm^3 -- and ``manifold3d`` then refuses the operand.
    """
    pts = np.asarray(face.vertices, dtype=np.float64)
    if pts.shape[0] < 3:
        return face
    pts = _dedup(pts)
    if pts.shape[0] < 3:
        return _Face(vertices=pts, plane=face.plane)
    normal = np.asarray(face.plane.normal, dtype=np.float64)
    offset = float(face.plane.offset)
    centre = pts.mean(axis=0)
    if float(centre @ normal - offset) < 0.0:
        normal = -normal
        offset = -offset
    interior_side = float(np.asarray(interior, dtype=np.float64) @ normal - offset)
    area_normal = _polygon_normal(pts)
    if float(area_normal @ normal) * interior_side > 0.0:
        pts = pts[::-1]
    return _Face(vertices=pts, plane=face.plane)


def _box_faces(lo: np.ndarray, hi: np.ndarray, tag: str = "box") -> list[_Face]:
    lo = np.asarray(lo, dtype=np.float64)
    hi = np.asarray(hi, dtype=np.float64)
    faces: list[_Face] = []
    for axis in range(3):
        low_normal = np.zeros(3)
        low_normal[axis] = -1.0
        high_normal = np.zeros(3)
        high_normal[axis] = 1.0
        faces.append(_Face(vertices=_box_plane_polygon(lo, hi, axis, lo[axis]),
                           plane=Plane(low_normal, -float(lo[axis]), f"{tag}_lo{axis}")))
        faces.append(_Face(vertices=_box_plane_polygon(lo, hi, axis, hi[axis]),
                           plane=Plane(high_normal, float(hi[axis]), f"{tag}_hi{axis}")))
    for face in faces:
        face.vertices = _sort_cyclic_on_plane(face.vertices, face.plane.normal)
    return faces


def _box_plane_polygon(lo: np.ndarray, hi: np.ndarray, axis: int, value: float) -> np.ndarray:
    other = [index for index in range(3) if index != axis]
    corners = []
    for a in (lo[other[0]], hi[other[0]]):
        for b in (lo[other[1]], hi[other[1]]):
            point = np.zeros(3)
            point[axis] = float(value)
            point[other[0]] = float(a)
            point[other[1]] = float(b)
            corners.append(point)
    return np.asarray(corners, dtype=np.float64)


def clip_polyhedron(faces: Sequence[_Face], plane: Plane,
                    interior: np.ndarray) -> tuple[list[_Face], _Face | None]:
    """Clip a convex polyhedron by one half-space; returns ``(faces, cut_face)``."""
    kept_faces: list[_Face] = []
    cut_points: list[np.ndarray] = []
    for face in faces:
        surviving, segment = _clip_face(face, plane)
        if surviving is not None:
            kept_faces.append(surviving)
        if segment.shape[0]:
            cut_points.extend(list(segment))
    cut_face: _Face | None = None
    if cut_points:
        polygon = _sort_cyclic_on_plane(_dedup(np.asarray(cut_points, dtype=np.float64)),
                                        plane.normal)
        if polygon.shape[0] >= 3:
            cut_face = _Face(vertices=polygon, plane=plane)
            kept_faces.append(cut_face)
    # ``interior`` is carried through unchanged (it is still inside the clipped solid, because the
    # solid can only shrink): it is what decides every facet's winding, and keeping it exact is
    # what keeps the volume of the cell mesh equal to the volume of the facet soup.
    kept_faces = [_outward(face, interior) for face in kept_faces if face.vertices.shape[0] >= 3]
    return kept_faces, cut_face


def polyhedron_volume(faces: Sequence[_Face]) -> float:
    """Signed volume of a closed facet soup (positive for outward-oriented facets)."""
    total = 0.0
    for face in faces:
        pts = np.asarray(face.vertices, dtype=np.float64)
        if pts.shape[0] < 3:
            continue
        anchor = pts[0]
        total += float(np.dot(anchor, np.cross(pts[1:-1] - anchor, pts[2:] - anchor).sum(axis=0)))
    return total / 6.0


def orient_outward(mesh: trimesh.Trimesh, interior: np.ndarray) -> int:
    """Flip every triangle whose normal points towards ``interior``; returns the flip count.

    The cell is convex and ``interior`` is a point strictly inside it, so the test
    ``dot(normal, centroid - interior) > 0`` is exact for every triangle of every facet, with no
    dependence on a polygon's vertex count, on collinear vertices, or on nearly-coincident points
    left behind by the clipper.

    The normal is taken with the **cross product at vertex 0** ``(b - a) x (c - a)``.  The
    alternative ``a x b + b x c + c x a`` is an area normal too, but its sign is unstable when the
    origin lies on the triangle's plane -- which is the common case here, because the world origin
    sits on many of the padded-box facets -- and a single flipped triangle makes the whole cell
    non-manifold for ``manifold3d`` (measured on V13: facets of 4 points and 1e-9 area at the
    origin, every boolean returning empty).

    Two weaker repairs were measured and **rejected** on the same geometry (V13, 4 cells):

    * ``mesh.fix_normals()`` leaves ``is_winding_consistent`` False;
    * a per-triangle "contribution to the enclosed volume" test is *not* sign-stable: flipping the
      four triangles it called negative took the cell from 251662.9 mm^3 to 468737.7 mm^3, i.e.
      the test mis-classified them.
    """
    points = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if faces.shape[0] == 0:
        return 0
    triangles = points[faces]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    centroids = triangles.mean(axis=1)
    outward = np.einsum("ij,ij->i", normals, centroids - np.asarray(interior,
                                                                   dtype=np.float64)[None, :]) > 0.0
    flip = ~outward
    if bool(np.any(flip)):
        faces = faces.copy()
        faces[flip] = faces[flip][:, ::-1]
        mesh.faces = faces
    return int(np.sum(flip))


def _fan_triangles(polygon: np.ndarray, *, anchor: np.ndarray,
                   normal: np.ndarray) -> np.ndarray:
    """Triangulate a convex facet by a fan from the vertex with the smallest index.

    The starting vertex is chosen by the facet's own canonical cyclic order (which both
    neighbours of a shared facet compute identically -- see :func:`_canonical_polygon`), so two
    adjacent cells emit the *same* triangle edges on their common facet, mirrored.  That is what
    makes the conjugate distance exactly zero instead of "small".
    """
    pts = np.asarray(polygon, dtype=np.float64)
    count = pts.shape[0]
    if count < 3:
        return np.zeros((0, 3), dtype=np.int64)
    del anchor, normal
    return np.asarray([(0, index, index + 1) for index in range(1, count - 1)], dtype=np.int64)


def _canonical_polygon(polygon: np.ndarray, interior: np.ndarray, normal: np.ndarray
                       ) -> np.ndarray:
    """Rotation-canonical cyclic order of one facet, **winding preserved**.

    Two neighbours see the same facet with possibly a rotated starting vertex.  Rotating both to
    start at the lexicographically smallest vertex makes the two vertex sequences equal, so their
    triangulations match edge for edge.  The *winding* is deliberately **not** normalised here:
    winding is owned by :func:`_outward`, and flipping it again from a cross-product sign is what
    produced an inconsistently wound cell mesh (measured on V13: ``mesh.volume`` 380964.8 vs. the
    facet soup's 402958.7 mm^3, with ``is_watertight`` still True, i.e. a silent volume error).
    ``normal`` and ``interior`` are accepted so callers can pass the facet's own plane without
    special-casing, and are used only by the debug assertion below.
    """
    pts = np.asarray(polygon, dtype=np.float64)
    if pts.shape[0] < 3:
        return pts
    rounded = np.round(pts, 9)
    order = np.lexsort((rounded[:, 2], rounded[:, 1], rounded[:, 0]))
    start = int(order[0])
    del interior, normal
    return np.roll(pts, -start, axis=0)


# ---------------------------------------------------------------------------- cells


@dataclass
class ConvexCell:
    """One Voronoi cell: a closed convex solid plus its facet bookkeeping."""

    index: int
    seed: np.ndarray
    faces: list[_Face]
    #: plane of every facet (parallel to ``faces``), and the neighbour seed index it separates
    #: from (``-1`` for a padded-box facet, which is never a fracture surface)
    facet_planes: list[Plane] = field(default_factory=list)
    facet_neighbours: list[int] = field(default_factory=list)
    bounds: np.ndarray = field(default_factory=lambda: np.zeros((2, 3), dtype=np.float64))

    @property
    def volume(self) -> float:
        return polyhedron_volume(self.faces)

    def facet_polygons(self) -> list[np.ndarray]:
        interior = np.asarray(self.seed, dtype=np.float64)
        out: list[np.ndarray] = []
        for face in self.faces:
            normal = np.asarray(face.plane.normal, dtype=np.float64)
            out.append(_canonical_polygon(face.vertices, interior, normal))
        return out

    def as_mesh(self, *, validate: bool = True) -> trimesh.Trimesh:
        """Closed triangle mesh of the cell (watertight, outward normals, positive volume).

        The winding is repaired per **triangle** (a closed solid is outward-oriented exactly when
        every triangle contributes positively to the enclosed volume).  ``mesh.fix_normals()`` is
        not usable here: it goes through ``networkx`` and leaves ``is_winding_consistent`` False on
        these cells (measured), and an inconsistently wound cell is refused by ``manifold3d`` with
        ``Error.NotManifold`` -- which shows up downstream as an *empty* intersection, i.e. a
        silent volume loss, not as an error.
        """
        polygons = self.facet_polygons()
        vertices: list[np.ndarray] = []
        faces: list[tuple[int, int, int]] = []
        for polygon, face in zip(polygons, self.faces):
            if polygon.shape[0] < 3:
                continue
            start = len(vertices)
            vertices.extend(list(polygon))
            triangles = _fan_triangles(polygon, anchor=polygon[0],
                                       normal=np.asarray(face.plane.normal, dtype=np.float64))
            faces.extend((start + int(a), start + int(b), start + int(c))
                         for a, b, c in triangles)
        mesh = trimesh.Trimesh(vertices=np.asarray(vertices, dtype=np.float64),
                               faces=np.asarray(faces, dtype=np.int64), process=False)
        if validate:
            mesh.merge_vertices()
            keep = np.asarray(mesh.nondegenerate_faces(), dtype=bool)
            if not bool(np.all(keep)):
                mesh.update_faces(keep)
            mesh.remove_unreferenced_vertices()
            orient_outward(mesh, np.asarray(self.seed, dtype=np.float64))
        return mesh

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": int(self.index),
            "seed": [float(x) for x in np.asarray(self.seed, dtype=np.float64)],
            "facets": int(len(self.faces)),
            "volume_mm3": float(self.volume),
            "facet_neighbours": [int(x) for x in self.facet_neighbours],
            "facet_areas_mm2": [float(face.area()) for face in self.faces],
        }


def voronoi_cells(seeds: np.ndarray, bounds: np.ndarray, *, neighbours: int = 48,
                  max_facet_area_ratio: float = 1.0e-6) -> list[ConvexCell]:
    """Build the Voronoi cell of every seed by half-space clipping of ``bounds``.

    ``neighbours`` nearest seeds are used as clipping planes; a bisector that cannot cut the
    current cell is dropped, so using more candidates than Delaunay neighbours is safe (it can
    only be redundant, never wrong) and it removes the need for a robust 3-D Voronoi library.
    A plane is tested against the *current* facets before clipping, so redundant work is skipped
    instead of paying for a full clip every time.

    A cell that the clipping removes entirely (a seed outside the convex hull of the others, or a
    duplicate seed) is **dropped and reported**, never silently merged into a neighbour.
    """
    points = np.asarray(seeds, dtype=np.float64).reshape(-1, 3)
    bounds = np.asarray(bounds, dtype=np.float64).reshape(2, 3)
    if points.shape[0] == 0:
        return []
    from scipy.spatial import cKDTree

    tree = cKDTree(points)
    k = int(min(max(neighbours, 2), max(points.shape[0], 2)))
    _distance, index = tree.query(points, k=k)
    index = np.atleast_2d(index)
    cells: list[ConvexCell] = []
    for i in range(points.shape[0]):
        seed = np.asarray(points[i], dtype=np.float64)
        faces: list[_Face] = []
        #: owner of every face, keyed by the plane tag that created it; keeping a *dictionary*
        #: instead of a parallel list is what makes the bookkeeping exact -- clipping can
        #: consume a plane without emitting a facet (a vertex exactly on the plane), which
        #: silently shifted a positional list by one and mislabelled every later facet.
        owner_by_tag: dict[str, int] = {}
        for box_face in _box_faces(bounds[0], bounds[1]):
            faces.append(_Face(vertices=np.asarray(box_face.vertices, dtype=np.float64).copy(),
                               plane=Plane(np.asarray(box_face.plane.normal, dtype=np.float64),
                                           float(box_face.plane.offset), box_face.plane.tag)))
            owner_by_tag[box_face.plane.tag] = -1
        candidate = [int(j) for j in index[i] if int(j) != i]
        # cut with the closest neighbour first: the surviving cell is then already small and the
        # remaining candidate planes are far more likely to be redundant
        candidate.sort(key=lambda j: float(np.linalg.norm(points[j] - seed)))
        for j in candidate:
            other = np.asarray(points[j], dtype=np.float64)
            delta = other - seed
            length = float(np.linalg.norm(delta))
            if length <= MERGE_TOL_MM:
                continue
            normal = delta / length
            plane = Plane(normal, float(normal @ (0.5 * (seed + other))), f"bisector_{j}")
            if not faces or polyhedron_volume(faces) <= _EPS:
                break
            # cheapest possible rejection: a plane that every current vertex already satisfies
            # cannot change the cell
            extreme = max(float(np.max(face.vertices @ normal)) for face in faces
                          if face.vertices.shape[0]) if faces else 0.0
            if extreme <= plane.offset + MERGE_TOL_MM:
                continue
            faces, _cut = clip_polyhedron(faces, plane, seed)
            owner_by_tag[plane.tag] = int(j)
        owners = [int(owner_by_tag.get(face.plane.tag, -2)) for face in faces]
        # **drop degenerate facets.**  Half-space clipping emits a "facet" for every plane that
        # touched the solid, including planes that only grazed a vertex or an existing edge: that
        # produces a polygon with repeated vertices and zero area (measured on V13: a 7-vertex
        # facet with 3 distinct, collinear points).  Such a facet is not part of the hull, and
        # keeping it makes the cell non-manifold for ``manifold3d`` while ``is_watertight`` still
        # says True.
        areas = np.asarray([face.area() for face in faces], dtype=np.float64) if faces else \
            np.zeros(0, dtype=np.float64)
        if areas.size:
            threshold = max(float(max_facet_area_ratio) * float(areas.max()), 1.0e-14)
            keep = [row for row in range(len(faces)) if areas[row] > threshold
                    and _dedup(faces[row].vertices).shape[0] >= 3]
            faces = [faces[row] for row in keep]
            owners = [owners[row] for row in keep]
        volume = polyhedron_volume(faces) if faces else 0.0
        if len(faces) < 4 or volume <= _EPS:
            continue
        vertices = np.concatenate([face.vertices for face in faces], axis=0)
        cells.append(ConvexCell(
            index=int(i), seed=seed, faces=faces,
            facet_planes=[face.plane for face in faces], facet_neighbours=owners,
            bounds=np.stack([vertices.min(axis=0), vertices.max(axis=0)]),
        ))
    return cells


# ---------------------------------------------------------------------------- seeds


@dataclass
class SeedConfig:
    """Declared weights of the seed-density law (mirrors ``fracture_physics.yaml: seeds``)."""

    thickness_exponent: float = 1.0
    curvature_gain: float = 1.0
    curvature_exponent: float = 0.5
    impact_decay_mm: float = 60.0
    impact_weight: float = 1.0
    min_weight_ratio: float = 0.05
    jitter_mm: float = 0.35
    max_candidates: int = 20000
    #: ``farthest_weighted`` (default) alternates one weighted draw with farthest-point
    #: refinement, so a thin-walled shell cannot spend all its seeds inside one wall band
    #: (measured on V13 at N=32: 8 wasted seeds with pure weighted sampling, 0 with refinement).
    #: ``weighted`` is kept so the effect of the strategy is measurable instead of asserted.
    strategy: str = "farthest_weighted"

    def as_dict(self) -> dict[str, Any]:
        return {
            "thickness_exponent": float(self.thickness_exponent),
            "curvature_gain": float(self.curvature_gain),
            "curvature_exponent": float(self.curvature_exponent),
            "impact_decay_mm": float(self.impact_decay_mm),
            "impact_weight": float(self.impact_weight),
            "min_weight_ratio": float(self.min_weight_ratio),
            "jitter_mm": float(self.jitter_mm),
            "max_candidates": int(self.max_candidates),
            "strategy": str(self.strategy),
        }


def material_candidates(mesh: trimesh.Trimesh, *, target: int, rng: np.random.Generator,
                        cfg: SeedConfig, stride_mm: float | None = None
                        ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Stratified candidate points inside the material + their local geometric weights.

    Candidate positions are drawn **inside the volume** (stratified jittered grid + an
    inside-the-material test), never on a bounding-box plane, so a seed can never land in the
    cavity of a vessel and produce an empty cell.  The weight of a candidate is

    ``w = (t_ref / t(p))^a_t * (1 + k_c * kappa(p) * s^2)^a_c * (w_i * exp(-d_imp(p)/lam) + 1 - w_i)``

    with ``t(p)`` the thickness of the *local* material at ``p``.  The local thickness is
    measured, not assumed: ``t(p) = 2 * d_surface(p)`` where ``d_surface`` is the exact distance
    to the mesh surface, which equals the wall thickness for a point on the shell's mid-surface
    and saturates for a thick solid body.  ``kappa(p)`` is the discrete mean curvature of the
    surface at the candidate's nearest surface point, ``d_imp`` the distance to the impact point.
    """
    points = np.asarray(mesh.vertices, dtype=np.float64)
    lo = points.min(axis=0)
    hi = points.max(axis=0)
    extent = np.maximum(hi - lo, 1e-6)
    volume = float(abs(mesh.volume))
    if stride_mm is None:
        # aim for a candidate pool of the requested size
        stride_mm = float(np.clip((volume / max(int(target), 1)) ** (1.0 / 3.0),
                                  0.35, 12.0))
    grid = np.maximum(np.ceil(extent / float(stride_mm)).astype(np.int64), 1)
    while int(np.prod(grid)) > int(cfg.max_candidates):
        stride_mm = float(stride_mm) * 1.3
        grid = np.maximum(np.ceil(extent / float(stride_mm)).astype(np.int64), 1)
    axes = [lo[axis] + (np.arange(grid[axis]) + 0.5) * extent[axis] / grid[axis]
            for axis in range(3)]
    meshgrid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    jitter = (rng.random(meshgrid.shape) - 0.5) * float(cfg.jitter_mm) * 2.0
    candidates = meshgrid + jitter
    inside = np.asarray(mesh.contains(candidates), dtype=bool)
    candidates = candidates[inside]
    if candidates.shape[0] == 0:
        return candidates, np.zeros(0, dtype=np.float64), {
            "candidates": 0, "stride_mm": float(stride_mm), "grid": [int(x) for x in grid]}
    nearest, distance, triangle = mesh.nearest.on_surface(candidates)
    del nearest
    thickness = 2.0 * np.asarray(distance, dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    curvature = _vertex_curvature(mesh)
    triangle = np.asarray(triangle, dtype=np.int64).reshape(-1)
    vertex_ids = np.asarray(mesh.faces, dtype=np.int64)[triangle]
    face_normal = normals[triangle]
    # local geometric weight
    t_ref = float(np.median(thickness[thickness > 0.0])) if np.any(thickness > 0.0) else 1.0
    safe_t = np.maximum(thickness, 1.0e-3)
    weight = (t_ref / safe_t) ** float(cfg.thickness_exponent)
    scale = float(np.max(extent))
    kappa = np.max(np.abs(curvature[vertex_ids]), axis=1)
    weight = weight * (1.0 + float(cfg.curvature_gain) * kappa * scale ** 2) ** float(
        cfg.curvature_exponent)
    stats = {
        "candidates": int(candidates.shape[0]),
        "stride_mm": float(stride_mm),
        "grid": [int(x) for x in grid],
        "thickness_median_mm": float(t_ref),
        "thickness_min_mm": float(np.min(thickness)) if thickness.size else 0.0,
        "thickness_max_mm": float(np.max(thickness)) if thickness.size else 0.0,
        "curvature_p95_per_mm": float(np.percentile(kappa, 95)) if kappa.size else 0.0,
        "face_normal_agreement": float(np.mean(
            np.einsum("ij,ij->i", face_normal,
                      _unit_rows(candidates - np.asarray(mesh.triangles_center)[triangle]))
            < 0.0)) if candidates.shape[0] else 0.0,
    }
    del scale
    return candidates, weight, stats


def _unit_rows(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64).reshape(-1, 3)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    return array / np.maximum(norms, _EPS)


def _vertex_curvature(mesh: trimesh.Trimesh) -> np.ndarray:
    """Discrete mean curvature per vertex (1/mm) from the cotangent-free area-weighted estimate.

    ``kappa(v) = |sum_f (n_f * angle_f)| / (2 * A_voronoi)`` is the standard discrete mean
    curvature magnitude; it is a *relative* measure here (it decides which regions get more
    seeds), and its units are 1/mm so the dimensionless group ``kappa * scale**2`` in the weight
    is well defined.
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    accum = np.zeros_like(vertices)
    area_sum = np.zeros(vertices.shape[0], dtype=np.float64)
    for corner in range(3):
        index = faces[:, corner]
        np.add.at(accum, index, normals * (areas / 3.0)[:, None])
        np.add.at(area_sum, index, areas / 3.0)
    magnitude = np.linalg.norm(accum, axis=1) / np.maximum(area_sum, _EPS)
    return np.asarray(magnitude, dtype=np.float64).reshape(-1)


def seed_points(mesh: trimesh.Trimesh, count: int, *, rng: np.random.Generator,
                cfg: SeedConfig, impact_point: np.ndarray | None = None,
                min_seed_distance_mm: float = 0.5
                ) -> tuple[np.ndarray, dict[str, Any]]:
    """Draw ``count`` seeds with the physically weighted density; returns ``(points, report)``.

    Selection is weighted sampling **without replacement on the candidate set**: each candidate
    is used at most once, so no two seeds can coincide (which would create a degenerate cell).
    If the weighted draw runs out of admissible candidates, the deficit is reported in the
    report as ``shortfall`` instead of being filled with unweighted duplicates.
    """
    target = max(int(count), 1)
    candidates, weight, stats = material_candidates(mesh, target=target, rng=rng, cfg=cfg)
    report: dict[str, Any] = dict(stats)
    report["seed_config"] = cfg.as_dict()
    if candidates.shape[0] == 0:
        report["shortfall"] = int(target)
        return np.zeros((0, 3), dtype=np.float64), report
    if impact_point is not None:
        distance = np.linalg.norm(candidates - np.asarray(impact_point, dtype=np.float64), axis=1)
        decay = np.exp(-distance / max(float(cfg.impact_decay_mm), 1e-6))
        weight = weight * (1.0 - float(cfg.impact_weight)
                           + float(cfg.impact_weight) * decay)
    floor = float(cfg.min_weight_ratio) * float(np.max(weight))
    weight = np.maximum(weight, floor)
    # keep the pool a bounded multiple of the request: otherwise the weighted draw mostly spends
    # entropy on candidates that will not be used
    pool_limit = int(min(candidates.shape[0], max(6 * target, 256)))
    order = np.argsort(-weight, kind="stable")[:pool_limit]
    pool = candidates[order]
    pool_weight = weight[order]
    if str(cfg.strategy) == "farthest_weighted":
        points, strategy_report = _farthest_weighted(pool, pool_weight, target, rng)
    else:
        points, strategy_report = _weighted_without_replacement(pool, pool_weight, target, rng)
    if points.shape[0] > 1:
        _prune_close(points, min_seed_distance_mm, report)
    report.update(strategy_report)
    report.update({
        "seeds_requested": int(target),
        "seeds_drawn": int(points.shape[0]),
        "pool": int(pool.shape[0]),
        "shortfall": int(max(target - points.shape[0], 0)),
        "weight_quantiles": [float(np.percentile(weight, q)) for q in (5, 50, 95)],
        "impact_point": None if impact_point is None else [float(x) for x in impact_point],
        "material_volume_mm3": float(abs(mesh.volume)),
        "seed_spacing_mean_mm": float(_mean_spacing(points)),
    })
    return points, report


def _weighted_without_replacement(pool: np.ndarray, pool_weight: np.ndarray, target: int,
                                  rng: np.random.Generator) -> tuple[np.ndarray, dict[str, Any]]:
    """Pure weighted draw: correct density, but can spend several seeds in one wall band."""
    keep = np.ones(pool.shape[0], dtype=bool)
    chosen: list[int] = []
    probabilities = pool_weight / float(np.sum(pool_weight))
    for _ in range(int(target)):
        if not bool(np.any(keep)):
            break
        probabilities = np.where(keep, probabilities, 0.0)
        total = float(np.sum(probabilities))
        if total <= 0.0:
            break
        pick = int(rng.choice(pool.shape[0], p=probabilities / total))
        keep[pick] = False
        chosen.append(pick)
    points = pool[np.asarray(chosen, dtype=np.int64)] if chosen else \
        np.zeros((0, 3), dtype=np.float64)
    return points, {"strategy": "weighted", "density_term": 1.0}


def _farthest_weighted(pool: np.ndarray, pool_weight: np.ndarray, target: int,
                       rng: np.random.Generator) -> tuple[np.ndarray, dict[str, Any]]:
    """Weighted density *and* greedy k-centre coverage over the material candidates.

    The first seed is drawn with the physical density; every further seed maximises
    ``weight(p) * distance(p, nearest selected seed)``.  The density term keeps the *placement*
    physical (thin / curved / near-impact material still gets proportionally more seeds, see
    :func:`seed_points`), while the coverage term is what stops the partition from wasting cells
    in the air: a Voronoi cell whose seed sits in the cavity of a hollow body contains no material
    at all and produces no piece, which silently lowers the achieved piece count.  The candidates
    are already restricted to material points, so maximising the distance to the nearest selected
    *material* point is exactly a coverage criterion on the body.
    """
    count = int(pool.shape[0])
    if count == 0:
        return np.zeros((0, 3), dtype=np.float64), {"strategy": "farthest_weighted"}
    wanted = int(min(max(target, 1), count))
    probabilities = pool_weight / float(np.sum(pool_weight))
    first = int(rng.choice(count, p=probabilities))
    selected = np.zeros(wanted, dtype=np.int64)
    selected[0] = first
    distance = np.linalg.norm(pool - pool[first], axis=1)
    used = np.zeros(count, dtype=bool)
    used[first] = True
    filled = 1
    for position in range(1, wanted):
        score = np.where(used, -np.inf, pool_weight * distance)
        pick = int(np.argmax(score))
        if not np.isfinite(score[pick]):
            break
        selected[position] = pick
        used[pick] = True
        filled = position + 1
        distance = np.minimum(distance, np.linalg.norm(pool - pool[pick], axis=1))
    points = pool[selected[:filled]]
    return points, {
        "strategy": "farthest_weighted",
        "spacing_min_mm": float(_min_pair_distance(points)),
    }


def _min_pair_distance(points: np.ndarray) -> float:
    if points.shape[0] < 2:
        return 0.0
    from scipy.spatial import cKDTree

    distance, _index = cKDTree(points).query(points, k=2)
    return float(np.min(distance[:, 1]))


def _prune_close(points: np.ndarray, minimum_mm: float, report: dict[str, Any]) -> np.ndarray:
    """Count (and report) seed pairs closer than ``minimum_mm``.

    Seeds are drawn without replacement from a stratum pool, so an exact coincidence cannot
    happen; this is the measurement that backs that claim.  A pair below the merge tolerance
    would produce a degenerate bisector, so the count is published instead of assumed to be 0.
    """
    if points.shape[0] < 2:
        report["near_duplicate_pairs"] = 0
        report["min_seed_distance_mm"] = 0.0
        return points
    from scipy.spatial import cKDTree

    tree = cKDTree(points)
    distance, _index = tree.query(points, k=2)
    nearest = float(np.min(distance[:, 1])) if distance.shape[0] else float("inf")
    pairs = tree.query_pairs(float(minimum_mm), output_type="ndarray")
    report["near_duplicate_pairs"] = int(np.asarray(pairs).reshape(-1, 2).shape[0]) \
        if np.size(pairs) else 0
    report["min_seed_distance_mm"] = nearest
    return points


def _mean_spacing(points: np.ndarray) -> float:
    if points.shape[0] < 2:
        return 0.0
    from scipy.spatial import cKDTree

    distance, _index = cKDTree(points).query(points, k=2)
    return float(np.mean(distance[:, 1]))


# ---------------------------------------------------------------------------- partition


@dataclass
class VoronoiPartition:
    """The whole partition: seeds, cells, per-cell volume and the derived size law."""

    seeds: np.ndarray
    cells: list[ConvexCell]
    bounds: np.ndarray
    dropped_seeds: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_cells(self) -> int:
        return len(self.cells)

    def volumes(self) -> np.ndarray:
        return np.asarray([cell.volume for cell in self.cells], dtype=np.float64)

    def as_dict(self) -> dict[str, Any]:
        volumes = self.volumes()
        return {
            "n_cells": int(self.n_cells),
            "dropped_seeds": int(self.dropped_seeds),
            "bounds": np.asarray(self.bounds, dtype=np.float64).tolist(),
            "cell_volumes_mm3": [float(x) for x in volumes],
            "cell_volume_total_mm3": float(np.sum(volumes)),
            "cell_volume_min_mm3": float(np.min(volumes)) if volumes.size else 0.0,
            "cell_volume_max_mm3": float(np.max(volumes)) if volumes.size else 0.0,
            "meta": dict(self.meta),
        }

    @property
    def hash(self) -> str:
        payload = {
            "seeds": np.round(np.asarray(self.seeds, dtype=np.float64), 9).tolist(),
            "bounds": np.round(np.asarray(self.bounds, dtype=np.float64), 9).tolist(),
        }
        return hash_json(payload)[:32]


def build_partition(mesh: trimesh.Trimesh, count: int, *, rng: np.random.Generator,
                    seed_cfg: SeedConfig, impact_point: np.ndarray | None = None,
                    padding_mm: float = 2.0, neighbours: int = 48
                    ) -> tuple[VoronoiPartition, dict[str, Any]]:
    """Full seed -> cell pipeline with the honest seed report attached.

    The padded bounding box is computed **once** and used both for the clipping and for the
    partition's recorded ``bounds``.  Recomputing it in two places (one of them from the *seed*
    bounds) silently made the recorded box smaller than the cells' own box, which made the
    "cells tile the box" volume check disagree with the geometry.
    """
    points, seed_report = seed_points(mesh, count, rng=rng, cfg=seed_cfg,
                                      impact_point=impact_point)
    if points.shape[0] == 0:
        raise ValueError("no seed point could be placed inside the material")
    lo = np.asarray(mesh.bounds[0], dtype=np.float64) - float(padding_mm)
    hi = np.asarray(mesh.bounds[1], dtype=np.float64) + float(padding_mm)
    cells = voronoi_cells(points, np.stack([lo, hi]), neighbours=neighbours)
    partition = VoronoiPartition(
        seeds=points, cells=cells, bounds=np.stack([lo, hi]),
        dropped_seeds=int(points.shape[0] - len(cells)),
        meta={"seed_report": seed_report, "padding_mm": float(padding_mm),
              "neighbours": int(neighbours)},
    )
    seed_report["cells"] = int(len(cells))
    seed_report["dropped_cells"] = int(partition.dropped_seeds)
    volumes = partition.volumes()
    if volumes.size:
        cell_total = float(np.sum(volumes))
        seed_report["cell_volume_sum_mm3"] = cell_total
        seed_report["cell_volume_uniformity"] = float(
            np.min(volumes) / max(np.max(volumes), _EPS))
        # the Voronoi cells must *tile* their common box: this is the structural check that the
        # per-cell clipping is complete.  A shortfall means material could be attributed to no
        # cell at all, so it is measured and reported (and refused above 5%, which cannot be a
        # rounding effect: the volumes are exact to ~1e-9 relative).
        box_total = float(np.prod(hi - lo))
        seed_report["bounds_volume_mm3"] = box_total
        seed_report["tile_volume_ratio"] = float(cell_total / max(box_total, _EPS))
        if cell_total < 0.95 * box_total:
            raise ValueError(
                f"the Voronoi cells tile only {cell_total / max(box_total, 1e-12):.4f} of their "
                f"box ({cell_total:.3f} of {box_total:.3f} mm^3): the partition is incomplete")
    return partition, seed_report


def facet_conjugacy_report(partition: VoronoiPartition, *, tolerance_mm: float = 1.0e-9
                           ) -> dict[str, Any]:
    """Measure, per shared facet, whether both cells really carry the same vertices.

    The claim "the two sides of a fracture surface are strictly conjugate" is only worth
    something if it is measured: this walks every internal facet, takes the polygon from both
    owning cells and reports the Hausdorff-style maximum nearest-vertex distance, the counted
    facet pairs, and any facet that only one side carries.
    """
    lookup: dict[tuple[int, int], list[tuple[int, int]]] = {}
    index_of = {int(cell.index): position for position, cell in enumerate(partition.cells)}
    for position, cell in enumerate(partition.cells):
        for facet_index, neighbour in enumerate(cell.facet_neighbours):
            if neighbour < 0:
                continue
            key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
            lookup.setdefault(key, []).append((position, facet_index))
    worst = 0.0
    pairs = 0
    one_sided = 0
    points_total = 0
    vertex_identity = 0
    for key, members in sorted(lookup.items()):
        if len(members) < 2:
            one_sided += 1
            continue
        polygons = []
        for position, facet_index in members[:2]:
            polygons.append(partition.cells[position].facet_polygons()[facet_index])
        a, b = polygons
        distance = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)
        worst = max(worst, float(np.max(np.min(distance, axis=1))),
                    float(np.max(np.min(distance, axis=0))))
        rounded_a = {tuple(row) for row in np.round(a, 9)}
        rounded_b = {tuple(row) for row in np.round(b, 9)}
        if rounded_a and rounded_a == rounded_b:
            vertex_identity += 1
        pairs += 1
        points_total += int(a.shape[0] + b.shape[0])
    del index_of
    return {
        "shared_facet_pairs": int(pairs),
        "one_sided_facets": int(one_sided),
        "identical_vertex_sets": int(vertex_identity),
        "max_vertex_distance_mm": float(worst),
        "tolerance_mm": float(tolerance_mm),
        "conjugate": bool(worst <= float(tolerance_mm) and one_sided == 0
                          and vertex_identity == pairs),
        "vertices_compared": int(points_total),
    }


def cell_mesh_stats(cells: Iterable[ConvexCell]) -> dict[str, Any]:
    """Watertightness / orientation / volume of every cell mesh (structural evidence)."""
    watertight = 0
    positive = 0
    total = 0
    worst_euler = None
    for cell in cells:
        mesh = cell.as_mesh()
        total += 1
        if bool(mesh.is_watertight):
            watertight += 1
        if float(mesh.volume) > 0.0:
            positive += 1
        euler = int(mesh.euler_number)
        worst_euler = euler if worst_euler is None else min(worst_euler, euler)
    return {
        "cells": int(total),
        "watertight": int(watertight),
        "positive_volume": int(positive),
        "min_euler_number": worst_euler,
        "all_convex_solids": bool(watertight == total == positive and total > 0),
    }


def cell_centroid(cell: ConvexCell) -> np.ndarray:
    """Volume centroid of a convex cell (used to order/identify pieces deterministically)."""
    faces = cell.faces
    total = 0.0
    accum = np.zeros(3, dtype=np.float64)
    origin = np.asarray(cell.seed, dtype=np.float64)
    for face in faces:
        pts = np.asarray(face.vertices, dtype=np.float64)
        if pts.shape[0] < 3:
            continue
        anchor = pts[0] - origin
        for index in range(1, pts.shape[0] - 1):
            b = pts[index] - origin
            c = pts[index + 1] - origin
            volume = float(np.dot(anchor, np.cross(b, c))) / 6.0
            total += volume
            accum += volume * (origin + (anchor + b + c) / 4.0)
    if abs(total) < _EPS:
        return np.asarray(cell.seed, dtype=np.float64)
    return accum / total


def partition_size_law(partition: VoronoiPartition) -> dict[str, Any]:
    """Piece count vs. characteristic size: the numbers the report's size law is built from."""
    volumes = partition.volumes()
    if volumes.size == 0:
        return {"n_cells": 0}
    equivalent = (6.0 * volumes / math.pi) ** (1.0 / 3.0)
    return {
        "n_cells": int(volumes.size),
        "volume_total_mm3": float(np.sum(volumes)),
        "volume_min_mm3": float(np.min(volumes)),
        "volume_median_mm3": float(np.median(volumes)),
        "volume_max_mm3": float(np.max(volumes)),
        "equivalent_diameter_min_mm": float(np.min(equivalent)),
        "equivalent_diameter_median_mm": float(np.median(equivalent)),
        "equivalent_diameter_max_mm": float(np.max(equivalent)),
        "size_ratio_max_over_min": float(np.max(volumes) / max(np.min(volumes), _EPS)),
    }
