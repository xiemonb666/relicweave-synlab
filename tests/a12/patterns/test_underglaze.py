from __future__ import annotations

import numpy as np
import pytest

import synlab.patterns.underglaze as underglaze
from synlab.patterns.underglaze import (
    blue_white_appearance,
    build_surface_of_revolution_operator,
    diffuse_pigment,
    diffuse_two_fraction_appearance,
    sample_periodic_field,
)


def cylinder_operator(*, radius=12.0, n_s=8, n_theta=32, ds=0.7,
                      d_s=0.12, d_theta=0.35, **kwargs):
    s = (np.arange(n_s, dtype=np.float64) + 0.5) * ds
    r = np.full(n_s, radius, dtype=np.float64)
    return build_surface_of_revolution_operator(
        s, r, n_theta,
        diffusivity_s_mm2_per_unit=d_s,
        diffusivity_theta_mm2_per_unit=d_theta,
        **kwargs,
    )


def test_constant_field_is_steady_and_weighted_mass_is_conserved():
    op = cylinder_operator()
    c0 = np.full(op.shape, 0.37)
    result = diffuse_pigment(op, c0, duration=2.5)

    np.testing.assert_allclose(result.concentration, c0, rtol=2e-13, atol=2e-14)
    assert result.receipt["mass"]["relative_solver_drift"] < 1e-12
    assert result.receipt["grid"]["first_band_excludes_pole"] is True
    assert result.receipt["operator"]["stiffness_max_abs_row_sum"] < 1e-12


def test_metric_operator_is_symmetric_conservative_and_nonpositive():
    op = cylinder_operator(radius=7.0, n_s=9, n_theta=20,
                           d_s=np.linspace(0.03, 0.4, 9),
                           d_theta=np.linspace(0.08, 0.7, 9))
    stiffness_delta = op.stiffness - op.stiffness.T
    generator_delta = op.generator - op.generator.T
    assert stiffness_delta.nnz == 0 or np.max(np.abs(stiffness_delta.data)) < 1e-14
    assert generator_delta.nnz == 0 or np.max(np.abs(generator_delta.data)) < 1e-14
    assert np.max(np.abs(np.asarray(op.stiffness.sum(axis=1)).ravel())) < 1e-12
    assert np.all(op.stiffness.diagonal() < 0.0)
    coo = op.stiffness.tocoo()
    assert np.all(coo.data[coo.row != coo.col] > 0.0)
    # For a random vector, x.T L x is a sum of non-positive edge energies.
    rng = np.random.default_rng(741)
    x = rng.normal(size=op.n_cells)
    assert float(x @ (op.stiffness @ x)) <= 1e-10


def test_cylinder_angular_fourier_mode_has_discrete_eigenvalue_decay():
    radius, n_theta, k, duration = 9.0, 40, 3, 1.7
    d_theta = 0.21
    op = cylinder_operator(radius=radius, n_s=7, n_theta=n_theta,
                           d_s=0.0, d_theta=d_theta)
    theta = (np.arange(n_theta) + 0.5) * op.dtheta_rad
    mode = np.cos(k * theta)
    c0 = np.broadcast_to((0.5 + 0.3 * mode)[None, :], op.shape).copy()
    result = diffuse_pigment(op, c0, duration=duration)

    eigenvalue_abs = (4.0 * d_theta * np.sin(np.pi * k / n_theta) ** 2
                      / (radius ** 2 * op.dtheta_rad ** 2))
    expected = 0.5 + 0.3 * mode[None, :] * np.exp(-duration * eigenvalue_abs)
    expected = np.broadcast_to(expected, op.shape)
    np.testing.assert_allclose(result.concentration, expected, rtol=2e-12, atol=2e-13)


def test_periodic_seam_roll_equivariance_and_seam_crossing_interpolation():
    n_theta = 36
    op = cylinder_operator(n_theta=n_theta, n_s=6, d_s=0.0)
    theta = (np.arange(n_theta) + 0.5) * op.dtheta_rad
    c0 = np.broadcast_to((0.5 + 0.4 * np.cos(3 * theta))[None, :], op.shape).copy()
    base = diffuse_pigment(op, c0, duration=1.2).concentration
    roll = 7
    shifted = diffuse_pigment(op, np.roll(c0, roll, axis=1), duration=1.2).concentration
    np.testing.assert_allclose(shifted, np.roll(base, roll, axis=1), rtol=0.0, atol=3e-14)

    seam_samples = sample_periodic_field(
        base, op.s_centers_mm, n_theta,
        np.full(2, op.s_centers_mm[2]),
        np.array([-1e-8, 2.0 * np.pi - 1e-8]),
    )
    np.testing.assert_allclose(seam_samples[0], seam_samples[1], atol=1e-14)
    assert base[:, 0].max() > 0.0
    assert base[:, -1].max() > 0.0


def test_seam_seed_spreads_across_periodic_boundary_into_blank_cells():
    op = cylinder_operator(n_s=5, n_theta=32, d_s=0.0, d_theta=0.2)
    c0 = np.zeros(op.shape)
    c0[:, [0, -1]] = 1.0
    spread = diffuse_pigment(op, c0, duration=0.8).concentration
    assert np.all(spread >= 0.0)
    assert np.all(spread[:, 1] > 0.0)
    assert np.all(spread[:, -2] > 0.0)
    assert np.all(spread[:, 2] > 0.0)
    assert spread[:, 1].mean() > spread[:, 2].mean()


def test_fixed_operator_obeys_semigroup_and_replays_deterministically():
    op = cylinder_operator(n_s=10, n_theta=28,
                           d_s=np.linspace(0.02, 0.18, 10),
                           d_theta=np.linspace(0.06, 0.31, 10))
    rng = np.random.default_rng(20261015)
    c0 = rng.random(op.shape)
    full_a = diffuse_pigment(op, c0, duration=2.4).concentration
    half = diffuse_pigment(op, c0, duration=1.2).concentration
    full_b = diffuse_pigment(op, half, duration=1.2).concentration
    replay = diffuse_pigment(op, c0, duration=2.4).concentration
    np.testing.assert_allclose(full_a, full_b, rtol=3e-11, atol=3e-12)
    np.testing.assert_array_equal(full_a, replay)


def test_length_unit_rescaling_preserves_dimensionless_diffusion():
    op_mm = cylinder_operator(radius=5.0, n_s=8, n_theta=24, ds=0.8,
                              d_s=0.09, d_theta=0.24)
    scale = 1000.0
    s_micromm = op_mm.s_centers_mm * scale
    radius_micromm = op_mm.radius_mm * scale
    op_scaled = build_surface_of_revolution_operator(
        s_micromm, radius_micromm, op_mm.n_theta,
        diffusivity_s_mm2_per_unit=op_mm.diffusivity_s_mm2_per_unit * scale ** 2,
        diffusivity_theta_mm2_per_unit=op_mm.diffusivity_theta_mm2_per_unit * scale ** 2,
    )
    rng = np.random.default_rng(5)
    c0 = rng.random(op_mm.shape)
    c_mm = diffuse_pigment(op_mm, c0, duration=0.7).concentration
    c_scaled = diffuse_pigment(op_scaled, c0, duration=0.7).concentration
    np.testing.assert_allclose(c_scaled, c_mm, rtol=3e-12, atol=3e-13)


def test_radius_controls_angular_spread_and_exact_area_is_reported():
    n_theta = 48
    theta = (np.arange(n_theta) + 0.5) * (2.0 * np.pi / n_theta)
    c0 = np.broadcast_to((0.5 + 0.45 * np.cos(5 * theta))[None, :], (6, n_theta)).copy()
    narrow = cylinder_operator(radius=5.0, n_s=6, n_theta=n_theta, d_s=0.0,
                               d_theta=0.3)
    wide = cylinder_operator(radius=10.0, n_s=6, n_theta=n_theta, d_s=0.0,
                             d_theta=0.3)
    cn = diffuse_pigment(narrow, c0, duration=1.0).concentration
    cw = diffuse_pigment(wide, c0, duration=1.0).concentration
    amplitude_n = float(np.ptp(cn[0]))
    amplitude_w = float(np.ptp(cw[0]))
    assert amplitude_w > amplitude_n

    exact_areas = np.full(8, 1.234)
    op_exact = cylinder_operator(cell_area_mm2=exact_areas)
    assert op_exact.budget["cell_area_source"] == \
        "caller_supplied_profile_integrated_discrete_cell_measure"
    result = diffuse_pigment(op_exact, np.random.default_rng(3).random(op_exact.shape),
                             duration=0.8)
    assert result.receipt["mass"]["relative_solver_drift"] < 2e-12


def test_zero_exposure_and_inputs_are_validated():
    op = cylinder_operator(n_s=4, n_theta=12)
    rng = np.random.default_rng(44)
    c0 = rng.random(op.shape)
    np.testing.assert_array_equal(diffuse_pigment(op, c0, duration=0.0).concentration, c0)
    with pytest.raises(ValueError, match="uniformly spaced"):
        build_surface_of_revolution_operator(
            np.array([0.5, 1.5, 3.0]), np.array([2.0, 2.1, 2.2]), 8,
            diffusivity_s_mm2_per_unit=0.1,
            diffusivity_theta_mm2_per_unit=0.2,
        )
    with pytest.raises(ValueError, match="strictly positive"):
        build_surface_of_revolution_operator(
            np.array([0.5, 1.5]), np.array([0.0, 2.0]), 8,
            diffusivity_s_mm2_per_unit=0.1,
            diffusivity_theta_mm2_per_unit=0.2,
        )
    with pytest.raises(ValueError, match="non-negative"):
        diffuse_pigment(op, -np.ones(op.shape), duration=1.0)
    with pytest.raises(ValueError, match="non-negative"):
        build_surface_of_revolution_operator(
            np.array([0.5, 1.5]), np.array([2.0, 2.0]), 8,
            diffusivity_s_mm2_per_unit=-1.0,
            diffusivity_theta_mm2_per_unit=0.2,
        )


def test_only_roundoff_sized_negative_values_are_clipped_and_measured(monkeypatch):
    op = cylinder_operator(n_s=4, n_theta=12)
    target = np.full(op.shape, 0.1)
    target[0, 0] = -1e-16
    sqrt_area = np.sqrt(np.broadcast_to(op.cell_area_mm2, op.shape)).ravel()

    def return_target(_matrix, _u0, *, traceA):
        del traceA
        return sqrt_area * target.ravel()

    monkeypatch.setattr(underglaze, "expm_multiply", return_target)
    result = diffuse_pigment(op, np.full(op.shape, 0.1), duration=1.0)
    assert result.concentration[0, 0] == 0.0
    assert result.receipt["roundoff"]["negative_cell_count"] == 1
    assert result.receipt["mass"]["roundoff_clip_added_mass"] > 0.0

    target[0, 0] = -1e-8
    with pytest.raises(FloatingPointError, match="roundoff clipping tolerance"):
        diffuse_pigment(op, np.full(op.shape, 0.1), duration=1.0)


def test_preflight_rejects_oversize_before_building_sparse_arrays():
    s = np.arange(257_001, dtype=np.float64) + 0.5
    radius = np.full(s.shape, 2.0)
    with pytest.raises(ValueError, match="budget"):
        build_surface_of_revolution_operator(
            s, radius, 3,
            diffusivity_s_mm2_per_unit=0.1,
            diffusivity_theta_mm2_per_unit=0.2,
        )


def test_preflight_checks_operator_nnz_and_memory_budgets():
    s = np.array([0.5, 1.5])
    radius = np.array([2.0, 2.0])
    base = dict(diffusivity_s_mm2_per_unit=0.1,
                diffusivity_theta_mm2_per_unit=0.2)
    with pytest.raises(ValueError, match="structural entries"):
        build_surface_of_revolution_operator(
            s, radius, 10, max_operator_nnz=79, **base)
    with pytest.raises(ValueError, match="working set"):
        build_surface_of_revolution_operator(
            s, radius, 10, max_memory_bytes=1, **base)


def test_two_fraction_appearance_keeps_bound_core_and_conserves_weighted_mass():
    op = cylinder_operator(radius=8.0, n_s=8, n_theta=32, ds=0.4,
                           d_s=0.08, d_theta=0.24)
    initial = np.zeros(op.shape)
    initial[3, 10] = 1.0
    original = initial.copy()

    partial = diffuse_two_fraction_appearance(
        op, initial, duration=1.0, mobile_fraction=0.25)
    fully_mobile = diffuse_pigment(op, initial, duration=1.0).concentration

    np.testing.assert_array_equal(initial, original)
    np.testing.assert_array_equal(partial.bound_density, 0.75 * initial)
    assert partial.total_density[3, 10] > fully_mobile[3, 10]
    assert partial.total_density[3, 11] > 0.0
    assert partial.mobile_density[3, 11] > 0.0
    assert partial.receipt["mass"]["relative_final_total_drift"] < 1e-12
    assert partial.receipt["no_sharpening_or_renormalization"] is True
    assert partial.receipt["claims"]["measured_glaze_chemistry"] is False
    area = np.broadcast_to(op.cell_area_mm2, op.shape)
    np.testing.assert_allclose(
        np.sum(area * partial.total_density), np.sum(area * initial),
        rtol=1e-12, atol=1e-12)


def test_two_fraction_limits_match_zero_spread_and_existing_full_diffusion():
    op = cylinder_operator(n_s=6, n_theta=24, d_s=0.05, d_theta=0.2)
    initial = np.zeros(op.shape)
    initial[2:4, 5:8] = np.linspace(0.2, 1.0, 6).reshape(2, 3)
    original = initial.copy()

    bound_only = diffuse_two_fraction_appearance(
        op, initial, duration=2.0, mobile_fraction=0.0)
    fully_mobile = diffuse_two_fraction_appearance(
        op, initial, duration=2.0, mobile_fraction=1.0)
    legacy_full = diffuse_pigment(op, initial, duration=2.0)

    np.testing.assert_array_equal(bound_only.total_density, initial)
    np.testing.assert_array_equal(bound_only.bound_density, initial)
    np.testing.assert_array_equal(bound_only.mobile_density, np.zeros(op.shape))
    np.testing.assert_allclose(fully_mobile.total_density, legacy_full.concentration,
                               rtol=0.0, atol=0.0)
    np.testing.assert_array_equal(initial, original)


def test_exponential_work_budget_rejects_excessive_scaled_generator_norm():
    op = cylinder_operator(n_s=5, n_theta=20)
    initial = np.zeros(op.shape)
    initial[2, 4] = 1.0

    with pytest.raises(ValueError, match="infinity norm exceeds the resource budget"):
        diffuse_pigment(op, initial, duration=10_000.0)


def test_blue_white_map_is_linear_rgb_and_unambiguously_uncalibrated():
    rgb = blue_white_appearance(np.array([0.0, 0.2, 1.0]))
    assert rgb.shape == (3, 3)
    assert rgb[0, 0] > rgb[0, 1] > rgb[0, 2]
    assert rgb[-1, 0] < rgb[-1, 1] < rgb[-1, 2]
    assert np.all((rgb >= 0.0) & (rgb <= 1.0))
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        blue_white_appearance(np.array([1.1]))
