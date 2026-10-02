"""Mate-absent ordinary negatives: the rule, its counts and its guard interaction.

The rule (``synlab.relations.mate_absent``) exists because a candidate that carries its **own**
confirmed ``R2`` mate inside the pool must not be used as an ordinary negative: the pair would
supervise "these two are not the same body" on a fragment whose true partner is in the same
gallery, which is exactly the "has a neighbour => positive" shortcut.  The pool semantics behind
it are the plan's own mate-absent reading (a fragment whose mate is absent from the gallery can
only act as a distractor/negative).

What these tests pin
--------------------
* the rule's classes, including that it is **idempotent** and stable across the ruling;
* that it never rewrites the measurement (``kind``/``valid``/``area_mm2``/identities);
* that the live sampler's exclusion vocabulary reports ``candidate_mate_present``;
* that the rows the sampler produces are accepted by ``training.batch`` with the guard
  **unchanged** -- and that the guard still refuses a mate-present candidate that is offered as
  an ordinary negative *of its own mate* (nothing here relaxes it);
* that the exported-table ruling and the live-pool ruling agree.
"""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from pool_fixtures import add_mate_absent_pieces, build_two_event_store, commit_event, make_event
from synlab.errors import ErrorCode, SynLabError
from synlab.relations.api import PoolConfig, build_pool, sample_training_batch
from synlab.relations.mate_absent import (
    CLASS_EXCLUDED,
    CLASS_MATE_PRESENT,
    CLASS_ORDINARY_NEGATIVE,
    CLASS_POSITIVE,
    MATE_PRESENT_EXCLUSION_REASON,
    MATE_PRESENT_REASON,
    apply_rule,
    class_count_table,
    mate_absent_fragments,
    minimal_trainable_set,
    ordinary_negative_pairs,
    r2_mates,
    row_class,
)
from synlab.relations.sampler import negative_exclusion_reason
from synlab.storage.store import AssetStore
from synlab.training.batch import assert_legal_negative, build_training_batch, negative_audit

CFG = {"queries_per_microbatch": 2, "positive_limit": 2, "legal_negative_limit": 8,
       "negative_mix": {"R1": 0.5, "R0": 0.5}}


# --------------------------------------------------------------------------------------
# a hand-written table: two R2 pairs and two mate-absent pieces
# --------------------------------------------------------------------------------------
def _table() -> list[dict]:
    """``p0-p1`` and ``p2-p3`` are real adjacencies; ``z0``/``z1`` have no mate at all."""
    rows = [
        {"query": "p0", "candidate": "p1", "kind": "R2", "valid": True, "loss_mask": True,
         "area_mm2": 5.0, "reason": "shared_cut_surface", "eligible_as_negative": False},
        {"query": "p2", "candidate": "p3", "kind": "R2", "valid": True, "loss_mask": True,
         "area_mm2": 4.0, "reason": "shared_cut_surface", "eligible_as_negative": False},
        {"query": "p0", "candidate": "p2", "kind": "R0", "valid": True, "loss_mask": True,
         "area_mm2": 0.0, "reason": "different_physical_mother", "eligible_as_negative": True},
        {"query": "p0", "candidate": "z0", "kind": "R0", "valid": True, "loss_mask": True,
         "area_mm2": 0.0, "reason": "different_physical_mother", "eligible_as_negative": True},
        {"query": "p0", "candidate": "z1", "kind": "R0", "valid": True, "loss_mask": True,
         "area_mm2": 0.0, "reason": "different_physical_mother", "eligible_as_negative": True},
        {"query": "z1", "candidate": "z0", "kind": "R1", "valid": True, "loss_mask": True,
         "area_mm2": 0.0, "reason": "mutually_exclusive_event_no_shared_surface",
         "eligible_as_negative": True},
        {"query": "p0", "candidate": "u0", "kind": "UNKNOWN", "valid": False, "loss_mask": False,
         "area_mm2": 0.0, "reason": "truth_not_computed_for_source_event",
         "eligible_as_negative": False},
    ]
    return rows


def test_r2_mates_and_mate_absent_population():
    rows = _table()
    mates = r2_mates(rows)
    assert mates["p0"] == {"p1"} and mates["p3"] == {"p2"}
    assert "z0" not in mates and "z1" not in mates
    assert mate_absent_fragments(rows) == {"z0", "z1", "u0"}


def test_an_invalid_r2_row_is_not_a_mate():
    rows = _table() + [{"query": "z0", "candidate": "z1", "kind": "R2", "valid": False,
                        "loss_mask": False, "area_mm2": 0.0, "reason": "below_area_threshold"}]
    assert mate_absent_fragments(rows) == {"z0", "z1", "u0"}
    strict = mate_absent_fragments(rows, valid_only=False)
    assert strict == {"u0"}


def test_row_classes_and_rule_application():
    rows = _table()
    mates = r2_mates(rows)
    classes = [row_class(row, mates) for row in rows]
    assert classes == [CLASS_POSITIVE, CLASS_POSITIVE, CLASS_MATE_PRESENT,
                       CLASS_ORDINARY_NEGATIVE, CLASS_ORDINARY_NEGATIVE,
                       CLASS_ORDINARY_NEGATIVE, CLASS_EXCLUDED]

    ruled, report = apply_rule(rows)
    # the measurement is untouched and the input is not mutated
    assert rows[2]["loss_mask"] is True and "reason" in rows[2]
    assert [dict(r) for r in rows] == _table()
    assert ruled[2]["kind"] == "R0" and ruled[2]["valid"] is True
    assert ruled[2]["loss_mask"] is False
    assert MATE_PRESENT_REASON in ruled[2]["reason"]
    assert ruled[2]["reason"].startswith("different_physical_mother")
    assert ruled[2]["eligible_as_negative"] is False
    assert [r["loss_mask"] for r in ruled] == [True, True, False, True, True, True, False]
    assert report["rows_reruled"] == 1
    assert report["ordinary_negatives_before"] == 4
    assert report["mate_present_candidates_before"] == 1
    assert report["ordinary_negatives_after"] == 3
    assert report["classes"][CLASS_MATE_PRESENT] == 1
    detail = report["rows_reruled_detail"][0]
    assert detail["candidate_mates"] == ["p3"] and detail["after"]["loss_mask"] is False


def test_the_rule_is_idempotent_and_the_class_is_stable():
    rows = _table()
    once, first = apply_rule(rows)
    twice, second = apply_rule(once)
    assert once == twice
    assert second["rows_reruled"] == 0            # nothing changes on a second pass
    assert second["ordinary_negatives_after"] == first["ordinary_negatives_after"] == 3
    assert str(twice[2]["reason"]).count(MATE_PRESENT_REASON) == 1
    # after the ruling the blocked pair still reads as its own class, not as a plain exclusion
    assert row_class(once[2], r2_mates(once)) == CLASS_MATE_PRESENT
    table = class_count_table(once)
    assert table["classes"][CLASS_MATE_PRESENT] == 1
    assert table["classes"][CLASS_ORDINARY_NEGATIVE] == 3
    assert table["classes"][CLASS_EXCLUDED] == 1
    assert table["fragments_with_mate"] == 4
    assert table["mate_absent_fragments"] == ["u0", "z0", "z1"]


def test_ordinary_negative_pairs_never_name_a_mate_present_candidate():
    rows = apply_rule(_table())[0]
    pairs = ordinary_negative_pairs(rows)
    assert pairs == [("p0", "z0"), ("p0", "z1"), ("z1", "z0")]
    mates = r2_mates(rows)
    assert not any(mates.get(candidate) for _query, candidate in pairs)


def test_minimal_trainable_set_requires_an_encodable_positive_and_two_negatives():
    rows = _table()
    encodable = {"p0": True, "p1": True, "z0": True, "z1": True, "p2": True, "p3": True}
    minimal = minimal_trainable_set(rows, encodable=encodable, minimum_negatives=2)
    assert minimal["ok"] is True
    assert minimal["query"] == "p0"
    assert minimal["positives"] == ["p1"]
    assert minimal["negatives"] == ["z0", "z1"]
    assert minimal["negatives_used"] == ["z0", "z1"]
    assert minimal["all_three_observed"] is True
    # a population that cannot reach the minimum is reported with its reason, never padded
    fewer = minimal_trainable_set(rows, encodable=encodable, minimum_negatives=3)
    assert fewer["ok"] is False and "no query carries both" in fewer["reason"]
    empty = minimal_trainable_set([{**row} for row in rows if row["kind"] != "R0"],
                                  encodable=encodable)
    assert empty["ok"] is False
    # a positive whose mate is unencodable is not usable as a positive either
    blind = minimal_trainable_set(rows, encodable={**encodable, "p1": False})
    assert blind["ok"] is False
    # without a measured encodability map the report says so instead of pretending
    unmeasured = minimal_trainable_set(rows)
    assert unmeasured["encodability_measured"] is False and unmeasured["ok"] is True


# --------------------------------------------------------------------------------------
# store -> pool -> sampler -> training.batch (the guard stays as it is)
# --------------------------------------------------------------------------------------
def _pool(tmp_path: Path, *, absent_count: int = 3):
    store = AssetStore(tmp_path)
    commit_event(store, make_event("LIN0100_V01_M01", "m::100", "a", 4, split="dev", seed=1))
    commit_event(store, make_event("LIN0101_V02_M02", "m::101", "b", 3, split="dev", seed=2))
    add_mate_absent_pieces(store, count=absent_count, r1_to=[("a00", "z00")])
    report = build_pool(store, None, PoolConfig(pool_id="p_mate_absent", size_target=100,
                                               query_per_mother=2))
    assert report["ok"], report.get("error")
    return report["pool"]


def test_live_pool_excludes_mate_present_candidates_from_negatives(tmp_path: Path):
    pool = _pool(tmp_path)
    # a00 and a01 are R2 mates of each other; b00 carries its own mate b01
    assert pool.neighbours("a00") == ["a01"]
    assert pool.neighbours("b00") == ["b01"]
    assert pool.neighbours("z00") == []
    assert negative_exclusion_reason(pool, "a00", "b00") == MATE_PRESENT_EXCLUSION_REASON
    assert negative_exclusion_reason(pool, "a00", "a01") == "known_R2"
    assert negative_exclusion_reason(pool, "a00", "z00") is None
    assert negative_exclusion_reason(pool, "a00", "z01") is None

    batch = sample_training_batch(pool, {**CFG, "queries_per_microbatch": 2,
                                        "legal_negative_limit": 4},
                                  np.random.default_rng(5))
    assert batch["rows"]
    seen = 0
    for row in batch["rows"]:
        for candidate in row["negatives"]:
            seen += 1
            assert pool.neighbours(candidate) == []          # mate-absent, by construction
            assert pool.relation(row["query"], candidate) in ("R0", "R1")
    assert seen > 0
    assert batch["exclusions"][MATE_PRESENT_EXCLUSION_REASON] >= 1


def test_sampled_rows_are_accepted_by_the_unchanged_guard(tmp_path: Path):
    """The whole point: with mate-absent negatives the trainer's own builder accepts the rows."""
    from synlab.training.adapter import FeatureBundle

    pool = _pool(tmp_path)
    bundle = FeatureBundle.from_dict({fid: pool.features[fid]
                                      for fid in pool.lineup}).check_shapes()
    batch = sample_training_batch(pool, {**CFG, "queries_per_microbatch": 3,
                                        "legal_negative_limit": 4},
                                  np.random.default_rng(4))
    built = build_training_batch(bundle, pool=pool, rows=batch["rows"])
    audit = negative_audit(built)
    assert audit["ok"] is True, audit
    assert audit["negatives"] > 0
    assert int(built.neg_mask.sum()) == sum(len(row["negatives"]) for row in batch["rows"])
    assert built.effective_query_count() >= 1
    assert int(built.negative_is_r2_history.sum()) == 0


def test_guard_still_refuses_a_mate_present_candidate_of_its_own_mate(tmp_path: Path):
    """Nothing here relaxes ``assert_legal_negative``: the real leak is still refused."""
    with pytest.raises(SynLabError) as excinfo:
        assert_legal_negative("R2", query_id="a00", candidate_id="a01", is_history_r2=True)
    assert excinfo.value.code == ErrorCode.LEAKAGE_DETECTED
    with pytest.raises(SynLabError):
        assert_legal_negative("R0", query_id="a00", candidate_id="a01", is_history_r2=True)
    with pytest.raises(SynLabError):
        assert_legal_negative("UNKNOWN", query_id="a00", candidate_id="u0", confirmed=True)
    with pytest.raises(SynLabError):
        assert_legal_negative("R0", query_id="a00", candidate_id="b00", confirmed=False)


def test_the_separate_class_is_allowed_by_the_guard_and_still_not_an_ordinary_negative(
        tmp_path: Path):
    """The guard accepts a mate-present candidate; the plan's rule is what refuses it.

    This is the honest statement of the boundary: the mate-present class is *not* a guard
    violation (the guard only knows the query's own history), so it cannot be caught by
    ``assert_legal_negative``.  It is refused by the mate-absent rule instead, which is why the
    ruling has to happen in the negative construction and not in the guard.
    """
    pool = _pool(tmp_path)
    assert_legal_negative("R0", query_id="a00", candidate_id="b00", is_history_r2=False,
                          confirmed=True)                     # accepted by the guard
    assert negative_exclusion_reason(pool, "a00", "b00") == MATE_PRESENT_EXCLUSION_REASON
    batch = sample_training_batch(pool, {**CFG, "queries_per_microbatch": 3,
                                         "legal_negative_limit": 6},
                                  np.random.default_rng(9))
    for row in batch["rows"]:
        assert "b00" not in row["negatives"] and "b01" not in row["negatives"]
        assert "b00" in row["excluded"] or "b01" in row["excluded"]


def test_exported_table_ruling_and_live_pool_ruling_agree(tmp_path: Path):
    """The row-level ruling of the export and the pool-level exclusion name the same pairs."""
    pool = _pool(tmp_path)
    rows = []
    for query in pool.lineup:
        for candidate in pool.lineup:
            if query == candidate:
                continue
            relation = pool.relation(query, candidate)
            if relation not in ("R0", "R1", "R2"):
                continue
            rows.append({"query": query, "candidate": candidate, "kind": relation,
                         "valid": True, "loss_mask": True, "area_mm2": 0.0, "reason": ""})
    ruled, _report = apply_rule(rows)
    table_pairs = set(ordinary_negative_pairs(ruled))
    pool_pairs = {(query, candidate) for query, candidate in table_pairs
                  if negative_exclusion_reason(pool, query, candidate) is None}
    assert table_pairs == pool_pairs
    assert table_pairs, "the fixture must leave at least one legal negative"


def test_counts_are_measured_not_declared(tmp_path: Path):
    pool = _pool(tmp_path, absent_count=4)
    rows = []
    for query in pool.lineup:
        for candidate in pool.lineup:
            if query == candidate:
                continue
            relation = pool.relation(query, candidate)
            rows.append({"query": query, "candidate": candidate,
                         "kind": relation if relation in ("R0", "R1", "R2") else "UNKNOWN",
                         "valid": relation in ("R0", "R1", "R2"), "loss_mask": True,
                         "area_mm2": 0.0, "reason": ""})
    before = copy.deepcopy(rows)
    ruled, report = apply_rule(rows)
    assert rows == before, "apply_rule must not mutate its input"
    assert report["ordinary_negatives_after"] == len(ordinary_negative_pairs(ruled))
    assert report["queries_with_ordinary_negative"] == len(
        {query for query, _c in ordinary_negative_pairs(ruled)})
    assert report["fragments"] == len(pool.lineup)
