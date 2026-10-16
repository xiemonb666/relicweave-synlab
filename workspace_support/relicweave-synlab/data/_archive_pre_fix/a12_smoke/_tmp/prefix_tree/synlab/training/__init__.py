"""A12 pretraining module: input adapter, dual-tower model, five task losses, trainer.

Public façade in :mod:`synlab.training.api`; the tensor contract is frozen in
:mod:`synlab.training.adapter` and documented in
``docs/a12/training_diagnostics_episodes.md``.

Integration points that are still pending (parallel development, not imported here):

* ``synlab.observe.api.adapt_observed_features`` -> ``FeatureBundle.from_dict``
* ``synlab.relations.api.build_pool`` / ``sample_training_batch`` -> ``sampler.PoolIndex``
"""

from __future__ import annotations

from .adapter import FEATURE_SCHEMA, TOKEN_DIM, FeatureBundle, TorchFeatureBundle
from .batch import TrainingBatch, build_training_batch, negative_audit
from .losses import DEFAULT_WEIGHTS, MultiTaskLoss
from .model import DualTowerModel, FragmentEncoder, PairRefineHead, build_model
from .sampler import LineageBalancedSampler, PoolIndex, ShardedIterableDataset, augmentation_rng
from .trainer import REPRODUCIBILITY_LEVEL, CurriculumSchedule, Trainer

__all__ = [
    "FEATURE_SCHEMA", "TOKEN_DIM", "FeatureBundle", "TorchFeatureBundle",
    "TrainingBatch", "build_training_batch", "negative_audit",
    "DEFAULT_WEIGHTS", "MultiTaskLoss",
    "FragmentEncoder", "PairRefineHead", "DualTowerModel", "build_model",
    "PoolIndex", "LineageBalancedSampler", "ShardedIterableDataset", "augmentation_rng",
    "Trainer", "CurriculumSchedule", "REPRODUCIBILITY_LEVEL",
]
