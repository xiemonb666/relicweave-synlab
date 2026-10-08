"""Seam audit: 1000 random u=0/1 pairs per family, value and first derivative.

The primary acceptance of plan 9.6 is the *value* continuity of the linear colour across
the periodic seam (budget 1e-5).  The derivative budget is measured as well and compared
with the same stencil applied in the chart interior, because frozen fields contain
legitimate kinks (Voronoi medial axes between dots, rasterised stroke edges, saturation
of a clipped channel, knots of a piecewise colour ramp).
"""

from __future__ import annotations

import numpy as np
import pytest

from synlab.patterns import api
from synlab.patterns.audit import SEAM_COLOR_TOL

FAMILIES = sorted(__import__("synlab.patterns.params", fromlist=["x"]).FAMILY_MODELS)


@pytest.mark.parametrize("family_id", FAMILIES)
def test_seam_1000_pairs(family_id, small_mother, recipe_factory):
    recipe = recipe_factory(small_mother, family_id, 1, allow_aux_layers=False)
    audit = api.audit_pattern(recipe, small_mother, n_pairs=1000, geometry_probe=False,
                              scale_samples=0)
    seam = audit["seam"]["chart_space"]
    assert seam["n_pairs"] == 1000
    assert seam["max_abs_color_error"] <= SEAM_COLOR_TOL, (
        f"{family_id}: seam colour error {seam['max_abs_color_error']} "
        f"above {SEAM_COLOR_TOL}")
    assert seam["pass"] is True
    assert seam["derivative_pass"] is True, (
        f"{family_id}: derivative mismatch {seam['max_deriv_mismatch_abs']} "
        f"(ratio {seam['max_deriv_mismatch_ratio']}) exceeds the interior reference "
        f"p99 {seam['interior_deriv_mismatch_p99']}")
    assert audit["seam"]["world_space"]["pass"] is True


def test_seam_values_are_bit_identical_when_the_field_is_pure_analytic(small_mother,
                                                                      recipe_factory):
    """Stripe/band families keep integer azimuthal counts, so the seam is exact."""
    for family_id in ("PAT02", "PAT03", "PAT04", "PAT09"):
        recipe = recipe_factory(small_mother, family_id, 1, allow_aux_layers=False)
        audit = api.audit_pattern(recipe, small_mother, n_pairs=1000, geometry_probe=False,
                                  scale_samples=0)
        # identical functional form on both sides: only float32 channel rounding remains
        assert audit["seam"]["chart_space"]["max_abs_color_error"] <= 1e-12
        # the albedo channel is float32, so the finite-difference noise floor of
        # (f(h) - f(2h))/h with h ~ 1.4 um is a few 1e-6 per mm
        assert audit["seam"]["chart_space"]["max_deriv_mismatch_abs"] <= 1e-4


def test_seam_report_contains_the_evidence_fields(small_mother, recipe_factory):
    recipe = recipe_factory(small_mother, "PAT05", 2, allow_aux_layers=False)
    audit = api.audit_pattern(recipe, small_mother, n_pairs=64, geometry_probe=False,
                              scale_samples=0)
    chart = audit["seam"]["chart_space"]
    for key in ("n_pairs", "x_values", "max_abs_color_error", "tolerance", "pass",
                "derivative_step_u", "max_deriv_mismatch_abs", "max_deriv_mismatch_ratio",
                "interior_deriv_mismatch_p99", "interior_n_pairs", "definition"):
        assert key in chart
    world = audit["seam"]["world_space"]
    assert world["status"] in ("OK", "NOT_RUN")
    if world["status"] == "OK":
        assert world["max_ratio_to_bound"] <= 1.05
        assert world["local_circumference_mm"][0] > 0


def test_warp_keeps_the_seam_and_a_positive_jacobian(small_mother, rng_factory):
    spec = {"family": "PAT03", "complexity": 2, "allow_aux_layers": False,
            "warp": {"enabled": True, "amplitude_mm": 0.8, "wavelength_mm": 12.0,
                     "components": 2}}
    recipe = api.build_pattern(small_mother, spec, rng_factory("warp-seam"))
    report = recipe.meta["warp"]["report"]
    assert report["positive"] is True
    assert report["jacobian_min_singular"] > 0.0
    assert recipe.meta["warp"]["enabled"] is True
    audit = api.audit_pattern(recipe, small_mother, n_pairs=1000, geometry_probe=False,
                              scale_samples=0)
    assert audit["seam"]["chart_space"]["max_abs_color_error"] <= SEAM_COLOR_TOL
    assert audit["seam"]["chart_space"]["derivative_pass"] is True


def test_oversized_warp_is_rejected_not_silently_kept(small_mother, rng_factory):
    spec = {"family": "PAT03", "allow_aux_layers": False,
            "warp": {"enabled": True, "amplitude_mm": 6.0, "wavelength_mm": 6.0,
                     "components": 1}}
    recipe = api.build_pattern(small_mother, spec, rng_factory("warp-too-big"))
    info = recipe.meta["warp"]
    attempts = info["report"]["attempts"]
    assert len(attempts) >= 1
    # the requested amplitude is never accepted when the Jacobian is not safely positive:
    # either the warp is disabled with a reason, or it was scaled down and that is recorded
    if info["enabled"]:
        assert attempts[-1]["amplitude_mm"] < 6.0
        assert attempts[-1]["positive"] is True
        assert attempts[-1]["jacobian_min_singular"] > 0.2
        assert any(not a["positive"] for a in attempts[:-1])
    else:
        assert "not positive" in info["reason"] or "Jacobian" in info["reason"]
