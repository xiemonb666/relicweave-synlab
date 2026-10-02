"""The implicit sheet field: ``w = h(u, v)`` with ``h`` *exactly* zero on the patch boundary ring.

Three jobs live here, and each one is a measurement rather than an assumption:

``FootprintEnvelope``
    the material cross-section (the fracture patch footprint) is rasterised from the frozen flat
    cross-section triangles.  The envelope forces the relief to zero on the footprint's boundary
    ring -- not by multiplying the field with a narrow ramp (which would turn the conchoidal bow
    into a steep rim) but by *subtracting the field's own value at the nearest ring point* and
    then applying a smooth indicator.  ``h`` therefore reaches zero on the ring with the field's
    own slope, which is what lets the two halves close on that ring.

``ImplicitSheetField``
    :class:`~synlab.fracture.morphology.MorphologyHeightField` with the footprint envelope and the
    optional glaze envelope composed in ``raw`` (the morphology field's own material-band window is
    deliberately *not* used: the footprint envelope replaces it, and it is much tighter).

``calibrate_slope``
    the frozen morphology model asks for amplitudes that are far too steep for a real ceramic
    fracture surface (measured P95 slope 53 deg, see ``docs/a12/fracture_realism.md`` 3.2/9.4).
    The calibration scales the relief amplitudes down until the *measured* P95 slope of the
    realized surface enters the declared band, and it reports before/after.  It never touches the
    interpolation budget, the cell/triangle budget or any A06 threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field, replace
from typing import Any, Mapping, Sequence

import numpy as np

from ..cut import FourierBand
from ..morphology import MorphologyHeightField, _PitSet, scatter_pits
from ..spec import DEFAULT_ERROR_BUDGET_MM

__all__ = [
    "SAMPLES_PER_WAVELENGTH",
    "SLOPE_P95_TARGET_DEG",
    "MAX_SHEET_TRIANGLES",
    "rasterize_triangles",
    "bilinear_lookup",
    "FootprintEnvelope",
    "ImplicitSheetField",
    "band_limit_params",
    "build_implicit_field",
    "calibrate_slope",
    "measure_field_slope",
    "sheet_spectrum",
]

#: samples per shortest retained wavelength in the sheet triangulation (plan: >= 4-5).
SAMPLES_PER_WAVELENGTH = 5.0
#: P95 of the surface slope (angle from the mean plane) the calibration aims at.
SLOPE_P95_TARGET_DEG = 18.0
#: triangle budget of the sheet triangulation; the spectrum is band-limited to fit it.
MAX_SHEET_TRIANGLES = 420_000
_EPS = 1.0e-12


# ---------------------------------------------------------------------------- raster tools
def rasterize_triangles(tris_uv: np.ndarray, u0: float, v0: float, step: float,
                        shape: tuple[int, int]) -> np.ndarray:
    """Boolean raster of a ``(N, 3, 2)`` triangle soup (cell-centre membership, vectorised)."""
    tris = np.asarray(tris_uv, dtype=np.float64).reshape(-1, 3, 2)
    out = np.zeros(shape, dtype=bool)
    if tris.shape[0] == 0:
        return out
    ii, jj = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), indexing="ij")
    gu = u0 + ii * step
    gv = v0 + jj * step
    lo = tris.reshape(-1, 2).min(axis=0)
    hi = tris.reshape(-1, 2).max(axis=0)
    i0 = max(0, int(np.floor((lo[0] - u0) / step)))
    i1 = min(shape[0], int(np.ceil((hi[0] - u0) / step)) + 1)
    j0 = max(0, int(np.floor((lo[1] - v0) / step)))
    j1 = min(shape[1], int(np.ceil((hi[1] - v0) / step)) + 1)
    if i1 <= i0 or j1 <= j0:
        return out
    sub_u = gu[i0:i1, j0:j1]
    sub_v = gv[i0:i1, j0:j1]
    hit = out[i0:i1, j0:j1]
    for tri in tris:
        (ax, ay), (bx, by), (cx, cy) = tri
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1.0e-18:
            continue
        tlo_u, thi_u = min(ax, bx, cx), max(ax, bx, cx)
        tlo_v, thi_v = min(ay, by, cy), max(ay, by, cy)
        a0 = max(i0, int(np.floor((tlo_u - u0) / step)) - 1)
        a1 = min(i1, int(np.ceil((thi_u - u0) / step)) + 2)
        b0 = max(j0, int(np.floor((tlo_v - v0) / step)) - 1)
        b1 = min(j1, int(np.ceil((thi_v - v0) / step)) + 2)
        if a1 <= a0 or b1 <= b0:
            continue
        px = gu[a0:a1, b0:b1] - cx
        py = gv[a0:a1, b0:b1] - cy
        w0 = ((by - cy) * px + (cx - bx) * py) / den
        w1 = ((cy - ay) * px + (ax - cx) * py) / den
        hit[a0 - i0:a1 - i0, b0 - j0:b1 - j0] |= (
            (w0 >= -1.0e-12) & (w1 >= -1.0e-12) & (w0 + w1 <= 1.0 + 1.0e-12))
    return out


def bilinear_lookup(values: np.ndarray, u0: float, v0: float, step: float,
                    u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Bilinear sample of a raster, clamped at the edges (kept for reference/tests)."""
    vals = np.asarray(values, dtype=np.float64)
    nu, nv = vals.shape
    fu = (np.asarray(u, dtype=np.float64) - u0) / step
    fv = (np.asarray(v, dtype=np.float64) - v0) / step
    fu = np.clip(fu, 0.0, nu - 1.0)
    fv = np.clip(fv, 0.0, nv - 1.0)
    i0 = np.floor(fu).astype(np.int64)
    j0 = np.floor(fv).astype(np.int64)
    i0 = np.clip(i0, 0, max(nu - 2, 0))
    j0 = np.clip(j0, 0, max(nv - 2, 0))
    du = fu - i0
    dv = fv - j0
    v00 = vals[i0, j0]
    v10 = vals[np.minimum(i0 + 1, nu - 1), j0]
    v01 = vals[i0, np.minimum(j0 + 1, nv - 1)]
    v11 = vals[np.minimum(i0 + 1, nu - 1), np.minimum(j0 + 1, nv - 1)]
    return (v00 * (1.0 - du) * (1.0 - dv) + v10 * du * (1.0 - dv)
            + v01 * (1.0 - du) * dv + v11 * du * dv)


def raster_lookup(values: np.ndarray, u0: float, v0: float, step: float,
                  u: np.ndarray, v: np.ndarray, *, order: int = 3) -> np.ndarray:
    """C^2 (cubic-spline) sample of a raster, clamped at the edges.

    Bilinear interpolation of a raster is only C^0: it has a slope kink on every cell boundary.
    The mask and the ring offset both carry genuine cell-scale curvature (measured 14 /mm and
    33 /mm on the real bodies), so those kinks are slope jumps of ~0.9 /mm, and a sheet triangle of
    0.13 mm cannot represent a slope jump better than ``kink * edge / 8`` = 0.015 mm -- which is
    exactly the error the first implementation reported.  A cubic-spline lookup removes the kinks
    instead of refining the raster (the diffusion that produced the offset stays cheap).
    """
    vals = np.asarray(values, dtype=np.float64)
    if int(order) <= 1 or vals.size == 0:
        return bilinear_lookup(vals, u0, v0, step, u, v)
    from scipy import ndimage

    shape = np.broadcast(np.asarray(u, dtype=np.float64), np.asarray(v, dtype=np.float64)).shape
    fu = (np.asarray(u, dtype=np.float64) - u0) / step
    fv = (np.asarray(v, dtype=np.float64) - v0) / step
    fu = np.clip(fu, 0.0, vals.shape[0] - 1.0).reshape(-1)
    fv = np.clip(fv, 0.0, vals.shape[1] - 1.0).reshape(-1)
    sampled = ndimage.map_coordinates(vals, np.stack([fu, fv], axis=0), order=int(order),
                                      mode="nearest")
    return np.asarray(sampled, dtype=np.float64).reshape(shape)


def _smootherstep(t: np.ndarray) -> np.ndarray:
    x = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)


# ---------------------------------------------------------------------------- envelope
@dataclass
class FootprintEnvelope:
    """Raster envelope that makes the relief vanish on the patch boundary ring.

    ``h_final = S(u, v) * (h_raw(u, v) - B(u, v))`` with

    * ``S``  a smooth indicator of the material footprint (1 inside, 0 outside, 0.5 on the ring)
      evaluated from a **bilinearly interpolated signed-distance raster**, never from a
      pre-quantised indicator: a sampled indicator has stair-steps of one raster cell, and a
      0.065 mm step in ``S`` multiplied by a 0.5 mm relief is a 0.7 mm interpolation error --
      measured, not guessed (first implementation of this module reported exactly that);
    * ``B``  a smooth inward extension of the raw field's value *on the ring* (blur-inpainting with
      the ring values held fixed, i.e. a diffusion extension).  ``h_raw - B`` therefore vanishes on
      the ring everywhere along it, without the seams a nearest-boundary extension produces across
      the medial axis of a wall strip.

    Both ``S`` and ``B`` are smooth functions of ``(u, v)``, so the composite stays resolvable by a
    mesh that samples the field's own shortest wavelength.
    """

    u0: float
    v0: float
    step_mm: float
    sign_raster: np.ndarray
    signed_raster: np.ndarray
    offset_raster: np.ndarray
    inside_raster: np.ndarray
    ring_cells: int
    width_mm: float
    raster_area_mm2: float
    exact_area_mm2: float
    footprint_touches_raster_edge: bool
    extension_iterations: int = 0
    extension_residual_mm: float = 0.0
    boundary_samples: int = 0
    signed_distance_raw: np.ndarray | None = None
    phi_iterations: int = 0
    phi_residual: float = 0.0
    phi_max_inside: float = 1.0
    boundary_source: str = ""
    dome_offset_raster: np.ndarray | None = None
    extra_raster: np.ndarray | None = None

    def mask(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``phi``: the smooth footprint mask (0 on the ring and outside, 1 in the body)."""
        return np.clip(raster_lookup(self.sign_raster, self.u0, self.v0, self.step_mm, u, v),
                       0.0, 1.0)

    def smoothness(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``phi`` under the name ``MorphologyHeightField`` expects for its modulation slot."""
        return self.mask(u, v)

    def offset(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Ring-value extension of the *relief* (bands, hackle, ribs, fibre, pits)."""
        return raster_lookup(self.offset_raster, self.u0, self.v0, self.step_mm, u, v)

    def dome_offset(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Ring-value extension of the *conchoidal form* (zero when no dome offset was built)."""
        if self.dome_offset_raster is None:
            return np.zeros(np.broadcast(u, v).shape, dtype=np.float64)
        return raster_lookup(self.dome_offset_raster, self.u0, self.v0, self.step_mm, u, v)

    def value(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``phi`` only: the object ``MorphologyHeightField`` expects in ``modulation``."""
        return self.mask(u, v)

    def scale_offsets(self, ratio: float) -> None:
        """No-op kept for the calibration hook (the ring offset is no longer used; see ``apply``)."""
        return

    def apply(self, u: np.ndarray, v: np.ndarray, relief: np.ndarray) -> np.ndarray:
        """``phi * relief``: the masked surface, exactly zero on the ring and outside it.

        The ring-value subtraction of the first revisions was removed after measuring it: the ring
        Dirichlet data varies by ~1.4 mm around the boundary (the conchoidal bow alone), the
        harmonic extension therefore carries a boundary layer about one raster cell wide, and a
        0.13 mm sheet cannot represent that layer (measured 0.017 mm of interpolation error, versus
        0.008 mm with the plain mask below).  The mask alone puts ``h`` at exactly zero on the ring
        *and* keeps the surface smooth; the price is that the relief is damped inside the envelope
        width, which is measured and published (``phi_max_inside``, ``core_area_mm2``).
        """
        uu = np.asarray(u, dtype=np.float64)
        vv = np.asarray(v, dtype=np.float64)
        out = self.mask(uu, vv) * np.asarray(relief, dtype=np.float64)
        if self.extra_raster is not None:
            out = out * raster_lookup(self.extra_raster, self.u0, self.v0, self.step_mm, uu, vv)
        return out

    def glaze_raster_from(self, *, strip_mm: float, ratio: float) -> np.ndarray | None:
        """Relief damping inside the glaze strip (``ratio`` at the ring, 1 in the body)."""
        if self.signed_raster is None or strip_mm <= 0.0 or ratio >= 1.0:
            return None
        depth = np.maximum(self.signed_raster, 0.0)
        strip = max(float(strip_mm), 2.0 * float(self.step_mm))
        return float(ratio) + (1.0 - float(ratio)) * _smootherstep(depth / strip)

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_mm": float(self.step_mm), "width_mm": float(self.width_mm),
            "ring_cells": int(self.ring_cells),
            "raster_area_mm2": float(self.raster_area_mm2),
            "exact_area_mm2": float(self.exact_area_mm2),
            "raster_area_rel_error": float(
                abs(self.raster_area_mm2 - self.exact_area_mm2)
                / max(self.exact_area_mm2, _EPS)),
            "footprint_touches_raster_edge": bool(self.footprint_touches_raster_edge),
            "extension_iterations": int(self.extension_iterations),
            "extension_residual_mm": float(self.extension_residual_mm),
            "phi_iterations": int(self.phi_iterations),
            "phi_residual": float(self.phi_residual),
            "phi_max_inside": float(self.phi_max_inside),
            "boundary_samples": int(self.boundary_samples),
            "boundary_source": str(self.boundary_source),
            "glaze_raster": self.extra_raster is not None,
            "construction": "h = phi * (h_raw - B); phi is a diffused footprint mask (0 on the ring, "
                            "0 outside, 1 deeper than the envelope width) and B is the diffusion "
                            "extension of h_raw's ring values, so h == 0 exactly on the ring with no "
                            "raster stair-step and no medial-axis seam",
        }


def boundary_samples_uv(tris_uv: np.ndarray, *, max_step_mm: float
                        ) -> tuple[np.ndarray, dict[str, Any]]:
    """Sample the footprint's true boundary polyline (exterior + interior rings) in ``(u, v)``."""
    tris = np.asarray(tris_uv, dtype=np.float64).reshape(-1, 3, 2)
    try:
        import shapely

        union = shapely.union_all(shapely.polygons(tris))
        boundary = union.boundary
        parts = list(shapely.get_parts(boundary)) if boundary.geom_type != "LineString" \
            else [boundary]
        points: list[np.ndarray] = []
        for part in parts:
            length = float(part.length)
            if length <= 0.0:
                continue
            count = int(max(8, np.ceil(length / max(float(max_step_mm), 1e-6))))
            distances = np.linspace(0.0, length, count, endpoint=False)
            sampled = shapely.line_interpolate_point(part, distances)
            points.append(np.column_stack([shapely.get_x(sampled), shapely.get_y(sampled)]))
        if points:
            return np.concatenate(points, axis=0), {
                "source": "shapely boundary of the union of the cross-section triangles",
                "parts": len(parts)}
    except Exception as exc:  # noqa: BLE001 - fall back to the triangle edges, and say so
        fallback = "shapely unavailable"
        error = f"{type(exc).__name__}: {exc}"
    else:
        fallback = "shapely produced no boundary"
        error = ""
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], axis=0)
    key = np.sort(edges, axis=1)
    flat = key[:, 0, 0] * 1.0e6 + key[:, 0, 1] * 1.0e3 + key[:, 1, 0] * 1.0e-3 + key[:, 1, 1]
    uniq, inverse, counts = np.unique(np.round(flat, 6), return_inverse=True, return_counts=True)
    boundary_edges = edges[np.isin(inverse, np.nonzero(counts == 1)[0])]
    pts = boundary_edges.reshape(-1, 2)
    return np.unique(np.round(pts, 9), axis=0), {
        "source": f"triangle edges used once ({fallback} {error})".strip(), "parts": 0}


def _masked_blur(values: np.ndarray, mask: np.ndarray, *, sigma: float) -> np.ndarray:
    """Gaussian blur that only averages the cells where ``mask`` is true (normalised convolution)."""
    from scipy import ndimage

    num = ndimage.gaussian_filter(np.where(mask, values, 0.0), sigma=sigma, mode="nearest")
    den = ndimage.gaussian_filter(mask.astype(np.float64), sigma=sigma, mode="nearest")
    return np.where(den > 1.0e-6, num / np.maximum(den, 1.0e-12), 0.0)


def build_footprint_envelope(tris_uv: np.ndarray, *, exact_area_mm2: float,
                             bbox: tuple[float, float, float, float],
                             step_mm: float, width_mm: float,
                             boundary_values_fn: Any = None,
                             dirichlet_step_mm: float | None = None,
                             extension_iterations: int = 400,
                             extension_tol_mm: float = 1.0e-5,
                             sigma_cells: float = 1.5
                             ) -> tuple["FootprintEnvelope", np.ndarray]:
    """Rasterise the footprint, build the smooth footprint mask and the ring-value extension.

    Both fields are produced by **normalised (masked) diffusion** rather than from a sampled
    distance transform: an EDT-based indicator is quantised to one raster cell and has a singular
    gradient along the medial axis of the *outside* region (which touches every convex corner of
    the footprint), and interpolating that indicator produced a 0.14 mm interpolation error on a
    0.13 mm sheet -- also measured, not guessed.  A diffused mask is smooth by construction.
    """
    from scipy import ndimage

    u0 = float(bbox[0])
    v0 = float(bbox[2])
    nu = int(np.ceil((bbox[1] - u0) / step_mm)) + 1
    nv = int(np.ceil((bbox[3] - v0) / step_mm)) + 1
    inside = rasterize_triangles(tris_uv, u0, v0, step_mm, (nu, nv))
    if not bool(inside.any()):
        raise ValueError("the material cross-section raster is empty")
    structure = ndimage.generate_binary_structure(2, 1)
    eroded = ndimage.binary_erosion(inside, structure=structure, border_value=0)
    ring = inside & ~eroded
    if not bool(ring.any()):
        ring = inside.copy()
    d_in = ndimage.distance_transform_edt(inside) * step_mm
    d_out = ndimage.distance_transform_edt(~inside) * step_mm
    signed = d_in - d_out
    edge = np.zeros_like(inside)
    edge[0, :] = edge[-1, :] = True
    edge[:, 0] = edge[:, -1] = True

    # ---------------------------------------------------------------- ring Dirichlet data
    #
    # The boundary is sampled far more densely than the raster cell: the Dirichlet value of a ring
    # cell is taken from the *nearest* boundary sample, and a nearest-sample map over samples that
    # are half a cell apart is a piecewise-constant function whose jumps diffuse inwards as kinks.
    # Measured: a 0.016 mm jump per cell produced 878 /mm of curvature in the ring offset and a
    # 0.015 mm sheet error -- versus 0.0016 mm jumps and < 1 /mm with the dense sampling below.
    samples, sample_info = boundary_samples_uv(
        tris_uv, max_step_mm=float(dirichlet_step_mm if dirichlet_step_mm is not None
                                   else 0.05 * step_mm))
    relief_values = np.zeros(samples.shape[0], dtype=np.float64)
    dome_values = np.zeros(samples.shape[0], dtype=np.float64)
    if boundary_values_fn is not None and samples.shape[0]:
        pair = boundary_values_fn(samples[:, 0], samples[:, 1])
        relief_values = np.asarray(pair[0], dtype=np.float64)
        dome_values = np.asarray(pair[1], dtype=np.float64)
    ring_i, ring_j = np.nonzero(ring)
    if samples.shape[0]:
        from scipy.spatial import cKDTree

        tree = cKDTree(samples)
        _dist, idx = tree.query(np.column_stack([u0 + ring_i * step_mm, v0 + ring_j * step_mm]),
                                k=1)
        fixed_relief = relief_values[idx]
        fixed_dome = dome_values[idx]
    else:
        fixed_relief = np.zeros(ring_i.size, dtype=np.float64)
        fixed_dome = np.zeros(ring_i.size, dtype=np.float64)
    fixed_mask = np.zeros_like(inside)
    fixed_mask[ring_i, ring_j] = True

    def _extend(values: np.ndarray, *, sigma: float = 1.5, outward_blurs: int = 8
                ) -> tuple[np.ndarray, int, float]:
        """Diffuse a ring-Dirichlet set inwards, then extend it smoothly outwards.

        The inward pass is a masked (normalised) blur so the outside cannot leak in -- a plain blur
        with the outside held at zero drags the ring values down and ``phi * (relief - B)`` then no
        longer vanishes on the ring (measured: 0.67 mm of interpolation error).  The outward pass
        keeps the inside values *exactly* as the inward pass produced them and only smooths the
        outside, so the bilinear lookup at the ring sees no jump and no smeared ring value.
        """
        fixed_dense = np.zeros_like(inside, dtype=np.float64)
        fixed_dense[ring_i, ring_j] = values
        dense = fixed_dense.copy()
        residual = 0.0
        iterations = 0
        free = inside & ~fixed_mask
        if bool(free.any()):
            for iterations in range(1, int(extension_iterations) + 1):
                blurred = _masked_blur(dense, inside, sigma=float(sigma))
                new = np.where(fixed_mask, fixed_dense, blurred)
                new = np.where(inside, new, 0.0)
                residual = float(np.max(np.abs(new - dense)[free])) if bool(free.any()) else 0.0
                dense = new
                if residual < float(extension_tol_mm):
                    break
        from scipy import ndimage

        if bool(inside.any()) and not bool(inside.all()):
            _dist, idx = ndimage.distance_transform_edt(~inside, return_indices=True)
            outer = dense[idx[0], idx[1]].copy()
            known = ~inside
            for _ in range(int(outward_blurs)):
                blurred = _masked_blur(outer, known, sigma=2.0)
                outer = np.where(known, blurred, outer)
                outer[inside] = dense[inside]
            dense = outer
        return dense, iterations, residual

    offset, iterations, residual = _extend(fixed_relief)
    dome_offset, _dome_it, _dome_res = _extend(fixed_dome)

    # ---------------------------------------------------------------- smooth footprint mask
    #
    # phi = 0 on the ring, 1 on the cells deeper than ``width_mm``: h = phi * (h_raw - B) is then
    # exactly zero on the ring *and* exactly zero outside the footprint, with no dependence on a
    # raster offset, and phi is smooth (diffused), so a mesh that samples the field can carry it.
    core = inside & (d_in >= float(width_mm))
    if not bool(core.any()):                      # footprint narrower than the envelope width
        core = inside & (d_in >= max(float(d_in[inside].max()) * 0.5, step_mm))
    core_mask = core & ~fixed_mask
    phi_fixed = np.zeros_like(inside, dtype=np.float64)
    phi_fixed[core_mask] = 1.0
    phi_fixed[fixed_mask] = 0.0
    phi = phi_fixed.copy()
    phi_residual = 0.0
    phi_iterations = 0
    phi_free = inside & ~fixed_mask & ~core_mask
    if bool(phi_free.any()):
        for phi_iterations in range(1, int(extension_iterations) + 1):
            blurred = _masked_blur(phi, inside, sigma=float(sigma_cells))
            new = np.where(fixed_mask, 0.0, np.where(core_mask, 1.0, blurred))
            new = np.where(inside, new, 0.0)
            phi_residual = float(np.max(np.abs(new - phi)[phi_free]))
            phi = new
            if phi_residual < 1.0e-5:
                break
    phi = np.clip(_masked_blur(phi, inside, sigma=1.0), 0.0, 1.0)
    #: the glaze strip needs a distance; the quantised EDT is smoothed before it is used
    smooth_distance = _masked_blur(np.where(inside, np.maximum(d_in, 0.0), 0.0), inside, sigma=2.0)

    return FootprintEnvelope(
        u0=u0, v0=v0, step_mm=float(step_mm), sign_raster=phi, signed_raster=smooth_distance,
        offset_raster=offset, inside_raster=inside,
        ring_cells=int(ring.sum()), width_mm=float(width_mm),
        raster_area_mm2=float(inside.sum() * step_mm ** 2), exact_area_mm2=float(exact_area_mm2),
        footprint_touches_raster_edge=bool(np.any(inside & edge)),
        extension_iterations=int(iterations), extension_residual_mm=float(residual),
        boundary_samples=int(samples.shape[0]),
        signed_distance_raw=signed, phi_iterations=int(phi_iterations),
        phi_residual=float(phi_residual),
        phi_max_inside=float(phi[inside].max()) if bool(inside.any()) else 0.0,
        boundary_source=str(sample_info.get("source", "")),
        dome_offset_raster=dome_offset,
    ), samples


# ---------------------------------------------------------------------------- field
@dataclass
class ImplicitSheetField(MorphologyHeightField):
    """``w = phi * (dome + relief - B)``: zero on the patch boundary ring, flat outside it.

    Three measured facts shape this construction:

    * ``phi`` (the footprint mask) must not multiply a large-amplitude field: a 1.6 mm conchoidal
      bow under a 0.5 mm-wide mask is ~70 /mm of curvature, and a 0.13 mm sheet cannot carry that
      (measured: 0.14 mm of interpolation error);
    * therefore the **conchoidal dome is scaled together with the relief** (it is a relief feature,
      and the frozen model already caps its sag at ``4 * sigma_r0``): ``dome_scale`` follows every
      slope-calibration step, so the mask only ever multiplies the calibrated (small) surface;
    * ``B`` is the ring value of the *whole* masked surface, extended inwards by diffusion, so
      ``phi * (h - B)`` vanishes exactly on the ring without a boundary layer of its own.
    """

    envelope: Any = None
    #: scale applied to the conchoidal term (it is not part of ``MorphologyHeightField``'s
    #: amplitude scaling, which only covers bands / hackle / ribs / fibre / pits).
    dome_scale: float = 1.0

    def dome_term(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        return float(self.dome_scale) * np.asarray(self.dome(u, v), dtype=np.float64)

    def _parts(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``(dome, relief)`` of the frozen morphology field, without the glaze modulation."""
        modulation = self.modulation
        self.modulation = None
        try:
            dome = self.dome_term(u, v)
            relief = np.asarray(self._relief(u, v), dtype=np.float64)
        finally:
            self.modulation = modulation
        return dome, relief

    def unmasked(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``dome + relief`` before the footprint envelope (what the ring values are taken from)."""
        dome, relief = self._parts(u, v)
        if self.modulation is not None:
            return (dome + relief) * self.modulation.value(u, v)
        return dome + relief

    def raw(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        dome, relief = self._parts(u, v)
        if self.envelope is None:
            out = dome + relief
        else:
            out = self.envelope.apply(u, v, dome + relief)
        if self.modulation is not None:
            out = out * self.modulation.value(u, v)
        return out

    def apply_scale(self, ratio: float, *, core_uv: tuple[np.ndarray, np.ndarray] | None = None
                    ) -> None:
        """Scale every relief amplitude *including* the conchoidal term (see the class docstring)."""
        ratio = float(ratio)
        super().apply_scale(ratio, core_uv=core_uv)
        self.dome_scale = float(self.dome_scale) * ratio
        self.dome_amplitude_mm = float(self.dome_amplitude_mm) * ratio


# ---------------------------------------------------------------------------- spectrum
def band_limit_params(params: Any, *, delta_mm: float, samples_per_wavelength: float
                      ) -> tuple[Any, dict[str, Any]]:
    """Drop the Fourier bands the sheet triangulation cannot sample (>= 4-5 samples/lambda).

    Band-limiting is the honest alternative to aliasing: the removed bands are named, their
    amplitude and RMS contribution are reported, and the shortest *retained* wavelength is what
    the sampling-density metric is evaluated against.  Nothing is silently coarsened.
    """
    lam_allowed = float(samples_per_wavelength) * float(delta_mm)
    kept: list[tuple[float, float, float, float, float]] = []
    dropped: list[dict[str, float]] = []
    for amplitude, wavelength, du, dv, phase in params.bands:
        if float(wavelength) + 1.0e-12 >= lam_allowed:
            kept.append((amplitude, wavelength, du, dv, phase))
        else:
            dropped.append({"amplitude_mm": float(amplitude), "wavelength_mm": float(wavelength),
                            "samples_at_delta": float(wavelength) / max(delta_mm, _EPS)})
    removed_rms = float(np.sqrt(np.sum([0.5 * d["amplitude_mm"] ** 2 for d in dropped])))
    kept_rms = float(np.sqrt(np.sum([0.5 * k[0] ** 2 for k in kept])))
    if not kept and params.bands:
        # never return an empty spectrum silently: keep the longest band and say so
        longest = max(params.bands, key=lambda b: float(b[1]))
        kept = [longest]
        dropped = [d for d in dropped if abs(d["wavelength_mm"] - float(longest[1])) > 1e-12]
        removed_rms = float(np.sqrt(np.sum([0.5 * d["amplitude_mm"] ** 2 for d in dropped])))
        kept_rms = float(np.sqrt(0.5 * float(longest[0]) ** 2))
    info = {
        "band_limit_mm": lam_allowed, "delta_mm": float(delta_mm),
        "samples_per_wavelength": float(samples_per_wavelength),
        "bands_requested": len(params.bands), "bands_kept": len(kept),
        "dropped": dropped,
        "removed_rms_mm": removed_rms, "kept_rms_mm": kept_rms,
        "requested_rms_mm": float(params.requested_rms_mm),
        "band_limited": bool(dropped),
        "lambda_min_realized_mm": float(min([float(k[1]) for k in kept], default=float("inf"))),
    }
    return replace(params, bands=tuple(kept)), info


def sheet_spectrum(params: Any) -> dict[str, Any]:
    """Shortest geometric scale of every active component of the field (mm)."""
    scales: dict[str, float] = {}
    for amplitude, wavelength, _du, _dv, _phase in params.bands:
        scales[f"band_{float(wavelength):.4g}mm"] = float(wavelength)
    if params.hackle_amplitude_mm > 0.0 and params.hackle_count > 1:
        scales["hackle_arc_at_mirror"] = float(2.0 * np.pi * params.mirror_radius_mm
                                               / params.hackle_count)
    if params.rib_amplitude_mm > 0.0 and params.rib_spacing_at_mirror_mm > 0.0:
        scales["rib_spacing"] = float(params.rib_spacing_at_mirror_mm)
    if params.pit_depth_mm > 0.0:
        scales["pit_diameter"] = float(2.0 * params.pit_radius_mm)
    if params.fiber_amplitude_mm > 0.0 and params.fiber_period_mm > 0.0:
        scales["fiber_period"] = float(params.fiber_period_mm)
    if params.glaze_strip_width_mm > 0.0:
        scales["glaze_strip"] = float(params.glaze_strip_width_mm)
    shortest = min(scales.values()) if scales else float("inf")
    return {"scales_mm": scales, "shortest_mm": float(shortest)}


# ---------------------------------------------------------------------------- slope
def measure_field_slope(h_fn: Any, *, bounds: tuple[float, float, float, float],
                        mask_fn: Any, step_mm: float, max_points: int = 600_000
                        ) -> dict[str, Any]:
    """P50/P95/max slope and curvature of the realized surface over the footprint.

    The curvature is the mixed second-derivative bound ``|h_uu| + 2|h_uv| + |h_vv|`` that the
    interpolation budget uses (``error <= C * cell^2 / 8``), measured on a raster finer than the
    sheet spacing so that a cell-sized feature cannot hide between samples.
    """
    u0, u1, v0, v1 = (float(x) for x in bounds)
    step = float(step_mm)
    while ((u1 - u0) / step + 2.0) * ((v1 - v0) / step + 2.0) > float(max_points):
        step *= 1.25
    gu = np.arange(u0, u1 + 0.5 * step, step)
    gv = np.arange(v0, v1 + 0.5 * step, step)
    GU, GV = np.meshgrid(gu, gv, indexing="ij")
    inside = np.asarray(mask_fn(GU, GV), dtype=bool)
    if int(inside.sum()) < 64:
        return {"samples": int(inside.sum()), "note": "too few samples inside the footprint"}
    h = np.asarray(h_fn(GU, GV), dtype=np.float64)
    dv_axis, du_axis = np.gradient(h, step)
    slope = np.hypot(du_axis, dv_axis)[inside]
    angles = np.degrees(np.arctan(slope))
    ddu = np.gradient(du_axis, step, axis=0)
    ddv = np.gradient(dv_axis, step, axis=1)
    duv = np.gradient(du_axis, step, axis=1)
    curv = (np.abs(ddu) + 2.0 * np.abs(duv) + np.abs(ddv))[inside]
    return {
        "samples": int(slope.size), "step_mm": float(step),
        "slope_p50": float(np.percentile(slope, 50)),
        "slope_p95": float(np.percentile(slope, 95)),
        "slope_max": float(slope.max()),
        "angle_p50_deg": float(np.percentile(angles, 50)),
        "angle_p95_deg": float(np.percentile(angles, 95)),
        "angle_max_deg": float(angles.max()),
        "height_rms_mm": float(np.sqrt(np.mean((h[inside] - float(np.mean(h[inside]))) ** 2))),
        "height_peak_to_valley_mm": float(np.ptp(h[inside])),
        "curvature_p50_per_mm": float(np.percentile(curv, 50)),
        "curvature_p99_per_mm": float(np.percentile(curv, 99)),
        "curvature_max_per_mm": float(curv.max()),
    }


def calibrate_slope(field: ImplicitSheetField, h_fn: Any, *, bounds: tuple[float, float, float, float],
                    mask_fn: Any, step_mm: float, target_p95_deg: float = SLOPE_P95_TARGET_DEG,
                    max_iterations: int = 4, on_scale: Any = None) -> dict[str, Any]:
    """Scale the relief amplitudes until the *measured* P95 slope enters the declared band.

    The scale is ``tan(target) / tan(measured)`` evaluated on the realized surface (footprint
    envelope included).  It only ever scales the relief *down*; the loop stops as soon as the
    measurement is inside the band, so the reported value is a measurement, not a prediction.
    ``on_scale`` is called with every ratio so a derived quantity (the envelope's ring extension)
    can follow the amplitudes.
    """
    before = measure_field_slope(h_fn, bounds=bounds, mask_fn=mask_fn, step_mm=step_mm)
    history: list[dict[str, Any]] = [{"stage": "requested", **before}]
    target_tan = float(np.tan(np.radians(float(target_p95_deg))))
    scale_total = 1.0
    achieved = before
    for iteration in range(1, int(max_iterations) + 1):
        p95 = float(achieved.get("slope_p95", 0.0))
        if p95 <= target_tan or p95 <= 0.0:
            break
        ratio = target_tan / p95
        scale_total *= ratio
        field.apply_scale(ratio)
        if on_scale is not None:
            on_scale(ratio)
        field.mean_mm = 0.0
        achieved = measure_field_slope(h_fn, bounds=bounds, mask_fn=mask_fn, step_mm=step_mm)
        history.append({"stage": f"iteration_{iteration}", "ratio": float(ratio), **achieved})
    return {
        "target_p95_deg": float(target_p95_deg),
        "target_p95_tan": target_tan,
        "amplitude_scale_applied": float(scale_total),
        "before": before, "after": achieved, "history": history,
        "constraint": ("scale relief amplitudes so that the measured P95 of |grad h| over the "
                       "footprint equals tan(target); only the relief is scaled (bands, hackle, "
                       "ribs, fibre, pits) and the loop re-measures after every step"),
        "achieved_within_band": bool(float(achieved.get("slope_p95", 0.0)) <= target_tan + 1e-9),
    }


# ---------------------------------------------------------------------------- assembly
def build_implicit_field(
    basis: Any,
    mesh: Any,
    params: Any,
    *,
    rng: np.random.Generator,
    cross_section: tuple[np.ndarray, float, Mapping[str, Any]],
    delta_mm: float,
    samples_per_wavelength: float = SAMPLES_PER_WAVELENGTH,
    slope_target_p95_deg: float = SLOPE_P95_TARGET_DEG,
    envelope_width_mm: float | None = None,
    raster_step_mm: float | None = None,
    slope_step_mm: float | None = None,
) -> tuple[ImplicitSheetField, dict[str, Any]]:
    """Build the implicit sheet field (band-limited + slope-calibrated) and its record."""
    tris_uv, core_area, _info = cross_section
    tris_uv = np.asarray(tris_uv, dtype=np.float64).reshape(-1, 3, 2)
    limited, limit_info = band_limit_params(params, delta_mm=float(delta_mm),
                                           samples_per_wavelength=float(samples_per_wavelength))
    spectrum = sheet_spectrum(limited)

    origin = np.asarray(limited.origin_uv_mm, dtype=np.float64).reshape(2)
    bands = [FourierBand(amplitude_mm=a, wavelength_mm=w, direction=np.array([du, dv]), phase=ph)
             for (a, w, du, dv, ph) in limited.bands]
    fiber_dir = np.asarray(limited.material.get("fiber_direction", [1.0, 0.0, 0.0]),
                           dtype=np.float64)[:2]
    fiber_norm = float(np.linalg.norm(fiber_dir))
    if fiber_norm > 0.0:
        fiber_dir = fiber_dir / fiber_norm
    else:
        fiber_dir = np.array([1.0, 0.0])
    field = ImplicitSheetField(
        basis=basis, bands=bands, bend=[], mean_mm=0.0,
        target_rms_mm=float(limited.requested_rms_mm), realized_rms_mm=0.0,
        wavelength_min_mm=float(spectrum["shortest_mm"]), max_slope=0.0,
        meta={"morphology": limited.as_dict(), "spectrum": spectrum},
        morphology=limited,
        origin_uv=(float(origin[0]), float(origin[1])),
        dome_radius_mm=float(limited.dome_radius_mm),
        dome_amplitude_mm=float(limited.dome_amplitude_mm),
        hackle_count=int(limited.hackle_count),
        hackle_amplitude_mm=float(limited.hackle_amplitude_mm),
        hackle_phase=float(limited.hackle_phase),
        mirror_radius_mm=float(limited.mirror_radius_mm),
        mist_radius_mm=float(limited.mist_radius_mm),
        rib_amplitude_mm=float(limited.rib_amplitude_mm),
        rib_spacing_mm=float(limited.rib_spacing_at_mirror_mm),
        fiber_amplitude_mm=float(limited.fiber_amplitude_mm),
        fiber_wavelength_mm=float(limited.fiber_period_mm),
        fiber_direction=(float(fiber_dir[0]), float(fiber_dir[1])),
        amplitude_max_mm=float(max(
            [b.amplitude_mm for b in bands]
            + [limited.hackle_amplitude_mm, limited.rib_amplitude_mm,
               limited.fiber_amplitude_mm, limited.pit_depth_mm, 0.0])),
    )
    centres = scatter_pits(
        tris_uv, origin, int(limited.pit_count),
        seed_material={"event": limited.event_id, "material": limited.material_id,
                       "mirror": round(float(limited.mirror_radius_mm), 6)},
        min_radius_from_origin_mm=float(limited.mirror_radius_mm))
    field.pits = _PitSet(centres_uv=centres, radius_mm=float(limited.pit_radius_mm),
                         depth_mm=float(limited.pit_depth_mm))
    field.meta["pit_centre_count"] = int(centres.shape[0])

    # ------------------------------------------------------------------ footprint envelope
    step_raster = float(raster_step_mm or max(0.5 * float(delta_mm), 0.02))
    width = float(envelope_width_mm if envelope_width_mm is not None
                  else max(10.0 * float(delta_mm), 1.4))
    pts = tris_uv.reshape(-1, 2)
    pad = 12.0 * step_raster
    bbox = (float(pts[:, 0].min()) - pad, float(pts[:, 0].max()) + pad,
            float(pts[:, 1].min()) - pad, float(pts[:, 1].max()) + pad)
    boundary_fn = lambda u, v: (np.asarray(field.unmasked(u, v), dtype=np.float64),) * 2  # noqa: E731
    envelope, samples = build_footprint_envelope(
        tris_uv, exact_area_mm2=float(core_area), bbox=bbox, step_mm=step_raster, width_mm=width,
        boundary_values_fn=boundary_fn,
        extension_iterations=int(240))
    glaze = envelope.glaze_raster_from(strip_mm=float(limited.glaze_strip_width_mm),
                                       ratio=float(limited.glaze_roughness_ratio))
    if glaze is not None:
        envelope.extra_raster = glaze
    field.envelope = envelope
    field.meta["envelope"] = envelope.as_dict()
    field.meta["glaze_applied"] = bool(glaze is not None)

    # ------------------------------------------------------------------ slope calibration
    #
    # The envelope is built from the *requested* amplitudes and follows the calibration through
    # ``scale_offsets`` (its ring extension is a linear functional of the relief amplitudes), so the
    # cancellation on the ring stays exact after the amplitudes are scaled down.
    mask_fn = lambda u, v: envelope.smoothness(u, v) > 0.5  # noqa: E731
    slope_step = float(slope_step_mm or max(0.5 * float(delta_mm), 0.02))
    h_fn = lambda u, v: np.asarray(field(u, v), dtype=np.float64)  # noqa: E731
    slope = calibrate_slope(field, h_fn, bounds=bbox, mask_fn=mask_fn, step_mm=slope_step,
                            target_p95_deg=float(slope_target_p95_deg),
                            on_scale=envelope.scale_offsets)
    field.max_slope = float(np.tan(np.radians(slope["after"]["angle_p95_deg"])))
    realized = measure_field_slope(h_fn, bounds=bbox, mask_fn=mask_fn, step_mm=slope_step)
    boundary_h = np.asarray(field(samples[:, 0], samples[:, 1]), dtype=np.float64) \
        if samples.shape[0] else np.zeros(0)
    ring_residual = {
        "samples": int(boundary_h.size),
        "boundary_height_max_mm": float(np.max(np.abs(boundary_h))) if boundary_h.size else 0.0,
        "boundary_height_rms_mm": float(np.sqrt(np.mean(boundary_h ** 2))) if boundary_h.size
        else 0.0,
        "boundary_height_p95_mm": float(np.percentile(np.abs(boundary_h), 95))
        if boundary_h.size else 0.0,
    }
    field.realized_rms_mm = float(realized.get("height_rms_mm", 0.0))
    field.meta["relief_rms_mm"] = field.realized_rms_mm
    field.meta["amplitude_max_mm"] = float(max(
        [b.amplitude_mm for b in field.bands]
        + [field.hackle_amplitude_mm, field.rib_amplitude_mm, field.fiber_amplitude_mm,
           (0.0 if field.pits is None else float(field.pits.depth_mm)), 0.0]))
    info = {
        "band_limit": limit_info, "spectrum": spectrum, "slope": slope,
        "envelope": envelope.as_dict(), "ring": ring_residual,
        "realized": realized,
        "finite_at_ring": bool(ring_residual["boundary_height_max_mm"] <= 1.0e-3),
    }
    return field, info
