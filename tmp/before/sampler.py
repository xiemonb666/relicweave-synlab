"""Sampling: lineage balance, view/point/episode buckets, sharded IterableDataset, seeds.

Frozen rules:

* every ordinary negative must be a **confirmed** R1/R0 candidate that is not the query, not a
  historical R2 mate, not a grey-zone edge, not ``UNKNOWN`` and not ``TINY``
  (:meth:`PoolIndex.assert_legal_negative` raises ``LEAKAGE_DETECTED`` otherwise);
* when a query has no confirmed R1 the sampler may fall back to R0 and **records** it
  (``r1_fallback`` / ``TrainingBatch.r1_fallback_used``);
* an :class:`IterableDataset` shards by rank+worker so that no worker replicates the whole
  stream, and exposes an **acknowledged draw cursor** for checkpointing.  Prefetched but
  unacknowledged batches are recomputable: the cursor never lies about what was trained;
* augmentation randomness is derived from ``(master_seed, sample_key, epoch, step, module)``
  and therefore never depends on the worker index or on completion order.

Integration point: ``synlab.relations.api.sample_training_batch(pool, sampler_cfg, rng)`` is
**not present in this checkout**; :class:`PoolIndex` accepts any object exposing
``relation``/``neighbours``/``lineup`` (see ``tests/a12/_fixtures.FixturePool``) and does not
import the relations module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..seeds import make_rng, seed64, seed_ref
from .batch import QUALITY_TIERS, UNCALIBRATED_TIERS

#: buckets used by the loader so padding stays bounded (plan 18.7)
VIEW_BUCKETS = (1, 2, 4, 8, 16)
POINT_BUCKETS = (64, 256, 1024, 4096, 16384)


def bucket_of(value: int, buckets: Sequence[int] = VIEW_BUCKETS) -> int:
    for b in buckets:
        if value <= b:
            return int(b)
    return int(buckets[-1])


def augmentation_rng(master_seed: int, sample_key: str, *, epoch: int, step: int,
                     module: str) -> np.random.Generator:
    """Deterministic augmentation stream: no worker index, no completion-order dependence."""
    return make_rng(int(master_seed), "augmentation", str(sample_key), int(epoch), int(step), str(module))


def augmentation_seed(master_seed: int, sample_key: str, *, epoch: int, step: int,
                      module: str) -> int:
    return seed64(int(master_seed), "augmentation", str(sample_key), int(epoch), int(step), str(module))


@dataclass
class PoolIndex:
    """Read-only adapter over a relation pool (structural duck typing, no upstream import)."""

    pool: Any
    gray_zone_relations: tuple[str, ...] = ("GRAY", "GRAY_ZONE", "AMBIGUOUS")

    @property
    def pool_id(self) -> str:
        return str(getattr(self.pool, "pool_id", "") or getattr(self.pool, "gallery", None))

    @property
    def lineage(self) -> list[str]:
        return list(getattr(self.pool, "lineup", getattr(self.pool, "fragment_ids", [])))

    def relation(self, a: str, b: str) -> str:
        if a == b:
            return "SELF"
        if hasattr(self.pool, "relation"):
            return str(self.pool.relation(a, b))
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "pool has no relation() accessor",
                          stage="training.sampler.PoolIndex.relation")

    def neighbours(self, fragment_id: str) -> set[str]:
        if hasattr(self.pool, "neighbours"):
            return set(self.pool.neighbours(fragment_id))
        return set()

    def mates(self, fragment_id: str) -> set[str]:
        """The historical R2 mate set, under the protocol name of ``synlab.qc.pool_contract``.

        Identical to :meth:`neighbours` by construction: this adapter is where the mate-set
        meaning is *consumed* (``_sample_row`` draws negatives around it), so a pool that answers
        ``neighbours`` with anything else is the divergence the contract suite refuses
        (``neighbours_are_mates``)."""
        return set(self.neighbours(fragment_id))

    def legal_negatives(self, fragment_id: str) -> set[str]:
        """Set spelling of :meth:`legal_pool` (same candidates, same exclusions)."""
        return set(self.legal_pool(fragment_id))

    def candidate_ids(self, fragment_id: str) -> list[str]:
        """The pool's universe minus the query itself (the query is never a candidate)."""
        return [str(fid) for fid in self.lineage if str(fid) != str(fragment_id)]

    def history_exclusions(self, fragment_id: str) -> set[str]:
        """Fragments that may never be an ordinary negative of ``fragment_id``."""
        out = set(self.neighbours(fragment_id))
        out.add(fragment_id)
        for cand in self.lineage:
            rel = self.relation(fragment_id, cand)
            if rel in ("UNKNOWN", "TINY_CONTACT") or rel in self.gray_zone_relations:
                out.add(cand)
        return out

    def confirmed(self, a: str, b: str) -> bool:
        rel = self.relation(a, b)
        return rel in ("R0", "R1", "R2")

    def legal_pool(self, fragment_id: str, *, relation: str | None = None) -> list[str]:
        banned = self.history_exclusions(fragment_id)
        out = []
        for cand in self.lineage:
            if cand in banned:
                continue
            rel = self.relation(fragment_id, cand)
            if not self.confirmed(fragment_id, cand):
                continue
            if relation is not None and rel != relation:
                continue
            out.append(cand)
        return out

    def assert_legal_negative(self, query_id: str, candidate_id: str) -> None:
        if query_id == candidate_id:
            raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                              f"query {query_id} used as its own negative",
                              stage="training.sampler.PoolIndex.assert_legal_negative")
        rel = self.relation(query_id, candidate_id)
        if candidate_id in self.neighbours(query_id) or rel == "R2":
            raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                              f"historical R2 {candidate_id} used as a negative of {query_id}",
                              stage="training.sampler.PoolIndex.assert_legal_negative")
        if rel in ("UNKNOWN", "TINY_CONTACT") or rel in self.gray_zone_relations:
            raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                              f"{rel} candidate {candidate_id} used as a negative of {query_id}",
                              stage="training.sampler.PoolIndex.assert_legal_negative")
        if not self.confirmed(query_id, candidate_id):
            raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                              f"unconfirmed candidate {candidate_id} used as a negative of {query_id}",
                              stage="training.sampler.PoolIndex.assert_legal_negative")

    def quality_tier(self, fragment_id: str) -> int:
        tiers = getattr(self.pool, "quality_tier", {}) or {}
        return int(tiers.get(fragment_id, 0))

    def tier_name(self, tier: int) -> str:
        return QUALITY_TIERS[tier] if 0 <= tier < len(QUALITY_TIERS) else f"T{tier}"


@dataclass
class SampledSpec:
    """One sampled microbatch specification (labels side only, no tensors)."""

    rows: list[dict]
    tier_plan: dict[str, int]
    bucket: dict[str, int]
    draw_index: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def sample_keys(self) -> list[str]:
        return [str(r["sample_key"]) for r in self.rows]


class LineageBalancedSampler:
    """Round-robin sampling balanced across lineage clusters and quality tiers.

    ``acknowledged_draws`` is the number of draws the trainer has actually consumed; a
    checkpoint stores exactly that number so a resume never reuses a prefetched-but-untrained
    batch.
    """

    def __init__(self, pool: Any, *, master_seed: int, queries_per_microbatch: int = 2,
                 positive_limit: int = 2, legal_negative_limit: int = 8,
                 negative_mix: Mapping[str, float] | None = None,
                 tier_sequence: Sequence[int] | None = None,
                 clean_minimum_fraction: float = 0.2,
                 epoch: int = 0, rank: int = 0, world_size: int = 1,
                 n_workers: int = 1) -> None:
        self.index = PoolIndex(pool) if not isinstance(pool, PoolIndex) else pool
        self.master_seed = int(master_seed)
        self.queries = int(queries_per_microbatch)
        self.positive_limit = int(positive_limit)
        self.negative_limit = int(legal_negative_limit)
        mix = dict(negative_mix or {"R1": 0.5, "R0": 0.5})
        total = max(mix.get("R1", 0.5) + mix.get("R0", 0.5), 1e-9)
        self.w1 = float(mix.get("R1", 0.5)) / total
        self.w0 = float(mix.get("R0", 0.5)) / total
        self.clean_minimum_fraction = float(clean_minimum_fraction)
        self.tier_sequence = list(tier_sequence) if tier_sequence is not None else None
        self.epoch = int(epoch)
        self.rank = int(rank)
        self.world_size = max(int(world_size), 1)
        self.n_workers = max(int(n_workers), 1)
        self.acknowledged_draws = 0
        self._cursor = 0
        self._lineage_order = self._ordered_lineage()

    # ------------------------------------------------------------------ ordering
    def _ordered_lineage(self) -> list[str]:
        clusters: dict[str, list[str]] = {}
        cluster_of = getattr(self.index.pool, "lineage_cluster_of", None) or {}
        for fid in self.index.lineage:
            key = str(cluster_of.get(fid, getattr(self.index.pool, "lineage_of", {}).get(fid, "?")))
            clusters.setdefault(key, []).append(fid)
        rng = make_rng(self.master_seed, "lineage_order")
        keys = sorted(clusters)
        perm = rng.permutation(len(keys))
        order: list[str] = []
        for i in perm.tolist():
            order.extend(sorted(clusters[keys[i]]))
        return order

    def tier_plan_for(self, draw_index: int) -> dict[str, int]:
        """Quality-tier histogram for one microbatch (curriculum or explicit plan)."""
        if self.tier_sequence:
            tiers = [self.tier_sequence[(draw_index * self.queries + k) % len(self.tier_sequence)]
                     for k in range(self.queries)]
        else:
            tiers = [self.index.quality_tier(fid) for fid in self._draw_fragments(draw_index)]
        plan = {name: 0 for name in QUALITY_TIERS}
        for t in tiers:
            plan[self.index.tier_name(int(t))] += 1
        return plan

    def _draw_fragments(self, draw_index: int) -> list[str]:
        """Disjoint shard per (rank, worker) with a stable global order."""
        order = [fid for i, fid in enumerate(self._lineage_order)
                 if i % self.world_size == self.rank]
        if not order:
            order = list(self._lineage_order)
        if not order:
            # an empty gallery is a structured refusal, not ZeroDivisionError: the pool exposes
            # no ``lineup``/``fragment_ids``/``neighbours`` for this consumer to draw from
            raise SynLabError(
                ErrorCode.INPUT_UNAVAILABLE,
                "the pool exposes no lineage fragment (lineup/fragment_ids is empty), so no "
                "microbatch can be drawn",
                stage="training.sampler.LineageBalancedSampler._draw_fragments")
        start = (draw_index * self.queries) % max(len(order), 1)
        out = []
        for k in range(self.queries):
            fid = order[(start + k) % len(order)]
            out.append(fid)
        return out

    # ------------------------------------------------------------------ sampling
    def sample(self, rng: np.random.Generator | None = None, *, draw_index: int | None = None
               ) -> SampledSpec:
        idx = self.acknowledged_draws if draw_index is None else int(draw_index)
        rng = rng or make_rng(self.master_seed, "sampler", self.epoch, idx)
        rows = []
        for qid in self._draw_fragments(idx):
            rows.append(self._sample_row(qid, rng))
        bucket = {
            "views": bucket_of(int(np.ceil(np.mean([r.get("views", 1) for r in rows])))) if rows else 1,
            "points": bucket_of(int(np.ceil(np.mean([r.get("points", 0) for r in rows]))),
                                POINT_BUCKETS) if rows else 0,
        }
        return SampledSpec(rows=rows, tier_plan=self.tier_plan_for(idx), bucket=bucket,
                           draw_index=idx, meta={"pool_id": self.index.pool_id})

    def _sample_row(self, qid: str, rng: np.random.Generator) -> dict:
        neighbours = sorted(self.index.neighbours(qid))
        positives = neighbours[: self.positive_limit]
        r1 = [c for c in self.index.legal_pool(qid, relation="R1")]
        r0 = [c for c in self.index.legal_pool(qid, relation="R0")]
        fallback = False
        n_r1 = int(round(self.negative_limit * self.w1)) if r1 else 0
        picked: list[str] = []
        if r1:
            picked.extend(rng.permutation(r1)[:n_r1].tolist())
        else:
            fallback = True
        remaining = max(0, self.negative_limit - len(picked))
        if remaining and r0:
            picked.extend(rng.permutation(r0)[:remaining].tolist())
        for cand in picked:
            self.index.assert_legal_negative(qid, cand)
        features = getattr(self.index.pool, "features", {}) or {}
        payload = features.get(qid) or {}
        n_views = int(np.asarray(payload["global_rgb"]).shape[0]) if payload else 1
        n_points = int(np.sum(np.asarray(payload["point_valid"]))) if payload else 0
        excluded = sorted(self.index.history_exclusions(qid))
        return {
            "query": qid,
            "positives": positives,
            "negatives": picked,
            "excluded": excluded,
            "r1_fallback": bool(fallback),
            "sample_key": f"{self.index.pool_id}::{qid}::e{self.epoch}",
            "views": n_views,
            "points": n_points,
            "quality_tier": self.index.quality_tier(qid),
        }

    # ------------------------------------------------------------------ cursor
    def acknowledge(self, count: int = 1) -> int:
        self.acknowledged_draws += int(count)
        return self.acknowledged_draws

    def cursor(self) -> dict[str, Any]:
        """Checkpoint payload: **acknowledged** draws only, never a produced-but-untrained draw."""
        return {
            "acknowledged_draws": int(self.acknowledged_draws),
            "epoch": int(self.epoch),
            "rank": int(self.rank),
            "world_size": int(self.world_size),
            "master_seed": int(self.master_seed),
            "pool_id": self.index.pool_id,
            "lineage_order_hash": seed_ref(self.master_seed, "lineage_order", len(self._lineage_order)),
            "seed_ref": seed_ref(self.master_seed, "sampler", self.epoch),
        }

    def resume_from(self, cursor: Mapping[str, Any]) -> None:
        if int(cursor.get("master_seed", -1)) != self.master_seed:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              "resume seed mismatch: refusing to continue a different stream",
                              stage="training.sampler.LineageBalancedSampler.resume_from")
        if str(cursor.get("pool_id", "")) not in ("", self.index.pool_id):
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"resume pool mismatch {cursor.get('pool_id')!r} != {self.index.pool_id!r}",
                              stage="training.sampler.LineageBalancedSampler.resume_from")
        self.acknowledged_draws = int(cursor.get("acknowledged_draws", 0))
        self.epoch = int(cursor.get("epoch", self.epoch))


class ShardedIterableDataset:
    """Iterable dataset with rank/worker sharding and an acknowledged (resumable) cursor.

    The dataset is deliberately explicit about the difference between a *produced* draw and an
    *acknowledged* one: :meth:`__iter__` yields ``(draw_index, spec)`` and only
    :meth:`acknowledge` advances the persisted cursor (plan 18.7).
    """

    def __init__(self, sampler: LineageBalancedSampler, *, epoch_length: int,
                 prefetch: int = 2) -> None:
        self.sampler = sampler
        self.epoch_length = int(epoch_length)
        self.prefetch = int(prefetch)
        self.epoch = sampler.epoch
        self._produced = 0

    # -- torch IterableDataset compatibility ------------------------------------------
    def __iter__(self) -> Iterator[tuple[int, SampledSpec]]:
        self._produced = 0
        start = self.sampler.acknowledged_draws
        for offset in range(self.epoch_length):
            draw_index = start + offset
            spec = self.sampler.sample(draw_index=draw_index)
            self._produced += 1
            yield draw_index, spec

    def __len__(self) -> int:
        return self.epoch_length

    # -- worker sharding ---------------------------------------------------------------
    @property
    def worker_shard(self) -> list[int]:
        """Draw indices this (rank, worker) owns; workers never replicate the whole stream."""
        return [i for i in range(self.epoch_length) if i % self.sampler.n_workers == 0]

    def worker_indices(self, worker_id: int) -> list[int]:
        w = max(int(self.sampler.n_workers), 1)
        return [i for i in range(self.epoch_length) if i % w == int(worker_id)]

    def acknowledge(self, count: int = 1) -> int:
        return self.sampler.acknowledge(count)

    def cursor(self) -> dict[str, Any]:
        return self.sampler.cursor()

    def set_epoch(self, epoch: int) -> None:
        self.epoch = int(epoch)
        self.sampler.epoch = int(epoch)

    def resume_from(self, cursor: Mapping[str, Any]) -> tuple[int, int]:
        """Return ``(discarded_prefetch, acknowledged_draws)`` for the resume report."""
        before = self.sampler.acknowledged_draws
        self.sampler.resume_from(cursor)
        discarded = max(0, before - self.sampler.acknowledged_draws)
        return discarded, self.sampler.acknowledged_draws


__all__ = [
    "VIEW_BUCKETS", "POINT_BUCKETS", "bucket_of", "augmentation_rng", "augmentation_seed",
    "PoolIndex", "SampledSpec", "LineageBalancedSampler", "ShardedIterableDataset",
    "QUALITY_TIERS", "UNCALIBRATED_TIERS",
]
