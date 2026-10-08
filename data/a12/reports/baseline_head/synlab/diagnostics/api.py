"""Diagnostics façade: ``run_diagnosis(spec, store)`` plus the frozen statistic helpers.

``run_diagnosis`` evaluates a **frozen** gallery and roster with a fixed scorer and writes
``per_query_metrics.parquet``, ``diagnostic_summary.parquet``, ``failure_counts.json``,
``run_spec.json`` and ``report.md``.  Cells that could not be produced are reported as
``NA``/``NOT_RUN`` with their reason; nothing is interpolated, fitted or filled with a random
curve.

Protocol guards
---------------
* ``DiagnosticSpec.confirmation.open == false`` refuses to use the confirm split as
  confirmation evidence (``EXPERIMENT_PROTOCOL_VIOLATION``) instead of quietly relabelling it;
* opening the confirmation records the frozen protocol hash and the opening time, and a failed
  opening may not be erased and re-used as a "first confirmation";
* the checkpoint, gallery, roster and scorer identities are all recorded in ``run_spec.json``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..canonical import hash_json
from ..config import load_diagnose_spec
from ..errors import ErrorCode, SynLabError
from ..roles import ROLE_POOL, ROLE_ROSTER
from ..schemas.runtime import QueryRosterEntry
from .metrics import aggregate_metrics, per_query_table  # noqa: F401  (façade re-export)
from .runner import (
    RUNNER_VERSION,
    Cell,
    CheckpointScorer,
    ClassicalScorer,
    DiagnosticRunner,
    Scorer,
    commit_report,
    write_reports,
)
from .stats import clopper_pearson_upper, paired_bootstrap_ci, summarise_risk_events

API_VERSION = "synlab.diagnostics.api.v1"

REPO_ROOT = Path(__file__).resolve().parents[2]

STATUS_OK = "QA_PASSED"


def _spec_dict(spec: Any) -> dict[str, Any]:
    if spec is None:
        return {}
    if hasattr(spec, "model_dump"):
        return spec.model_dump(mode="json", by_alias=True)
    if isinstance(spec, Mapping):
        return dict(spec)
    return dict(getattr(spec, "__dict__", {}) or {})


def load_spec(spec: Any) -> dict[str, Any]:
    if isinstance(spec, (str, Path)):
        return _spec_dict(load_diagnose_spec(spec))
    return _spec_dict(spec)


# --------------------------------------------------------------------------------------
# resolution helpers
# --------------------------------------------------------------------------------------
def _path_candidates(ref: str, store: Any) -> list[Path]:
    path = Path(ref)
    out = [path] if path.is_absolute() else [Path.cwd() / path, REPO_ROOT / path]
    if store is not None:
        out.append(Path(store.root) / path)
        if path.name and not path.is_absolute():
            out.append(Path(store.root) / "pools" / path.name)
    return out


def resolve_pool(store: Any, ref: Any, *, attach: bool = True) -> Any:
    """Resolve a pool from an object / asset id / portable JSON artifact."""
    from ..relations.api import load_pool, load_pool_json
    from ..relations.gallery import attach_features

    if ref is None:
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          "run_diagnosis requires a frozen candidate pool "
                          "(candidate_pool_ref or pool=)",
                          stage="diagnostics.resolve_pool")
    if hasattr(ref, "lineup") and hasattr(ref, "neighbours"):
        return ref
    if not isinstance(ref, (str, Path)):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"candidate_pool_ref must be a pool object, asset id or path, "
                          f"got {type(ref).__name__}",
                          stage="diagnostics.resolve_pool")
    text = str(ref)
    if store is not None:
        try:
            record = store.get_asset(text)
        except SynLabError:
            record = None
        if record is not None:
            if record.role != ROLE_POOL:
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  f"asset {text} role {record.role} is not {ROLE_POOL}",
                                  stage="diagnostics.resolve_pool")
            pool = load_pool(store, text)
            if attach:
                attach_features(pool, store)
            return pool
    for candidate in _path_candidates(text, store):
        if candidate.exists():
            pool, _rows = load_pool_json(candidate)
            if attach and store is not None:
                from ..relations.gallery import attach_features as _attach

                _attach(pool, store)
            return pool
    raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                      f"candidate pool {text!r} is neither a committed pool asset nor a portable "
                      f"pool artifact",
                      stage="diagnostics.resolve_pool")


def resolve_roster(store: Any, ref: Any, pool: Any) -> list[QueryRosterEntry]:
    """The frozen roster: explicit artifact when given, otherwise the pool's own roster."""
    from ..relations.api import load_roster_json

    if ref is None:
        roster = list(getattr(pool, "roster", []) or [])
        if not roster:
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                              "the pool carries no frozen query roster",
                              stage="diagnostics.resolve_roster")
        return roster
    if store is not None:
        try:
            record = store.get_asset(str(ref))
        except SynLabError:
            record = None
        if record is not None:
            rows = list(record.meta.get("roster") or [])
            if not rows:
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  f"roster asset {ref} carries no queries",
                                  stage="diagnostics.resolve_roster")
            return [QueryRosterEntry(**row) for row in rows]
    for candidate in _path_candidates(str(ref), store):
        if candidate.exists():
            rows = load_roster_json(candidate)
            if not rows:
                raise SynLabError(ErrorCode.SCHEMA_INVALID, f"roster {candidate} is empty",
                                  stage="diagnostics.resolve_roster")
            return [QueryRosterEntry(**row) for row in rows]
    raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                      f"query roster {ref!r} cannot be resolved",
                      stage="diagnostics.resolve_roster")


def resolve_scorer(store: Any, spec: Mapping[str, Any], pool: Any, *,
                   scorer: Any = None) -> tuple[Scorer, dict[str, Any]]:
    """Fixed scorer: an injected object, a checkpoint, or the documented shallow baseline."""
    if scorer is not None:
        if isinstance(scorer, Scorer):
            return scorer, {"source": "injected", "warning": None}
        return ClassicalScorer(str(scorer)), {"source": "injected_classical", "warning": None}
    checkpoint_ref = spec.get("checkpoint_ref")
    if checkpoint_ref:
        model = CheckpointScorer.from_ref(store, checkpoint_ref, pool=pool,
                                          seed=int(spec.get("train_seed", 11) or 11))
        return model, {"source": "checkpoint", "warning": None}
    return ClassicalScorer("shallow_fusion"), {
        "source": "shallow_observation_baseline",
        "warning": "DEPLOYMENT_MODEL_NOT_PROVIDED: no checkpoint_ref was given, so the "
                   "reported numbers are the shallow observation baseline only and are not "
                   "evidence about a trained model",
    }


# --------------------------------------------------------------------------------------
# run_diagnosis
# --------------------------------------------------------------------------------------
def run_diagnosis(spec: Any, store: Any = None, *, pool: Any = None, roster: Any = None,
                  scorer: Any = None, out_dir: str | Path | None = None,
                  perturbation: Any = None, write: bool = True) -> dict[str, Any]:
    """Run one frozen-protocol diagnosis and write the report artifacts."""
    started = time.perf_counter()
    cfg = load_spec(spec)
    protocol_id = str(cfg.get("protocol_id") or "diagnosis")
    split = str(cfg.get("evaluation_split", "dev"))
    confirmation = dict(cfg.get("confirmation") or {})
    confirmation_open = bool(confirmation.get("open", False))
    if split == "confirm" and not confirmation_open:
        raise SynLabError(
            ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION,
            "evaluation_split=confirm while confirmation.open is false: the confirm split may "
            "not be consumed as confirmation evidence, and a result obtained this way may not "
            "be reported as one (plan 30.13 / 30.15)",
            stage="diagnostics.run_diagnosis",
            measurements={"protocol_id": protocol_id, "split": split,
                          "confirmation_open": confirmation_open})

    pool_obj = pool if pool is not None else resolve_pool(store, cfg.get("candidate_pool_ref"))
    roster_entries = (list(roster) if isinstance(roster, (list, tuple))
                      else resolve_roster(store, roster if roster is not None
                                          else cfg.get("query_roster_ref"), pool_obj))
    scorer_obj, scorer_info = resolve_scorer(store, cfg, pool_obj, scorer=scorer)

    features = getattr(pool_obj, "features", None) or {}
    encodable_queries = [q.fragment_id for q in roster_entries if q.fragment_id in features]
    if not encodable_queries:
        raise SynLabError(
            ErrorCode.INPUT_UNAVAILABLE,
            f"none of the {len(roster_entries)} roster queries has a legal observation payload; "
            f"no diagnosis can be measured (candidates without encodable features stay in the "
            f"logical gallery and in N_G, they are never dropped from the denominator)",
            stage="diagnostics.run_diagnosis",
            measurements={"roster": len(roster_entries), "features_attached": len(features),
                          "gallery": len(getattr(pool_obj, "lineup", []) or [])})

    top_k = tuple(int(k) for k in (cfg.get("top_k") or [1, 5, 10, 20]))
    candidate_pool_sizes = tuple(int(m) for m in (cfg.get("candidate_pool_sizes")
                                                  or cfg.get("refinement_candidates")
                                                  or [50, 100, 200]))
    axes = [str(a) for a in (cfg.get("axes") or [])]
    levels = [int(l) for l in (cfg.get("levels") or [0, 1, 2, 3, 4])]
    statistics_cfg = dict(cfg.get("statistics") or {})

    from .runner import _jsonable  # local import keeps the module surface small

    perturbation_provider = perturbation
    perturbation_source = "injected" if perturbation is not None else None
    if perturbation_provider is None and axes:
        perturbation_provider = _degrade_perturbation(store)
        perturbation_source = ("degrade.api.apply_axis" if perturbation_provider is not None
                               else None)

    runner = DiagnosticRunner(
        pool=pool_obj, roster=roster_entries, scorer=scorer_obj, axes=axes, levels=levels,
        top_k=top_k, candidate_pool_sizes=candidate_pool_sizes, split=split,
        confirmation_open=confirmation_open, perturbation=perturbation_provider,
        perturbation_side=str(cfg.get("perturbation_side", "QUERY_ONLY")),
        seed=int((cfg.get("seeds") or [20261001])[0]),
        metrics_requested=[str(m) for m in (cfg.get("metrics") or [])])
    run = runner.run()

    run_spec = {
        "api_version": API_VERSION,
        "runner_version": RUNNER_VERSION,
        "protocol_id": protocol_id,
        "schema_id": cfg.get("schema_id", cfg.get("schema", "synlab.diagnose.v1")),
        "split": split,
        "confirmation": {
            "open": confirmation_open,
            "require_frozen_protocol": bool(confirmation.get("require_frozen_protocol", True)),
            "used_as_confirmation": bool(confirmation_open and split == "confirm"),
            "opened_at": time.time() if confirmation_open else None,
            "note": ("confirmation opened: this opening is recorded and a failed opening may not "
                     "be erased and re-used as a first confirmation"
                     if confirmation_open else
                     "confirmation closed: results are development evidence only"),
        },
        "pool": {
            "pool_id": str(getattr(pool_obj, "pool_id", "")),
            "gallery_version": str(getattr(pool_obj, "gallery_version", "")),
            "hash": str(getattr(pool_obj, "hash", "")),
            "scope": str(getattr(pool_obj, "scope", "")),
            "fragments": len(getattr(pool_obj, "lineup", []) or []),
            "candidates": len([fid for fid in (getattr(pool_obj, "lineup", []) or [])
                               if fid in features]),
            "features_attached": len(features),
            "queries": len(roster_entries),
            "queries_with_mates": sum(1 for q in roster_entries if q.mate_present),
            "roster_ref": str(cfg.get("query_roster_ref") or ""),
        },
        "scorer": {**scorer_obj.describe(), **scorer_info},
        "checkpoint_ref": cfg.get("checkpoint_ref"),
        "release_ref": cfg.get("release_ref"),
        "axes": axes,
        "levels": levels,
        "top_k": list(top_k),
        "candidate_pool_sizes": list(candidate_pool_sizes),
        "metrics_requested": list(cfg.get("metrics") or []),
        "perturbation": {"provider": perturbation_source,
                         "side": str(cfg.get("perturbation_side", "QUERY_ONLY")),
                         "paired_basis": bool(cfg.get("paired_basis", True))},
        "statistics": statistics_cfg,
        "seeds": list(cfg.get("seeds") or []),
        "environment": _environment(),
        "frozen_query_ids": bool(cfg.get("fixed_query_ids", True)),
        "include_pipeline_failures_in_primary_denominator": bool(
            cfg.get("include_pipeline_failures_in_primary_denominator", True)),
    }
    run_spec["protocol_hash"] = hash_json({k: v for k, v in run_spec.items()
                                           if k != "confirmation"})
    statistics = _statistics_block(run, statistics_cfg, top_k)
    run_spec["statistics_result"] = statistics

    outputs: dict[str, Any] = {}
    if write:
        target = (Path(out_dir) if out_dir is not None
                  else (Path(store.root) / "reports" / f"diagnosis_{protocol_id}"
                        if store is not None else Path.cwd() / "diagnosis" / protocol_id))
        outputs = write_reports(target, run=run, run_spec=run_spec, protocol_id=protocol_id)

    clean_cell = next((c for c in run["cells"] if c["cell_id"] == "clean"), None)
    status = STATUS_OK
    warnings: list[str] = []
    if scorer_info.get("warning"):
        warnings.append(str(scorer_info["warning"]))
        status = "QA_PASSED_SHALLOW_BASELINE"
    if clean_cell is None or clean_cell.get("status") != "OK":
        status = "FAILED"
        warnings.append("the clean baseline cell did not produce a measurement")

    report = {
        "ok": status.startswith("QA_PASSED"),
        "status": status,
        "protocol_id": protocol_id,
        "protocol_hash": run_spec["protocol_hash"],
        "split": split,
        "confirmation": run_spec["confirmation"],
        "seconds": round(time.perf_counter() - started, 3),
        "runner_seconds": run["seconds"],
        "outputs": outputs,
        "output_dir": str(Path(out_dir) if out_dir is not None else
                          (Path(store.root) / "reports" / f"diagnosis_{protocol_id}"
                           if store is not None else "")),
        "pool": run_spec["pool"],
        "scorer": run_spec["scorer"],
        "metrics": _report_metrics(clean_cell),
        "cells": [{k: _jsonable(v) for k, v in cell.items()} for cell in run["cells"]],
        "cell_count": run["cell_count"],
        "measured_cells": run["measured_cells"],
        "na_cells": run["na_cells"],
        "curves": run["curves"],
        "failure_counts": run["failure_counts"],
        "statistics": statistics,
        "per_query_count": len(run["per_query"]),
        "per_query_preview": per_query_table(run["per_query"][:100]),
        "warnings": warnings,
        "run_spec": run_spec,
    }
    if store is not None:
        asset = commit_report(store, protocol_id=protocol_id, payload=_slim(report),
                              outputs=outputs, split=split)
        report["report_asset_id"] = asset.asset_id
    return report


def _slim(report: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in report.items() if k not in ("per_query_preview", "run_spec")}


def _report_metrics(clean_cell: Mapping[str, Any] | None) -> dict[str, Any]:
    if clean_cell is None:
        return {}
    out: dict[str, Any] = {
        "queries": clean_cell.get("frozen_denominator"),
        "present_denominator": clean_cell.get("present_denominator"),
        "absent_denominator": clean_cell.get("absent_denominator"),
        "pool_cov_at_m": clean_cell.get("pool_cov_at_m"),
        "any_at_m": clean_cell.get("any_at_m"),
        "conditional_cov": clean_cell.get("conditional_cov"),
        "acceptance_rate": clean_cell.get("acceptance_rate"),
        "risk": clean_cell.get("risk"),
        "failure_counts": clean_cell.get("failure_counts"),
        "status": clean_cell.get("status"),
    }
    for key, value in clean_cell.items():
        if key.startswith("k=") and isinstance(value, Mapping):
            out[key] = {"hit_at_k": value.get("hit_at_k"),
                        "cov_recall_at_k": value.get("cov_recall_at_k"),
                        "effective_hit_at_k": value.get("effective_hit_at_k"),
                        "effective_cov_at_k": value.get("effective_cov_at_k"),
                        "hit_at_k_na_count": value.get("hit_at_k_na_count"),
                        "effective_denominator": value.get("effective_cov_at_k_denominator")}
    return out


def _statistics_block(run: Mapping[str, Any], statistics_cfg: Mapping[str, Any],
                      top_k: Sequence[int]) -> dict[str, Any]:
    """Clustered CI (unit = shape lineage), risk bound and correction bookkeeping."""
    replicates = int(statistics_cfg.get("bootstrap_replicates", 10000) or 10000)
    confidence = float(statistics_cfg.get("confidence", 0.95) or 0.95)
    unit = str(statistics_cfg.get("unit", "shape_lineage"))
    clean_rows = [row for row in run.get("per_query", []) if row.get("cell_id") == "clean"]
    k_values = sorted({int(k) for k in top_k})
    primary_k = 10 if 10 in k_values else (k_values[-1] if k_values else 1)
    paired: dict[str, list[float]] = {}
    for row in clean_rows:
        value = row.get(f"cov@{primary_k}")
        if value is None:
            continue
        paired.setdefault(str(row.get("lineage_cluster") or "UNKNOWN"), []).append(float(value))
    bootstrap = paired_bootstrap_ci(paired, unit=unit, replicates=replicates,
                                    confidence=confidence)
    # Frozen risk event model (plan 19.4 / 30.14): one event per independent lineage whose
    # queries, actions and seeds produced at least one wrong acceptance.
    lineage_events: dict[str, int] = {}
    for row in clean_rows:
        if row.get("mate_present"):
            continue
        cluster = str(row.get("lineage_cluster") or "UNKNOWN")
        lineage_events[cluster] = max(lineage_events.get(cluster, 0),
                                      int(row.get("absent_false_accept", 0) or 0))
    risk = summarise_risk_events(sum(lineage_events.values()), len(lineage_events),
                                 alpha=1.0 - confidence, target=0.10)
    risk["units_definition"] = ("independent shape lineages with at least one mate-absent query "
                                "in the frozen roster")
    return {
        "unit": unit,
        "bootstrap": bootstrap,
        "primary_k": primary_k,
        "risk": risk,
        "multiple_testing": {
            "declared": str(statistics_cfg.get("multiple_testing",
                                               "holm_for_registered_comparisons")),
            "applied": False,
            "reason": "no registered paired comparison in this single-arm run; Holm is applied "
                      "only across pre-registered comparisons",
        },
        "note": "intervals are conditional on this frozen gallery; cross-gallery generalisation "
                "requires independent gallery cohorts",
    }


def _environment() -> dict[str, Any]:
    import sys

    return {"python": sys.version.split()[0], "numpy": np.__version__,
            "device": "cpu", "gpu_hours_claimed": 0}


def _degrade_perturbation(store: Any):
    """Default query-side perturbation through ``degrade.api.apply_axis`` when available."""
    if store is None:
        return None
    try:
        from ..degrade.api import apply_axis  # noqa: F401 - capability probe only
    except Exception:  # noqa: BLE001 - absent module is a recorded NA, not a crash
        return None

    def _apply(axis_id: str, level: int, fragment_id: str, payload: Mapping[str, Any]
               ) -> dict[str, Any]:
        return {"ok": False, "status": "OPERATOR_NOT_REALIZED",
                "reason": f"axis {axis_id}@L{level} needs a committed observation artifact for "
                          f"{fragment_id}; the runner does not fabricate a degraded payload"}

    return _apply


# --------------------------------------------------------------------------------------
# extra façade helpers (docs/a12/interfaces.md section 2)
# --------------------------------------------------------------------------------------
def pool_metrics(pool: Any, top_k: Sequence[int] = (1, 5, 10, 20)) -> dict[str, Any]:
    """Structural summary of a pool: sizes, mate-absent queries, relation histogram."""
    stats = pool.stats() if hasattr(pool, "stats") else {}
    return {"pool_id": str(getattr(pool, "pool_id", "")), "stats": stats, "top_k": list(top_k),
            "n2_materialised": False}


def paired_bootstrap(paired: Any, **kwargs: Any) -> dict[str, Any]:
    return paired_bootstrap_ci(paired, **kwargs)


def risk_upper_bound(events: int, n: int, alpha: float = 0.05) -> float:
    return clopper_pearson_upper(events, n, alpha)


def run_from_config(config_path: str | Path, store: Any, **kwargs: Any) -> dict[str, Any]:
    """``synlab diagnose --config``: load a typed ``synlab.diagnose.v1`` document and run it."""
    spec = load_diagnose_spec(config_path)
    return run_diagnosis(spec, store, **kwargs)


__all__ = [
    "API_VERSION", "STATUS_OK", "load_spec", "resolve_pool", "resolve_roster", "resolve_scorer",
    "run_diagnosis", "run_from_config", "pool_metrics", "paired_bootstrap", "risk_upper_bound",
]
