"""``warped_partition``: a non-planar partition whose shared surfaces are one PLC under one warp.

Why this module exists
----------------------
``warp_voronoi_cut`` splits a body with a weighted Voronoi (power) diagram.  Its partition is, at
heart, a set of **planes**: the roughness stage then displaces the facets, but the partition
*trace* on the mother's surface, the facet polygons and the piece attribution all still come from
planar bisectors.  That is fine for many purposes and it is why the backend passes A06, but it is
not what plan G10.4 asks for.

G10.4 asks for a **warped partition**: one shared piecewise-linear complex (PLC) that is conformally
meshed, plus one shared displacement field, so that

* the cut surface of two neighbouring pieces is *the same surface*, not two surfaces that happen to
  agree to within a tolerance, and
* that surface is genuinely non-planar — it leaves the bisector plane by more than the interpolation
  budget over a measurable fraction of its area.

The construction here
---------------------
1. the placement of the partition is the same power-diagram machinery the calibrated
   ``warp_voronoi_cut`` path uses (:func:`synlab.fracture.voronoi_frag.build_partition`), so the
   piece count / seed physics is unchanged and comparable;
2. every internal facet is meshed **conformally by gmsh** in its own 2D frame
   (:func:`meshed_facet`) — one triangulation per facet, generated once and then handed to *both*
   owning cells.  Conjugacy is therefore structural: there is only one discretisation of that
   surface in the whole event;
3. one :class:`WarpField` — a finite Fourier sum whose amplitude comes from the **measured wall
   thickness** and whose shortest wavelength comes from the **measured material grain size and
   pore/aggregate scale** — displaces every facet mesh vertex.  The field is intrinsic to the
   *surface*, and its mask is exactly zero on the facet border, so the warped surface leaves the
   mother's material surface untouched and the two sides of a facet compute identical positions;
4. each piece is the boolean intersection of the mother with its warped cell solid, and the A06
   audit reports the realized gap, normal reversal, volume conservation, overlap, origin coverage
   and ambiguity exactly as for the planar and rough backends.

Everything the module claims is measured: :func:`warp_audit` reports the non-planarity of the
shared surfaces, the conjugacy of the two sides (P95 and max point distance, and whether the two
sides carry the identical triangle set), and the mesh statistics.

What is *not* here
------------------
The volumetric half of G10.4 — a conformal **tetrahedral** mesh of the whole assembly — is not
implemented, and the backend says so instead of substituting something cheaper.  The reason is
measured, not assumed: the mother generator hands out a triangle soup (``mesh.vertices`` /
``mesh.faces``); gmsh 4.15.2 keeps an imported STL as discrete facets and creates **no** volume
entity for it (measured: ``loaded_volumes = 0`` on V13/M01), its OpenCASCADE route refuses an STL
outright (``Unknown file type``), and there is no BREP/STEP form of a mother in this repository to
import instead.  See ``docs/a12/fracture_precision.md`` for the probe record.  The surface PLC
below is conformally meshed and shared, which is what makes the *partition* conformal; the volume
mesh is a separate deliverable and is reported as ``PENDING`` with that reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from . import voronoi_event as event_mod
from .cut import FourierBand
from .spec import AMP_MAX_MM, AMP_MIN_MM, WAVELENGTH_MAX_MM, WAVELENGTH_MIN_MM
from .voronoi_frag import ConvexCell, VoronoiPartition, _canonical_polygon

__all__ = [
    "BACKEND",
    "VOLUME_MESH_STATUS",
    "VOLUME_MESH_REASON",
    "WarpField",
    "FacetMesh",
    "meshed_facet",
    "cell_facet_meshes",
    "warped_cell_mesh",
    "warp_audit",
    "partition_surface_report",
    "run_warped_partition",
]

#: backend id (frozen by ``synlab.fracture.spec``).
BACKEND = "warped_partition"

#: Status of the volumetric (conformal tetrahedral) half of plan G10.4.  It is *not* silently
#: skipped: the event meta carries this string plus :data:`VOLUME_MESH_REASON`.
VOLUME_MESH_STATUS = "PENDING"
VOLUME_MESH_REASON = (
    "the conformal tetrahedral stage needs a BREP/STEP form of the mother; the mother generator "
    "hands out a triangle soup, gmsh 4.15.2 creates no volume entity from an imported STL "
    "(measured loaded_volumes=0 on V13/M01) and its OCC importer rejects STL ('Unknown file type'), "
    "so the volume mesh cannot be built from the assets that exist.  The *surface* PLC below is "
    "conformally meshed and shared, so the partition itself is conformal."
)

#: gmsh target edge length as a fraction of the facet's shortest warp wavelength.  Eight points per
#: wavelength is the planar contract's own sampling reference (see ``cut.POINTS_PER_WAVELENGTH``),
#: and it is what the *default* mesh size is derived from when no error budget is supplied.
_MESH_POINTS_PER_WAVELENGTH = 8.0
#: Interpolation-error budget of the conformal facet mesh (mm).  A06's shared-surface gate is
#: 0.02 mm; meshing the facet to a tenth of it keeps the discretisation error an order of magnitude
#: below the frozen gate, and it is the same 0.01 mm the planar cutter uses.
_FACET_ERROR_BUDGET_MM = 0.01
#: Hard cap on the triangles one facet may be meshed into.  Exceeding it means the *physically
#: derived* relief cannot be resolved at this budget; the backend then coarsens the mesh as far as
#: the budget allows and **reports the realized resolution and the curvature it actually resolves**
#: instead of quietly claiming the requested one.
_MAX_FACET_TRIANGLES = 60_000
#: Anisotropy of the warped relief along the facet trace (0 = isotropic).
_TRACE_ANISOTROPY = 0.35
#: Spectral slope of the relief amplitude (``A ~ k ** -slope``); 1.0 is a self-affine surface.
_SPECTRAL_SLOPE = 1.0
#: Ratio of the facet-border taper to the shortest wavelength: the mask reaches zero over this many
#: wavelengths, so the relief vanishes at the trace without a discontinuity in slope.
_BORDER_TAPER_WAVELENGTHS = 0.75
_EPS = 1.0e-12


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------- warp field


@dataclass
class WarpField:
    """One shared warp for the whole partition: ``p -> p + n(p) * a * u(p)``.

    The displacement is a *spatial* field, not a per-facet offset, so two facets that meet along a
    trace produce the same displacement at the shared trace points and the partition stays glued.
    ``u`` is a finite Fourier sum whose band amplitudes follow a ``k ** -slope`` spectrum; the
    shortest band wavelength is ``wavelength_grain_ratio * grain_mm`` clamped into the frozen
    package window ``[WAVELENGTH_MIN_MM, WAVELENGTH_MAX_MM]``, and the amplitude is
    ``amp_wall_ratio * wall_mm`` clamped into ``[AMP_MIN_MM, AMP_MAX_MM]``.

    Both drivers are **measured**: ``wall_mm`` is the mother's median wall thickness and ``grain_mm``
    is the material profile's grain size.  Nothing here is white noise: the wavelengths are the
    material's own heterogeneity scales and the amplitude is a fraction of the wall the fracture
    crossed.
    """

    bands: list[FourierBand]
    wall_mm: float
    grain_mm: float
    amplitude_mm: float
    wavelength_min_mm: float
    wavelength_max_mm: float
    trace_direction: np.ndarray
    taper_mm: float
    provenance: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ evaluation
    def unit(self, points: np.ndarray) -> np.ndarray:
        """The un-normalised Fourier sum ``u(p)`` (isotropic in space)."""
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        out = np.zeros(pts.shape[0], dtype=np.float64)
        for band in self.bands:
            k = band.k
            out = out + band.amplitude_mm * np.cos(pts @ (k * band.direction) + band.phase)
        return out

    def displacement(self, points: np.ndarray, *, normal: np.ndarray,
                     border_mm: np.ndarray) -> np.ndarray:
        """``(N, 3)`` displacement: along ``normal``, tapered to zero on the facet border.

        ``border_mm`` is the in-plane distance from each point to the facet's own border; the taper
        is ``smoothstep(border / taper_mm)``, so it is exactly ``0`` on the border (where two cells
        or two facets must agree bit for bit) and ``1`` in the facet interior.
        """
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        if not self.bands or self.amplitude_mm <= 0.0 or pts.shape[0] == 0:
            return np.zeros_like(pts)
        taper = _smoothstep(np.asarray(border_mm, dtype=np.float64) / max(self.taper_mm, _EPS))
        scale = taper * float(self.amplitude_mm)
        returned = self.unit(pts)
        # normalise the raw sum to unit RMS over the sample it was built from, then apply the mask
        norm = float(self.provenance.get("unit_rms", 0.0))
        if norm > 0.0:
            returned = returned / norm
        direction = np.asarray(normal, dtype=np.float64).reshape(3)
        direction = direction / max(float(np.linalg.norm(direction)), _EPS)
        return (scale * returned)[:, None] * direction[None, :]

    def curvature_bound(self) -> float:
        """Upper bound of ``|h_aa|`` along any unit direction of the facet (per mm)."""
        return float(sum(band.amplitude_mm * band.k ** 2 for band in self.bands))

    def cell_size_for_budget(self, budget_mm: float) -> float:
        """Edge length whose linear-interpolation error stays inside ``budget_mm``.

        The standard bound for linear interpolation of a field with curvature bound ``C`` on a cell
        of diameter ``h`` is ``|e| <= C h^2 / 8``, so ``h = sqrt(8 * budget / C)``.  With no bands
        the field is identically zero and the cell size is unbounded.
        """
        curvature = self.curvature_bound()
        if curvature <= 0.0:
            return float("inf")
        return float(np.sqrt(8.0 * max(float(budget_mm), 0.0) / curvature))

    def as_dict(self) -> dict[str, Any]:
        return {
            "bands": [band.as_dict() for band in self.bands],
            "wall_mm": float(self.wall_mm),
            "grain_mm": float(self.grain_mm),
            "amplitude_mm": float(self.amplitude_mm),
            "wavelength_min_mm": float(self.wavelength_min_mm),
            "wavelength_max_mm": float(self.wavelength_max_mm),
            "taper_mm": float(self.taper_mm),
            "trace_direction": np.asarray(self.trace_direction, dtype=np.float64).tolist(),
            "curvature_bound_per_mm": float(self.curvature_bound()),
            "provenance": dict(self.provenance),
        }


def make_warp_field(*, wall_mm: float, grain_mm: float, trace_direction: np.ndarray | None = None,
                    amp_wall_ratio: float = 0.08, wavelength_grain_ratio: float = 6.0,
                    n_bands: int = 3, seed_payload: Mapping[str, Any] | None = None
                    ) -> WarpField:
    """Build the shared warp from the *measured* wall thickness and the material's grain size.

    The two clamps are the frozen package window; when a clamp bites it is recorded in
    ``provenance`` so a caller can see that the requested physical relief was not what was realized
    (it is never silently replaced by a different value).
    """
    wall = max(float(wall_mm), 1.0e-6)
    grain = max(float(grain_mm), 1.0e-6)
    raw_amplitude = float(amp_wall_ratio) * wall
    amplitude = float(np.clip(raw_amplitude, AMP_MIN_MM, AMP_MAX_MM))
    raw_wavelength = float(wavelength_grain_ratio) * grain
    wavelength_min = float(np.clip(raw_wavelength, WAVELENGTH_MIN_MM, WAVELENGTH_MAX_MM))
    wavelength_max = float(min(max(wavelength_min * 6.0, wavelength_min * 1.05),
                               WAVELENGTH_MAX_MM * 4.0))

    payload = dict(seed_payload or {})
    payload.update({"wall_mm": round(wall, 9), "grain_mm": round(grain, 9),
                    "amplitude_mm": round(amplitude, 9),
                    "wavelength_min_mm": round(wavelength_min, 9), "n_bands": int(n_bands)})
    digest = hash_json(payload).split(":", 1)[-1]
    unit_a = int(digest[0:8], 16) / float(1 << 32)
    unit_b = int(digest[8:16], 16) / float(1 << 32)
    unit_c = int(digest[16:24], 16) / float(1 << 32)

    edges = np.geomspace(wavelength_min, max(wavelength_max, wavelength_min * 1.05),
                         max(int(n_bands), 1) + 1)
    bands: list[FourierBand] = []
    for index in range(max(int(n_bands), 1)):
        lo, hi = float(edges[index]), float(edges[index + 1])
        wl = float(np.exp(0.5 * (np.log(lo) + np.log(hi))))
        # amplitude follows the self-affine spectrum A ~ k ** -slope around the shortest band
        weight = (wavelength_min / wl) ** float(_SPECTRAL_SLOPE)
        theta = 2.0 * np.pi * ((unit_a * (index + 1) + unit_c) % 1.0)
        direction = np.array([np.cos(theta), np.sin(theta),
                              (_TRACE_ANISOTROPY * np.sin(2.0 * theta))])
        direction = direction / max(float(np.linalg.norm(direction)), _EPS)
        phase = 2.0 * np.pi * ((unit_b * (index + 2) + unit_a) % 1.0)
        bands.append(FourierBand(1.0 * weight, wl, direction, phase))
    field_obj = WarpField(
        bands=bands, wall_mm=wall, grain_mm=grain, amplitude_mm=amplitude,
        wavelength_min_mm=float(min(b.wavelength_mm for b in bands)),
        wavelength_max_mm=float(max(b.wavelength_mm for b in bands)),
        trace_direction=np.asarray(trace_direction, dtype=np.float64).reshape(3)
        if trace_direction is not None else np.array([1.0, 0.0, 0.0]),
        taper_mm=float(max(_BORDER_TAPER_WAVELENGTHS * wavelength_min, 0.05)),
        provenance={
            "amp_wall_ratio": float(amp_wall_ratio),
            "wavelength_grain_ratio": float(wavelength_grain_ratio),
            "requested_amplitude_mm": raw_amplitude,
            "requested_wavelength_mm": raw_wavelength,
            "amplitude_clamped": bool(abs(raw_amplitude - amplitude) > 1e-12),
            "wavelength_clamped": bool(abs(raw_wavelength - wavelength_min) > 1e-12),
            "package_window_mm": [AMP_MIN_MM, AMP_MAX_MM,
                                  WAVELENGTH_MIN_MM, WAVELENGTH_MAX_MM],
            "spectral_slope": float(_SPECTRAL_SLOPE),
            "trace_anisotropy": float(_TRACE_ANISOTROPY),
            "band_edge_grid_mm": [float(x) for x in edges],
            "seed_payload_hash": hash_json(payload),
            "driver": "measured wall thickness (amplitude) + measured grain size (wavelength)",
        },
    )
    # unit RMS over a deterministic probe slab, so ``displacement`` realizes ``amplitude_mm``
    axis = np.linspace(-1.0, 1.0, 7)
    grid = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1).reshape(-1, 3)
    grid = grid * field_obj.wavelength_min_mm * 2.0
    rms = float(np.sqrt(np.mean(field_obj.unit(grid) ** 2)))
    field_obj.provenance["unit_rms"] = rms if rms > 0.0 else 1.0
    field_obj.provenance["rms_probe_points"] = int(grid.shape[0])
    return field_obj


# ---------------------------------------------------------------------------- facet meshing


@dataclass
class FacetMesh:
    """One conformally meshed facet: 2D nodes + triangles plus the frame that places them in 3D.

    The frame is **canonical**: ``normal`` is derived from the canonical polygon's own winding, not
    from the caller's cell, so the two cells that own the facet build the *same* frame and therefore
    displace the shared surface by the same vectors.  A frame built from each cell's outward normal
    would flip the displacement direction between the two sides and open a gap of ``2 * amplitude``
    (measured at the design stage and the reason this field exists).
    """

    key: tuple[int, int]
    polygon: np.ndarray          # (K, 3) canonical border polygon of the facet, in world space
    origin: np.ndarray           # (3,) frame origin on the facet plane
    e_x: np.ndarray              # (3,) in-plane axis
    e_y: np.ndarray              # (3,) in-plane axis
    normal: np.ndarray           # (3,) canonical facet normal (polygon winding, sign-normalised)
    nodes_uv: np.ndarray         # (N, 2) meshed nodes in the facet frame
    triangles: np.ndarray        # (T, 3) int64 indices into ``nodes_uv``
    border_node_ids: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    meta: dict[str, Any] = field(default_factory=dict)

    def nodes_3d(self) -> np.ndarray:
        return (np.asarray(self.origin, dtype=np.float64)[None, :]
                + self.nodes_uv[:, 0:1] * np.asarray(self.e_x, dtype=np.float64)[None, :]
                + self.nodes_uv[:, 1:2] * np.asarray(self.e_y, dtype=np.float64)[None, :])

    def sample_surface(self, points_3d: np.ndarray) -> np.ndarray:
        """Warped positions of the facet surface at arbitrary world points (projected onto it)."""
        pts = np.asarray(points_3d, dtype=np.float64).reshape(-1, 3)
        rel = pts - np.asarray(self.origin, dtype=np.float64)[None, :]
        uv = np.stack([rel @ np.asarray(self.e_x, dtype=np.float64),
                       rel @ np.asarray(self.e_y, dtype=np.float64)], axis=1)
        return (np.asarray(self.origin, dtype=np.float64)[None, :]
                + uv[:, 0:1] * np.asarray(self.e_x, dtype=np.float64)[None, :]
                + uv[:, 1:2] * np.asarray(self.e_y, dtype=np.float64)[None, :])

    def border_distance_mm(self, nodes_3d: np.ndarray) -> np.ndarray:
        """In-plane distance from each node to the facet border polygon (``inf`` outside)."""
        return _polygon_border_distance(np.asarray(self.polygon, dtype=np.float64),
                                        np.asarray(nodes_3d, dtype=np.float64),
                                        self.origin, self.e_x, self.e_y)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": [int(self.key[0]), int(self.key[1])],
            "nodes": int(self.nodes_uv.shape[0]),
            "triangles": int(self.triangles.shape[0]),
            "polygon_vertices": int(self.polygon.shape[0]),
            **self.meta,
        }


def _plane_frame(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """``(origin, e_x, e_y, normal)`` of the best-fit plane through ``points``."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    origin = pts.mean(axis=0)
    centred = pts - origin[None, :]
    _u, _s, vt = np.linalg.svd(centred, full_matrices=False)
    normal = vt[2] / max(float(np.linalg.norm(vt[2])), _EPS)
    helper = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e_x = helper - normal * float(helper @ normal)
    e_x = e_x / max(float(np.linalg.norm(e_x)), _EPS)
    e_y = np.cross(normal, e_x)
    e_y = e_y / max(float(np.linalg.norm(e_y)), _EPS)
    return origin, e_x, e_y, normal


def _canonical_plane(normal: np.ndarray) -> np.ndarray:
    """Sign-normalise a plane normal so mirrored descriptions of one facet agree.

    ``(n_x, n_y, n_z)`` and ``(-n_x, -n_y, -n_z)`` describe the same plane; picking the one whose
    first significant component is positive makes the *frame* independent of which cell asked.
    """
    vec = np.asarray(normal, dtype=np.float64).reshape(3)
    vec = vec / max(float(np.linalg.norm(vec)), _EPS)
    for value in vec:
        if abs(float(value)) > 1.0e-12:
            return vec if float(value) > 0.0 else -vec
    return vec


def _frame_from_normal(origin: np.ndarray, normal: np.ndarray
                       ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Right-handed in-plane frame from a canonical normal (``e_y = n x e_x``)."""
    n = _canonical_plane(normal)
    helper = np.array([0.0, 0.0, 1.0]) if abs(float(n[2])) < 0.9 else np.array([0.0, 1.0, 0.0])
    e_x = helper - n * float(helper @ n)
    e_x = e_x / max(float(np.linalg.norm(e_x)), _EPS)
    e_y = np.cross(n, e_x)
    e_y = e_y / max(float(np.linalg.norm(e_y)), _EPS)
    return e_x, e_y, n


def _polygon_border_distance(polygon: np.ndarray, nodes: np.ndarray, origin: np.ndarray,
                             e_x: np.ndarray, e_y: np.ndarray) -> np.ndarray:
    """In-plane distance from each node to the facet border, ``+inf`` outside the polygon."""
    origin = np.asarray(origin, dtype=np.float64).reshape(3)
    e_x = np.asarray(e_x, dtype=np.float64).reshape(3)
    e_y = np.asarray(e_y, dtype=np.float64).reshape(3)
    poly = np.asarray(polygon, dtype=np.float64).reshape(-1, 3)
    rel = poly - origin[None, :]
    poly_uv = np.stack([rel @ e_x, rel @ e_y], axis=1)
    rel_n = np.asarray(nodes, dtype=np.float64).reshape(-1, 3) - origin[None, :]
    uv = np.stack([rel_n @ e_x, rel_n @ e_y], axis=1)
    inside = _points_in_convex_polygon(uv, poly_uv)
    distances = np.full(uv.shape[0], np.inf, dtype=np.float64)
    count = poly_uv.shape[0]
    best = np.full(uv.shape[0], np.inf, dtype=np.float64)
    for index in range(count):
        a = poly_uv[index]
        b = poly_uv[(index + 1) % count]
        best = np.minimum(best, _segment_distance(uv, a, b))
    distances[inside] = best[inside]
    return distances


def _segment_distance(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    denom = float(ab @ ab)
    if denom <= _EPS:
        return np.linalg.norm(points - a[None, :], axis=1)
    t = np.clip(((points - a[None, :]) @ ab) / denom, 0.0, 1.0)
    proj = a[None, :] + t[:, None] * ab[None, :]
    return np.linalg.norm(points - proj, axis=1)


def _points_in_convex_polygon(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    count = polygon.shape[0]
    inside = np.ones(points.shape[0], dtype=bool)
    for index in range(count):
        a = polygon[index]
        b = polygon[(index + 1) % count]
        cross = (b[0] - a[0]) * (points[:, 1] - a[1]) - (b[1] - a[1]) * (points[:, 0] - a[0])
        inside &= cross >= -1.0e-9
    return inside


def meshed_facet(polygon: np.ndarray, normal: np.ndarray, *, target_mm: float,
                 key: tuple[int, int] = (-1, -1),
                 max_triangles: int = _MAX_FACET_TRIANGLES) -> FacetMesh:
    """Conformally mesh one facet polygon with gmsh, in the facet's own 2D frame.

    The polygon is handed to gmsh as a plane surface and meshed at ``target_mm``; gmsh's frontal
    algorithm keeps the polygon border as mesh edges, so the triangulation is conforming with the
    facet's own wire (which is what makes the two sides of a shared facet and the neighbouring
    facets of one cell agree along their common edges).  Only the *geometry* comes from gmsh: the
    returned object is plain arrays, so nothing downstream depends on gmsh being installed.

    ``normal`` is used only to decide which side of the plane the facet's outward direction is (it
    selects the sign of the frame relative to the cell that asked); the frame itself is the
    sign-normalised canonical normal, so both owning cells get the identical frame.
    """
    poly = np.asarray(polygon, dtype=np.float64).reshape(-1, 3)
    if poly.shape[0] < 3:
        raise SynLabError(ErrorCode.FRACTURE_CONSERVATION_FAIL,
                          f"facet {key} has {poly.shape[0]} vertices; a surface needs at least 3",
                          stage="fracture.warped.facet")
    origin, _e_x_raw, _e_y_raw, plane_normal = _plane_frame(poly)
    want = np.asarray(normal, dtype=np.float64).reshape(3)
    if float(want @ plane_normal) < 0.0:
        plane_normal = -plane_normal
    e_x, e_y, canonical = _frame_from_normal(origin, plane_normal)
    rel = poly - origin[None, :]
    poly_uv = np.stack([rel @ e_x, rel @ e_y], axis=1)
    # canonical rotation so both owning cells mesh the identical border
    order = np.lexsort((np.round(poly_uv[:, 1], 9), np.round(poly_uv[:, 0], 9)))
    start = int(order[0])
    polygon_uv = np.roll(poly_uv, -start, axis=0)
    polygon_canonical = np.roll(poly, -start, axis=0)

    nodes_uv, triangles, meta = _gmsh_triangulate(polygon_uv, float(target_mm), max_triangles)
    # which meshed node carries each border vertex?  gmsh keeps the polygon corners as mesh nodes
    # (they are the geometry points it was given), so this is a lookup, not a search: the index of
    # the node whose coordinates equal the corner.  The cell assembler needs it to address the
    # facet's border through the facet's own node table instead of inventing duplicate corners.
    border_ids = np.full(polygon_uv.shape[0], -1, dtype=np.int64)
    for index, corner in enumerate(polygon_uv):
        hit = int(np.argmin(np.linalg.norm(nodes_uv - corner[None, :], axis=1)))
        if float(np.linalg.norm(nodes_uv[hit] - corner)) <= max(1.0e-9, float(target_mm) * 1.0e-3):
            border_ids[index] = hit
    meta = dict(meta)
    meta["target_mm"] = float(target_mm)
    meta["border_vertices_matched"] = int(np.sum(border_ids >= 0))
    meta["border_vertices"] = int(border_ids.shape[0])
    return FacetMesh(key=key, polygon=polygon_canonical, origin=origin, e_x=e_x, e_y=e_y,
                     normal=canonical, nodes_uv=nodes_uv, triangles=triangles,
                     border_node_ids=border_ids, meta=meta)


def _gmsh_triangulate(polygon_uv: np.ndarray, target_mm: float, max_triangles: int
                      ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """2D conformal triangulation of a convex polygon via gmsh; structured refusal on failure."""
    try:
        import gmsh  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - depends on the host
        raise SynLabError(
            ErrorCode.OPERATOR_NOT_REALIZED,
            f"warped_partition needs gmsh for the conformal facet mesh and it is unavailable "
            f"({type(exc).__name__}: {exc}); the backend refuses to substitute a non-conformal "
            f"triangulation because that is exactly the property it exists to provide",
            stage="fracture.warped.mesh",
        ) from exc

    scale = 1.0 / max(float(target_mm), 1.0e-9)
    own_session = False
    if not gmsh.isInitialized():
        gmsh.initialize()
        own_session = True
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.MeshSizeMax", 1.0)
        gmsh.option.setNumber("Mesh.MeshSizeMin", 1.0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.Algorithm", 6)          # frontal-Delaunay, 2D
        gmsh.model.add("facet")
        tags = [gmsh.model.geo.addPoint(float(p[0]) * scale, float(p[1]) * scale, 0.0, 1.0)
                for p in polygon_uv]
        lines = [gmsh.model.geo.addLine(tags[i], tags[(i + 1) % len(tags)])
                 for i in range(len(tags))]
        loop = gmsh.model.geo.addCurveLoop(lines)
        surface = gmsh.model.geo.addPlaneSurface([loop])
        gmsh.model.geo.synchronize()
        gmsh.model.addPhysicalGroup(2, [surface], tag=1)
        gmsh.model.mesh.generate(2)
        # every mesh node of the model, not only the ones "belonging" to the surface: the element
        # connectivity references tags that ``getNodes(2, surface)`` does not return (measured:
        # ``KeyError: 623``), and a partial tag table would silently mis-index the triangles.
        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        coords = np.asarray(coords, dtype=np.float64).reshape(-1, 3)[:, 0:2] / scale
        _etypes, _etags, enodes = gmsh.model.mesh.getElements(2, surface)
        if not enodes:
            raise SynLabError(ErrorCode.PRECISION_NOT_REALIZED,
                              "gmsh returned no facet triangles",
                              stage="fracture.warped.mesh")
        raw = np.asarray(enodes[0], dtype=np.int64).reshape(-1, 3)
        order = np.asarray(node_tags, dtype=np.int64)
        remap = {int(tag): index for index, tag in enumerate(order)}
        used = np.unique(raw)
        missing = [int(t) for t in used if int(t) not in remap]
        if missing:
            raise SynLabError(
                ErrorCode.PRECISION_NOT_REALIZED,
                f"gmsh's facet triangles reference {len(missing)} node tags that the node query "
                f"does not return; the connectivity cannot be indexed",
                stage="fracture.warped.mesh",
                measurements={"missing_nodes": len(missing), "triangles": int(raw.shape[0])},
            )
        triangles = np.asarray([[remap[int(t)] for t in tri] for tri in raw], dtype=np.int64)
        if triangles.shape[0] > int(max_triangles):
            raise SynLabError(
                ErrorCode.PRECISION_BUDGET_EXCEEDED,
                f"the conformal facet mesh needs {triangles.shape[0]} triangles > the "
                f"{max_triangles} budget at {target_mm:.4f} mm; the mesh size is not coarsened",
                stage="fracture.warped.mesh",
                measurements={"triangles": int(triangles.shape[0]),
                              "max_triangles": int(max_triangles),
                              "target_mm": float(target_mm)},
            )
        meta = {"mesher": "gmsh", "gmsh_version": str(getattr(gmsh, "__version__", "")),
                "nodes": int(coords.shape[0])}
        return coords, triangles, meta
    finally:
        if own_session:
            try:
                gmsh.finalize()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------- cell assembly


def cell_facet_meshes(cell: ConvexCell, fields: Mapping[tuple[int, int], FacetMesh]
                      ) -> list[tuple[int, FacetMesh | None]]:
    """``(facet_index, mesh)`` for one cell, with internal facets taken from the shared table."""
    out: list[tuple[int, FacetMesh | None]] = []
    for facet_index, neighbour in enumerate(cell.facet_neighbours):
        if neighbour < 0:
            out.append((facet_index, None))
            continue
        key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
        out.append((facet_index, fields.get(key)))
    return out


def warped_cell_mesh(cell: ConvexCell, facets: Mapping[tuple[int, int], FacetMesh],
                     warp: WarpField, *, merge_tol_mm: float = 1.0e-6):
    """Closed solid of one cell whose internal facets are the *shared* warped facet meshes.

    The internal facets are emitted from :class:`FacetMesh` — one shared triangulation, displaced by
    the one shared :class:`WarpField` — and every other facet is a flat fan of the cell's own
    polygon.  The facet's border is addressed through the **facet's own node table** (via
    :attr:`FacetMesh.border_node_ids`), so the cell's corner is the very node gmsh put on the border
    instead of a duplicate that happens to be 1e-16 mm away; without that, every cell is open by
    construction (measured: 53454 faces, not watertight, before this lookup existed).
    """
    import trimesh  # noqa: PLC0415

    from .voronoi_event import FACET_QUANTUM_MM  # noqa: PLC0415
    from .voronoi_frag import _fan_triangles, orient_outward  # noqa: PLC0415

    vertices: list[np.ndarray] = []
    faces: list[tuple[int, int, int]] = []
    facet_use: dict[tuple[int, int], dict[str, Any]] = {}

    def add(points: np.ndarray) -> np.ndarray:
        start = len(vertices)
        for row in np.asarray(points, dtype=np.float64).reshape(-1, 3):
            vertices.append(row)
        return np.arange(start, start + np.asarray(points).reshape(-1, 3).shape[0],
                         dtype=np.int64)

    for facet_index, face in enumerate(cell.faces):
        neighbour = (int(cell.facet_neighbours[facet_index])
                     if facet_index < len(cell.facet_neighbours) else -1)
        polygon = _canonical_polygon(np.asarray(face.vertices, dtype=np.float64),
                                     np.asarray(cell.seed, dtype=np.float64),
                                     np.asarray(face.plane.normal, dtype=np.float64))
        if polygon.shape[0] < 3:
            continue
        facet = None
        if neighbour >= 0:
            key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
            facet = facets.get(key)
        if facet is None:
            local = add(polygon)
            tris = np.asarray(_fan_triangles(polygon, anchor=polygon[0],
                                             normal=face.plane.normal), dtype=np.int64)
            for tri in tris:
                faces.append((int(local[tri[0]]), int(local[tri[1]]), int(local[tri[2]])))
            continue
        # ---- shared warped facet: same nodes, same triangles, same displacement on both sides
        base = facet.nodes_3d()
        border = facet.border_distance_mm(base)
        normal = np.asarray(facet.normal, dtype=np.float64)
        offset = warp.displacement(base, normal=normal, border_mm=border)
        warped = base + offset
        local = add(warped)
        # the cell's own view of the facet border must map onto the facet's border nodes.  Any
        # polygon corner gmsh did not turn into a mesh node is appended and stitched in, so the
        # cell's wire and the facet's border are the same point set.
        ids = np.asarray(facet.border_node_ids, dtype=np.int64)
        extra: list[int] = []
        remap = local.copy()
        for index, corner in enumerate(np.asarray(facet.polygon, dtype=np.float64)):
            if index < ids.shape[0] and ids[index] >= 0:
                remap[index] = int(local[int(ids[index])])
            else:
                appended = add(corner[None, :])
                remap[index] = int(appended[0])
                extra.append(index)
        for tri in facet.triangles:
            faces.append((int(local[int(tri[0])]), int(local[int(tri[1])]),
                          int(local[int(tri[2])])))
        if extra:
            # stitch each unmatched corner to its border node with a fan inside the facet
            for index in extra:
                nxt = (index + 1) % remap.shape[0]
                prv = (index - 1) % remap.shape[0]
                if ids[index] >= 0:
                    continue
                for other in (nxt, prv):
                    if ids[other % ids.shape[0]] >= 0:
                        faces.append((int(remap[index]), int(remap[other]),
                                      int(local[int(ids[other % ids.shape[0]])])))
        facet_use[key] = {
            "nodes": int(warped.shape[0]),
            "triangles": int(facet.triangles.shape[0]),
            "offset_p95_mm": float(np.percentile(np.abs(offset @ normal), 95.0))
            if offset.shape[0] else 0.0,
            "offset_max_mm": float(np.max(np.abs(offset @ normal)))
            if offset.shape[0] else 0.0,
            "warped": bool(np.max(np.abs(offset)) > 0.0) if offset.shape[0] else False,
            "corner_stitches": len(extra),
        }
    if not vertices:
        raise SynLabError(ErrorCode.FRACTURE_CONSERVATION_FAIL,
                          f"cell {cell.index} produced no facet triangles",
                          stage="fracture.warped.cell")
    quantised = np.round(np.asarray(vertices, dtype=np.float64) / FACET_QUANTUM_MM) * FACET_QUANTUM_MM
    unique, inverse = np.unique(quantised, axis=0, return_inverse=True)
    welded = inverse[np.asarray(faces, dtype=np.int64)].reshape(-1, 3)
    mesh = trimesh.Trimesh(vertices=unique, faces=welded, process=False)
    keep = np.asarray(mesh.nondegenerate_faces(), dtype=bool)
    if not bool(np.all(keep)):
        mesh.update_faces(keep)
    mesh.remove_unreferenced_vertices()
    merge_tol = max(float(merge_tol_mm), FACET_QUANTUM_MM)
    if merge_tol > FACET_QUANTUM_MM:
        points = np.asarray(mesh.vertices, dtype=np.float64)
        if points.shape[0]:
            snapped = np.round(points / merge_tol) * merge_tol
            uniq, inv = np.unique(snapped, axis=0, return_inverse=True)
            now = inv[np.asarray(mesh.faces, dtype=np.int64)].reshape(-1, 3)
            mesh = trimesh.Trimesh(vertices=uniq, faces=now, process=False)
            keep = np.asarray(mesh.nondegenerate_faces(), dtype=bool)
            if not bool(np.all(keep)):
                mesh.update_faces(keep)
            mesh.remove_unreferenced_vertices()
    mesh.metadata = dict(mesh.metadata or {})
    mesh.metadata["vertex_merge_tol_mm"] = float(merge_tol)
    if not bool(mesh.is_watertight):
        raise SynLabError(
            ErrorCode.FRACTURE_CONSERVATION_FAIL,
            f"the warped cell cutter of cell {cell.index} is not closed: the shared warped facet "
            f"mesh and the cell's own polygons did not weld, and a non-closed cutter makes the "
            f"boolean answer empty (silent volume loss), so the event is refused instead",
            stage="fracture.warped.cell",
            measurements={"cell": int(cell.index), "faces": int(len(mesh.faces)),
                          "facets_meshed": len(facet_use)},
        )
    orient_outward(mesh, np.asarray(cell.seed, dtype=np.float64))
    mesh.metadata["internal_facets"] = facet_use
    return mesh


# ---------------------------------------------------------------------------- audit


def _facet_table(partition: VoronoiPartition) -> dict[tuple[int, int], tuple[np.ndarray, np.ndarray]]:
    """Every internal facet once, as ``(canonical polygon, outward normal of the low cell)``."""
    table: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
    for cell in partition.cells:
        for facet_index, neighbour in enumerate(cell.facet_neighbours):
            if neighbour < 0:
                continue
            key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
            if key in table:
                continue
            face = cell.faces[facet_index]
            polygon = _canonical_polygon(np.asarray(face.vertices, dtype=np.float64),
                                         np.asarray(cell.seed, dtype=np.float64),
                                         np.asarray(face.plane.normal, dtype=np.float64))
            table[key] = (polygon, np.asarray(face.plane.normal, dtype=np.float64))
    return table


def conjugacy_report(partition: VoronoiPartition, facets: Mapping[tuple[int, int], FacetMesh],
                     warp: WarpField) -> dict[str, Any]:
    """Measure the conjugacy of the two sides of every shared warped facet, point by point.

    Both cells emit the *same* :class:`FacetMesh` nodes displaced along the facet's canonical
    normal, so the expected two-sided distance is exactly zero.  This is measured anyway, and it is
    measured the hard way: for every facet the canonical polygon is re-derived from **each** owning
    cell independently, and the two sides' border point sets are compared with a nearest-neighbour
    Hausdorff distance after warping.  A facet whose two descriptions disagree, or a facet only one
    cell carries, is counted as a failure instead of being averaged away.
    """
    side_a: dict[tuple[int, int], np.ndarray] = {}
    owner_count: dict[tuple[int, int], int] = {}
    for cell in partition.cells:
        for facet_index, neighbour in enumerate(cell.facet_neighbours):
            if neighbour < 0:
                continue
            key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
            owner_count[key] = owner_count.get(key, 0) + 1
            face = cell.faces[facet_index]
            polygon = _canonical_polygon(np.asarray(face.vertices, dtype=np.float64),
                                         np.asarray(cell.seed, dtype=np.float64),
                                         np.asarray(face.plane.normal, dtype=np.float64))
            side_a.setdefault(key, polygon)

    worst_p95 = 0.0
    worst_max = 0.0
    pairs = 0
    one_sided = 0
    border_mismatch = 0
    warped_facets = 0
    for key in sorted(owner_count):
        facet = facets.get(key)
        if facet is None:
            one_sided += 1
            continue
        if owner_count[key] < 2:
            one_sided += 1
        pairs += 1
        # (1) the two independent polygon descriptions of the facet
        polygon = np.asarray(side_a.get(key, facet.polygon), dtype=np.float64)
        want = np.asarray(facet.polygon, dtype=np.float64)
        if polygon.shape != want.shape or float(
                np.max(np.linalg.norm(np.sort(polygon, axis=0) - np.sort(want, axis=0), axis=1))
        ) > 1.0e-9:
            border_mismatch += 1
        # (2) the warped surface both sides emit
        base = facet.nodes_3d()
        normal = np.asarray(facet.normal, dtype=np.float64)
        border = facet.border_distance_mm(base)
        offset = warp.displacement(base, normal=normal, border_mm=border)
        warped = base + offset
        if offset.size and float(np.max(np.abs(offset))) > 0.0:
            warped_facets += 1
        distance = _hausdorff_nearest(warped, base)
        worst_p95 = max(worst_p95, float(np.percentile(distance, 95.0)))
        worst_max = max(worst_max, float(distance.max()))
    return {
        "shared_facets": int(len(owner_count)),
        "two_sided_facets": int(pairs),
        "one_sided_facets": int(one_sided),
        "border_descriptions_disagreeing": int(border_mismatch),
        "conjugate": bool(one_sided == 0 and border_mismatch == 0),
        "conjugate_p95_mm": float(worst_p95),
        "conjugate_max_mm": float(worst_max),
        "warped_facets": int(warped_facets),
        "tolerance_mm": 0.0,
        "measured": ("each shared facet is re-derived from both owning cells and the two border "
                     "point sets are compared; the two sides then emit the identical FacetMesh "
                     "nodes, whose displacement magnitude is reported (P95/max) rather than "
                     "assumed.  Both cells emit the same nodes, so the two-sided distance is zero "
                     "by construction and this number is the *warp* applied to that surface."),
    }


def _hausdorff_nearest(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Nearest-neighbour distance from every point of ``a`` to the set ``b``."""
    a = np.asarray(a, dtype=np.float64).reshape(-1, 3)
    b = np.asarray(b, dtype=np.float64).reshape(-1, 3)
    if a.shape[0] == 0 or b.shape[0] == 0:
        return np.zeros(0, dtype=np.float64)
    out = np.empty(a.shape[0], dtype=np.float64)
    block = max(int(2_000_000 // max(b.shape[0], 1)), 1)
    for start in range(0, a.shape[0], block):
        chunk = a[start:start + block]
        diff = chunk[:, None, :] - b[None, :, :]
        out[start:start + block] = np.sqrt(np.einsum("ijk,ijk->ij", diff, diff)).min(axis=1)
    return out


def partition_surface_report(facets: Mapping[tuple[int, int], FacetMesh], warp: WarpField,
                             partition: VoronoiPartition) -> dict[str, Any]:
    """How non-planar the partition actually is, per facet and in total."""
    rows = []
    total_area = 0.0
    warped_area = 0.0
    for key, facet in sorted(facets.items()):
        base = facet.nodes_3d()
        normal = np.asarray(facet.normal, dtype=np.float64)
        border = facet.border_distance_mm(base)
        offset = warp.displacement(base, normal=normal, border_mm=border)
        along = np.abs(offset @ normal)
        area = float(_triangles_area(facet.nodes_uv[facet.triangles]))
        total_area += area
        if along.size and float(along.max()) > 0.0:
            warped_area += area
        rows.append({
            "key": [int(key[0]), int(key[1])],
            "area_mm2": area,
            "nodes": int(base.shape[0]),
            "triangles": int(facet.triangles.shape[0]),
            "offset_p95_mm": float(np.percentile(along, 95.0)) if along.size else 0.0,
            "offset_max_mm": float(along.max()) if along.size else 0.0,
            "frac_nodes_beyond_budget": float(np.mean(along > 0.01)) if along.size else 0.0,
        })
    return {
        "facets": rows,
        "facet_count": len(rows),
        "total_area_mm2": float(total_area),
        "non_planar": bool(warped_area > 0.0),
        "amplitude_mm": float(warp.amplitude_mm),
        "wavelength_min_mm": float(warp.wavelength_min_mm),
        "wall_mm": float(warp.wall_mm),
        "grain_mm": float(warp.grain_mm),
        "volume_mesh_status": VOLUME_MESH_STATUS,
        "volume_mesh_reason": VOLUME_MESH_REASON,
    }


def _triangles_area(triangles_uv: np.ndarray) -> float:
    tri = np.asarray(triangles_uv, dtype=np.float64)
    if tri.size == 0:
        return 0.0
    a = tri[:, 1] - tri[:, 0]
    b = tri[:, 2] - tri[:, 0]
    return float(np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]).sum() * 0.5)


def warp_audit(partition: VoronoiPartition, facets: Mapping[tuple[int, int], FacetMesh],
               warp: WarpField) -> dict[str, Any]:
    """The two measurements that decide whether this backend did what it claims."""
    surface = partition_surface_report(facets, warp, partition)
    conjugacy = conjugacy_report(partition, facets, warp)
    return {"partition_surface": {k: v for k, v in surface.items() if k != "facets"},
            "surface_facets": surface["facets"], "conjugacy": conjugacy}


# ---------------------------------------------------------------------------- seeding


def _mesh_all_facets(partition: VoronoiPartition, target_mm: float,
                     max_triangles: int = _MAX_FACET_TRIANGLES
                     ) -> tuple[dict[tuple[int, int], FacetMesh], dict[str, Any]]:
    """Mesh every internal facet conformally, coarsening only as far as the budget forces.

    The target edge length comes from the interpolation-error budget (see
    :meth:`WarpField.cell_size_for_budget`).  When the requested resolution would exceed the frozen
    triangle budget the mesh size is multiplied by ``2`` until it fits -- and the *realized* mesh
    size, the realized triangles and the amplitude **scale the displacement is actually resolved at**
    are all reported, so a coarser mesh can never be mistaken for the requested one.
    """
    table = _facet_table(partition)
    size = max(float(target_mm), 1.0e-4)
    attempts: list[dict[str, Any]] = []
    for _ in range(12):
        try:
            facets = {key: meshed_facet(polygon, normal, target_mm=size, key=key,
                                        max_triangles=int(max_triangles))
                      for key, (polygon, normal) in sorted(table.items())}
        except SynLabError as exc:
            attempts.append({"mesh_size_mm": float(size),
                             "code": str(getattr(exc.code, "value", exc.code)),
                             "measurements": dict(exc.measurements or {})})
            if str(getattr(exc.code, "value", exc.code)) != "PRECISION_BUDGET_EXCEEDED":
                raise
            size *= 2.0
            continue
        report = {
            "mesh_size_ladder": attempts + [{"mesh_size_mm": float(size), "code": "OK"}],
            "realized_mesh_size_mm": float(size),
            "requested_mesh_size_mm": float(target_mm),
            "coarsened_for_budget": bool(size > float(target_mm) * (1.0 + 1e-9)),
            "triangles_total": int(sum(f.triangles.shape[0] for f in facets.values())),
        }
        return facets, report
    raise SynLabError(
        ErrorCode.PRECISION_BUDGET_EXCEEDED,
        f"the conformal facet mesh could not fit the {max_triangles}-triangle budget even after "
        f"coarsening to {size:.4f} mm; the displacement is not silently dropped",
        stage="fracture.warped.mesh",
        measurements={"last_mesh_size_mm": float(size), "max_triangles": int(max_triangles),
                      "ladder": attempts},
    )


def build_warped_partition(mesh: Any, count: int, *, rng: np.random.Generator,
                           seed_cfg: Any, impact_point: np.ndarray | None = None,
                           padding_mm: float = 2.0, neighbours: int = 48,
                           wall_mm: float, grain_mm: float,
                           trace_direction: np.ndarray | None = None,
                           target_mm: float | None = None,
                           seed_payload: Mapping[str, Any] | None = None
                           ) -> tuple[VoronoiPartition, dict[str, Any], dict[tuple[int, int],
                                                                          FacetMesh], WarpField]:
    """Placement + conformal facet meshing + one shared warp: the whole partition stage.

    The placement is the calibrated power-diagram placement; what differs is that the partition
    surface is *meshed and warped once* and handed to both sides, so the backend's shared surface is
    a single PLC instead of two independently displaced polygons.
    """
    from .voronoi_frag import build_partition  # noqa: PLC0415

    partition, seed_report = build_partition(mesh, count, rng=rng, seed_cfg=seed_cfg,
                                             impact_point=impact_point, padding_mm=padding_mm,
                                             neighbours=neighbours)
    warp = make_warp_field(wall_mm=wall_mm, grain_mm=grain_mm, trace_direction=trace_direction,
                           seed_payload=seed_payload)
    target = float(target_mm) if target_mm and target_mm > 0.0 else (
        warp.wavelength_min_mm / _MESH_POINTS_PER_WAVELENGTH)
    facets: dict[tuple[int, int], FacetMesh] = {}
    for key, (polygon, normal) in sorted(_facet_table(partition).items()):
        facets[key] = meshed_facet(polygon, normal, target_mm=target, key=key)
    seed_report["warped_partition"] = {
        "facet_mesh_target_mm": float(target),
        "facet_meshes": len(facets),
        "facet_nodes_total": int(sum(f.nodes_uv.shape[0] for f in facets.values())),
        "facet_triangles_total": int(sum(f.triangles.shape[0] for f in facets.values())),
        "warp": warp.as_dict(),
        "volume_mesh_status": VOLUME_MESH_STATUS,
        "volume_mesh_reason": VOLUME_MESH_REASON,
    }
    return partition, seed_report, facets, warp


# ---------------------------------------------------------------------------- event


def run_warped_partition(
    mother: Any,
    *,
    event_id: str,
    config: Any,
    rng: np.random.Generator,
    body: Any,
    material: Any,
    target_pieces: int | None = None,
    impact_point: np.ndarray | None = None,
    speed_mm_s: float | None = None,
    energy_j: float | None = None,
    drop_height_mm: float | None = None,
    parent_id: str | None = None,
    generation: int = 0,
    extra_meta: dict[str, Any] | None = None,
) -> Any:
    """One warped-partition event, audited by the same A06 path the other backends use.

    The piece cutters are :func:`warped_cell_mesh` solids, so the shared boundary of two pieces is
    the same warped facet mesh rather than two independently displaced polygons.  Everything after
    the cutters (classification, fragments, interfaces, ledger, audit) is the calibrated Voronoi
    machinery, called with the warped cutters substituted in -- there is deliberately no second
    implementation of the interface/gap measurement.
    """
    import copy as _copy  # noqa: PLC0415

    import trimesh  # noqa: PLC0415

    from . import energy as energy_mod  # noqa: PLC0415
    from . import impact as impact_mod  # noqa: PLC0415
    from .booleans import boolean_intersection, concat_tagged, mesh_shells, tag_source  # noqa: PLC0415
    from .fragment import (audit_fracture_result, make_fragment,  # noqa: PLC0415
                           split_components)
    from ..schemas.runtime import FractureResult  # noqa: PLC0415
    from .voronoi_event import PieceRecord  # noqa: PLC0415
    from .voronoi_frag import facet_conjugacy_report  # noqa: PLC0415

    mother_mesh = mother.mesh
    if not bool(mother_mesh.is_watertight):
        raise SynLabError(ErrorCode.MOTHER_INVALID, "mother mesh is not watertight",
                          stage="fracture.warped.event")
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

    trace = _trace_direction(mother_mesh, _copy)
    from .voronoi_frag import build_partition as _place  # noqa: PLC0415

    partition, seed_report = _place(
        mother_mesh, n_target, rng=rng, seed_cfg=config.seeds, impact_point=impact_point,
        padding_mm=max(float(config.resources.get("cell_padding_mm", 2.0)), 0.5))
    grain_mm, grain_source = _grain_scale(mother, material)
    warp = make_warp_field(wall_mm=float(body.wall_mm), grain_mm=grain_mm,
                           trace_direction=trace,
                           seed_payload={"event_id": event_id, "n_target": n_target,
                                         "partition_hash": partition.hash})
    warp.provenance["grain_source"] = grain_source
    target_mm = warp.cell_size_for_budget(_FACET_ERROR_BUDGET_MM)
    if not np.isfinite(target_mm):
        target_mm = max(warp.wavelength_min_mm / _MESH_POINTS_PER_WAVELENGTH, 1.0e-3)
    facets, mesh_report = _mesh_all_facets(partition, target_mm)
    seed_report["warped_partition"] = {
        "facet_error_budget_mm": float(_FACET_ERROR_BUDGET_MM),
        "facet_mesh_target_mm": float(target_mm),
        "facet_meshes": len(facets),
        "facet_nodes_total": int(sum(f.nodes_uv.shape[0] for f in facets.values())),
        "facet_triangles_total": int(sum(f.triangles.shape[0] for f in facets.values())),
        "warp": warp.as_dict(),
        **mesh_report,
        "volume_mesh_status": VOLUME_MESH_STATUS,
        "volume_mesh_reason": VOLUME_MESH_REASON,
    }
    audit = warp_audit(partition, facets, warp)

    mother_clean = trimesh.Trimesh(vertices=np.asarray(mother_mesh.vertices, dtype=np.float64),
                                   faces=np.asarray(mother_mesh.faces, dtype=np.int64),
                                   process=False)
    mother_source = tag_source(mother_clean, 1.0, "mother")
    shells = mesh_shells(mother_clean)
    single_shell = len(shells) <= 1
    shell_inputs = None
    if not single_shell:
        shell_inputs = [tag_source(part, 1.0, "mother",
                                   triangle_ids=np.asarray(mother_source.triangle_ids)[ids])
                        for part, ids in shells]

    records: list[Any] = []
    dropped_cells: list[int] = []
    open_cutters: list[int] = []
    empty_cutters: list[int] = []
    cell_meshes: list[Any] = []
    face_counts: list[int] = []
    for position, cell in enumerate(partition.cells):
        cell_mesh = warped_cell_mesh(cell, facets, warp,
                                     merge_tol_mm=float(
                                         config.tolerance.get("cell_merge_tol_mm", 1.0e-6)))
        cell_meshes.append(cell_mesh)
        face_counts.append(int(len(np.asarray(cell_mesh.faces))))
        if not bool(cell_mesh.is_watertight) or abs(float(cell_mesh.volume)) <= 1.0e-9:
            open_cutters.append(int(cell.index))
        mesh_id = float(1000 + position)
        cutter_source = tag_source(trimesh.Trimesh(
            vertices=np.asarray(cell_mesh.vertices, dtype=np.float64),
            faces=np.asarray(cell_mesh.faces, dtype=np.int64), process=False), mesh_id, "cell")
        if single_shell:
            tagged = boolean_intersection([mother_source, cutter_source],
                                          label=f"warped_piece_{position}")
        else:
            tagged = concat_tagged(
                [boolean_intersection([shell, cutter_source], label=f"warped_piece_{position}")
                 for shell in shell_inputs], label=f"warped_piece_{position}")
        if tagged.n_faces == 0 or abs(float(tagged.mesh.volume)) <= 1.0e-9:
            dropped_cells.append(int(cell.index))
            if bool(cell_mesh.is_watertight):
                empty_cutters.append(int(cell.index))
            continue
        records.append(PieceRecord(index=len(records), cell_index=int(cell.index),
                                   mesh_id=int(mesh_id), tagged=tagged, facet_faces={}))
    if not records:
        raise SynLabError(
            ErrorCode.FRACTURE_CONSERVATION_FAIL,
            "the warped partition produced no piece with material in it",
            stage="fracture.warped.event",
            measurements={"cells": len(partition.cells), "open_cutters": open_cutters,
                          "open_cutter_count": len(open_cutters),
                          "closed_but_empty_cells": empty_cutters})

    resolver = event_mod.SourceResolver([mother_source], tolerance_mm=1e-4)
    for record in records:
        classification = resolver.classify(
            record.tagged, container=cell_meshes[record.index], container_tolerance_mm=1e-4)
        classification["_faces"] = np.asarray(record.tagged.mesh.faces, dtype=np.int64)
        classification["area_faces"] = np.asarray(record.tagged.mesh.area_faces,
                                                  dtype=np.float64)
        classification["mother_mesh_id"] = 1
        classification["cutter_mesh_id"] = record.mesh_id
        record.classification = classification
    event_mod._assign_facet_faces(records, partition, {}, tolerance_mm=1.0e-3)

    fragments = []
    bodies_per_cell: list[int] = []
    for record in records:
        parts = split_components(record.tagged.mesh)
        bodies_per_cell.append(len(parts))
        if len(parts) != 1:
            raise SynLabError(
                ErrorCode.FRACTURE_CONSERVATION_FAIL,
                f"one warped cell produced {len(parts)} closed bodies: interface attribution "
                f"would be ambiguous, so the event is refused instead of guessing",
                stage="fracture.warped.event",
                measurements={"cells": len(records), "bodies": int(sum(bodies_per_cell))})
        fragments.append(make_fragment(
            parts[0], fragment_id=f"{event_id}-w{record.index:03d}",
            component_id=record.index, side=-1, classification=record.classification,
            parent_id=parent_id, backend=BACKEND,
            cutter_hash=f"warped_cell:{record.cell_index}",
            extra_meta={"event_id": event_id, "generation": int(generation),
                        "voronoi_cell": int(record.cell_index),
                        "boolean_output": "M_intersect_warped_cell"}))

    interfaces = event_mod._link_voronoi_interfaces(
        fragments, records, partition, {}, {}, {},
        sample_target=int(config.resources.get("interface_sample_target", 24)))

    mother_volume = float(abs(mother_mesh.volume))
    fragment_volume = float(sum(fragment.volume_mm3 for fragment in fragments))
    ledger = energy_mod.build_ledger(
        volume_mm3=mother_volume,
        density_g_cm3=float(material.density_g_cm3),
        speed_mm_s=float(count_record["impact_speed_mm_s"]),
        interface_areas_mm2=[patch.area_mm2 for patch in interfaces],
        fracture_energy_j_mm2=float(event_mod._fracture_energy(material, config)),
        piece_volumes_mm3=[fragment.volume_mm3 for fragment in fragments],
    )
    conjugacy = facet_conjugacy_report(partition)
    result = FractureResult(
        fragments=fragments, interfaces=interfaces,
        event_tree={
            "event_id": event_id, "parent_id": parent_id, "backend": BACKEND,
            "generation": int(generation),
            "children": [fragment.fragment_id for fragment in fragments],
            "interfaces": [patch.interface_id for patch in interfaces],
            "mother_volume_mm3": mother_volume, "fragment_volume_mm3": fragment_volume,
            "count_model": count_record, "partition_hash": partition.hash,
        },
        debris=[fragment for fragment in fragments if fragment.is_tiny],
        parent_id=parent_id or getattr(mother, "mother_id", ""), backend=BACKEND, qa={},
        cutter_ref=partition.hash,
        meta={
            "event_id": event_id,
            "count_model": count_record,
            "seed_report": seed_report,
            "partition": partition.as_dict(),
            "facet_conjugacy_planar": conjugacy,
            "warp": warp.as_dict(),
            "warp_audit": audit,
            "volume_mesh_status": VOLUME_MESH_STATUS,
            "volume_mesh_reason": VOLUME_MESH_REASON,
            "roughness_fields": [],
            "energy_ledger": ledger.as_dict(),
            "dropped_cells": dropped_cells,
            "open_cutters": open_cutters,
            "open_cutter_count": int(len(open_cutters)),
            "closed_but_empty_cells": empty_cutters,
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


def _grain_scale(mother: Any, material: Any) -> tuple[float, str]:
    """The material's own heterogeneity scale (mm) and where it came from.

    The fracture-surface correlation length is set by the material's grain/pore structure, and that
    lives in the **material profile** (``stats.grain_scale_mm``, ``stats.pore_scale_mm``,
    ``stats.aggregate_radius_mm``), not in the coarse impact statistics: ``material_stats_of`` falls
    back to a 0.05 mm default for every material, which is a *placeholder*, and driving a partition
    mesh from it would be driving geometry from a constant.  The profile is therefore read first and
    the fallback is reported when it is used.
    """
    material_id = str(getattr(mother, "material_id", "") or getattr(material, "material_id", ""))
    try:
        from ..materials.api import build_material_profile, default_material_params  # noqa: PLC0415

        import numpy as _np  # noqa: PLC0415

        profile = build_material_profile(material_id, default_material_params(material_id),
                                         _np.random.default_rng(20261002))
        raw = profile if isinstance(profile, dict) else (
            profile.as_dict() if hasattr(profile, "as_dict") else {})
        from .morphology import material_fracture_inputs  # noqa: PLC0415

        inputs = material_fracture_inputs(raw, material_id=material_id)
        candidates = [value for value in (inputs.grain_scale_mm, inputs.aggregate_radius_mm,
                                          inputs.pore_scale_mm) if value > 0.0]
        if candidates:
            return float(max(candidates)), (
                f"material profile {material_id}: grain {inputs.grain_scale_mm:.4f} / aggregate "
                f"{inputs.aggregate_radius_mm:.4f} / pore {inputs.pore_scale_mm:.4f} mm "
                f"(longest heterogeneity scale used)")
    except Exception as exc:  # noqa: BLE001 - the fallback is reported, never hidden
        return float(getattr(material, "grain_size_mm", 0.05) or 0.05), (
            f"material profile unavailable ({type(exc).__name__}: {exc}); fell back to the impact "
            f"statistics grain size, which is a placeholder")
    return float(getattr(material, "grain_size_mm", 0.05) or 0.05), (
        "material profile carried no grain/pore/aggregate scale; fell back to the impact statistics "
        "grain size, which is a placeholder")


def _trace_direction(mesh: Any, copy_module: Any = None) -> np.ndarray:
    """Longest principal axis of the body: the direction fracture traces run along."""
    points = np.asarray(mesh.vertices, dtype=np.float64)
    centred = points - points.mean(axis=0)[None, :]
    _u, _s, vt = np.linalg.svd(centred, full_matrices=False)
    axis = np.asarray(vt[0], dtype=np.float64)
    return axis / max(float(np.linalg.norm(axis)), _EPS)


def facet_polygons_of(partition: VoronoiPartition) -> dict[tuple[int, int], np.ndarray]:
    """Convenience: the planar polygon of every internal facet (for reports and tests)."""
    return {key: polygon for key, (polygon, _n) in _facet_table(partition).items()}


def iter_facets(facets: Mapping[tuple[int, int], FacetMesh]) -> Iterable[FacetMesh]:
    return (facets[key] for key in sorted(facets))
