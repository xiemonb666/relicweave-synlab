"""Trainer: AdamW, curriculum, effective-query accumulation, checkpoint/resume, NaN guard.

Frozen settings (plan 18.4): ``head_lr=1e-4``, ``backbone_lr=1e-5``, ``weight_decay=.01``,
warmup 5%, cosine decay, grad-clip 1.0, FP32.  On this host torch is CPU-only, so a spec that
asks for ``bf16_if_verified`` is **downgraded to fp32 with a recorded reason** -- the run never
claims a precision it did not use.

Gradient accumulation is weighted by the effective number of queries:
``L = sum_m (n_m * L_m) / sum_m n_m``.  Microbatches with different denominators are therefore
never averaged as if they were equal.

Checkpoint content: model, optimizer, scheduler, step, **acknowledged sampler cursor**, RNG
state, data release hash, recipe, encoder/cache version, curriculum/exposure counters.  A
resume discards prefetched-but-unacknowledged draws and deterministically recomputes them; the
reproducibility level actually reached is reported, not asserted.

A non-finite loss raises ``SynLabError(TRAIN_NONFINITE)`` after persisting the offending batch.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ..canonical import array_hash, hash_json
from ..errors import ErrorCode, SynLabError
from ..seeds import make_rng
from .adapter import FeatureBundle
from .batch import TrainingBatch, build_training_batch, mate_present_shortcut_probe
from .losses import (
    DEFAULT_HARD_NEGATIVE_WEIGHT,
    DEFAULT_WEIGHTS,
    HARD_NEGATIVE_TASK,
    MultiTaskLoss,
    contradiction_loss,
    correspondence_loss,
    hard_negative_loss,
    quality_loss,
    rank_loss_pair_head,
    task_gradient_norms,
    view_infonce,
)
from .model import DualTowerModel
from .sampler import LineageBalancedSampler, ShardedIterableDataset
from .supervision import supervision_accounting

TRAINER_VERSION = "a12.trainer.v1"
#: reproducibility actually provided: sampler stream and optimizer steps are exact on CPU fp32
#: within one process; gradients are not guaranteed bitwise across devices/builds.
REPRODUCIBILITY_LEVEL = "EXACT_SAMPLER_SEQUENCE_AND_STEP_CPU_FP32_SAME_PROCESS"

_CLEAN_TIERS = (0, 1)
_MID_TIERS = (2,)
_HARD_TIERS = (3, 4, 5)


def _label_histogram(labels: Any, valid: Any) -> dict[str, int]:
    """Histogram of the *valid* labels only (an invalid label is not a label)."""
    arr = np.asarray(labels, dtype=np.int64)[np.asarray(valid, dtype=bool)]
    if arr.size == 0:
        return {}
    values, counts = np.unique(arr, return_counts=True)
    return {str(int(v)): int(c) for v, c in zip(values.tolist(), counts.tolist())}


def _rank_skip_reason(n_positives: int, n_negatives: int, n_allowed: int) -> str:
    """Name the *measured* blocker of the rank task instead of a single catch-all string.

    The batch can fail rank supervision for two independent reasons -- no legal negative at all,
    or no positive pair that can be encoded -- and the fix is different for each.  The reason
    string is derived from the counts that were just measured, never from a constant.
    """
    if n_positives == 0:
        return "no_confirmed_R2_positive_in_the_batch"
    if n_negatives == 0:
        return "no_legal_negative_in_exported_relations"
    if n_allowed == 0:
        return "no_encodable_pair_for_the_positive_and_its_negatives"
    return "no_encodable_positive_pair"


def _contradiction_skip_reason(n_labels: int, n_allowed: int, n_q_encodable: int,
                               n_c_encodable: int) -> str:
    """Why a non-empty contradiction label set produced no loss row."""
    if n_labels == 0:
        return "no_contradiction_label"
    if n_allowed == 0 and n_c_encodable == 0:
        return "no_encodable_contradiction_pair_candidate_side_unobserved"
    if n_allowed == 0 and n_q_encodable == 0:
        return "no_encodable_contradiction_pair_query_side_unobserved"
    if n_allowed == 0:
        return "no_encodable_contradiction_pair"
    return "no_valid_contradiction_label"


def _torch():
    import torch

    return torch


def _hashable_state(value: Any) -> Any:
    """JSON-safe, content-addressed projection of one checkpoint field.

    ``canonical.hash_json`` refuses objects it cannot serialise, and a checkpoint's ``model`` /
    ``pair_head`` entries are ``torch.Tensor`` state dicts, so hashing the raw payload raised
    ``TypeError: Object of type Tensor is not JSON serializable`` -- for *every*
    ``save_checkpoint`` call.  Tensors (and numpy arrays) are projected to a content hash with
    their shape/dtype kept, so the payload hash still changes whenever a weight changes.
    """
    torch = _torch()
    if isinstance(value, torch.Tensor):
        arr = np.ascontiguousarray(value.detach().cpu().numpy())
        return {"tensor_sha256": array_hash(arr), "shape": list(arr.shape),
                "dtype": str(arr.dtype)}
    if isinstance(value, Mapping):
        return {str(k): _hashable_state(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_hashable_state(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_hashable_state(v) for v in value), key=repr)
    if isinstance(value, np.ndarray):
        arr = np.ascontiguousarray(value)
        return {"ndarray_sha256": array_hash(arr), "shape": list(arr.shape),
                "dtype": str(arr.dtype)}
    return value


@dataclass
class CurriculumSchedule:
    """20% Q0/Q1 -> 40% mixing Q2 -> 40% mixing Q3/Q4/Q5, with >=20% clean at all times."""

    total_steps: int
    clean_minimum_fraction: float = 0.2
    mid_start: float = 0.2
    hard_start: float = 0.6
    enabled: bool = True

    def phase(self, step: int) -> str:
        if not self.enabled:
            return "RANDOM"
        frac = (step + 1) / max(int(self.total_steps), 1)
        if frac <= self.mid_start:
            return "EARLY"
        if frac <= self.hard_start:
            return "MID"
        return "LATE"

    def tiers_for_step(self, step: int, count: int) -> list[int]:
        """Requested quality tiers for the ``count`` query slots of this step."""
        if not self.enabled:
            rng = make_rng(0, "curriculum-random", int(step))
            return [int(rng.integers(0, 6)) for _ in range(count)]
        phase = self.phase(step)
        hard_pool = _HARD_TIERS if phase == "LATE" else _MID_TIERS
        allow_hard = phase != "EARLY"
        n_clean = max(int(math.ceil(self.clean_minimum_fraction * count)), 1) if count else 0
        n_clean = min(n_clean, count)
        tiers = [0, 1][:n_clean] if n_clean <= 2 else [0] * n_clean
        rng = make_rng(20261001, "curriculum", phase, int(step))
        for k in range(count - n_clean):
            if allow_hard and (phase == "LATE" or k % 2 == 1):
                tiers.append(int(hard_pool[int(rng.integers(0, len(hard_pool)))]))
            else:
                tiers.append(int(rng.integers(0, 2)))
        return tiers[:count]

    def realised_plan(self, total_steps: int, queries: int, *, control_seed: int | None = None
                      ) -> dict[str, Any]:
        """Tier histogram this schedule will request (and the random-mixture control arm)."""
        curric: list[int] = []
        for step in range(int(total_steps)):
            curric.extend(self.tiers_for_step(step, queries))
        self_hist = _hist(curric)
        clean = sum(self_hist.get(t, 0) for t in ("Q0", "Q1"))
        control: list[int] = []
        rng = np.random.default_rng(0 if control_seed is None else int(control_seed))
        control = list(rng.integers(0, 6, size=len(curric)))
        return {
            "curriculum": self_hist,
            "curriculum_clean_fraction": clean / max(len(curric), 1),
            "control": _hist(control),
            "control_clean_fraction": sum(_hist(control).get(t, 0) for t in ("Q0", "Q1"))
            / max(len(control), 1),
            "clean_minimum_fraction": self.clean_minimum_fraction,
            "schedule": {"mid_start": self.mid_start, "hard_start": self.hard_start},
        }


def _hist(tiers: Sequence[int]) -> dict[str, int]:
    from .batch import QUALITY_TIERS

    out = {name: 0 for name in QUALITY_TIERS}
    for t in tiers:
        name = QUALITY_TIERS[int(t)] if 0 <= int(t) < len(QUALITY_TIERS) else f"T{int(t)}"
        out[name] = out.get(name, 0) + 1
    return out


@dataclass
class TrainMetrics:
    steps: int = 0
    microbatches: int = 0
    samples: int = 0
    effective_denominator: float = 0.0
    r2_edges_exposed: int = 0
    legal_negatives: int = 0
    mothers_exposed: set[str] = field(default_factory=set)
    lineages_exposed: set[str] = field(default_factory=set)
    tier_histogram: dict[str, int] = field(default_factory=dict)
    requested_tier_histogram: dict[str, int] = field(default_factory=dict)
    task_history: list[dict[str, Any]] = field(default_factory=list)
    skipped_total: dict[str, int] = field(default_factory=dict)
    grad_norm_history: list[float] = field(default_factory=list)
    wall_seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "steps": self.steps, "microbatches": self.microbatches, "samples": self.samples,
            "effective_denominator": self.effective_denominator,
            "r2_edges_exposed": self.r2_edges_exposed,
            "legal_negatives": self.legal_negatives,
            "mothers_exposed": len(self.mothers_exposed),
            "lineages_exposed": len(self.lineages_exposed),
            "tier_histogram": dict(self.tier_histogram),
            "requested_tier_histogram": dict(self.requested_tier_histogram),
            "skipped_total": dict(self.skipped_total),
            "grad_norm_last": self.grad_norm_history[-1] if self.grad_norm_history else None,
            "grad_norm_max": max(self.grad_norm_history) if self.grad_norm_history else None,
            "wall_seconds": self.wall_seconds,
            "throughput_samples_per_s": (self.samples / self.wall_seconds) if self.wall_seconds > 0 else None,
        }


class Trainer:
    """Trains a :class:`DualTowerModel` on observed features plus separately supplied labels."""

    def __init__(self, spec: Any, model: DualTowerModel, *,
                 pool: Any | None = None,
                 sampler: LineageBalancedSampler | None = None,
                 out_dir: str | os.PathLike[str] | None = None,
                 store: Any | None = None,
                 device: str = "cpu",
                 trainer_version: str = TRAINER_VERSION,
                 recipe: Mapping[str, Any] | None = None,
                 release_hash: str = "",
                 curriculum_enabled: bool | None = None,
                 curriculum_control: bool = False,
                 label_source: Any | None = None) -> None:
        torch = _torch()
        self.spec = spec
        self.model = model
        self.pool = pool
        self.store = store
        self.label_source = label_source
        self.label_report: dict[str, Any] = {}
        self.device = torch.device(device)
        self.trainer_version = trainer_version
        self.recipe = dict(recipe or {})
        self.release_hash = release_hash
        self.out_dir = Path(out_dir) if out_dir is not None else None
        if self.out_dir is not None:
            self.out_dir.mkdir(parents=True, exist_ok=True)

        opt = getattr(spec, "optimization", spec)
        self.head_lr = float(getattr(opt, "head_lr", 1e-4))
        self.backbone_lr = float(getattr(opt, "backbone_lr", 1e-5))
        self.weight_decay = float(getattr(opt, "weight_decay", 0.01))
        self.warmup_fraction = float(getattr(opt, "warmup_fraction", 0.05))
        self.clip_norm = float(getattr(opt, "gradient_clip_norm", 1.0))
        self.max_steps = int(getattr(opt, "max_steps", 100))
        self.accumulation_steps = max(int(getattr(opt, "accumulation_steps", 1)), 1)
        requested_precision = str(getattr(opt, "precision", "fp32"))
        cuda = torch.cuda.is_available()
        if requested_precision == "bf16_if_verified" and not cuda:
            self.precision = "fp32"
            self.precision_downgrade_reason = (
                "spec requested bf16_if_verified but this host has no CUDA device; FP32 used "
                "(plan 18.4: precise geometry never uses BF16)"
            )
        else:
            self.precision = "fp32" if not cuda else requested_precision
            self.precision_downgrade_reason = None

        loss_weights = getattr(spec, "losses", None)
        weights = ({name: float(getattr(loss_weights, name, DEFAULT_WEIGHTS[name]))
                    for name in DEFAULT_WEIGHTS} if loss_weights is not None else dict(DEFAULT_WEIGHTS))
        # the S2 auxiliary hard-negative term is **off** unless a caller gives it a non-zero
        # weight; it lives outside ``DEFAULT_WEIGHTS``/``TASK_ORDER`` so the five core tasks and
        # their frozen defaults are untouched.
        self.hard_negative_weight = float(
            getattr(loss_weights, HARD_NEGATIVE_TASK, DEFAULT_HARD_NEGATIVE_WEIGHT)
            if loss_weights is not None else DEFAULT_HARD_NEGATIVE_WEIGHT)
        self.loss_weights = weights
        # the combination weights carry the auxiliary task beside the five core ones; the core
        # five keep their frozen values (``self.loss_weights`` is unchanged, so checkpoints and
        # reports keep their existing shape).
        self.multi_task = MultiTaskLoss(
            loss_weights={**weights, HARD_NEGATIVE_TASK: self.hard_negative_weight})
        self.temperature = float(getattr(getattr(spec, "retrieval", spec), "temperature", 0.1)
                                if hasattr(getattr(spec, "retrieval", spec), "temperature") else 0.1)

        curriculum_cfg = getattr(spec, "curriculum", None)
        enabled = (bool(getattr(curriculum_cfg, "enabled", True)) if curriculum_enabled is None
                   else bool(curriculum_enabled))
        self.curriculum = CurriculumSchedule(
            total_steps=self.max_steps,
            clean_minimum_fraction=float(getattr(curriculum_cfg, "clean_minimum_fraction", 0.2)),
            enabled=enabled and not curriculum_control,
        )
        self.curriculum_control = bool(curriculum_control)
        self.master_seed = int(getattr(spec, "train_seed", 11))
        self.sampler = sampler or (LineageBalancedSampler(pool, master_seed=self.master_seed)
                                   if pool is not None else None)
        self.dataset = (ShardedIterableDataset(self.sampler, epoch_length=self.max_steps * 2)
                        if self.sampler is not None else None)

        self.optimizer = self._make_optimizer()
        self.scheduler = self._make_scheduler()
        self.step_index = 0
        self.rng = make_rng(self.master_seed, "trainer")
        self.metrics = TrainMetrics()
        self.history: list[dict[str, Any]] = []
        self._rng_state = None
        self._failure_dump: str | None = None
        self.stopped_at_step = 0

    # ------------------------------------------------------------------ optimiser
    def _make_optimizer(self):
        torch = _torch()
        groups = self.model.parameter_groups(head_lr=self.head_lr, backbone_lr=self.backbone_lr)
        if not groups:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "model exposes no parameters",
                              stage="training.trainer.setup")
        return torch.optim.AdamW(groups, lr=self.head_lr, weight_decay=self.weight_decay)

    def _make_scheduler(self):
        torch = _torch()
        warmup = max(int(round(self.max_steps * self.warmup_fraction)), 0)

        def lr_lambda(step: int) -> float:
            if warmup and step < warmup:
                return float(step + 1) / float(warmup)
            progress = (step - warmup) / max(self.max_steps - warmup, 1)
            progress = min(max(progress, 0.0), 1.0)
            return 0.5 * (1.0 + math.cos(math.pi * progress))

        return torch.optim.lr_scheduler.LambdaLR(self.optimizer, lr_lambda)

    # ------------------------------------------------------------------ data
    def _payloads_for(self, fragment_ids: Sequence[str]) -> dict[str, dict]:
        features = getattr(self.pool, "features", None) or {}
        out = {}
        for fid in fragment_ids:
            if fid not in features:
                raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                                  f"pool has no feature payload for {fid}",
                                  stage="training.trainer._payloads_for")
            out[fid] = features[fid]
        return out

    def _tier_sequence_for(self, steps: int) -> list[int]:
        queries = int(getattr(getattr(self.spec, "sampling", self.spec),
                              "queries_per_microbatch", 2))
        seq: list[int] = []
        for step in range(int(steps)):
            seq.extend(self.curriculum.tiers_for_step(step, queries))
        return seq

    def build_batch(self, spec) -> TrainingBatch:
        """Turn a sampled spec into a feature bundle plus separately held labels.

        When a ``label_source`` is configured (see :mod:`synlab.training.labels`), the label side
        of the package is handed to :func:`synlab.training.batch.build_training_batch` through
        its ``correspondence=`` / ``quality_target=`` / ``quality_target_valid=`` arguments.  That
        plumbing is the difference between "the package carries no label" and "the label never
        reached the batch": without it every one of those tensors is zero no matter what the
        package stores, and the loss then reports ``no_correspondence_label`` /
        ``no_valid_quality_target`` for a package that does carry both.
        """
        ids: list[str] = []
        for row in spec.rows:
            for fid in [row["query"], *row["positives"], *row["negatives"]]:
                if fid not in ids:
                    ids.append(fid)
        payloads = self._payloads_for(ids)
        bundle = FeatureBundle.from_dict(payloads, token_budget=int(
            getattr(getattr(self.spec, "inputs", self.spec), "local_token_budget", 256)
        )).check_shapes()
        labels = {"pool_id": getattr(self.pool, "pool_id", ""),
                  "lineage_cluster": getattr(self.pool, "lineage_cluster_of", {}) or {}}
        kwargs: dict[str, Any] = {}
        label_report: dict[str, Any] = {}
        source = self.label_source
        if source is not None:
            quality_target, quality_valid, quality_report = source.quality_target_for(ids)
            kwargs["quality_target"] = quality_target
            kwargs["quality_target_valid"] = quality_valid
            label_report["quality"] = quality_report
            correspondence, corr_report = source.correspondence_for(bundle, spec.rows)
            label_report["correspondence"] = corr_report
            if correspondence:
                # only a real, token-mapped correspondence table may become W
                kwargs["correspondence"] = correspondence
        self.label_report = label_report
        batch = build_training_batch(
            bundle, pool=self.pool, rows=spec.rows, labels=labels,
            sampler_cfg=getattr(self.spec, "sampling", None),
            quality_tier=getattr(self.pool, "quality_tier", None),
            meta={"supervision_labels": label_report} if label_report else None,
            **kwargs,
        )
        return batch

    # ------------------------------------------------------------------ losses
    def compute_losses(self, batch: TrainingBatch, *,
                       return_task_tensors: bool = False) -> dict[str, Any]:
        torch = _torch()
        features = batch.features.to_torch(device=str(self.device))
        f = features.n_fragments
        pair = torch.as_tensor(batch.pair_index, dtype=torch.long, device=self.device)
        pair_valid = torch.as_tensor(batch.pair_valid, dtype=torch.bool, device=self.device)
        pos_mask = torch.as_tensor(batch.pos_mask, dtype=torch.bool, device=self.device)
        neg_mask = torch.as_tensor(batch.neg_mask, dtype=torch.bool, device=self.device)

        z, z_valid = self.model.encoder.encode(features)

        # ---- pair-shaped similarity [Q,C] from the cacheable first-stage tower
        q_idx = pair[:, :, 0]
        c_idx = pair[:, :, 1]
        zq = z[q_idx]
        zc = z[c_idx]
        sim_qc = (zq * zc).sum(dim=-1) / max(self.temperature, 1e-8)
        allowed = z_valid[q_idx] & z_valid[c_idx] & pair_valid
        # an unencodable pair (no legal modality) is reported, never scored as if valid
        sim_masked = torch.where(allowed, sim_qc, torch.full_like(sim_qc, -20.0))

        results: dict[str, Any] = {}
        if int((pos_mask & allowed).sum()) == 0:
            results["rank"] = {"loss": None, "n_valid": 0, "skipped": True,
                               "n_valid_labels": int(pos_mask.sum() + neg_mask.sum()),
                               "reason": _rank_skip_reason(int(pos_mask.sum()), int(neg_mask.sum()),
                                                           int(allowed.sum())),
                               "diagnostics": {
                                   "n_positives_label_valid": int(pos_mask.sum()),
                                   "n_negatives_label_valid": int(neg_mask.sum()),
                                   "n_encodable_pairs": int(allowed.sum()),
                                   "rejected_by": "z_valid[candidate]==False for every positive"
                                                  if int(neg_mask.sum()) == 0 else
                                                  "no legal negative survives `allowed`"}}
        else:
            results["rank"] = rank_loss_pair_head(
                sim_masked, allowed, pos_mask=pos_mask & allowed, neg_mask=neg_mask & allowed,
                temperature=self.temperature,
            )
            results["rank"]["n_valid_labels"] = int(pos_mask.sum() + neg_mask.sum())

        # ---- B'. auxiliary hard-negative term (S2): OFF unless weighted ---------------------
        # ``DEFAULT_HARD_NEGATIVE_WEIGHT`` is 0.0, in which case the term is not built at all:
        # the combination, the report and the backward pass are then bit-identical to a run
        # without the class.  When it is on, the term is combined *beside* the five core tasks
        # with its own weight and its own mask -- ``neg_mask`` is never read here.
        hard_mask = torch.as_tensor(np.asarray(batch.hard_neg_mask, dtype=bool),
                                    dtype=torch.bool, device=self.device)
        hard_query_mate = torch.as_tensor(np.asarray(batch.hard_neg_query_mate, dtype=bool),
                                          dtype=torch.bool, device=self.device)
        if self.hard_negative_weight != 0.0 and int(hard_mask.sum()) > 0:
            results[HARD_NEGATIVE_TASK] = hard_negative_loss(
                sim_masked, allowed, pos_mask=pos_mask & allowed,
                hard_neg_mask=hard_mask & allowed, query_mate_present=hard_query_mate,
                temperature=self.temperature)
            results[HARD_NEGATIVE_TASK]["n_valid_labels"] = int(hard_mask.sum())

        # ---- A. same-fragment multi-view InfoNCE (R2 / grey-zone excluded from negatives)
        view_emb, view_valid = self._view_embeddings(features)
        view_fragment_index = torch.repeat_interleave(
            torch.arange(f, device=self.device), features.global_rgb.shape[1])
        results["view"] = view_infonce(
            view_emb, fragment_index=view_fragment_index, view_valid=view_valid,
            exclude_matrix=self._r2_exclusion_matrix(batch), temperature=self.temperature)

        # ---- C. correspondence (only when the label side really carries an edge weight W)
        tokens = features.local_tokens
        tok_valid = features.token_valid
        l_dim = int(tokens.shape[1])
        corr_w = np.asarray(batch.corr_weight, dtype=np.float32)
        corr_labels = dict((batch.meta.get("supervision_labels") or {}).get("correspondence") or {})
        if float(corr_w.sum()) <= 0:
            results["correspondence"] = {
                "loss": None, "n_valid": 0, "skipped": True,
                "n_valid_labels": int(corr_labels.get("n_label_samples_in_batch",
                                                      corr_labels.get(
                                                          "n_label_samples_in_package", 0))),
                "reason": ("no_correspondence_label" if not corr_labels
                           or not corr_labels.get("n_label_samples_in_package")
                           else "correspondence_labels_never_reached_token_space"),
                "diagnostics": {
                    "label_samples_in_package": int(
                        corr_labels.get("n_label_samples_in_package", 0)),
                    "pairs_in_batch_with_labels": int(
                        corr_labels.get("pairs_in_batch_with_labels", 0)),
                    "pairs_with_both_sides_observable": int(
                        corr_labels.get("pairs_with_both_sides_observable", 0)),
                    "token_mapped_rows": int(corr_labels.get("token_mapped_rows", 0)),
                    "blocked_by": list(corr_labels.get("blocked_by") or []),
                }}
        else:
            q_tokens = torch.nn.functional.normalize(tokens[q_idx], dim=-1)   # [Q,C,L,D]
            c_tokens = torch.nn.functional.normalize(tokens[c_idx], dim=-1)
            sim_tok = torch.einsum("qcid,qcjd->qcij", q_tokens, c_tokens)
            k = int(corr_w.shape[-1])
            kk = min(k, l_dim)
            w = torch.zeros((*sim_tok.shape[:3], l_dim), device=self.device)
            row_valid = torch.zeros((*sim_tok.shape[:3],), dtype=torch.bool, device=self.device)
            col_valid = torch.zeros((*sim_tok.shape[:3],), dtype=torch.bool, device=self.device)
            w[:, :, :kk, :kk] = torch.as_tensor(corr_w[:, :, :kk, :kk], device=self.device)
            row_valid[:, :, :kk] = torch.as_tensor(
                np.asarray(batch.corr_row_valid)[..., :kk], device=self.device)
            col_valid[:, :, :kk] = torch.as_tensor(
                np.asarray(batch.corr_col_valid)[..., :kk], device=self.device)
            row_valid = row_valid & tok_valid[q_idx][:, :, :l_dim] & allowed
            col_valid = col_valid & tok_valid[c_idx][:, :, :l_dim] & allowed
            results["correspondence"] = correspondence_loss(
                sim_tok, w, row_valid=row_valid, col_valid=col_valid, mode="masked_ce",
                temperature=self.temperature, source_group=features.token_source[q_idx])

        # ---- D. quality estimation: observation-only inputs, target valid per channel
        q_target = torch.as_tensor(batch.quality_target, dtype=torch.float32, device=self.device)
        q_valid = torch.as_tensor(batch.quality_target_valid, dtype=torch.bool,
                                  device=self.device)
        pred = self.model.encoder.encode_quality(features)
        if int(q_valid.sum()) == 0:
            quality_labels = dict((batch.meta.get("supervision_labels") or {}).get("quality") or {})
            results["quality"] = {"loss": None, "n_valid": 0, "skipped": True,
                                  "n_valid_labels": 0,
                                  "reason": "no_valid_quality_target",
                                  "diagnostics": {
                                      "n_fragments": int(f),
                                      "channel": str(quality_labels.get("channel", "")),
                                      "measured_fragments_in_package": int(quality_labels.get(
                                          "n_measured_fragments_in_package", 0)),
                                      "missing_is_not_a_zero_label": True}}
        elif pred.shape[-1] == int(np.prod(q_target.shape[1:])):
            results["quality"] = quality_loss(
                pred, q_target.reshape(f, -1), q_valid.reshape(f, -1), kind="huber", delta=1.0)
            results["quality"]["n_valid_labels"] = int(q_valid.sum())
        elif pred.shape[-1] == 1 and q_target.numel():
            results["quality"] = quality_loss(
                pred, q_target.mean(dim=(-1, -2), keepdim=False).unsqueeze(-1),
                q_valid.any(dim=(-1, -2)).unsqueeze(-1), kind="huber", delta=1.0)
            results["quality"]["n_valid_labels"] = int(q_valid.any(dim=(-1, -2)).sum())
        else:
            results["quality"] = {
                "loss": None, "n_valid": 0, "skipped": True, "n_valid_labels": int(q_valid.sum()),
                "reason": f"quality_output_dim_mismatch(pred={pred.shape[-1]},"
                          f"target={int(np.prod(q_target.shape[1:]))})",
                "diagnostics": {}}

        # ---- E. contradiction / compatibility on the pair score (missing masked out)
        cont = torch.as_tensor(batch.contradiction, dtype=torch.long, device=self.device)
        # the label set *before* encodability is measured separately: "no label exists" and
        # "every labelled pair is unencodable" are different facts with different fixes
        cont_labels = torch.as_tensor(batch.contradiction_valid, dtype=torch.bool,
                                      device=self.device)
        cont_valid = cont_labels & allowed
        if int(cont_valid.sum()) == 0:
            results["contradiction"] = {
                "loss": None, "n_valid": 0, "skipped": True,
                "n_valid_labels": int(cont_labels.sum()),
                "reason": _contradiction_skip_reason(
                    int(cont_labels.sum()), 0, int(z_valid[q_idx].sum()),
                    int(z_valid[c_idx].sum())),
                "diagnostics": {
                    "n_labels_valid_before_encodability": int(cont_labels.sum()),
                    "n_labels_after_encodability": 0,
                    "label_histogram": _label_histogram(batch.contradiction,
                                                        np.asarray(batch.contradiction_valid)),
                    "classes_present": len(_label_histogram(batch.contradiction,
                                                            np.asarray(batch.contradiction_valid)))},
            }
        else:
            logits3 = torch.stack([torch.zeros_like(sim_masked), sim_masked, -sim_masked],
                                  dim=-1)[..., None, :]
            results["contradiction"] = contradiction_loss(
                logits3, cont[..., None], cont_valid[..., None])
            results["contradiction"]["n_valid_labels"] = int(cont_labels.sum())

        combined = self.multi_task.combine(results)
        supervision = supervision_accounting(
            batch, z_valid=np.asarray(z_valid.detach().cpu().numpy(), dtype=bool),
            label_report=batch.meta.get("supervision_labels"))
        out = {
            "combined": combined,
            "results": results,
            "effective_queries": int(batch.effective_query_count()),
            "n_fragments": f,
            "encodable_pairs": int(allowed.sum()),
            "unencodable_pairs": int((pair_valid & ~allowed).sum()),
            "supervision": supervision,
        }
        if return_task_tensors:
            out["task_tensors"] = {k: v.get("loss") for k, v in results.items()}
        return out

    def _view_embeddings(self, features) -> tuple[Any, Any]:
        """Per-(fragment, view) embeddings from the shared RGB tower (view positives)."""
        torch = _torch()
        rgb = features.global_rgb
        f, v = rgb.shape[0], rgb.shape[1]
        flat = rgb.reshape(f * v, 3, rgb.shape[-2], rgb.shape[-1])
        emb = self.model.encoder.global_branch(flat)
        emb = torch.nn.functional.normalize(emb, dim=-1)
        valid = features.global_valid.reshape(-1)
        return emb, valid

    def _r2_exclusion_matrix(self, batch: TrainingBatch):
        torch = _torch()
        f = batch.features.n_fragments
        ex = torch.zeros((f, f), dtype=torch.bool, device=self.device)
        # a fragment that is a positive/negative partner in this batch must not be pushed away
        # as a view-level negative when its relation is R2 or excluded (grey zone / UNKNOWN)
        q_idx = batch.pair_index[:, :, 0].reshape(-1)
        c_idx = batch.pair_index[:, :, 1].reshape(-1)
        pos = batch.pos_mask.reshape(-1)
        excluded = batch.excluded_mask.reshape(-1)
        for i in range(q_idx.shape[0]):
            a, b = int(q_idx[i]), int(c_idx[i])
            if pos[i] or excluded[i] or batch.labels_relation.reshape(-1)[i] != 0:
                ex[a, b] = True
                ex[b, a] = True
        return ex

    # ------------------------------------------------------------------ step
    def train_step(self, batch: TrainingBatch, *, accumulate: float = 1.0,
                   retain_graph: bool = False) -> dict[str, Any]:
        """One forward/backward.

        ``accumulate`` is the **effective-query weight** of this microbatch: the loss handed to
        ``backward`` is ``L * n_eff`` so that dividing the accumulated gradients by
        ``sum(n_eff)`` over the window yields the exact effective-query-weighted mean.  Equal
        averaging of microbatches with different denominators is therefore impossible.
        """
        torch = _torch()
        out = self.compute_losses(batch, return_task_tensors=retain_graph)
        combined = out["combined"]
        if combined["loss"] is None:
            return {"skipped": True, "reason": "all_tasks_skipped", "report": combined["report"],
                    "effective_queries": out["effective_queries"],
                    "supervision": out.get("supervision")}
        loss = combined["loss"]
        accum_loss = loss * float(accumulate)
        if not bool(torch.isfinite(accum_loss)):
            self._dump_failure(batch, loss)
            raise SynLabError(
                ErrorCode.TRAIN_NONFINITE,
                f"non-finite training loss at step {self.step_index}",
                stage="training.trainer.train_step",
                evidence_refs=[self._failure_dump] if self._failure_dump else [],
                measurements={"loss": float(loss.detach()), "step": self.step_index,
                              "effective_queries": out["effective_queries"]},
            )
        accum_loss.backward(retain_graph=retain_graph)
        report = combined["report"]
        if retain_graph:
            params = [p for group in self.optimizer.param_groups for p in group["params"]]
            report["grad_norms"] = task_gradient_norms(out.get("task_tensors", {}), params,
                                                       retain_graph=True)
        return {"skipped": False, "loss": float(loss.detach()), "report": report,
                "effective_queries": out["effective_queries"],
                "encodable_pairs": out["encodable_pairs"],
                "unencodable_pairs": out["unencodable_pairs"],
                "supervision": out.get("supervision"),
                "diagnostics": {k: v.get("diagnostics", {}) for k, v in out["results"].items()}}

    def _dump_failure(self, batch: TrainingBatch, loss) -> str:
        if self.out_dir is None:
            self._failure_dump = None
            return ""
        path = self.out_dir / f"failure_batch_step{self.step_index}.npz"
        np.savez(
            path,
            pair_index=batch.pair_index, labels_relation=batch.labels_relation,
            pos_mask=batch.pos_mask, neg_mask=batch.neg_mask,
            local_tokens=batch.features.local_tokens, token_valid=batch.features.token_valid,
            loss=np.asarray([float(loss.detach())]),
        )
        self._failure_dump = str(path)
        return self._failure_dump

    # ------------------------------------------------------------------ loop
    def fit(self, steps: int | None = None) -> dict[str, Any]:
        torch = _torch()
        if self.sampler is None:
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                              "no sampler/pool configured for fit()",
                              stage="training.trainer.fit")
        total = int(steps if steps is not None else self.max_steps)
        queries = int(getattr(getattr(self.spec, "sampling", self.spec),
                              "queries_per_microbatch", 2))
        seq = self._tier_sequence_for(total)
        self.sampler.tier_sequence = seq if not self.curriculum_control else None

        started = time.perf_counter()
        end_step = self.step_index + total
        while self.step_index < end_step:
            self.optimizer.zero_grad(set_to_none=True)
            micro_reports: list[dict[str, Any]] = []
            total_n = 0.0
            for _ in range(self.accumulation_steps):
                spec = self.sampler.sample(draw_index=self.sampler.acknowledged_draws)
                batch = self.build_batch(spec)
                n_eff = float(batch.effective_query_count())
                micro_reports.append(self._micro_record(batch, spec, n_eff))
                if n_eff <= 0:
                    # no valid supervision anywhere in this microbatch: skip explicitly
                    self.sampler.acknowledge(1)
                    continue
                step_info = self.train_step(batch, accumulate=n_eff)
                if step_info.get("skipped"):
                    micro_reports[-1]["train_skipped_reason"] = step_info.get("reason")
                    self.sampler.acknowledge(1)
                    continue
                total_n += n_eff
                self.sampler.acknowledge(1)
            self.step_index += 1
            self.history.extend(micro_reports)
            if total_n <= 0:
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  "no effective query in the whole accumulation window",
                                  stage="training.trainer.fit")
            # gradients hold sum_m (n_m * dL_m); divide by sum_m n_m for the weighted mean
            for group in self.optimizer.param_groups:
                for p in group["params"]:
                    if p.grad is not None:
                        p.grad.mul_(1.0 / total_n)
            grad_norm = torch.nn.utils.clip_grad_norm_(
                [p for group in self.optimizer.param_groups for p in group["params"]],
                self.clip_norm)
            if not bool(torch.isfinite(grad_norm)):
                raise SynLabError(ErrorCode.TRAIN_NONFINITE,
                                  f"non-finite gradient norm at step {self.step_index}",
                                  stage="training.trainer.fit")
            self.optimizer.step()
            self.scheduler.step()
            self.metrics.grad_norm_history.append(float(grad_norm))
            self.metrics.effective_denominator += float(total_n)
            self.metrics.steps = self.step_index
        self.metrics.wall_seconds += time.perf_counter() - started
        self.stopped_at_step = self.step_index
        return self.metrics.as_dict()

    def _micro_record(self, batch: TrainingBatch, spec, n_eff: float) -> dict[str, Any]:
        exposure = batch.exposure()
        self.metrics.microbatches += 1
        self.metrics.samples += batch.features.n_fragments
        self.metrics.r2_edges_exposed += exposure["r2_edges_exposed"]
        self.metrics.legal_negatives += exposure["legal_negatives"]
        for fid in batch.features.fragment_ids:
            self.metrics.mothers_exposed.add(
                str(getattr(self.pool, "mother_of", {}).get(fid, "?")))
            self.metrics.lineages_exposed.add(
                str(getattr(self.pool, "lineage_cluster_of", {}).get(fid, "?")))
        for name, count in exposure["tier_histogram"].items():
            self.metrics.tier_histogram[name] = self.metrics.tier_histogram.get(name, 0) + count
        for name, count in (spec.tier_plan or {}).items():
            self.metrics.requested_tier_histogram[name] = (
                self.metrics.requested_tier_histogram.get(name, 0) + count)
        return {"draw_index": spec.draw_index, "sample_keys": spec.sample_keys(),
                "effective_queries": int(n_eff), "exposure": exposure,
                "tier_plan": spec.tier_plan}

    # ------------------------------------------------------------------ checkpoint
    def checkpoint_payload(self, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        torch = _torch()
        state = {
            "trainer_version": self.trainer_version,
            "model": self.model.encoder.state_dict(),
            "pair_head": (self.model.pair_head.state_dict()
                          if self.model.pair_head is not None else None),
            "optimizer": self.optimizer.state_dict(),
            "scheduler": self.scheduler.state_dict(),
            "step": self.step_index,
            "sampler_cursor": self.sampler.cursor() if self.sampler is not None else None,
            "rng_state": self.rng.bit_generator.state,
            "torch_rng_state": torch.get_rng_state(),
            "data_release_hash": self.release_hash,
            "recipe": dict(self.recipe),
            "encoder_version": self.model.index_identity().get("encoder_version"),
            "index_identity": self.model.index_identity(),
            "precision": self.precision,
            "precision_downgrade_reason": self.precision_downgrade_reason,
            "loss_weights": dict(self.loss_weights),
            "curriculum": {
                "enabled": self.curriculum.enabled, "control_arm": self.curriculum_control,
                "total_steps": self.curriculum.total_steps,
                "clean_minimum_fraction": self.curriculum.clean_minimum_fraction,
            },
            "metrics": self.metrics.as_dict(),
            "reproducibility_level": REPRODUCIBILITY_LEVEL,
            "history_tail": [h["sample_keys"] for h in self.history[-4:]],
        }
        if extra:
            state["extra"] = dict(extra)
        state["payload_hash"] = hash_json(_hashable_state({
            k: v for k, v in state.items()
            if k not in ("optimizer", "scheduler", "torch_rng_state", "rng_state")
        }))
        return state

    def save_checkpoint(self, path: str | os.PathLike[str] | None = None, *,
                        extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        torch = _torch()
        if path is None:
            if self.out_dir is None:
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  "no checkpoint path and no out_dir configured",
                                  stage="training.trainer.save_checkpoint")
            path = self.out_dir / f"checkpoint_step{self.step_index}.pt"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.checkpoint_payload(extra=extra)
        torch.save(payload, path)
        record: dict[str, Any] = {"path": str(path), "step": self.step_index,
                                  "payload_hash": payload["payload_hash"],
                                  "sampler_cursor": payload["sampler_cursor"],
                                  "reproducibility_level": REPRODUCIBILITY_LEVEL}
        if self.store is not None:
            from ..roles import ROLE_CHECKPOINT, SCHEMA_CHECKPOINT

            asset = self.store.commit_asset(
                role=ROLE_CHECKPOINT, schema=SCHEMA_CHECKPOINT, unit="1", frame="NA",
                payload={"bytes": path.read_bytes()},
                meta={"step": self.step_index, "payload_hash": payload["payload_hash"],
                      "encoder_version": payload["encoder_version"],
                      "release_hash": self.release_hash, "recipe": dict(self.recipe),
                      "precision": self.precision},
                ancestry=[], lineage_id=None, split="train",
            )
            record["asset_id"] = asset.asset_id
            record["asset_hash"] = asset.blob_hash
        return record

    def load_checkpoint(self, checkpoint: Any, *, map_location: str = "cpu") -> dict[str, Any]:
        torch = _torch()
        if isinstance(checkpoint, (str, os.PathLike)):
            path = Path(checkpoint)
            if not path.exists():
                raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                                  f"checkpoint {path} not found",
                                  stage="training.trainer.load_checkpoint")
            payload = torch.load(path, map_location=map_location, weights_only=False)
        elif isinstance(checkpoint, Mapping):
            payload = dict(checkpoint)
        else:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "unsupported checkpoint reference",
                              stage="training.trainer.load_checkpoint")
        if self.release_hash and payload.get("data_release_hash") not in (None, "", self.release_hash):
            raise SynLabError(
                ErrorCode.REPLAY_MISMATCH,
                f"checkpoint data release {payload.get('data_release_hash')!r} != current "
                f"{self.release_hash!r}; refusing to resume a different dataset",
                stage="training.trainer.load_checkpoint",
            )
        return payload

    def resume(self, checkpoint: Any, *, steps: int | None = None, **kwargs) -> dict[str, Any]:
        """Restore state from the **acknowledged** draw cursor and continue training.

        Draws that were produced (prefetched) but never acknowledged are discarded and
        deterministically recomputed from the cursor.
        """
        torch = _torch()
        payload = self.load_checkpoint(checkpoint, **kwargs)
        self.model.encoder.load_state_dict(payload["model"])
        if self.model.pair_head is not None and payload.get("pair_head"):
            self.model.pair_head.load_state_dict(payload["pair_head"])
        self.optimizer.load_state_dict(payload["optimizer"])
        self.scheduler.load_state_dict(payload["scheduler"])
        self.step_index = int(payload["step"])
        if self.sampler is not None and payload.get("sampler_cursor"):
            before = self.sampler.acknowledged_draws
            self.sampler.resume_from(payload["sampler_cursor"])
            discarded = max(0, before - self.sampler.acknowledged_draws)
        else:
            discarded = 0
        if payload.get("rng_state") is not None:
            self.rng.bit_generator.state = payload["rng_state"]
        if payload.get("torch_rng_state") is not None:
            torch.set_rng_state(payload["torch_rng_state"])
        report = {
            "resumed_from_step": self.step_index,
            "discarded_prefetch": int(discarded),
            "sampler_cursor": self.sampler.cursor() if self.sampler is not None else None,
            "reproducibility_level": payload.get("reproducibility_level", REPRODUCIBILITY_LEVEL),
            "acknowledged_draws": (self.sampler.acknowledged_draws if self.sampler else 0),
            "recomputed_from_cursor": int(discarded) > 0,
        }
        if steps:
            metrics = self.fit(steps=steps)
            report["continued_metrics"] = metrics
        return report


__all__ = [
    "TRAINER_VERSION", "REPRODUCIBILITY_LEVEL", "CurriculumSchedule", "TrainMetrics", "Trainer",
]
