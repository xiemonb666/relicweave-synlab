"""Relation pools, gallery construction, training sampling and hard-negative mining.

Public entry points (see ``docs/a12/relations_diagnostics_episodes.md``):

``synlab.relations.api``
    :func:`build_pool`, :func:`build_pool_from_config`, :func:`sample_training_batch`,
    :func:`mine_hard_negatives`, :func:`commit_pool`, :func:`load_pool`.
"""

from __future__ import annotations

from .api import (
    API_VERSION,
    PoolConfig,
    build_pool,
    build_pool_from_config,
    commit_pool,
    commit_roster,
    load_pool,
    load_pool_json,
    load_roster_json,
    mine_hard_negatives,
    pool_from_asset,
    sample_training_batch,
    save_pool_json,
    save_roster_json,
)
from .gallery import (
    FragmentRecord,
    RelationPool,
    RelationsIndex,
    attach_features,
    collect_fragments,
)
from .sampler import HARD_GROUPS, new_sampler_state

__all__ = [
    "API_VERSION", "PoolConfig", "build_pool", "build_pool_from_config", "sample_training_batch",
    "mine_hard_negatives", "commit_pool", "commit_roster", "load_pool", "load_pool_json",
    "load_roster_json", "pool_from_asset", "save_pool_json", "save_roster_json",
    "FragmentRecord", "RelationPool", "RelationsIndex", "attach_features", "collect_fragments",
    "HARD_GROUPS", "new_sampler_state",
]
