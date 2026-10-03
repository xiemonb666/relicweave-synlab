"""Real-package training smoke: real batch, real forward/backward, real checkpoint round-trip.

This module runs the **training path** against a real exported training package
(``data/a12_exports/closed_loop/training_package``) on CPU.  Nothing is synthesised:

* the batch comes from the package's own ``research/relations.parquet``,
  ``deploy/queries.parquet``, ``deploy/obs``, ``deploy/geometry`` and ``deploy/tokens``
  shards, read through :mod:`synlab.qc.loader_probe` (that reader is reused, not re-implemented);
* the model is :func:`synlab.training.model.build_model` with the observation-only input
  widths the package actually carries;
* every reported loss is the value of the loss that was just computed, and a task with no
  usable supervision is reported as **skipped with its reason**, never as ``0.0``.

Two facts about the current package are structural and are reported, not worked around:

1. the exported relation table contains **only R2 rows** (no confirmed R1/R0 with
   ``valid=true`` and ``loss_mask=true``), so the batch carries zero legal negatives and
   ``TrainingBatch.effective_query_count() == 0`` -- the trainer's own ``fit()`` refuses such an
   accumulation window (``no effective query``);
2. the R2 mates are *modelled but unobserved* (``queries.parquet`` has
   ``has_observation=false``; ``obs/geometry/tokens`` indexes carry only the three ``-m``
   fragments), so even the positive pairs are unencodable and the rank task has no pair to
   score.

Both are named per task, with the measured counts of the mask that rejected each row, in
``report["supervision"]`` (see :mod:`synlab.training.supervision`) -- a task that is *blocked*
(``n_valid_labels > 0``, ``n_allowed == 0``) is never reported as if it had no labels.

``run_smoke`` therefore drives the same per-microbatch call the trainer uses
(:meth:`synlab.training.trainer.Trainer.train_step`) with the real batch, performs the real
optimizer step, and separately records the ``fit()`` refusal as evidence.  It does not fake a
sampler, a negative, a label or a curve.

Usage::

    .venv\\Scripts\\python.exe -m synlab.training.smoke --package <dir> --steps 3 \
        --out data/a12/reports/training_smoke.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..qc.loader_probe import ExportedRelationPool, _batch_rows, _pool_id, load_features
from ..storage.export import TrainingPackage, _jsonable
from .api import _SpecView, _shape_of_pool
from .batch import QUALITY_TIERS, TrainingBatch
from .labels import PackageLabelSource
from .model import build_model
from .sampler import POINT_BUCKETS, SampledSpec, bucket_of
from .trainer import Trainer

SMOKE_SCHEMA = "synlab.training.smoke.v1"
DEFAULT_PACKAGE = Path("data/a12_exports/closed_loop/training_package")
#: a run name that cannot collide with a real training run
SMOKE_RUN_NAME = "real_package_smoke"

#: Complete ``synlab.train.v1``-shaped spec (every field the Trainer reads is present, and the
#: loss weights are the plan 18.3 starting values).  ``_SpecView`` is the very view
#: ``synlab.training.api.resume`` uses when it rebuilds the spec from ``recipe.json``.
SMOKE_SPEC: dict[str, Any] = {
    "schema": "synlab.train.v1",
    "run_name": SMOKE_RUN_NAME,
    "train_seed": 11,
    "release_ref": "",
    "retrieval": {"first_stage": "normalized_dual_encoder",
                  "refinement": "observed_local_pair_head", "temperature": 0.1},
    "inputs": {"feature_schema": "a12.obs.v1", "local_token_budget": 256},
    "sampling": {"queries_per_microbatch": 3, "positive_limit": 2, "legal_negative_limit": 8,
                 "negative_mix": {"R1": 0.5, "R0": 0.5}},
    "optimization": {"optimizer": "AdamW", "head_lr": 1e-4, "backbone_lr": 1e-5,
                     "weight_decay": 0.01, "warmup_fraction": 0.05, "gradient_clip_norm": 1.0,
                     "accumulation_steps": 1, "max_steps": 3, "precision": "fp32"},
    "losses": {"rank": 1.0, "view": 0.1, "correspondence": 0.1, "quality": 0.05,
               "contradiction": 0.1},
    "curriculum": {"enabled": False},
}


class TrainingPoolView(ExportedRelationPool):
    """Training-side view of the exported relation table.

    ``synlab.training.sampler.PoolIndex`` and ``build_training_batch`` read
    ``pool.neighbours(fid)`` as the **historical R2 mate set** (see ``PoolIndex.
    history_exclusions`` and ``LineageBalancedSampler._sample_row``), while
    ``qc.loader_probe.ExportedRelationPool.neighbours`` exposes the confirmed *negative*
    neighbours (R1/R0).  This view exposes the R2 mates under the training-side name and adds
    the ``lineup`` the sampler reads (``PoolIndex.lineage``); every other reading rule is
    inherited unchanged, so nothing is duplicated here.
    """

    def __init__(self, rows, *, lineup: Sequence[str], **kwargs) -> None:
        super().__init__(rows, **kwargs)
        self.lineup = [str(fid) for fid in lineup]

    def neighbours(self, fragment_id: str) -> set[str]:
        return self.mates(fragment_id)


def _jsonable_local(value: Any) -> Any:
    return _jsonable(value)


def _tensor_digest(pairs: Sequence[tuple[str, Any]]) -> str:
    """Deterministic sha256 over ``(name, shape, bytes)`` of an ordered parameter list."""
    h = hashlib.sha256()
    for name, tensor in pairs:
        arr = np.ascontiguousarray(tensor.detach().cpu().numpy())
        h.update(str(name).encode("utf-8"))
        h.update(str(arr.shape).encode("utf-8"))
        h.update(arr.tobytes())
    return "sha256:" + h.hexdigest()


def _model_digest(model) -> str:
    pairs: list[tuple[str, Any]] = list(model.encoder.named_parameters())
    if model.pair_head is not None:
        pairs += list(model.pair_head.named_parameters(prefix="pair_head."))
    return _tensor_digest(pairs)


def _parameter_counts(model) -> dict[str, int]:
    def total(named) -> int:
        return int(sum(int(p.numel()) for _, p in named))

    groups = model.parameter_groups(head_lr=1e-4, backbone_lr=1e-5)
    return {
        "encoder": total(model.encoder.named_parameters()),
        "pair_head": total(model.pair_head.named_parameters()) if model.pair_head else 0,
        "total": total(model.encoder.named_parameters())
        + (total(model.pair_head.named_parameters()) if model.pair_head else 0),
        "backbone_group": sum(int(p.numel()) for p in groups[1]["params"]) if len(groups) > 1 else 0,
        "head_group": sum(int(p.numel()) for p in groups[0]["params"]) if groups else 0,
    }


# --------------------------------------------------------------------------------------
# Real inputs
# --------------------------------------------------------------------------------------
def load_real_inputs(package_dir: str | Path, *, token_budget: int | None = 256
                     ) -> dict[str, Any]:
    """Read the real package into ``(package, pool, payloads, rows, relations, queries)``.

    The fragment-id set and the row split follow ``qc.loader_probe.probe_training_package``
    exactly (same helpers: ``load_features``, ``ExportedRelationPool``, ``_batch_rows``).
    """
    package = TrainingPackage(package_dir, access="research")
    verify = package.verify_files()
    relations = package.relations()
    queries = package.queries()
    observed = set(package.observed_ids())

    fragment_ids = [str(row.get("fragment_id") or _query_fragment(row)) for row in queries]
    fragment_ids = [f for f in dict.fromkeys(fragment_ids) if f in observed]
    for candidate in sorted({str(r.get("candidate", "")) for r in relations if r.get("candidate")}):
        if candidate in observed and candidate not in fragment_ids:
            fragment_ids.append(candidate)

    payloads = load_features(package, fragment_ids, token_budget=token_budget)
    pool = TrainingPoolView(relations, lineup=fragment_ids, pool_id=_pool_id(relations))
    pool.features = payloads
    rows = _batch_rows(relations, fragment_ids, pool)
    return {"package": package, "verify": verify, "relations": relations, "queries": queries,
            "fragment_ids": fragment_ids, "payloads": payloads, "pool": pool, "rows": rows}


def _query_fragment(row: Mapping[str, Any]) -> str:
    query_id = str(row.get("query_id", ""))
    return query_id.split("::", 1)[1] if "::" in query_id else query_id


def _tier_plan(pool, rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Real quality-tier histogram of the queries in these rows (Q0 unless the pool says otherwise)."""
    tiers = getattr(pool, "quality_tier", {}) or {}
    plan = {name: 0 for name in QUALITY_TIERS}
    for row in rows:
        tier = int(tiers.get(str(row["query"]), 0))
        plan[QUALITY_TIERS[tier] if 0 <= tier < len(QUALITY_TIERS) else f"T{tier}"] += 1
    return plan


def _row_bucket(pool, rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Real view/point bucket of these rows, computed from the packaged shards."""
    features = getattr(pool, "features", {}) or {}
    views, points = [], []
    for row in rows:
        payload = features.get(str(row["query"])) or {}
        views.append(int(np.asarray(payload["global_rgb"]).shape[0]) if payload else 1)
        points.append(int(np.sum(np.asarray(payload["point_valid"]))) if payload else 0)
    return {"views": bucket_of(int(np.ceil(np.mean(views)))) if rows else 1,
            "points": bucket_of(int(np.ceil(np.mean(points))), POINT_BUCKETS) if rows else 0}


def _rank_unavailability_reason(batch: TrainingBatch, pos: np.ndarray,
                               neg: np.ndarray) -> str:
    """Measured reason the rank task has no supervision in *this* batch.

    Only facts the batch itself carries are used here (the encodability of a pair needs the
    encoder, so that half is reported by ``compute_losses``'s diagnostics and by
    ``report["supervision"]``).
    """
    n_pos, n_neg = int(pos.sum()), int(neg.sum())
    if n_pos == 0:
        return "the exported relation table carries no supervised R2 pair"
    if n_neg == 0:
        return (f"the exported relation table carries {n_pos} supervised R2 pair(s) and no "
                "confirmed R1/R0 row (valid=true and loss_mask=true), so a query has no legal "
                "negative to compete against")
    return f"{n_neg} legal negative pair(s) are present; see supervision.rank for the mask"


# --------------------------------------------------------------------------------------
# Batch / model / step
# --------------------------------------------------------------------------------------
def _sample_spec(rows: Sequence[Mapping[str, Any]], pool, *, draw_index: int = 0) -> SampledSpec:
    """A :class:`SampledSpec` carrying the **real** exported rows (no sampler invention)."""
    return SampledSpec(rows=[dict(r) for r in rows], tier_plan=_tier_plan(pool, rows),
                       bucket=_row_bucket(pool, rows), draw_index=draw_index,
                       meta={"source": "exported relation table"})


def _batch_facts(batch: TrainingBatch) -> dict[str, Any]:
    pair = np.asarray(batch.pair_index)
    return {
        "shapes": {name: list(np.asarray(getattr(batch, name)).shape)
                   for name in ("pair_index", "pair_valid", "labels_relation", "label_pair_valid",
                                "pos_mask", "neg_mask", "excluded_mask", "exclusion_reason",
                                "quality_target", "quality_target_valid", "corr_weight",
                                "corr_row_valid", "corr_col_valid", "corr_kind", "contradiction",
                                "contradiction_valid", "quality_tier", "lineage_cluster",
                                "r1_fallback_used", "sample_keys")},
        "dtypes": {name: str(np.asarray(getattr(batch, name)).dtype)
                   for name in ("pair_index", "labels_relation", "pos_mask", "neg_mask",
                                "exclusion_reason")},
        "n_queries": int(batch.n_queries),
        "n_candidates": int(batch.n_candidates),
        "positives": int(batch.pos_mask.sum()),
        "negatives": int(batch.neg_mask.sum()),
        "excluded": int(batch.excluded_mask.sum()),
        "unconfirmed_candidates": int((~batch.label_pair_valid).sum()),
        "queries_with_positive": int((batch.pos_mask.sum(axis=1) > 0).sum()),
        "queries_with_legal_negative": int((batch.neg_mask.sum(axis=1) > 0).sum()),
        "effective_queries": int(batch.effective_query_count()),
        "exposure": _jsonable(batch.exposure()),
        "rows": [
            {"query": batch.features.fragment_ids[int(pair[i, 0, 0])],
             "positives": [batch.features.fragment_ids[int(pair[i, j, 1])]
                           for j in range(pair.shape[1]) if batch.pos_mask[i, j]],
             "negatives": [batch.features.fragment_ids[int(pair[i, j, 1])]
                           for j in range(pair.shape[1]) if batch.neg_mask[i, j]],
             "excluded": [batch.features.fragment_ids[int(pair[i, j, 1])]
                          for j in range(pair.shape[1]) if batch.excluded_mask[i, j]],
             "relation_codes": [int(c) for c in np.asarray(batch.labels_relation)[i]],
             "sample_key": str(np.asarray(batch.sample_keys)[i])}
            for i in range(pair.shape[0])
        ],
    }


def _run_step(trainer: Trainer, batch: TrainingBatch, *, accumulate: float = 1.0) -> dict[str, Any]:
    """One real forward/backward + optimizer step, mirroring ``Trainer.fit``'s inner body.

    ``accumulate`` is the effective-query weight of the microbatch.  It is 1.0 here because
    this batch has no effective query at all (no legal negative exists in the package), so the
    effective-query-weighted mean of :meth:`Trainer.fit` has no denominator to apply; the
    gradient is therefore the plain gradient of the combined loss of this single microbatch.
    """
    torch = __import__("torch")
    t0 = time.perf_counter()
    trainer.optimizer.zero_grad(set_to_none=True)
    info = trainer.train_step(batch, accumulate=float(accumulate))
    record: dict[str, Any] = {
        "skipped": bool(info.get("skipped")),
        "skip_reason": info.get("reason"),
        "effective_queries": info.get("effective_queries"),
        "encodable_pairs": info.get("encodable_pairs"),
        "unencodable_pairs": info.get("unencodable_pairs"),
        "supervision": info.get("supervision"),
        "tasks": {name: {"skipped": bool(res.get("skipped")),
                         "reason": res.get("reason"),
                         "loss": (None if res.get("loss") is None else float(res["loss"])),
                         "n_valid": int(res.get("n_valid", 0)),
                         "n_allowed": int(res.get("n_allowed", res.get("n_valid", 0))),
                         "n_valid_labels": int(res.get("n_valid_labels",
                                                       res.get("n_valid", 0)) or 0),
                         "weight": float(res.get("weight", 0.0)),
                         "diagnostics": _jsonable(res.get("diagnostics", {}))}
                  for name, res in (info.get("report") or {}).items()},
    }
    if not record["skipped"]:
        record["loss"] = float(info["loss"])
        params = [p for group in trainer.optimizer.param_groups for p in group["params"]]
        grad_norm = torch.nn.utils.clip_grad_norm_(params, trainer.clip_norm)
        record["grad_norm"] = float(grad_norm)
        record["grad_finite"] = bool(torch.isfinite(grad_norm))
        trainer.optimizer.step()
        trainer.scheduler.step()
        trainer.step_index += 1
        record["lr_after_step"] = float(trainer.optimizer.param_groups[0]["lr"])
    record["optimizer_steps"] = int(trainer.step_index)
    record["param_digest"] = _model_digest(trainer.model)
    record["seconds"] = time.perf_counter() - t0
    return record


# --------------------------------------------------------------------------------------
# Smoke run
# --------------------------------------------------------------------------------------
def run_smoke(package_dir: str | Path = DEFAULT_PACKAGE, *, steps: int = 3,
              out_dir: str | Path | None = None, token_budget: int = 256,
              include_loader_probe: bool = True) -> dict[str, Any]:
    """Run the smoke and return the report (also written next to ``out_dir`` when given)."""
    torch = __import__("torch")
    started = time.perf_counter()
    report: dict[str, Any] = {"schema": SMOKE_SCHEMA, "package_dir": str(package_dir),
                             "steps_requested": int(steps), "ok": False}
    real = load_real_inputs(package_dir, token_budget=token_budget)
    package, pool, rows = real["package"], real["pool"], real["rows"]
    manifest = package.manifest

    report["package"] = {
        "manifest_schema": manifest.get("schema"),
        "package_schema": manifest.get("package_schema"),
        "package_id": manifest.get("package_id"),
        "release_id": manifest.get("release_id"),
        "release_manifest_hash": manifest.get("release_manifest_hash"),
        "counts": _jsonable(manifest.get("counts")),
        "counts_total": _jsonable(manifest.get("counts_total")),
        "files_in_manifest": len(manifest.get("files", [])),
        "files_verified": bool(real["verify"]["ok"]),
        "files_checked": int(real["verify"]["files_checked"]),
        "bytes_total": manifest.get("bytes_total"),
        "relation_rows": len(real["relations"]),
        "relation_kind_histogram": _kind_histogram(real["relations"]),
        "query_rows": len(real["queries"]),
        "queries_with_observation": sum(1 for q in real["queries"]
                                        if str(q.get("has_observation")).lower() == "true"),
        "fragments_in_batch_scope": len(real["fragment_ids"]),
        "observed_fragments": sorted(package.observed_ids()),
    }
    if include_loader_probe:
        from ..qc.loader_probe import probe_training_package

        probe = probe_training_package(package_dir)
        report["loader_probe"] = {
            "ok": probe.get("ok"), "files_ok": probe.get("files_ok"),
            "counts": probe.get("counts"), "batch_fragments": probe.get("batch_fragments"),
            "batch_rows": probe.get("batch_rows"),
            "batch": {k: v for k, v in (probe.get("batch") or {}).items() if k != "exposure"},
            "negative_audit": probe.get("negative_audit"),
            "real_denominator": probe.get("real_denominator"),
            "seconds": probe.get("seconds"),
            "report_path": probe.get("report_path"),
        }

    # ---- model + trainer (same construction path as synlab.training.api.train) ----------
    dims = _shape_of_pool(pool)
    model = build_model(seed=int(SMOKE_SPEC["train_seed"]), **dims)
    spec = _SpecView(SMOKE_SPEC)
    out_path = Path(out_dir) if out_dir is not None else None
    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)
    release_hash = str(manifest.get("release_manifest_hash") or manifest.get("manifest_hash") or "")
    # the label side of the package is read here and handed to the batch builder; without this
    # wiring the correspondence/quality tensors stay zero however much the package stores
    label_source = PackageLabelSource.from_package(package)
    report["labels"] = label_source.report()
    trainer = Trainer(spec, model, pool=pool, out_dir=out_path, release_hash=release_hash,
                      label_source=label_source,
                      recipe={"smoke": True, "package_id": manifest.get("package_id"),
                              "source": "synlab.training.smoke"})
    report["model"] = {
        "index_identity": model.index_identity(),
        "parameters": _parameter_counts(model),
        "quality_input_dim": dims["quality_input_dim"],
        "quality_target_dim": dims["quality_target_dim"],
        "device": "cpu",
        "torch_version": torch.__version__,
        "cuda_available": bool(torch.cuda.is_available()),
        "precision": trainer.precision,
        "precision_downgrade_reason": trainer.precision_downgrade_reason,
        "loss_weights": dict(trainer.loss_weights),
        "temperature": trainer.temperature,
        "initial_param_digest": _model_digest(model),
    }

    # ---- the real batch -----------------------------------------------------------------
    sample_spec = _sample_spec(rows, pool)
    batch = trainer.build_batch(sample_spec)
    report["batch"] = _batch_facts(batch)
    report["batch"]["source"] = {
        "reader": "synlab.qc.loader_probe.load_features / ExportedRelationPool / _batch_rows",
        "relations_parquet": "research/relations.parquet",
        "queries_parquet": "deploy/queries.parquet",
        "rows_read": len(rows),
        "rows_with_positives": sum(1 for r in rows if r["positives"]),
        "rows_with_negatives": sum(1 for r in rows if r["negatives"]),
        "sample_key_prefix": "probe::",
        "tier_plan": sample_spec.tier_plan,
        "bucket": sample_spec.bucket,
        "fragment_ids": list(batch.features.fragment_ids),
        "fragments_with_observation": int(np.count_nonzero(batch.features.tokens_total > 0)),
        "fragments_without_observation": int(np.count_nonzero(batch.features.tokens_total == 0)),
        "tokens_total": int(np.sum(batch.features.tokens_total)),
        "tokens_valid": int(batch.features.token_valid.sum()),
        "points_valid": int(batch.features.point_valid.sum()),
    }
    pos = np.asarray(batch.pos_mask)
    neg = np.asarray(batch.neg_mask)
    report["supervision_availability"] = {
        "positive_pairs": int(pos.sum()),
        "legal_negative_pairs": int(neg.sum()),
        "queries_eligible_for_rank_loss": int(np.count_nonzero((pos.sum(axis=1) > 0)
                                                              & (neg.sum(axis=1) > 0))),
        "reason_rank_unnavailable": _rank_unavailability_reason(batch, pos, neg),
        "correspondence_labels_in_package": int(
            report["labels"]["correspondence"]["samples"]),
        "valid_quality_targets": int(np.asarray(batch.quality_target_valid).sum()),
        "quality_target_channel": str(report["labels"]["quality"]["channel"]),
        "valid_contradiction_labels": int(np.asarray(batch.contradiction_valid).sum()),
        "views_per_observed_fragment": sorted({int(np.count_nonzero(batch.features.global_valid[i]))
                                               for i in range(batch.features.n_fragments)}),
    }

    # ---- the trainer's own fit() on the sampler path (recorded refusal) -----------------
    refusal: dict[str, Any] = {"attempted": True}
    probe_model = build_model(seed=int(SMOKE_SPEC["train_seed"]), **dims)
    probe_trainer = Trainer(spec, probe_model, pool=pool, out_dir=None, release_hash=release_hash,
                            label_source=label_source)
    try:
        metrics = probe_trainer.fit(steps=1)
        refusal.update({"raised": None, "metrics": _jsonable(metrics)})
    except Exception as exc:  # noqa: BLE001 - the refusal *is* the measurement
        refusal.update({"raised": type(exc).__name__,
                        "error_code": str(getattr(getattr(exc, "code", None), "value", "")),
                        "message": str(exc),
                        "microbatches_sampled": int(probe_trainer.metrics.microbatches),
                        "step_index": int(probe_trainer.step_index)})
    report["trainer_fit_refusal"] = refusal

    # ---- real steps on the real batch ---------------------------------------------------
    step_records = [_run_step(trainer, batch) for _ in range(int(steps))]
    report["steps"] = {
        "optimizer_steps_taken": int(trainer.step_index),
        "records": step_records,
        "loss_sequence": [r.get("loss") for r in step_records],
        "grad_norm_sequence": [r.get("grad_norm") for r in step_records],
        "wall_seconds": float(sum(r["seconds"] for r in step_records)),
        "trainer_metrics": _jsonable(trainer.metrics.as_dict()),
        "multi_task_report": _jsonable(trainer.multi_task.task_report()),
    }
    # per-task supervision accounting of the *real* batch: n_valid (labels that exist) against
    # n_allowed (rows that survive every mask the loss applies), with the measured blocker
    report["supervision"] = _jsonable(step_records[0].get("supervision") or {})

    # ---- checkpoint: save -> reload -> one more identical step ---------------------------
    ckpt_path = (out_path / f"{SMOKE_RUN_NAME}_step{trainer.step_index}.pt") if out_path else None
    if ckpt_path is None:
        report["checkpoint"] = {"saved": False,
                                "reason": "no out_dir given; a checkpoint file was not written"}
    else:
        save_record = trainer.save_checkpoint(ckpt_path)
        payload = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        # the report must describe *this* file: prove the bytes on disk carry the weights the
        # in-memory model had at save time (``payload_hash`` covers neither the optimizer nor the
        # RNG blobs, and those two make two saves of identical weights differ byte-for-byte)
        file_round_trip = _compare_checkpoint(trainer.model, payload)
        digest_at_save = _model_digest(trainer.model)
        # A. continue in-process
        loss_a = _run_step(trainer, batch)
        digest_a = _model_digest(trainer.model)
        # B. rebuild from the checkpoint and continue
        resumed_model = build_model(seed=int(SMOKE_SPEC["train_seed"]), **dims)
        resumed_trainer = Trainer(spec, resumed_model, pool=pool, out_dir=out_path,
                                  release_hash=release_hash, label_source=label_source)
        resume_report = resumed_trainer.resume(ckpt_path)
        digest_loaded = _model_digest(resumed_trainer.model)
        # compare *as loaded*: the extra step below is a real optimizer step that changes the
        # weights, so comparing after it would report a mismatch that says nothing about the
        # round trip (it reported eight "value mismatch" entries for exactly that reason).
        state_vs_checkpoint = _compare_checkpoint(resumed_trainer.model, payload)
        loss_b = _run_step(resumed_trainer, batch)
        digest_b = _model_digest(resumed_trainer.model)
        # C. a different data release must be refused, not silently resumed
        other = build_model(seed=int(SMOKE_SPEC["train_seed"]), **dims)
        other_trainer = Trainer(spec, other, pool=pool, out_dir=out_path,
                                release_hash="sha256:not-the-same-release",
                                label_source=label_source)
        try:
            other_trainer.resume(ckpt_path)
            mismatch = {"raised": None}
        except Exception as exc:  # noqa: BLE001
            mismatch = {"raised": type(exc).__name__,
                        "error_code": str(getattr(getattr(exc, "code", None), "value", "")),
                        "message": str(exc)}
        report["checkpoint"] = {
            "saved": True,
            "path": save_record["path"],
            "bytes": int(Path(save_record["path"]).stat().st_size),
            "step": int(save_record["step"]),
            "payload_hash": save_record["payload_hash"],
            "sampler_cursor": _jsonable(save_record["sampler_cursor"]),
            "reproducibility_level": save_record["reproducibility_level"],
            "data_release_hash": payload.get("data_release_hash"),
            "model_state_vs_checkpoint": state_vs_checkpoint,
            "file_matches_model_at_save": file_round_trip,
            "param_digest_at_save": digest_at_save,
            "param_digest_after_load": digest_loaded,
            "param_digest_after_extra_step_live": digest_a,
            "param_digest_after_extra_step_resumed": digest_b,
            "load_is_bitwise_identical": digest_loaded == digest_at_save,
            "extra_step_loss_live": loss_a.get("loss"),
            "extra_step_loss_resumed": loss_b.get("loss"),
            "extra_step_loss_equal": (loss_a.get("loss") == loss_b.get("loss")),
            "extra_step_loss_delta": (None if loss_a.get("loss") is None or loss_b.get("loss") is None
                                      else float(abs(loss_a["loss"] - loss_b["loss"]))),
            "extra_step_digest_equal": digest_a == digest_b,
            "extra_step_grad_norm_live": loss_a.get("grad_norm"),
            "extra_step_grad_norm_resumed": loss_b.get("grad_norm"),
            "extra_step_live": loss_a,
            "extra_step_resumed": loss_b,
            "resume_report": _jsonable(resume_report),
            "release_mismatch_refused": mismatch,
        }

    report["honesty"] = {
        "synthesised_labels": 0,
        "synthesised_negatives": 0,
        "tasks_skipped": sorted({name for r in step_records for name, t in r["tasks"].items()
                                 if t["skipped"]}),
        "skipped_task_reasons": {name: t["reason"] for r in step_records
                                 for name, t in r["tasks"].items() if t["skipped"]},
        "tasks_with_real_supervision": list(report.get("supervision", {}).get(
            "tasks_with_supervision", [])),
        "tasks_blocked_with_labels_present": sorted(
            name for name, task in (report.get("supervision", {}).get("tasks") or {}).items()
            if task["n_allowed"] == 0 and task.get("n_valid_labels", task["n_valid"]) > 0),
        "claim": ("the pipeline (read -> batch -> forward -> backward -> optimizer -> "
                  "checkpoint -> resume) is exercised on real bytes; no generalisation claim "
                  "is made from this package"),
    }

    checks = {
        "package_files_verified": bool(real["verify"]["ok"]),
        "batch_built": report["batch"]["n_queries"] > 0,
        "losses_finite": all(r.get("loss") is None or np.isfinite(r["loss"]) for r in step_records),
        "optimizer_steps_taken": int(trainer.step_index) >= int(steps),
        "checkpoint_consistent": bool(report.get("checkpoint", {}).get("extra_step_loss_equal")
                                      and report["checkpoint"].get("extra_step_digest_equal")
                                      and report["checkpoint"].get("load_is_bitwise_identical")
                                      and report["checkpoint"].get(
                                          "model_state_vs_checkpoint", {}).get("ok")
                                      and report["checkpoint"].get(
                                          "file_matches_model_at_save", {}).get("ok"))
        if report.get("checkpoint", {}).get("saved") else True,
    }
    report["checks"] = checks
    report["ok"] = all(checks.values())
    report["status"] = "PIPELINE_OK_DATA_INSUFFICIENT" if report["ok"] else "FAILED"
    report["wall_seconds"] = time.perf_counter() - started
    if out_path is not None:
        json_path = out_path / "training_smoke.json"
        json_path.write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2,
                                        sort_keys=True, default=str), encoding="utf-8")
        report["report_path"] = str(json_path)
    return report


def _kind_histogram(relations: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in relations:
        key = str(row.get("kind", "UNKNOWN"))
        out[key] = out.get(key, 0) + 1
    return out


def _compare_checkpoint(model, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Bitwise comparison of every loaded parameter against the checkpoint tensors.

    ``model`` must be the **just-resumed** model: ``smoke.run_smoke`` calls this immediately
    after ``Trainer.resume`` and before the extra verification step, because that step is a
    real optimizer step and would otherwise make the comparison report a difference that has
    nothing to do with checkpointing.
    """
    torch = __import__("torch")
    encoder_state = payload.get("model") or {}
    head_state = payload.get("pair_head") or {}
    checked, mismatches = 0, []
    for name, param in model.encoder.named_parameters():
        ref = encoder_state.get(name)
        if ref is None:
            mismatches.append(f"{name}: absent from checkpoint")
            continue
        checked += 1
        if not torch.equal(param.detach(), ref):
            mismatches.append(f"{name}: value mismatch")
    if model.pair_head is not None:
        for name, param in model.pair_head.named_parameters():
            ref = head_state.get(name)
            if ref is None:
                mismatches.append(f"pair_head.{name}: absent from checkpoint")
                continue
            checked += 1
            if not torch.equal(param.detach(), ref):
                mismatches.append(f"pair_head.{name}: value mismatch")
    return {"parameters_checked": checked, "mismatches": mismatches, "ok": not mismatches}


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def _summary(report: Mapping[str, Any]) -> str:
    lines = [f"status={report['status']} ok={report['ok']} schema={report['schema']}"]
    pkg = report.get("package", {})
    lines.append(f"package: files_verified={pkg.get('files_verified')} "
                 f"checked={pkg.get('files_checked')} relations={pkg.get('relation_rows')} "
                 f"kinds={pkg.get('relation_kind_histogram')} queries={pkg.get('query_rows')} "
                 f"observed={pkg.get('queries_with_observation')}")
    b = report.get("batch", {})
    lines.append(f"batch: Q={b.get('n_queries')} C={b.get('n_candidates')} "
                 f"pos={b.get('positives')} neg={b.get('negatives')} eff_queries={b.get('effective_queries')} "
                 f"pair_index={b.get('shapes', {}).get('pair_index')}")
    st = report.get("steps", {})
    lines.append(f"steps: {st.get('optimizer_steps_taken')} losses={st.get('loss_sequence')} "
                 f"grad_norms={st.get('grad_norm_sequence')} seconds={st.get('wall_seconds')}")
    for name, task in ((st.get("records") or [{}])[0].get("tasks") or {}).items():
        lines.append(f"  task {name}: skipped={task['skipped']} loss={task['loss']} "
                     f"n_valid={task['n_valid']} reason={task['reason']}")
    ck = report.get("checkpoint", {})
    if ck.get("saved"):
        lines.append(f"checkpoint: {ck.get('path')} bytes={ck.get('bytes')} "
                     f"payload_hash={ck.get('payload_hash')}")
        lines.append(f"  load_bitwise={ck.get('load_is_bitwise_identical')} "
                     f"extra_step_loss={ck.get('extra_step_loss_live')} vs "
                     f"{ck.get('extra_step_loss_resumed')} equal={ck.get('extra_step_loss_equal')} "
                     f"digest_equal={ck.get('extra_step_digest_equal')}")
    fit = report.get("trainer_fit_refusal", {})
    lines.append(f"trainer.fit(): raised={fit.get('raised')} code={fit.get('error_code')} "
                 f"message={fit.get('message')}")
    model = report.get("model", {}).get("parameters", {})
    lines.append(f"parameters: total={model.get('total')} encoder={model.get('encoder')} "
                 f"pair_head={model.get('pair_head')} "
                 f"backbone_group={model.get('backbone_group')} head_group={model.get('head_group')}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real-package training smoke (CPU)")
    parser.add_argument("--package", default=str(DEFAULT_PACKAGE))
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--token-budget", type=int, default=256)
    parser.add_argument("--out", default="data/a12/reports")
    parser.add_argument("--no-loader-probe", action="store_true")
    args = parser.parse_args(argv)

    report = run_smoke(args.package, steps=args.steps, out_dir=args.out,
                       token_budget=args.token_budget,
                       include_loader_probe=not args.no_loader_probe)
    print(_summary(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
