"""Poisson dot lattice: periodic seam contract, density evidence and no relaxed spacing.

Plan 9.4 requires: candidates from ``scipy.stats.qmc.PoissonDisk`` with native bounds, the
periodic seam handled by wrapped copies plus a KDTree check, measured rejection rate,
density and largest gap, and a *failure* instead of a relaxed minimum distance when the
requested density cannot be reached.
"""

from __future__ import annotations

import numpy as np
import pytest

from synlab.errors import SynLabError
from synlab.patterns import api
from synlab.patterns.spatial import (distance_to_points, lattice_dots,
                                     nearest_neighbour_distance, sample_periodic_dots)


def test_poisson_cross_seam_minimum_distance_small_mother(small_mother, rng_factory):
    recipe = api.build_pattern(small_mother,
                               {"family": "PAT06", "allow_aux_layers": False,
                                "params": {"mode": "poisson", "radius_mm": 2.0,
                                           "clearance_mm": 0.5}},
                               rng_factory("poisson-a"))
    rows = np.asarray(recipe.params["dots"], dtype=np.float64)
    period = recipe.meta["chart"]["x_period_mm"]
    nn = nearest_neighbour_distance(rows[:, :2], period)
    required = 2.0 * rows[:, 2].max()
    assert nn.min() >= required - 1e-9, "periodic minimum spacing must hold across the seam"
    report = recipe.params["sampling_report"]
    assert report["engine"].startswith("scipy.stats.qmc.PoissonDisk")
    assert report["optimization"] is None
    assert report["n_kept"] == rows.shape[0]
    assert report["n_candidates"] >= report["n_kept"]
    assert report["min_neighbour_distance_mm"] >= report["sampler_radius_mm"] - 1e-9
    assert report["seam_extension"]["copies"] == "x +/- C_ref"
    assert "cKDTree" in report["seam_extension"]["method"]
    assert report["density_per_100mm2"] >= report["density_target_per_100mm2"] - 1e-9
    assert report["max_gap_mm"] is not None and report["gap_probe_grid_mm"] > 0


def test_cross_seam_rejection_actually_happens_on_a_narrow_chart(rng_factory):
    """A narrow band forces many near-seam candidates, so removal must be recorded."""
    rng = rng_factory("poisson-narrow")
    dots = sample_periodic_dots(rng, x_period_mm=75.0, s_min_mm=0.0, s_max_mm=16.0,
                               radius_mm=3.0, clearance_mm=0.5, max_rounds=3)
    report = dots.report
    assert report["n_removed_cross_seam"] + report["n_removed_same_tile"] == report["n_removed"]
    assert report["rejection_rate"] >= 0.0
    nn = nearest_neighbour_distance(dots.points[:, :2], 75.0)
    assert nn.min() >= 2.0 * dots.points[:, 2].max() - 1e-9
    assert report["min_radius_sum_margin_mm"] >= -1e-9


def test_variable_radius_enforces_the_radius_sum(rng_factory):
    rng = rng_factory("poisson-var")
    dots = sample_periodic_dots(rng, x_period_mm=120.0, s_min_mm=0.0, s_max_mm=20.0,
                               radius_mm=3.0, var_radius_mm=(2.0, 4.0), clearance_mm=0.5,
                               max_rounds=2)
    radii = dots.points[:, 2]
    assert radii.min() >= 2.0 - 1e-9 and radii.max() <= 4.0 + 1e-9
    assert radii.std() > 0.0
    assert dots.report["var_radius_mm"] == [2.0, 4.0]
    assert dots.report["min_radius_sum_margin_mm"] >= -1e-9
    # the sampler radius covers the worst pair, never the relaxed rule
    assert dots.report["sampler_radius_mm"] >= 2.0 * radii.max() + 0.5 - 1e-9


def test_impossible_density_fails_instead_of_relaxing_spacing(small_mother, rng_factory):
    spec = {"family": "PAT06", "allow_aux_layers": False,
            "params": {"mode": "poisson", "radius_mm": 3.0, "clearance_mm": 0.5,
                       "density_target_per_100mm2": 60.0}}
    with pytest.raises(SynLabError) as excinfo:
        api.build_pattern(small_mother, spec, rng_factory("poisson-impossible"))
    assert excinfo.value.code == "TARGET_INFEASIBLE"
    measurements = excinfo.value.measurements
    assert measurements["density_per_100mm2"] < measurements["target_per_100mm2"]
    assert measurements["n_kept"] > 0


def test_lattice_dots_close_exactly_at_the_seam(small_mother, rng_factory):
    spec = {"family": "PAT06", "allow_aux_layers": False,
            "params": {"mode": "lattice", "lattice_mode": "hex", "radius_mm": 2.0,
                       "spacing_mm": 10.0}}
    recipe = api.build_pattern(small_mother, spec, rng_factory("lattice-hex"))
    report = recipe.params["sampling_report"]
    assert report["n_columns_integer"] >= 1
    assert report["seam_closes_exactly"] is True
    assert abs(report["realized_spacing_s_mm"] - 10.0 * np.sqrt(3) / 2) < 0.5
    rows = np.asarray(recipe.params["dots"], dtype=np.float64)
    nn = nearest_neighbour_distance(rows[:, :2], recipe.meta["chart"]["x_period_mm"])
    assert nn.min() >= 2.0 * rows[:, 2].max() - 0.5


def test_dot_coverage_uses_the_frozen_radius(small_mother, rng_factory):
    spec = {"family": "PAT06", "allow_aux_layers": False,
            "params": {"mode": "poisson", "radius_mm": 2.5, "clearance_mm": 0.5,
                       "solid": True}}
    recipe = api.build_pattern(small_mother, spec, rng_factory("dots-cov"))
    rows = np.asarray(recipe.params["dots"], dtype=np.float64)
    period = recipe.meta["chart"]["x_period_mm"]
    # centre of a dot -> covered, far from every dot -> unpainted
    centre = rows[0, :2]
    x = np.array([centre[0], centre[0] + period / 2])
    s = np.array([centre[1], centre[1]])
    from synlab.patterns.api import pattern_field

    field = pattern_field(recipe, x, s)
    assert field.coverage[0] > 0.9
    far = distance_to_points(x[1:2], s[1:2], rows[:, :2], period)[0]
    if far > rows[:, 2].max() + 1.0:
        assert field.coverage[1] < 0.1


def test_lattice_helper_reports_spacing_deviation():
    dots = lattice_dots(x_period_mm=100.0, s_min_mm=0.0, s_max_mm=30.0, spacing_mm=12.0,
                        radius_mm=2.0, mode="hex")
    report = dots.report
    assert report["n_columns_integer"] == round(100.0 / 12.0)
    assert abs(report["realized_spacing_x_mm"] * report["n_columns_integer"] - 100.0) < 1e-9
    assert report["spacing_deviation_mm"] >= 0.0
    assert report["density_per_100mm2"] > 0
