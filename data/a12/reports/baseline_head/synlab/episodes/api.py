"""Episodes façade: ``run_episode_config(store, config_path)`` (plan 17, 30.14).

The configuration file is the pool/gallery document (``synlab.pool.v1``) optionally extended
with episode keys::

    baselines: [uniform_capture, coverage_first, single_step_quality, greedy_gain_cost, stop_only]
    budget: {max_actions: 6, max_seconds: 600, candidate_pool_size: 50}
    episode_queries: [fragment_id, ...]      # default: the frozen roster
    cameras: {accessories: [light, polarization], turntable: {azimuth_step_deg: 15}}
    oracle: true                             # report the ORACLE_ACTION upper bound separately

All failures and STOP trajectories are kept; ``ORACLE_ACTION`` is reported apart from the
legal baselines and can never be listed among them.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..roles import FRAME_WORLD, ROLE_EPISODE, SCHEMA_EPISODE, UNIT_NONE
from .baselines import (
    BASELINE_NAMES,
    ORACLE_TAG,
    assert_baseline_legal,
    run_baseline,
    run_oracle,
)
from .env import ENV_VERSION, STOP_ACTION, EpisodeEnv, load_episode_config

API_VERSION = "synlab.episodes.api.v1"


def _default_cameras(config: Mapping[str, Any]) -> list[Any]:
    from ..cameras.api import camera_profiles

    profiles = [copy.deepcopy(profile) for profile in camera_profiles()]
    declared = dict(config.get("cameras") or {})
    accessories = [str(a) for a in (declared.get("accessories") or [])]
    turntable = dict(declared.get("turntable") or {})
    for profile in profiles:
        meta = dict(getattr(profile, "meta", {}) or {})
        actions = set(meta.get("declared_actions") or [])
        actions.update(accessories)
        if actions:
            meta["declared_actions"] = sorted(actions)
        if turntable and str(getattr(profile, "tier", "")) in ("GLOBAL", "MID"):
            meta["turntable"] = turntable
        profile.meta = meta
    return profiles


def resolve_episode_pool(store: Any, config: Mapping[str, Any],
                         config_path: str | Path) -> tuple[Any, dict[str, Any]]:
    """Resolve the frozen pool: portable artifact first, otherwise build it for real."""
    from ..relations.api import PoolConfig, build_pool, load_pool_json, save_pool_json
    from ..relations.gallery import attach_features

    pool_id = str(config.get("pool_id") or "pool")
    artifact = Path(store.root) / "pools" / f"{pool_id}.json"
    resolution: dict[str, Any] = {"pool_id": pool_id, "artifact": str(artifact)}
    if artifact.exists():
        pool, _rows = load_pool_json(artifact)
        resolution["source"] = "portable_json"
    else:
        # build from the store; the episode document is a superset of the pool document, so
        # only the pool keys are handed to PoolConfig (and no config file is rewritten)
        resolution["source"] = "build"
        known = set(PoolConfig.__dataclass_fields__)
        pool_keys = {key: value for key, value in config.items() if key in known}
        pool_config = PoolConfig.from_mapping(pool_keys)
        report = build_pool(store, str(config.get("release") or "sandbox"), pool_config,
                            with_features=True)
        if not report.get("ok"):
            raise SynLabError(
                ErrorCode.INPUT_UNAVAILABLE,
                f"no frozen pool for {pool_id!r}: {report.get('error', {}).get('message', '')}",
                stage="episodes.run_episode_config",
                measurements={"pool_id": pool_id, "status": report.get("status")})
        pool = report["pool"]
        save_pool_json(pool, artifact)
        resolution["build_status"] = report.get("status")
    if store is not None:
        attach_features(pool, store)
    resolution["fragments"] = len(getattr(pool, "lineup", []) or [])
    resolution["features"] = len(getattr(pool, "features", {}) or {})
    resolution["hash"] = str(getattr(pool, "hash", ""))
    return pool, resolution


def run_episode_config(store: Any, config_path: str | Path, *, episode_id: str | None = None,
                       cameras: Any = None, max_steps: int | None = None,
                       write_asset: bool = True) -> dict[str, Any]:
    """Run the legal rule baselines (and the oracle upper bound) over one frozen pool."""
    config = load_episode_config(config_path)
    baselines = [str(b) for b in (config.get("baselines") or BASELINE_NAMES)]
    for name in baselines:
        assert_baseline_legal(name)
    if ORACLE_TAG in baselines:
        raise SynLabError(ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION,
                          f"{ORACLE_TAG} may never be listed as a rule baseline",
                          stage="episodes.run_episode_config")
    budget = {key: value for key, value in dict(config.get("budget") or {}).items()
              if key in ("max_actions", "max_seconds", "candidate_pool_size")}
    pool, resolution = resolve_episode_pool(store, config, config_path)
    features = getattr(pool, "features", None) or {}
    if not features:
        raise SynLabError(
            ErrorCode.INPUT_UNAVAILABLE,
            f"pool {resolution['pool_id']!r} carries no legal observation payloads; an episode "
            f"cannot be scored without revealed observations",
            stage="episodes.run_episode_config",
            measurements=resolution)
    query = str(config.get("episode_query") or episode_id or "")
    if not query:
        roster = getattr(pool, "roster", []) or []
        lineup = [f for f in (getattr(pool, "lineup", []) or []) if f in features]
        query = (roster[0].fragment_id if roster else (lineup[0] if lineup else ""))
    episode = episode_id or f"ep::{query}"
    env_cameras = cameras if cameras is not None else _default_cameras(config)
    env = EpisodeEnv(store, pool, env_cameras,
                     budget=budget or None,
                     seed=int((config.get("seeds") or [20261001])[0]
                              if isinstance(config.get("seeds"), (list, tuple))
                              else config.get("seed", 20261001)))

    runs: list[dict[str, Any]] = []
    for name in baselines:
        runs.append(run_baseline(env, name, episode_id=episode, max_steps=max_steps))
    oracle = None
    if bool(config.get("oracle", True)):
        oracle = run_oracle(env, episode_id=episode, max_steps=max_steps)

    steps: list[dict[str, Any]] = []
    costs: dict[str, Any] = {}
    stop_reasons: dict[str, int] = {}
    metrics: dict[str, Any] = {}
    for run in runs:
        policy = str(run["policy"])
        for step in run["steps"]:
            steps.append({**step, "policy": policy,
                          "legal_baseline": bool(run["legal_baseline"])})
        costs[policy] = dict(run["costs"])
        reason = str(run["metrics"].get("stop_reason", "RUNNING"))
        stop_reasons[reason] = stop_reasons.get(reason, 0) + 1
        metrics[policy] = dict(run["metrics"])
    if oracle is not None:
        for step in oracle["steps"]:
            steps.append({**step, "policy": ORACLE_TAG, "legal_baseline": False})
        costs[ORACLE_TAG] = dict(oracle["costs"])
        reason = str(oracle["metrics"].get("stop_reason", "RUNNING"))
        stop_reasons[reason] = stop_reasons.get(reason, 0) + 1
        metrics[ORACLE_TAG] = dict(oracle["metrics"])

    legal_metrics = [m for name, m in metrics.items() if name in BASELINE_NAMES]
    best = max((m for m in legal_metrics if m.get("net_recall_gain") is not None),
               key=lambda m: float(m.get("net_recall_gain") or 0.0), default=None)
    summary = {
        "api_version": API_VERSION,
        "env_version": ENV_VERSION,
        "pool_id": resolution["pool_id"],
        "gallery_hash": resolution.get("hash", ""),
        "query_id": query,
        "episode_id": episode,
        "baselines": baselines,
        "legal_baselines": list(BASELINE_NAMES),
        "oracle_reported_separately": oracle is not None,
        "steps_total": len(steps),
        "steps_by_policy": {name: int(m.get("steps", 0)) for name, m in metrics.items()},
        "seconds_total": float(sum(float(c.get("seconds", 0.0)) for c in costs.values())),
        "frames_total": int(sum(int(c.get("frames", 0)) for c in costs.values())),
        "best_legal_policy": (best or {}).get("policy"),
        "net_recall_gain_best_legal": (best or {}).get("net_recall_gain"),
        "oracle_net_recall_gain": (metrics.get(ORACLE_TAG, {}) or {}).get("net_recall_gain"),
        "oracle_tag": ORACLE_TAG,
        "oracle_excluded_from_baselines": ORACLE_TAG not in baselines,
        "pool_rerank_only_steps": int(sum(int(m.get("pool_rerank_only_steps", 0))
                                          for m in metrics.values())),
        "failed_steps": int(sum(int(m.get("failed_steps", 0)) for m in metrics.values())),
        "stop_closed": all(bool(m.get("stop_reason")) for m in metrics.values()),
    }
    report = {
        "ok": bool(runs) and summary["stop_closed"],
        "status": "QA_PASSED" if (runs and summary["stop_closed"]) else "FAILED",
        "steps": steps,
        "costs": costs,
        "stop_reasons": stop_reasons,
        "metrics": summary,
        "policy_metrics": metrics,
        "runs": runs,
        "oracle": oracle,
        "pool": resolution,
        "config": {"path": str(config_path), "pool_id": resolution["pool_id"],
                   "baselines": baselines, "budget": budget,
                   "hash": hash_json(_jsonable({k: v for k, v in config.items()
                                                if k != "config_path"}))},
    }
    if store is not None and write_asset:
        report["trace_asset_id"] = commit_episode(store, report, query=query)
    return report


def commit_episode(store: Any, report: Mapping[str, Any], *, query: str,
                   ancestry: Sequence[str] = ()) -> str:
    slim = {k: v for k, v in report.items() if k not in ("runs", "oracle")}
    asset = store.commit_asset(
        role=ROLE_EPISODE, schema=SCHEMA_EPISODE, unit=UNIT_NONE, frame=FRAME_WORLD,
        payload={},
        meta={"episode_id": slim.get("metrics", {}).get("episode_id"),
              "pool_id": slim.get("metrics", {}).get("pool_id"),
              "query_id": query, "steps": len(slim.get("steps", [])),
              "stop_reasons": _jsonable(slim.get("stop_reasons", {})),
              "costs": _jsonable(slim.get("costs", {})),
              "metrics": _jsonable(slim.get("metrics", {})),
              "trace_json": json.dumps(_jsonable(slim.get("steps", [])), ensure_ascii=False,
                                       default=str)},
        qa={"ok": bool(report.get("ok")), "oracle_excluded": True, "stop_closed":
            bool(slim.get("metrics", {}).get("stop_closed"))},
        ancestry=list(ancestry), split="dev")
    return asset.asset_id


def _jsonable(value: Any) -> Any:
    import numpy as np

    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = ["API_VERSION", "run_episode_config", "resolve_episode_pool", "commit_episode",
           "STOP_ACTION"]
