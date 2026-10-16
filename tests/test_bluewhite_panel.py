from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from synlab.integrations.reference_generator import load_reference_mother
from synlab.mothers.tagging import TAG_INDEX
from synlab.patterns.bluewhite_panel import (
    GRID_BILINEAR_SAMPLING,
    NORMALIZED_DENSITY_HASH_SCHEMA,
    SOURCE_RESOLVED_STATIONARY_SAMPLING,
    build_bluewhite_panel,
    normalized_density_sha256,
)


REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent
REFERENCE_ASSET = (
    WORKSPACE / "vesselforge" / "experiments" / "continuation_20261015"
    / "reference_forms" / "outputs" / "daily_aberdeen_108x53_v6_final"
)
MASK_PATH = (
    REPO / "synlab" / "patterns" / "resources" / "bluewhite_20261015"
    / "derived" / "met_50899_O2_dragon_cobalt_fired_photo_mask.png"
)


@pytest.fixture(scope="module")
def actual_outer_profile() -> np.ndarray:
    mother = load_reference_mother(REFERENCE_ASSET)
    chart = mother.chart_for_tag(TAG_INDEX["outer_wall"])
    profile = np.asarray(chart.meta["arrays"]["profile_rzs"], dtype=np.float64)
    assert profile.shape == (641, 3)
    assert np.all(profile[:, 0] > 0.0)
    return profile


@pytest.fixture(scope="module")
def sourced_mask() -> tuple[np.ndarray, dict[str, str]]:
    with Image.open(MASK_PATH) as image:
        full = image.convert("L")
        # Keep the real continuous chroma pattern while reducing test-only source-array
        # memory. The experiment uses the full 2000 x 1160 mask.
        small = full.resize((160, 93), Image.Resampling.BILINEAR)
        density = np.asarray(small, dtype=np.float64) / 255.0
    metadata = {
        "source_id": "met-50899-o2-dragon-continuous-cobalt-chroma",
        "title": "Vase with dragon, O2 already-fired photograph crop",
        "source_url": "https://www.metmuseum.org/art/collection/search/50899",
        "source_mask_path": str(MASK_PATH.relative_to(WORKSPACE)),
        "source_mask_sha256": hashlib.sha256(MASK_PATH.read_bytes()).hexdigest(),
        "normalized_density_sha256": normalized_density_sha256(density),
        "mask_semantics": "continuous blue-excess chroma proxy from fired photograph; tonal values retained",
        "photo_state": "already_fired_photo",
    }
    return density, metadata


def _build(profile, sourced_mask, *, n_s=72, n_theta=128, **overrides):
    density, metadata = sourced_mask
    s_length = np.linalg.norm(np.diff(profile[:, :2], axis=0), axis=1).sum()
    controls = {
        "panel_width_mm": 45.0,
        "panel_height_mm": 26.0,
        "center_s_mm": float(s_length / 2.0),
        "center_theta_rad": np.pi,
        "diffusivity_s_mm2_per_unit": 0.02,
        "diffusivity_theta_mm2_per_unit": 0.08,
        "duration": 1.0,
        "mobile_fraction": 0.25,
        "n_s": n_s,
        "n_theta": n_theta,
    }
    controls.update(overrides)
    return build_bluewhite_panel(profile, density, source_metadata=metadata, **controls)


def test_normalized_density_digest_binds_schema_shape_and_input_dtype():
    matrix = np.arange(6, dtype=np.float64).reshape(2, 3) / 5.0
    reshaped = matrix.reshape(3, 2)
    as_float32 = matrix.astype(np.float32)
    assert normalized_density_sha256(matrix) != normalized_density_sha256(reshaped)
    assert normalized_density_sha256(matrix) != normalized_density_sha256(as_float32)
    assert NORMALIZED_DENSITY_HASH_SCHEMA.endswith(".v1")


def test_actual_variable_radius_surface_conserves_area_weighted_mass_and_keeps_halos(
        actual_outer_profile, sourced_mask):
    result = _build(actual_outer_profile, sourced_mask)
    area = result.cell_area_mm2[:, None]
    mass_initial = float(np.sum(area * result.initial_density))
    mass_final = float(np.sum(area * result.total_density))
    assert np.ptp(result.radius_mm) > 1.0
    assert mass_initial > 0.0
    assert abs(mass_final - mass_initial) / mass_initial < 2e-12
    assert result.receipt["mass"]["relative_final_total_drift"] < 2e-12
    assert result.operator.budget["cell_area_source"] == \
        "caller_supplied_profile_integrated_discrete_cell_measure"
    assert result.receipt["surface"]["s_origin_rz_mm"] == list(actual_outer_profile[0, :2])

    panel = result.receipt["panel"]
    assert panel["actual_s_halo_mm"][0] >= panel["boundary_halo_mm"]
    assert panel["actual_s_halo_mm"][1] >= panel["boundary_halo_mm"]
    s = result.s_centers_mm
    low, high = panel["s_bounds_mm"]
    assert np.all(result.initial_density[(s < low) | (s > high)] == 0.0)
    assert panel["tiling_or_repetition"] is False
    assert panel["periodic_seam_away_from_panel"] is True
    assert panel["piecewise_polyline_max_abs_shear_a_bound"] > 0.0
    assert panel["finite_width_guard"].startswith("panel_width_mm < 2*pi*")
    ds_profile = np.linalg.norm(np.diff(actual_outer_profile[:, :2], axis=0), axis=1)
    s_profile = np.r_[0.0, np.cumsum(ds_profile)]
    shear_bound = 0.0
    low, high = panel["s_bounds_mm"]
    for i, (s0, s1) in enumerate(zip(s_profile[:-1], s_profile[1:])):
        left, right = max(s0, low), min(s1, high)
        if right < left:
            continue
        slope = ((actual_outer_profile[i + 1, 0] - actual_outer_profile[i, 0])
                 / (s1 - s0))
        r_left = actual_outer_profile[i, 0] + slope * (left - s0)
        r_right = actual_outer_profile[i, 0] + slope * (right - s0)
        shear_bound = max(shear_bound,
                          0.5 * panel["width_mm"] * abs(slope) / min(r_left, r_right))
    assert panel["piecewise_polyline_max_abs_shear_a_bound"] == pytest.approx(
        shear_bound, rel=1e-13)


def test_panel_is_one_partial_source_projection_and_periodic_sampling_is_seam_safe(
        actual_outer_profile, sourced_mask):
    result = _build(actual_outer_profile, sourced_mask)
    center_s = result.receipt["panel"]["center_s_mm"]
    center_theta = result.receipt["panel"]["center_theta_rad"]
    seam = result.sample_density(center_s, np.array([0.0, 2.0 * np.pi]))
    np.testing.assert_allclose(seam[0], seam[1], rtol=0.0, atol=1e-14)
    assert result.sample_density(center_s, center_theta) > 0.0
    assert result.sample_density(center_s, center_theta + np.pi) == 0.0
    # The deliberately remote periodic seam remains blank in the initial projected
    # panel. This detects accidental full-image tiling before any spread is applied.
    assert result.initial_density[:, [0, -1]].max() == 0.0
    assert result.receipt["source"]["source_density_contains_tonal_variation"] is True
    assert result.receipt["interpretation_limits"]["recovered_prefire_pigment"] is False
    assert result.receipt["interpretation_limits"]["synthetic_new_design_on_bowl_candidate"] is True


def test_density_hash_binding_reproducibility_and_bound_mobile_split(actual_outer_profile,
                                                                      sourced_mask):
    first = _build(actual_outer_profile, sourced_mask, n_s=48, n_theta=96)
    replay = _build(actual_outer_profile, sourced_mask, n_s=48, n_theta=96)
    np.testing.assert_array_equal(first.initial_density, replay.initial_density)
    np.testing.assert_array_equal(first.total_density, replay.total_density)
    np.testing.assert_array_equal(first.linear_rgb, replay.linear_rgb)
    np.testing.assert_allclose(first.bound_density, 0.75 * first.initial_density,
                               rtol=0.0, atol=0.0)
    assert np.any(first.mobile_density > 0.0)
    assert np.any(first.mobile_density[first.initial_density == 0.0] > 0.0)

    density, metadata = sourced_mask
    assert metadata["source_mask_sha256"] == hashlib.sha256(MASK_PATH.read_bytes()).hexdigest()
    assert metadata["normalized_density_sha256"] == normalized_density_sha256(density)
    float32_density = density.astype(np.float32)
    float32_metadata = {
        **metadata,
        "normalized_density_sha256": normalized_density_sha256(float32_density),
    }
    float32_result = _build(actual_outer_profile,
                            (float32_density, float32_metadata),
                            n_s=48, n_theta=96)
    assert float32_result.receipt["source"]["normalized_density_hash_input_dtype"] == "<f4"
    assert float32_result.receipt["source"]["normalized_density_hash_binds_shape_and_dtype"]
    wrong_density = density.copy()
    wrong_density[0, 0] = 1.0 - wrong_density[0, 0]
    with pytest.raises(ValueError, match="does not match the supplied source field"):
        build_bluewhite_panel(
            actual_outer_profile, wrong_density, source_metadata=metadata,
            panel_width_mm=45.0, panel_height_mm=26.0,
            center_s_mm=float(np.linalg.norm(np.diff(actual_outer_profile[:, :2], axis=0), axis=1).sum() / 2),
            center_theta_rad=np.pi, diffusivity_s_mm2_per_unit=0.02,
            diffusivity_theta_mm2_per_unit=0.08, duration=1.0,
            mobile_fraction=0.25, n_s=48, n_theta=96,
        )


def test_source_resolved_stationary_sampling_retains_detail_and_matches_grid_centers(
        actual_outer_profile):
    # A narrow asymmetric source line falls between the legacy bowl-grid centers. The
    # opt-in route must preserve its sampled source value instead of diffusing its bound
    # fraction through a downsampled raster.
    source = np.zeros((64, 64), dtype=np.float32)
    source[:, 28:36] = 0.02  # broad support keeps the FV grid nonempty
    source[:, 32] = 1.0
    source_hash = normalized_density_sha256(source)
    metadata = {
        "source_id": "synthetic-sharp-line-validation",
        "title": "Synthetic sharp line validation field",
        "source_url": "https://example.invalid/field",
        "source_mask_path": "tests/fixture/sharp-line",
        "source_mask_sha256": "a" * 64,
        "normalized_density_sha256": source_hash,
        "mask_semantics": "synthetic test field",
        "photo_state": "already_fired_photo",
    }
    length = np.linalg.norm(np.diff(actual_outer_profile[:, :2], axis=0), axis=1).sum()
    common = dict(
        source_metadata=metadata, panel_width_mm=45.0, panel_height_mm=26.0,
        center_s_mm=float(length / 2.0), center_theta_rad=np.pi,
        diffusivity_s_mm2_per_unit=0.02, diffusivity_theta_mm2_per_unit=0.08,
        duration=1.0, mobile_fraction=0.25, n_s=48, n_theta=64,
    )
    source_resolved = build_bluewhite_panel(
        actual_outer_profile, source, continuous_sampling_mode=SOURCE_RESOLVED_STATIONARY_SAMPLING,
        **common)
    legacy = build_bluewhite_panel(
        actual_outer_profile, source, continuous_sampling_mode=GRID_BILINEAR_SAMPLING,
        **common)

    radius_at_center = np.interp(source_resolved.center_s_mm,
                                 source_resolved.profile_s_mm,
                                 source_resolved.profile_radius_mm)
    source_pixel_x_mm = ((32.5 / source.shape[1]) - 0.5) * 45.0
    theta_at_line = np.pi + source_pixel_x_mm / radius_at_center
    query_s = source_resolved.center_s_mm
    direct_bound = source_resolved.sample_density(query_s, theta_at_line, component="bound")
    grid_bound = legacy.sample_density(query_s, theta_at_line, component="bound")
    assert direct_bound == pytest.approx(0.75, abs=1e-14)
    assert grid_bound < direct_bound * 0.2
    assert not source_resolved.source_density.flags.writeable
    with pytest.raises(ValueError, match="WRITEABLE"):
        source_resolved.source_density.setflags(write=True)
    assert source_resolved.source_density.dtype == np.dtype(np.float32)
    assert source_resolved.receipt["source"]["normalized_density_hash_input_dtype"] == "<f4"
    assert source_resolved.receipt["source"]["normalized_density_sha256"] == source_hash
    assert source_resolved.receipt["appearance_controls"]["continuous_sampling_mode"] == (
        SOURCE_RESOLVED_STATIONARY_SAMPLING)
    assert source_resolved.receipt["mass_accounting"]["scope"] == "DISCRETE_GRID_MASS_ONLY"
    assert source_resolved.receipt["mass_accounting"][
        "continuous_source_quadrature_equality_claimed"] is False
    assert source_resolved.receipt["mass_accounting"]["fine_grid_convergence_claimed"] is False

    s_grid, theta_grid = np.meshgrid(source_resolved.s_centers_mm,
                                     source_resolved.theta_centers_rad, indexing="ij")
    for component, recorded in (("initial", source_resolved.initial_density),
                                ("bound", source_resolved.bound_density),
                                ("mobile", source_resolved.mobile_density),
                                ("total", source_resolved.total_density)):
        sampled = source_resolved.sample_density(s_grid, theta_grid, component=component)
        np.testing.assert_allclose(sampled, recorded, rtol=0.0, atol=2e-15)

    # The finite source stays blank outside its band, including across the periodic seam.
    seam_s = query_s
    seam = source_resolved.sample_density(seam_s, np.array([0.0, 2.0 * np.pi]),
                                          component="bound")
    np.testing.assert_allclose(seam[0], seam[1], rtol=0.0, atol=1e-14)
    assert source_resolved.sample_density(seam_s, np.pi + np.pi / 2.0,
                                          component="bound") == 0.0


@pytest.mark.parametrize("zero_control", [
    {"duration": 0.0},
    {"diffusivity_s_mm2_per_unit": 0.0,
     "diffusivity_theta_mm2_per_unit": 0.0},
    {"mobile_fraction": 0.0},
])
def test_source_resolved_no_transport_preserves_exact_source_at_arbitrary_queries(
        actual_outer_profile, sourced_mask, zero_control):
    density, metadata = sourced_mask
    source_resolved = _build(
        actual_outer_profile, (density, metadata), n_s=48, n_theta=64,
        continuous_sampling_mode=SOURCE_RESOLVED_STATIONARY_SAMPLING,
        **zero_control)
    s_query = source_resolved.receipt["panel"]["center_s_mm"] + np.array([-0.7, 0.0, 0.9])
    theta_query = np.array([
        source_resolved.center_theta_rad - 0.02,
        source_resolved.center_theta_rad,
        source_resolved.center_theta_rad + 0.03,
    ])
    expected = source_resolved.sample_density(s_query, theta_query, component="initial")
    actual = source_resolved.sample_density(s_query, theta_query, component="total")
    np.testing.assert_array_equal(actual, expected)
    assert source_resolved.mobile_transport_is_zero is True


@pytest.mark.parametrize("overrides,match", [
    ({"panel_width_mm": 10_000.0}, "2\\*pi\\*minimum panel radius"),
    ({"center_s_mm": 1.0}, "outside the outer-meridian band or its blank halo"),
    ({"n_s": 512, "n_theta": 512}, "grid has 262,144 cells"),
])
def test_unwrapped_width_band_and_grid_resource_guards(actual_outer_profile, sourced_mask,
                                                       overrides, match):
    with pytest.raises(ValueError, match=match):
        _build(actual_outer_profile, sourced_mask, **overrides)

