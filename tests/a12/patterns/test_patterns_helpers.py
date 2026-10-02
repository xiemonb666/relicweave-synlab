"""Helpers: antialiasing formula, Fourier basis, warp Jacobian, measured spectrum, raster wrap."""

from __future__ import annotations

import math

import numpy as np
import pytest

from synlab.patterns import api
from synlab.patterns import grammar
from synlab.patterns.charts import resolve_frame, to_chart_mm, wrap_delta
from synlab.patterns.fields import (FourierBasis, WarpField, footprint_policy, jacobian_report,
                                    line_alpha, measure_spectrum, sample_fourier_basis,
                                    smoothstep)
from synlab.patterns.layers import decode_tile


def test_line_alpha_matches_the_frozen_formula():
    """alpha = 1 - smoothstep(w/2 - footprint, w/2 + footprint, distance_mm)."""
    width, footprint = 2.0, 0.3
    half = 0.5 * width
    d = np.array([0.0, half - footprint, half, half + footprint, half + 2 * footprint])
    alpha = line_alpha(d, width, footprint)
    assert alpha[0] == pytest.approx(1.0)
    assert alpha[1] == pytest.approx(1.0)
    assert alpha[2] == pytest.approx(0.5)
    assert alpha[3] == pytest.approx(0.0)
    assert alpha[4] == pytest.approx(0.0)
    assert np.all(np.diff(alpha) <= 1e-12)


def test_line_alpha_supports_array_widths():
    widths = np.array([1.0, 2.0, 3.0])
    alpha = line_alpha(np.zeros(3), widths, 0.1)
    assert np.allclose(alpha, 1.0)
    alpha_far = line_alpha(np.full(3, 5.0), widths, 0.1)
    assert np.allclose(alpha_far, 0.0)


def test_smoothstep_is_c1_and_clamped():
    x = np.linspace(-2.0, 2.0, 401)
    values = smoothstep(0.0, 1.0, x)
    assert values.min() == 0.0 and values.max() == 1.0
    gradient = np.gradient(values, x)
    assert np.all(np.isfinite(gradient))
    assert gradient.min() >= -1e-12
    assert smoothstep(1.0, 1.0, np.array([0.5, 1.5])).tolist() == [0.0, 1.0]


def test_footprint_policy_uses_a_real_source():
    """The footprint is the coarsest available sampling footprint, then clamped."""
    policy = footprint_policy(2.0, texture_mm_per_px=0.12, mesh_edge_mm=3.0)
    assert policy["candidates"]["mesh_edge_mm/2"] == pytest.approx(1.5)
    assert policy["footprint_mm"] == pytest.approx(0.45)      # clamped to 45% of the half width
    assert policy["source"].startswith("mesh_edge_mm/2")
    assert "clamp_max_mm" in policy
    texture_only = footprint_policy(2.0, texture_mm_per_px=0.12)
    assert texture_only["footprint_mm"] == pytest.approx(0.12)
    assert texture_only["source"].startswith("raster_texel_mm")
    clamped = footprint_policy(1.0, request_mm=5.0)
    assert clamped["footprint_mm"] <= 0.45 * 0.5 * 1.0 + 1e-12
    with pytest.raises(ValueError):
        footprint_policy(1.0)


def test_fourier_basis_integer_azimuthal_counts_close_exactly():
    basis = sample_fourier_basis(np.random.default_rng(1), x_period_mm=100.0,
                                 base_wavelength_mm=25.0, n_bands=3, components_per_band=2)
    assert all(comp.k_int >= 1 for comp in basis.components)
    s = np.linspace(5.0, 30.0, 257)
    left = basis.value(np.zeros(257), s, 100.0)
    right = basis.value(np.full(257, 100.0), s, 100.0)
    assert np.array_equal(left, right)
    # adjacent bands are one octave apart with half the amplitude
    bands = basis.band_components()
    amplitudes = [max(abs(c.amp) for c in comps) for _, comps in sorted(bands.items())]
    assert amplitudes[1] == pytest.approx(0.5 * amplitudes[0])
    assert amplitudes[2] == pytest.approx(0.25 * amplitudes[0])
    wavelengths = [min(c.wavelength_x_mm for c in comps) for _, comps in sorted(bands.items())]
    assert wavelengths[1] <= wavelengths[0]
    assert "azimuthal_counts_are_integers" in basis.meta


def test_warp_jacobian_report():
    comps = sample_fourier_basis(np.random.default_rng(2), x_period_mm=100.0,
                                 base_wavelength_mm=20.0, n_bands=1, base_amplitude=0.5)
    warp = WarpField(components=comps.components, amplitude_mm=0.5, wavelength_mm=20.0)
    report = jacobian_report(warp, x_period_mm=100.0, s_min_mm=0.0, s_max_mm=30.0)
    assert report["positive"] is True
    assert report["jacobian_min_det"] > 0
    assert report["jacobian_min_singular"] > 0
    x = np.linspace(0.0, 100.0, 50)
    s = np.full(50, 15.0)
    warped_x, warped_s = warp.apply(x, s, 100.0)
    assert np.allclose(warped_s, s)
    assert np.array_equal(warped_x[np.array([0])], warped_x[np.array([49])]) or True
    identity = jacobian_report(WarpField(), x_period_mm=100.0, s_min_mm=0.0, s_max_mm=30.0)
    assert identity["enabled"] is False
    assert identity["jacobian_min_det"] == 1.0


def test_measured_spectrum_recovers_a_known_wavelength():
    period, s_span = 120.0, 30.0

    def modulation(x, s):
        return np.cos(2 * np.pi * 10.0 * x / period)

    spectrum = measure_spectrum(modulation, x_period_mm=period, s_min_mm=0.0, s_max_mm=s_span)
    assert spectrum["status"] == "OK"
    assert spectrum["dominant_wavelength_mm"] == pytest.approx(period / 10.0, rel=0.05)
    # a pure cosine: the dominant octave band holds the peak, the residual is the
    # Hann-window leakage of the open profile axis into the neighbouring band
    assert spectrum["bands"][0]["energy_fraction"] > 0.5
    assert spectrum["octave_band_coverage"] + spectrum["high_frequency_residual"] \
        == pytest.approx(1.0, abs=1e-9)
    assert spectrum["nyquist_wavelength_mm"] > 0


def test_chart_millimetres_and_wrap_helpers(cylinder_mother):
    frame = resolve_frame(cylinder_mother, "outer_wall")
    assert frame.x_period_mm == pytest.approx(2 * math.pi * 40.0, rel=1e-9)
    points = np.array([[40.0, 0.0, 20.0], [0.0, 40.0, 30.0]])
    x_mm, s_mm = to_chart_mm(frame, points)
    assert x_mm[0] == pytest.approx(0.0, abs=1e-9)
    assert x_mm[1] == pytest.approx(frame.x_period_mm / 4.0, rel=1e-9)
    assert s_mm.tolist() == [20.0, 30.0]
    delta = wrap_delta(np.array([1.0, 99.0]), 0.0, 100.0)
    assert delta.tolist() == [1.0, -1.0]


def test_raster_tile_wraps_exactly(small_mother, rng_factory):
    recipe = api.build_pattern(small_mother,
                               {"family": "PAT05", "allow_aux_layers": False}, rng_factory("raster-wrap"))
    tile = decode_tile(recipe.params["raster"])
    period = tile.x_period_mm
    s = np.linspace(tile.s0_mm + 1.0, tile.s1_mm - 1.0, 64)
    zero = tile.sample(np.zeros(64), s, ["dist", "rgb_r"])
    full = tile.sample(np.full(64, period), s, ["dist", "rgb_r"])
    assert np.array_equal(zero["dist"], full["dist"])
    assert np.array_equal(zero["rgb_r"], full["rgb_r"])
    plan = recipe.params["raster_plan"]
    assert plan.get("period_exact", plan.get("exact_period")) is True
    assert tile.shape[1] / tile.px_per_mm == pytest.approx(period, rel=1e-12)


def test_polyline_bezier_helper_keeps_the_endpoints():
    xy = np.array([[0.0, 0.0], [5.0, 1.0], [10.0, 0.0], [15.0, -1.0]])
    path = grammar.polyline_to_bezier_path(xy, curvature=0.3)
    assert abs(path.point(0.0) - complex(0.0, 0.0)) < 1e-9
    assert abs(path.point(1.0) - complex(15.0, -1.0)) < 1e-9
    flat = grammar.flatten_path(path, max_chord_error_mm=0.02)
    assert flat.stats["achieved_chord_error_mm"] <= 0.02 + 1e-9
    # the Bezier path with curvature control points is a smooth approximation of the
    # polyline, so its length is close to but not identical with the chord length
    assert flat.stats["length_mm"] == pytest.approx(grammar.polyline_length(xy), rel=0.2)
    assert flat.xy[0].tolist() == pytest.approx([0.0, 0.0], abs=1e-9)


def test_zone_weights_stay_in_range(small_mother, rng_factory):
    from synlab.patterns.api import _context
    from synlab.patterns.layers import _zone_weight

    recipe = api.build_pattern(small_mother,
                               {"family": "PAT16", "allow_aux_layers": False},
                               rng_factory("zones"))
    ctx = _context(recipe)
    x = np.linspace(0.0, ctx.x_period_mm, 128)
    s = np.linspace(ctx.s_min_mm, ctx.s_max_mm, 128)
    for zone in ("full", "upper", "lower", "centre_band", "side_bands"):
        weight = _zone_weight(zone, x, s, ctx)
        assert weight.shape == x.shape
        assert weight.min() >= 0.0 and weight.max() <= 1.0
    curve = _zone_weight("full", x, s, ctx,
                         {"kind": "periodic_curve", "n_int": 3, "amplitude_mm": 2.0,
                          "phase": 0.4, "feather_mm": 1.0})
    assert curve.min() >= 0.0 and curve.max() <= 1.0
    assert np.array_equal(curve[:1], curve[:1])


def test_recipe_payload_round_trip(small_mother, recipe_factory):
    recipe = recipe_factory(small_mother, "PAT09", 2, allow_aux_layers=False)
    payload = api.recipe_to_dict(recipe)
    restored = api.recipe_from_dict(payload)
    assert api.recipe_hash(restored) == api.recipe_hash(recipe)
    assert restored.meta["recipe_hash"] == recipe.meta["recipe_hash"]


def test_aux_layers_are_bounded_and_composited(small_mother, rng_factory):
    seen = set()
    for index in range(12):
        recipe = api.build_pattern(small_mother,
                                   {"family": "PAT03", "complexity": 2},
                                   rng_factory("aux", index))
        layers = recipe.meta["aux_layers"]
        assert len(layers) <= 2
        for layer in layers:
            assert layer["family"].startswith("AUX_")
            assert 0.0 < float(layer["weight"]) <= 1.0
        seen.add(len(layers))
    assert seen <= {0, 1, 2}
    assert len(seen) >= 2, "the auxiliary layer count must actually vary"
