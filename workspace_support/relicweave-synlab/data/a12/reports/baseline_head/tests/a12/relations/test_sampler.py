"""Training sampler and hard-negative mining tests (plan 16.2, 16.3, 30.10).

The batch rows produced here are fed to ``synlab.training.batch.build_training_batch`` through
the documented ``rows=`` interface.  ``synlab/training/batch.py`` currently has a defect in
``_build_lookup`` (it returns the neighbour *dict* while ``build_training_batch`` calls it as a
function, ``TypeError: 'dict' object is not callable``); that file is outside this task's write
scope, so the integration test applies the one-line wrapper locally and records the defect here
and in ``docs/a12/relations_diagnostics_episodes.md``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pool_fixtures import build_two_event_store, commit_event, make_event
from synlab.errors import ErrorCode, SynLabError
from synlab.relations.api import PoolConfig, build_pool, mine_hard_negatives, sample_training_batch
from synlab.relations.sampler import (
    HARD_GROUPS,
    assert_legal_feature_payload,
    legal_retrieval_vector,
    negative_exclusion_reason,
    new_sampler_state,
)
from synlab.storage.store import AssetStore

CFG = {"queries_per_microbatch": 2, "positive_limit": 2, "legal_negative_limit": 8,
       "negative_mix": {"R1": 0.5, "R0": 0.5}}


def _pool(tmp_path: Path, **kwargs):
    store, specs = build_two_event_store(tmp_path, **kwargs)
    report = build_pool(store, None, PoolConfig(pool_id="p_sampler", size_target=100,
                                                query_per_mother=2))
    assert report["ok"], report.get("error")
    return report["pool"]


def test_lineage_balanced_draw_and_row_structure(tmp_path: Path):
    pool = _pool(tmp_path)
    batch = sample_training_batch(pool, CFG, np.random.default_rng(3))
    assert batch["schema"] == "synlab.relations.batch.v1"
    assert len(batch["rows"]) == 2
    clusters = [row["lineage_cluster"] for row in batch["rows"]]
    assert len(set(clusters)) == len(clusters), clusters       # one query per lineage first
    for row in batch["rows"]:
        assert set(row) >= {"query", "positives", "negatives", "excluded", "r1_fallback",
                            "sample_key"}
        assert row["query"] not in row["positives"] + row["negatives"]
        assert 1 <= len(row["positives"]) <= CFG["positive_limit"]
    assert batch["index"]["n_queries"] == 2
    assert batch["index"]["fragment_ids"]
    assert all(isinstance(v, str) for v in batch["rows"][0]["negatives"])
    assert batch["exposure"]["mothers_exposed"] == 2
    assert set(batch["exposure"]["hard_groups"]) == set(HARD_GROUPS)


def test_positives_walk_the_whole_r2_set_across_batches(tmp_path: Path):
    store = AssetStore(tmp_path)
    spec = make_event("LIN0100_V01_M01", "m::100", "a", 6, split="dev", seed=1)
    commit_event(store, spec)
    report = build_pool(store, None, PoolConfig(pool_id="p_cov", size_target=100,
                                                query_per_mother=1))
    pool = report["pool"]
    query = next(fid for fid in pool.lineup if len(pool.neighbours(fid)) >= 2)
    neighbours = set(pool.neighbours(query))
    assert len(neighbours) >= 2
    state = new_sampler_state()
    seen: set[str] = set()
    for step in range(12):
        batch = sample_training_batch(pool, {**CFG, "queries_per_microbatch": 1,
                                             "positive_limit": 1, "legal_negative_limit": 2},
                                      np.random.default_rng(step), state=state,
                                      query_ids=[query])
        row = batch["rows"][0]
        assert set(row["positives"]) <= neighbours
        seen.update(row["positives"])
    assert seen == neighbours, (sorted(seen), sorted(neighbours))
    assert batch["exposure"]["r2_edges_exposed_cumulative"] == len(neighbours)


def test_negatives_remove_all_history_r2_tiny_unknown_and_self(tmp_path: Path):
    store = AssetStore(tmp_path)
    spec = make_event("LIN0101_V01_M01", "m::101", "a", 5, split="dev", seed=2)
    spec.r1 = [("a00", "a04")]
    spec.tiny = [("a00", "a03")]
    spec.unknown = [("a00", "a02")]
    commit_event(store, spec)
    report = build_pool(store, None, PoolConfig(pool_id="p_excl", size_target=100,
                                                query_per_mother=1))
    pool = report["pool"]
    # the query's R2 set is {a01} and the *other* pieces are R0 unless declared otherwise
    batch = sample_training_batch(pool, {**CFG, "queries_per_microbatch": 1,
                                        "positive_limit": 1, "legal_negative_limit": 8},
                                  np.random.default_rng(1), query_ids=["a00"])
    row = batch["rows"][0]
    assert row["positives"] == ["a01"]
    assert "a00" not in row["negatives"]
    assert "a01" not in row["negatives"]                       # history R2, not just positives
    assert "a02" not in row["negatives"]                       # UNKNOWN
    assert "a03" not in row["negatives"]                       # TINY_CONTACT
    assert "a04" in row["negatives"]                           # confirmed R1 is legal
    assert set(row["excluded"]) >= {"a01", "a02", "a03", "a00"}
    assert batch["exclusions"]["known_R2"] >= 1
    assert batch["exclusions"]["gray_zone"] == 1
    assert batch["exclusions"]["TINY_CONTACT"] == 1
    reasons = {c: negative_exclusion_reason(pool, "a00", c) for c in pool.lineup}
    assert reasons["a02"] == "gray_zone" and reasons["a03"] == "TINY_CONTACT"
    assert reasons["a01"] == "known_R2" and reasons["a00"] == "same_fragment"
    assert reasons["a04"] is None


def test_r1_fallback_is_recorded_not_invented(tmp_path: Path):
    store = AssetStore(tmp_path)
    # two lineages with *no* R1 edge between them: every query must fall back to R0
    spec_a = make_event("LIN0102_V01_M01", "m::102", "a", 3, split="dev", seed=3)
    spec_b = make_event("LIN0103_V02_M02", "m::103", "b", 3, split="dev", seed=4)
    commit_event(store, spec_a)
    commit_event(store, spec_b)
    report = build_pool(store, None, PoolConfig(pool_id="p_fallback", size_target=100,
                                                query_per_mother=2))
    pool = report["pool"]
    batch = sample_training_batch(pool, CFG, np.random.default_rng(0))
    assert batch["rows"]
    for row in batch["rows"]:
        assert row["r1_fallback"] is True
        assert all(pool.relation(row["query"], c) == "R0" for c in row["negatives"])
    assert batch["exposure"]["r1_fallback_events"] == len(batch["rows"])


def test_r1_and_r0_quota_is_four_plus_four_with_shortfall_to_r0(tmp_path: Path):
    pool = _pool(tmp_path)
    batch = sample_training_batch(pool, {**CFG, "legal_negative_limit": 8},
                                  np.random.default_rng(11))
    for row in batch["rows"]:
        query = row["query"]
        legal = [c for c in pool.candidate_ids(query)
                 if negative_exclusion_reason(pool, query, c) is None]
        r1_available = [c for c in legal if pool.relation(query, c) == "R1"]
        r0_available = [c for c in legal if pool.relation(query, c) == "R0"]
        r1 = [c for c in row["negatives"] if pool.relation(query, c) == "R1"]
        r0 = [c for c in row["negatives"] if pool.relation(query, c) == "R0"]
        expected_r1 = min(4, len(r1_available))
        assert len(r1) == expected_r1, (query, r1, r1_available)
        assert len(r0) == min(8 - expected_r1, len(r0_available))
        assert len(row["negatives"]) == len(r1) + len(r0)
    assert batch["exposure"]["negatives"] == sum(len(r["negatives"]) for r in batch["rows"])


def test_r0_quota_categories_need_legal_observations(tmp_path: Path):
    pool = _pool(tmp_path)
    batch = sample_training_batch(pool, CFG, np.random.default_rng(7))
    categories = batch["exposure"]["r0_categories"]
    assert categories["pattern_approx"] >= 1 and categories["geometry_approx"] >= 1
    assert not batch["exposure"]["r0_categories_unavailable"]
    bare = _pool(tmp_path / "bare", features=False)
    batch_bare = sample_training_batch(bare, CFG, np.random.default_rng(7))
    assert batch_bare["exposure"]["r0_categories"]["pattern_approx"] == 0
    assert "pattern_approx" in batch_bare["exposure"]["r0_categories_unavailable"]


def test_q5_exposure_is_recorded_not_removed(tmp_path: Path):
    store = AssetStore(tmp_path)
    spec = make_event("LIN0104_V01_M01", "m::104", "a", 4, split="dev", seed=5,
                      quality_tier={"a00": 5, "a01": 5})
    commit_event(store, spec)
    report = build_pool(store, None, PoolConfig(pool_id="p_q5", size_target=10,
                                                query_per_mother=1))
    pool = report["pool"]
    batch = sample_training_batch(pool, {**CFG, "queries_per_microbatch": 1},
                                  np.random.default_rng(0), query_ids=["a00"])
    assert "a00" in batch["exposure"]["q5_unresolvable_queries"]
    assert batch["rows"][0]["quality_tier"] == 5
    assert batch["rows"][0]["positives"] == ["a01"]            # the hard query is not dropped


def test_forbidden_fields_never_reach_the_retrieval_features(tmp_path: Path):
    pool = _pool(tmp_path)
    payload = dict(pool.features["a00"])
    payload["mate_present"] = True
    with pytest.raises(SynLabError) as excinfo:
        legal_retrieval_vector(payload)
    assert excinfo.value.code == ErrorCode.LEAKAGE_DETECTED
    with pytest.raises(SynLabError):
        assert_legal_feature_payload({"nested": {"historical_R2": ["a01"]}})


def test_mine_hard_negatives_uses_labels_only_for_exclusion(tmp_path: Path):
    pool = _pool(tmp_path)
    mined = mine_hard_negatives(pool, ["a00"], top_m=3)
    assert len(mined) == 1
    entry = mined[0]
    assert entry["status"] == "OK"
    assert entry["retrieved"] == 3
    by_candidate = {c["candidate"]: c for c in entry["candidates"]}
    assert len(by_candidate) == 3
    for candidate, info in by_candidate.items():
        if info["relation"] == "R2":
            assert info["usable_as_negative"] is False
            assert info["exclusion_reason"] == "known_R2"
        if info["relation"] == "UNKNOWN":
            assert info["usable_as_negative"] is False
    assert all("score" in info for info in by_candidate.values())
    assert entry["cache"]["encoder_hash"] == ""
    # retrieval is deterministic (no random candidate selection)
    again = mine_hard_negatives(pool, ["a00"], top_m=3)
    assert [c["candidate"] for c in again[0]["candidates"]] == list(by_candidate)


def test_mine_hard_negatives_records_stale_cache(tmp_path: Path):
    pool = _pool(tmp_path)
    mined = mine_hard_negatives(pool, ["a00"], top_m=2, encoder_hash="enc_v2",
                                cache={"encoder_hash": "enc_v1", "age_batches": 12},
                                cache_version="c2")
    assert mined[0]["cache"]["stale"] is True
    assert mined[0]["cache"]["cache_age_batches"] == 12
    assert mined[0]["cache"]["source"] == "train_only"


def test_mine_hard_negatives_without_features_is_na(tmp_path: Path):
    pool = _pool(tmp_path / "bare", features=False)
    mined = mine_hard_negatives(pool, ["a00"], top_m=5)
    assert mined[0]["status"] == "INPUT_UNAVAILABLE"
    assert mined[0]["candidates"] == []


def test_rows_feed_training_batch(tmp_path: Path):
    """Integration with ``synlab.training.batch`` (with the documented local patch)."""
    from synlab.training import batch as training_batch
    from synlab.training.adapter import FeatureBundle

    pool = _pool(tmp_path)
    bundle = FeatureBundle.from_dict({fid: pool.features[fid]
                                      for fid in pool.lineup}).check_shapes()
    batch = sample_training_batch(pool, CFG, np.random.default_rng(4))
    original = training_batch._build_lookup

    def _patched(labels, pool_arg, ids):
        relation_of, neighbours, confirmed_of = original(labels, pool_arg, ids)
        return relation_of, (lambda fid: set(neighbours.get(fid, set()))), confirmed_of

    training_batch._build_lookup = _patched
    try:
        built = training_batch.build_training_batch(bundle, pool=pool, rows=batch["rows"])
    finally:
        training_batch._build_lookup = original
    audit = training_batch.negative_audit(built)
    assert audit["ok"] is True, audit
    assert audit["negatives"] == sum(len(row["negatives"]) for row in batch["rows"])
    assert audit["positives"] == sum(len(row["positives"]) for row in batch["rows"])
    exposure = built.exposure()
    assert exposure["r2_edges_exposed"] == audit["positives"]
    assert exposure["exclusion_histogram"]["known_R2"] >= 0
