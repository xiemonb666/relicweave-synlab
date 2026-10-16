"""Active-observation episodes: environment, rule baselines and the trace façade.

Public entry points (``docs/a12/interfaces.md`` §2):

``synlab.episodes`` / ``synlab.episodes.api``
    :class:`EpisodeEnv`, :func:`available_actions`, :func:`step`, :func:`run_episode_config`.
"""

from __future__ import annotations

from .api import API_VERSION, commit_episode, resolve_episode_pool, run_episode_config
from .baselines import (
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
from .env import (
    ENV_VERSION,
    STOP_ACTION,
    ActionSpec,
    EpisodeEnv,
    available_actions,
    load_episode_config,
    step,
)

__all__ = [
    "API_VERSION", "ENV_VERSION", "STOP_ACTION", "ActionSpec", "EpisodeEnv",
    "available_actions", "step", "load_episode_config", "run_episode_config",
    "resolve_episode_pool", "commit_episode", "BASELINE_NAMES", "ORACLE_TAG",
    "legal_baselines", "assert_baseline_legal", "observable_action_features", "select_action",
    "run_baseline", "oracle_action", "run_oracle",
]
