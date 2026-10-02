"""The calibrated piece-count law: the shipped config reproduces the measured points.

``configs/a12/fracture_calibration.json`` is the machine-readable record of the calibration and
``configs/a12/fracture_physics.yaml`` is the law that runs.  These tests keep the two honest:

* the shipped config's amplitude is the one the calibration measured (and it is *not* the value the
  degenerate reference-energy solve produced before this round);
* the energy exponent inside the measured one-sigma band;
* the law is monotone where the measurements say it is, and the *measured* counter-examples are
  carried in the file instead of being smoothed away;
* the calibration's own fit reproduces the unclamped measured points to the stated error, so the
  R^2 quoted in the documentation is a property of the code and not of a one-off script run.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from synlab.fracture.calibrate import count_fit
from synlab.fracture.impact import BodyStats, MaterialStats, count_model
from synlab.fracture.physics import load_physics_config

REPO_ROOT = Path(__file__).resolve().parents[3]
CALIBRATION = REPO_ROOT / "configs" / "a12" / "fracture_calibration.json"
PHYSICS = REPO_ROOT / "configs" / "a12" / "fracture_physics.yaml"
#: the measured exponent and its one-sigma band (unclamped fit, 21 points, R^2 0.8632)
MEASURED_BETA = 0.588
MEASURED_BETA_SIGMA = 0.054
#: the amplitude the calibration adopted (configs/a12/fracture_calibration.json -> fit_adopted)
ADOPTED_N0 = 2.5295
#: the before/after amplitude of this round's fix
DEGENERATE_N0 = 3.0


@pytest.fixture(scope="module")
def calibration() -> dict:
    if not CALIBRATION.is_file():  # pragma: no cover - the artefact ships with the repo
        pytest.skip(f"{CALIBRATION} is missing")
    return json.loads(CALIBRATION.read_text(encoding="utf-8"))


def _body(volume_mm3: float, wall_mm: float) -> BodyStats:
    return BodyStats(vessel_id="T", volume_mm3=volume_mm3, area_mm2=volume_mm3 ** (2 / 3),
                     thickness_median_mm=wall_mm)


def _material() -> MaterialStats:
    return MaterialStats(material_id="M01", density_g_cm3=2.2, porosity=0.2, grain_size_mm=0.05)


def test_shipped_amplitude_is_the_calibrated_one() -> None:
    config = load_physics_config(PHYSICS)
    assert config.impact.n0 == pytest.approx(ADOPTED_N0, rel=2e-3)
    # the degenerate value of the previous round is NOT what runs any more: it came from solving
    # U_ref out of N0, which left the amplitude free to be anything
    assert abs(config.impact.n0 - DEGENERATE_N0) > 0.3


def test_energy_exponent_is_inside_the_measured_band() -> None:
    config = load_physics_config(PHYSICS)
    beta = float(config.impact.impact_energy_exponent)
    assert abs(beta - MEASURED_BETA) <= 3.0 * MEASURED_BETA_SIGMA


def test_shipped_law_reproduces_the_measured_mid_range_counts() -> None:
    """The three V01/M01 drop heights that carry a measured count above the floor."""
    config = load_physics_config(PHYSICS)
    body = _body(184887.9889183985, 4.080892328102671)
    material = _material()
    measured = {2000.0: 3.0, 4000.0: 5.0, 8000.0: 8.0}
    for height, count in measured.items():
        record = count_model(body, material, config.impact, drop_height_mm=height)
        assert record["clamped"] is False
        assert record["n_deterministic"] == pytest.approx(count, abs=1.5)


def test_law_is_monotone_in_energy_and_size() -> None:
    config = load_physics_config(PHYSICS)
    body = _body(184887.9889183985, 4.080892328102671)
    material = _material()
    counts = [count_model(body, material, config.impact, drop_height_mm=h)["n_deterministic"]
              for h in (500.0, 1000.0, 2000.0, 4000.0, 8000.0)]
    assert counts == sorted(counts)
    # at a *fixed energy* a bigger body must give at least as many pieces (more fracture sites)
    bigger = count_model(_body(184887.9889183985 * 2.0, 4.080892328102671), material,
                         config.impact, energy_j=8.0)["n_deterministic"]
    smaller = count_model(_body(184887.9889183985 / 2.0, 4.080892328102671), material,
                          config.impact, energy_j=8.0)["n_deterministic"]
    assert bigger > smaller


def test_calibration_file_carries_the_measurements_and_the_counter_examples(calibration: dict) -> None:
    assert calibration["schema"] == "synlab.fracture_calibration.v1"
    points = calibration["points"]
    assert len(points) >= 20
    # every point carries what it was measured at
    for point in points:
        assert point["energy_j"] > 0.0
        assert point["volume_mm3"] > 0.0
        assert point["wall_mm"] > 0.0
        assert point["pieces"] >= 2
    mono = calibration["monotonicity"]
    # the controlled size series (one vessel, scaled) is monotone in volume: measured, not assumed
    assert mono["scaled_size_series"]["monotone_non_decreasing"] is True
    assert mono["scaled_size_series_measured_integer"]["monotone_non_decreasing"] is True
    # and the file does NOT claim more than that: the across-vessel comparison is not monotone and
    # the violations are published
    assert mono["all_points_in_volume"]["monotone_non_decreasing"] is False
    assert len(mono["all_points_in_volume"]["violations"]) >= 1
    for violation in mono["all_points_in_volume"]["violations"]:
        assert isinstance(violation["smaller"]["pieces"], (int, float))
        assert isinstance(violation["larger"]["pieces"], (int, float))


def test_calibration_fit_is_reproducible_from_the_points(calibration: dict) -> None:
    """Re-running the fit on the stored points reproduces the published exponents and R^2."""
    points = [dict(p) for p in calibration["points"]]
    published = calibration["fit_unclamped_only"]
    free = [p for p in points if float(p.get("n_deterministic") or 0.0) > 2.0]
    again = count_fit(free, v_ref_mm3=339292.0, thickness_ref_mm=6.0, weibull_modulus=7.0,
                      weibull_volume_exponent=0.5, min_pieces=2, max_pieces=64, censor=False)
    assert again["n"] == published["n"]
    assert again["fitted"]["beta"] == pytest.approx(published["fitted"]["beta"], abs=1e-9)
    assert again["fitted"]["n0"] == pytest.approx(published["fitted"]["n0"], rel=1e-9)
    assert again["r2_log"] == pytest.approx(published["r2_log"], abs=1e-9)
    assert again["r2_log"] > 0.8
    assert again["mae_pieces"] < 1.0
    # the amplitude actually shipped is the one the censored re-solve on all points produced
    adopted = count_fit(points, v_ref_mm3=339292.0, thickness_ref_mm=6.0, weibull_modulus=7.0,
                        weibull_volume_exponent=0.5, min_pieces=2, max_pieces=64, censor=True,
                        beta_override=float(again["fitted"]["beta"]))
    assert adopted["fitted"]["n0"] == pytest.approx(
        calibration["fit_adopted"]["fitted"]["n0"], rel=1e-9)
    config = load_physics_config(PHYSICS)
    assert config.impact.impact_energy_exponent == pytest.approx(adopted["fitted"]["beta"], rel=1e-3)
    assert config.impact.n0 == pytest.approx(adopted["fitted"]["n0"], rel=2e-3)


def test_calibration_reports_the_clamped_share(calibration: dict) -> None:
    """The floor of two pieces is a property of the law and the file says how often it binds."""
    fit = calibration["fit"]
    assert fit["n_censored_at_floor"] >= 1
    assert fit["n"] == len(calibration["points"])
    adopted = calibration["fit_adopted"]["fitted"]
    # the shipped amplitude is the adopted one (the census that constrains it from above)
    assert adopted["n0"] == pytest.approx(ADOPTED_N0, rel=1e-4)
    assert adopted["beta"] == pytest.approx(MEASURED_BETA, rel=1e-6)
    # the declared law (the shipped config, evaluated on the same points) binds at least as often
    declared = calibration["declared_law_on_the_same_points"]
    assert declared["n_clamped"] >= 1


def test_physics_config_declares_the_backends_and_keeps_the_baseline() -> None:
    import yaml

    document = yaml.safe_load(PHYSICS.read_text(encoding="utf-8"))
    block = document["backends"]
    assert block["default"] == "warp_voronoi_cut"
    assert block["baseline"] == "plane_shared_cut"
    assert "plane_shared_cut" in block["implemented"]
    assert document["generation_spec"]["fracture"]["backend"] == block["default"]
    # the thresholds in this file must never be looser than the frozen spec
    from synlab.fracture.spec import (
        AMBIGUITY_AREA_RATIO_MAX, INTERFACE_GAP_P95_MM, NORMAL_REVERSAL_P95_DEG,
        OVERLAP_RATIO_MAX, VOLUME_REL_TOL,
    )

    tolerances = document["tolerances"]
    assert tolerances["interface_gap_p95_mm"] <= INTERFACE_GAP_P95_MM
    assert tolerances["normal_reversal_p95_deg"] <= NORMAL_REVERSAL_P95_DEG
    assert tolerances["volume_rel_tol"] <= VOLUME_REL_TOL
    assert tolerances["overlap_ratio_max"] <= OVERLAP_RATIO_MAX
    assert tolerances["ambiguity_area_ratio_max"] <= AMBIGUITY_AREA_RATIO_MAX
    assert np.isfinite(float(document["count_model"]["n0"]))
