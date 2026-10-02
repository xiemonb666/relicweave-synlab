"""Continuous fields, antialiasing and *measured* spectra (plan 9.2 / 9.3).

Everything in this module is a pure function of frozen coefficients: given the same
recipe parameters it produces bit-identical values, and nothing here draws randomness
except the explicit ``sample_*`` helpers that run once inside ``build_pattern``.

Antialiasing follows the frozen formula of plan 9.3::

    alpha = 1 - smoothstep(w/2 - footprint, w/2 + footprint, distance_mm)

``footprint`` is derived from a real sampling footprint (raster texel size or the
projected mesh edge length), never from an arbitrary constant; the chosen value and its
source string travel inside the recipe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

TWO_PI = 2.0 * np.pi


# ---------------------------------------------------------------------------------------
# antialiasing
# ---------------------------------------------------------------------------------------
def smoothstep(edge0: float | np.ndarray, edge1: float | np.ndarray,
               x: np.ndarray | float) -> np.ndarray:
    """C1 Hermite ramp; array edges are supported and degenerate edges give a hard step."""
    e0 = np.asarray(edge0, dtype=np.float64)
    e1 = np.asarray(edge1, dtype=np.float64)
    width = e1 - e0
    safe = np.where(np.abs(width) < 1e-12, 1.0, width)
    t = np.clip((np.asarray(x, dtype=np.float64) - e0) / safe, 0.0, 1.0)
    out = t * t * (3.0 - 2.0 * t)
    degenerate = np.abs(width) < 1e-12
    if np.any(degenerate):
        out = np.where(degenerate, (np.asarray(x, dtype=np.float64) >= e1).astype(np.float64), out)
    return np.asarray(out, dtype=np.float64)


def line_alpha(distance_mm: np.ndarray, width_mm: float | np.ndarray,
               footprint_mm: float) -> np.ndarray:
    """Frozen line alpha of plan 9.3 (distance is measured to the centre line)."""
    half = 0.5 * np.asarray(width_mm, dtype=np.float64)
    fp = max(0.0, float(footprint_mm))
    return 1.0 - smoothstep(half - fp, half + fp, np.asarray(distance_mm, dtype=np.float64))


def footprint_policy(line_width_mm: float, *, request_mm: float | None = None,
                     texture_mm_per_px: float | None = None,
                     mesh_edge_mm: float | None = None) -> dict[str, Any]:
    """Choose the antialiasing footprint from a real sampling footprint.

    Priority: explicit request -> raster texel size -> half the projected mesh edge length.
    The result is clamped to at most half of the line half-width so that the frozen
    formula keeps a visible core, and the *source* of the number is recorded.
    """
    half = 0.5 * float(line_width_mm)
    sources: list[tuple[str, float]] = []
    if request_mm is not None:
        sources.append(("request_mm", float(request_mm)))
    if texture_mm_per_px is not None:
        sources.append(("raster_texel_mm", float(texture_mm_per_px)))
    if mesh_edge_mm is not None:
        sources.append(("mesh_edge_mm/2", 0.5 * float(mesh_edge_mm)))
    if not sources:
        raise ValueError("footprint_policy needs at least one measured footprint source")
    name, value = max(sources, key=lambda kv: kv[1])
    clamped = float(np.clip(value, 1e-3, max(1e-3, 0.45 * half)))
    return {
        "footprint_mm": clamped,
        "source": f"{name}={value:.6g}",
        "candidates": {k: float(v) for k, v in sources},
        "clamp_max_mm": float(max(1e-3, 0.45 * half)),
    }


# ---------------------------------------------------------------------------------------
# periodic Fourier basis (plan 9.2)
# ---------------------------------------------------------------------------------------
@dataclass
class FourierComponent:
    amp: float
    k_int: int          # integer azimuthal count: guarantees u=0 / u=1 continuity
    f_mm_inv: float     # cycles per millimetre along the profile arc length
    phase: float
    band: int
    wavelength_x_mm: float
    wavelength_s_mm: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "amp": float(self.amp), "k_int": int(self.k_int),
            "f_mm_inv": float(self.f_mm_inv), "phase": float(self.phase),
            "band": int(self.band), "wavelength_x_mm": float(self.wavelength_x_mm),
            "wavelength_s_mm": (None if self.wavelength_s_mm is None
                                else float(self.wavelength_s_mm)),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FourierComponent":
        return cls(amp=float(payload["amp"]), k_int=int(payload["k_int"]),
                   f_mm_inv=float(payload["f_mm_inv"]), phase=float(payload["phase"]),
                   band=int(payload.get("band", 0)),
                   wavelength_x_mm=float(payload.get("wavelength_x_mm", 0.0)),
                   wavelength_s_mm=(None if payload.get("wavelength_s_mm") is None
                                    else float(payload["wavelength_s_mm"])))

    def value(self, x_mm: np.ndarray, s_mm: np.ndarray, x_period_mm: float) -> np.ndarray:
        u = np.asarray(x_mm, dtype=np.float64) / float(x_period_mm)
        # reduce the azimuthal phase onto [0,1) so u=0 and u=1 are bit-identical
        turns = np.mod(self.k_int * u, 1.0)
        arg = TWO_PI * turns + TWO_PI * self.f_mm_inv * np.asarray(s_mm, dtype=np.float64) + self.phase
        return self.amp * np.cos(arg)


@dataclass
class FourierBasis:
    """Finite cosine basis on ``(u, s_mm)`` with integer azimuthal counts."""

    components: list[FourierComponent]
    offset: float = 0.0
    rms_scale: float = 1.0
    normalisation: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def value(self, x_mm: np.ndarray, s_mm: np.ndarray, x_period_mm: float) -> np.ndarray:
        x = np.asarray(x_mm, dtype=np.float64)
        out = np.zeros(x.shape[0], dtype=np.float64)
        for comp in self.components:
            out += comp.value(x, s_mm, x_period_mm)
        return (out + self.offset) * self.rms_scale

    def band_components(self) -> dict[int, list[FourierComponent]]:
        out: dict[int, list[FourierComponent]] = {}
        for comp in self.components:
            out.setdefault(comp.band, []).append(comp)
        return out

    def band_summary(self) -> list[dict[str, Any]]:
        out = []
        for band, comps in sorted(self.band_components().items()):
            wavelengths = [c.wavelength_x_mm for c in comps]
            amps = [abs(c.amp) for c in comps]
            out.append({
                "band": int(band),
                "n_components": len(comps),
                "amplitude_max": float(max(amps)),
                "amplitude_sum": float(sum(amps)),
                "wavelength_x_mm_min": float(min(wavelengths)),
                "wavelength_x_mm_max": float(max(wavelengths)),
                "f_mm_inv_abs_max": float(max(abs(c.f_mm_inv) for c in comps)),
            })
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "components": [c.as_dict() for c in self.components],
            "offset": float(self.offset), "rms_scale": float(self.rms_scale),
            "normalisation": dict(self.normalisation), "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FourierBasis":
        return cls(components=[FourierComponent.from_dict(c) for c in payload["components"]],
                   offset=float(payload.get("offset", 0.0)),
                   rms_scale=float(payload.get("rms_scale", 1.0)),
                   normalisation=dict(payload.get("normalisation") or {}),
                   meta=dict(payload.get("meta") or {}))


def sample_fourier_basis(rng: np.random.Generator, *, x_period_mm: float, base_wavelength_mm: float,
                         n_bands: int, components_per_band: int = 1,
                         amplitude_ratio: float = 0.5, base_amplitude: float = 1.0,
                         angle_spread_deg: float = 60.0, x_only: bool = False,
                         band_wavelength_ratio: float = 0.5) -> FourierBasis:
    """Draw one frozen 3-5 band basis: adjacent frequency ~x2, amplitude ~x0.5.

    ``band_wavelength_ratio`` is the wavelength factor between bands (0.5 == one octave
    finer per band).  Azimuthal counts stay integers, so ``u=0`` and ``u=1`` agree
    exactly; the achieved wavelengths are recorded per component because integer rounding
    quantises the azimuthal wavelength to ``x_period_mm / k``.
    """
    components: list[FourierComponent] = []
    for band in range(int(n_bands)):
        wavelength = float(base_wavelength_mm) * (band_wavelength_ratio ** band)
        amp = float(base_amplitude) * (amplitude_ratio ** band)
        for _ in range(int(components_per_band)):
            if x_only:
                angle = 0.0
            else:
                angle = float(rng.uniform(-angle_spread_deg, angle_spread_deg)) * np.pi / 180.0
            phase = float(rng.uniform(0.0, TWO_PI))
            k_int = max(1, int(np.floor(x_period_mm / wavelength)))
            wavelength_x = x_period_mm / k_int
            # keep the band isotropy: the profile-direction frequency completes the
            # requested wavelength as long as the quantised azimuthal one allows it
            inv_w = 1.0 / wavelength
            inv_x = k_int / x_period_mm
            if x_only or abs(np.cos(angle)) < 1e-9:
                f_mm_inv = 0.0
            else:
                target = inv_w / max(abs(np.cos(angle)), 1e-6)
                f_mm_inv = float(np.sign(np.sin(angle)) * np.sqrt(max(0.0, target ** 2 - inv_x ** 2)))
            wavelength_s = None if abs(f_mm_inv) < 1e-12 else float(1.0 / abs(f_mm_inv))
            components.append(FourierComponent(
                amp=amp, k_int=k_int, f_mm_inv=f_mm_inv, phase=phase, band=band,
                wavelength_x_mm=float(wavelength_x), wavelength_s_mm=wavelength_s))
    return FourierBasis(components=components, meta={
        "sampler": "synlab.patterns.fields.sample_fourier_basis",
        "n_bands": int(n_bands), "components_per_band": int(components_per_band),
        "base_wavelength_mm": float(base_wavelength_mm),
        "amplitude_ratio": float(amplitude_ratio),
        "band_wavelength_ratio": float(band_wavelength_ratio),
        "angle_spread_deg": float(angle_spread_deg),
        "azimuthal_counts_are_integers": True,
        "x_only": bool(x_only),
    })


# ---------------------------------------------------------------------------------------
# domain warp (plan 9.2)
# ---------------------------------------------------------------------------------------
@dataclass
class WarpField:
    """Periodic displacement field in millimetres; ``x`` keeps integer azimuthal counts."""

    components: list[FourierComponent] = field(default_factory=list)
    amplitude_mm: float = 0.0
    wavelength_mm: float = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.components) and self.amplitude_mm > 0.0

    def apply(self, x_mm: np.ndarray, s_mm: np.ndarray,
              x_period_mm: float) -> tuple[np.ndarray, np.ndarray]:
        x = np.asarray(x_mm, dtype=np.float64)
        s = np.asarray(s_mm, dtype=np.float64)
        if not self.enabled:
            return x, s
        acc = np.zeros(x.shape[0], dtype=np.float64)
        for comp in self.components:
            acc += comp.value(x, s, x_period_mm)
        return x + acc, s

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled), "amplitude_mm": float(self.amplitude_mm),
            "wavelength_mm": float(self.wavelength_mm),
            "components": [c.as_dict() for c in self.components],
            "units": "mm",
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "WarpField":
        if not payload:
            return cls()
        return cls(components=[FourierComponent.from_dict(c) for c in payload.get("components", [])],
                   amplitude_mm=float(payload.get("amplitude_mm", 0.0)),
                   wavelength_mm=float(payload.get("wavelength_mm", 0.0)))


def jacobian_report(warp: WarpField, *, x_period_mm: float, s_min_mm: float, s_max_mm: float,
                    n_x: int = 48, n_s: int = 24) -> dict[str, Any]:
    """Finite-difference Jacobian of the warp; positive determinant and min singular value."""
    if not warp.enabled:
        return {"enabled": False, "jacobian_min_det": 1.0, "jacobian_min_singular": 1.0,
                "jacobian_max_singular": 1.0, "positive": True,
                "note": "warp disabled -> identity map"}
    h = max(1e-2, min(x_period_mm / 512.0, (s_max_mm - s_min_mm) / 128.0))
    xs = (np.arange(n_x) + 0.5) * x_period_mm / n_x
    ss = s_min_mm + (np.arange(n_s) + 0.5) * (s_max_mm - s_min_mm) / n_s
    grid_x, grid_s = np.meshgrid(xs, ss, indexing="ij")
    x = grid_x.reshape(-1)
    s = grid_s.reshape(-1)

    def map_x(xx: np.ndarray, ss_: np.ndarray) -> np.ndarray:
        return warp.apply(xx, ss_, x_period_mm)[0]

    def map_s(xx: np.ndarray, ss_: np.ndarray) -> np.ndarray:
        return warp.apply(xx, ss_, x_period_mm)[1]

    dx_dx = (map_x(x + h, s) - map_x(x - h, s)) / (2 * h)
    dx_ds = (map_x(x, s + h) - map_x(x, s - h)) / (2 * h)
    ds_dx = (map_s(x + h, s) - map_s(x - h, s)) / (2 * h)
    ds_ds = (map_s(x, s + h) - map_s(x, s - h)) / (2 * h)
    det = (1.0 + dx_dx) * (1.0 + ds_ds) - dx_ds * ds_dx
    # singular values of the 2x2 Jacobian in closed form
    a, b, c, d = 1.0 + dx_dx, dx_ds, ds_dx, 1.0 + ds_ds
    tr = a * a + b * b + c * c + d * d
    diff = np.sqrt(np.maximum(0.0, (a * a + b * b - c * c - d * d) ** 2 + 4 * (a * c + b * d) ** 2))
    smax = np.sqrt(np.maximum(0.0, 0.5 * (tr + diff)))
    smin = np.sqrt(np.maximum(0.0, 0.5 * (tr - diff)))
    return {
        "enabled": True,
        "step_mm": float(h),
        "grid": {"n_x": int(n_x), "n_s": int(n_s)},
        "jacobian_min_det": float(det.min()),
        "jacobian_min_singular": float(smin.min()),
        "jacobian_max_singular": float(smax.max()),
        "positive": bool(det.min() > 0.0 and smin.min() > 0.0),
        "amplitude_mm": float(warp.amplitude_mm),
        "wavelength_mm": float(warp.wavelength_mm),
    }


# ---------------------------------------------------------------------------------------
# measured statistics / spectra
# ---------------------------------------------------------------------------------------
def weighted_stats(values: np.ndarray, weights: np.ndarray) -> dict[str, float]:
    v = np.asarray(values, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    total = float(w.sum())
    if v.size == 0 or total <= 0.0:
        return {"mean": 0.0, "rms": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "n": 0.0}
    mean = float((w * v).sum() / total)
    var = float((w * (v - mean) ** 2).sum() / total)
    return {"mean": mean, "rms": float(np.sqrt(max(var, 0.0))), "std": float(np.sqrt(max(var, 0.0))),
            "min": float(v.min()), "max": float(v.max()), "n": float(v.size)}


def band_projection_energy(basis: FourierBasis, x_mm: np.ndarray, s_mm: np.ndarray,
                           weights: np.ndarray, x_period_mm: float) -> dict[str, Any]:
    """Area-weighted projection of a Fourier basis per band (measured, not nominal)."""
    x = np.asarray(x_mm, dtype=np.float64)
    s = np.asarray(s_mm, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    total = float(w.sum())
    if x.size == 0 or total <= 0.0:
        return {"bands": [], "energy_explained": 0.0, "residual_rms": 0.0}
    field = basis.value(x, s, x_period_mm)
    stats = weighted_stats(field, w)
    var = stats["rms"] ** 2
    per_band: dict[int, float] = {}
    for comp in basis.components:
        u = x / x_period_mm
        arg = TWO_PI * np.mod(comp.k_int * u, 1.0) + TWO_PI * comp.f_mm_inv * s + comp.phase
        basis_vec = np.cos(arg)
        denom = float((w * basis_vec ** 2).sum())
        coeff = 0.0 if denom <= 0 else float((w * field * basis_vec).sum() / denom)
        per_band[comp.band] = per_band.get(comp.band, 0.0) + 0.5 * coeff ** 2
    bands = []
    explained = 0.0
    for band, energy in sorted(per_band.items()):
        frac = 0.0 if var <= 0 else float(energy / var)
        explained += frac
        comps = [c for c in basis.components if c.band == band]
        bands.append({
            "band": int(band),
            "energy": float(energy),
            "energy_fraction_of_variance": frac,
            "amplitude_nominal": float(max(abs(c.amp) for c in comps)),
            "wavelength_x_mm_min": float(min(c.wavelength_x_mm for c in comps)),
        })
    return {
        "bands": bands,
        "energy_explained": float(explained),
        "residual_rms": float(np.sqrt(max(var * max(0.0, 1.0 - explained), 0.0))),
        "field_stats": stats,
        "weights": "area_mm2",
    }


def measure_spectrum(modulation: Callable[[np.ndarray, np.ndarray], np.ndarray], *,
                     x_period_mm: float, s_min_mm: float, s_max_mm: float,
                     n_x: int = 192, n_s: int = 96, band_count: int = 5,
                     s_periodic: bool = False) -> dict[str, Any]:
    """Measured band energy of the *frozen* field on a uniform chart grid.

    ``x`` is the periodic axis, so the azimuthal transform is exact; ``s`` is windowed
    (Hann) unless the profile is closed, and the window energy loss is compensated.
    Wavelengths are reported in the chart millimetres the recipe is defined in.
    """
    nx = int(n_x)
    ns = int(n_s)
    span = float(s_max_mm - s_min_mm)
    if nx < 8 or ns < 8 or span <= 0:
        return {"status": "NOT_RUN", "reason": "grid too small for a spectrum measurement"}
    xs = (np.arange(nx) + 0.5) * float(x_period_mm) / nx
    ss = s_min_mm + (np.arange(ns) + 0.5) * span / ns
    gx, gs = np.meshgrid(xs, ss, indexing="xy")
    values = np.asarray(modulation(gx.reshape(-1), gs.reshape(-1)), dtype=np.float64).reshape(ns, nx)
    mean = float(values.mean())
    centred = values - mean

    if s_periodic:
        window = np.ones(ns)
        window_note = "profile axis is closed: periodic transform"
    else:
        window = np.hanning(ns)
        window_note = "profile axis is open: Hann window, energy compensated"
    win2d = window[:, None] * np.ones((1, nx))
    windowed = centred * win2d
    energy_correction = 1.0 / max(float((win2d ** 2).mean()), 1e-12)

    spectrum = np.fft.fft2(windowed)[:, : nx // 2 + 1]           # positive azimuthal half
    power = np.asarray(np.abs(spectrum) ** 2 / (nx * ns) ** 2 * energy_correction,
                       dtype=np.float64)
    fx = np.fft.rfftfreq(nx, d=float(x_period_mm) / nx)          # cycles per mm, positive
    fs = np.abs(np.fft.fftfreq(ns, d=span / ns))                 # cycles per mm, folded
    fgrid = np.sqrt(fx[None, :] ** 2 + fs[:, None] ** 2)
    with np.errstate(divide="ignore"):
        wavelength = np.where(fgrid > 0, 1.0 / np.maximum(fgrid, 1e-12), np.inf)

    dx_mm = float(x_period_mm) / nx
    ds_mm = span / ns
    nyquist_wavelength_mm = 2.0 * max(dx_mm, ds_mm)
    total = float(power.sum())
    positive = fgrid > 0
    if not np.any(positive) or total <= 0.0:
        return {"status": "FLAT_FIELD", "mean": mean, "total_energy": total,
                "grid": {"n_x": nx, "n_s": ns, "dx_mm": dx_mm, "ds_mm": ds_mm}}

    flat_index = int(np.argmax(np.where(positive, power, -np.inf)))
    dom_f = float(fgrid.reshape(-1)[flat_index])
    dominant_wavelength = float(1.0 / dom_f)
    bands = []
    for k in range(int(band_count)):
        lo = dom_f * (2.0 ** (k - 1)) if k > 0 else 0.0
        hi = dom_f * (2.0 ** k)
        if k == 0:
            mask = positive & (fgrid <= hi)
        else:
            mask = positive & (fgrid > lo) & (fgrid <= hi)
        if not np.any(mask):
            bands.append({"band": k, "f_lo": float(lo), "f_hi": float(hi), "energy": 0.0,
                          "energy_fraction": 0.0, "peak_wavelength_mm": None})
            continue
        energy = float(power[mask].sum())
        peak = float(wavelength[mask][np.argmax(power[mask])])
        bands.append({
            "band": k, "f_lo": float(lo), "f_hi": float(hi), "energy": energy,
            "energy_fraction": float(energy / total),
            "peak_wavelength_mm": peak,
            "peak_f_mm_inv": float(1.0 / peak),
        })
    covered = float(sum(b["energy_fraction"] for b in bands))
    resolved = [b for b in bands if b["energy_fraction"] >= 0.05 and b["peak_wavelength_mm"]]
    min_wavelength = float(min(b["peak_wavelength_mm"] for b in resolved)) if resolved else None
    return {
        "status": "OK",
        "mean": mean,
        "total_energy": total,
        "dominant_f_mm_inv": dom_f,
        "dominant_wavelength_mm": dominant_wavelength,
        "octave_band_coverage": covered,
        "high_frequency_residual": float(max(0.0, 1.0 - covered)),
        "band_coverage_note": "five octave bands above the dominant frequency; the residual is "
                              "the energy above the highest band (or outside it)", 
        "min_wavelength_mm": min_wavelength,
        "min_wavelength_definition": "smallest octave band centre carrying >=5% of the energy",
        "bands": bands,
        "nyquist_wavelength_mm": float(nyquist_wavelength_mm),
        "grid": {"n_x": nx, "n_s": ns, "dx_mm": dx_mm, "ds_mm": ds_mm},
        "x_axis_periodic": True,
        "s_axis_periodic": bool(s_periodic),
        "window": window_note,
        "method": "numpy.fft.rfft2 on the frozen field sampled on a uniform chart grid",
    }
