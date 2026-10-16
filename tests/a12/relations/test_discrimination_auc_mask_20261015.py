"""MC07: relation discrimination respects legal relation and loss-mask semantics."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _pool_for_scores(monkeypatch, scores: dict[str, float]):
    """Return exact cosine fixtures by making every query vector the x axis."""
    from synlab.relations import sampler

    monkeypatch.setattr(
        sampler,
        "legal_retrieval_vector",
        lambda payload: np.asarray(payload["vector"], dtype=np.float64),
    )
    pool = type("ScorePool", (), {})()
    pool.features = {}
    pool.mother_of = {}
    ids = {}
    for index, (name, score) in enumerate(list(scores.items())):
        query_id, candidate_id = f"q{index}", f"c{index}"
        pool.features[query_id] = {"vector": [1.0, 0.0]}
        pool.features[candidate_id] = {
            "vector": [score, float(np.sqrt(1.0 - score * score))]
        }
        pool.mother_of[query_id] = f"mother{index}"
        pool.mother_of[candidate_id] = f"mother{index}"
        ids[name] = (query_id, candidate_id)
    return pool, ids


def test_auc_masks_non_supervised_rows_and_excludes_nonphysical_kinds(monkeypatch):
    from synlab.relations.negatives import discrimination_auc

    pool, ids = _pool_for_scores(
        monkeypatch,
        {
            "positive_legacy_mask": 0.9,
            "positive_explicit_mask": 0.8,
            "negative_r0": 0.6,
            "negative_r1_legacy_mask": 0.2,
            "masked_r0": 0.99,
            "valid_tiny_unmasked": 0.01,
            "unknown_masked_in": 0.95,
            "invalid_r0": 0.98,
            "missing_kind": 0.97,
        },
    )

    def row(name: str, kind: str, **fields):
        query, candidate = ids[name]
        return {"query": query, "candidate": candidate, "kind": kind, **fields}

    relations = [
        row("positive_legacy_mask", "R2", valid=True),
        row("positive_explicit_mask", "R2", valid=True, loss_mask=True),
        row("negative_r0", "R0", valid=True, loss_mask=True),
        row("negative_r1_legacy_mask", "R1", valid=True),
        row("masked_r0", "R0", valid=True, loss_mask=False),
        row("valid_tiny_unmasked", "TINY_CONTACT", valid=True, loss_mask=False),
        row("unknown_masked_in", "UNKNOWN", valid=True, loss_mask=True),
        row("invalid_r0", "R0", valid=False, loss_mask=True),
        {"query": ids["missing_kind"][0], "candidate": ids["missing_kind"][1],
         "valid": True, "loss_mask": True},
    ]

    report = discrimination_auc(pool, relations, bootstrap=50, seed=7)

    assert report["metric_version"] == "relations.discrimination_auc.v2"
    assert report["status"] == "MEASURED"
    assert report["denominator"] == {
        "input_relations": 9,
        "excluded_by_kind": 3,
        "excluded_by_valid": 1,
        "excluded_by_loss_mask": 1,
        "relation_eligible": 4,
        "eligible_self_pairs": 0,
        "eligible_pairs_missing_features": 0,
        "scorable_pairs": 4,
        "positive_pairs": 2,
        "negative_pairs": 2,
    }
    # Hand calculation: positives (.9, .8) outrank negatives (.6, .2) in all 4 comparisons.
    assert report["auc"] == 1.0
    assert report["pairs"] == 4
    assert report["positives"] == 2 and report["negatives"] == 2
    assert report["negative_kinds"] == ["R0", "R1"]
    assert {(pair["a"], pair["b"]) for pair in report["per_pair"]} == {
        ids[name] for name in ("positive_legacy_mask", "positive_explicit_mask",
                               "negative_r0", "negative_r1_legacy_mask")
    }


def test_auc_single_class_is_not_established_with_null_metrics(monkeypatch):
    from synlab.relations.negatives import discrimination_auc

    pool, ids = _pool_for_scores(monkeypatch, {"positive": 0.7, "masked_negative": 0.99})
    rows = [
        {"query": ids["positive"][0], "candidate": ids["positive"][1],
         "kind": "R2", "valid": True},
        {"query": ids["masked_negative"][0], "candidate": ids["masked_negative"][1],
         "kind": "R0", "valid": True, "loss_mask": False},
    ]

    report = discrimination_auc(pool, rows, bootstrap=20, seed=5)

    assert report["status"] == "NOT_ESTABLISHED"
    assert report["ok"] is False
    assert report["denominator"]["scorable_pairs"] == 1
    assert report["denominator"]["positive_pairs"] == 1
    assert report["denominator"]["negative_pairs"] == 0
    assert report["auc"] is None
    assert report["auc_interval"] is None
    assert report["accuracy_at_median_threshold"] is None


def test_auc_empty_eligible_set_is_not_run_and_reports_zero_denominator(monkeypatch):
    from synlab.relations.negatives import discrimination_auc

    pool, ids = _pool_for_scores(monkeypatch, {"invalid": 0.7, "unknown": 0.8})
    rows = [
        {"query": ids["invalid"][0], "candidate": ids["invalid"][1],
         "kind": "R0", "valid": False, "loss_mask": True},
        {"query": ids["unknown"][0], "candidate": ids["unknown"][1],
         "kind": "UNKNOWN", "valid": True, "loss_mask": True},
    ]

    report = discrimination_auc(pool, rows)

    assert report["status"] == "NOT_RUN"
    assert report["ok"] is False
    assert report["denominator"]["input_relations"] == 2
    assert report["denominator"]["relation_eligible"] == 0
    assert report["denominator"]["scorable_pairs"] == 0
    assert "AUC denominator is 0" in report["reason"]
    assert report["auc"] is None
    assert report["auc_interval"] is None
    assert report["accuracy_at_median_threshold"] is None
