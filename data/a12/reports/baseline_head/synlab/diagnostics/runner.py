"""Fixed gallery + frozen roster evaluation, report writer (plan 19.1, 19.6, 30.14).

Honesty rules implemented here
------------------------------
* the gallery, the roster and the acceptance policy are frozen before the run; the report
  records their hashes;
* every cell is a *real* measurement or an explicit ``NA``/``NOT_RUN`` with a reason -- cells
  that could not be produced are marked missing and are **never interpolated or fitted**;
* no random curve is ever drawn: ``curves`` contains measured points only;
* when ``DiagnosticSpec.confirmation.open`` is false the confirm split may not be used as
  confirmation evidence (the run is refused instead of silently relabelled).
"""

from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..roles import (
    FORBIDDEN_FEATURE_FIELDS,
    FRAME_WORLD,
    ROLE_DIAG_REPORT,
    SCHEMA_REPORT,
    UNIT_NONE,
)
from ..schemas.runtime import QueryRosterEntry
from .metrics import (
    DEFAULT_TOP_K,
    STATUS_INPUT_UNAVAILABLE,
    STATUS_NA_NOT_APPLICABLE,
    STATUS_OK,
    STATUS_REJECTED,
    aggregate_metrics,
    dedupe_candidates,
    per_query_table,
    query_metrics,
)

RUNNER_VERSION = "diagnostics.runner.v1"

#: Cell statuses used by the summary table (never a silent zero).
CELL_OK = "OK"
CELL_NA = "NA"
CELL_NOT_RUN = "NOT_RUN"
CELL_FAILED = "FAILED"


# --------------------------------------------------------------------------------------
# scorers
# --------------------------------------------------------------------------------------
class Scorer:
    """Structural protocol: legal features in, one L2-normalised vector per fragment out."""

    identity: dict[str, Any] = {}

    def encode(self, payloads: Mapping[str, Mapping[str, Any]]
               ) -> tuple[dict[str, np.ndarray], dict[str, bool]]:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {"scorer": type(self).__name__, **dict(self.identity)}


class CallableScorer(Scorer):
    """Wraps ``fn(payloads) -> (vectors, valid)`` (used by tests and injected baselines)."""

    def __init__(self, fn: Callable[[Mapping[str, Mapping[str, Any]]],
                                    tuple[Mapping[str, np.ndarray], Mapping[str, bool]]],
                 *, name: str = "callable", identity: Mapping[str, Any] | None = None) -> None:
        self._fn = fn
        self.identity = {"name": name, **dict(identity or {})}

    def encode(self, payloads):
        vectors, valid = self._fn(payloads)
        return ({str(k): np.asarray(v, dtype=np.float64) for k, v in dict(vectors).items()},
                {str(k): bool(v) for k, v in dict(valid).items()})


class ClassicalScorer(Scorer):
    """Shallow observation baseline (2D / 3D / fusion) -- labelled as such in the report."""

    def __init__(self, mode: str = "shallow_fusion") -> None:
        from ..training.model import ObservationVectorBaseline

        self.baseline = ObservationVectorBaseline(mode=mode)
        self.identity = {"name": f"classical_{mode}", "kind": "shallow_baseline",
                         **self.baseline.identity()}

    def encode(self, payloads):
        vectors: dict[str, np.ndarray] = {}
        valid: dict[str, bool] = {}
        for fid, payload in payloads.items():
            try:
                vec = np.asarray(self.baseline.vector(payload), dtype=np.float64)
            except Exception:  # noqa: BLE001 - a payload that cannot be encoded is recorded
                valid[str(fid)] = False
                continue
            norm = float(np.linalg.norm(vec))
            if not np.isfinite(norm) or norm <= 1e-12:
                valid[str(fid)] = False
                continue
            vectors[str(fid)] = vec / norm
            valid[str(fid)] = True
        return vectors, valid


class CheckpointScorer(Scorer):
    """Trained dual-tower encoder loaded from a checkpoint (cacheable tower only)."""

    def __init__(self, checkpoint: Any, *, pool: Any = None, seed: int = 11,
                 device: str = "cpu") -> None:
        import torch

        from ..training.adapter import FeatureBundle
        from ..training.model import assert_cacheable_index_ok, build_model

        self._FeatureBundle = FeatureBundle
        self.torch = torch
        self.device = device
        self.payload = checkpoint
        quality_input_dim, quality_target_dim = _quality_dims(pool)
        self.model = build_model(seed=int(seed), quality_input_dim=quality_input_dim,
                                 quality_target_dim=quality_target_dim)
        try:
            self.model.encoder.load_state_dict(checkpoint["model"])
        except Exception as exc:  # noqa: BLE001 - a mismatched checkpoint is a structured error
            raise SynLabError(
                ErrorCode.ASSET_HASH_MISMATCH,
                f"checkpoint encoder state does not match the pool feature contract: {exc}",
                stage="diagnostics.CheckpointScorer",
                measurements={"quality_input_dim": quality_input_dim,
                              "quality_target_dim": quality_target_dim}) from exc
        if self.model.pair_head is not None and checkpoint.get("pair_head"):
            try:
                self.model.pair_head.load_state_dict(checkpoint["pair_head"])
            except Exception:  # noqa: BLE001 - refinement head is optional for pool metrics
                pass
        identity = dict(self.model.index_identity())
        assert_cacheable_index_ok(identity)
        self.identity = {"name": "checkpoint_encoder", "kind": "trained",
                         "step": int(checkpoint.get("step", 0) or 0),
                         "payload_hash": str(checkpoint.get("payload_hash", "")),
                         "reproducibility_level": str(checkpoint.get("reproducibility_level", "")),
                         "index_identity": identity}
        self.model.encoder.eval()

    @classmethod
    def from_ref(cls, store: Any, ref: Any, *, pool: Any = None, seed: int = 11
                 ) -> "CheckpointScorer":
        import torch

        if isinstance(ref, Mapping):
            return cls(dict(ref), pool=pool, seed=seed)
        path = Path(str(ref))
        if path.exists():
            payload = torch.load(path, map_location="cpu", weights_only=False)
            return cls(payload, pool=pool, seed=seed)
        if store is not None:
            try:
                record = store.get_asset(str(ref))
            except SynLabError as exc:
                raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                                  f"checkpoint {ref!r} is neither a file nor a known asset",
                                  stage="diagnostics.CheckpointScorer.from_ref") from exc
            data = store.load_bytes(record.asset_id, "bytes")
            payload = torch.load(io.BytesIO(data), map_location="cpu", weights_only=False)
            return cls(payload, pool=pool, seed=seed)
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          f"checkpoint {ref!r} cannot be resolved",
                          stage="diagnostics.CheckpointScorer.from_ref")

    def encode(self, payloads):
        ids = [str(k) for k in payloads]
        bundle = self._FeatureBundle.from_dict({fid: payloads[fid] for fid in ids}).check_shapes()
        self.model.encoder.eval()
        z, z_valid = self.model.encoder.encode_batch(bundle.to_torch(device=self.device))
        vectors = {fid: np.asarray(z[i], dtype=np.float64) for i, fid in enumerate(ids)}
        valid = {fid: bool(z_valid[i]) for i, fid in enumerate(ids)}
        return vectors, valid


def _quality_dims(pool: Any) -> tuple[int | None, int | None]:
    """Same derivation as the training façade: no hard-coded channel widths."""
    features = getattr(pool, "features", None) or {}
    for payload in features.values():
        quality = np.asarray(payload["quality"])
        presence = np.asarray(payload["presence"])
        return (int(quality.shape[0] * quality.shape[1] + presence.shape[0]),
                int(quality.shape[0] * quality.shape[1]))
    return None, None


def assert_legal_payloads(payloads: Mapping[str, Mapping[str, Any]], *, where: str) -> None:
    """The decision stages may not read ancestry/answers: a forbidden key is a hard failure."""
    forbidden = {str(f).lower() for f in FORBIDDEN_FEATURE_FIELDS}
    violations: list[str] = []

    def walk(node: Any, path: str, depth: int) -> None:
        if depth > 6:
            return
        if isinstance(node, Mapping):
            for key, value in node.items():
                if str(key).lower() in forbidden:
                    violations.append(f"{path}.{key}")
                else:
                    walk(value, f"{path}.{key}", depth + 1)
        elif isinstance(node, (list, tuple)) and not isinstance(node, (str, bytes)):
            for i, value in enumerate(node[:16]):
                walk(value, f"{path}[{i}]", depth + 1)

    for fid, payload in payloads.items():
        walk(payload, f"{where}[{fid}]", 0)
    if violations:
        raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                          f"forbidden fields reached the retrieval decision stage: "
                          f"{violations[:8]}",
                          stage="diagnostics.assert_legal_payloads",
                          evidence_refs=violations[:8])


# --------------------------------------------------------------------------------------
# cells
# --------------------------------------------------------------------------------------
@dataclass
class Cell:
    """One evaluation cell: ``clean`` baseline or one (axis, level) point."""

    axis_id: str
    level: int
    status: str = CELL_OK
    na_reason: str | None = None
    failure_code: str | None = None

    @property
    def cell_id(self) -> str:
        return "clean" if self.axis_id == "clean" else f"{self.axis_id}@{self.level}"

    def as_row(self) -> dict[str, Any]:
        """Cell fields; deliberately prefixed so they never clobber a query's own ``status``."""
        return {"cell_id": self.cell_id, "axis_id": self.axis_id, "level": int(self.level),
                "cell_status": self.status, "cell_na_reason": self.na_reason,
                "cell_failure_code": self.failure_code}


@dataclass
class DiagnosticRunner:
    """Evaluate a frozen roster against a frozen gallery, cell by cell."""

    pool: Any
    roster: Sequence[QueryRosterEntry]
    scorer: Scorer
    axes: Sequence[str] = ()
    levels: Sequence[int] = (0, 1, 2, 3, 4)
    top_k: Sequence[int] = DEFAULT_TOP_K
    candidate_pool_sizes: Sequence[int] = (50, 100, 200)
    split: str = "dev"
    confirmation_open: bool = False
    perturbation: Callable[[str, int, str, Mapping[str, Any]], Any] | None = None
    perturbation_side: str = "QUERY_ONLY"
    seed: int = 20261001
    metrics_requested: Sequence[str] = ()
    extra_spec: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ helpers
    def _candidate_ids(self) -> list[str]:
        return [str(f) for f in self.pool.lineup]

    def _payloads(self, query_ids: Sequence[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for fid in query_ids:
            payload = self.pool.feature_for(fid) if hasattr(self.pool, "feature_for") else None
            if payload is None:
                payload = (getattr(self.pool, "features", {}) or {}).get(fid)
            if payload is not None:
                out[str(fid)] = payload
        return out

    def _rank(self, scores: Mapping[str, float], query: str) -> list[str]:
        order = sorted(scores, key=lambda cid: (-float(scores[cid]), str(cid)))
        ranked, _hygiene = dedupe_candidates(order, query_id=query)
        return ranked

    # ------------------------------------------------------------------ one cell
    def evaluate_cell(self, cell: Cell) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        candidate_ids = self._candidate_ids()
        candidate_payloads = {fid: (getattr(self.pool, "features", {}) or {})[fid]
                              for fid in candidate_ids
                              if fid in (getattr(self.pool, "features", {}) or {})}
        query_ids = [q.fragment_id for q in self.roster]
        query_payloads = self._payloads(query_ids)
        perturb_report: dict[str, Any] = {}
        if cell.axis_id != "clean" and self.perturbation is not None:
            perturbed: dict[str, dict] = {}
            for fid in query_ids:
                payload = query_payloads.get(fid)
                if payload is None:
                    continue
                outcome = self.perturbation(cell.axis_id, int(cell.level), fid, payload)
                if outcome is None:
                    perturb_report[fid] = {"status": "NOT_REALIZED"}
                    continue
                if isinstance(outcome, Mapping):
                    if not outcome.get("ok", True):
                        perturb_report[fid] = {"status": str(outcome.get("status", "NA")),
                                               "reason": outcome.get("reason")}
                        continue
                    perturbed[fid] = outcome.get("payload", payload)
                    if outcome.get("seconds") is not None:
                        perturb_report[fid] = {"status": "OK", "seconds": outcome["seconds"]}
                else:
                    perturbed[fid] = outcome
                    perturb_report[fid] = {"status": "OK"}
            query_payloads = perturbed
        elif cell.axis_id != "clean" and self.perturbation is None:
            cell.status = CELL_NA
            cell.na_reason = "no perturbation provider is available for this axis"

        if cell.status != CELL_OK:
            rows = [self._missing_row(entry, cell) for entry in self.roster]
            return rows, {"perturbation": perturb_report}
        if cell.axis_id != "clean" and perturb_report and \
                all(info.get("status") != "OK" for info in perturb_report.values()):
            cell.status = CELL_NA
            cell.na_reason = ("no query could be perturbed: "
                              + ", ".join(sorted({str(i.get("status"))
                                                  for i in perturb_report.values()})))
            rows = [self._missing_row(entry, cell) for entry in self.roster]
            return rows, {"perturbation": perturb_report}

        assert_legal_payloads(candidate_payloads, where="candidate")
        assert_legal_payloads(query_payloads, where="query")

        vectors: dict[str, np.ndarray] = {}
        valid: dict[str, bool] = {}
        for label, payloads in (("candidate", candidate_payloads), ("query", query_payloads)):
            if not payloads:
                continue
            part_vectors, part_valid = self.scorer.encode(payloads)
            vectors.update(part_vectors)
            valid.update(part_valid)
        unencodable = sorted(fid for fid in candidate_ids if not valid.get(fid, False)
                             and fid not in query_ids)

        rows: list[dict[str, Any]] = []
        for entry in self.roster:
            query = entry.fragment_id
            if not valid.get(query, False) or query not in vectors:
                row = query_metrics(
                    query_id=query, neighbours=list(entry.historical_neighbours),
                    gallery_ids=candidate_ids, first_stage=[], ranked=[], top_k=self.top_k,
                    status=STATUS_INPUT_UNAVAILABLE, failure_code=ErrorCode.INPUT_UNAVAILABLE.value,
                    lineage_cluster=entry.lineage_cluster,
                    unencodable_candidates=unencodable,
                    input_hash=hash_json({"cell": cell.cell_id, "query": query}),
                    gallery_hash=str(getattr(self.pool, "hash", "")))
                row.update(cell.as_row())
                rows.append(row)
                continue
            scores = {cid: float(np.dot(vectors[query], vectors[cid]))
                      for cid in candidate_ids if cid != query and cid in vectors}
            ranked = self._rank(scores, query)
            pool_size = max([int(s) for s in self.candidate_pool_sizes] or [len(ranked) or 1])
            top_size = max([int(k) for k in self.top_k] or [1])
            first_stage = ranked[: pool_size]
            accepted = list(ranked[: top_size])
            status = STATUS_OK if accepted else STATUS_REJECTED
            row = query_metrics(
                query_id=query, neighbours=list(entry.historical_neighbours),
                gallery_ids=candidate_ids, first_stage=first_stage, ranked=ranked,
                top_k=self.top_k, accepted=accepted, status=status,
                failure_code=None if accepted else "REJECTED_EMPTY_ACCEPT_SET",
                lineage_cluster=entry.lineage_cluster,
                unencodable_candidates=unencodable,
                input_hash=hash_json({"cell": cell.cell_id, "query": query}),
                gallery_hash=str(getattr(self.pool, "hash", "")))
            row.update(cell.as_row())
            rows.append(row)
        return rows, {"perturbation": perturb_report, "unencodable_candidates": unencodable}

    def _missing_row(self, entry: QueryRosterEntry, cell: Cell) -> dict[str, Any]:
        row = query_metrics(
            query_id=entry.fragment_id, neighbours=list(entry.historical_neighbours),
            gallery_ids=self._candidate_ids(), first_stage=[], ranked=[], top_k=self.top_k,
            status=(STATUS_NA_NOT_APPLICABLE if cell.status == CELL_NA
                    else STATUS_INPUT_UNAVAILABLE),
            failure_code=cell.failure_code or cell.na_reason, lineage_cluster=entry.lineage_cluster)
        row.update(cell.as_row())
        row["na_reason"] = cell.na_reason
        return row

    # ------------------------------------------------------------------ whole run
    def run(self) -> dict[str, Any]:
        started = time.perf_counter()
        cells: list[Cell] = [Cell(axis_id="clean", level=0)]
        for axis in self.axes:
            for level in self.levels:
                if axis == "clean":
                    continue
                cells.append(Cell(axis_id=str(axis), level=int(level)))
        all_rows: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []
        for cell in cells:
            rows, extra = self.evaluate_cell(cell)
            for row in rows:
                row["cell_status"] = cell.status
            aggregate = aggregate_metrics(rows, top_k=self.top_k)
            if cell.status != CELL_OK:
                aggregate = _na_aggregate(aggregate, cell)
            summary = {**cell.as_row(), **aggregate,
                       "status": cell.status, "na_reason": cell.na_reason,
                       "extra": _jsonable(extra),
                       "n_rows": len(rows)}
            summaries.append(summary)
            all_rows.extend(rows)
        curves = self._curves(summaries)
        failure_counts = _failure_counts(all_rows)
        return {
            "cells": summaries,
            "per_query": all_rows,
            "curves": curves,
            "failure_counts": failure_counts,
            "scorer": self.scorer.describe(),
            "seconds": round(time.perf_counter() - started, 6),
            "cell_count": len(cells),
            "measured_cells": sum(1 for s in summaries if s["status"] == CELL_OK),
            "na_cells": sum(1 for s in summaries if s["status"] == CELL_NA),
        }

    def _curves(self, summaries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        axes: dict[str, dict[int, Mapping[str, Any]]] = {}
        for summary in summaries:
            axis = str(summary["axis_id"])
            if axis == "clean":
                continue
            axes.setdefault(axis, {})[int(summary["level"])] = summary
        curves: list[dict[str, Any]] = []
        for axis, by_level in sorted(axes.items()):
            points: list[dict[str, Any]] = []
            missing: list[dict[str, Any]] = []
            for level in sorted(by_level):
                summary = by_level[level]
                if summary["status"] != CELL_OK:
                    missing.append({"level": level, "status": summary["status"],
                                    "reason": summary.get("na_reason")
                                    or summary.get("cell_failure_code")})
                    continue
                point: dict[str, Any] = {"level": level, "status": CELL_OK,
                                         "n_queries": summary.get("frozen_denominator")}
                for k in sorted({int(k) for k in self.top_k}):
                    point[f"cov@{k}"] = summary.get(f"k={k}", {}).get("cov_recall_at_k")
                    point[f"effective_cov@{k}"] = summary.get(f"k={k}", {}).get("effective_cov_at_k")
                    point[f"hit@{k}"] = summary.get(f"k={k}", {}).get("hit_at_k")
                point["pool_cov"] = summary.get("pool_cov_at_m")
                points.append(point)
            curves.append({"axis_id": axis, "metric": "CovRecall@K",
                           "points": points, "missing": missing,
                           "measured_points_only": True, "interpolated": False})
        return curves


def _na_aggregate(summary: Mapping[str, Any], cell: Cell) -> dict[str, Any]:
    """A cell that did not run reports NA: no measured value may be written as 0."""
    out = dict(summary)
    for key in ("pool_cov_at_m", "pool_cov_at_m_na_count", "any_at_m", "any_at_m_na_count",
                "conditional_cov", "conditional_cov_na_count", "acceptance_rate",
                "seconds_total", "cost_total", "all_rejected_present", "pool_miss",
                "duplicates_removed", "self_candidates_removed"):
        out.pop(key, None)
    for key, value in list(out.items()):
        if key.startswith("k=") and isinstance(value, Mapping):
            out[key] = {sub: (None if sub not in ("effective_hit_at_k_denominator",
                                                  "effective_cov_at_k_denominator",
                                                  "effective_hit_at_k_completed_denominator")
                              else sub_value)
                        for sub, sub_value in value.items()}
    risk = dict(out.get("risk") or {})
    for key in list(risk):
        if key.endswith("_events") or key.endswith("_rate"):
            risk[key] = None
    out["risk"] = risk
    out["metrics_status"] = cell.status
    out["na_reason"] = cell.na_reason or cell.failure_code
    out["measured"] = False
    return out


def _failure_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_code: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_cell: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status", "UNKNOWN"))
        by_status[status] = by_status.get(status, 0) + 1
        code = row.get("failure_code")
        if code:
            by_code[str(code)] = by_code.get(str(code), 0) + 1
        if row.get("cell_status") not in (None, CELL_OK):
            key = str(row.get("cell_id"))
            by_cell[key] = by_cell.get(key, 0) + 1
    return {"by_failure_code": by_code, "by_status": by_status, "by_cell": by_cell,
            "total_rows": len(rows),
            "note": "failures are reported per item; an unrun item is never written as 0"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(float(value)) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# --------------------------------------------------------------------------------------
# report writing
# --------------------------------------------------------------------------------------
REPORT_FILES = ("per_query_metrics.parquet", "diagnostic_summary.parquet",
                "failure_counts.json", "run_spec.json", "report.md")


def write_reports(out_dir: str | Path, *, run: Mapping[str, Any],
                  run_spec: Mapping[str, Any], protocol_id: str) -> dict[str, Any]:
    """Write the five frozen report artifacts; parquet falls back loudly, never silently."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Any] = {}

    per_query_rows = per_query_table(run.get("per_query", []))
    summary_rows = [_summary_row(row) for row in run.get("cells", [])]
    written["per_query_metrics.parquet"] = _write_parquet(
        out_dir / "per_query_metrics.parquet", per_query_rows)
    written["diagnostic_summary.parquet"] = _write_parquet(
        out_dir / "diagnostic_summary.parquet", summary_rows)
    failure = dict(run.get("failure_counts") or {})
    (out_dir / "failure_counts.json").write_text(
        json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8")
    written["failure_counts.json"] = str(out_dir / "failure_counts.json")
    (out_dir / "run_spec.json").write_text(
        json.dumps(_jsonable(run_spec), ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8")
    written["run_spec.json"] = str(out_dir / "run_spec.json")
    (out_dir / "report.md").write_text(
        _markdown(run, run_spec, protocol_id), encoding="utf-8")
    written["report.md"] = str(out_dir / "report.md")
    return written


def _write_parquet(path: Path, rows: Sequence[Mapping[str, Any]]) -> str:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.Table.from_pylist([dict(row) for row in rows]) if rows else \
            pa.table({"empty": pa.array([], type=pa.string())})
        pq.write_table(table, path)
        return str(path)
    except Exception as exc:  # noqa: BLE001 - written as JSON beside the missing parquet
        fallback = path.with_suffix(".json")
        fallback.write_text(json.dumps(_jsonable(list(rows)), ensure_ascii=False, indent=2,
                                        default=str), encoding="utf-8")
        return f"PARQUET_FAILED({type(exc).__name__}: {exc}); wrote {fallback}"


def _summary_row(row: Mapping[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, Mapping):
            for sub_key, sub_value in value.items():
                flat[f"{key}_{sub_key}"] = (json.dumps(_jsonable(sub_value), ensure_ascii=False)
                                            if isinstance(sub_value, (list, tuple, dict))
                                            else sub_value)
        elif isinstance(value, (list, tuple)):
            flat[key] = json.dumps(_jsonable(value), ensure_ascii=False)
        else:
            flat[key] = value
    return flat


def _markdown(run: Mapping[str, Any], run_spec: Mapping[str, Any], protocol_id: str) -> str:
    lines: list[str] = [f"# 诊断报告 / diagnostic report — `{protocol_id}`", ""]
    lines.append(f"* runner: `{RUNNER_VERSION}`")
    lines.append(f"* gallery: `{run_spec.get('pool_id')}` hash `{run_spec.get('pool_hash')}`")
    lines.append(f"* split: `{run_spec.get('split')}`; confirmation open: "
                 f"`{run_spec.get('confirmation', {}).get('open')}`")
    lines.append(f"* scorer: `{json.dumps(run.get('scorer', {}), ensure_ascii=False)}`")
    lines.append(f"* cells measured: {run.get('measured_cells')} / {run.get('cell_count')} "
                 f"(NA: {run.get('na_cells')})")
    lines.append("")
    lines.append("## 汇总 / summary")
    lines.append("")
    lines.append("| cell | status | present n | Hit@10 | Cov@10 | EffCov@10 | PoolCov@M | "
                 "任何缺失 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for cell in run.get("cells", []):
        k10 = cell.get("k=10", {})
        lines.append("| {cid} | {status} | {n} | {hit} | {cov} | {eff} | {pool} | {na} |".format(
            cid=cell.get("cell_id"), status=cell.get("status"),
            n=cell.get("present_denominator"),
            hit=_fmt(k10.get("hit_at_k")), cov=_fmt(k10.get("cov_recall_at_k")),
            eff=_fmt(k10.get("effective_cov_at_k")), pool=_fmt(cell.get("pool_cov_at_m")),
            na=cell.get("k=10", {}).get("hit_at_k_na_count")))
    lines.append("")
    lines.append("## 曲线（仅实测点） / curves (measured points only)")
    lines.append("")
    for curve in run.get("curves", []):
        lines.append(f"### {curve['axis_id']}")
        lines.append("")
        for point in curve["points"]:
            lines.append(f"* level {point['level']}: Cov@10={_fmt(point.get('cov@10'))}, "
                         f"EffCov@10={_fmt(point.get('effective_cov@10'))}, "
                         f"n={point.get('n_queries')}")
        for missing in curve["missing"]:
            lines.append(f"* level {missing['level']}: **MISSING** "
                         f"({missing['status']}: {missing['reason']})")
        if not curve["points"] and not curve["missing"]:
            lines.append("* no cell was measured")
        lines.append("")
    lines.append("## 失败与缺失 / failures and gaps")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(run.get("failure_counts", {}), ensure_ascii=False, indent=2,
                            default=str))
    lines.append("```")
    lines.append("")
    lines.append("> 未运行/不适用一律标 `NA` 或 `NOT_RUN`，不写 0 分；曲线不插值、不拟合、"
                 "不生成随机曲线。失败轨迹与 STOP 全部保留。")
    return "\n".join(lines) + "\n"


def _fmt(value: Any) -> str:
    if value is None:
        return "NA"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


# --------------------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------------------
def commit_report(store: Any, *, protocol_id: str, payload: Mapping[str, Any],
                  outputs: Mapping[str, Any], split: str, ancestry: Sequence[str] = ()) -> Any:
    return store.commit_asset(
        role=ROLE_DIAG_REPORT, schema=SCHEMA_REPORT, unit=UNIT_NONE, frame=FRAME_WORLD,
        payload={"report_json": json.dumps(_jsonable(payload), ensure_ascii=False, default=str),
                 "outputs_json": json.dumps(_jsonable(outputs), ensure_ascii=False, default=str)},
        meta={"protocol_id": protocol_id, "runner_version": RUNNER_VERSION, "split": split,
              "outputs": _jsonable(outputs)},
        qa={"ok": True, "measured_only": True}, ancestry=list(ancestry), split=split)


__all__ = [
    "RUNNER_VERSION", "CELL_OK", "CELL_NA", "CELL_NOT_RUN", "CELL_FAILED", "REPORT_FILES",
    "Scorer", "CallableScorer", "ClassicalScorer", "CheckpointScorer", "Cell",
    "DiagnosticRunner", "write_reports", "commit_report",
    "FORBIDDEN_FEATURE_FIELDS",
]
