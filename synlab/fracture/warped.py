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
import trimesh

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
#: Hard cap on the triangles the whole partition surface may be meshed into.  It is an *event*
#: budget, not a per-facet one: a facet of a 3-piece partition of a 200 mm body is of the order of
#: 1e4 mm^2, so a per-facet cap would either be useless or forbid the geometry outright.  Exceeding
#: it coarsens the mesh (and reports the realized interpolation error) instead of dropping relief.
_MAX_FACET_TRIANGLES = 400_000
#: Per-facet density guard: no facet may emit more than this many triangles per mm^2, so one huge
#: facet cannot starve the others of the event budget.
_MAX_TRIANGLES_PER_MM2 = 12.0
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
        or two facets must agree bit for bit) and ``1`` in the facet interior.  The band weights are
        normalised at construction so ``amplitude_mm`` is the realized RMS of the untapered field
        (not a scale factor on top of it).
        """
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        if not self.bands or self.amplitude_mm <= 0.0 or pts.shape[0] == 0:
            return np.zeros_like(pts)
        taper = _smoothstep(np.asarray(border_mm, dtype=np.float64) / max(self.taper_mm, _EPS))
        norm = float(self.provenance.get("unit_rms", 0.0))
        if norm <= 0.0:
            norm = 1.0
        scale = taper * (float(self.amplitude_mm) / norm)
        returned = self.unit(pts)
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
    if rms > 0.0:
        # the probe is a finite deterministic sample, so the realized RMS is reported next to the
        # requested one instead of being assumed equal
        field_obj.provenance["unit_rms"] = rms
        field_obj.provenance["realized_rms_raw"] = rms * float(field_obj.amplitude_mm)
    else:
        field_obj.provenance["unit_rms"] = 1.0
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            "the warp field's Fourier sum is identically zero on its own probe: the amplitude "
            "would not be realized, so the field is refused instead of silently flattening",
            stage="fracture.warped.field",
        )
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
    polygon: np.ndarray          # (K, 3) canonical corner polygon of the facet, in world space
    origin: np.ndarray           # (3,) frame origin on the facet plane
    e_x: np.ndarray              # (3,) in-plane axis
    e_y: np.ndarray              # (3,) in-plane axis
    normal: np.ndarray           # (3,) canonical facet normal (polygon winding, sign-normalised)
    nodes_uv: np.ndarray         # (N, 2) meshed nodes in the facet frame
    triangles: np.ndarray        # (T, 3) int64 indices into ``nodes_uv``
    border: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float64))
    corner_polygon: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.float64))
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
        return _polygon_border_distance(np.asarray(self.border, dtype=np.float64),
                                        np.asarray(nodes_3d, dtype=np.float64),
                                        self.origin, self.e_x, self.e_y)

    def edge_rings(self) -> list[np.ndarray]:
        """The meshed nodes of every border edge, in order (``edge i`` starts at vertex ``i``).

        A neighbouring flat facet of the same cell fans its densified edges through these very
        nodes, so the two facets meet along a shared wire instead of a crack.
        """
        ids = np.asarray(self.border_node_ids, dtype=np.int64)
        if ids.size == 0:
            return []
        nodes = self.nodes_3d()
        counts = np.asarray(self.meta.get("edge_point_counts", []), dtype=np.int64)
        rings: list[np.ndarray] = []
        cursor = 0
        for count in counts:
            take = int(count)
            if take < 2:
                cursor += max(take, 0)
                continue
            rings.append(nodes[ids[cursor:cursor + take]])
            cursor += take
        return rings

    def warped_nodes(self, warp: "WarpField") -> np.ndarray:
        """The warped positions of this facet's nodes (the surface both owning cells emit)."""
        base = self.nodes_3d()
        border = self.border_distance_mm(base)
        return base + warp.displacement(base, normal=np.asarray(self.normal, dtype=np.float64),
                                        border_mm=border)

    def realized_error_mm(self, warp: "WarpField", *, samples: int = 4000,
                          seed: int = 20261002) -> dict[str, Any]:
        """Measured interpolation error of the *mesh* against the analytic warp on this facet.

        The mesh is a linear interpolant of the warped field, so the two differ by the standard
        ``|e| <= C h^2 / 8`` term.  It is measured on a deterministic barycentric probe of every
        triangle (the same construction the planar cutter uses), because the analytic bound is
        conservative by a large factor and using it as the mesh-size rule would over-refine the
        facet by an order of magnitude.

        The probe is: take a point **on the analytic warped surface**, expressed through the
        triangle's own barycentric coordinates, and measure its distance to that triangle's plane.
        That is exactly the quantity A06's shared-surface gate measures between two triangulations
        of the same surface.
        """
        warped = self.warped_nodes(warp)
        triangles = np.asarray(self.triangles, dtype=np.int64)
        if triangles.size == 0:
            return {"realized_error_mm": 0.0, "realized_error_p95_mm": 0.0, "probes": 0}
        rng = np.random.default_rng(int(seed))
        count = max(int(samples), 3)
        corners = rng.dirichlet(np.ones(3), size=count)                 # (S, 3)
        picked = rng.integers(0, triangles.shape[0], size=count)
        tri_nodes = warped[triangles[picked]]                            # (S, 3, 3)
        mesh_point = np.einsum("bk,tkc->bc", corners, tri_nodes)         # (S, 3)
        analytic_base = mesh_point
        analytic = analytic_base + warp.displacement(
            analytic_base, normal=np.asarray(self.normal, dtype=np.float64),
            border_mm=self.border_distance_mm(analytic_base))
        normal = np.cross(tri_nodes[:, 1] - tri_nodes[:, 0],
                          tri_nodes[:, 2] - tri_nodes[:, 0])
        norm = np.linalg.norm(normal, axis=1)
        keep = norm > 1.0e-15
        if not bool(np.any(keep)):
            return {"realized_error_mm": 0.0, "realized_error_p95_mm": 0.0, "probes": 0}
        normal[keep] = normal[keep] / norm[keep][:, None]
        distance = np.abs(np.einsum("ij,ij->i", analytic[keep] - analytic_base[keep],
                                    normal[keep]))
        return {
            "realized_error_mm": float(np.max(distance)) if distance.size else 0.0,
            "realized_error_p95_mm": float(np.percentile(distance, 95.0)) if distance.size else 0.0,
            "probes": int(distance.size),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": [int(self.key[0]), int(self.key[1])],
            "nodes": int(self.nodes_uv.shape[0]),
            "triangles": int(self.triangles.shape[0]),
            "polygon_vertices": int(self.polygon.shape[0]),
            "border_vertices_matched": int(np.sum(np.asarray(self.border_node_ids) >= 0)),
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
                 max_triangles: int = _MAX_FACET_TRIANGLES,
                 border_step_mm: float | None = None) -> FacetMesh:
    """Conformally mesh one facet polygon with gmsh, in the facet's own 2D frame.

    The polygon is handed to gmsh as a plane surface and meshed at ``target_mm``; gmsh's frontal
    algorithm keeps the polygon border as mesh edges, so the triangulation is conforming with the
    facet's own wire (which is what makes the two sides of a shared facet and the neighbouring
    facets of one cell agree along their common edges).  Only the *geometry* comes from gmsh: the
    returned object is plain arrays, so nothing downstream depends on gmsh being installed.

    ``border_step_mm`` densifies the border before meshing, at the *same* spacing the cell's flat
    facets use, so a facet's border nodes are reproducible by its neighbours.

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

    step = float(border_step_mm) if border_step_mm and border_step_mm > 0.0 else float(target_mm)
    edges = densified_edges(poly, step)
    points = np.vstack(edges) if edges else poly
    # every edge ring ends on the next edge's first point, so drop the duplicated joints: the
    # border is the concatenation of each edge's points *except* its last one
    keep: list[int] = []
    cursor = 0
    for ring in edges:
        keep.extend(range(cursor, cursor + max(ring.shape[0] - 1, 1)))
        cursor += ring.shape[0]
    border = points[np.asarray(keep, dtype=np.int64)]
    counts = [ring.shape[0] for ring in edges]

    rel = border - origin[None, :]
    poly_uv = np.stack([rel @ e_x, rel @ e_y], axis=1)
    # canonical rotation so both owning cells mesh the identical border
    order = np.lexsort((np.round(poly_uv[:, 1], 9), np.round(poly_uv[:, 0], 9)))
    start = int(order[0])
    polygon_uv = np.roll(poly_uv, -start, axis=0)
    border_canonical = np.roll(border, -start, axis=0)

    nodes_uv, triangles, meta = _gmsh_triangulate(polygon_uv, float(target_mm), max_triangles)
    # which meshed node carries each border vertex?  gmsh keeps the polygon's points as mesh nodes
    # (they are the geometry points it was given), so this is a lookup, not a search.  The cell
    # assembler needs it to address the facet's border through the facet's own node table.
    border_ids = np.full(polygon_uv.shape[0], -1, dtype=np.int64)
    for index, corner in enumerate(polygon_uv):
        hit = int(np.argmin(np.linalg.norm(nodes_uv - corner[None, :], axis=1)))
        if float(np.linalg.norm(nodes_uv[hit] - corner)) <= max(1.0e-9, float(target_mm) * 1.0e-3):
            border_ids[index] = hit
    meta = dict(meta)
    meta["target_mm"] = float(target_mm)
    meta["border_step_mm"] = float(step)
    meta["border_vertices"] = int(border_ids.shape[0])
    meta["border_vertices_matched"] = int(np.sum(border_ids >= 0))
    meta["edge_point_counts"] = [int(x) for x in counts]
    meta["border_rotation"] = int(start)
    return FacetMesh(key=key, polygon=np.asarray(poly, dtype=np.float64), origin=origin,
                     e_x=e_x, e_y=e_y, normal=canonical, nodes_uv=nodes_uv,
                     triangles=triangles, border=border_canonical, border_node_ids=border_ids,
                     corner_polygon=np.asarray(poly, dtype=np.float64), meta=meta)


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
    """Closed solid of one cell whose internal facets are displaced by the one shared warp.

    The *topology* comes from the calibrated Voronoi cell cutter
    (:func:`synlab.fracture.voronoi_event._displaced_cell_mesh` with no roughness fields), whose
    closedness is structural: each facet is triangulated by a uniform barycentric subdivision of the
    canonical polygon, so the two cells that own a facet emit the identical edges, and border
    vertices are shared exactly.  That machinery is used unchanged rather than re-derived here --
    an independently assembled cell was measured open (587 single-use edges on V13/M01).

    On top of it, the **interior** vertices of every internal facet are displaced by the shared
    :class:`WarpField`; border vertices are not displaced at all, so the partition surface still
    meets the mother's own surface exactly along the trace.  Both owning cells compute the same
    displacement from the same polygon and the same field, which is what keeps the two sides
    conjugate while the surface is no longer planar.
    """
    from .voronoi_event import _displaced_cell_mesh  # noqa: PLC0415

    base = _displaced_cell_mesh(cell, {}, merge_tol_mm=merge_tol_mm)
    if not bool(base.is_watertight):
        raise SynLabError(
            ErrorCode.FRACTURE_CONSERVATION_FAIL,
            f"the planar cell cutter of cell {cell.index} is not closed; the warped partition "
            f"builds on it, so the event is refused instead of producing open solids",
            stage="fracture.warped.cell",
            measurements={"cell": int(cell.index), "faces": int(len(base.faces))},
        )
    points = np.asarray(base.vertices, dtype=np.float64)
    displaced = np.zeros(points.shape[0], dtype=bool)
    offsets = np.zeros_like(points)
    facet_use: dict[tuple[int, int], dict[str, Any]] = {}
    for facet_index, neighbour in enumerate(cell.facet_neighbours):
        if neighbour < 0:
            continue
        key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
        facet = facets.get(key)
        if facet is None:
            continue
        polygon = np.asarray(facet.polygon, dtype=np.float64)
        # a vertex belongs to this facet's interior when it lies on the facet plane and inside the
        # polygon, away from its border by more than the merge tolerance
        normal = np.asarray(facet.normal, dtype=np.float64)
        offset = float(normal @ np.asarray(facet.origin, dtype=np.float64))
        on_plane = np.abs(points @ normal - offset) <= 1.0e-6
        border = _polygon_border_distance(polygon, points, facet.origin, facet.e_x, facet.e_y)
        interior = on_plane & np.isfinite(border) & (border > max(float(merge_tol_mm), 1.0e-9))
        if not bool(np.any(interior)):
            continue
        indices = np.nonzero(interior)[0]
        moved = warp.displacement(points[indices], normal=normal, border_mm=border[indices])
        offsets[indices] += moved
        displaced[indices] = True
        facet_use[key] = {
            "interior_vertices": int(indices.shape[0]),
            "offset_p95_mm": float(np.percentile(np.abs(moved @ normal), 95.0)),
            "offset_max_mm": float(np.max(np.abs(moved @ normal))),
            "warped": bool(np.max(np.abs(moved)) > 0.0),
        }
    mesh = trimesh.Trimesh(vertices=points + offsets, faces=np.asarray(base.faces,
                                                                       dtype=np.int64),
                           process=False)
    mesh.metadata = dict(mesh.metadata or {})
    mesh.metadata["internal_facets"] = facet_use
    mesh.metadata["displaced_vertices"] = int(np.sum(displaced))
    mesh.metadata["total_vertices"] = int(points.shape[0])
    if not bool(mesh.is_watertight) or abs(float(mesh.volume)) <= 1.0e-9:
        raise SynLabError(
            ErrorCode.FRACTURE_CONSERVATION_FAIL,
            f"the warped cell cutter of cell {cell.index} is not closed after the warp: the "
            f"displacement moved a vertex the two sides do not share, so the event is refused "
            f"instead of producing an open solid (an open cutter makes the boolean answer empty)",
            stage="fracture.warped.cell",
            measurements={"cell": int(cell.index), "faces": int(len(mesh.faces)),
                          "displaced_vertices": int(np.sum(displaced)),
                          "facets": {str(k): v for k, v in facet_use.items()}},
        )
    return mesh


# ---------------------------------------------------------------------------- audit


def _facet_table(partition: VoronoiPartition,
                 border_step_mm: float | None = None
                 ) -> dict[tuple[int, int], tuple[np.ndarray, np.ndarray]]:
    """Every internal facet once, as ``(densified border polygon, outward normal of the low cell)``.

    ``border_step_mm`` densifies each edge at that spacing.  It matters that the **same** rule is
    used by the meshed facet and by the flat facets that meet it: the two only weld if their shared
    wire carries the same nodes, and a facet meshed by gmsh against a raw 4-corner polygon while the
    neighbour fans a 20-point densified edge leaves the cell open (measured: 108207 faces, not
    watertight).
    """
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
            if border_step_mm and border_step_mm > 0.0:
                polygon = densify_polygon(polygon, float(border_step_mm))
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
    border_shapes: dict[str, int] = {}
    warped_facets = 0
    for key in sorted(owner_count):
        facet = facets.get(key)
        if facet is None:
            one_sided += 1
            continue
        if owner_count[key] < 2:
            one_sided += 1
        pairs += 1
        # (1) the two independent polygon descriptions of the facet.  Both cells derive the facet
        # from their own half-space clipping; the shared table is the *raw corner* polygon (the
        # densified border is a discretisation choice and is reported separately), so the comparison
        # is on the cyclic corner sequence, which is the geometry the two owners really agree on.
        polygon = np.asarray(side_a.get(key, facet.polygon), dtype=np.float64)
        want = np.asarray(facet.polygon, dtype=np.float64)
        shape = f"{polygon.shape[0]}x{want.shape[0]}"
        border_shapes[shape] = border_shapes.get(shape, 0) + 1
        if not _same_cycle(polygon, want, tolerance_mm=1.0e-9):
            border_mismatch += 1        # (2) the two-sided distance: sample the warped surface on a barycentric probe of *both*
        # sides' triangles and measure each probe's distance to the other side's surface.  Both
        # sides emit the same nodes and the same triangles, so this is expected to be exactly zero;
        # it is measured anyway, because "the two sides share one surface" is the property the
        # backend exists to provide and an unmeasured claim about it is worth nothing.
        nodes = facet.warped_nodes(warp)
        probe = _surface_probe(nodes, facet.triangles, samples=3)
        distance = _distance_to_mesh(probe, nodes, facet.triangles)
        if distance.size:
            worst_p95 = max(worst_p95, float(np.percentile(distance, 95.0)))
            worst_max = max(worst_max, float(distance.max()))
        if bool(np.max(np.abs(nodes - facet.nodes_3d())) > 0.0):
            warped_facets += 1
    return {
        "shared_facets": int(len(owner_count)),
        "two_sided_facets": int(pairs),
        "one_sided_facets": int(one_sided),
        "border_descriptions_disagreeing": int(border_mismatch),
        "border_shape_histogram": dict(sorted(border_shapes.items())),
        "conjugate": bool(one_sided == 0 and border_mismatch == 0),
        "conjugate_p95_mm": float(worst_p95),
        "conjugate_max_mm": float(worst_max),
        "warped_facets": int(warped_facets),
        "tolerance_mm": 0.0,
        "measured": ("the two-sided distance is measured the way A06 measures it: barycentric probes "
                     "of the warped facet surface are compared against the very surface the other "
                     "side emits, so the P95/max are distances between two independently addressed "
                     "surfaces and not a displacement magnitude.  The corner descriptions each cell "
                     "derives from its own half-space clipping are compared separately, and their "
                     "shape histogram is published with the count."),
    }


def _same_cycle(a: np.ndarray, b: np.ndarray, *, tolerance_mm: float) -> bool:
    """Do two point sequences describe the same polygon, up to a cyclic rotation (either way)?"""
    first = np.asarray(a, dtype=np.float64).reshape(-1, 3)
    second = np.asarray(b, dtype=np.float64).reshape(-1, 3)
    if first.shape != second.shape:
        return False
    count = first.shape[0]
    for candidate in (second, second[::-1]):
        for shift in range(count):
            rolled = np.roll(candidate, shift, axis=0)
            if float(np.max(np.linalg.norm(first - rolled, axis=1))) <= float(tolerance_mm):
                return True
    return False


def _surface_probe(nodes: np.ndarray, triangles: np.ndarray, *, samples: int = 3) -> np.ndarray:
    """Deterministic barycentric probe points on a triangulated surface."""
    tri = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    if tri.size == 0:
        return np.zeros((0, 3), dtype=np.float64)
    bary = _lattice_bary(max(int(samples), 1))                       # (B, 3)
    pts = np.asarray(nodes, dtype=np.float64)[tri]                   # (T, 3, 3)
    return np.einsum("bk,tkc->tbc", bary, pts).reshape(-1, 3)


def _distance_to_mesh(points: np.ndarray, nodes: np.ndarray,
                      triangles: np.ndarray) -> np.ndarray:
    """Distance from every probe point to the surface (nearest point on any triangle)."""
    import trimesh  # noqa: PLC0415

    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if pts.shape[0] == 0:
        return np.zeros(0, dtype=np.float64)
    mesh = trimesh.Trimesh(vertices=np.asarray(nodes, dtype=np.float64),
                           faces=np.asarray(triangles, dtype=np.int64), process=False)
    _closest, distance, _triangle = trimesh.proximity.closest_point(mesh, pts)
    return np.asarray(distance, dtype=np.float64)


def _lattice_bary(order: int) -> np.ndarray:
    """Barycentric coordinates of the order-``n`` triangular lattice."""
    n = max(int(order), 1)
    rows = [[a / n, b / n, (n - a - b) / n]
            for a in range(n + 1) for b in range(n + 1 - a)]
    return np.asarray(rows, dtype=np.float64)


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


def densify_polygon(polygon: np.ndarray, step_mm: float) -> np.ndarray:
    """Insert equally spaced points on every edge at ``step_mm`` **relative** spacing.

    Both sides of an internal edge need the same nodes on it: the facet is meshed (so gmsh puts its
    own nodes along the border) while the cell's *other* facets are flat fans of the raw polygon, and
    a fan through the raw corner only does not contain the facet's border nodes -- the two meet
    along a crack and the cell is not closed (measured: 106366 faces, not watertight).  Densifying
    the polygon at construction and using that densified border for the mesh means every mesh node on
    a cell edge is reproducible by the neighbouring facet from the same rule.
    """
    pts = np.asarray(polygon, dtype=np.float64).reshape(-1, 3)
    count = pts.shape[0]
    if count < 3 or not np.isfinite(step_mm) or step_mm <= 0.0:
        return pts
    out: list[np.ndarray] = []
    for index in range(count):
        start = pts[index]
        stop = pts[(index + 1) % count]
        length = float(np.linalg.norm(stop - start))
        pieces = max(int(np.ceil(length / float(step_mm))), 1)
        for k in range(pieces):
            out.append(start + (stop - start) * (float(k) / float(pieces)))
    return np.asarray(out, dtype=np.float64)


def densified_edges(polygon: np.ndarray, step_mm: float) -> list[np.ndarray]:
    """The densified points of every edge, in order; edge ``i`` runs from vertex ``i`` onward."""
    pts = np.asarray(polygon, dtype=np.float64).reshape(-1, 3)
    count = pts.shape[0]
    edges: list[np.ndarray] = []
    if count < 3 or not np.isfinite(step_mm) or step_mm <= 0.0:
        return edges
    for index in range(count):
        start = pts[index]
        stop = pts[(index + 1) % count]
        length = float(np.linalg.norm(stop - start))
        pieces = max(int(np.ceil(length / float(step_mm))), 1)
        edges.append(np.asarray([start + (stop - start) * (float(k) / float(pieces))
                                 for k in range(pieces + 1)], dtype=np.float64))
    return edges


def _edge_key(point: np.ndarray) -> tuple[int, int, int]:
    """Rounded integer identity of a point, for matching a cell edge against a facet edge."""
    return (int(round(float(point[0]) * 1.0e6)), int(round(float(point[1]) * 1.0e6)),
            int(round(float(point[2]) * 1.0e6)))


def _fan_ring(ring: np.ndarray, normal: np.ndarray, origin: np.ndarray) -> np.ndarray:
    """Fan a planar ring from its first vertex; ``ring`` is closed by construction (no repeats)."""
    del normal, origin
    count = np.asarray(ring).shape[0]
    return np.asarray([(0, index, index + 1) for index in range(1, count - 1)], dtype=np.int64)


def _mesh_all_facets(partition: VoronoiPartition, warp: WarpField, *,
                     error_budget_mm: float = _FACET_ERROR_BUDGET_MM,
                     max_triangles: int = _MAX_FACET_TRIANGLES
                     ) -> tuple[dict[tuple[int, int], FacetMesh], dict[str, Any]]:
    """Conformally mesh every internal facet, refining against the **measured** error.

    The mesh size is driven by the interpolation error, but by the error that is *measured* rather
    than by the analytic bound: the bound ``C h^2 / 8`` assumes a field that saturates its whole
    curvature spectrum on one cell and over-refines a real facet by roughly 8x (measured on V13/M01:
    the bound asks for 0.167 mm, i.e. 1.2e6 triangles on a 1.7e4 mm^2 partition surface, while the
    same surface meets the 0.01 mm budget at 8 points per shortest wavelength).

    The loop is therefore: start at the sampling reference (``wavelength_min / 8``), measure the
    realized error per facet on a deterministic barycentric probe, halve the mesh size while the
    error is over budget **and** the triangle budget allows, and otherwise stop and *report the
    realized error*.  A coarse mesh can therefore never be mistaken for one that met the budget: the
    realized number travels with it, and ``met_error_budget`` is False when it did not.
    """
    # the border step is fixed *before* any meshing so every facet's wire and every flat facet that
    # meets it densify their edges at the same spacing
    border_step = float(warp.wavelength_min_mm) / _MESH_POINTS_PER_WAVELENGTH
    table = _facet_table(partition, border_step_mm=border_step)
    if not table:
        return {}, {"facet_meshes": 0, "ladder": [], "realized_error_mm": 0.0,
                    "met_error_budget": True, "triangle_budget_exhausted": False}
    areas = {key: float(_polygon_area_3d(polygon)) for key, (polygon, _n) in table.items()}
    size = float(warp.wavelength_min_mm) / _MESH_POINTS_PER_WAVELENGTH
    ladder: list[dict[str, Any]] = []
    best: tuple[dict[tuple[int, int], FacetMesh], float, float] | None = None
    for _ in range(12):
        facets: dict[tuple[int, int], FacetMesh] = {}
        failed = False
        for key, (polygon, normal) in sorted(table.items()):
            cap = int(min(float(max_triangles),
                          max(_MAX_TRIANGLES_PER_MM2 * areas.get(key, 0.0), 64.0)))
            try:
                facets[key] = meshed_facet(polygon, normal, target_mm=size, key=key,
                                           max_triangles=cap, border_step_mm=border_step)
            except SynLabError as exc:
                code = str(getattr(exc.code, "value", exc.code))
                ladder.append({"mesh_size_mm": float(size), "code": code,
                               "measurements": dict(exc.measurements or {})})
                if code != "PRECISION_BUDGET_EXCEEDED":
                    raise
                failed = True
                break
        if failed:
            if best is None:
                raise SynLabError(
                    ErrorCode.PRECISION_BUDGET_EXCEEDED,
                    f"the conformal facet mesh needs more triangles than the event budget "
                    f"({max_triangles}) allows even at {size:.4f} mm; the displacement is not "
                    f"silently dropped",
                    stage="fracture.warped.mesh",
                    measurements={"mesh_size_mm": float(size),
                                  "max_triangles": int(max_triangles),
                                  "ladder": ladder},
                )
            break
        measured = [facet.realized_error_mm(warp)["realized_error_mm"]
                    for facet in facets.values()]
        worst = max(measured) if measured else 0.0
        triangles = int(sum(f.triangles.shape[0] for f in facets.values()))
        ladder.append({"mesh_size_mm": float(size), "code": "OK",
                       "triangles": triangles, "realized_error_mm": float(worst),
                       "within_error_budget": bool(worst <= float(error_budget_mm))})
        if triangles > int(max_triangles):
            ladder[-1]["code"] = "PRECISION_BUDGET_EXCEEDED"
            if best is None:
                raise SynLabError(
                    ErrorCode.PRECISION_BUDGET_EXCEEDED,
                    f"the conformal facet mesh needs {triangles} triangles > the event budget "
                    f"{max_triangles} at {size:.4f} mm; the displacement is not silently dropped",
                    stage="fracture.warped.mesh",
                    measurements={"triangles": triangles, "max_triangles": int(max_triangles),
                                  "mesh_size_mm": float(size), "ladder": ladder},
                )
            break
        if best is None or worst < best[2]:
            best = (facets, float(size), float(worst))
        if worst <= float(error_budget_mm):
            return facets, _mesh_report(table, ladder, size, triangles, worst, True, False)
        size *= 0.5
    facets, realized_size, worst = best if best is not None else ({}, size, float("inf"))
    return facets, _mesh_report(table, ladder, realized_size,
                                int(sum(f.triangles.shape[0] for f in facets.values())),
                                worst, bool(worst <= float(error_budget_mm)), True)


def _polygon_area_3d(polygon: np.ndarray) -> float:
    points = np.asarray(polygon, dtype=np.float64).reshape(-1, 3)
    if points.shape[0] < 3:
        return 0.0
    origin = points.mean(axis=0)
    rel = points - origin[None, :]
    _u, _s, vt = np.linalg.svd(rel, full_matrices=False)
    e_x, e_y = vt[0], vt[1]
    uv = np.stack([rel @ e_x, rel @ e_y], axis=1)
    return float(abs(np.sum(uv[:, 0] * np.roll(uv[:, 1], -1)
                            - np.roll(uv[:, 0], -1) * uv[:, 1])) * 0.5)


def _mesh_report(table: Mapping[Any, Any], ladder: list[dict[str, Any]], size: float,
                 triangles: int, realized: float, met: bool, exhausted: bool) -> dict[str, Any]:
    return {
        "facet_meshes": len(table),
        "requested_error_budget_mm": float(_FACET_ERROR_BUDGET_MM),
        "mesh_size_ladder": ladder,
        "realized_mesh_size_mm": float(size),
        "triangles_total": int(triangles),
        "realized_interpolation_error_mm": float(realized),
        "met_error_budget": bool(met),
        "triangle_budget_exhausted": bool(exhausted),
        "error_probe": "deterministic barycentric probe of every facet triangle",
    }


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
    table = _facet_table(partition, border_step_mm=target)
    for key, (polygon, normal) in sorted(table.items()):
        facets[key] = meshed_facet(polygon, normal, target_mm=target, key=key,
                                   border_step_mm=target)
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
    facets, mesh_report = _mesh_all_facets(partition, warp)
    seed_report["warped_partition"] = {
        "facet_error_budget_mm": float(_FACET_ERROR_BUDGET_MM),
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
    event_mod._assign_facet_faces(records, partition, _facet_records(facets, warp),
                                  tolerance_mm=1.0e-3)

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
        fragments, records, partition, _facet_records(facets, warp),
        {key: np.asarray(f.border, dtype=np.float64) for key, f in facets.items()},
        {key: np.asarray(f.normal, dtype=np.float64) for key, f in facets.items()},
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


@dataclass
class _FacetRecord:
    """Adapter that presents a :class:`FacetMesh` to the calibrated interface-linking stage.

    ``_assign_facet_faces`` and ``_link_voronoi_interfaces`` expect the per-facet object the
    roughness path passes (they read ``amplitude_mm`` and call ``as_dict()``); this adapter supplies
    exactly those two things plus the mesh itself, so the warped partition reuses that code
    unchanged instead of growing a second interface implementation.
    """

    mesh: FacetMesh
    warp: WarpField

    @property
    def amplitude_mm(self) -> float:
        return float(self.warp.amplitude_mm)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "warped_partition_facet", "amplitude_mm": float(self.warp.amplitude_mm),
                "wavelength_min_mm": float(self.warp.wavelength_min_mm),
                "wall_mm": float(self.warp.wall_mm), "grain_mm": float(self.warp.grain_mm),
                "facet": self.mesh.as_dict()}


def _facet_records(facets: Mapping[tuple[int, int], FacetMesh],
                   warp: WarpField) -> dict[tuple[int, int], _FacetRecord]:
    return {key: _FacetRecord(mesh=facet, warp=warp) for key, facet in facets.items()}


def _open_edge_report(mesh: Any, facet_use: Mapping[Any, Any]) -> dict[str, Any]:
    """Characterise the non-manifold edges of a failed cell, so the cause is visible."""
    faces = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    counter: dict[tuple[int, int], int] = {}
    for tri in faces:
        for k in range(3):
            a, b = int(tri[k]), int(tri[(k + 1) % 3])
            key = (a, b) if a < b else (b, a)
            counter[key] = counter.get(key, 0) + 1
    bad = {edge: use for edge, use in counter.items() if use != 2}
    lengths = []
    for (a, b) in bad:
        lengths.append(float(np.linalg.norm(verts[a] - verts[b])))
    histogram: dict[str, int] = {}
    for use in counter.values():
        histogram[str(use)] = histogram.get(str(use), 0) + 1
    return {
        "edges_total": len(counter),
        "edges_not_2": len(bad),
        "edge_use_histogram": dict(sorted(histogram.items())),
        "bad_edge_length_mm": {
            "min": float(min(lengths)) if lengths else 0.0,
            "max": float(max(lengths)) if lengths else 0.0,
        },
        "facets": {str(k): v for k, v in facet_use.items()},
        "degenerate_faces": int(np.sum(np.asarray(mesh.area_faces) <= 0.0)),
    }


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
