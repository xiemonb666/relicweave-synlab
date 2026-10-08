"""Rule baselines for the active-observation episode (plan 17.2).

Legal rule baselines (they read the already revealed observation and the declared camera
catalogue only):

``uniform_capture``
    round-robin over the declared reachable actions (equal budget per action);
``coverage_first``
    prefer an action whose declared view kind/tier is not represented yet among the revealed
    views (adds missing azimuth/elevation/local coverage before re-shooting the same view);
``single_step_quality``
    pick the declared single-step quality proxy of the highest quality tier still missing;
``greedy_gain_cost``
    greedy predicted gain / cost -- the predictor must be learned on train/dev; this checkout
    has no trained gain predictor, so the declared OBS_EST quality proxy is used and the run is
    explicitly labelled ``UNLEARNED_GAIN_PROXY``;
``stop_only``
    take STOP at once (the "never capture more" baseline).

Picking an action by its **ground-truth** coverage gain is ``ORACLE_ACTION``: it is exposed by
:func:`oracle_action` and is never part of :func:`legal_baselines`.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from .env import KIND_STOP, STOP_ACTION, EpisodeEnv

BASELINE_VERSION = "episodes.baselines.v1"

#: Legal rule baselines (``ORACLE_ACTION`` is deliberately absent).
BASELINE_NAMES: tuple[str, ...] = (
    "uniform_capture", "coverage_first", "single_step_quality", "greedy_gain_cost", "stop_only",
)

ORACLE_TAG = "ORACLE_ACTION"

#: Quality proxy used by the unlearned greedy baseline (declared, not fitted).
GAIN_PROXY_NOTE = ("UNLEARNED_GAIN_PROXY: no train/dev observation-gain predictor is available "
                   "in this checkout, so the declared single-step quality/cost proxy is used")


def legal_baselines() -> tuple[str, ...]:
    return BASELINE_NAMES


def assert_baseline_legal(name: str) -> None:
    if name not in BASELINE_NAMES:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{name!r} is not a legal rule baseline; ORACLE_ACTION may never be "
                          f"listed as one (plan 17.2)",
                          stage="episodes.assert_baseline_legal",
                          evidence_refs=list(BASELINE_NAMES))


# --------------------------------------------------------------------------------------
# declared observables used by the policies (no GT, no reward)
# --------------------------------------------------------------------------------------
def observable_action_features(env: EpisodeEnv, state: Any, action_id: str) -> dict[str, Any]:
    """Legal, declared action features (cost, tier, view kind, novelty) -- no GT."""
    spec = env.action_catalogue().get(action_id)
    if spec is None:
        return {}
    revealed_kinds = {view.split("#", 1)[0] for view in state.revealed_views}
    novelty = 0.0 if action_id in revealed_kinds else 1.0
    return {
        "action_id": action_id,
        "kind": spec.kind,
        "tier": spec.tier,
        "view_kind": spec.view_kind,
        "cost_seconds": float(spec.cost_seconds),
        "frames": int(spec.frames),
        "novelty": novelty,
        "declared_by": spec.declared_by,
    }


def _candidates(env: EpisodeEnv, state: Any) -> list[str]:
    """Legal action candidates as declared to the policy (the state carries the list)."""
    declared = list(getattr(state, "available_actions", []) or [])
    actions = declared if declared else env.available_actions(state)
    return [a for a in actions if a != STOP_ACTION]


def _quality_proxy(env: EpisodeEnv, state: Any, action_id: str) -> float:
    """Declared single-step quality proxy (higher is better); never a GT quantity."""
    spec = env.action_catalogue().get(action_id)
    if spec is None:
        return 0.0
    tier_score = {"LOCAL": 1.0, "MID": 0.6, "GLOBAL": 0.3}.get(str(spec.tier), 0.4)
    kind_score = {"local_fracture": 1.0, "rgb": 0.6, "light": 0.5, "polarization": 0.55}.get(
        str(spec.view_kind), 0.5)
    novelty = observable_action_features(env, state, action_id)["novelty"]
    return 0.7 * tier_score + 0.2 * kind_score + 0.1 * novelty


# --------------------------------------------------------------------------------------
# policies
# --------------------------------------------------------------------------------------
def select_action(env: EpisodeEnv, state: Any, name: str, *,
                  counters: dict[str, int] | None = None) -> str:
    """Deterministic action choice of one legal baseline (``STOP`` when nothing helps)."""
    assert_baseline_legal(name)
    candidates = _candidates(env, state)
    if name == "stop_only" or not candidates:
        return STOP_ACTION
    if name == "uniform_capture":
        counters = counters if counters is not None else {}
        index = int(counters.get("uniform", 0)) % len(candidates)
        counters["uniform"] = index + 1
        return candidates[index]
    if name == "coverage_first":
        ranked = sorted(candidates,
                        key=lambda a: (-observable_action_features(env, state, a)["novelty"], a))
        best = ranked[0]
        if observable_action_features(env, state, best)["novelty"] <= 0.0:
            return STOP_ACTION                     # every view kind is already represented
        return best
    if name == "single_step_quality":
        ranked = sorted(candidates, key=lambda a: (-_quality_proxy(env, state, a), a))
        return ranked[0]
    if name == "greedy_gain_cost":
        def ratio(action_id: str) -> tuple[float, str]:
            feats = observable_action_features(env, state, action_id)
            cost = max(float(feats.get("cost_seconds", 0.0)), 1e-6)
            return (-_quality_proxy(env, state, action_id) / cost, action_id)

        return min(candidates, key=ratio)
    raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown baseline {name!r}",
                      stage="episodes.select_action")


def run_baseline(env: EpisodeEnv, name: str, *, episode_id: str | None = None,
                 max_steps: int | None = None, stop_when_no_gain: bool = False) -> dict[str, Any]:
    """Run one legal rule baseline and return its full trajectory (including STOP/failures)."""
    assert_baseline_legal(name)
    state = env.reset(episode_id or _episode_id(env))
    state.meta["policy"] = name
    steps: list[dict[str, Any]] = []
    counters: dict[str, int] = {}
    budget = int(max_steps if max_steps is not None else env.budget["max_actions"])
    while not state.done:
        if int(state.cumulative_cost.get("actions", 0)) >= budget:
            state.stop_reason = "BUDGET_ACTIONS"
            state.done = True
            break
        action = select_action(env, state, name, counters=counters)
        if action == STOP_ACTION:
            state, _cost, _done = env.stop(state)
            steps.append(dict(env.trace[-1]))
            break
        previous = len(steps)
        state, cost, done = env.step(action, state)
        steps.append(dict(env.trace[-1]))
        if stop_when_no_gain and len(steps) > previous and cost.get("delta_cov_recall") == 0.0 \
                and cost.get("no_new_evidence"):
            state, _cost, _done = env.stop(state)
            steps.append(dict(env.trace[-1]))
            break
    return _report(env, name, state, steps, legal=True)


def oracle_action(env: EpisodeEnv, state: Any) -> tuple[str, dict[str, Any]]:
    """``ORACLE_ACTION``: the action with the largest **GT** coverage gain (upper bound only)."""
    candidates = _candidates(env, state)
    best_action, best_gain, detail = STOP_ACTION, 0.0, {}
    for action_id in candidates:
        gain = env.gt_gain_if(state, action_id)
        if gain is None:
            continue
        detail[action_id] = float(gain)
        if float(gain) > best_gain + 1e-12:
            best_action, best_gain = action_id, float(gain)
    return best_action, {"tag": ORACLE_TAG, "gt_gain": best_gain, "per_action_gt_gain": detail,
                         "legal": False,
                         "note": "ORACLE_ACTION uses current GT coverage: it is an upper bound "
                                 "and may never be listed as a rule baseline"}


def run_oracle(env: EpisodeEnv, *, episode_id: str | None = None,
               max_steps: int | None = None) -> dict[str, Any]:
    """Oracle upper bound (marked ``ORACLE_ACTION``; excluded from the legal baseline set)."""
    state = env.reset(episode_id or _episode_id(env))
    state.meta["policy"] = ORACLE_TAG
    steps: list[dict[str, Any]] = []
    budget = int(max_steps if max_steps is not None else env.budget["max_actions"])
    while not state.done:
        if int(state.cumulative_cost.get("actions", 0)) >= budget:
            state.done, state.stop_reason = True, "BUDGET_ACTIONS"
            break
        action, detail = oracle_action(env, state)
        if action == STOP_ACTION:
            state, _cost, _done = env.stop(state)
            stop_step = dict(env.trace[-1])
            stop_step.update({"tag": ORACLE_TAG, "legal": False, "legal_baseline": False,
                              "per_action_gt_gain": detail.get("per_action_gt_gain", {})})
            steps.append(stop_step)
            break
        state, _cost, _done = env.step(action, state)
        step = dict(env.trace[-1])
        step.update(detail)
        step["legal_baseline"] = False
        steps.append(step)
    report = _report(env, ORACLE_TAG, state, steps, legal=False)
    report["tag"] = ORACLE_TAG
    return report


# --------------------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------------------
def _episode_id(env: EpisodeEnv) -> str:
    roster = getattr(env.pool, "roster", []) or []
    if roster:
        return f"ep::{roster[0].fragment_id}"
    lineup = getattr(env.pool, "lineup", []) or []
    return f"ep::{lineup[0]}" if lineup else "ep::unknown"


def _report(env: EpisodeEnv, name: str, state: Any, steps: Sequence[Mapping[str, Any]], *,
            legal: bool) -> dict[str, Any]:
    initial = list(state.meta.get("initial_pool", []))
    final = list(state.candidate_ids)
    neighbours = env._gt_neighbours(state.query_id)
    cov_initial = env._cov(initial, neighbours)
    cov_final = env._cov(final, neighbours)
    metrics = {
        "policy": name,
        "legal_baseline": bool(legal),
        "steps": len(steps),
        "actions": int(state.cumulative_cost.get("actions", 0)),
        "frames": int(state.cumulative_cost.get("frames", 0)),
        "seconds": float(state.cumulative_cost.get("seconds", 0.0)),
        "capture_seconds": float(state.cumulative_cost.get("capture_seconds", 0.0)),
        "inference_seconds": float(state.cumulative_cost.get("inference_seconds", 0.0)),
        "gt_cov_recall_initial": cov_initial,
        "gt_cov_recall_final": cov_final,
        "net_recall_gain": (None if cov_initial is None or cov_final is None
                            else cov_final - cov_initial),
        "wrong_to_right": sum(1 for s in steps if (s.get("net_recall_gain") or 0) > 0),
        "right_to_wrong": sum(1 for s in steps if (s.get("net_recall_gain") or 0) < 0),
        "unnecessary_actions": sum(1 for s in steps if s.get("pool_rerank_only")
                                   and not s.get("candidates_left")),
        "pool_rerank_only_steps": sum(1 for s in steps if s.get("pool_rerank_only")),
        "false_accept_events": int(sum(int(s.get("wrong_accept_after") or 0)
                                       for s in steps[-1:]) if steps else 0),
        "failed_steps": sum(1 for s in steps if s.get("failed")),
        "stop_reason": state.stop_reason or "RUNNING",
        "reward_total": float(sum(float(s.get("reward") or 0.0) for s in steps)),
        "reward_definition": "GT CovRecall gain - lambda_time * new seconds - lambda_risk * "
                             "new wrong acceptances (environment side only)",
        "gain_proxy": GAIN_PROXY_NOTE if name == "greedy_gain_cost" else None,
    }
    return {
        "baseline_version": BASELINE_VERSION,
        "policy": name,
        "legal_baseline": bool(legal),
        "episode_id": state.episode_id,
        "query_id": state.query_id,
        "pool_id": str(getattr(env.pool, "pool_id", "")),
        "gallery_hash": str(getattr(env.pool, "hash", "")),
        "steps": [dict(step) for step in steps],
        "final_state": {
            "step": state.step, "obs_version": state.obs_version,
            "candidate_ids": list(state.candidate_ids),
            "revealed_views": list(state.revealed_views),
            "cumulative_cost": dict(state.cumulative_cost),
            "done": bool(state.done), "stop_reason": state.stop_reason,
            "available_actions": list(state.available_actions),
        },
        "costs": dict(state.cumulative_cost),
        "metrics": metrics,
        "trace_hash": env.trace_report(policy=name)["trace_hash"],
    }


__all__ = [
    "BASELINE_VERSION", "BASELINE_NAMES", "ORACLE_TAG", "GAIN_PROXY_NOTE", "legal_baselines",
    "assert_baseline_legal", "observable_action_features", "select_action", "run_baseline",
    "oracle_action", "run_oracle",
]
