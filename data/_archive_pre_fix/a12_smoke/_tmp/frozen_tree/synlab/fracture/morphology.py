"""Physically driven fracture-surface morphology on one shared partition plane.

Why this module exists
----------------------
``plane_shared_cut`` produces a mathematically perfect plane: correct, but it carries no
fracture *morphology*, and fracture morphology is the strongest signal a neighbour-piece
retrieval stage can read off a sherd edge.  ``rough_shared_cut`` adds a frozen finite-Fourier
height field, but its coefficients are drawn from the RNG rather than derived from the body, so
the relief it produces cannot be tied to the material or to the wall it broke out of.

This module adds morphology driven by **measured physical quantities** and keeps every frozen
numeric gate intact:

* wall thickness ``t`` (measured on the real mother) and the real material profile (grain size,
  pore scale, aggregate, fibre, glaze thickness) are the only physical inputs;
* the fracture-mirror radius comes from the fracture-mechanics mirror relation
  ``sigma_f * sqrt(r_m) = A_m`` with a porosity (Ryshkewitch-Duckworth) and wall-thickness
  (Weibull size effect) correction of the strength;
* the radial hackle-line count comes from the mirror radius and the grain size (lines diverge
  from the initiation point);
* the roughness spectrum (amplitude, correlation length, Hurst exponent) comes from the material
  profile;
* the pull-out pit density comes from the porosity area fraction.

Only *phases* and *pit positions* are drawn from a frozen deterministic stream: the amplitude /
wavelength / density structure is entirely physical.  That is the standard surface-metrology
construction (a random field with a prescribed, physically derived spectrum), and it is the
reason this is not "random noise pretending to be a fracture".

Numeric contract
----------------
The realized surface goes through the frozen shared-cutter path
(:func:`synlab.fracture.cut.build_closed_cutter`), so watertightness, the no-T-junction
triangulation, the interpolation budget and the "one cutter for both sides" property are the
same code that already passes A06.  Because the interpolation budget is a hard gate, the
*requested* physical relief may not fit the available cell budget; the requested and realized
curvature are both reported and the amplitude scale actually applied is published as
``precision_amplitude_scale`` (never silently dropped).  The precision ladder only ever scales
the relief *down*; it never relaxes the budget, the cell budget or any A06 threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

import numpy as np

from ..canonical import hash_json
from . import cut as cut_mod
from .cut import HeightField, FourierBand, build_band_window
from .spec import (
    DEFAULT_ERROR_BUDGET_MM,
    DEFAULT_MAX_CUTTER_CELLS,
    DEFAULT_MAX_CUTTER_TRIANGLES,
)

__all__ = [
    "MORPHOLOGY_META_KEY",
    "MaterialFractureInputs",
    "WallThickness",
    "FractureMorphologyParams",
    "MorphologyHeightField",
    "material_fracture_inputs",
    "wall_thickness",
    "derive_morphology_parameters",
    "build_morphology_field",
    "prepare_morphology",
    "build_morphology_cutter",
]

#: key under which the morphology parameter record is published (cutter / fragment / patch meta).
MORPHOLOGY_META_KEY = "fracture_morphology"
#: backend label carried in the parameter record.
BACKEND_MORPHOLOGY = "morphology_shared_cut"

#: reference uniaxial strength (MPa) of a dense, 5 mm wall ceramic body.
SIGMA_REF_MPA = 90.0
#: reference wall thickness (mm) the reference strength belongs to.
WALL_REF_MM = 5.0
#: Weibull modulus of a ceramic body (size effect ``sigma ~ t ** (-1/m)``).
WEIBULL_M = 9.0
#: Ryshkewitch-Duckworth porosity coefficient (``sigma ~ exp(-b * P)``).
RYSKEWITCH_B = 4.5
#: fracture-mirror constant (MPa * m^0.5), Mecholsky/Orr: ``sigma_f * sqrt(r_m) = A_m``.
MIRROR_CONSTANT_MPA_SQRT_M = 2.5
#: ratio of the mist boundary radius to the mirror boundary radius.
MIST_TO_MIRROR_RATIO = 1.8
#: pore-visibility weight -> area/volume porosity.  The material catalogue records a shading
#: weight, not a measured porosity, so the mapping is an explicit, documented calibration
#: (M01 pore_amount 0.45 -> 0.158, coarse earthenware; M04 0.03 -> 0.011, porcelain).
POROSITY_FROM_PORE_AMOUNT = 0.35
#: grain pull-out relief as a fraction of the grain size.
GRAIN_RELIEF_FRACTION = 0.12
#: porosity amplification of the grain relief.
POROSITY_RELIEF_GAIN = 2.0
#: Hurst exponent of a ceramic fracture surface (self-affine, ``S(k) ~ k ** -(2H+2)``).
HURST_EXPONENT = 0.75
#: number of Fourier bands used to realise the roughness spectrum.
ROUGHNESS_BANDS = 5
#: relief of a hackle ridge as a fraction of the requested roughness RMS.
HACKLE_AMPLITUDE_FRACTION = 0.55
#: relief of an arrest line (rib mark) as a fraction of the requested roughness RMS.
RIB_AMPLITUDE_FRACTION = 0.45
#: rib-mark spacing growth per mm away from the mirror boundary.
RIB_SPACING_GROWTH_PER_MM = 0.05
#: pull-out crater depth as a fraction of its radius.
PIT_DEPTH_FRACTION = 0.35
#: conchoidal bow radius as a multiple of the wall thickness.
CONCHOIDAL_RADIUS_PER_WALL = 6.0
#: smooth (glaze) fracture relief relative to the body relief.
GLAZE_ROUGHNESS_RATIO = 0.12
#: oblique-crossing factor: a plane crossing a glaze shell of thickness ``t_g`` at an average
#: angle leaves a strip of width ``t_g / sin(theta)``; averaged over orientations this is ~2 t_g.
GLAZE_STRIP_GEOMETRIC_FACTOR = 2.0
#: fraction of the cell-budget-implied curvature the *predicted* relief is allowed to use.
PRECISION_SAFETY = 0.5
#: relative steps of the relief-amplitude ladder applied when the prediction does not fit.
PRECISION_LADDER_FACTORS: tuple[float, ...] = (1.0, 0.5, 0.25)

_EPS = 1.0e-12


def _smootherstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(np.asarray(t, dtype=np.float64), 0.0, 1.0)
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    return out if np.isfinite(out) else float(default)


def _unit2(vector: Any) -> np.ndarray:
    v = np.asarray(vector, dtype=np.float64).reshape(-1)
    if v.size < 2:
        return np.array([1.0, 0.0])
    out = np.array([v[0], v[1]], dtype=np.float64)
    norm = float(np.linalg.norm(out))
    if norm < 1.0e-9:
        return np.array([1.0, 0.0])
    return out / norm


def _stable_int(payload: Any, modulo: int = 2 ** 32) -> int:
    digest = hash_json(payload).split(":", 1)[-1]
    return int(digest[:16], 16) % int(modulo)


# ---------------------------------------------------------------------------- physical inputs


@dataclass(frozen=True)
class MaterialFractureInputs:
    """Fracture-relevant part of one material profile (every value comes from the profile)."""

    material_id: str
    grain_scale_mm: float
    pore_scale_mm: float
    aggregate_radius_mm: float
    correlation_length_mm: float
    anisotropy: float
    fiber_period_mm: float
    fiber_direction: tuple[float, float, float]
    fiber_amount: float
    grain_amount: float
    pore_amount: float
    aggregate_amount: float
    appearance_roughness: float
    pore_roughness: float
    glaze_thickness_mm: float
    glaze_kind: str
    porosity: float
    pit_radius_mm: float
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id,
            "grain_scale_mm": self.grain_scale_mm,
            "pore_scale_mm": self.pore_scale_mm,
            "aggregate_radius_mm": self.aggregate_radius_mm,
            "correlation_length_mm": self.correlation_length_mm,
            "anisotropy": self.anisotropy,
            "fiber_period_mm": self.fiber_period_mm,
            "fiber_direction": list(self.fiber_direction),
            "fiber_amount": self.fiber_amount,
            "grain_amount": self.grain_amount,
            "pore_amount": self.pore_amount,
            "aggregate_amount": self.aggregate_amount,
            "appearance_roughness": self.appearance_roughness,
            "pore_roughness": self.pore_roughness,
            "glaze_thickness_mm": self.glaze_thickness_mm,
            "glaze_kind": self.glaze_kind,
            "porosity": self.porosity,
            "pit_radius_mm": self.pit_radius_mm,
            "source": self.source,
        }


def material_fracture_inputs(profile: Mapping[str, Any], *,
                             material_id: str = "") -> MaterialFractureInputs:
    """Extract the fracture inputs from a real material profile (never invents a value)."""
    stats = dict(profile.get("stats") or {})
    appearance = dict(profile.get("appearance") or {})
    layers = list(profile.get("layers") or [])
    mid = str(material_id or stats.get("material_id") or appearance.get("material_id") or "")
    glaze_thickness = 0.0
    glaze_kind = ""
    for layer in layers:
        name = str(layer.get("name", "")).lower()
        if "glaze" not in name and "paint" not in name:
            continue
        thickness = _as_float(layer.get("thickness_mm"))
        if thickness > glaze_thickness:
            glaze_thickness = thickness
            glaze_kind = str(layer.get("kind", ""))
    grain = _as_float(stats.get("grain_scale_mm"))
    correlation = _as_float(stats.get("correlation_length_mm"), grain)
    if correlation <= 0.0:
        correlation = grain
    pore_amount = _as_float(appearance.get("pore_amount"))
    pore_scale = _as_float(stats.get("pore_scale_mm"))
    direction = stats.get("fiber_direction") or (1.0, 0.0, 0.0)
    vec = np.asarray(direction, dtype=np.float64).reshape(-1)
    return MaterialFractureInputs(
        material_id=mid,
        grain_scale_mm=grain,
        pore_scale_mm=pore_scale,
        aggregate_radius_mm=_as_float(stats.get("aggregate_radius_mm")),
        correlation_length_mm=correlation,
        anisotropy=_as_float(stats.get("anisotropy")),
        fiber_period_mm=_as_float(stats.get("fiber_period_mm")),
        fiber_direction=tuple(float(x) for x in
                              (vec[:3] if vec.size >= 3 else np.array([1.0, 0.0, 0.0]))),
        fiber_amount=_as_float(appearance.get("fiber_amount")),
        grain_amount=_as_float(appearance.get("grain_amount")),
        pore_amount=pore_amount,
        aggregate_amount=_as_float(appearance.get("aggregate_amount")),
        appearance_roughness=_as_float(appearance.get("roughness")),
        pore_roughness=_as_float(appearance.get("pore_roughness")),
        glaze_thickness_mm=glaze_thickness,
        glaze_kind=glaze_kind,
        porosity=POROSITY_FROM_PORE_AMOUNT * pore_amount,
        pit_radius_mm=max(0.5 * pore_scale, 0.05),
        source=str(profile.get("notes", ""))[:120],
    )


@dataclass(frozen=True)
class WallThickness:
    """Measured wall-thickness distribution of the mother the fracture runs through."""

    min_mm: float
    p05_mm: float
    median_mm: float
    max_mm: float
    probes: int
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {"min_mm": self.min_mm, "p05_mm": self.p05_mm, "median_mm": self.median_mm,
                "max_mm": self.max_mm, "probes": self.probes, "source": self.source}


def wall_thickness(mother: Any, *, max_probes: int = 320) -> WallThickness:
    """Wall-thickness distribution from the mother's own frozen audit measurement."""
    from ..mothers.api import audit_mother

    report = audit_mother(mother, max_thickness_probes=int(max_probes),
                          run_self_intersection=False)
    thickness = dict((report.get("checks") or {}).get("min_thickness") or {})
    if not thickness:
        raise ValueError("mother audit produced no thickness measurement")
    fallback = _as_float(thickness.get("median_mm"), 1.0)
    return WallThickness(
        min_mm=_as_float(thickness.get("min_mm"), fallback),
        p05_mm=_as_float(thickness.get("p05_mm"), fallback),
        median_mm=_as_float(thickness.get("median_mm"), fallback),
        max_mm=_as_float(thickness.get("max_mm"), fallback),
        probes=int(thickness.get("n_valid", 0) or 0),
        source="synlab.mothers.audit.audit_mother:checks.min_thickness",
    )


# ---------------------------------------------------------------------------- parameter record


@dataclass(frozen=True)
class FractureMorphologyParams:
    """Frozen, JSON-serialisable morphology record (every number has a documented source)."""

    vessel_id: str = ""
    material_id: str = ""
    mother_id: str = ""
    event_id: str = ""
    backend: str = BACKEND_MORPHOLOGY
    material: dict[str, Any] = field(default_factory=dict)
    wall: dict[str, Any] = field(default_factory=dict)
    porosity: float = 0.0
    sigma_f_mpa: float = 0.0
    mirror_radius_mm: float = 0.0
    mist_radius_mm: float = 0.0
    requested_rms_mm: float = 0.0
    requested_curvature_per_mm: float = 0.0
    curvature_budget_per_mm: float = 0.0
    predicted_amplitude_scale: float = 1.0
    precision_amplitude_scale: float = 1.0
    precision_attempts: int = 0
    precision_ladder: tuple[float, ...] = ()
    correlation_length_mm: float = 0.0
    hurst_exponent: float = HURST_EXPONENT
    bands: tuple[tuple[float, float, float, float, float], ...] = ()
    dome_radius_mm: float = 0.0
    dome_amplitude_mm: float = 0.0
    hackle_count: int = 0
    hackle_spacing_at_mirror_mm: float = 0.0
    hackle_amplitude_mm: float = 0.0
    hackle_phase: float = 0.0
    rib_spacing_at_mirror_mm: float = 0.0
    rib_amplitude_mm: float = 0.0
    pit_count: int = 0
    pit_radius_mm: float = 0.0
    pit_depth_mm: float = 0.0
    pit_area_fraction: float = 0.0
    fiber_period_mm: float = 0.0
    fiber_amplitude_mm: float = 0.0
    glaze_thickness_mm: float = 0.0
    glaze_strip_width_mm: float = 0.0
    glaze_roughness_ratio: float = 1.0
    origin_uv_mm: tuple[float, float] = (0.0, 0.0)
    origin_world_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    extent_mm: tuple[float, float] = (0.0, 0.0)
    core_area_mm2: float = 0.0
    window_area_mm2: float = 0.0
    error_budget_mm: float = DEFAULT_ERROR_BUDGET_MM
    max_cells: int = DEFAULT_MAX_CUTTER_CELLS
    formulas: dict[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in self.__dataclass_fields__:
            value = getattr(self, key)
            if isinstance(value, tuple):
                out[key] = [list(v) if isinstance(v, tuple) else v for v in value]
            elif isinstance(value, dict):
                out[key] = dict(value)
            else:
                out[key] = value
        out["bands"] = [list(b) for b in self.bands]
        out["precision_ladder"] = [float(x) for x in self.precision_ladder]
        out["notes"] = list(self.notes)
        return out


_SIGMA_FORMULA = "sigma_f = sigma_ref * exp(-b * porosity) * (wall_ref / wall_p05) ** (1 / m)"
_MIRROR_FORMULA = "r_mirror[mm] = ((A_m[MPa m^0.5] / sigma_f[MPa]) * sqrt(1000)) ** 2"
_MIST_FORMULA = "r_mist = k_mh * r_mirror"
_HACKLE_FORMULA = "N_hackle = clip(round(2*pi*r_mirror / (2*grain)), 3, 48)"
_RELIEF_FORMULA = "sigma_r0 = c_g * grain * (1 + c_p * porosity)"
_SPECTRUM_FORMULA = ("a(k) = a_ref * (k/k_ref)^-(H+0.5) with k_ref = 2*pi/correlation_length, "
                     "renormalised so that sum(a_i^2/2) = sigma_r0^2")
_CURVATURE_FORMULA = "C_requested = sum(a_i*k_i^2) + hackle + ribs + pits, all area-weighted"
_BUDGET_FORMULA = ("C_budget = safety * max_cells * 8 * error_budget / effective_band_area_mm2; "
                   "predicted_amplitude_scale = min(1, C_budget / C_requested)")
_PIT_FORMULA = ("N_pit = porosity * core_area / (pi * pit_radius^2); "
                "depth = c_pit * pit_radius; positions are a stratified jittered scatter")
_GLAZE_FORMULA = "strip = t_glaze * k_geo along the cross-section boundary; relief *= ratio"
_DOME_FORMULA = "R_conchoidal = max(k_R * wall_p05, D^2 / (8 * sag_max)), sag_max = 4*sigma_r0"


# ---------------------------------------------------------------------------- derivation


def radius_grid(origin: np.ndarray, tris_uv: np.ndarray, *, n: int = 256) -> np.ndarray:
    """Radii (mm) at ``n`` quantiles of the cross-section, for the cost integrals."""
    pts = np.asarray(tris_uv, dtype=np.float64).reshape(-1, 2)
    if pts.shape[0] == 0:
        return np.zeros(1, dtype=np.float64)
    r = np.linalg.norm(pts - np.asarray(origin, dtype=np.float64).reshape(1, 2), axis=1)
    return np.quantile(r, np.linspace(0.0, 1.0, int(n)))


def _hackle_area_curvature(a_h: float, n_h: int, r_m: float, radii: np.ndarray) -> float:
    """``integral C dA`` of ``a_h*cos(N*theta)`` over the cross-section (``2*pi*r*dr`` shells)."""
    if a_h <= 0.0 or n_h <= 0 or r_m <= 0.0 or radii.size < 2:
        return 0.0
    r = np.clip(np.asarray(radii, dtype=np.float64), r_m * 1.001, None)
    k = n_h / np.maximum(r, _EPS)
    return float(np.trapezoid(a_h * k ** 2 * 2.0 * np.pi * r, r))


def _rib_area_curvature(a_rib: float, r_m: float, radii: np.ndarray,
                        growth: float = RIB_SPACING_GROWTH_PER_MM) -> float:
    if a_rib <= 0.0 or r_m <= 0.0 or radii.size < 2:
        return 0.0
    r = np.clip(np.asarray(radii, dtype=np.float64), r_m * 1.001, None)
    k = 2.0 * np.pi / np.maximum(r_m * (1.0 + growth * r), _EPS)
    return float(np.trapezoid(a_rib * k ** 2 * 2.0 * np.pi * r, r))


def derive_morphology_parameters(
    *,
    material: MaterialFractureInputs,
    wall: WallThickness,
    origin_uv: Sequence[float],
    tris_uv: np.ndarray,
    core_area_mm2: float,
    window_area_mm2: float,
    extent_mm: Sequence[float],
    rng: np.random.Generator,
    vessel_id: str = "",
    mother_id: str = "",
    event_id: str = "",
    error_budget_mm: float = DEFAULT_ERROR_BUDGET_MM,
    max_cells: int = DEFAULT_MAX_CUTTER_CELLS,
    origin_world_mm: Sequence[float] = (0.0, 0.0, 0.0),
) -> FractureMorphologyParams:
    """Derive every morphology parameter from the measured material and wall thickness.

    No number below is a free choice of the caller: each is the evaluation of a published
    relation on a measured input, and the relation is recorded in ``formulas``.  The amplitudes
    returned here are the *requested physical* ones; the precision budget only yields a
    prediction (``predicted_amplitude_scale``) that :func:`build_morphology_cutter` applies.
    """
    origin = np.asarray(origin_uv, dtype=np.float64).reshape(2)
    ex, ey = float(extent_mm[0]), float(extent_mm[1])
    diagonal = float(np.hypot(ex, ey))
    lc = float(max(material.correlation_length_mm, 1.0e-3))
    grain = float(max(material.grain_scale_mm, 1.0e-3))
    wall_p05 = float(max(wall.p05_mm, 1.0e-3))

    sigma_f = (SIGMA_REF_MPA * float(np.exp(-RYSKEWITCH_B * material.porosity))
               * (WALL_REF_MM / wall_p05) ** (1.0 / WEIBULL_M))
    r_mirror = float(((MIRROR_CONSTANT_MPA_SQRT_M / max(sigma_f, 1.0e-6)) * np.sqrt(1000.0)) ** 2)
    r_mirror = float(np.clip(r_mirror, 0.25, max(0.25, 0.25 * min(ex, ey, diagonal))))
    r_mist = float(min(MIST_TO_MIRROR_RATIO * r_mirror, max(r_mirror, 0.5 * diagonal)))

    n_hackle = int(np.clip(round(2.0 * np.pi * r_mirror / (2.0 * grain)), 3, 48))
    hackle_spacing = float(2.0 * np.pi * r_mirror / n_hackle)

    sigma_r0 = float(max(GRAIN_RELIEF_FRACTION * grain
                         * (1.0 + POROSITY_RELIEF_GAIN * material.porosity), 1.0e-4))
    band_wavelengths = np.array(
        [lc * (2.0 ** (i - (ROUGHNESS_BANDS - 1) / 2.0)) for i in range(ROUGHNESS_BANDS)],
        dtype=np.float64)
    band_wavelengths = np.clip(band_wavelengths, 0.20, max(4.0 * lc, 0.5))
    band_k = 2.0 * np.pi / band_wavelengths
    raw_amp = (band_k / (2.0 * np.pi / lc)) ** (-(HURST_EXPONENT + 0.5))
    raw_amp = raw_amp / max(float(np.sqrt(np.sum(0.5 * raw_amp ** 2))), _EPS)
    band_amp = raw_amp * sigma_r0

    a_hackle = HACKLE_AMPLITUDE_FRACTION * sigma_r0
    a_rib = RIB_AMPLITUDE_FRACTION * sigma_r0
    pit_radius = float(max(material.pit_radius_mm, 0.05))
    pit_area_fraction = float(np.clip(material.porosity, 0.0, 0.6))
    pit_count = int(min(max(0, round(pit_area_fraction * core_area_mm2 / (np.pi * pit_radius ** 2))),
                        4000))
    pit_depth = PIT_DEPTH_FRACTION * pit_radius

    radii = radius_grid(origin, tris_uv)
    r_max = float(radii.max()) if radii.size else 0.0
    sag_max = 4.0 * sigma_r0
    r_conch = max(CONCHOIDAL_RADIUS_PER_WALL * wall_p05,
                  diagonal ** 2 / (8.0 * max(sag_max, 1e-6)))
    dome_amp = float(min((r_max ** 2) / (2.0 * r_conch), sag_max))

    glaze_thickness = float(max(material.glaze_thickness_mm, 0.0))
    glaze_strip = glaze_thickness * GLAZE_STRIP_GEOMETRIC_FACTOR
    glaze_ratio = GLAZE_ROUGHNESS_RATIO if glaze_thickness > 0.0 else 1.0

    effective_area = float(max(core_area_mm2 + 0.7 * max(window_area_mm2 - core_area_mm2, 0.0),
                               1.0))
    c_budget = PRECISION_SAFETY * max_cells * 8.0 * error_budget_mm / effective_area
    c_bands = float(np.sum(band_amp * band_k ** 2))
    c_hackle = _hackle_area_curvature(a_hackle, n_hackle, r_mirror, radii) / effective_area
    c_rib = _rib_area_curvature(a_rib, r_mirror, radii) / effective_area
    c_pits = 2.0 * np.pi * pit_count * pit_depth / effective_area
    c_requested = float(c_bands + c_hackle + c_rib + c_pits)
    predicted = float(min(1.0, c_budget / max(c_requested, _EPS)))

    notes: list[str] = []
    if glaze_thickness <= 0.0:
        notes.append("unglazed profile: no glaze strip, the body relief applies to the whole face")
    else:
        notes.append(f"glaze layer {glaze_thickness:.3f} mm ({material.glaze_kind or 'n/a'}): "
                     f"relief damped to {glaze_ratio:.2f} inside the strip")
    if material.fiber_amount <= 0.0 or material.fiber_period_mm <= 0.0:
        notes.append("no fibre field in this profile: the periodic fibre term is inactive")
    if predicted < 1.0:
        notes.append(
            f"requested relief exceeds the frozen {error_budget_mm} mm interpolation budget at "
            f"the {max_cells} cell budget: predicted amplitude scale {predicted:.4f} "
            f"(C_requested {c_requested:.3f} /mm > C_budget {c_budget:.3f} /mm)")
    if r_mist >= 0.5 * diagonal:
        notes.append("mist boundary reaches the cross-section: the whole face is mist/hackle")

    fiber_dir = _unit2(np.asarray(material.fiber_direction, dtype=np.float64)[:2])
    spread = 0.6 * (1.0 - float(np.clip(material.anisotropy, 0.0, 1.0)))
    bands: list[tuple[float, float, float, float, float]] = []
    for wavelength, amplitude in zip(band_wavelengths, band_amp):
        if material.anisotropy > 0.0 and material.fiber_amount > 0.0:
            theta = float(np.arctan2(fiber_dir[1], fiber_dir[0])) + float(rng.normal(0.0, spread))
        else:
            theta = float(rng.uniform(0.0, 2.0 * np.pi))
        bands.append((float(amplitude), float(wavelength), float(np.cos(theta)),
                      float(np.sin(theta)), float(rng.uniform(0.0, 2.0 * np.pi))))

    return FractureMorphologyParams(
        vessel_id=str(vessel_id), material_id=str(material.material_id),
        mother_id=str(mother_id), event_id=str(event_id), backend=BACKEND_MORPHOLOGY,
        material=material.as_dict(), wall=wall.as_dict(),
        porosity=float(material.porosity), sigma_f_mpa=float(sigma_f),
        mirror_radius_mm=float(r_mirror), mist_radius_mm=float(r_mist),
        requested_rms_mm=float(sigma_r0), requested_curvature_per_mm=float(c_requested),
        curvature_budget_per_mm=float(c_budget),
        predicted_amplitude_scale=float(predicted),
        precision_amplitude_scale=float(predicted),
        correlation_length_mm=float(lc), hurst_exponent=float(HURST_EXPONENT),
        bands=tuple(bands),
        dome_radius_mm=float(r_conch), dome_amplitude_mm=float(dome_amp),
        hackle_count=int(n_hackle), hackle_spacing_at_mirror_mm=hackle_spacing,
        hackle_amplitude_mm=float(a_hackle),
        rib_spacing_at_mirror_mm=float(r_mirror), rib_amplitude_mm=float(a_rib),
        pit_count=int(pit_count), pit_radius_mm=pit_radius, pit_depth_mm=float(pit_depth),
        pit_area_fraction=pit_area_fraction,
        fiber_period_mm=float(material.fiber_period_mm),
        fiber_amplitude_mm=float(0.25 * sigma_r0 * material.fiber_amount),
        glaze_thickness_mm=glaze_thickness, glaze_strip_width_mm=float(glaze_strip),
        glaze_roughness_ratio=float(glaze_ratio),
        origin_uv_mm=(float(origin[0]), float(origin[1])),
        origin_world_mm=tuple(float(x) for x in np.asarray(origin_world_mm).reshape(-1)[:3]),
        extent_mm=(ex, ey), core_area_mm2=float(core_area_mm2),
        window_area_mm2=float(window_area_mm2),
        error_budget_mm=float(error_budget_mm), max_cells=int(max_cells),
        formulas={"sigma_f": _SIGMA_FORMULA, "mirror_radius": _MIRROR_FORMULA,
                  "mist_radius": _MIST_FORMULA, "hackle_count": _HACKLE_FORMULA,
                  "roughness_rms": _RELIEF_FORMULA, "roughness_spectrum": _SPECTRUM_FORMULA,
                  "curvature_requested": _CURVATURE_FORMULA,
                  "precision_budget": _BUDGET_FORMULA, "pits": _PIT_FORMULA,
                  "glaze": _GLAZE_FORMULA, "conchoidal": _DOME_FORMULA},
        notes=tuple(notes),
    )


def _scale_params(params: FractureMorphologyParams, scale: float, *,
                  attempts: int = 0, ladder: Sequence[float] = ()) -> FractureMorphologyParams:
    """Scale every relief amplitude by ``scale``; no physical input is modified."""
    scale = float(scale)
    bands = tuple((a * scale, w, du, dv, phase) for (a, w, du, dv, phase) in params.bands)
    return replace(
        params, bands=bands,
        hackle_amplitude_mm=params.hackle_amplitude_mm * scale,
        rib_amplitude_mm=params.rib_amplitude_mm * scale,
        pit_depth_mm=params.pit_depth_mm * scale,
        fiber_amplitude_mm=params.fiber_amplitude_mm * scale,
        precision_amplitude_scale=scale, precision_attempts=int(attempts),
        precision_ladder=tuple(float(x) for x in ladder),
    )


# ---------------------------------------------------------------------------- pits


@dataclass
class _PitSet:
    """Grain pull-out craters: positions are scrambled, density/depth/radius are physical."""

    centres_uv: np.ndarray
    radius_mm: float
    depth_mm: float
    cutoff: float = 2.5

    def __post_init__(self) -> None:
        self.centres_uv = np.asarray(self.centres_uv, dtype=np.float64).reshape(-1, 2)
        self._cell = max(3.0 * float(self.cutoff) * float(self.radius_mm), 1.0e-3)
        self._index: dict[tuple[int, int], list[int]] = {}
        reach = self.cutoff * float(self.radius_mm)
        for i, (cu, cv) in enumerate(self.centres_uv):
            for ii in range(int(np.floor((cu - reach) / self._cell)),
                            int(np.floor((cu + reach) / self._cell)) + 1):
                for jj in range(int(np.floor((cv - reach) / self._cell)),
                                int(np.floor((cv + reach) / self._cell)) + 1):
                    self._index.setdefault((ii, jj), []).append(i)

    def __len__(self) -> int:
        return int(self.centres_uv.shape[0])

    def value(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        out = np.zeros(np.broadcast(u, v).shape, dtype=np.float64)
        if not self._index or self.depth_mm == 0.0:
            return out
        u = np.asarray(u, dtype=np.float64)
        v = np.asarray(v, dtype=np.float64)
        gi = np.floor(u / self._cell).astype(np.int64).reshape(-1)
        gj = np.floor(v / self._cell).astype(np.int64).reshape(-1)
        wanted: set[int] = set()
        index = self._index
        for key in np.unique(np.stack([gi, gj], axis=1), axis=0):
            found = index.get((int(key[0]), int(key[1])))
            if found:
                wanted.update(found)
        if not wanted:
            return out
        scale = 1.0 / max(self.radius_mm, _EPS)
        cut2 = (self.cutoff * self.radius_mm) ** 2
        for i in sorted(wanted):
            cu, cv = self.centres_uv[i]
            d2 = (u - cu) ** 2 + (v - cv) ** 2
            hit = d2 <= cut2
            if not bool(np.any(hit)):
                continue
            out = out - np.where(hit, self.depth_mm * np.exp(-(d2 * scale ** 2)), 0.0)
        return out

    def curvature_bound(self) -> float:
        return float(2.0 * self.depth_mm / max(self.radius_mm ** 2, _EPS))


def points_in_triangles(points: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """True where a ``(u, v)`` point falls inside any of the ``(N, 3, 2)`` triangles."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    out = np.zeros(pts.shape[0], dtype=bool)
    for tri in np.asarray(tris, dtype=np.float64).reshape(-1, 3, 2):
        ax, ay = tri[0]
        bx, by = tri[1]
        cx, cy = tri[2]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1.0e-18:
            continue
        px, py = pts[:, 0] - cx, pts[:, 1] - cy
        w0 = ((by - cy) * px + (cx - bx) * py) / den
        w1 = ((cy - ay) * px + (ax - cx) * py) / den
        out |= (w0 >= -1.0e-12) & (w1 >= -1.0e-12) & (w0 + w1 <= 1.0 + 1.0e-12)
    return out


def scatter_pits(tris_uv: np.ndarray, origin_uv: Sequence[float], count: int, *,
                 seed_material: Any, min_radius_from_origin_mm: float = 0.0) -> np.ndarray:
    """Deterministic stratified scatter of pit centres inside the cross-section.

    The *density* is physical (porosity area fraction); the positions of individual pull-out
    sites are not, so they are drawn from a stratified (jittered) design: one candidate per
    stratum of the cross-section bounding box, jittered by a frozen hash stream, kept when it
    falls inside the cross-section and outside the mirror zone.  Reproducible for a given event
    id, and free of the clumping a plain uniform draw would produce.
    """
    tris = np.asarray(tris_uv, dtype=np.float64).reshape(-1, 3, 2)
    if tris.shape[0] == 0 or count <= 0:
        return np.zeros((0, 2), dtype=np.float64)
    lo = tris.reshape(-1, 2).min(axis=0)
    hi = tris.reshape(-1, 2).max(axis=0)
    span = np.maximum(hi - lo, 1.0e-6)
    n_side = int(max(2, np.ceil(np.sqrt(max(count, 1) * 2.0))))
    rng = np.random.Generator(np.random.PCG64(_stable_int(seed_material)))
    gu, gv = np.meshgrid(np.arange(n_side), np.arange(n_side), indexing="ij")
    cu = lo[0] + (gu.ravel() + 0.5) / n_side * span[0]
    cv = lo[1] + (gv.ravel() + 0.5) / n_side * span[1]
    cu = cu + (rng.random(cu.shape[0]) - 0.5) / n_side * span[0]
    cv = cv + (rng.random(cv.shape[0]) - 0.5) / n_side * span[1]
    keep = points_in_triangles(np.stack([cu, cv], axis=1), tris)
    if min_radius_from_origin_mm > 0.0:
        origin = np.asarray(origin_uv, dtype=np.float64).reshape(2)
        keep = keep & (np.hypot(cu - origin[0], cv - origin[1]) >= min_radius_from_origin_mm)
    cu, cv = cu[keep], cv[keep]
    if cu.size > count:
        pick = rng.permutation(cu.size)[:int(count)]
        cu, cv = cu[pick], cv[pick]
    return np.stack([cu, cv], axis=1)


# ---------------------------------------------------------------------------- modulation


@dataclass
class _Raster:
    """Smooth scalar envelope on the cutter ``(u, v)`` rectangle (bilinear lookup)."""

    u0: float
    v0: float
    step_mm: float
    values: np.ndarray

    def value(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        fi = (np.asarray(u, dtype=np.float64) - self.u0) / self.step_mm
        fj = (np.asarray(v, dtype=np.float64) - self.v0) / self.step_mm
        fi = np.clip(fi, 0.0, self.values.shape[0] - 1.0 - 1e-12)
        fj = np.clip(fj, 0.0, self.values.shape[1] - 1.0 - 1e-12)
        i0 = np.floor(fi).astype(np.int64)
        j0 = np.floor(fj).astype(np.int64)
        ti = fi - i0
        tj = fj - j0
        i1 = np.minimum(i0 + 1, self.values.shape[0] - 1)
        j1 = np.minimum(j0 + 1, self.values.shape[1] - 1)
        a = self.values[i0, j0] * (1 - ti) + self.values[i1, j0] * ti
        b = self.values[i0, j1] * (1 - ti) + self.values[i1, j1] * ti
        return a * (1 - tj) + b * tj


def glaze_modulation(window: Any, strip_mm: float, ratio: float) -> _Raster | None:
    """Body/glaze relief envelope from the distance to the cross-section boundary.

    The glaze shell is crossed by the cutting plane in a strip of width ``t_glaze/sin(theta)``
    along the boundary of the cross-section, so the distance field of the material band *is* the
    geometric quantity that decides where the crack ran through glaze and where it ran through
    body.  ``ratio`` is the relief that survives inside the strip.
    """
    if window is None or strip_mm <= 0.0 or ratio >= 1.0:
        return None
    from scipy import ndimage

    core = np.asarray(window.core, dtype=bool)
    if not bool(core.any()):
        return None
    step = float(window.step_mm)
    width = max(float(strip_mm), 2.0 * step)   # a narrower transition is not representable
    depth = ndimage.distance_transform_edt(core) * step
    values = ratio + (1.0 - ratio) * _smootherstep(depth / width)
    return _Raster(u0=float(window.u0), v0=float(window.v0), step_mm=step, values=values)


# ---------------------------------------------------------------------------- height field


@dataclass
class MorphologyHeightField(HeightField):
    """``w = W(u, v) * (dome + G(u, v) * [roughness + hackle + ribs + pits + fibre])``.

    ``W`` is the frozen material-band envelope of :mod:`synlab.fracture.cut` (exactly flat far
    from the material, so coarse frame cells carry zero interpolation error) and ``G`` is the
    body/glaze relief envelope.  Everything is analytic except the pit sum and ``G``, which are
    evaluated from bucketed tables because the refinement calls the field once per quadtree cell.
    """

    morphology: FractureMorphologyParams | None = None
    pits: Any = None
    modulation: Any = None
    origin_uv: tuple[float, float] = (0.0, 0.0)
    dome_radius_mm: float = 0.0
    dome_amplitude_mm: float = 0.0
    hackle_count: int = 0
    hackle_amplitude_mm: float = 0.0
    hackle_phase: float = 0.0
    mirror_radius_mm: float = 1.0
    mist_radius_mm: float = 1.8
    rib_amplitude_mm: float = 0.0
    rib_spacing_mm: float = 1.0
    rib_growth: float = RIB_SPACING_GROWTH_PER_MM
    fiber_amplitude_mm: float = 0.0
    fiber_wavelength_mm: float = 0.0
    fiber_direction: tuple[float, float] = (1.0, 0.0)
    amplitude_max_mm: float = 0.0

    # ------------------------------------------------------------------ components
    def _roughness(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        out = np.zeros(np.broadcast(u, v).shape, dtype=np.float64)
        for band in self.bands:
            k = band.k
            out = out + band.amplitude_mm * np.cos(
                k * (band.direction[0] * u + band.direction[1] * v) + band.phase)
        return out

    def _radial(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        du = np.asarray(u, dtype=np.float64) - self.origin_uv[0]
        dv = np.asarray(v, dtype=np.float64) - self.origin_uv[1]
        return np.hypot(du, dv), np.arctan2(dv, du)

    def hackle(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Radial hackle lines: ``N`` lines diverging from the fracture origin."""
        shape = np.broadcast(u, v).shape
        if self.hackle_count <= 0 or self.hackle_amplitude_mm <= 0.0:
            return np.zeros(shape, dtype=np.float64)
        r, theta = self._radial(u, v)
        r_m = max(self.mirror_radius_mm, _EPS)
        r_mist = max(self.mist_radius_mm, r_m * 1.0001)
        ramp = _smootherstep((r - r_m) / max(r_mist - r_m, _EPS))
        growth = 1.0 + 0.35 * np.log1p(np.clip(r / r_mist, 0.0, 200.0))
        return self.hackle_amplitude_mm * ramp * growth * np.cos(
            self.hackle_count * theta + self.hackle_phase)

    def ribs(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Arrest lines (rib marks): the mirror boundary is the first one, spacing grows."""
        shape = np.broadcast(u, v).shape
        if self.rib_amplitude_mm <= 0.0 or self.rib_spacing_mm <= 0.0:
            return np.zeros(shape, dtype=np.float64)
        r, _theta = self._radial(u, v)
        beta = max(self.rib_growth, 1.0e-9)
        phase = 2.0 * np.pi * np.log1p(beta * r) / (beta * self.rib_spacing_mm)
        ramp = _smootherstep((r - self.rib_spacing_mm) / max(0.5 * self.rib_spacing_mm, _EPS))
        return self.rib_amplitude_mm * ramp * np.cos(phase)

    def dome(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        if self.dome_radius_mm <= 0.0:
            return np.zeros(np.broadcast(u, v).shape, dtype=np.float64)
        du = np.asarray(u, dtype=np.float64) - self.origin_uv[0]
        dv = np.asarray(v, dtype=np.float64) - self.origin_uv[1]
        return (du ** 2 + dv ** 2) / (2.0 * self.dome_radius_mm)

    def fibre(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        if self.fiber_amplitude_mm <= 0.0 or self.fiber_wavelength_mm <= 0.0:
            return np.zeros(np.broadcast(u, v).shape, dtype=np.float64)
        arg = (self.fiber_direction[0] * np.asarray(u, dtype=np.float64)
               + self.fiber_direction[1] * np.asarray(v, dtype=np.float64))
        return self.fiber_amplitude_mm * np.cos(
            2.0 * np.pi * arg / self.fiber_wavelength_mm)

    def _relief(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Everything except the conchoidal form, with the body/glaze envelope applied."""
        out = self._roughness(u, v) + self.hackle(u, v) + self.ribs(u, v) + self.fibre(u, v)
        if self.pits is not None and len(self.pits):
            out = out + self.pits.value(u, v)
        if self.modulation is not None:
            out = out * self.modulation.value(u, v)
        return out

    # ------------------------------------------------------------------ HeightField API
    def raw(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        return self.dome(u, v) + self._relief(u, v)

    def gradient(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        u = np.asarray(u, dtype=np.float64)
        v = np.asarray(v, dtype=np.float64)
        du = np.zeros(np.broadcast(u, v).shape, dtype=np.float64)
        dv = np.zeros_like(du)
        for band in self.bands:
            k = band.k
            arg = k * (band.direction[0] * u + band.direction[1] * v) + band.phase
            s = -band.amplitude_mm * k * np.sin(arg)
            du = du + s * band.direction[0]
            dv = dv + s * band.direction[1]
        # the remaining components are bounded by their own curvature; a central difference of
        # that (cheap) part is what the envelope cross-term guard needs, never the inverse
        step = 0.05
        rest = self.dome(u, v) + self._relief(u, v)
        rest_u = (self.dome(u + step, v) + self._relief(u + step, v) - rest) / step
        rest_v = (self.dome(u, v + step) + self._relief(u, v + step) - rest) / step
        return du + rest_u, dv + rest_v

    def curvature_bound(self) -> float:
        """Upper bound of the *unwindowed* ``|h_aa|`` along any unit (u, v) direction."""
        total = 0.0
        for band in self.bands:
            total += band.amplitude_mm * band.k ** 2
        r_m = max(self.mirror_radius_mm, _EPS)
        r_mist = max(self.mist_radius_mm, r_m)
        if self.hackle_count > 0:
            total += self.hackle_amplitude_mm * (
                (self.hackle_count / r_m) ** 2 + (0.35 / r_mist) ** 2)
        if self.rib_amplitude_mm > 0.0 and self.rib_spacing_mm > 0.0:
            total += self.rib_amplitude_mm * (2.0 * np.pi / self.rib_spacing_mm) ** 2
        if self.pits is not None and len(self.pits):
            total += float(self.pits.curvature_bound())
        if self.fiber_amplitude_mm > 0.0 and self.fiber_wavelength_mm > 0.0:
            total += self.fiber_amplitude_mm * (2.0 * np.pi / self.fiber_wavelength_mm) ** 2
        return float(total)

    def gradient_bound(self) -> float:
        """Upper bound of ``|grad h|`` (used only for the envelope cross-term bound)."""
        total = 0.0
        for band in self.bands:
            total += band.amplitude_mm * band.k
        r_m = max(self.mirror_radius_mm, _EPS)
        if self.hackle_count > 0:
            total += self.hackle_amplitude_mm * (
                self.hackle_count / r_m + 0.35 / max(self.mist_radius_mm, r_m))
        if self.rib_amplitude_mm > 0.0 and self.rib_spacing_mm > 0.0:
            total += self.rib_amplitude_mm * 2.0 * np.pi / self.rib_spacing_mm
        if self.fiber_amplitude_mm > 0.0 and self.fiber_wavelength_mm > 0.0:
            total += self.fiber_amplitude_mm * 2.0 * np.pi / self.fiber_wavelength_mm
        if self.pits is not None and len(self.pits):
            total += float(np.sqrt(2.0 / np.e)) * float(self.pits.depth_mm) / max(
                float(self.pits.radius_mm), _EPS)
        return float(total)

    def windowed_curvature_bound(self) -> float:
        """``|(W h)_aa|`` bound including the band and glaze envelopes' own derivatives."""
        base = self.curvature_bound()
        if self.window is None:
            return base
        slope = float(np.max(np.hypot(self.window.grad_u, self.window.grad_v)))
        second = float(np.max(np.abs(self.window.lap)))
        amp = float(self.amplitude_max_mm) + float(abs(self.dome_amplitude_mm))
        extra = 2.0 * slope * float(self.gradient_bound()) + second * amp
        if self.modulation is not None:
            step = max(float(self.modulation.step_mm), _EPS)
            gy, gx = np.gradient(self.modulation.values, step)
            mod_slope = float(np.max(np.abs(gx))) + float(np.max(np.abs(gy)))
            extra += (2.0 * mod_slope + 2.0 * mod_slope / step) * float(self.amplitude_max_mm)
        return float(base + extra)

    def as_dict(self) -> dict[str, Any]:
        out = super().as_dict()
        out["morphology"] = None if self.morphology is None else self.morphology.as_dict()
        out["components"] = {
            "dome_radius_mm": float(self.dome_radius_mm),
            "dome_amplitude_mm": float(self.dome_amplitude_mm),
            "hackle_count": int(self.hackle_count),
            "hackle_amplitude_mm": float(self.hackle_amplitude_mm),
            "rib_amplitude_mm": float(self.rib_amplitude_mm),
            "rib_spacing_mm": float(self.rib_spacing_mm),
            "pit_count": 0 if self.pits is None else int(len(self.pits)),
            "fiber_amplitude_mm": float(self.fiber_amplitude_mm),
            "glaze_modulation": self.modulation is not None,
            "origin_uv_mm": list(self.origin_uv),
        }
        return out


def flat_cross_section(basis: Any, mesh: Any) -> tuple[np.ndarray, float, dict[str, Any]]:
    """Reuse the frozen flat cross-section estimator (:mod:`synlab.fracture.cut`) as footprint."""
    return cut_mod._flat_cross_section_uv(basis, mesh, error_budget_mm=1.0e-2)


def initiate_origin(tris_uv: np.ndarray, wall_p05_mm: float) -> np.ndarray:
    """Fracture origin in ``(u, v)``: an extremity of the cross-section on the outer wall.

    Initiation is surface-controlled, so the origin must sit on the body surface, and the stress
    is highest at the extremity of the cross-section where the constraint is lowest.  Among the
    cross-section vertices that lie within ``2 * t_p05`` of the cross-section *boundary*, the one
    farthest from the area centroid is taken: deterministic and reproducible for one geometry.
    The origin stays a free physical input of the model (the caller may pass its own).
    """
    tris = np.asarray(tris_uv, dtype=np.float64).reshape(-1, 3, 2)
    if tris.shape[0] == 0:
        return np.zeros(2, dtype=np.float64)
    pts = tris.reshape(-1, 2)
    areas = np.abs((tris[:, 1, 0] - tris[:, 0, 0]) * (tris[:, 2, 1] - tris[:, 0, 1])
                   - (tris[:, 2, 0] - tris[:, 0, 0]) * (tris[:, 1, 1] - tris[:, 0, 1])) * 0.5
    centroid = np.average(pts, axis=0, weights=np.maximum(np.repeat(areas, 3), 1e-12))
    boundary = None
    try:
        import shapely

        union = shapely.union_all(shapely.polygons(tris))
        boundary = union.boundary
        distance = np.asarray(shapely.distance(boundary, shapely.points(pts)), dtype=np.float64)
    except Exception:  # noqa: BLE001 - geometric evidence, never a hard dependency
        boundary = None
    if boundary is None or not np.any(np.isfinite(distance)):
        from scipy.spatial import cKDTree

        tree = cKDTree(pts)
        _d, idx = tree.query(pts, k=2)
        distance = _d[:, 1] if _d.ndim > 1 and _d.shape[1] > 1 else np.zeros(pts.shape[0])
    near_wall = distance <= max(2.0 * float(wall_p05_mm), 1.0e-3)
    candidates = pts[near_wall] if bool(np.any(near_wall)) else pts
    if candidates.shape[0] == 0:
        candidates = pts
    return candidates[int(np.argmax(np.linalg.norm(candidates - centroid, axis=1)))].astype(
        np.float64)


def build_morphology_field(
    basis: Any,
    mesh: Any,
    params: FractureMorphologyParams,
    *,
    rng: np.random.Generator | None = None,
    probe_step_mm: float | None = None,
    halo_mm: float | None = None,
    cross_section: tuple[np.ndarray, float, dict[str, Any]] | None = None,
) -> MorphologyHeightField:
    """Realise ``params`` as an analytic height field over the cut basis."""
    origin = np.asarray(params.origin_uv_mm, dtype=np.float64).reshape(2)
    bands = [FourierBand(amplitude_mm=a, wavelength_mm=w,
                         direction=np.array([du, dv]), phase=phase)
             for (a, w, du, dv, phase) in params.bands]
    fiber_dir = _unit2(np.asarray(params.material.get("fiber_direction", [1.0, 0.0, 0.0]),
                                  dtype=np.float64)[:2])
    field = MorphologyHeightField(
        basis=basis, bands=bands, bend=[], mean_mm=0.0,
        target_rms_mm=float(params.requested_rms_mm), realized_rms_mm=0.0,
        wavelength_min_mm=float(min([b.wavelength_mm for b in bands] or [float("inf")])),
        max_slope=0.0,
        meta={"morphology": params.as_dict()}, morphology=params,
        origin_uv=(float(origin[0]), float(origin[1])),
        dome_radius_mm=float(params.dome_radius_mm),
        dome_amplitude_mm=float(params.dome_amplitude_mm),
        hackle_count=int(params.hackle_count),
        hackle_amplitude_mm=float(params.hackle_amplitude_mm),
        hackle_phase=float(params.hackle_phase),
        mirror_radius_mm=float(params.mirror_radius_mm),
        mist_radius_mm=float(params.mist_radius_mm),
        rib_amplitude_mm=float(params.rib_amplitude_mm),
        rib_spacing_mm=float(params.rib_spacing_mm),
        fiber_amplitude_mm=float(params.fiber_amplitude_mm),
        fiber_wavelength_mm=float(params.fiber_period_mm),
        fiber_direction=(float(fiber_dir[0]), float(fiber_dir[1])),
        amplitude_max_mm=float(max(
            [b.amplitude_mm for b in bands]
            + [params.hackle_amplitude_mm, params.rib_amplitude_mm,
               params.fiber_amplitude_mm, params.pit_depth_mm, 0.0])),
    )
    tris_uv, core_area, info = (cross_section if cross_section is not None
                                else flat_cross_section(basis, mesh))
    centres = scatter_pits(tris_uv, origin, int(params.pit_count),
                           seed_material={"event": params.event_id,
                                          "material": params.material_id,
                                          "mirror": round(params.mirror_radius_mm, 6)},
                           min_radius_from_origin_mm=float(params.mirror_radius_mm))
    field.pits = _PitSet(centres_uv=centres, radius_mm=float(params.pit_radius_mm),
                         depth_mm=float(params.pit_depth_mm))
    field.meta["flat_cross_section"] = dict(info)
    field.meta["pit_centres_uv"] = np.round(centres[:64], 6).tolist()
    field.meta["pit_centre_count"] = int(centres.shape[0])
    field.meta["core_area_mm2"] = float(core_area)
    # The band envelope is sized from this number, so it must be published before the window.
    # The conchoidal form is carried in the *margin* (its reach can put the surface inside the
    # material) but not in the halo: the halo only has to make the lateral decay smooth, and
    # letting a millimetre-scale bow inflate it would multiply the cutter cell cost for nothing.
    relief_amp = float(max(
        [b.amplitude_mm for b in bands]
        + [params.hackle_amplitude_mm, params.rib_amplitude_mm,
           params.fiber_amplitude_mm, params.pit_depth_mm, 0.0]))
    field.meta["amplitude_max_mm"] = float(max(relief_amp, abs(field.dome_amplitude_mm)))
    field.meta["relief_amplitude_mm"] = relief_amp
    if halo_mm is None:
        halo_mm = float(max(cut_mod.BAND_HALO_MM, 8.0 * relief_amp))

    window, norm_uv = build_band_window(basis, field, mesh, probe_step_mm=probe_step_mm,
                                        halo_mm=halo_mm)
    field.window = window
    field.modulation = glaze_modulation(window, float(params.glaze_strip_width_mm),
                                        float(params.glaze_roughness_ratio))
    raw = field.raw(norm_uv[0], norm_uv[1])
    field.mean_mm = float(np.mean(raw))
    field.realized_rms_mm = float(np.sqrt(np.mean((raw - field.mean_mm) ** 2)))
    grad_u, grad_v = field.gradient(norm_uv[0], norm_uv[1])
    field.max_slope = float(np.max(np.hypot(grad_u, grad_v)))
    return field


# ---------------------------------------------------------------------------- cutter / event


def prepare_morphology(
    mother: Any,
    *,
    material_profile: Mapping[str, Any],
    rng: np.random.Generator,
    basis: Any | None = None,
    event_id: str = "",
    error_budget_mm: float = DEFAULT_ERROR_BUDGET_MM,
    max_cells: int = DEFAULT_MAX_CUTTER_CELLS,
    wall_probes: int = 320,
    origin_uv: Sequence[float] | None = None,
    window_area_estimate_mm2: float | None = None,
) -> dict[str, Any]:
    """Measure the body once and derive the morphology parameters (no cutter is built).

    Kept separate so a caller can run a *plane* baseline with exactly the same basis, the same
    wall measurement, the same material and the same fracture origin, which is what makes the
    "morphology vs plane" comparison apples to apples.
    """
    from .api import _default_basis
    from .spec import FractureSpec

    if basis is None:
        basis = _default_basis(mother, rng, FractureSpec())
    mesh = mother.mesh
    material = material_fracture_inputs(material_profile)
    wall = wall_thickness(mother, max_probes=wall_probes)
    tris_uv, core_area, cross_info = flat_cross_section(basis, mesh)
    mu = basis.meta.get("material_u_range", basis.u_range)
    mv = basis.meta.get("material_v_range", basis.v_range)
    ex, ey = float(mu[1] - mu[0]), float(mv[1] - mv[0])
    origin = (np.asarray(origin_uv, dtype=np.float64).reshape(2)
              if origin_uv is not None else initiate_origin(tris_uv, wall.p05_mm))
    window_estimate = (float(window_area_estimate_mm2) if window_area_estimate_mm2
                       else float(core_area * 2.2 + 500.0))
    base = derive_morphology_parameters(
        material=material, wall=wall, origin_uv=origin, tris_uv=tris_uv,
        core_area_mm2=core_area, window_area_mm2=window_estimate,
        extent_mm=(ex, ey), rng=rng, vessel_id=str(getattr(mother, "vessel_id", "")),
        mother_id=str(getattr(mother, "mother_id", "")), event_id=event_id,
        error_budget_mm=float(error_budget_mm), max_cells=int(max_cells),
        origin_world_mm=basis.to_world(np.array([[origin[0], origin[1], 0.0]]))[0],
    )
    return {"basis": basis, "material": material, "wall": wall, "tris_uv": tris_uv,
            "core_area_mm2": float(core_area), "cross_info": cross_info,
            "origin_uv": origin, "base_params": base, "extent_mm": (ex, ey),
            "window_area_estimate_mm2": window_estimate, "event_id": str(event_id)}


def build_morphology_cutter(
    mother: Any,
    *,
    material_profile: Mapping[str, Any] | None = None,
    rng: np.random.Generator,
    basis: Any | None = None,
    prepared: Mapping[str, Any] | None = None,
    event_id: str = "",
    error_budget_mm: float = DEFAULT_ERROR_BUDGET_MM,
    max_cells: int = DEFAULT_MAX_CUTTER_CELLS,
    max_triangles: int = DEFAULT_MAX_CUTTER_TRIANGLES,
    wall_probes: int = 320,
    allow_precision_ladder: bool = True,
    origin_uv: Sequence[float] | None = None,
    window_area_estimate_mm2: float | None = None,
) -> tuple[Any, MorphologyHeightField, FractureMorphologyParams, dict[str, Any]]:
    """Build the shared morphology cutter and its parameter record.

    Returns ``(cutter_result, height_field, params, report)``.  The precision ladder only ever
    *scales the relief down* and records the scale it used; it never relaxes the interpolation
    budget, the cell budget or any A06 threshold.
    """
    from ..schemas.runtime import CutterResult
    from .booleans import mesh_hash

    if prepared is None:
        if material_profile is None:
            raise ValueError("build_morphology_cutter needs either material_profile or prepared")
        prepared = prepare_morphology(
            mother, material_profile=material_profile, rng=rng, basis=basis, event_id=event_id,
            error_budget_mm=error_budget_mm, max_cells=max_cells, wall_probes=wall_probes,
            origin_uv=origin_uv, window_area_estimate_mm2=window_area_estimate_mm2)
    basis = prepared["basis"]
    mesh = mother.mesh
    tris_uv = prepared["tris_uv"]
    core_area = float(prepared["core_area_mm2"])
    cross_info = prepared["cross_info"]
    base: FractureMorphologyParams = prepared["base_params"]
    if event_id and not base.event_id:
        base = replace(base, event_id=str(event_id))

    factors = PRECISION_LADDER_FACTORS if allow_precision_ladder else (1.0,)
    ladder = tuple(dict.fromkeys(float(base.predicted_amplitude_scale) * f for f in factors))
    ladder = tuple(x for x in ladder if x > 1.0e-6)
    last_error: Exception | None = None
    for attempt, rung in enumerate(ladder, start=1):
        params = _scale_params(base, rung, attempts=attempt, ladder=ladder)
        field = build_morphology_field(basis, mesh, params, rng=rng,
                                       cross_section=(tris_uv, core_area, cross_info))
        try:
            cutter_mesh, cutter_report = cut_mod.build_closed_cutter(
                basis, field, error_budget_mm=float(error_budget_mm),
                max_cells=int(max_cells), max_triangles=int(max_triangles))
        except Exception as exc:  # noqa: BLE001 - a resource failure is a measurement
            last_error = exc
            code = str(getattr(getattr(exc, "code", None), "value", ""))
            if code not in ("PRECISION_BUDGET_EXCEEDED", "PRECISION_NOT_REALIZED") \
                    or attempt == len(ladder):
                raise
            continue
        report = dict(cutter_report)
        report["morphology_params"] = params.as_dict()
        report["morphology_field"] = field.as_dict()
        report["precision_ladder"] = list(ladder)
        report["precision_ladder_step"] = float(rung)
        report["precision_ladder_attempts"] = int(attempt)
        report["backend"] = BACKEND_MORPHOLOGY
        report["cutter_hash"] = mesh_hash(cutter_mesh)
        report["core_area_mm2"] = float(core_area)
        report["window_area_mm2"] = float(field.window.as_dict()["window_area_mm2"])
        cutter = CutterResult(
            mesh=cutter_mesh, basis=basis,
            h_fn=(lambda u, v: np.asarray(field(u, v), dtype=np.float64)),
            requested_error_mm=float(error_budget_mm),
            realized_error_mm=float(cutter_report.get("realized_error_mm", float("inf"))),
            triangles=int(len(np.asarray(cutter_mesh.faces))),
            meta={k: v for k, v in report.items() if k != "morphology_field"},
        )
        cutter.meta["height_field"] = field.as_dict()
        if cutter.realized_error_mm > float(error_budget_mm) + 1.0e-12:
            raise AssertionError("cutter reported a realized error above its budget")
        return cutter, field, params, report
    raise last_error if last_error is not None else RuntimeError("no morphology cutter candidate")
