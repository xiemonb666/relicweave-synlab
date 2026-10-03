"""Hand-computed metric fixtures and the frozen NA/failure denominators (plan 19.1, 30.14)."""

from __future__ import annotations

import numpy as np
import pytest

from synlab.diagnostics.metrics import (
    STATUS_INPUT_UNAVAILABLE,
    STATUS_OK,
    STATUS_REJECTED,
    STATUS_TIMEOUT,
    accept_set,
    aggregate_metrics,
    any_at_m,
    conditional_cov,
    conditional_cov_at_k,
    cov_recall_at_k,
    dedupe_candidates,
    effective_cov_at_k,
    effective_hit_at_k,
    hit_at_k,
    pool_cov_at_m,
    pool_miss,
    query_metrics,
    risk_events,
)
from synlab.diagnostics.fixtures import run_fixtures


# ---------------------------------------------------------------------------- hand computed
def test_hand_computed_primary_case():
    """q has true neighbours B and C, the pool holds only B, TopK holds B."""
    neighbours = ["B", "C"]
    pool = ["B", "X1", "X2"]
    top = ["B", "X1"]
    assert hit_at_k(top, neighbours) == 1.0
    assert pool_cov_at_m(pool, neighbours) == 0.5
    assert cov_recall_at_k(top, neighbours) == 0.5
    assert conditional_cov(pool, neighbours) == 1.0
    assert any_at_m(pool, neighbours) == 1.0
    assert pool_miss(pool, neighbours) is False


def test_fixture_suite_reports_required_flags():
    report = run_fixtures()
    metrics = report["metrics"]
    assert metrics["ok"] is True
    for key in ("hand_computed_hit", "hand_computed_poolcov", "hand_computed_cov",
                "effective_zero_on_failure", "absent_risk_defined"):
        assert metrics[key] is True, key
    assert report["stats"]["clopper_pearson_ok"] is True
    assert report["stats"]["bootstrap_unit"] == "shape_lineage"
    assert metrics["checks_passed"] == metrics["checks_total"]
    assert report["stats"]["checks_passed"] == report["stats"]["checks_total"]


# ---------------------------------------------------------------------------- NA semantics
def test_mate_absent_query_is_na_but_stays_in_the_risk_denominator():
    neighbours: list[str] = []
    row = query_metrics(query_id="q", neighbours=neighbours, gallery_ids=["X1", "X2"],
                        first_stage=["X1"], ranked=["X1"], top_k=(1, 5), accepted=[])
    assert row["hit@1"] is None and row["cov@1"] is None
    assert row["hit_na"] is True and row["pool_cov_na"] is True
    assert row["in_absent_denominator"] is True and row["in_frozen_denominator"] is True
    assert row["absent_false_accept"] == 0
    accepted = query_metrics(query_id="q2", neighbours=[], gallery_ids=["X1"],
                            first_stage=["X1"], ranked=["X1"], top_k=(1,))
    assert accepted["absent_false_accept"] == 1
    summary = aggregate_metrics([row, accepted], top_k=(1,))
    assert summary["absent_denominator"] == 2
    assert summary["present_denominator"] == 0
    assert summary["frozen_denominator"] == 2
    assert summary["risk"]["absent_false_accept_events"] == 1
    assert summary["risk"]["absent_false_accept_rate"] == 0.5
    assert summary["k=1"]["hit_at_k"] is None
    assert summary["k=1"]["hit_at_k_na_count"] == 2
    assert summary["k=1"]["effective_hit_at_k"] is None          # no present query at all


def test_failure_timeout_and_no_input_keep_effective_zero_in_the_frozen_denominator():
    good = query_metrics(query_id="q1", neighbours=["B"], gallery_ids=["B"], first_stage=["B"],
                         ranked=["B"], top_k=(1,), lineage_cluster="L1")
    timeout = query_metrics(query_id="q2", neighbours=["C"], gallery_ids=["C"], first_stage=[],
                            ranked=[], top_k=(1,), status=STATUS_TIMEOUT,
                            failure_code="TIMEOUT", lineage_cluster="L2")
    no_input = query_metrics(query_id="q3", neighbours=["D"], gallery_ids=["D"],
                             first_stage=[], ranked=[], top_k=(1,),
                             status=STATUS_INPUT_UNAVAILABLE,
                             failure_code="INPUT_UNAVAILABLE", lineage_cluster="L3")
    rejected = query_metrics(query_id="q4", neighbours=["E"], gallery_ids=["E"],
                             first_stage=["E"], ranked=["E"], top_k=(1,), accepted=[],
                             status=STATUS_REJECTED, failure_code="REJECTED", lineage_cluster="L4")
    summary = aggregate_metrics([good, timeout, no_input, rejected], top_k=(1,))
    assert summary["present_denominator"] == 4
    assert summary["frozen_denominator"] == 4
    assert summary["failures"] == 2 and summary["rejections"] == 1
    assert timeout["effective_hit@1"] == 0.0 and timeout["effective_cov@1"] == 0.0
    assert no_input["effective_hit@1"] == 0.0 and no_input["effective_cov@1"] == 0.0
    assert rejected["effective_cov@1"] == 0.0
    assert rejected["hit@1"] == 1.0                       # the original ranking is still reported
    # a query whose original ranking was never produced reports NA, never a fabricated 0
    assert timeout["rank_produced"] is False and timeout["hit@1"] is None
    assert no_input["rank_produced"] is False and no_input["cov@1"] is None
    assert rejected["rank_produced"] is True
    assert summary["k=1"]["effective_cov_at_k"] == pytest.approx(0.25)
    assert summary["k=1"]["effective_cov_at_k_denominator"] == 4
    assert summary["k=1"]["effective_cov_at_k_completed_only"] == 1.0
    assert summary["k=1"]["cov_recall_at_k"] == 1.0       # the two produced rankings are exact
    assert summary["k=1"]["cov_recall_at_k_na_count"] == 2
    assert summary["all_rejected_present"] == 1
    assert summary["failure_counts"] == {"TIMEOUT": 1, "INPUT_UNAVAILABLE": 1, "REJECTED": 1}


def test_conditional_cov_na_is_counted_as_pool_miss():
    row = query_metrics(query_id="q", neighbours=["B"], gallery_ids=["X"], first_stage=["X"],
                        ranked=["X"], top_k=(1,))
    assert row["conditional_cov"] is None and row["conditional_cov_na"] is True
    assert row["pool_miss"] is True
    summary = aggregate_metrics([row], top_k=(1,))
    assert summary["pool_miss"] == 1
    assert summary["conditional_cov_na_count"] == 1
    assert summary["any_at_m"] == 0.0
    assert summary["pool_cov_at_m"] == 0.0


def test_conditional_cov_at_k_measures_refined_coverage_inside_pool():
    neighbours = ["B", "C"]
    first_stage = ["B", "C", "X"]
    assert conditional_cov_at_k(["B"], first_stage, neighbours) == 0.5
    assert conditional_cov_at_k(["X"], first_stage, neighbours) == 0.0
    assert conditional_cov_at_k(["B", "C"], ["B", "X"], neighbours) == 1.0
    assert conditional_cov_at_k(["B"], ["X"], neighbours) is None
    assert pool_miss(["X"], neighbours) is True
    # The retained two-argument API is explicitly only a pool-presence census.
    assert conditional_cov(first_stage, neighbours) == 1.0


def test_query_metrics_and_aggregate_use_conditional_cov_at_each_k():
    row = query_metrics(query_id="q", neighbours=["B", "C"], gallery_ids=["B", "C", "X"],
                        first_stage=["B", "C", "X"], ranked=["B", "X"], top_k=(1, 2))
    summary = aggregate_metrics([row], top_k=(1, 2))

    assert row["conditional_cov@1"] == 0.5
    assert row["conditional_cov@2"] == 0.5
    assert row["conditional_cov"] == row["conditional_cov@2"]
    assert row["conditional_cov_legacy_pool_census"] == 1.0
    assert summary["k=1"]["conditional_cov_at_k"] == 0.5
    assert summary["k=2"]["conditional_cov_at_k"] == 0.5
    assert summary["conditional_cov"] == 0.5
    assert summary["pool_miss"] == 0


def test_generator_top_k_is_consumed_once_for_query_and_aggregate_metrics():
    row = query_metrics(query_id="q", neighbours=["B"], gallery_ids=["B", "X"],
                        first_stage=["B", "X"], ranked=["B", "X"],
                        top_k=(k for k in (1, 2)))
    summary = aggregate_metrics([row], top_k=(k for k in (1, 2)))

    assert row["conditional_cov@1"] == 1.0
    assert row["conditional_cov@2"] == 1.0
    assert summary["k=1"]["conditional_cov_at_k"] == 1.0
    assert summary["k=2"]["conditional_cov_at_k"] == 1.0


# ---------------------------------------------------------------------------- hygiene
def test_duplicate_candidates_collapse_and_self_is_never_a_candidate():
    row = query_metrics(query_id="q", neighbours=["B", "C"], gallery_ids=["q", "B", "C", "X1"],
                        first_stage=["q", "B", "B", "X1"], ranked=["q", "B", "B", "C", "X1"],
                        top_k=(1, 3))
    assert row["rank_order"] == ["B", "C", "X1"]
    assert row["first_stage"] == ["B", "X1"]
    assert row["duplicates_removed"] == 2
    assert row["self_candidates_removed"] >= 1
    assert pool_cov_at_m(["B", "B"], ["B", "C"]) == 0.5
    unique, hygiene = dedupe_candidates(["a", "a", "b", "q"], query_id="q")
    assert unique == ["a", "b"]
    assert hygiene["duplicates_removed"] == 1 and hygiene["self_candidates_removed"] == 1


def test_gallery_smaller_than_k_does_not_pad():
    row = query_metrics(query_id="q", neighbours=["B"], gallery_ids=["q", "B"], first_stage=["B"],
                        ranked=["B"], top_k=(1, 5, 10, 20))
    assert row["rank_order"] == ["B"]
    for k in (1, 5, 10, 20):
        assert row[f"cov@{k}"] == 1.0
        assert row[f"hit@{k}"] == 1.0


def test_multi_neighbour_coverage():
    neighbours = ["B", "C", "D"]
    assert pool_cov_at_m(["B", "C"], neighbours) == pytest.approx(2.0 / 3.0)
    assert cov_recall_at_k(["B", "C"], neighbours) == pytest.approx(2.0 / 3.0)
    assert cov_recall_at_k(["B", "C", "D"], neighbours) == 1.0


# ---------------------------------------------------------------------------- acceptance
def test_accept_set_uses_threshold_and_observed_validity():
    candidates = ["B", "X1", "C"]
    scores = {"B": 0.9, "X1": 0.4, "C": 0.8}
    assert accept_set(candidates, scores, threshold=0.5) == ["B", "C"]
    assert accept_set(candidates, scores, threshold=0.5,
                      observed_valid={"B": True, "X1": True, "C": False}) == ["B"]
    assert accept_set(candidates, scores, threshold=0.5, keep_top=1) == ["B"]
    assert accept_set(candidates, scores, threshold=0.95) == []


def test_multiple_positives_may_be_accepted_together():
    accepted = accept_set(["B", "C", "X1"], {"B": 1.0, "C": 0.9, "X1": 0.1}, threshold=0.5)
    assert accepted == ["B", "C"]
    assert effective_cov_at_k(accepted, ["B", "C"]) == 1.0
    assert effective_hit_at_k(accepted, ["B", "C"]) == 1.0


def test_risk_events_cover_the_four_combinations():
    assert risk_events([], ["X"])["absent_false_accept"] == 1
    assert risk_events([], [])["absent_false_accept"] == 0
    assert risk_events(["B"], ["B", "R1x"])["present_wrong_accept"] == 1
    assert risk_events(["B"], ["B"])["present_wrong_accept"] == 0
    both = risk_events(["B"], ["B", "R1x"])
    assert both["n_wrong_accepted"] == 1 and both["wrong_accepted"] == ["R1x"]


def test_aggregate_reports_acceptance_duplicates_and_all_rejected():
    rows = [
        query_metrics(query_id="q1", neighbours=["B"], gallery_ids=["B", "X"],
                      first_stage=["B", "X"], ranked=["B", "X"], top_k=(2,)),
        query_metrics(query_id="q2", neighbours=["C"], gallery_ids=["C", "X"],
                      first_stage=["X"], ranked=["C", "X"], top_k=(2,), accepted=[],
                      status=STATUS_REJECTED, failure_code="REJECTED"),
    ]
    summary = aggregate_metrics(rows, top_k=(2,))
    assert summary["acceptance_rate"] == pytest.approx(0.5)
    assert summary["present_denominator"] == 2
    # q1 accepted its true mate *and* a wrong candidate -> the event counts; q2 rejected all
    assert summary["risk"]["present_wrong_accept_events"] == 1
    assert summary["risk"]["present_wrong_accept_rate"] == 0.5
    assert summary["all_rejected_present"] == 1
    assert "frozen_denominator_note" in summary


def test_aggregate_ignores_na_instead_of_writing_a_fake_zero():
    rows = [query_metrics(query_id="q", neighbours=[], gallery_ids=["X"], first_stage=["X"],
                          ranked=["X"], top_k=(1,))]
    summary = aggregate_metrics(rows, top_k=(1,))
    assert summary["k=1"]["hit_at_k"] is None
    assert summary["k=1"]["cov_recall_at_k"] is None
    assert summary["pool_cov_at_m"] is None
    assert summary["any_at_m"] is None
    assert summary["k=1"]["effective_cov_at_k"] is None
    assert summary["present_denominator"] == 0 and summary["absent_denominator"] == 1
