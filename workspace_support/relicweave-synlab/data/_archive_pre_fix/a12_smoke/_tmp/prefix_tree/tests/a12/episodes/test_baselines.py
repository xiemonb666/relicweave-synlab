"""Rule baseline tests (plan 17.2): legal set, STOP closure, ORACLE_ACTION isolation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from synlab.diagnostics.runner import CallableScorer
from synlab.episodes.baselines import (
    BASELINE_NAMES,
    ORACLE_TAG,
    assert_baseline_legal,
    legal_baselines,
    observable_action_features,
    oracle_action,
    run_baseline,
    run_oracle,
    select_action,
)
from synlab.episodes.env import STOP_ACTION, EpisodeEnv
from synlab.errors import ErrorCode, SynLabError

from test_env import _env, _quality_scorer  # noqa: E402  (shared local helpers)


def test_legal_baseline_set_excludes_the_oracle():
    assert legal_baselines() == BASELINE_NAMES
    assert ORACLE_TAG not in BASELINE_NAMES
    assert set(BASELINE_NAMES) == {"uniform_capture", "coverage_first", "single_step_quality",
                                   "greedy_gain_cost", "stop_only"}
    with pytest.raises(SynLabError) as excinfo:
        assert_baseline_legal(ORACLE_TAG)
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID


def test_every_legal_baseline_terminates_with_a_stop_reason(tmp_path: Path):
    env, pool = _env(tmp_path)
    for name in BASELINE_NAMES:
        report = run_baseline(env, name, episode_id="ep::a00")
        assert report["legal_baseline"] is True
        assert report["policy"] == name
        assert report["metrics"]["stop_reason"] in (
            "STOP", "BUDGET_ACTIONS", "BUDGET_TIME", "NO_AVAILABLE_ACTION")
        assert report["final_state"]["done"] is True
        assert report["pool_id"] == pool.pool_id
        for step in report["steps"]:
            assert step["environment_side_only"] is True
            assert step["cost_seconds"] >= 0
        if name != "stop_only":
            assert report["metrics"]["seconds"] >= 0


def test_stop_only_takes_no_capture_action(tmp_path: Path):
    env, _pool = _env(tmp_path)
    report = run_baseline(env, "stop_only", episode_id="ep::a00")
    assert report["metrics"]["actions"] == 0
    assert report["metrics"]["frames"] == 0
    assert report["metrics"]["stop_reason"] == "STOP"
    assert len(report["steps"]) == 1 and report["steps"][0]["action_id"] == STOP_ACTION
    assert report["metrics"]["gt_cov_recall_initial"] == report["metrics"]["gt_cov_recall_final"]


def test_uniform_capture_uses_the_declared_cost(tmp_path: Path):
    env, _pool = _env(tmp_path)
    report = run_baseline(env, "uniform_capture", episode_id="ep::a00", max_steps=2)
    assert report["metrics"]["actions"] == 2
    for step in report["steps"]:
        if step["action_id"] == STOP_ACTION:
            continue
        assert step["capture_seconds"] > 0
        assert step["inference_seconds"] >= 0
        assert step["frames"] >= 1
    assert report["metrics"]["seconds"] >= report["metrics"]["capture_seconds"]


def test_greedy_is_labelled_as_an_unlearned_proxy(tmp_path: Path):
    env, _pool = _env(tmp_path)
    report = run_baseline(env, "greedy_gain_cost", episode_id="ep::a00", max_steps=2)
    assert "UNLEARNED_GAIN_PROXY" in report["metrics"]["gain_proxy"]
    assert report["legal_baseline"] is True


def test_coverage_first_reports_unnecessary_actions(tmp_path: Path):
    env, _pool = _env(tmp_path)
    report = run_baseline(env, "coverage_first", episode_id="ep::a00", max_steps=3)
    metrics = report["metrics"]
    assert metrics["pool_rerank_only_steps"] >= 0
    assert metrics["unnecessary_actions"] <= metrics["pool_rerank_only_steps"]
    assert metrics["failed_steps"] == 0


def test_oracle_is_tagged_and_reported_apart(tmp_path: Path):
    env, pool = _env(tmp_path)
    payloads = pool.features
    target = next(fid for fid in pool.lineup if fid != "a00")

    def observer(query, state, spec):
        return {"payload": dict(payloads[target]), "views": [f"{spec.action_id}#v1"],
                "obs_version": int(state.obs_version) + 1, "seconds": 3.0}

    env.observer = observer
    report = run_oracle(env, episode_id="ep::a00", max_steps=2)
    assert report["tag"] == ORACLE_TAG
    assert report["legal_baseline"] is False
    assert report["metrics"]["legal_baseline"] is False
    for step in report["steps"]:
        assert step["legal_baseline"] is False
        assert step["tag"] == ORACLE_TAG
        assert "per_action_gt_gain" in step
    assert ORACLE_TAG not in BASELINE_NAMES


def test_oracle_action_reads_ground_truth_and_is_never_a_legal_choice(tmp_path: Path):
    env, pool = _env(tmp_path)
    payloads = pool.features
    target = next(fid for fid in pool.lineup if fid != "a00")

    def observer(query, state, spec):
        return {"payload": dict(payloads[target]), "views": [f"{spec.action_id}#v1"],
                "obs_version": int(state.obs_version) + 1, "seconds": 3.0}

    env.observer = observer
    state = env.reset("ep::a00")
    action, detail = oracle_action(env, state)
    assert detail["tag"] == ORACLE_TAG
    assert detail["legal"] is False
    assert detail["per_action_gt_gain"]
    assert action in env.available_actions(state) or action == STOP_ACTION
    for name in BASELINE_NAMES:
        chosen = select_action(env, state, name, counters={})
        assert chosen != ORACLE_TAG
        assert chosen in env.available_actions(state)


def test_observable_action_features_carry_no_ground_truth(tmp_path: Path):
    env, _pool = _env(tmp_path)
    state = env.reset("ep::a00")
    action = next(a for a in state.available_actions if a.startswith("U_MOVE:"))
    features = observable_action_features(env, state, action)
    assert set(features) == {"action_id", "kind", "tier", "view_kind", "cost_seconds", "frames",
                             "novelty", "declared_by"}
    assert features["cost_seconds"] > 0
    assert features["novelty"] in (0.0, 1.0)


def test_baseline_without_any_available_action_stops(tmp_path: Path):
    env, _pool = _env(tmp_path)
    state = env.reset("ep::a00")
    state.available_actions = [STOP_ACTION]
    for name in BASELINE_NAMES:
        assert select_action(env, state, name, counters={}) == STOP_ACTION
