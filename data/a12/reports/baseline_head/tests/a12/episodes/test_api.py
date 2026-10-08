"""``run_episode_config`` tests: report shape, pool resolution, oracle isolation (plan 17)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from relations.pool_fixtures import build_two_event_store
from synlab.episodes.api import run_episode_config
from synlab.errors import ErrorCode, SynLabError
from synlab.relations.api import PoolConfig, build_pool, save_pool_json
from synlab.roles import ROLE_EPISODE
from synlab.storage.store import AssetStore


def _store_with_pool(tmp_path: Path, pool_id: str = "episode_dev", **pool_kwargs):
    store, _specs = build_two_event_store(tmp_path)
    report = build_pool(store, None, PoolConfig(pool_id=pool_id, size_target=100,
                                                query_per_mother=2, **pool_kwargs))
    assert report["ok"], report.get("error")
    artifacts = tmp_path / "pools"
    save_pool_json(report["pool"], artifacts / f"{pool_id}.json")
    return store, report["pool"]


def _config(tmp_path: Path, pool_id: str, **overrides) -> Path:
    payload = {
        "schema": "synlab.pool.v1",
        "pool_id": pool_id,
        "gallery_version": "v1",
        "scope": "FULL",
        "split": "dev",
        "size_target": 100,
        "query_per_mother": 2,
        "baselines": ["uniform_capture", "coverage_first", "single_step_quality",
                      "greedy_gain_cost", "stop_only"],
        "budget": {"max_actions": 2, "max_seconds": 600, "candidate_pool_size": 3},
        "oracle": True,
    }
    payload.update(overrides)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path = tmp_path / f"episode_{pool_id}.json"
    path.write_text(text, encoding="utf-8")
    return path


def test_run_episode_config_reports_steps_costs_and_stop_reasons(tmp_path: Path):
    store, pool = _store_with_pool(tmp_path)
    config = _config(tmp_path, pool.pool_id)
    report = run_episode_config(store, config)
    assert report["ok"] is True and report["status"] == "QA_PASSED"
    assert report["steps"], "at least the STOP records must be kept"
    assert set(report["costs"]) >= {"uniform_capture", "coverage_first", "single_step_quality",
                                    "greedy_gain_cost", "stop_only"}
    assert report["stop_reasons"]
    metrics = report["metrics"]
    assert set(report["metrics"]) >= {"baselines", "steps_total", "seconds_total", "frames_total"}
    assert metrics["legal_baselines"] == ["uniform_capture", "coverage_first",
                                          "single_step_quality", "greedy_gain_cost", "stop_only"]
    assert metrics["oracle_reported_separately"] is True
    assert metrics["oracle_excluded_from_baselines"] is True
    assert metrics["stop_closed"] is True
    assert metrics["pool_id"] == pool.pool_id
    for step in report["steps"]:
        assert "policy" in step and "action_id" in step
        assert step["legal_baseline"] is (step["policy"] != "ORACLE_ACTION")
    assert report["policy_metrics"]["stop_only"]["actions"] == 0
    assert report["oracle"]["metrics"]["legal_baseline"] is False
    asset = store.get_asset(report["trace_asset_id"])
    assert asset.role == ROLE_EPISODE
    assert asset.meta["steps"] == len(report["steps"])
    assert json.loads(asset.meta["trace_json"])


def test_run_episode_config_marks_pool_rerank_only_steps(tmp_path: Path):
    store, pool = _store_with_pool(tmp_path)
    config = _config(tmp_path, pool.pool_id)
    report = run_episode_config(store, config)
    rerank = [step for step in report["steps"] if step["pool_rerank_only"]]
    assert rerank, "without new evidence every capture can only re-rank the original pool"
    for step in rerank:
        assert step["candidates_entered"] == []
        assert step["no_new_evidence"] is True


def test_oracle_cannot_be_listed_as_a_rule_baseline(tmp_path: Path):
    store, pool = _store_with_pool(tmp_path)
    config = _config(tmp_path, pool.pool_id, baselines=["uniform_capture", "ORACLE_ACTION"])
    with pytest.raises(SynLabError) as excinfo:
        run_episode_config(store, config)
    assert excinfo.value.code in (ErrorCode.SCHEMA_INVALID,
                                  ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION)


def test_missing_pool_raises_input_unavailable(tmp_path: Path):
    store = AssetStore(tmp_path / "empty")
    config = _config(tmp_path, "absent_pool")
    with pytest.raises(SynLabError) as excinfo:
        run_episode_config(store, config)
    assert excinfo.value.code == ErrorCode.INPUT_UNAVAILABLE


def test_pool_without_features_cannot_run_an_episode(tmp_path: Path):
    store, _specs = build_two_event_store(tmp_path, features=False)
    report = build_pool(store, None, PoolConfig(pool_id="no_features", size_target=100,
                                                query_per_mother=1))
    assert report["ok"]
    save_pool_json(report["pool"], tmp_path / "pools" / "no_features.json")
    config = _config(tmp_path, "no_features")
    with pytest.raises(SynLabError) as excinfo:
        run_episode_config(store, config)
    assert excinfo.value.code == ErrorCode.INPUT_UNAVAILABLE
    assert "legal observation payloads" in excinfo.value.message


def test_declared_accessories_extend_the_action_catalogue(tmp_path: Path):
    store, pool = _store_with_pool(tmp_path)
    config = _config(tmp_path, pool.pool_id,
                     cameras={"accessories": ["light"],
                              "turntable": {"azimuth_step_deg": 15, "max_steps": 1,
                                            "step_seconds": 5.0}})
    report = run_episode_config(store, config)
    actions = {step["action_id"] for step in report["steps"]}
    assert any(action.startswith("TOGGLE_LIGHT:") for action in actions)
    assert any(action.startswith("ADD_AZIMUTH:") for action in actions)


def test_episode_query_can_be_selected_explicitly(tmp_path: Path):
    store, pool = _store_with_pool(tmp_path)
    query = next(fid for fid in pool.lineup if pool.neighbours(fid))
    config = _config(tmp_path, pool.pool_id, episode_query=query)
    report = run_episode_config(store, config)
    assert report["metrics"]["query_id"] == query
    for policy, metrics in report["policy_metrics"].items():
        assert metrics["policy"] == policy
