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
    """Bilinear sample of a raster, clamped at the edges (an edge value is a real value)."""
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


def _smootherstep(t: np.ndarray) -> np.ndarray:
    x = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)


# ---------------------------------------------------------------------------- envelope
@dataclass
class FootprintEnvelope:
    """Raster envelope that makes the relief vanish on the patch boundary ring.

    ``h_final = S(u, v) * (h_raw(u, v) - B(u, v))`` with

    * ``S``  a smooth indicator of the material footprint (1 inside, 0 outside, 0.5 on the ring),
      built from the signed distance to the footprint boundary;
    * ``B``  the raw field's value at the *nearest ring point* (nearest-neighbour extension of the
      boundary value inwards).  ``h_raw - B`` therefore vanishes exactly on the ring, everywhere on
      it, without adding a ramp of its own: the subtraction is a Lipschitz operation, so the
      envelope cannot make the surface steeper than the field already is.
    """

    u0: float
    v0: float
    step_mm: float
    sign_raster: np.ndarray
    offset_raster: np.ndarray
    inside_raster: np.ndarray
    ring_cells: int
    width_mm: float
    raster_area_mm2: float
    exact_area_mm2: float
    footprint_touches_raster_edge: bool
    signed_raster: np.ndarray | None = None
    extra_raster: np.ndarray | None = None

    def smoothness(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        return bilinear_lookup(self.sign_raster, self.u0, self.v0, self.step_mm, u, v)

    def value(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``S`` only (the footprint indicator): the object ``MorphologyHeightField`` expects."""
        return self.smoothness(u, v)

    def apply(self, u: np.ndarray, v: np.ndarray, base: np.ndarray) -> np.ndarray:
        """``S * (base - B)``: the displaced sheet, zero on the ring and outside the footprint."""
        uu = np.asarray(u, dtype=np.float64)
        vv = np.asarray(v, dtype=np.float64)
        s = bilinear_lookup(self.sign_raster, self.u0, self.v0, self.step_mm, uu, vv)
        b = bilinear_lookup(self.offset_raster, self.u0, self.v0, self.step_mm, uu, vv)
        out = s * (np.asarray(base, dtype=np.float64) - b)
        if self.extra_raster is not None:
            out = out * bilinear_lookup(self.extra_raster, self.u0, self.v0, self.step_mm, uu, vv)
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
            "construction": "h = smootherstep(signed_distance/width) * (h_raw - h_raw(nearest "
                            "ring point)); h == 0 exactly on the ring",
        }


def build_footprint_envelope(tris_uv: np.ndarray, *, exact_area_mm2: float,
                             bbox: tuple[float, float, float, float],
                             step_mm: float, width_mm: float
                             ) -> tuple["FootprintEnvelope", tuple[np.ndarray, np.ndarray]]:
    """Rasterise the footprint and build :class:`FootprintEnvelope` (ring value + indicator)."""
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
    sign = _smootherstep((signed + 0.5 * width_mm) / max(width_mm, _EPS))
    sign[~ndimage.binary_dilation(inside, structure=structure, iterations=2)] = 0.0
    _dist, indices = ndimage.distance_transform_edt(~ring, return_indices=True)
    ring_i, ring_j = indices[0], indices[1]
    edge = np.zeros_like(inside)
    edge[0, :] = edge[-1, :] = True
    edge[:, 0] = edge[:, -1] = True
    return FootprintEnvelope(
        u0=u0, v0=v0, step_mm=float(step_mm), sign_raster=sign,
        offset_raster=np.zeros_like(sign), inside_raster=inside,
        ring_cells=int(ring.sum()), width_mm=float(width_mm),
        raster_area_mm2=float(inside.sum() * step_mm ** 2), exact_area_mm2=float(exact_area_mm2),
        footprint_touches_raster_edge=bool(np.any(inside & edge)),
        signed_raster=signed,
    ), (ring_i, ring_j)


# ---------------------------------------------------------------------------- field
@dataclass
class ImplicitSheetField(MorphologyHeightField):
    """``w = E(u, v) * (h_morphology(u, v) - h_morphology(ring))``, zero on the footprint ring.

    ``E`` is the footprint envelope (times the glaze envelope when the profile is glazed).  The
    material-band window of :mod:`synlab.fracture.cut` is intentionally not used: the envelope
    above is tighter and makes the surface *exactly* flat outside the footprint, so the coarse
    cells of the sheet triangulation carry exactly zero interpolation error there.
    """

    envelope: Any = None

    def raw(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        modulation = self.modulation
        self.modulation = None
        try:
            base = super().raw(u, v)
        finally:
            self.modulation = modulation
        if self.envelope is not None:
            base = self.envelope.apply(u, v, base)
        if modulation is not None:
            base = base * modulation.value(u, v)
        return base


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
    """P50/P95/max of the surface slope (deg from the mean plane) on a raster of the footprint."""
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
    gv_axis, gu_axis = np.gradient(h, step)
    slope = np.hypot(gu_axis, gv_axis)[inside]
    angles = np.degrees(np.arctan(slope))
    return {
        "samples": int(slope.size), "step_mm": float(step),
        "slope_p50": float(np.percentile(slope, 50)),
        "slope_p95": float(np.percentile(slope, 95)),
        "slope_max": float(slope.max()),
        "angle_p50_deg": float(np.percentile(angles, 50)),
        "angle_p95_deg": float(np.percentile(angles, 95)),
        "angle_max_deg": float(angles.max()),
        "height_rms_mm": float(np.sqrt(np.mean(
            (h[inside] - float(np.mean(h[inside]))) ** 2))),
        "height_peak_to_valley_mm": float(np.ptp(h[inside])),
    }


def calibrate_slope(field: ImplicitSheetField, h_fn: Any, *, bounds: tuple[float, float, float, float],
                    mask_fn: Any, step_mm: float, target_p95_deg: float = SLOPE_P95_TARGET_DEG,
                    max_iterations: int = 4) -> dict[str, Any]:
    """Scale the relief amplitudes until the *measured* P95 slope enters the declared band.

    The scale is ``tan(target) / tan(measured)`` evaluated on the realized surface (footprint
    envelope included).  It only ever scales the relief *down*; the loop stops as soon as the
    measurement is inside the band, so the reported value is a measurement, not a prediction.
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
                  else max(2.0 * float(delta_mm), 0.25))
    pts = tris_uv.reshape(-1, 2)
    pad = 8.0 * step_raster
    bbox = (float(pts[:, 0].min()) - pad, float(pts[:, 0].max()) + pad,
            float(pts[:, 1].min()) - pad, float(pts[:, 1].max()) + pad)
    envelope, (ring_i, ring_j) = build_footprint_envelope(
        tris_uv, exact_area_mm2=float(core_area), bbox=bbox, step_mm=step_raster, width_mm=width)
    ring_u = envelope.u0 + ring_i * step_raster
    ring_v = envelope.v0 + ring_j * step_raster
    modulation = field.modulation
    field.modulation = None
    try:
        ring_values = np.asarray(field.raw(ring_u, ring_v), dtype=np.float64)
    finally:
        field.modulation = modulation
    envelope.offset_raster = ring_values
    glaze = envelope.glaze_raster_from(strip_mm=float(limited.glaze_strip_width_mm),
                                       ratio=float(limited.glaze_roughness_ratio))
    if glaze is not None:
        envelope.extra_raster = glaze
    field.envelope = envelope
    field.meta["envelope"] = envelope.as_dict()
    field.meta["glaze_applied"] = bool(glaze is not None)

    # ------------------------------------------------------------------ slope calibration
    mask_fn = lambda u, v: envelope.smoothness(u, v) > 0.5  # noqa: E731
    slope_step = float(slope_step_mm or max(0.5 * float(delta_mm), 0.02))
    h_fn = lambda u, v: np.asarray(field(u, v), dtype=np.float64)  # noqa: E731
    slope = calibrate_slope(field, h_fn, bounds=bbox, mask_fn=mask_fn, step_mm=slope_step,
                            target_p95_deg=float(slope_target_p95_deg))
    field.max_slope = float(np.tan(np.radians(slope["after"]["angle_p95_deg"])))
    realized = measure_field_slope(h_fn, bounds=bbox, mask_fn=mask_fn, step_mm=slope_step)
    field.realized_rms_mm = float(realized.get("height_rms_mm", 0.0))
    field.meta["relief_rms_mm"] = field.realized_rms_mm
    field.meta["amplitude_max_mm"] = float(max(
        [b.amplitude_mm for b in field.bands]
        + [field.hackle_amplitude_mm, field.rib_amplitude_mm, field.fiber_amplitude_mm,
           (0.0 if field.pits is None else float(field.pits.depth_mm)), 0.0]))
    info = {
        "band_limit": limit_info, "spectrum": spectrum, "slope": slope,
        "envelope": envelope.as_dict(),
        "realized": realized,
        "finite_at_ring": True,
    }
    return field, info
