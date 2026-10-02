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
    """Outward taper of the fracture surface: 1 on the footprint, 0 far outside it.

    ``phi`` is built from the *signed distance* to the material cross-section outline:
    ``phi = smootherstep((d + width) / width)``, i.e. exactly 1 on the footprint and on its
    boundary, decaying to 0 over ``width`` outside it.  Both C^1 junctions (at ``d = 0`` and
    ``d = -width``) are smooth because ``smootherstep'`` vanishes at both ends.

    Why not force ``h = 0`` *on* the ring (the first two revisions did)
    ------------------------------------------------------------------
    Measured on the real bodies: any mask that rises from 0 at the ring to 1 in the interior has to
    interpolate between the ring and the interior, and on a thin wall strip (V18: mean cross-section
    width 1.6 mm) the medial axis of that strip is a ridge where the distance function itself has a
    slope kink.  The taper then carries a kink straight through the middle of the fracture face, and
    a sheet triangle cannot represent it (measured 0.024 mm of interpolation error versus the 0.01 mm
    budget, for every mask width between 0.5 mm and 2.7 mm).  A real fracture face does not return
    to the mean plane at the rim either, so the taper is the physically right shape: the surface
    keeps its relief to the edge and only the *outside* of the footprint is damped, which is what
    keeps the flat frame cheap.  ``boundary_height_*`` publishes where the sheet crosses the ring
    plane, and the interface patch it produces is measured like everything else.
    """

    u0: float
    v0: float
    step_mm: float
    sign_raster: np.ndarray
    signed_raster: np.ndarray
    inside_raster: np.ndarray
    boundary_cells: int
    width_mm: float
    raster_area_mm2: float
    exact_area_mm2: float
    footprint_touches_raster_edge: bool
    boundary_samples: int = 0
    boundary_source: str = ""
    blur_sigma_cells: float = 2.0
    #: kept for API stability with the earlier revisions (unused by the taper construction)
    offset_raster: np.ndarray | None = None
    dome_offset_raster: np.ndarray | None = None
    extra_raster: np.ndarray | None = None

    def mask(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``phi``: 1 on the footprint, decaying to 0 over ``width_mm`` outside it."""
        sd = raster_lookup(self.signed_raster, self.u0, self.v0, self.step_mm, u, v)
        return _smootherstep((sd + self.width_mm) / max(self.width_mm, _EPS))

    def smoothness(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``phi`` under the name ``MorphologyHeightField`` expects for its modulation slot."""
        return self.mask(u, v)

    def signed_distance(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        return raster_lookup(self.signed_raster, self.u0, self.v0, self.step_mm, u, v)

    def offset(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Unused by the taper construction (kept so the record's readers do not break)."""
        return np.zeros(np.broadcast(u, v).shape, dtype=np.float64)

    def dome_offset(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        return np.zeros(np.broadcast(u, v).shape, dtype=np.float64)

    def value(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``phi``: the object ``MorphologyHeightField`` expects in its modulation slot."""
        return self.mask(u, v)

    def is_exactly_one(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Duck-type of ``cut.BandWindow``: the footprint core (where the relief is untouched).

        ``surface_features.measure_cutter_surface`` restricts its samples with this method, so the
        implicit envelope can be passed where the frozen band window is expected.
        """
        return self.mask(u, v) >= 1.0 - 1.0e-9

    def apply(self, u: np.ndarray, v: np.ndarray, relief: np.ndarray) -> np.ndarray:
        """``phi * relief``: the masked surface (relief to the rim, flat far outside)."""
        uu = np.asarray(u, dtype=np.float64)
        vv = np.asarray(v, dtype=np.float64)
        out = self.mask(uu, vv) * np.asarray(relief, dtype=np.float64)
        if self.extra_raster is not None:
            out = out * raster_lookup(self.extra_raster, self.u0, self.v0, self.step_mm, uu, vv)
        return out

    def scale_offsets(self, ratio: float) -> None:
        """No-op (kept as the calibration hook; the taper has no ring offset to scale)."""
        return

    def glaze_raster_from(self, *, strip_mm: float, ratio: float) -> np.ndarray | None:
        """Relief damping inside the glaze strip (``ratio`` at the rim, 1 in the body)."""
        if strip_mm <= 0.0 or ratio >= 1.0:
            return None
        depth = np.maximum(self.signed_raster, 0.0)
        strip = max(float(strip_mm), 2.0 * float(self.step_mm))
        return float(ratio) + (1.0 - float(ratio)) * _smootherstep(depth / strip)

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_mm": float(self.step_mm), "width_mm": float(self.width_mm),
            "boundary_cells": int(self.boundary_cells),
            "raster_area_mm2": float(self.raster_area_mm2),
            "exact_area_mm2": float(self.exact_area_mm2),
            "raster_area_rel_error": float(
                abs(self.raster_area_mm2 - self.exact_area_mm2) / max(self.exact_area_mm2, _EPS)),
            "footprint_touches_raster_edge": bool(self.footprint_touches_raster_edge),
            "boundary_samples": int(self.boundary_samples),
            "boundary_source": str(self.boundary_source),
            "blur_sigma_cells": float(self.blur_sigma_cells),
            "glaze_raster": self.extra_raster is not None,
            "construction": "phi = smootherstep((signed_distance + width) / width): exactly 1 on "
                            "the footprint (relief reaches the rim, as a real fracture face does) "
                            "and 0 at 'width' outside it; the signed distance is blurred before it "
                            "is used so its raster quantisation cannot reach the surface",
        }


def _masked_blur(values: np.ndarray, mask: np.ndarray, *, sigma: float) -> np.ndarray:
    """Gaussian blur that only averages the cells where ``mask`` is true (normalised convolution)."""
    from scipy import ndimage

    num = ndimage.gaussian_filter(np.where(mask, values, 0.0), sigma=sigma, mode="nearest")
    den = ndimage.gaussian_filter(mask.astype(np.float64), sigma=sigma, mode="nearest")
    return np.where(den > 1.0e-6, num / np.maximum(den, 1.0e-12), 0.0)


def boundary_samples_uv(tris_uv: np.ndarray, *, max_step_mm: float
                        ) -> tuple[np.ndarray, dict[str, Any]]:
    """Sample the footprint boundary polyline (exterior + interior rings) in ``(u, v)``."""
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
    flat = (key[:, 0, 0] * 1.0e6 + key[:, 0, 1] * 1.0e3
            + key[:, 1, 0] * 1.0e-3 + key[:, 1, 1])
    _uniq, inverse, counts = np.unique(np.round(flat, 6), return_inverse=True,
                                       return_counts=True)
    boundary_edges = edges[np.isin(inverse, np.nonzero(counts == 1)[0])]
    pts = boundary_edges.reshape(-1, 2)
    return np.unique(np.round(pts, 9), axis=0), {
        "source": f"triangle edges used once ({fallback} {error})".strip(), "parts": 0}


def build_footprint_envelope(tris_uv: np.ndarray, *, exact_area_mm2: float,
                             bbox: tuple[float, float, float, float],
                             step_mm: float, width_mm: float,
                             boundary_values_fn: Any = None,
                             dirichlet_step_mm: float | None = None,
                             extension_iterations: int = 0,
                             extension_tol_mm: float = 1.0e-5,
                             sigma_cells: float = 2.0
                             ) -> tuple["FootprintEnvelope", np.ndarray]:
    """Rasterise the footprint, blur its signed distance and build the outward taper."""
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
    boundary_cells = inside & ~eroded
    if not bool(boundary_cells.any()):
        boundary_cells = inside.copy()
    d_in = ndimage.distance_transform_edt(inside) * step_mm
    d_out = ndimage.distance_transform_edt(~inside) * step_mm
    signed = d_in - d_out
    #: blur the quantised EDT over a band that covers the taper plus a margin: the taper's *input*
    #: must be smooth, otherwise its one-cell staircase reaches the surface (measured: 0.04 mm).
    band = np.abs(signed) <= (2.0 * float(width_mm) + 8.0 * float(step_mm))
    #: outside the band the blurred value is meaningless (the normalised blur returns 0 there, which
    #: would make the taper 1 *far* outside the footprint and fill the flat frame with relief --
    #: measured as a 0.9 mm interpolation error), so the raw distance is kept there, pushed out of
    #: the taper's range on both sides.
    filled = np.where(signed > 0.0, np.maximum(signed, 2.0 * float(width_mm)),
                      np.minimum(signed, -2.0 * float(width_mm)))
    signed_smooth = np.where(band, _masked_blur(signed, band, sigma=float(sigma_cells)), filled)
    edge = np.zeros_like(inside)
    edge[0, :] = edge[-1, :] = True
    edge[:, 0] = edge[:, -1] = True
    samples, sample_info = boundary_samples_uv(
        tris_uv, max_step_mm=float(dirichlet_step_mm if dirichlet_step_mm is not None
                                   else 0.05 * step_mm))
    del boundary_values_fn, extension_iterations, extension_tol_mm
    return FootprintEnvelope(
        u0=u0, v0=v0, step_mm=float(step_mm), sign_raster=signed_smooth,
        signed_raster=signed_smooth, inside_raster=inside,
        boundary_cells=int(boundary_cells.sum()), width_mm=float(width_mm),
        raster_area_mm2=float(inside.sum() * step_mm ** 2), exact_area_mm2=float(exact_area_mm2),
        footprint_touches_raster_edge=bool(np.any(inside & edge)),
        boundary_samples=int(samples.shape[0]),
        boundary_source=str(sample_info.get("source", "")),
        blur_sigma_cells=float(sigma_cells),
        offset_raster=None, dome_offset_raster=None,
    ), samples


# ---------------------------------------------------------------------------- field
@dataclass
class ImplicitSheetField(MorphologyHeightField):
    """``w = dome_scale * dome + relief``, tapered to zero outside the material footprint.

    The conchoidal dome (which the frozen model caps at ``4 * sigma_r0`` but evaluates as an
    unbounded paraboloid) is scaled together with the relief by every slope-calibration step: it is
    a relief feature, and leaving it out of the scaling made the taper multiply a 1.6 mm bow, which
    is what produced the earliest curvature failures (measured 48 /mm on a 0.13 mm sheet).
    """

    envelope: Any = None
    #: scale applied to the conchoidal term (``MorphologyHeightField.apply_scale`` covers only
    #: bands / hackle / ribs / fibre / pits).
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
        """``dome + relief`` before the footprint taper."""
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

    Band-limiting is the honest alternative to aliasing: the removed bands are named with their
    amplitude and RMS contribution, and the shortest *retained* wavelength is what the sampling
    metric is evaluated against.  Nothing is coarsened silently.
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
        longest = max(params.bands, key=lambda b: float(b[1]))
        kept = [longest]
        dropped = [d for d in dropped if abs(d["wavelength_mm"] - float(longest[1])) > 1e-12]
        removed_rms = float(np.sqrt(np.sum([0.5 * d["amplitude_mm"] ** 2 for d in dropped])))
        kept_rms = float(np.sqrt(0.5 * float(longest[0]) ** 2))
    info = {
        "band_limit_mm": lam_allowed, "delta_mm": float(delta_mm),
        "samples_per_wavelength": float(samples_per_wavelength),
        "bands_requested": len(params.bands), "bands_kept": len(kept), "dropped": dropped,
        "removed_rms_mm": removed_rms, "kept_rms_mm": kept_rms,
        "requested_rms_mm": float(params.requested_rms_mm), "band_limited": bool(dropped),
        "lambda_min_realized_mm": float(min([float(k[1]) for k in kept], default=float("inf"))),
    }
    return replace(params, bands=tuple(kept)), info


def sheet_spectrum(params: Any) -> dict[str, Any]:
    """Shortest geometric scale of every active component of the field (mm)."""
    scales: dict[str, float] = {}
    for _amplitude, wavelength, _du, _dv, _phase in params.bands:
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


# ---------------------------------------------------------------------------- slope / curvature
def measure_field_slope(h_fn: Any, *, bounds: tuple[float, float, float, float],
                        mask_fn: Any, step_mm: float, max_points: int = 600_000
                        ) -> dict[str, Any]:
    """P50/P95/max slope and curvature of the realized surface over the footprint.

    The curvature is the mixed bound ``|h_uu| + 2|h_uv| + |h_vv|`` that the interpolation budget uses
    (``error <= C * cell^2 / 8``), measured on a raster finer than the sheet spacing so a cell-sized
    feature cannot hide between samples.
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


def calibrate_slope(field: ImplicitSheetField, h_fn: Any, *,
                    bounds: tuple[float, float, float, float], mask_fn: Any, step_mm: float,
                    target_p95_deg: float = SLOPE_P95_TARGET_DEG, max_iterations: int = 4,
                    on_scale: Any = None) -> dict[str, Any]:
    """Scale the relief amplitudes until the *measured* P95 slope enters the declared band.

    The step is ``tan(target) / tan(measured)`` on the realized surface (footprint taper included),
    the loop re-measures after every step, and it only ever scales the relief *down*.  The reported
    numbers are measurements, not predictions.
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
        "target_p95_deg": float(target_p95_deg), "target_p95_tan": target_tan,
        "amplitude_scale_applied": float(scale_total),
        "before": before, "after": achieved, "history": history,
        "constraint": ("scale relief amplitudes (conchoidal term included) so that the measured P95 "
                       "of |grad h| over the footprint equals tan(target); re-measured after every "
                       "step, and only ever scaled down"),
        "achieved_within_band": bool(float(achieved.get("slope_p95", 0.0)) <= target_tan + 1e-9),
    }


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
                  else max(8.0 * float(delta_mm), 1.0))
    pts = tris_uv.reshape(-1, 2)
    #: the raster must contain the whole taper (plus a margin): a taper clipped by the raster edge
    #: leaves the mask at ~0.8 on the edge, i.e. a step of 0.8 * relief in the middle of the sheet
    #: (measured: 0.147 mm of interpolation error, and it grew with the taper width).
    pad = float(width) + 12.0 * step_raster
    bbox = (float(pts[:, 0].min()) - pad, float(pts[:, 0].max()) + pad,
            float(pts[:, 1].min()) - pad, float(pts[:, 1].max()) + pad)
    envelope, samples = build_footprint_envelope(
        tris_uv, exact_area_mm2=float(core_area), bbox=bbox, step_mm=step_raster, width_mm=width)
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
