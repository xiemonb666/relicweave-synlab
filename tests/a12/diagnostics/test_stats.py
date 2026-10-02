"""Statistics tests: clustered bootstrap, Holm, Clopper-Pearson and power (plan 19.4, 30.15)."""

from __future__ import annotations

import numpy as np
import pytest

from synlab.diagnostics.stats import (
    BOOTSTRAP_UNIT,
    achieved_power,
    clopper_pearson_upper,
    holm_correction,
    macro_mean_by_stratum,
    n90,
    paired_bootstrap_ci,
    power_approx,
    power_report,
    risk_bound_table,
    summarise_risk_events,
    zeron_event_units,
)


# ------------------------------------------------------------------------------- bootstrap
def test_paired_bootstrap_unit_is_the_lineage_cluster():
    paired = {"LIN1": [0.04, 0.02], "LIN2": [0.06], "LIN3": [0.01, 0.03, 0.02],
              "LIN4": [0.05, 0.07]}
    report = paired_bootstrap_ci(paired, replicates=2000, seed=5)
    assert report["unit"] == BOOTSTRAP_UNIT == "shape_lineage"
    assert report["unit_is_shape_lineage"] is True
    assert report["replicates"] == 2000
    assert report["n_clusters"] == 4
    assert report["n_observations"] == 8
    expected = float(np.mean([np.mean(v) for v in paired.values()]))
    assert report["mean_delta"] == pytest.approx(expected, abs=1e-12)
    assert report["ci_low"] <= report["mean_delta"] <= report["ci_high"]
    assert report["per_cluster_mean"]["LIN2"] == pytest.approx(0.06)


def test_bootstrap_is_deterministic_for_a_seed_and_repeats_do_not_inflate_n():
    paired = {"LIN1": [0.1] * 50, "LIN2": [0.2] * 50, "LIN3": [0.3] * 50}
    first = paired_bootstrap_ci(paired, replicates=1000, seed=11)
    second = paired_bootstrap_ci(paired, replicates=1000, seed=11)
    assert first["ci_low"] == second["ci_low"]
    assert first["n_clusters"] == 3          # 150 observations are still only 3 clusters
    assert first["n_observations"] == 150
    assert first["ci_high"] - first["ci_low"] > 0


def test_bootstrap_refuses_a_single_cluster():
    report = paired_bootstrap_ci({"LIN1": [0.1, 0.2]}, replicates=500)
    assert report["ok"] is False
    assert report["ci_low"] is None and report["ci_high"] is None
    assert "single cluster" in report["degenerate"]


def test_bootstrap_accepts_pair_sequences_and_detects_direction():
    report = paired_bootstrap_ci([("LIN1", 0.02), ("LIN1", 0.01), ("LIN2", 0.04),
                                  ("LIN3", -0.01), ("LIN3", 0.0), ("LIN4", 0.03)],
                                 replicates=1000, seed=2, null_delta=0.0)
    assert report["n_clusters"] == 4
    assert report["direction"] == "positive"
    assert report["excludes_null"] is True


def test_macro_mean_by_stratum_reports_the_worst_layer():
    rows = [{"vessel": "V01", "value": 0.5}, {"vessel": "V01", "value": 0.6},
            {"vessel": "V02", "value": 0.2}, {"vessel": "V03", "value": 0.9}]
    report = macro_mean_by_stratum(rows, value_key="value", stratum_key="vessel")
    assert report["n_strata"] == 3
    assert report["macro_mean"] == pytest.approx((0.55 + 0.2 + 0.9) / 3)
    assert report["worst_stratum"]["name"] == "V02"


# ----------------------------------------------------------------------------------- Holm
def test_holm_correction_adjusts_and_stops():
    report = holm_correction({"a": 0.001, "b": 0.01, "c": 0.04, "d": 0.2}, alpha=0.05)
    assert report["adjusted"]["a"] == pytest.approx(0.004)
    assert report["adjusted"]["b"] == pytest.approx(0.03)
    assert report["adjusted"]["c"] == pytest.approx(0.08)
    assert report["adjusted"]["d"] == pytest.approx(0.2)
    assert report["rejected"] == {"a": True, "b": True, "c": False, "d": False}
    assert report["n_rejected"] == 2
    assert holm_correction([])["ok"] is False


# ------------------------------------------------------------------------ Clopper-Pearson
def test_clopper_pearson_zero_event_closed_form():
    upper_20 = clopper_pearson_upper(0, 20, 0.05)
    upper_29 = clopper_pearson_upper(0, 29, 0.05)
    assert upper_20 == pytest.approx(0.1391, abs=5e-4)
    assert upper_29 == pytest.approx(0.0981, abs=5e-4)
    assert upper_20 == pytest.approx(1.0 - 0.05 ** (1.0 / 20.0), abs=1e-15)
    assert upper_29 == pytest.approx(1.0 - 0.05 ** (1.0 / 29.0), abs=1e-15)
    assert clopper_pearson_upper(0, 59, 0.05) < 0.05
    assert clopper_pearson_upper(0, 299, 0.05) < 0.01


def test_clopper_pearson_nonzero_uses_scipy_beta():
    from scipy.stats import beta

    assert clopper_pearson_upper(1, 20, 0.05) == pytest.approx(float(beta.ppf(0.95, 2, 19)))
    assert clopper_pearson_upper(3, 40, 0.05) == pytest.approx(float(beta.ppf(0.95, 4, 37)))
    assert clopper_pearson_upper(20, 20, 0.05) == 1.0
    with pytest.raises(ValueError):
        clopper_pearson_upper(21, 20, 0.05)
    with pytest.raises(ValueError):
        clopper_pearson_upper(0, 0, 0.05)


def test_zero_event_units_table_matches_the_plan():
    assert zeron_event_units(0.10) == 29
    assert zeron_event_units(0.05) == 59
    assert zeron_event_units(0.01) == 299
    table = risk_bound_table(0.05)
    assert table["units"] == {"10%": 29, "5%": 59, "1%": 299}


def test_risk_summary_refuses_all_zero_bootstrap_claims():
    evidence = summarise_risk_events(0, 20, alpha=0.05, target=0.10)
    assert evidence["upper_bound"] == pytest.approx(0.1391, abs=5e-4)
    assert evidence["meets_target"] is False
    assert evidence["zero_event_units_required"] == 29
    assert evidence["verdict"] == "NOT_ESTABLISHED"
    passing = summarise_risk_events(0, 30, alpha=0.05, target=0.10)
    assert passing["verdict"] == "PASS" and passing["meets_target"] is True
    non_zero = summarise_risk_events(1, 20, alpha=0.05, target=0.10)
    assert non_zero["verdict"] == "NOT_ESTABLISHED"


# ---------------------------------------------------------------------------------- power
def test_power_approximation_matches_the_plan_examples():
    assert power_approx(0.10, 0.03, alpha=0.05, power=0.8) == 88
    assert power_approx(0.20, 0.03, alpha=0.05, power=0.8) == 349
    assert power_approx(0.10, 0.03, alpha=0.05, power=0.9) > 88
    with pytest.raises(ValueError):
        power_approx(0.0, 0.03)
    report = power_report(0.10, 0.03, pilot_clusters=10)
    assert report["n_approx"] == 88
    assert report["achieved_power_at_n"] >= 0.79
    assert report["n_sensitivity"]["2x_sd"] > report["n_approx"]
    assert achieved_power(88, 0.10, 0.03) >= 0.79


# ------------------------------------------------------------------------------------ n90
def test_n90_only_brackets_measured_points():
    reached = n90([(200, 0.40), (1000, 0.62), (2500, 0.95)], reference=1.0, metric="Cov@10")
    assert reached["status"] == "BRACKETED"
    assert reached["bracket"][0] <= reached["n90"] <= reached["bracket"][1]
    assert reached["extrapolated"] is False
    not_reached = n90([(200, 0.40), (1000, 0.55)], reference=1.0)
    assert not_reached["status"] == "NOT_REACHED"
    assert not_reached["n90"] is None
    assert "never reaches" in not_reached["reason"]
    too_few = n90([(200, 0.40)])
    assert too_few["status"] == "INSUFFICIENT_POINTS"
    measured_reference = n90([(200, 0.40), (1000, 0.85)])
    assert measured_reference["reference_source"] == "max_measured_value"
    assert measured_reference["status"] == "BRACKETED"
