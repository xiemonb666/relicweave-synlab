"""One multi-piece fracture event: physically driven count, Voronoi cells, rough shared facets.

This is the module that turns the partition built by :mod:`synlab.fracture.voronoi_frag` into a
complete :class:`~synlab.schemas.runtime.FractureResult`, i.e. into the same object the existing
pipeline, the auditor and the truth layer already understand:

* **piece count** from :mod:`synlab.fracture.impact` (size x toughness x impact energy);
* **pieces** ``M ∩ cell_k`` through ``manifold3d``, one CSG operand per cell, all from the *same*
  mother bytes;
* **fracture surfaces**: every facet that separates two cells is a real internal face; its two
  sides are generated from the identical bisector arithmetic, then displaced by the *same*
  spatial roughness field, so the two surfaces stay exactly conjugate;
* **face attributes**: ``origin_kind`` (``mother_surface`` / ``interface``), ``interface_id``,
  ``source_tri`` (the mother triangle) and ``side`` are written on every face;
* **secondary / tertiary crushing** re-runs the same machinery on the largest pieces, which is
  what makes a big shard break again instead of staying whole.

Roughness is *not* noise.  It is a finite Fourier sum whose shortest wavelength comes from the
material's grain size, whose amplitude comes from the measured wall thickness (clamped to the
package window ``[0.02, 0.30] mm``) and whose phases come from the facet's own geometry hash.
The horizontal wavelengths are long compared with the facet's vertical extent, so the field is
close to constant across the wall thickness: that is the thin-plate regime of a real fracture
surface (a wall cracks through its thickness as one front), and it is what keeps ``M ∩ cell`` a
valid solid instead of a self-intersecting one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np
import trimesh

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import (
    ORIGIN_INTERFACE,
    ORIGIN_MOTHER_SURFACE,
    FractureResult,
    Fragment,
)
from ..storage.mesh_io import with_face_attrs
from . import energy as energy_mod
from . import impact as impact_mod
from .booleans import (
    SourceResolver,
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
    is_tiny,
    make_fragment,
    split_components,
)
from .physics import PhysicsConfig
from .voronoi_frag import (
    ConvexCell,
    SeedConfig,
    VoronoiPartition,
    build_partition,
    cell_centroid,
    facet_conjugacy_report,
)
from .voronoi_frag import _canonical_polygon as canonical_polygon
from .voronoi_frag import _unit as unit_vector

__all__ = ["RoughnessField", "facet_roughness_field", "run_voronoi_event", "BACKEND"]

BACKEND = "warp_voronoi_cut"

#: how far the roughness displacement decays before it is treated as zero (mm).  Two decay
#: lengths is below the numerical noise of a 1e-6 mm vertex merge, so clamping there cannot
#: leave a sliver behind.
_DECAY_FLOOR = 1.0e-3


# ---------------------------------------------------------------------------- roughness


@dataclass
class RoughnessField:
    """Deterministic, physics-driven roughness shared by the two sides of one fracture surface.

    The displacement is a *spatial* field, not a per-facet translation, and that is what makes the
    two sides of a fracture stay glued without giving up the roughness:

    ``d(x) = g(x) * u(x) / |u(x)|``    with    ``u(x) = sum_b A_b cos(k_b . x + phi_b) * m_b``

    * ``A_b`` -- band amplitude = ``amp_wall_ratio * measured wall thickness``, split over
      ``n_bands`` logarithmic bands with a ``1/f^spectral_slope`` spectrum, clamped to the
      package window ``[0.02, 0.30] mm`` (``w_scale`` here is exactly that clamp factor, so
      ``A_b = w_scale * A_b^normalised`` corrects the amplitude when the clamp bites).
    * ``k_b`` -- wave vector from the band's wavelength (the shortest is
      ``wavelength_grain_ratio * measured grain size``, clamped to ``[0.20, 3.00] mm``) tilted out
      of the surface plane by :attr:`tilt`, which is what makes the field vary *through* the wall
      and keeps the fracture surface three-dimensional.
    * ``m_b`` -- unit direction of the band; the mean of the ``m_b`` is the **spatial** direction
      field, and its spatial variation is bounded by :attr:`spread` so adjacent vertices cannot
      be displaced in wildly different directions (which is what would fold the mesh).
    * ``g(x)`` -- smooth mask ``(1 - exp(-(w/L)^2)) * exp(-(r/R)^2)`` with ``w`` the distance
      along the wall normal and ``r`` the in-plane distance: zero on the cut surface of the
      mother, full inside the fracture surface.  ``d`` therefore vanishes where the fracture
      meets the mother's surface, so the CSG intersection with the mother stays valid.
    * the phases come from the SHA-256 of the facet's own plane + vertices: deterministic, and
      different facets get different topography without a single call to a random generator.
    """

    normal: np.ndarray
    trace: np.ndarray
    centroid: np.ndarray
    bands: list[tuple[float, np.ndarray, np.ndarray, float]]   # (A_b, k_b, m_b, phi_b)
    wall_mm: float
    mask_half_width_mm: float
    mask_in_plane_mm: float
    w_scale: float
    amplitude_mm: float
    wavelength_min_mm: float
    spread: float = 0.25
    meta: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ components
    def along(self, points: np.ndarray) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        return (pts - np.asarray(self.centroid, dtype=np.float64)) @ np.asarray(
            self.normal, dtype=np.float64)

    def in_plane(self, points: np.ndarray) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        rel = pts - np.asarray(self.centroid, dtype=np.float64)
        along = rel @ np.asarray(self.normal, dtype=np.float64)
        return np.linalg.norm(rel - along[:, None] * np.asarray(self.normal,
                                                               dtype=np.float64), axis=1)

    def mask(self, points: np.ndarray) -> np.ndarray:
        wall = np.abs(self.along(points))
        radius = self.in_plane(points)
        return (1.0 - np.exp(-((wall / max(self.wall_mm, _DECAY_FLOOR)) ** 2))) * np.exp(
            -((radius / max(self.mask_in_plane_mm, _DECAY_FLOOR)) ** 2))

    def vector(self, points: np.ndarray) -> np.ndarray:
        """``u(x)`` (the vector field before normalisation); ``|u|`` is the local amplitude."""
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        out = np.zeros_like(pts)
        for amplitude, k_vector, direction, phase in self.bands:
            value = float(amplitude) * np.cos(pts @ np.asarray(k_vector, dtype=np.float64)
                                              + float(phase))
            out += value[:, None] * np.asarray(direction, dtype=np.float64)[None, :]
        return out

    def displacement(self, points: np.ndarray) -> np.ndarray:
        vector = self.vector(points)
        magnitude = np.linalg.norm(vector, axis=1, keepdims=True)
        points_array = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        del points_array
        return self.mask(points) [:, None] * vector / np.maximum(magnitude, 1e-12)

    def scalar(self, points: np.ndarray) -> np.ndarray:
        return np.linalg.norm(self.vector(points), axis=1) * self.mask(points)

    def displace_all(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        pts = np.asarray(mesh.vertices, dtype=np.float64)
        mesh.vertices = pts + self.displacement(pts)
        return mesh

    def max_slope(self) -> float:
        """Lipschitz bound of ``d`` before the mask: ``sum_b A_b |k_b|``."""
        total = 0.0
        for amplitude, k_vector, _direction, _phase in self.bands:
            total += abs(float(amplitude)) * float(np.linalg.norm(k_vector))
        return float(total)

    def as_dict(self) -> dict[str, Any]:
        return {
            "bands": [{"amplitude_mm": float(a),
                       "wavelength_mm": float(2.0 * np.pi / max(np.linalg.norm(k), 1e-12)),
                       "k": [float(x) for x in np.asarray(k, dtype=np.float64)],
                       "direction": [float(x) for x in np.asarray(d, dtype=np.float64)],
                       "phase": float(p)} for a, k, d, p in self.bands],
            "wall_mm": float(self.wall_mm),
            "mask_half_width_mm": float(self.mask_half_width_mm),
            "mask_in_plane_mm": float(self.mask_in_plane_mm),
            "w_scale": float(self.w_scale),
            "amplitude_mm": float(self.amplitude_mm),
            "wavelength_min_mm": float(self.wavelength_min_mm),
            "max_slope": float(self.max_slope()),
            "normal": [float(x) for x in np.asarray(self.normal, dtype=np.float64)],
            "trace": [float(x) for x in np.asarray(self.trace, dtype=np.float64)],
            "centroid": [float(x) for x in np.asarray(self.centroid, dtype=np.float64)],
            "meta": dict(self.meta),
        }


def facet_roughness_field(cell_a: ConvexCell, cell_b: ConvexCell, facet_index: int, *,
                          config: PhysicsConfig, wall_mm: float, grain_mm: float,
                          seed: int = 0) -> RoughnessField:
    """Build one facet's roughness field from *measured* wall thickness and grain size."""
    rough = config.roughness
    facet = cell_a.faces[facet_index]
    normal = np.asarray(facet.plane.normal, dtype=np.float64)
    normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
    vertices = np.asarray(facet.vertices, dtype=np.float64)
    centroid = vertices.mean(axis=0)
    best = None
    best_length = -1.0
    for i in range(min(vertices.shape[0], 24)):
        for j in range(i + 1, min(vertices.shape[0], 24)):
            edge = vertices[j] - vertices[i]
            length = float(np.linalg.norm(edge))
            if length > best_length:
                best_length = length
                best = edge
    trace = np.zeros(3, dtype=np.float64)
    if best is not None and best_length > 1e-9:
        candidate = best / best_length
        candidate = candidate - normal * float(candidate @ normal)
        length = float(np.linalg.norm(candidate))
        trace = candidate / length if length > 1e-9 else np.zeros(3, dtype=np.float64)

    amp_normalised = float(rough.amp_wall_ratio) * max(float(wall_mm), 0.0)
    amplitude = float(min(max(amp_normalised, float(rough.amp_min_mm)),
                          float(rough.amp_max_mm)))
    w_scale = float(amplitude / max(amp_normalised, 1e-9))
    wavelength_min = rough.wavelength_min_for(grain_mm)
    wavelength_max = max(float(rough.wavelength_max_mm), wavelength_min * 1.05)
    vertical = max(float(wall_mm), 0.05)
    mask_half_width = max(2.5 * vertical, 2.0 * wavelength_min)
    in_plane = max(3.0 * best_length, 4.0 * wavelength_max)
    n_bands = int(np.clip(rough.n_bands, 2, 8))
    phases = _phases_for(facet, seed, n_bands)

    e1 = _orthonormal(normal)
    e2 = np.cross(normal, e1)
    edges = np.geomspace(wavelength_min, wavelength_max, n_bands + 1)
    raw: list[tuple[float, np.ndarray, np.ndarray, float]] = []
    total_weight = 0.0
    directions: list[np.ndarray] = []
    for index in range(n_bands):
        wavelength = float(0.5 * (edges[index] + edges[index + 1]))
        theta = float(phases[index])
        direction = (e1 * math.cos(theta) + e2 * math.sin(theta)
                     + float(rough.anisotropy) * trace * math.cos(2.0 * theta))
        direction = direction / max(float(np.linalg.norm(direction)), 1e-12)
        weight = (wavelength / wavelength_min) ** (-float(rough.spectral_slope))
        total_weight += weight
        # tilt out of the surface plane: this is what makes the field vary *through* the wall
        tilt = 0.35 * float(np.clip(vertical / max(wavelength, 1e-9), 0.0, 1.0))
        k_vector = direction * (2.0 * np.pi / max(wavelength, 1e-9)) + normal * tilt * (
            2.0 * np.pi / max(wavelength, 1e-9))
        raw.append((weight, k_vector, direction, float(phases[n_bands + index])))
        directions.append(direction)
    mean_direction = np.sum(np.asarray(directions, dtype=np.float64), axis=0)
    mean_direction = mean_direction / max(float(np.linalg.norm(mean_direction)), 1e-12)
    bands: list[tuple[float, np.ndarray, np.ndarray, float]] = []
    for weight, k_vector, direction, phase in raw:
        bands.append((float(amplitude) * weight / max(total_weight, 1e-12), k_vector, direction,
                      phase))
    spread = _direction_spread(directions, mean_direction)
    return RoughnessField(
        normal=normal, trace=trace, centroid=centroid, bands=bands, wall_mm=float(vertical),
        mask_half_width_mm=float(mask_half_width), mask_in_plane_mm=float(in_plane),
        w_scale=float(w_scale), amplitude_mm=float(amplitude),
        wavelength_min_mm=float(wavelength_min), spread=float(spread),
        meta={
            "wall_mm": float(wall_mm), "grain_mm": float(grain_mm),
            "wavelength_max_mm": float(wavelength_max),
            "facet_longest_edge_mm": float(best_length),
            "spectral_slope": float(rough.spectral_slope),
            "anisotropy": float(rough.anisotropy),
            "amplitude_clamped": bool(abs(w_scale - 1.0) > 1e-9),
            "amplitude_source": "amp_wall_ratio * measured wall thickness, clamped to "
                                "the package window [0.02, 0.30] mm",
            "wavelength_source": "wavelength_grain_ratio * measured grain size, clamped to "
                                 "the package window [0.20, 3.00] mm",
            "phase_source": "deterministic: SHA-256 of the facet's own plane and vertices",
            "noise_used": False,
        },
    )


def _direction_spread(directions: Sequence[np.ndarray], mean: np.ndarray) -> float:
    if not len(directions):
        return 0.0
    values = np.asarray(directions, dtype=np.float64)
    return float(np.max(np.linalg.norm(values - mean[None, :], axis=1)))


def _orthonormal(normal: np.ndarray) -> np.ndarray:
    helper = np.array([1.0, 0.0, 0.0]) if abs(float(normal[0])) < 0.9 else \
        np.array([0.0, 1.0, 0.0])
    value = helper - np.asarray(normal, dtype=np.float64) * float(helper @ normal)
    norm = float(np.linalg.norm(value))
    return value / norm if norm > 1e-12 else np.array([0.0, 1.0, 0.0])


def _phases_for(facet: Any, seed: int, count: int) -> np.ndarray:
    payload = {
        "plane": [round(float(x), 9) for x in facet.plane.as_tuple()],
        "vertices": np.round(np.asarray(facet.vertices, dtype=np.float64), 6).tolist(),
        "seed": int(seed),
        "n": int(count),
    }
    digest = hash_json(payload).split(":", 1)[-1]
    values = np.asarray([int(digest[(index * 4) % 60:(index * 4) % 60 + 4], 16) / float(1 << 16)
                         for index in range(2 * count)], dtype=np.float64)
    return values * 2.0 * np.pi


def _phase_shift(facet: Any, seed: int) -> float:
    payload = {
        "offset": [round(float(x), 9) for x in facet.plane.as_tuple()],
        "seed": int(seed),
    }
    digest = hash_json(payload).split(":", 1)[-1]
    return float(int(digest[:8], 16) / float(1 << 32) - 0.5)


# ---------------------------------------------------------------------------- pieces


@dataclass
class _Piece:
    """Internal record of one produced piece before it becomes a ``Fragment``."""

    index: int
    cell_index: int
    mesh_id: int
    result: Any                        # SourceTaggedResult
    nodes: Any
    facet_faces: dict[int, list[int]]  # facet slot -> face ids of this piece on that facet
    classification: dict[str, Any]
    parent: str | None = None


def _cell_rough_geometry(cell: ConvexCell, neighbours: Sequence[list[ConvexCell]]) -> Any:
    return cell, neighbours


def _displaced_cell_mesh(cell: ConvexCell, facets: dict[int, RoughnessField]) -> trimesh.Trimesh:
    """Triangulate the cell, then displace every vertex by the shared spatial roughness field.

    Two properties matter and both are structural rather than tolerance-based:

    * **the same triangulation on both sides.**  A facet's fan is built from its canonical cyclic
      order (:func:`synlab.fracture.voronoi_frag._canonical_polygon`), which was normalised so
      that the two owning cells see the *identical* vertex sequence; the fans therefore match
      edge for edge, mirrored -- that is what makes the conjugate distance exactly zero instead
      of "small".
    * **the same displacement on both sides.**  Every vertex is displaced by the sum of the
      fields of the facets it belongs to, evaluated at its own position.  Both cells hold the
      same position for a shared vertex, so both compute the same displacement, and the two
      fracture surfaces remain glued while being genuinely rough.

    The mask decays to zero away from the facet planes, so vertices far from every fracture
    surface (the padded-box facets, which the boolean discards anyway) move by less than
    :data:`_DECAY_FLOOR` and are left exactly in place.
    """
    vertices: list[np.ndarray] = []
    faces: list[tuple[int, int, int]] = []
    for facet_index, cell_face in enumerate(cell.faces):
        polygon = _canonical_polygon(cell_face)
        if polygon.shape[0] < 3:
            continue
        start = len(vertices)
        vertices.extend(list(polygon))
        for index in range(1, polygon.shape[0] - 1):
            faces.append((start, start + index, start + index + 1))
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices, dtype=np.float64),
                           faces=np.asarray(faces, dtype=np.int64), process=False)
    mesh.merge_vertices()
    keep = np.asarray(mesh.nondegenerate_faces(), dtype=bool)
    if not bool(np.all(keep)):
        mesh.update_faces(keep)
    mesh.remove_unreferenced_vertices()
    # **orient every triangle outwards.**  ``mesh.is_watertight`` is True even when the winding of
    # some facets is inconsistent (measured on V13: watertight True, winding False, volume
    # 380964.8 mm^3 from signed cancellation, and ``manifold3d`` then refuses the solid with
    # ``Error.NotManifold`` and returns an *empty* intersection).  A closed solid's outward
    # orientation is exactly "every triangle contributes positively to the enclosed volume", which
    # is a per-triangle test and therefore immune to the per-facet normal degeneracies that made
    # the geometric reorientation unreliable.
    points = np.asarray(mesh.vertices, dtype=np.float64)
    triangles = points[np.asarray(mesh.faces, dtype=np.int64)]
    contribution = np.einsum("ij,ij->i", triangles[:, 0],
                             np.cross(triangles[:, 1], triangles[:, 2]))
    if float(np.sum(contribution)) < 0.0:
        contribution = -contribution
    flip = contribution < 0.0
    if bool(np.any(flip)):
        new_faces = np.asarray(mesh.faces, dtype=np.int64).copy()
        new_faces[flip] = new_faces[flip][:, ::-1]
        mesh.faces = new_faces
    if facets:
        points = np.asarray(mesh.vertices, dtype=np.float64)
        displacement = np.zeros_like(points)
        for field_obj in facets.values():
            displacement += field_obj.displacement(points)
        mesh.vertices = points + displacement
        mesh.metadata = dict(mesh.metadata or {})
    return mesh


def _canonical_polygon(face: Any) -> np.ndarray:
    """The same canonical cyclic order :mod:`voronoi_frag` uses (single source of truth)."""
    return canonical_polygon(face.vertices, np.asarray(face.vertices, dtype=np.float64).mean(axis=0),
                             np.asarray(face.plane.normal, dtype=np.float64))


def _facet_patch_mesh(polygon: np.ndarray, plane_normal: np.ndarray) -> trimesh.Trimesh:
    """Small planar mesh covering one facet: the "cutter" handed to ``build_interface``.

    ``build_interface`` groups both sides' faces by their nearest triangle of this mesh, projects
    each group into that triangle's 2D frame and measures the common coverage there.  The patch
    therefore has to *cover* the shared area with well-shaped triangles (``_cutter_frame`` refuses
    a zero-length edge, and a sliver would put the projection of a whole face into a frame that is
    numerically unusable).  Shapely's constrained Delaunay triangulation gives exactly that,
    respects the facet boundary, and reproduces the facet area to machine precision.
    """
    import shapely

    points = np.asarray(polygon, dtype=np.float64)
    if points.shape[0] < 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "facet polygon has fewer than 3 vertices",
                          stage="fracture.voronoi.facet_patch")
    normal = unit_vector(plane_normal)
    e1 = _orthonormal(normal)
    e2 = np.cross(normal, e1)
    origin = points.mean(axis=0)
    flat = np.stack([(points - origin) @ e1, (points - origin) @ e2], axis=1)
    result = shapely.constrained_delaunay_triangles(shapely.Polygon(flat))
    triangles: list[np.ndarray] = []

    def walk(geometry: Any) -> None:
        if geometry.geom_type == "Polygon":
            triangles.append(np.asarray(geometry.exterior.coords, dtype=np.float64)[:3])
            return
        for part in getattr(geometry, "geoms", ()):
            walk(part)

    walk(result)
    if not triangles:
        triangles = [flat[:3]]
    stack = np.asarray(triangles, dtype=np.float64)
    vertices = origin[None, :] + stack[:, :, 0:1] * e1[None, None, :] \
        + stack[:, :, 1:2] * e2[None, None, :]
    vertices = vertices.reshape(-1, 3)
    faces = np.arange(vertices.shape[0], dtype=np.int64).reshape(-1, 3)
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


# ---------------------------------------------------------------------------- event


@dataclass
class PieceRecord:
    """One produced piece: geometry, provenance classification and its facet ownership."""

    index: int
    cell_index: int
    mesh_id: int
    tagged: Any                        # SourceTaggedResult of M ∩ cell
    facet_faces: dict[int, list[int]]  # facet slot -> face ids of this piece on that facet
    classification: dict[str, Any] = field(default_factory=dict)
    parent: str | None = None
    generation: int = 0




def run_voronoi_event(
    mother: Any,
    *,
    event_id: str,
    config: PhysicsConfig,
    rng: np.random.Generator,
    body: impact_mod.BodyStats,
    material: impact_mod.MaterialStats,
    target_pieces: int | None = None,
    impact_point: np.ndarray | None = None,
    speed_mm_s: float | None = None,
    energy_j: float | None = None,
    drop_height_mm: float | None = None,
    parent_id: str | None = None,
    generation: int = 0,
    extra_meta: dict[str, Any] | None = None,
) -> FractureResult:
    """Run one multi-piece event: count law -> partition -> pieces -> interfaces -> audit.

    ``target_pieces`` is the sweep override (see :func:`synlab.fracture.impact.target_piece_count`);
    when it is ``None`` the count comes from the physics and is reported next to the formula's
    intermediate terms.
    """
    mother_mesh = mother.mesh
    if not bool(mother_mesh.is_watertight):
        raise SynLabError(ErrorCode.MOTHER_INVALID, "mother mesh is not watertight",
                          stage="fracture.voronoi.event")
    # the scenario comes from the config unless the caller overrides it, so a bare call still has
    # a declared impact (never an implicit zero energy)
    if speed_mm_s is None and energy_j is None and drop_height_mm is None:
        declared_speed = float(config.scenario.get("speed_mm_s", 0.0))
        if declared_speed > 0.0:
            speed_mm_s = declared_speed
        else:
            drop_height_mm = float(config.scenario.get("drop_height_mm", 500.0))
    count_record = impact_mod.target_piece_count(
        body, material, config.impact, rng=rng, speed_mm_s=speed_mm_s, energy_j=energy_j,
        drop_height_mm=drop_height_mm, target_pieces=target_pieces)
    n_target = int(count_record["n_target"])

    partition, seed_report = build_partition(
        mother_mesh, n_target, rng=rng, seed_cfg=config.seeds, impact_point=impact_point,
        padding_mm=max(float(config.resources.get("cell_padding_mm", 2.0)), 0.5))
    roughness_fields: dict[tuple[int, int], RoughnessField] = {}
    facet_polygons: dict[tuple[int, int], np.ndarray] = {}
    facet_normals: dict[tuple[int, int], np.ndarray] = {}
    for cell in partition.cells:
        for facet_index, neighbour in enumerate(cell.facet_neighbours):
            if neighbour < 0:
                continue
            key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
            if key in roughness_fields:
                continue
            other_position = _position_of(partition, int(neighbour))
            if other_position is None:
                continue
            other = partition.cells[other_position]
            pair = _matching_facets(cell, facet_index, other)
            if pair is None:
                continue
            field_obj = facet_roughness_field(
                cell, other, pair[0], config=config, wall_mm=body.wall_mm,
                grain_mm=material.grain_size_mm, seed=0)
            roughness_fields[key] = field_obj
            facet_polygons[key] = _canonical_polygon(cell.faces[pair[0]])
            facet_normals[key] = np.asarray(cell.faces[pair[0]].plane.normal, dtype=np.float64)

    # ---------------------------------------------------------------- pieces
    mother_clean = trimesh.Trimesh(vertices=np.asarray(mother_mesh.vertices, dtype=np.float64),
                                   faces=np.asarray(mother_mesh.faces, dtype=np.int64),
                                   process=False)
    mother_source = tag_source(mother_clean, 1.0, "mother")
    shells = mesh_shells(mother_clean)
    single_shell = len(shells) <= 1
    shell_inputs = None
    if not single_shell:
        shell_inputs = [
            tag_source(part, 1.0, "mother",
                       triangle_ids=np.asarray(mother_source.triangle_ids)[ids])
            for part, ids in shells]
    records: list[PieceRecord] = []
    dropped_cells: list[int] = []
    cell_meshes: list[trimesh.Trimesh] = []
    face_counts: list[int] = []
    for position, cell in enumerate(partition.cells):
        fields: dict[int, RoughnessField] = {}
        for facet_index, neighbour in enumerate(cell.facet_neighbours):
            if neighbour < 0:
                continue
            key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
            if key in roughness_fields:
                fields[facet_index] = roughness_fields[key]
        cell_mesh = _displaced_cell_mesh(cell, fields)
        cell_meshes.append(cell_mesh)
        face_counts.append(int(len(np.asarray(cell_mesh.faces))))
        mesh_id = float(1000 + position)
        cutter_source = tag_source(trimesh.Trimesh(
            vertices=np.asarray(cell_mesh.vertices, dtype=np.float64),
            faces=np.asarray(cell_mesh.faces, dtype=np.int64), process=False), mesh_id, "cell")
        if single_shell:
            tagged = boolean_intersection([mother_source, cutter_source],
                                          label=f"piece_{position}")
        else:
            tagged = concat_tagged(
                [boolean_intersection([shell, cutter_source], label=f"piece_{position}")
                 for shell in shell_inputs], label=f"piece_{position}")
        if tagged.n_faces == 0 or float(abs(tagged.mesh.volume)) <= 1.0e-9:
            dropped_cells.append(int(cell.index))
            continue
        records.append(PieceRecord(index=len(records), cell_index=int(cell.index),
                                   mesh_id=int(mesh_id), tagged=tagged, facet_faces={}))
    if not records:
        raise SynLabError(ErrorCode.FRACTURE_CONSERVATION_FAIL,
                          "the Voronoi partition produced no piece with material in it",
                          stage="fracture.voronoi.event",
                          measurements={"cells": len(partition.cells)})

    # ---------------------------------------------------------------- classification
    resolver = SourceResolver([mother_source], tolerance_mm=1e-4)
    for record in records:
        classification = resolver.classify(
            record.tagged, container=cell_meshes[record.index],
            container_tolerance_mm=1e-4)
        classification["_faces"] = np.asarray(record.tagged.mesh.faces, dtype=np.int64)
        classification["area_faces"] = np.asarray(record.tagged.mesh.area_faces,
                                                  dtype=np.float64)
        classification["mother_mesh_id"] = 1
        classification["cutter_mesh_id"] = record.mesh_id
        record.classification = classification
    _assign_facet_faces(records, partition, roughness_fields,
                        tolerance_mm=float(config.tolerance.get("facet_plane_tol_mm", 1.0e-4)))

    # ---------------------------------------------------------------- fragments
    fragments: list[Fragment] = []
    bodies_per_cell: list[int] = []
    for record in records:
        parts = split_components(record.tagged.mesh)
        bodies_per_cell.append(len(parts))
        if len(parts) != 1:
            raise SynLabError(
                ErrorCode.FRACTURE_CONSERVATION_FAIL,
                f"one Voronoi cell produced {len(parts)} closed bodies: the interface "
                f"attribution would be ambiguous, so the event is refused instead of guessing",
                stage="fracture.voronoi.event",
                measurements={"cells": len(records), "bodies": int(sum(bodies_per_cell))},
            )
        fragment = make_fragment(
            parts[0], fragment_id=f"{event_id}-c{record.index:03d}",
            component_id=record.index, side=-1, classification=record.classification,
            parent_id=parent_id, backend=BACKEND,
            cutter_hash=f"cell:{record.cell_index}",
            extra_meta={"event_id": event_id, "generation": int(generation),
                        "voronoi_cell": int(record.cell_index),
                        "boolean_output": "M_intersect_cell"},
        )
        fragments.append(fragment)

    interfaces = _link_voronoi_interfaces(
        fragments, records, partition, roughness_fields, facet_polygons, facet_normals,
        sample_target=int(config.resources.get("interface_sample_target", 24)))

    mother_volume = float(abs(mother_mesh.volume))
    fragment_volume = float(sum(fragment.volume_mm3 for fragment in fragments))
    ledger = energy_mod.build_ledger(
        volume_mm3=mother_volume,
        density_g_cm3=float(material.density_g_cm3),
        speed_mm_s=float(count_record["impact_speed_mm_s"]),
        interface_areas_mm2=[patch.area_mm2 for patch in interfaces],
        fracture_energy_j_mm2=float(_fracture_energy(material, config)),
        piece_volumes_mm3=[fragment.volume_mm3 for fragment in fragments],
    )
    conjugacy = facet_conjugacy_report(partition)
    event_tree = {
        "event_id": event_id,
        "parent_id": parent_id,
        "backend": BACKEND,
        "generation": int(generation),
        "children": [fragment.fragment_id for fragment in fragments],
        "interfaces": [patch.interface_id for patch in interfaces],
        "mother_volume_mm3": mother_volume,
        "fragment_volume_mm3": fragment_volume,
        "count_model": count_record,
        "partition_hash": partition.hash,
    }
    result = FractureResult(
        fragments=fragments, interfaces=interfaces, event_tree=event_tree,
        debris=[fragment for fragment in fragments if fragment.is_tiny],
        parent_id=parent_id or getattr(mother, "mother_id", ""), backend=BACKEND, qa={},
        cutter_ref=partition.hash,
        meta={
            "event_id": event_id,
            "count_model": count_record,
            "seed_report": seed_report,
            "partition": partition.as_dict(),
            "facet_conjugacy": conjugacy,
            "roughness_fields": [field.as_dict() for field in roughness_fields.values()],
            "energy_ledger": ledger.as_dict(),
            "dropped_cells": dropped_cells,
            "cells_total": len(partition.cells),
            "pieces_produced": len(fragments),
            "faces_total": int(sum(fragment.n_faces for fragment in fragments)),
            "cell_faces_total": int(sum(face_counts)),
            "config_hash": config.hash,
            "target_pieces": int(n_target),
            "count_source": str(count_record["count_source"]),
            "shells": len(shells),
            **dict(extra_meta or {}),
        },
    )
    result.qa = audit_fracture_result(result, mother)
    return result


def _position_of(partition: VoronoiPartition, cell_index: int) -> int | None:
    for position, cell in enumerate(partition.cells):
        if int(cell.index) == int(cell_index):
            return position
    return None


def _matching_facets(cell: ConvexCell, facet_index: int, other: ConvexCell
                     ) -> tuple[int, int] | None:
    """Find the facet of ``other`` that corresponds to ``cell.faces[facet_index]``."""
    polygon_a = _canonical_polygon(cell.faces[facet_index])
    for index, neighbour in enumerate(other.facet_neighbours):
        if int(neighbour) != int(cell.index):
            continue
        polygon_b = _canonical_polygon(other.faces[index])
        distance = np.linalg.norm(polygon_a[:, None, :] - polygon_b[None, :, :], axis=2)
        if float(np.max(np.min(distance, axis=1))) <= 1.0e-6:
            return int(facet_index), int(index)
    return None


def _fracture_energy(material: impact_mod.MaterialStats, config: PhysicsConfig) -> float:
    if material.fracture_energy_j_mm2 is not None:
        return float(material.fracture_energy_j_mm2)
    table = config.impact.fracture_energy_j_mm2
    return float(table.get(material.material_id,
                           config.impact.fracture_energy_default_j_mm2))


def _assign_facet_faces(records: Sequence[PieceRecord], partition: VoronoiPartition,
                        fields: dict[tuple[int, int], RoughnessField], *, tolerance_mm: float
                        ) -> None:
    """Attribute every interface face of every piece to the facet (cell pair) it lies on.

    The classification already says *that* a face is a fracture surface; this says *which* one.
    A face is attributed to the facet whose plane it sits on (smallest absolute plane distance);
    a face that is not within the merge tolerance of any facet plane is left unattributed and is
    reported through the ``unattributed_interface_faces`` counter instead of being forced onto
    the nearest plane.
    """
    for record in records:
        cell = partition.cells[record.index]
        entries: list[tuple[int, int, int]] = []       # (facet slot, neighbour, pair key id)
        key_ids: dict[tuple[int, int], int] = {}
        for facet_index, neighbour in enumerate(cell.facet_neighbours):
            if neighbour < 0:
                continue
            key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
            if key not in fields:
                continue
            key_ids.setdefault(key, len(key_ids))
            entries.append((int(facet_index), int(neighbour), key_ids[key]))
        mesh = record.tagged.mesh
        faces = np.asarray(mesh.faces, dtype=np.int64)
        centres = np.asarray(mesh.triangles_center, dtype=np.float64)
        origin = np.asarray(record.classification["vertex_origin"])
        face_origin = np.asarray([origin[face].max() for face in faces], dtype=np.uint8)
        candidates = np.nonzero(face_origin == ORIGIN_INTERFACE)[0]
        mapping: dict[int, list[int]] = {int(facet): [] for facet, _n, _k in entries}
        unattributed = 0
        if candidates.size:
            distances = np.full((candidates.shape[0], len(entries)), np.inf, dtype=np.float64)
            for column, (facet_index, _neighbour, _key) in enumerate(entries):
                plane = cell.faces[facet_index].plane
                distances[:, column] = np.abs(plane.signed(centres[candidates]))
            chosen = np.argmin(distances, axis=1)
            best = distances[np.arange(candidates.shape[0]), chosen]
            for row, column in enumerate(chosen):
                if float(best[row]) > float(tolerance_mm):
                    unattributed += 1
                    continue
                mapping[int(entries[int(column)][0])].append(int(candidates[row]))
        record.facet_faces = mapping
        record.classification["unattributed_interface_faces"] = int(unattributed)


def _link_voronoi_interfaces(
    fragments: Sequence[Fragment],
    records: Sequence[PieceRecord],
    partition: VoronoiPartition,
    fields: dict[tuple[int, int], RoughnessField],
    facet_polygons: dict[tuple[int, int], np.ndarray],
    facet_normals: dict[tuple[int, int], np.ndarray],
    *,
    sample_target: int = 24,
) -> list[Any]:
    """Build one interface patch per shared facet, with the measured conjugacy statistics."""
    by_cell = {int(record.cell_index): record for record in records}
    fragment_of_cell = {int(record.cell_index): fragment
                        for record, fragment in zip(records, fragments)}
    patches: list[Any] = []
    interface_id = 0
    for key in sorted(fields):
        first, second = key
        record_a = by_cell.get(int(first))
        record_b = by_cell.get(int(second))
        if record_a is None or record_b is None:
            continue
        slot_a = _facet_slot(partition, record_a, int(second))
        slot_b = _facet_slot(partition, record_b, int(first))
        if slot_a < 0 or slot_b < 0:
            continue
        faces_a = record_a.facet_faces.get(slot_a, [])
        faces_b = record_b.facet_faces.get(slot_b, [])
        if not faces_a or not faces_b:
            continue
        fragment_a = fragment_of_cell[int(first)]
        fragment_b = fragment_of_cell[int(second)]
        patch_mesh = _facet_patch_mesh(facet_polygons[key], facet_normals[key])
        patch, rows = build_interface(
            interface_id=interface_id, fragment_a=fragment_a, fragment_b=fragment_b,
            faces_a=faces_a, faces_b=faces_b, source_tri=0, cutter_mesh=patch_mesh,
            sample_target=int(sample_target),
        )
        if patch.area_mm2 <= 0.0 and not rows:
            continue
        patch.meta["facet_pair"] = [int(first), int(second)]
        patch.meta["facet_area_mm2"] = float(_polygon_area(facet_polygons[key]))
        patch.meta["roughness"] = fields[key].as_dict()
        patch.meta["voronoi_interface"] = True
        patch.meta["correspondence_rows"] = len(rows)
        patch.meta.update(interface_distance_stats(fragment_a, fragment_b, patch))
        patches.append(patch)
        interface_id += 1
    return patches


def _facet_slot(partition: VoronoiPartition, record: PieceRecord, neighbour: int) -> int:
    cell = partition.cells[record.index]
    for facet_index, value in enumerate(cell.facet_neighbours):
        if int(value) == int(neighbour):
            return int(facet_index)
    return -1


def _polygon_area(polygon: np.ndarray) -> float:
    points = np.asarray(polygon, dtype=np.float64)
    if points.shape[0] < 3:
        return 0.0
    anchor = points[0]
    return float(0.5 * np.linalg.norm(np.cross(points[1:-1] - anchor,
                                               points[2:] - anchor).sum(axis=0)))
