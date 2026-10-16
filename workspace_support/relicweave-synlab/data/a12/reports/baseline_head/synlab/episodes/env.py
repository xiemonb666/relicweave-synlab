"""Active-observation episode environment (plan 17.1, 17.2, 30.14).

``EpisodeEnv(store, pool, cameras=None)``

* ``reset(episode_id) -> EpisodeState`` reveals **only** the initial observation;
* ``available_actions(state)`` lists the actions the camera profile actually declares
  reachable -- an arbitrary camera teleport is never a free action;
* ``step(action) -> (state, cost, done)`` re-checks the **entire fixed gallery**; only
  re-ranking the original pool is labelled ``POOL_RERANK_ONLY`` and never counted as
  candidate recovery.  Images of actions that were not selected never enter the state;
* ``stop()`` closes the episode; a stopped episode rejects further actions.

The environment may use ground truth to compute the offline reward (it is written to the
environment-side trace only); the state carries observable information alone and never a
reward, a GT label or a success flag.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import EpisodeState

ENV_VERSION = "episodes.env.v1"

STOP_ACTION = "STOP"

#: Action kinds the rig may declare.
KIND_STOP = "STOP"
KIND_U_MOVE = "U_MOVE"
KIND_LOCAL_FRAME = "LOCAL_FRACTURE_FRAME"
KIND_AZIMUTH = "ADD_AZIMUTH"
KIND_ELEVATION = "ADD_ELEVATION"
KIND_LIGHT = "TOGGLE_LIGHT"
KIND_POLARIZATION = "TOGGLE_POLARIZATION"
KIND_RECLAMP = "RECLAMP_FLIP"

#: Accessories an action needs the profile/rig to declare (otherwise it is unreachable).
DECLARED_ACTION_KEYS = {
    KIND_LIGHT: ("declared_actions", "light"),
    KIND_POLARIZATION: ("declared_actions", "polarization"),
    KIND_RECLAMP: ("declared_actions", "reclamp"),
}

DEFAULT_BUDGET = {"max_actions": 6, "max_seconds": 600.0, "candidate_pool_size": 50}


@dataclass(frozen=True)
class ActionSpec:
    """One reachable action with its declared cost and provenance."""

    action_id: str
    kind: str
    cost_seconds: float
    frames: int = 1
    profile_id: str = ""
    tier: str = ""
    u_position_mm: float | None = None
    declared_by: str = ""
    view_kind: str = "rgb"
    requires: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"action_id": self.action_id, "kind": self.kind,
                "cost_seconds": float(self.cost_seconds), "frames": int(self.frames),
                "profile_id": self.profile_id, "tier": self.tier,
                "u_position_mm": self.u_position_mm, "declared_by": self.declared_by,
                "view_kind": self.view_kind, "requires": list(self.requires)}


class EpisodeEnv:
    """Environment over one frozen gallery and one query at a time."""

    def __init__(self, store: Any, pool: Any, cameras: Any = None, *,
                 scorer: Any = None, observer: Callable[..., Any] | None = None,
                 budget: Mapping[str, Any] | None = None, seed: int = 20261001,
                 reward_weights: Mapping[str, float] | None = None) -> None:
        self.store = store
        self.pool = pool
        self.cameras = cameras if cameras is not None else _default_cameras()
        self.budget = {**DEFAULT_BUDGET, **dict(budget or {})}
        self.seed = int(seed)
        self.reward_weights = {"lambda_time": 1.0 / 600.0, "lambda_risk": 1.0,
                               **dict(reward_weights or {})}
        self.scorer = scorer if scorer is not None else _default_scorer(pool)
        self.observer = observer if observer is not None else self._store_observer
        self.state: EpisodeState | None = None
        self.trace: list[dict[str, Any]] = []
        self._encodings: dict[str, np.ndarray] = {}
        self._valid: dict[str, bool] = {}
        self._initial_pool: list[str] = []
        self._gt_cache: dict[str, float] = {}

    # ------------------------------------------------------------------ internals
    @property
    def features(self) -> dict[str, dict]:
        return getattr(self.pool, "features", {}) or {}

    def _encode(self, payloads: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, np.ndarray],
                                                                        dict[str, bool]]:
        return self.scorer.encode(payloads)

    def _scores(self, query: str) -> dict[str, float]:
        if not self._encodings:
            payloads = self.features
            vectors, valid = self._encode(payloads)
            self._encodings, self._valid = vectors, valid
        if query not in self._encodings:
            return {}
        q = self._encodings[query]
        return {str(cid): float(np.dot(q, vec)) for cid, vec in self._encodings.items()
                if cid != query}

    def _rank(self, query: str) -> list[str]:
        scores = self._scores(query)
        return sorted(scores, key=lambda cid: (-float(scores[cid]), str(cid)))

    def _pool_size(self) -> int:
        return max(1, min(int(self.budget["candidate_pool_size"]),
                          max(1, len(getattr(self.pool, "lineup", []) or [1]))))

    def _gt_neighbours(self, query: str) -> list[str]:
        try:
            return [n for n in self.pool.neighbours(query) if n != query]
        except Exception:  # noqa: BLE001 - a pool without neighbours cannot score GT
            return []

    def gt_cov_recall(self, state: EpisodeState) -> float | None:
        """Environment-side GT coverage of the full ``N_G(q)`` by the current candidates."""
        neighbours = self._gt_neighbours(state.query_id)
        if not neighbours:
            return None
        hit = len([c for c in state.candidate_ids if c in set(neighbours)])
        return hit / float(len(neighbours))

    # ------------------------------------------------------------------ action catalogue
    def action_catalogue(self) -> dict[str, ActionSpec]:
        specs: dict[str, ActionSpec] = {
            STOP_ACTION: ActionSpec(action_id=STOP_ACTION, kind=KIND_STOP, cost_seconds=0.0,
                                    frames=0, declared_by="environment")}
        for profile in self._profiles():
            meta = dict(getattr(profile, "meta", {}) or {})
            travel = meta.get("u_travel_mm") or _travel_from(profile)
            step_mm = float(meta.get("u_step_mm", 0.0) or 0.0)
            if travel and step_mm > 0:
                lo, hi = float(travel[0]), float(travel[1])
                n_steps = int(round((hi - lo) / step_mm))
                for index in range(n_steps + 1):
                    u = lo + index * step_mm
                    if abs(u - float(getattr(profile, "u_position_mm", 0.0))) < 1e-9:
                        continue
                    action_id = f"{KIND_U_MOVE}:{profile.profile_id}@{u:+.0f}mm"
                    specs[action_id] = ActionSpec(
                        action_id=action_id, kind=KIND_U_MOVE,
                        cost_seconds=float(getattr(profile, "action_cost_seconds", 0.0) or 0.0),
                        profile_id=str(profile.profile_id), tier=str(getattr(profile, "tier", "")),
                        u_position_mm=float(u), declared_by=f"profile:{profile.profile_id}",
                        requires=("u_travel_mm", "u_step_mm"))
            declared = {str(a) for a in (meta.get("declared_actions") or [])}
            if str(getattr(profile, "tier", "")) == "LOCAL":
                specs[f"{KIND_LOCAL_FRAME}:{profile.profile_id}"] = ActionSpec(
                    action_id=f"{KIND_LOCAL_FRAME}:{profile.profile_id}",
                    kind=KIND_LOCAL_FRAME,
                    cost_seconds=float(getattr(profile, "action_cost_seconds", 0.0) or 0.0) + 3.0,
                    profile_id=str(profile.profile_id), tier="LOCAL",
                    declared_by=f"profile:{profile.profile_id}",
                    view_kind="local_fracture", requires=("tier", "depth_of_field_mm"))
            turntable = dict(meta.get("turntable") or {})
            if turntable:
                for kind, key, unit in ((KIND_AZIMUTH, "azimuth_step_deg", "deg"),
                                        (KIND_ELEVATION, "elevation_step_deg", "deg")):
                    step = float(turntable.get(key, 0.0) or 0.0)
                    if step <= 0:
                        continue
                    limit = int(turntable.get("max_steps", 4) or 4)
                    for index in range(1, limit + 1):
                        action_id = f"{kind}:{profile.profile_id}@{index * step:+.0f}{unit}"
                        specs[action_id] = ActionSpec(
                            action_id=action_id, kind=kind,
                            cost_seconds=float(turntable.get("step_seconds", 6.0) or 6.0),
                            profile_id=str(profile.profile_id), tier=str(profile.tier),
                            declared_by=f"profile:{profile.profile_id}:turntable",
                            requires=("turntable", key))
            for kind, (meta_key, access) in DECLARED_ACTION_KEYS.items():
                if access in declared:
                    specs[f"{kind}:{profile.profile_id}"] = ActionSpec(
                        action_id=f"{kind}:{profile.profile_id}", kind=kind,
                        cost_seconds=float(meta.get("accessory_seconds", 8.0) or 8.0),
                        profile_id=str(profile.profile_id), tier=str(profile.tier),
                        declared_by=f"profile:{profile.profile_id}:declared_actions",
                        view_kind=access, requires=(f"{meta_key}={access}",))
        return specs

    def _profiles(self) -> list[Any]:
        cameras = self.cameras
        if cameras is None:
            return []
        if isinstance(cameras, Mapping):
            return list(cameras.get("profiles") or [])
        return list(cameras)

    def available_actions(self, state: EpisodeState) -> list[str]:
        """Only actions the camera profile declares reachable, plus ``STOP``."""
        if state.done:
            return [STOP_ACTION]
        catalogue = self.action_catalogue()
        available = [STOP_ACTION]
        for action_id, spec in catalogue.items():
            if action_id == STOP_ACTION:
                continue
            if spec.kind == KIND_U_MOVE and spec.u_position_mm is not None:
                if abs(spec.u_position_mm - self._current_u()) < 1e-9:
                    continue
            available.append(action_id)
        return sorted(set(available), key=lambda a: (a != STOP_ACTION, a))

    def _current_u(self) -> float:
        for profile in self._profiles():
            meta = dict(getattr(profile, "meta", {}) or {})
            if meta.get("u_position_mm") is not None:
                return float(meta["u_position_mm"])
            if getattr(profile, "u_position_mm", None) is not None:
                return float(profile.u_position_mm)
        return float("nan")

    # ------------------------------------------------------------------ observation
    def _store_observer(self, query: str, state: EpisodeState, action: ActionSpec
                        ) -> dict[str, Any] | None:
        """Default re-observation: a later committed observation of the same query, if any.

        The environment never invents pixels.  When no later observation exists the action is
        still charged and the gallery is re-checked with the evidence actually revealed.
        """
        return None

    def _view_id(self, action: ActionSpec, obs_version: int) -> str:
        return f"{action.action_id}#v{obs_version}"

    def _initial_views(self, query: str) -> list[str]:
        payload = self.features.get(query) or {}
        views = payload.get("view_ids")
        if isinstance(views, (list, tuple)) and views:
            return [str(v) for v in views]
        tokens = payload.get("view_tokens")
        count = int(np.asarray(tokens).shape[0]) if tokens is not None else 0
        return [f"initial#v0#{i}" for i in range(count)]

    # ------------------------------------------------------------------ reset
    def reset(self, episode_id: str) -> EpisodeState:
        query = self._resolve_query(episode_id)
        self._encodings, self._valid = {}, {}
        ranked = self._rank(query)
        candidate_ids = ranked[: self._pool_size()]
        self._initial_pool = list(candidate_ids)
        self.trace = []
        state = EpisodeState(
            episode_id=str(episode_id), query_id=query, step=0, obs_version=0,
            revealed_views=self._initial_views(query), candidate_ids=candidate_ids,
            cumulative_cost={"seconds": 0.0, "capture_seconds": 0.0, "manual_seconds": 0.0,
                             "inference_seconds": 0.0, "frames": 0, "actions": 0},
            done=False, stop_reason=None, available_actions=[],
            meta={"pool_id": str(getattr(self.pool, "pool_id", "")),
                  "gallery_hash": str(getattr(self.pool, "hash", "")),
                  "gallery_size": len(getattr(self.pool, "lineup", []) or []),
                  "initial_pool": list(candidate_ids),
                  "scorer": self.scorer.describe() if hasattr(self.scorer, "describe") else {},
                  "env_version": ENV_VERSION,
                  "policy": None,
                  "budget": dict(self.budget),
                  "no_ground_truth": True})
        state.available_actions = self.available_actions(state)
        self.state = state
        return state

    def _resolve_query(self, episode_id: str) -> str:
        text = str(episode_id)
        for prefix in ("ep::", "q::", "episode::"):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        lineup = [str(f) for f in (getattr(self.pool, "lineup", []) or [])]
        if text in lineup:
            return text
        roster = [q.fragment_id for q in (getattr(self.pool, "roster", []) or [])]
        if not lineup and not roster:
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, "the pool has no fragments to observe",
                              stage="episodes.EpisodeEnv.reset")
        pool_first = roster[0] if roster else lineup[0]
        if text not in lineup and text not in roster:
            return pool_first
        return text

    # ------------------------------------------------------------------ step
    def step(self, action: Any, state: EpisodeState | None = None
             ) -> tuple[EpisodeState, dict[str, Any], bool]:
        """Apply ``action``: re-check the whole gallery, return ``(state, cost, done)``."""
        current = state if state is not None else self.state
        if current is None:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              "episode has not been reset; call reset(episode_id) first",
                              stage="episodes.EpisodeEnv.step")
        if current.done:
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                f"episode {current.episode_id} has STOPPED ({current.stop_reason}); no further "
                f"action is accepted",
                stage="episodes.EpisodeEnv.step",
                measurements={"stop_reason": current.stop_reason, "step": current.step})
        action_id = str(action)
        catalogue = self.action_catalogue()
        if action_id not in catalogue:
            raise SynLabError(
                ErrorCode.TARGET_INFEASIBLE,
                f"action {action_id!r} is not declared by any camera profile; an arbitrary "
                f"camera teleport is not a legal action",
                stage="episodes.EpisodeEnv.step",
                evidence_refs=sorted(catalogue)[:12],
                measurements={"available_actions": self.available_actions(current)})
        spec = catalogue[action_id]
        if action_id not in self.available_actions(current):
            raise SynLabError(
                ErrorCode.TARGET_INFEASIBLE,
                f"action {action_id!r} is declared but not reachable in this state",
                stage="episodes.EpisodeEnv.step",
                measurements={"available_actions": self.available_actions(current)})
        if spec.kind == KIND_STOP:
            return self.stop(current)

        started = time.perf_counter()
        old_version = int(current.obs_version)
        old_candidates = list(current.candidate_ids)
        outcome = self.observer(current.query_id, current, spec) or {}
        payload = outcome.get("payload")
        if payload is not None:
            self._encodings.pop(current.query_id, None)
            vectors, valid = self._encode({current.query_id: payload})
            if valid.get(current.query_id):
                self._encodings[current.query_id] = vectors[current.query_id]
        new_version = int(outcome.get("obs_version", old_version + 1))
        inference_seconds = time.perf_counter() - started
        seconds = float(outcome.get("seconds", spec.cost_seconds) or 0.0)
        new_views = [str(v) for v in (outcome.get("views") or [self._view_id(spec, new_version)])]

        # full fixed-gallery re-check (plan 17.2)
        ranked = self._rank(current.query_id)
        new_candidates = ranked[: self._pool_size()]
        entered = [c for c in new_candidates if c not in old_candidates]
        left = [c for c in old_candidates if c not in new_candidates]
        rerank_only = not entered
        unavailable = self._valid and not self._valid.get(current.query_id, True)

        cumulative = dict(current.cumulative_cost)
        cumulative["seconds"] = float(cumulative.get("seconds", 0.0)) + seconds + inference_seconds
        cumulative["capture_seconds"] = float(cumulative.get("capture_seconds", 0.0)) + seconds
        cumulative["inference_seconds"] = (float(cumulative.get("inference_seconds", 0.0))
                                          + inference_seconds)
        cumulative["manual_seconds"] = float(cumulative.get("manual_seconds", 0.0))
        cumulative["frames"] = int(cumulative.get("frames", 0)) + int(spec.frames)
        cumulative["actions"] = int(cumulative.get("actions", 0)) + 1

        neighbours = self._gt_neighbours(current.query_id)
        gt_cov_before = self._cov(old_candidates, neighbours)
        gt_cov_after = self._cov(new_candidates, neighbours)
        risk_before = self._wrong_accepts(old_candidates, neighbours)
        risk_after = self._wrong_accepts(new_candidates, neighbours)
        penalty = (self.reward_weights["lambda_time"] * (seconds + inference_seconds)
                   + self.reward_weights["lambda_risk"] * max(0, risk_after - risk_before))
        reward = (gt_cov_after - gt_cov_before) - penalty if gt_cov_after is not None else None

        done_actions = int(cumulative["actions"]) >= int(self.budget["max_actions"])
        done_seconds = float(cumulative["seconds"]) >= float(self.budget["max_seconds"])
        done = bool(done_actions or done_seconds)
        stop_reason = ("BUDGET_ACTIONS" if done_actions else
                       ("BUDGET_TIME" if done_seconds else None))

        new_state = EpisodeState(
            episode_id=current.episode_id, query_id=current.query_id, step=current.step + 1,
            obs_version=new_version,
            revealed_views=list(current.revealed_views) + new_views,
            candidate_ids=new_candidates, cumulative_cost=cumulative, done=done,
            stop_reason=stop_reason,
            available_actions=[], meta=dict(current.meta))
        new_state.meta.update({
            "last_action": action_id,
            "last_action_kind": spec.kind,
            "no_new_evidence": payload is None,
            "unencodable_query": bool(unavailable),
            "pool_rerank_only": bool(rerank_only),
            "candidates_entered": entered,
            "candidates_left": left,
            "initial_pool_retained": len([c for c in old_candidates if c in new_candidates]),
        })
        new_state.available_actions = self.available_actions(new_state)
        if not done and new_state.available_actions == [STOP_ACTION]:
            new_state.done = True
            new_state.stop_reason = "NO_AVAILABLE_ACTION"
        self.state = new_state

        cost = {
            "seconds": seconds + inference_seconds,
            "capture_seconds": seconds,
            "inference_seconds": inference_seconds,
            "manual_seconds": 0.0,
            "frames": int(spec.frames),
            "risk_events": max(0, risk_after - risk_before),
            "delta_cov_recall": (None if gt_cov_after is None
                                 else gt_cov_after - gt_cov_before),
            "reward": reward,
            "cumulative": dict(cumulative),
            "action": spec.as_dict(),
        }
        self.trace.append({
            "episode_id": new_state.episode_id,
            "query_id": new_state.query_id,
            "policy": new_state.meta.get("policy"),
            "action_id": action_id,
            "action_kind": spec.kind,
            "old_obs_version": old_version,
            "new_obs_version": new_version,
            "revealed_views": new_views,
            "frames": int(spec.frames),
            "capture_seconds": seconds,
            "manual_seconds": 0.0,
            "inference_seconds": inference_seconds,
            "cost_seconds": cost["seconds"],
            "failed": bool(unavailable),
            "failure_code": ErrorCode.INPUT_UNAVAILABLE.value if unavailable else None,
            "no_new_evidence": payload is None,
            "pool_rerank_only": bool(rerank_only),
            "candidates_entered": entered,
            "candidates_left": left,
            "candidate_count": len(new_candidates),
            "gt_cov_recall_before": gt_cov_before,
            "gt_cov_recall_after": gt_cov_after,
            "net_recall_gain": cost["delta_cov_recall"],
            "wrong_accept_before": risk_before,
            "wrong_accept_after": risk_after,
            "reward": reward,
            "done": bool(new_state.done),
            "stop_reason": new_state.stop_reason,
            "environment_side_only": True,
        })
        return new_state, cost, bool(new_state.done)

    def stop(self, state: EpisodeState | None = None
             ) -> tuple[EpisodeState, dict[str, Any], bool]:
        """Close the episode; the STOP record is kept even when nothing was recovered."""
        current = state if state is not None else self.state
        if current is None:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "episode has not been reset",
                              stage="episodes.EpisodeEnv.stop")
        final = EpisodeState(
            episode_id=current.episode_id, query_id=current.query_id, step=current.step + 1,
            obs_version=int(current.obs_version), revealed_views=list(current.revealed_views),
            candidate_ids=list(current.candidate_ids),
            cumulative_cost=dict(current.cumulative_cost), done=True, stop_reason="STOP",
            available_actions=[STOP_ACTION], meta=dict(current.meta))
        final.meta["stopped_by"] = "policy"
        self.state = final
        cost = {"seconds": 0.0, "capture_seconds": 0.0, "inference_seconds": 0.0,
                "manual_seconds": 0.0, "frames": 0, "risk_events": 0, "delta_cov_recall": 0.0,
                "reward": 0.0, "cumulative": dict(final.cumulative_cost), "action": None}
        self.trace.append({
            "episode_id": final.episode_id, "query_id": final.query_id,
            "policy": final.meta.get("policy"), "action_id": STOP_ACTION,
            "action_kind": KIND_STOP, "old_obs_version": int(current.obs_version),
            "new_obs_version": int(current.obs_version), "revealed_views": [],
            "frames": 0, "capture_seconds": 0.0, "manual_seconds": 0.0,
            "inference_seconds": 0.0, "cost_seconds": 0.0, "failed": False,
            "failure_code": None, "no_new_evidence": True, "pool_rerank_only": False,
            "candidates_entered": [], "candidates_left": [], "candidate_count":
                len(final.candidate_ids),
            "gt_cov_recall_before": self.gt_cov_recall(final),
            "gt_cov_recall_after": self.gt_cov_recall(final), "net_recall_gain": 0.0,
            "wrong_accept_before": None, "wrong_accept_after": None, "reward": 0.0,
            "done": True, "stop_reason": "STOP", "environment_side_only": True,
        })
        return final, cost, True

    # ------------------------------------------------------------------ GT helpers
    @staticmethod
    def _cov(candidates: Sequence[str], neighbours: Sequence[str]) -> float | None:
        if not neighbours:
            return None
        return len([c for c in candidates if c in set(neighbours)]) / float(len(neighbours))

    @staticmethod
    def _wrong_accepts(candidates: Sequence[str], neighbours: Sequence[str]) -> int:
        return len([c for c in candidates if c not in set(neighbours)])

    def gt_gain_if(self, state: EpisodeState, action_id: str) -> float | None:
        """Oracle-side GT gain of one action (``ORACLE_ACTION`` only; never a legal policy)."""
        catalogue = self.action_catalogue()
        if action_id not in catalogue or action_id == STOP_ACTION:
            return 0.0
        saved = self._encodings.get(state.query_id)
        # The oracle evaluates the action by *simulating* the re-observation the rig declares.
        outcome = self.observer(state.query_id, state, catalogue[action_id]) or {}
        payload = outcome.get("payload")
        if payload is None:
            return 0.0
        vectors, valid = self._encode({state.query_id: payload})
        if not valid.get(state.query_id):
            return 0.0
        q = vectors[state.query_id]
        scores = {cid: float(np.dot(q, vec)) for cid, vec in self._encodings.items()
                  if cid != state.query_id}
        ranked = sorted(scores, key=lambda cid: (-scores[cid], cid))[: self._pool_size()]
        neighbours = self._gt_neighbours(state.query_id)
        before = self._cov(state.candidate_ids, neighbours)
        after = self._cov(ranked, neighbours)
        if before is None or after is None:
            return None
        return after - before

    # ------------------------------------------------------------------ trace export
    def trace_report(self, *, policy: str | None = None) -> dict[str, Any]:
        return {
            "env_version": ENV_VERSION,
            "policy": policy,
            "pool_id": str(getattr(self.pool, "pool_id", "")),
            "gallery_hash": str(getattr(self.pool, "hash", "")),
            "scorer": self.scorer.describe() if hasattr(self.scorer, "describe") else {},
            "steps": list(self.trace),
            "trace_hash": hash_json([{k: v for k, v in step.items() if k != "reward"}
                                     for step in self.trace]),
        }


# --------------------------------------------------------------------------------------
# module-level helpers (docs/a12/interfaces.md §2: available_actions / step façades)
# --------------------------------------------------------------------------------------
def _default_cameras() -> list[Any]:
    try:
        from ..cameras.api import camera_profiles

        return list(camera_profiles())
    except Exception:  # noqa: BLE001 - absent camera catalogue is recorded, not faked
        return []


def _default_scorer(pool: Any) -> Any:
    """Shallow observation baseline, chosen by the legal channels actually present."""
    from ..diagnostics.runner import ClassicalScorer

    features = getattr(pool, "features", None) or {}
    payload = next(iter(features.values()), {})
    if "quality" in payload and "presence" in payload and "global_rgb" in payload:
        mode = "shallow_fusion"
    elif "global_rgb" in payload:
        mode = "2d"
    else:
        mode = "3d"
    return ClassicalScorer(mode)


def _travel_from(profile: Any) -> tuple[float, float] | None:
    meta = dict(getattr(profile, "meta", {}) or {})
    travel = meta.get("u_travel_mm") or meta.get("u_allowed_range_mm")
    if travel and len(travel) == 2:
        return (float(travel[0]), float(travel[1]))
    return None


def available_actions(state: EpisodeState, *, env: EpisodeEnv | None = None) -> list[str]:
    """Module-level façade: requires an environment (``env=``) or a bound state."""
    environment = env or getattr(state, "meta", {}).get("_env")
    if environment is None:
        return list(state.available_actions) or [STOP_ACTION]
    return environment.available_actions(state)


def step(env: EpisodeEnv, action: Any, state: EpisodeState | None = None):
    """Module-level façade mirroring ``EpisodeEnv.step``."""
    return env.step(action, state)


def load_episode_config(path: str | Path) -> dict[str, Any]:
    from ..config import load_document

    document = load_document(path)
    config = {**dict(document), "config_path": str(path)}
    config.setdefault("budget", {})
    if not isinstance(config.get("budget"), Mapping):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "episode budget must be a mapping",
                          stage="episodes.load_episode_config")
    return config


__all__ = [
    "ENV_VERSION", "STOP_ACTION", "DEFAULT_BUDGET", "ActionSpec", "EpisodeEnv",
    "available_actions", "step", "load_episode_config",
]
