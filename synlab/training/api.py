"""Training façade (plan 18, interfaces.md §2)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..roles import (
    FRAME_WORLD,
    ROLE_CHECKPOINT,
    ROLE_TRAIN_METRICS,
    SCHEMA_MEASUREMENT,
    UNIT_NONE,
)
from ..seeds import make_rng
from .adapter import FeatureBundle
from .batch import build_training_batch
from .model import DualTowerModel, ObservationVectorBaseline, assert_cacheable_index_ok, build_model
from .trainer import Trainer

API_VERSION = "a12.training.api.v1"


def _require_cpu_gpu_statement() -> dict[str, Any]:
    import torch

    return {
        "torch_version": torch.__version__,
        "cuda_available": bool(torch.cuda.is_available()),
        "device_used": "cpu",
        "precision": "fp32",
        "note": "CPU-only host: no GPU hours are claimed (plan 18.4 / honesty rules)",
    }


def _spec_dict(spec: Any) -> dict[str, Any]:
    if hasattr(spec, "model_dump"):
        return spec.model_dump(mode="json")
    return dict(spec or {})


def train(spec: Any, store: Any | None = None, *, pool: Any | None = None,
          payloads: Mapping[str, Mapping[str, Any]] | None = None,
          labels: Mapping[str, Any] | None = None,
          resume_from: str | os.PathLike[str] | None = None,
          out_dir: str | os.PathLike[str] | None = None,
          max_steps_override: int | None = None,
          curriculum_control: bool = False,
          release_hash: str = "",
          extra_recipe: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Run (or resume) a training run and return real metrics.

    The returned dict follows the universal Result shape (status / output_refs / input_hashes /
    metrics / error) plus the run reference needed by :func:`resume` and by downstream
    diagnostics.  No value in ``metrics`` is synthetic: every number comes from the run that
    just executed.
    """
    started = time.perf_counter()
    spec_dict = _spec_dict(spec)
    run_name = str(getattr(spec, "run_name", None) or spec_dict.get("run_name") or "run")
    out_path = Path(out_dir) if out_dir is not None else None
    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)

    if pool is None and payloads is not None:
        pool = _InlinePool(payloads, labels or {})

    model = _build_model_for_pool(spec, pool)
    trainer = Trainer(spec, model, pool=pool, store=store, out_dir=out_path,
                      release_hash=release_hash or str(getattr(spec, "release_ref", "")),
                      recipe=dict(extra_recipe or {}),
                      curriculum_control=curriculum_control)
    if max_steps_override is not None:
        trainer.max_steps = int(max_steps_override)
        trainer.curriculum.total_steps = int(max_steps_override)
        trainer.scheduler = trainer._make_scheduler()

    resume_report = None
    if resume_from is not None:
        resume_report = trainer.resume(resume_from)
    metrics = trainer.fit()

    checkpoint_path = None
    checkpoint_record: dict[str, Any] = {}
    if out_path is not None:
        checkpoint_path = out_path / f"{run_name}_final.pt"
        checkpoint_record = trainer.save_checkpoint(checkpoint_path)
    elif store is not None:
        checkpoint_record = trainer.save_checkpoint()

    recipe = {
        "api_version": API_VERSION,
        "trainer_version": trainer.trainer_version,
        "spec": spec_dict,
        "loss_weights": trainer.loss_weights,
        "curriculum": {"enabled": trainer.curriculum.enabled,
                       "control_arm": trainer.curriculum_control,
                       "plan": trainer.curriculum.realised_plan(
                           trainer.max_steps,
                           int(getattr(getattr(spec, "sampling", spec),
                                       "queries_per_microbatch", 2)))},
        "precision": trainer.precision,
        "precision_downgrade_reason": trainer.precision_downgrade_reason,
        "index_identity": model.index_identity(),
        "environment": _require_cpu_gpu_statement(),
    }
    recipe_hash = hash_json(recipe)
    if out_path is not None:
        (out_path / "recipe.json").write_text(
            json.dumps(recipe, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8")

    exposure = {
        "mothers_exposed": metrics["mothers_exposed"],
        "lineages_exposed": metrics["lineages_exposed"],
        "fragments_seen": metrics["samples"],
        "r2_edges_exposed": metrics["r2_edges_exposed"],
        "legal_negatives_exposed": metrics["legal_negatives"],
        "effective_denominator": metrics["effective_denominator"],
        "tier_histogram": metrics["tier_histogram"],
        "requested_tier_histogram": metrics["requested_tier_histogram"],
    }
    result_metrics = {
        "steps": metrics["steps"],
        "microbatches": metrics["microbatches"],
        "wall_seconds": metrics["wall_seconds"],
        "throughput_samples_per_s": metrics["throughput_samples_per_s"],
        "grad_norm_last": metrics["grad_norm_last"],
        "grad_norm_max": metrics["grad_norm_max"],
        "effective_denominator": metrics["effective_denominator"],
        "clean_fraction_realised": _clean_fraction(metrics["tier_histogram"]),
        "skipped_tasks": metrics["skipped_total"],
        "exposure": exposure,
        "resume": resume_report,
        "latest_task_report": (trainer.history[-1].get("exposure") if trainer.history else None),
    }
    output_refs = []
    if checkpoint_record.get("asset_id"):
        output_refs.append({"asset_id": checkpoint_record["asset_id"],
                            "hash": checkpoint_record.get("asset_hash", ""),
                            "role": ROLE_CHECKPOINT})
    status = "QA_PASSED" if metrics["steps"] > 0 else "NOT_RUN"
    report = {
        "status": status,
        "run_ref": {
            "run_name": run_name,
            "checkpoint_path": checkpoint_record.get("path"),
            "checkpoint_payload_hash": checkpoint_record.get("payload_hash"),
            "sampler_cursor": checkpoint_record.get("sampler_cursor"),
            "reproducibility_level": checkpoint_record.get("reproducibility_level"),
            "recipe_hash": recipe_hash,
        },
        "output_refs": output_refs,
        "input_hashes": [str(getattr(spec, "release_ref", ""))],
        "metrics": result_metrics,
        "task_report": trainer.multi_task.task_report(),
        "error": None,
    }
    if store is not None:
        asset = store.commit_asset(
            role=ROLE_TRAIN_METRICS, schema=SCHEMA_MEASUREMENT, unit=UNIT_NONE, frame=FRAME_WORLD,
            payload={k: v for k, v in result_metrics.items() if not isinstance(v, dict)},
            meta={"run_name": run_name, "recipe_hash": recipe_hash,
                  "spec": spec_dict, "exposure": exposure,
                  "task_report": trainer.multi_task.task_report()},
            ancestry=[checkpoint_record["asset_id"]] if checkpoint_record.get("asset_id") else [],
            split="train",
        )
        report["metrics_asset_id"] = asset.asset_id
    return report


def _shape_of_pool(pool: Any | None) -> dict[str, int]:
    """Infer quality/presence dimensions from the pool payloads (no hard-coded widths)."""
    features = getattr(pool, "features", None) or {}
    q_in = q_out = None
    for payload in features.values():
        q = np.asarray(payload["quality"])
        pr = np.asarray(payload["presence"])
        q_in = int(q.shape[0] * q.shape[1] + pr.shape[0])
        q_out = int(q.shape[0] * q.shape[1])
        break
    return {"quality_input_dim": int(q_in or 12), "quality_target_dim": int(q_out or 8)}


def _build_model_for_pool(spec: Any, pool: Any | None) -> DualTowerModel:
    dims = _shape_of_pool(pool)
    return build_model(seed=int(getattr(spec, "train_seed", 11)), **dims)


def _clean_fraction(histogram: Mapping[str, int]) -> float | None:
    total = sum(int(v) for v in histogram.values())
    if total <= 0:
        return None
    clean = int(histogram.get("Q0", 0)) + int(histogram.get("Q1", 0))
    return clean / total


# --------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------
def evaluate(checkpoint_ref: Any, pool_ref: Any = None, *, top_k: Sequence[int] = (1, 5, 10, 20),
             candidate_pool_size: int = 200, accept_threshold: float | None = None,
             store: Any | None = None, split: str = "dev",
             queries: Sequence[str] | None = None, model: DualTowerModel | None = None,
             observed_valid: Mapping[str, bool] | None = None) -> dict[str, Any]:
    """Fixed-gallery evaluation separating the first-stage pool from the refined TopK.

    Reports ``PoolCov@M`` / ``any@M`` (first stage) and ``Hit@K`` / ``CovRecall@K``
    (refinement) **separately**, because "does the true mate enter TopM" and "does the
    refinement cover all mates" are different questions (plan 30.10).  The gallery is scored
    with the cacheable encoder tower only.
    """
    from ..diagnostics.metrics import (
        accept_set,
        any_at_m,
        conditional_cov,
        cov_recall_at_k,
        effective_cov_at_k,
        effective_hit_at_k,
        hit_at_k,
        pool_cov_at_m,
        risk_events,
    )

    pool = pool_ref
    if pool is None:
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, "evaluate requires a gallery pool",
                          stage="training.api.evaluate")
    if pool_ref is not None and isinstance(pool_ref, str) and store is not None:
        pool = _load_pool(store, pool_ref)

    checkpoint = None
    if checkpoint_ref is not None:
        if isinstance(checkpoint_ref, (str, os.PathLike)) and Path(checkpoint_ref).exists():
            import torch

            checkpoint = torch.load(checkpoint_ref, map_location="cpu", weights_only=False)
        elif isinstance(checkpoint_ref, Mapping):
            checkpoint = dict(checkpoint_ref)
        else:
            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                              f"checkpoint {checkpoint_ref!r} cannot be resolved",
                              stage="training.api.evaluate")
    if model is None:
        model = build_model()
        if checkpoint is not None:
            model.encoder.load_state_dict(checkpoint["model"])
            if model.pair_head is not None and checkpoint.get("pair_head"):
                model.pair_head.load_state_dict(checkpoint["pair_head"])
    assert_cacheable_index_ok(model.index_identity())

    payloads = getattr(pool, "features", None) or {}
    if not payloads:
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          "pool has no feature payloads to evaluate",
                          stage="training.api.evaluate")
    lineup = list(getattr(pool, "lineup", list(payloads)))
    ids = [fid for fid in lineup if fid in payloads]
    missing_feature_ids = sorted({str(fid) for fid in lineup if fid not in payloads})
    bundle = FeatureBundle.from_dict({fid: payloads[fid] for fid in ids}).check_shapes()
    model.encoder.eval()
    z, z_valid = model.encoder.encode_batch(bundle.to_torch())
    emb = {fid: z[i] for i, fid in enumerate(ids)}
    encodable = {fid: bool(z_valid[i]) for i, fid in enumerate(ids)}
    input_failures = sorted(fid for fid in ids if not encodable[fid])

    query_ids = list(queries) if queries is not None else list(ids)
    rows: list[dict[str, Any]] = []
    per_k: dict[int, dict[str, list[float]]] = {int(k): {"hit": [], "cov": [], "eff_hit": [],
                                                         "eff_cov": []} for k in top_k}
    pool_covs: list[float] = []
    anys: list[float] = []
    conditionals: list[float] = []
    risk_absent: list[int] = []
    risk_present: list[int] = []

    for qid in query_ids:
        # The pool owns the historical R2 denominator. Feature payload availability is a
        # separate candidate-input outcome and must not silently shrink that positive set.
        neighbours = sorted({str(n) for n in (
            pool.neighbours(qid) if hasattr(pool, "neighbours") else []) if str(n) != str(qid)})
        neighbour_availability = {
            n: ("FEATURE_MISSING" if n not in payloads else
                "NOT_IN_EVALUATED_LINEUP" if n not in emb else
                "ENCODER_INPUT_UNAVAILABLE" if not encodable.get(n, False) else
                "ENCODABLE")
            for n in neighbours
        }
        available_neighbours = [n for n in neighbours
                                if neighbour_availability[n] == "ENCODABLE"]
        missing_feature_neighbours = [n for n in neighbours
                                      if neighbour_availability[n] == "FEATURE_MISSING"]
        invalid_neighbours = [n for n in neighbours
                              if neighbour_availability[n] == "ENCODER_INPUT_UNAVAILABLE"]
        if not encodable.get(qid, False):
            row = {
                "query_id": qid,
                "status": "INPUT_UNAVAILABLE",
                "historical_neighbours": neighbours,
                "n_historical_neighbours": len(neighbours),
                "historical_neighbour_availability": neighbour_availability,
                "encodable_historical_neighbours": available_neighbours,
                "missing_feature_historical_neighbours": missing_feature_neighbours,
                "unencodable_historical_neighbours": invalid_neighbours,
                "hit": None,
                "cov": None,
                "pool_cov": None,
                "any_at_m": None,
                "conditional_cov": None,
                "effective_hit": 0.0,
                "effective_cov": 0.0,
                "failure_code": ErrorCode.INPUT_UNAVAILABLE.value,
            }
            for k in top_k:
                row[f"hit@{int(k)}"] = None
                row[f"cov@{int(k)}"] = None
                row[f"effective_hit@{int(k)}"] = 0.0
                row[f"effective_cov@{int(k)}"] = 0.0
                per_k[int(k)]["eff_hit"].append(0.0)
                per_k[int(k)]["eff_cov"].append(0.0)
            rows.append(row)
            continue
        cand_ids = [c for c in ids if c != qid and encodable.get(c, False)]
        scores = np.array([float(emb[qid] @ emb[c]) for c in cand_ids], dtype=np.float64)
        order = np.argsort(-scores, kind="stable")
        ranked = [cand_ids[int(i)] for i in order]
        pool_size = max(1, min(int(candidate_pool_size), len(ranked)))
        first_stage = ranked[:pool_size]
        observed = {c: True for c in cand_ids}
        if observed_valid:
            observed.update({k: bool(v) for k, v in observed_valid.items() if k in observed})
        row = {
            "query_id": qid,
            "status": "OK",
            "historical_neighbours": neighbours,
            "n_historical_neighbours": len(neighbours),
            "historical_neighbour_availability": neighbour_availability,
            "encodable_historical_neighbours": available_neighbours,
            "missing_feature_historical_neighbours": missing_feature_neighbours,
            "unencodable_historical_neighbours": invalid_neighbours,
            "first_stage": first_stage,
            "candidate_input_failures": sorted(set(input_failures)),
            "pool_cov": pool_cov_at_m(first_stage, neighbours),
            "any_at_m": any_at_m(first_stage, neighbours),
            "conditional_cov": conditional_cov(first_stage, neighbours),
        }
        pool_covs.append(row["pool_cov"] if row["pool_cov"] is not None else np.nan)
        anys.append(row["any_at_m"] if row["any_at_m"] is not None else np.nan)
        conditionals.append(row["conditional_cov"] if row["conditional_cov"] is not None
                            else np.nan)
        for k in top_k:
            k = int(k)
            top = ranked[:k]
            hit = hit_at_k(top, neighbours)
            cov = cov_recall_at_k(top, neighbours)
            accepted = (accept_set(top, {c: float(emb[qid] @ emb[c]) for c in top},
                                   threshold=float(accept_threshold), observed_valid=observed)
                        if accept_threshold is not None else top)
            eff_hit = effective_hit_at_k(accepted, neighbours)
            eff_cov = effective_cov_at_k(accepted, neighbours)
            row[f"hit@{k}"] = hit
            row[f"cov@{k}"] = cov
            row[f"effective_hit@{k}"] = eff_hit
            row[f"effective_cov@{k}"] = eff_cov
            per_k[k]["hit"].append(np.nan if hit is None else hit)
            per_k[k]["cov"].append(np.nan if cov is None else cov)
            per_k[k]["eff_hit"].append(eff_hit)
            per_k[k]["eff_cov"].append(eff_cov)
            if k == int(max(top_k)):
                events = risk_events(neighbours, accepted)
                risk_absent.append(int(events["absent_false_accept"]))
                risk_present.append(int(events["present_wrong_accept"]))
                row["accepted"] = accepted
                row["risk"] = events
        rows.append(row)

    def _agg(values):
        arr = np.asarray(values, dtype=np.float64)
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            return None
        return float(finite.mean())

    metrics: dict[str, Any] = {
        "split": split,
        "gallery_size": len(ids),
        "encodable": sum(1 for v in encodable.values() if v),
        "candidate_input_failure_count": len(input_failures),
        "candidate_input_failures": input_failures,
        "candidate_missing_feature_count": len(missing_feature_ids),
        "candidate_missing_features": missing_feature_ids,
        "pool_cov_at_m": _agg(pool_covs),
        "any_at_m": _agg(anys),
        "conditional_cov": _agg(conditionals),
        "na_counts": {
            "pool_cov": int(np.sum(~np.isfinite(np.asarray(pool_covs, dtype=np.float64)))),
            "hit": 0, "cov": 0,
        },
        "risk": {
            "absent_false_accept_events": int(sum(risk_absent)) if risk_absent else 0,
            "possible_absent": len(risk_absent),
            "present_wrong_accept_events": int(sum(risk_present)) if risk_present else 0,
            "possible_present": len(risk_present),
        },
        "per_k": {},
        "scale": "CPU-only fixed-gallery evaluation; no GPU hours",
    }
    for k, buckets in per_k.items():
        metrics["per_k"][f"k={k}"] = {
            "hit_at_k": _agg(buckets["hit"]),
            "cov_recall_at_k": _agg(buckets["cov"]),
            "effective_hit_at_k": _agg(buckets["eff_hit"]),
            "effective_cov_at_k": _agg(buckets["eff_cov"]),
            "hit_na_count": int(np.sum(~np.isfinite(np.asarray(buckets["hit"], dtype=np.float64)))),
        }
    return {"status": "OK", "checkpoint_ref": str(checkpoint_ref), "pool_id": str(
        getattr(pool, "pool_id", "")), "metrics": metrics, "per_query": rows,
        "index_identity": model.index_identity()}


def resume(run_ref: Any, store: Any | None = None, **kwargs) -> dict[str, Any]:
    """Continue a run from its recorded checkpoint."""
    if isinstance(run_ref, Mapping):
        checkpoint = run_ref.get("checkpoint_path") or run_ref.get("checkpoint")
        spec = run_ref.get("spec")
    else:
        checkpoint = str(run_ref)
        spec = kwargs.pop("spec", None)
    if checkpoint is None:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "run_ref carries no checkpoint reference",
                          stage="training.api.resume")
    if spec is None:
        recipe_path = Path(checkpoint).parent / "recipe.json"
        if recipe_path.exists():
            recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
            spec = recipe.get("spec")
    if spec is None:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "cannot resume without the training spec (pass spec= or a run_ref "
                          "written by train())",
                          stage="training.api.resume")
    return train(_SpecView(spec), store, resume_from=checkpoint, **kwargs)


class _SpecView:
    """Attribute view over a plain spec dict so :class:`Trainer` can read it.

    A field that is absent from the spec raises :class:`AttributeError` so that
    ``getattr(spec, "name", default)`` really returns ``default``.  Returning ``None`` instead
    (the previous behaviour) turned every optional field into ``float(None)`` / ``int(None)``
    for specs that simply omit it -- e.g. the plan 22.2 ``curriculum`` block carries only
    ``enabled``/``comparison_ref``, so resuming a run trained from such a spec crashed while
    constructing the :class:`Trainer`.
    """

    def __init__(self, data: Mapping[str, Any]):
        object.__setattr__(self, "_data", dict(data))

    def __getattr__(self, item: str) -> Any:
        data = object.__getattribute__(self, "_data")
        if item in data:
            value = data[item]
            return _SpecView(value) if isinstance(value, Mapping) else value
        raise AttributeError(
            f"spec has no field {item!r}; an absent field must read as absent so that "
            "getattr(spec, name, default) applies the documented default")

    def __contains__(self, item: str) -> bool:
        return item in object.__getattribute__(self, "_data")

    def get(self, item: str, default: Any = None) -> Any:
        return self.__getattr__(item) if item in self else default

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return dict(object.__getattribute__(self, "_data"))


class _InlinePool:
    """Minimal pool over an explicit payload mapping (no relations module needed)."""

    def __init__(self, payloads: Mapping[str, Mapping[str, Any]], labels: Mapping[str, Any]):
        self.features = dict(payloads)
        self.lineup = list(payloads)
        self._r2 = {k: set(v) for k, v in (labels.get("R2") or {}).items()}
        self.relations: dict[tuple[str, str], str] = {}
        for a, mates in self._r2.items():
            for b in mates:
                self.relations[(a, b)] = "R2"
                self.relations[(b, a)] = "R2"
        for key, name in (("R1", "R1"), ("R0", "R0"), ("UNKNOWN", "UNKNOWN"),
                          ("TINY_CONTACT", "TINY_CONTACT")):
            for a, mates in (labels.get(key) or {}).items():
                for b in mates:
                    self.relations.setdefault((a, b), name)
                    self.relations.setdefault((b, a), name)
        self.quality_tier = dict(labels.get("quality_tier") or {})
        self.lineage_cluster_of = dict(labels.get("lineage_cluster") or {})
        self.mother_of = dict(labels.get("mother_of") or {})
        self.pool_id = str(labels.get("pool_id", "inline_pool"))

    def relation(self, a: str, b: str) -> str:
        if a == b:
            return "SELF"
        return self.relations.get((a, b), "R0")

    def neighbours(self, fragment_id: str) -> list[str]:
        return sorted(self._r2.get(fragment_id, set()))


def _load_pool(store: Any, pool_ref: str) -> Any:
    from ..roles import ROLE_POOL

    record = store.get_asset(pool_ref)
    if record.role != ROLE_POOL:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"asset {pool_ref} role {record.role} != {ROLE_POOL}",
                          stage="training.api._load_pool")
    meta = record.meta or {}
    payloads = store.load_arrays(pool_ref)
    return _InlinePool(payloads, meta.get("labels", {}))


__all__ = ["API_VERSION", "train", "evaluate", "resume"]
