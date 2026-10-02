"""Scale audit: line widths, dot spacing and wavelengths are measured in millimetres.

Plan 9.6 requires the line width, dot spacing and shortest wavelength to be measured on
the surface with recorded quantiles and a real local range, not asserted from the recipe.
"""

from __future__ import annotations

import numpy as np
import pytest

from synlab.patterns import api
from synlab.patterns.params import SPACING_RANGE

LINE_FAMILIES = ("PAT02", "PAT03", "PAT04", "PAT07", "PAT08", "PAT09", "PAT11", "PAT12",
                 "PAT15", "PAT16")


@pytest.mark.parametrize("family_id", LINE_FAMILIES)
def test_measured_line_width_is_in_millimetres_and_inside_the_plan_band(family_id,
                                                                       small_mother,
                                                                       recipe_factory):
    recipe = recipe_factory(small_mother, family_id, 1, allow_aux_layers=False)
    audit = api.audit_pattern(recipe, small_mother, n_pairs=32, geometry_probe=False,
                              scale_samples=72)
    width = audit["scale"]["line_width_mm"]
    if width["status"] != "OK":
        # a sparse motif, or a window with fewer than three unimodal cross-sections, must
        # say so instead of reporting a width
        assert width.get("reason")
        return
    assert width["n_measurements"] >= 3
    assert 0.1 <= width["p05_mm"] <= width["p50_mm"] <= width["p95_mm"] <= 12.0
    declared = audit["scale"]["declared_line_width_mm"]
    assert declared > 0
    # The measured FWHM is a *surface* measurement: a cross-section taken diagonally across
    # a lattice edge or through a junction is wider than the frozen stroke width, and a
    # rasterised family carries one texel of quantisation.  The median must stay within a
    # factor of the frozen width and the whole distribution is reported by the audit.
    assert 0.5 * declared - 0.2 <= width["p50_mm"] <= 2.2 * declared + 0.3, (
        f"{family_id}: measured p50 {width['p50_mm']:.3f} mm vs declared {declared:.3f} mm")


def test_dot_spacing_and_cross_seam_distance(small_mother, rng_factory):
    spec = {"family": "PAT06", "allow_aux_layers": False,
            "params": {"mode": "poisson", "radius_mm": 2.0, "clearance_mm": 0.5}}
    recipe = api.build_pattern(small_mother, spec, rng_factory("scale-dots"))
    audit = api.audit_pattern(recipe, small_mother, n_pairs=32, geometry_probe=False,
                              scale_samples=0)
    spacing = audit["scale"]["dot_spacing_mm"]
    assert spacing["status"] == "OK"
    assert spacing["pass"] is True
    assert spacing["min_neighbour_distance_mm"] >= spacing["required_min_distance_mm"] - 1e-9
    assert spacing["min_radius_sum_margin_mm"] >= -1e-9
    assert spacing["cross_seam_min_distance_mm"] >= 2.0 * spacing["radius_max_mm"] - 1e-9
    report = audit["scale"]["dots_report"]
    assert report["n_kept"] > 20
    assert 0.0 <= report["rejection_rate"] <= 1.0
    assert report["n_removed_cross_seam"] >= 0
    assert report["density_per_100mm2"] >= report["density_target_per_100mm2"] - 1e-9
    assert report["max_gap_mm"] is not None


@pytest.mark.parametrize("family_id", ("PAT03", "PAT05", "PAT06", "PAT11", "PAT13", "PAT15"))
def test_measured_spectrum_is_reported_with_quantiles(family_id, small_mother,
                                                     recipe_factory):
    recipe = recipe_factory(small_mother, family_id, 1, allow_aux_layers=False)
    audit = api.audit_pattern(recipe, small_mother, n_pairs=32, geometry_probe=False,
                              scale_samples=0)
    spectrum = audit["scale"]["spectrum"]
    assert spectrum["status"] in ("OK", "FLAT_FIELD")
    if spectrum["status"] != "OK":
        return
    assert spectrum["dominant_wavelength_mm"] > 0
    assert spectrum["nyquist_wavelength_mm"] > 0
    assert len(spectrum["bands"]) >= 3
    fractions = [b["energy_fraction"] for b in spectrum["bands"]]
    coverage = spectrum["octave_band_coverage"]
    assert coverage == pytest.approx(sum(fractions), rel=1e-9, abs=1e-12)
    assert 0.0 < coverage <= 1.0 + 1e-9
    assert coverage + spectrum["high_frequency_residual"] == pytest.approx(1.0, abs=1e-9)
    minimum = spectrum["min_wavelength_mm"]
    if minimum is not None:
        assert minimum >= 0.2, "the shortest resolved wavelength must stay physical"
        assert minimum <= spectrum["dominant_wavelength_mm"] + 1e-9
    frozen = recipe.meta["spectrum"]
    if frozen.get("dominant_wavelength_mm") and spectrum.get("dominant_wavelength_mm"):
        agreement = abs(spectrum["dominant_wavelength_mm"] - frozen["dominant_wavelength_mm"]) \
            / frozen["dominant_wavelength_mm"]
        assert agreement < 0.35, "the audit-time spectrum must reproduce the frozen one"


def test_circumferential_metric_is_reported(small_mother, cylinder_mother, recipe_factory):
    recipe = recipe_factory(cylinder_mother, "PAT03", 1, allow_aux_layers=False)
    audit = api.audit_pattern(recipe, cylinder_mother, n_pairs=32, geometry_probe=False,
                              scale_samples=0)
    metric = audit["scale"]["circumferential_metric"]
    assert metric["x_period_mm"] > 0
    assert metric["u_arc_length_mm_min"] > 0
    assert metric["u_arc_length_mm_max"] >= metric["u_arc_length_mm_min"]
    assert "varies with the radius" in metric["note"]
    spacing = audit["scale"].get("circumferential_spacing_mm")
    if spacing:
        assert spacing["integer_count"] >= 1
        assert spacing["local_spacing_mm_min"] <= spacing["local_spacing_mm_max"]


def test_declared_spacing_inside_the_plan_band(small_mother, recipe_factory):
    for family_id in ("PAT02", "PAT03", "PAT04", "PAT09"):
        recipe = recipe_factory(small_mother, family_id, 1, allow_aux_layers=False)
        spacing = recipe.params.get("spacing_requested_mm")
        if spacing is None:
            continue
        assert SPACING_RANGE[0] - 1e-9 <= float(spacing) <= SPACING_RANGE[1] + 1e-9
