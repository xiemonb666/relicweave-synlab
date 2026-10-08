"""Episode environment tests (plan 17.1, 17.2, 30.14).

The camera catalogue is the real one (``synlab.cameras.api.camera_profiles``): GLOBAL/MID/LOCAL
tiers with declared slide travel and step, no declared accessories -- which is exactly what
makes an undeclared light/polarisation action *unreachable*.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from relations.pool_fixtures import build_two_event_store
from synlab.diagnostics.runner import CallableScorer
from synlab.episodes.env import STOP_ACTION, EpisodeEnv, available_actions, step
from synlab.errors import ErrorCode, SynLabError
from synlab.relations.api import PoolConfig, build_pool


def _quality_scorer() -> CallableScorer:
    """Scorer over the observed quality channel only -- lets a test control the ranking."""

    def _fn(payloads):
        vectors, valid = {}, {}
        for fid, payload in payloads.items():
            quality = np.asarray(payload["quality"], dtype=np.float64)
            vec = np.concatenate([quality.mean(axis=0), [1e-6]])
            norm = float(np.linalg.norm(vec))
            vectors[str(fid)] = vec / norm if norm > 1e-12 else vec
            valid[str(fid)] = norm > 1e-12
        return vectors, valid

    return CallableScorer(_fn, name="quality_channel")


def _env(tmp_path: Path, *, observer=None, budget=None, pool_kwargs=None):
    store, _specs = build_two_event_store(tmp_path)
    report = build_pool(store, None, PoolConfig(pool_id="ep_pool", size_target=100,
                                                query_per_mother=2, **(pool_kwargs or {})))
    assert report["ok"], report.get("error")
    pool = report["pool"]
    env = EpisodeEnv(store, pool, budget=budget or {"max_actions": 4, "max_seconds": 600.0,
                                                    "candidate_pool_size": 3},
                     scorer=_quality_scorer(), observer=observer)
    return env, pool


def test_reset_reveals_only_the_initial_observation(tmp_path: Path):
    env, pool = _env(tmp_path)
    state = env.reset("ep::a00")
    assert state.query_id == "a00"
    assert state.step == 0 and state.obs_version == 0 and state.done is False
    assert state.candidate_ids and len(state.candidate_ids) <= 3
    assert "a00" not in state.candidate_ids
    assert state.revealed_views == env._initial_views("a00")
    assert state.meta["no_ground_truth"] is True
    assert "reward" not in state.meta
    assert avail_actions_only_declared(state.available_actions)
    assert state.available_actions[0] == STOP_ACTION


def avail_actions_only_declared(actions):
    assert STOP_ACTION in actions
    for action in actions:
        assert action == STOP_ACTION or ":" in action
    return True


def test_available_actions_follow_the_camera_declaration(tmp_path: Path):
    env, _pool = _env(tmp_path)
    state = env.reset("ep::a00")
    catalogue = env.action_catalogue()
    assert STOP_ACTION in state.available_actions
    u_moves = [a for a in state.available_actions if a.startswith("U_MOVE:")]
    assert u_moves, state.available_actions
    for action in u_moves:
        spec = catalogue[action]
        profile = next(p for p in env.cameras if p.profile_id == spec.profile_id)
        travel = profile.meta["u_travel_mm"]
        assert travel[0] - 1e-9 <= spec.u_position_mm <= travel[1] + 1e-9
        assert spec.cost_seconds > 0
    assert any(a.startswith("LOCAL_FRACTURE_FRAME:") for a in state.available_actions)
    # accessories are not declared by the shipped rig -> they are not offered
    assert not any(a.startswith("TOGGLE_LIGHT:") for a in state.available_actions)
    assert not any(a.startswith("TOGGLE_POLARIZATION:") for a in state.available_actions)
    assert not any(a.startswith("RECLAMP_FLIP:") for a in state.available_actions)


def test_unreachable_actions_are_rejected(tmp_path: Path):
    env, _pool = _env(tmp_path)
    state = env.reset("ep::a00")
    with pytest.raises(SynLabError) as excinfo:
        env.step("TOGGLE_LIGHT:CAM_LOCAL_V3", state)
    assert excinfo.value.code == ErrorCode.TARGET_INFEASIBLE
    assert "not declared" in excinfo.value.message
    with pytest.raises(SynLabError):
        env.step("U_MOVE:CAM_LOCAL_V3@+500mm", state)          # far outside the declared travel
    assert not state.done
    assert len(env.trace) == 0


def test_stop_closes_the_episode(tmp_path: Path):
    env, _pool = _env(tmp_path)
    state = env.reset("ep::a00")
    action = next(a for a in state.available_actions if a.startswith("U_MOVE:"))
    state, cost, done = env.step(action, state)
    assert done is False and cost["seconds"] > 0
    final, _cost, done = env.stop(state)
    assert done is True and final.done is True and final.stop_reason == "STOP"
    assert final.available_actions == [STOP_ACTION]
    with pytest.raises(SynLabError) as excinfo:
        env.step(action, final)
    assert "STOPPED" in excinfo.value.message


def test_step_rechecks_the_whole_fixed_gallery(tmp_path: Path):
    env, pool = _env(tmp_path)
    state = env.reset("ep::a00")
    initial = list(state.candidate_ids)
    target = "b02"
    assert target not in initial
    payloads = pool.features

    def observer(query, current_state, spec):
        payload = dict(payloads[target])          # a legal re-observation of the same query
        return {"payload": payload, "views": [f"{spec.action_id}#v1"], "obs_version": 1,
                "seconds": 4.0}

    env.observer = observer
    action = next(a for a in state.available_actions if a.startswith("U_MOVE:"))
    new_state, cost, done = env.step(action, state)
    assert cost["action"]["action_id"] == action
    assert env.trace[-1]["no_new_evidence"] is False
    assert env.trace[-1]["pool_rerank_only"] is False
    assert target in new_state.candidate_ids
    entered = new_state.meta["candidates_entered"]
    assert target in entered
    assert set(entered) <= set(pool.lineup) - {"a00"}       # only real gallery identities
    assert set(new_state.candidate_ids) <= set(pool.lineup) - {"a00"}
    # the re-check is over the whole gallery: the query is the only excluded identity
    assert env.trace[-1]["candidate_count"] <= 3
    assert cost["delta_cov_recall"] is not None


def test_no_new_evidence_is_labelled_pool_rerank_only(tmp_path: Path):
    env, _pool = _env(tmp_path)
    state = env.reset("ep::a00")
    initial = list(state.candidate_ids)
    action = next(a for a in state.available_actions if a.startswith("U_MOVE:"))
    new_state, cost, _done = env.step(action, state)
    assert new_state.candidate_ids == initial
    assert new_state.meta["pool_rerank_only"] is True
    assert env.trace[-1]["no_new_evidence"] is True
    assert cost["delta_cov_recall"] == 0.0


def test_unselected_action_images_never_enter_the_state(tmp_path: Path):
    env, _pool = _env(tmp_path)
    state = env.reset("ep::a00")
    actions = [a for a in state.available_actions if a != STOP_ACTION]
    taken = actions[0]
    new_state, _cost, _done = env.step(taken, state)
    assert len(new_state.revealed_views) == len(state.revealed_views) + 1
    assert new_state.revealed_views[-1].startswith(taken)
    for other in actions[1:]:
        assert not any(view.startswith(other) for view in new_state.revealed_views)


def test_budget_exhaustion_sets_an_explicit_stop_reason(tmp_path: Path):
    env, _pool = _env(tmp_path, budget={"max_actions": 1, "max_seconds": 600.0,
                                        "candidate_pool_size": 3})
    state = env.reset("ep::a00")
    action = next(a for a in state.available_actions if a.startswith("U_MOVE:"))
    state, _cost, done = env.step(action, state)
    assert done is True and state.done is True
    assert state.stop_reason == "BUDGET_ACTIONS"
    with pytest.raises(SynLabError):
        env.step(action, state)


def test_reward_and_ground_truth_stay_environment_side(tmp_path: Path):
    env, _pool = _env(tmp_path)
    state = env.reset("ep::a00")
    action = next(a for a in state.available_actions if a.startswith("U_MOVE:"))
    new_state, cost, _done = env.step(action, state)
    assert "reward" in cost and "delta_cov_recall" in cost
    assert env.trace[-1]["environment_side_only"] is True

    def keys(node, prefix=""):
        out = []
        if isinstance(node, dict):
            for key, value in node.items():
                out.append(f"{prefix}{key}")
                out.extend(keys(value, f"{prefix}{key}."))
        elif isinstance(node, (list, tuple)):
            for index, value in enumerate(node[:4]):
                out.extend(keys(value, f"{prefix}[{index}]."))
        return out

    state_keys = keys(new_state.meta)
    for forbidden in ("reward", "gt_", "mate_present", "success"):
        assert not any(forbidden in key for key in state_keys), (forbidden, state_keys)


def test_module_level_facades(tmp_path: Path):
    env, _pool = _env(tmp_path)
    state = env.reset("ep::a00")
    assert available_actions(state, env=env) == env.available_actions(state)
    assert available_actions(state) == state.available_actions
    action = next(a for a in state.available_actions if a.startswith("U_MOVE:"))
    new_state, cost, done = step(env, action, state)
    assert cost["seconds"] > 0 and new_state.step == 1


def test_declared_accessories_add_reachable_actions(tmp_path: Path):
    store, _specs = build_two_event_store(tmp_path)
    report = build_pool(store, None, PoolConfig(pool_id="ep_pool2", size_target=100,
                                                query_per_mother=1))
    pool = report["pool"]
    from synlab.cameras.api import camera_profiles

    profiles = []
    for profile in camera_profiles():
        profile = profile.__class__(**{**profile.__dict__})
        meta = dict(profile.meta)
        meta["declared_actions"] = ["light"]
        if profile.tier == "MID":
            meta["turntable"] = {"azimuth_step_deg": 15, "max_steps": 2, "step_seconds": 5.0}
        profile.meta = meta
        profiles.append(profile)
    env = EpisodeEnv(store, pool, profiles, budget={"max_actions": 3, "candidate_pool_size": 3},
                     scorer=_quality_scorer())
    actions = env.available_actions(env.reset("ep::a00"))
    assert any(a.startswith("TOGGLE_LIGHT:") for a in actions)
    assert any(a.startswith("ADD_AZIMUTH:") for a in actions)
    assert not any(a.startswith("TOGGLE_POLARIZATION:") for a in actions)
