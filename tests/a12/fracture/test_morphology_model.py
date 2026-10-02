"""Physics and model contracts of the fracture-morphology module (plan: fracture realism).

Every assertion here ties one model number back to the measured physical quantity it is supposed
to come from: wall thickness and porosity enter the strength, the strength fixes the mirror
radius, the mirror radius and the grain size fix the hackle line count, the grain size and the
porosity fix the relief, and the porosity fixes the pull-out pit density.  The tests are also the
guard against the failure mode the task forbids: relief that is *not* a function of the body.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.fracture.cut import build_basis  # noqa: E402
from synlab.fracture.morphology import (  # noqa: E402
    GRAIN_RELIEF_FRACTION,
    MIRROR_CONSTANT_MPA_SQRT_M,
    MIST_TO_MIRROR_RATIO,
    MORPHOLOGY_META_KEY,
    POROSITY_FROM_PORE_AMOUNT,
    POROSITY_RELIEF_GAIN,
    PRECISION_SAFETY,
    RYSKEWITCH_B,
    SIGMA_REF_MPA,
    WALL_REF_MM,
    WEIBULL_M,
    MorphologyHeightField,
    WallThickness,
    _scale_params,
    derive_morphology_parameters,
    material_fracture_inputs,
    scatter_pits,
)
from synlab.fracture.surface_features import detrend_plane  # noqa: E402
from synlab.materials.api import build_material_profile, default_material_params  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

MASTER_SEED = 20261001


def profile_of(material_id: str) -> dict:
    return build_material_profile(material_id, default_material_params(material_id),
                                  make_rng(MASTER_SEED, "morphology_test", "materials", material_id))


def square_cross_section(size_mm: float = 20.0) -> np.ndarray:
    half = 0.5 * float(size_mm)
    a = np.array([-half, -half])
    b = np.array([half, -half])
    c = np.array([half, half])
    d = np.array([-half, half])
    return np.array([[a, b, c], [a, c, d]], dtype=np.float64)


def params_for(material_id: str, *, wall_p05_mm: float = 5.0, wall_median_mm: float = 6.0,
               size_mm: float = 20.0, core_area_mm2: float | None = None,
               window_area_mm2: float | None = None):
    material = material_fracture_inputs(profile_of(material_id), material_id=material_id)
    wall = WallThickness(min_mm=wall_p05_mm * 0.8, p05_mm=wall_p05_mm, median_mm=wall_median_mm,
                         max_mm=wall_median_mm * 1.5, probes=320, source="test")
    tris = square_cross_section(size_mm)
    area = core_area_mm2 if core_area_mm2 is not None else size_mm ** 2
    window = window_area_mm2 if window_area_mm2 is not None else area * 2.2 + 500.0
    return derive_morphology_parameters(
        material=material, wall=wall, origin_uv=(0.5 * size_mm, 0.5 * size_mm), tris_uv=tris,
        core_area_mm2=area, window_area_mm2=window, extent_mm=(size_mm, size_mm),
        rng=np.random.default_rng(7), vessel_id="V_TEST", mother_id="M_TEST",
        event_id="E_TEST", origin_world_mm=(0.0, 0.0, 0.0),
    )


# ---------------------------------------------------------------------------- strength / mirror


def test_mirror_radius_follows_the_fracture_mirror_relation() -> None:
    params = params_for("M02", wall_p05_mm=5.0)
    expected_sigma = (SIGMA_REF_MPA * np.exp(-RYSKEWITCH_B * params.porosity)
                      * (WALL_REF_MM / 5.0) ** (1.0 / WEIBULL_M))
    assert params.sigma_f_mpa == pytest.approx(float(expected_sigma), rel=1e-9)
    expected_rm = ((MIRROR_CONSTANT_MPA_SQRT_M / expected_sigma) * np.sqrt(1000.0)) ** 2
    assert params.mirror_radius_mm == pytest.approx(float(expected_rm), rel=1e-6)
    assert params.mist_radius_mm == pytest.approx(
        min(MIST_TO_MIRROR_RATIO * params.mirror_radius_mm, params.mist_radius_mm), rel=1e-9)
    # the porosity mapping is the documented calibration of the catalogue's shading weight
    material = params.material
    assert params.porosity == pytest.approx(
        POROSITY_FROM_PORE_AMOUNT * material["pore_amount"], rel=1e-12)


def test_thicker_wall_is_weaker_and_gets_a_larger_mirror_zone() -> None:
    """Weibull size effect: a bigger stressed volume is weaker, so its mirror zone is larger."""
    thin = params_for("M02", wall_p05_mm=2.0)
    thick = params_for("M02", wall_p05_mm=10.0)
    assert thick.sigma_f_mpa < thin.sigma_f_mpa
    assert thick.mirror_radius_mm > thin.mirror_radius_mm
    assert thin.sigma_f_mpa / thick.sigma_f_mpa == pytest.approx(
        (10.0 / 2.0) ** (1.0 / WEIBULL_M), rel=1e-9)


def test_higher_porosity_gives_a_weaker_body_and_a_larger_mirror_zone() -> None:
    coarse = params_for("M01")          # 粗陶: pore_amount 0.45
    porcelain = params_for("M04")       # 白瓷: pore_amount 0.03
    assert coarse.porosity > porcelain.porosity
    assert coarse.sigma_f_mpa < porcelain.sigma_f_mpa
    assert coarse.mirror_radius_mm > porcelain.mirror_radius_mm


def test_strength_follows_the_rys_kewitch_relation() -> None:
    coarse = params_for("M01")
    expected = (SIGMA_REF_MPA * np.exp(-RYSKEWITCH_B * coarse.porosity)
                * (WALL_REF_MM / coarse.wall["p05_mm"]) ** (1.0 / WEIBULL_M))
    assert coarse.sigma_f_mpa == pytest.approx(float(expected), rel=1e-9)


# ---------------------------------------------------------------------------- hackle / relief


def test_hackle_count_follows_the_grain_size_and_the_mirror_radius() -> None:
    coarse = params_for("M01")
    fine = params_for("M04")
    for params in (coarse, fine):
        expected = int(np.clip(round(2.0 * np.pi * params.mirror_radius_mm
                                     / (2.0 * params.material["grain_scale_mm"])), 3, 48))
        assert params.hackle_count == expected
        assert params.hackle_spacing_at_mirror_mm == pytest.approx(
            2.0 * np.pi * params.mirror_radius_mm / params.hackle_count, rel=1e-9)
    # a coarse body nucleates fewer, wider-spaced hackle lines than a fine one
    assert coarse.hackle_spacing_at_mirror_mm > fine.hackle_spacing_at_mirror_mm


def test_roughness_relief_is_driven_by_grain_size_and_porosity() -> None:
    coarse = params_for("M01")
    porcelain = params_for("M04")
    grain_c = coarse.material["grain_scale_mm"]
    expected = GRAIN_RELIEF_FRACTION * grain_c * (1.0 + POROSITY_RELIEF_GAIN * coarse.porosity)
    assert coarse.requested_rms_mm == pytest.approx(expected, rel=1e-9)
    assert coarse.requested_rms_mm > porcelain.requested_rms_mm


def test_roughness_spectrum_realises_the_requested_rms_and_the_correlation_length() -> None:
    params = params_for("M01")
    amplitudes = np.array([b[0] for b in params.bands], dtype=np.float64)
    wavelengths = np.array([b[1] for b in params.bands], dtype=np.float64)
    realised = float(np.sqrt(np.sum(0.5 * amplitudes ** 2)))
    assert realised == pytest.approx(params.requested_rms_mm, rel=1e-6)
    # the spectrum is centred on the material's own correlation length
    assert float(np.median(wavelengths)) == pytest.approx(
        params.correlation_length_mm, rel=0.35)
    # self-affine decay: longer wavelength carries a larger amplitude
    order = np.argsort(wavelengths)
    assert np.all(np.diff(amplitudes[order]) > 0.0)


def test_pit_density_follows_the_porosity_area_fraction() -> None:
    params = params_for("M01")
    expected = params.pit_area_fraction * params.core_area_mm2 / (
        np.pi * params.pit_radius_mm ** 2)
    assert params.pit_count == int(min(max(0, round(expected)), 4000))
    assert params.pit_depth_mm == pytest.approx(
        0.35 * params.pit_radius_mm, rel=1e-9)
    assert params.pit_area_fraction == pytest.approx(params.porosity, rel=1e-12)


def test_fibre_term_is_inactive_without_a_fibre_field_and_active_with_one() -> None:
    without = params_for("M01")
    assert without.fiber_amplitude_mm == 0.0
    assert any("fibre" in note for note in without.notes)
    with_fibre = params_for("M11")       # 木质: fiber_amount 0.8, period 5.5 mm
    assert with_fibre.material["fiber_amount"] > 0.0
    assert with_fibre.fiber_period_mm > 0.0
    assert with_fibre.fiber_amplitude_mm > 0.0
    assert not any("fibre field" in note for note in with_fibre.notes)


# ---------------------------------------------------------------------------- glaze


def test_glaze_profile_gets_a_strip_and_unglazed_one_does_not() -> None:
    unglazed = params_for("M02")
    glazed = params_for("M04")
    assert unglazed.glaze_thickness_mm == 0.0
    assert unglazed.glaze_strip_width_mm == 0.0
    assert unglazed.glaze_roughness_ratio == 1.0
    assert any("unglazed" in note for note in unglazed.notes)
    assert glazed.glaze_thickness_mm > 0.0
    assert glazed.glaze_strip_width_mm > glazed.glaze_thickness_mm
    assert glazed.glaze_roughness_ratio < 1.0


def test_glaze_modulation_damps_the_boundary_and_leaves_the_core_alone() -> None:
    from synlab.fracture.cut import BandWindow
    from synlab.fracture.morphology import glaze_modulation

    step = 0.25
    n = 81
    values = np.ones((n, n), dtype=np.float64)
    core = np.ones((n, n), dtype=bool)
    core[0, :] = core[-1, :] = core[:, 0] = core[:, -1] = False
    window = BandWindow(u0=0.0, v0=0.0, step_mm=step, values=values,
                        grad_u=np.zeros_like(values), grad_v=np.zeros_like(values),
                        lap=np.zeros_like(values), core=core, halo_mm=0.5, margin_mm=0.5)
    field = glaze_modulation(window, 1.0, 0.12)
    assert field is not None
    inside = field.value(np.array([10.0]), np.array([0.05]))[0]
    centre = field.value(np.array([10.0]), np.array([10.0]))[0]
    assert inside == pytest.approx(0.12, abs=0.02)
    assert centre == pytest.approx(1.0, abs=1e-9)
    assert glaze_modulation(window, 0.0, 0.12) is None
    assert glaze_modulation(window, 1.0, 1.0) is None


# ---------------------------------------------------------------------------- precision honesty


def test_precision_budget_is_reported_and_never_silently_dropped() -> None:
    params = params_for("M02")
    assert params.curvature_budget_per_mm > 0.0
    assert params.requested_curvature_per_mm > 0.0
    expected = PRECISION_SAFETY * params.max_cells * 8.0 * params.error_budget_mm / (
        params.core_area_mm2 + 0.7 * (params.window_area_mm2 - params.core_area_mm2))
    assert params.curvature_budget_per_mm == pytest.approx(float(expected), rel=1e-9)
    assert 0.0 < params.predicted_amplitude_scale <= 1.0
    if params.predicted_amplitude_scale < 1.0:
        assert any("interpolation budget" in note for note in params.notes)


def test_coarser_body_needs_a_smaller_relief_scale_than_a_finer_one() -> None:
    """Long wavelengths are cheap: the modelled amplitude scale is a real precision statement."""
    coarse = params_for("M01")
    fine = params_for("M04")
    assert coarse.requested_curvature_per_mm < fine.requested_curvature_per_mm
    assert coarse.predicted_amplitude_scale >= fine.predicted_amplitude_scale


def test_formulas_are_recorded_for_every_derived_number() -> None:
    params = params_for("M01")
    for key in ("sigma_f", "mirror_radius", "mist_radius", "hackle_count", "roughness_rms",
                "roughness_spectrum", "curvature_requested", "precision_budget", "pits",
                "glaze", "conchoidal"):
        assert key in params.formulas and params.formulas[key]
    record = params.as_dict()
    assert record["material_id"] == "M01"
    assert MORPHOLOGY_META_KEY not in record      # the key is applied by the caller, not the record
    assert record["bands"] and len(record["bands"][0]) == 5


# ---------------------------------------------------------------------------- geometry pieces


def test_scatter_pits_is_deterministic_and_inside_the_cross_section() -> None:
    tris = square_cross_section(20.0)
    first = scatter_pits(tris, (10.0, 10.0), 40, seed_material={"event": "E"})
    second = scatter_pits(tris, (10.0, 10.0), 40, seed_material={"event": "E"})
    assert first.shape == (40, 2)
    assert np.allclose(first, second)
    assert np.all(np.abs(first) <= 10.0 + 1e-9)
    # outside the mirror zone
    mirrored = scatter_pits(tris, (10.0, 10.0), 40, seed_material={"event": "E"},
                            min_radius_from_origin_mm=5.0)
    assert np.all(np.hypot(mirrored[:, 0] - 10.0, mirrored[:, 1] - 10.0) >= 5.0 - 1e-9)
    other = scatter_pits(tris, (10.0, 10.0), 40, seed_material={"event": "F"})
    assert not np.allclose(first, other)


def test_field_raw_matches_the_closed_form_sum() -> None:
    from synlab.fracture.cut import FourierBand

    params = params_for("M01")
    points = np.array([[-40.0, -40.0, 0.0], [40.0, 40.0, 0.0], [10.0, -30.0, 0.0]])
    basis = build_basis(points, np.array([0.0, 0.0, 1.0]))
    bands = [FourierBand(amplitude_mm=a, wavelength_mm=w,
                         direction=np.array([du, dv]), phase=phase)
             for (a, w, du, dv, phase) in params.bands]
    field = MorphologyHeightField(
        basis=basis, bands=bands, bend=[], mean_mm=0.0,
        target_rms_mm=params.requested_rms_mm,
        realized_rms_mm=0.0, wavelength_min_mm=1.0, max_slope=0.0,
        origin_uv=(0.0, 0.0), dome_radius_mm=params.dome_radius_mm,
        dome_amplitude_mm=params.dome_amplitude_mm, hackle_count=0,
        hackle_amplitude_mm=0.0, hackle_phase=0.0,
        mirror_radius_mm=params.mirror_radius_mm, mist_radius_mm=params.mist_radius_mm,
        rib_amplitude_mm=0.0, rib_spacing_mm=params.rib_spacing_at_mirror_mm,
    )
    u = np.array([-5.0, 3.0, 20.0])
    v = np.array([2.0, -7.0, 15.0])
    expected = (u ** 2 + v ** 2) / (2.0 * params.dome_radius_mm)
    for amplitude, wavelength, du, dv, phase in params.bands:
        expected = expected + amplitude * np.cos(
            2.0 * np.pi / wavelength * (du * u + dv * v) + phase)
    assert np.allclose(field.raw(u, v), expected, atol=1e-12)


def test_hackle_and_ribs_start_at_the_mirror_boundary() -> None:
    params = params_for("M01")
    points = np.array([[-40.0, -40.0, 0.0], [40.0, 40.0, 0.0], [10.0, -30.0, 0.0]])
    basis = build_basis(points, np.array([0.0, 0.0, 1.0]))
    field = MorphologyHeightField(
        basis=basis, bands=[], bend=[], mean_mm=0.0, target_rms_mm=0.0, realized_rms_mm=0.0,
        wavelength_min_mm=1.0, max_slope=0.0, origin_uv=(0.0, 0.0), dome_radius_mm=0.0,
        hackle_count=params.hackle_count, hackle_amplitude_mm=params.hackle_amplitude_mm,
        hackle_phase=0.3, mirror_radius_mm=params.mirror_radius_mm,
        mist_radius_mm=params.mist_radius_mm, rib_amplitude_mm=params.rib_amplitude_mm,
        rib_spacing_mm=params.rib_spacing_at_mirror_mm,
    )
    # inside the mirror zone both radial components are exactly zero
    r_in = 0.5 * params.mirror_radius_mm
    assert field.hackle(np.array([r_in]), np.array([0.0]))[0] == 0.0
    assert field.ribs(np.array([r_in]), np.array([0.0]))[0] == 0.0
    # beyond the mist boundary the hackle is a real radial modulation: the same radius at two
    # angles gives different heights, which is the defining property of radiating ridge lines
    r_out = 2.0 * params.mist_radius_mm
    angles = np.linspace(0.0, 2.0 * np.pi, 360, endpoint=False)
    ring = field.hackle(r_out * np.cos(angles), r_out * np.sin(angles))
    assert float(np.ptp(ring)) > 0.2 * params.hackle_amplitude_mm
    # the number of crests on the ring is the hackle line count
    crests = int(np.sum((ring[1:-1] > ring[:-2]) & (ring[1:-1] >= ring[2:])))
    assert crests == params.hackle_count


def test_apply_scale_keeps_the_spectrum_and_scales_the_amplitudes() -> None:
    params = params_for("M01")
    halved = _scale_params(params, 0.5)
    assert [b[1] for b in halved.bands] == [b[1] for b in params.bands]     # wavelengths kept
    assert [b[2:] for b in halved.bands] == [b[2:] for b in params.bands]  # directions/phases kept
    for before, after in zip(params.bands, halved.bands):
        assert after[0] == pytest.approx(0.5 * before[0], rel=1e-12)
    assert halved.hackle_amplitude_mm == pytest.approx(0.5 * params.hackle_amplitude_mm)
    assert halved.pit_depth_mm == pytest.approx(0.5 * params.pit_depth_mm)
    assert halved.requested_rms_mm == params.requested_rms_mm       # the request is unchanged
    assert halved.precision_amplitude_scale == 0.5
    assert halved.correlation_length_mm == params.correlation_length_mm


def test_form_removal_removes_a_tilt_and_leaves_the_roughness() -> None:
    """The delivered ``Ra``/``Rz`` must be roughness, not the tilt of the cut plane."""
    from synlab.fracture.surface_features import amplitude_statistics

    rng = np.random.default_rng(3)
    u = rng.uniform(-10.0, 10.0, 20000)
    v = rng.uniform(-10.0, 10.0, 20000)
    tilt = 2.0 + 0.35 * u - 0.18 * v
    rough = 0.02 * np.sin(2.0 * np.pi * u / 1.0)
    out = detrend_plane(u, v, tilt + rough)
    # the fitted plane absorbs a small projection of the roughness on a finite sample
    assert float(np.max(np.abs(out["residual"] - rough))) < 0.1 * 0.02
    stats = amplitude_statistics(u, v, out["residual"], cell_mm=2.5)
    # a 0.02 mm sinusoid has Ra = 2 a / pi and Rq = a / sqrt(2)
    assert stats["Ra_mm"] == pytest.approx(2.0 * 0.02 / np.pi, rel=0.05)
    assert stats["Rq_mm"] == pytest.approx(0.02 / np.sqrt(2.0), rel=0.05)
    # a flat surface has no roughness at all
    flat = detrend_plane(u, v, tilt)
    assert amplitude_statistics(u, v, flat["residual"])["Ra_mm"] == pytest.approx(0.0, abs=1e-9)
