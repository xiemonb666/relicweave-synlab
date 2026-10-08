"""Diagnosis runner / report tests (plan 19.6, 30.14): real cells, honest NA, frozen files."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from relations.pool_fixtures import build_two_event_store, commit_event, make_event
from synlab.diagnostics.api import run_diagnosis
from synlab.diagnostics.runner import CallableScorer, DiagnosticRunner, write_reports
from synlab.errors import ErrorCode, SynLabError
from synlab.relations.api import (
    PoolConfig,
    build_pool,
    save_pool_json,
    save_roster_json,
)
from synlab.schemas.runtime import QueryRosterEntry
from synlab.storage.store import AssetStore


def _legal_scorer() -> CallableScorer:
    """Deterministic observable-feature scorer (global RGB statistics + OBS_EST quality)."""

    def _fn(payloads):
        vectors, valid = {}, {}
        for fid, payload in payloads.items():
            rgb = np.asarray(payload["global_rgb"], dtype=np.float64)
            gv = np.asarray(payload["global_valid"], dtype=bool)
            if rgb.size == 0:
                valid[str(fid)] = False
                continue
            selected = rgb[gv] if gv.any() else rgb
            quality = np.asarray(payload["quality"], dtype=np.float64)
            qv = np.asarray(payload["quality_valid"], dtype=bool)
            q_masked = np.where(qv, quality, 0.0)
            vec = np.concatenate([selected.mean(axis=(0, 1, 2)), np.atleast_1d(selected.std()),
                                  q_masked.mean(axis=0)])
            norm = float(np.linalg.norm(vec))
            if not np.isfinite(norm) or norm <= 1e-12:
                valid[str(fid)] = False
                continue
            vectors[str(fid)] = vec / norm
            valid[str(fid)] = True
        return vectors, valid

    return CallableScorer(_fn, name="appearance_quality_only", identity={"legal": "OBS_EST"})


def _pool(tmp_path: Path):
    store, _specs = build_two_event_store(tmp_path)
    report = build_pool(store, None, PoolConfig(pool_id="diag_pool", size_target=100,
                                                query_per_mother=2))
    assert report["ok"], report.get("error")
    return store, report["pool"]


def _roster(pool):
    return list(pool.roster)


# ------------------------------------------------------------------------------- runner
def test_runner_marks_unavailable_cells_as_na_and_never_interpolates(tmp_path: Path):
    _store, pool = _pool(tmp_path)
    runner = DiagnosticRunner(pool=pool, roster=_roster(pool), scorer=_legal_scorer(),
                              axes=["P01"], levels=[1, 2], top_k=(1, 5))
    run = runner.run()
    assert run["cell_count"] == 3                       # clean + 2 axis cells
    assert run["measured_cells"] == 1 and run["na_cells"] == 2
    clean = next(cell for cell in run["cells"] if cell["cell_id"] == "clean")
    assert clean["status"] == "OK"
    assert clean["present_denominator"] == len(pool.roster)
    assert clean["k=1"]["cov_recall_at_k"] is not None
    for cell in run["cells"]:
        if cell["cell_id"] == "clean":
            continue
        assert cell["status"] == "NA"
        assert cell["na_reason"]
        assert cell["k=5"]["cov_recall_at_k"] is None    # NA, never a fake 0
        assert cell["metrics_status"] == "NA"
    curve = next(c for c in run["curves"] if c["axis_id"] == "P01")
    assert curve["points"] == []
    assert len(curve["missing"]) == 2
    assert curve["interpolated"] is False and curve["measured_points_only"] is True
    assert all(missing["level"] in (1, 2) for missing in curve["missing"])


def test_runner_measures_a_cell_when_a_perturbation_exists(tmp_path: Path):
    _store, pool = _pool(tmp_path)

    def perturbation(axis_id, level, fragment_id, payload):
        if level == 0:
            return {"ok": True, "payload": payload}
        if level == 3:
            return {"ok": False, "status": "OPERATOR_NOT_REALIZED",
                    "reason": "operator has no realization for this axis level"}
        noisy = dict(payload)
        rgb = np.asarray(payload["global_rgb"], dtype=np.float32).copy()
        noisy["global_rgb"] = rgb * (1.0 - 0.05 * level)
        return {"ok": True, "payload": noisy, "seconds": 0.5}

    runner = DiagnosticRunner(pool=pool, roster=_roster(pool), scorer=_legal_scorer(),
                              axes=["P10"], levels=[1, 3], top_k=(1, 5),
                              perturbation=perturbation)
    run = runner.run()
    measured = [c for c in run["cells"] if c["axis_id"] == "P10" and c["status"] == "OK"]
    assert len(measured) == 1 and measured[0]["level"] == 1
    curve = next(c for c in run["curves"] if c["axis_id"] == "P10")
    assert len(curve["points"]) == 1
    point = curve["points"][0]
    assert point["level"] == 1
    assert point["cov@5"] is not None and point["effective_cov@5"] is not None
    assert [m["level"] for m in curve["missing"]] == [3]
    assert "OPERATOR_NOT_REALIZED" in curve["missing"][0]["reason"]


def test_runner_keeps_failures_in_the_frozen_denominator(tmp_path: Path):
    _store, pool = _pool(tmp_path)
    healthy = _roster(pool)
    roster = healthy + [QueryRosterEntry(
        query_id="q::ghost", lineage_cluster="LIN0001_V01_M01", mother_id="m::LIN0001",
        fragment_id="ghost::fragment", split="dev", gallery_id=pool.pool_id,
        historical_neighbours=["a01"], mate_present=True, status="FROZEN", applicability={})]
    runner = DiagnosticRunner(pool=pool, roster=roster, scorer=_legal_scorer(),
                              axes=[], levels=[], top_k=(1, 5))
    run = runner.run()
    clean = run["cells"][0]
    assert clean["present_denominator"] == len(healthy) + 1
    assert clean["failures"] == 1
    failed = [row for row in run["per_query"] if row["query_id"] == "ghost::fragment"]
    assert failed and failed[0]["status"] == "INPUT_UNAVAILABLE"
    assert failed[0]["effective_hit@1"] == 0.0
    assert failed[0]["in_frozen_denominator"] is True
    assert run["failure_counts"]["by_failure_code"]["INPUT_UNAVAILABLE"] == 1


def test_runner_mate_absent_query_is_na_and_still_risked(tmp_path: Path):
    store, _first = _pool(tmp_path)
    lonely = make_event("LIN0007_V07_M07", "m::7", "s", 1, split="dev", seed=7)
    commit_event(store, lonely)
    report = build_pool(store, None, PoolConfig(pool_id="diag_pool2", size_target=100,
                                                query_per_mother=3))
    pool2 = report["pool"]
    assert "s00" in pool2.lineup and pool2.neighbours("s00") == []
    roster = [QueryRosterEntry(query_id="q::s00", lineage_cluster="LIN0007_V07_M07",
                               mother_id="m::7", fragment_id="s00", split="dev",
                               gallery_id=pool2.pool_id, historical_neighbours=[],
                               mate_present=False, status="FROZEN", applicability={})]
    runner = DiagnosticRunner(pool=pool2, roster=roster, scorer=_legal_scorer(),
                              axes=[], levels=[], top_k=(1, 5))
    run = runner.run()
    clean = run["cells"][0]
    assert clean["absent_denominator"] == 1 and clean["present_denominator"] == 0
    row = run["per_query"][0]
    assert row["hit@1"] is None and row["cov@1"] is None
    assert row["absent_false_accept"] == 1              # the acceptance set recommends something
    assert clean["risk"]["absent_false_accept_events"] == 1


# ---------------------------------------------------------------------------- run_diagnosis
def _spec(pool, tmp_path: Path, **overrides) -> dict:
    artifact = tmp_path / "pools" / "diag_pool.json"
    save_pool_json(pool, artifact)
    roster_path = tmp_path / "pools" / "diag_pool_queries.json"
    save_roster_json(pool, roster_path)
    spec = {
        "schema": "synlab.diagnose.v1",
        "protocol_id": "unit_test_protocol",
        "checkpoint_ref": None,
        "release_ref": None,
        "evaluation_split": "dev",
        "candidate_pool_ref": str(artifact),
        "query_roster_ref": str(roster_path),
        "axes": [],
        "levels": [0],
        "paired_basis": True,
        "input_profile": "SENSOR_PROXY",
        "observation_route": "proxy_scan",
        "include_pipeline_failures_in_primary_denominator": True,
        "fixed_query_ids": True,
        "seeds": [11],
        "metrics": ["HitAtK", "CovRecallAtK", "PoolCovAtM"],
        "statistics": {"unit": "shape_lineage", "bootstrap_replicates": 200,
                       "confidence": 0.95,
                       "multiple_testing": "holm_for_registered_comparisons",
                       "report_all_attempts": True},
        "confirmation": {"open": False, "require_frozen_protocol": True},
    }
    spec.update(overrides)
    return spec


def test_run_diagnosis_writes_the_five_report_artifacts(tmp_path: Path):
    store, pool = _pool(tmp_path)
    spec = _spec(pool, tmp_path)
    report = run_diagnosis(spec, store, scorer=_legal_scorer())
    assert report["ok"] is True and report["status"] == "QA_PASSED"
    out_dir = Path(report["output_dir"])
    for name in ("per_query_metrics.parquet", "diagnostic_summary.parquet",
                 "failure_counts.json", "run_spec.json", "report.md"):
        assert (out_dir / name).exists(), name
    assert report["scorer"]["name"] == "appearance_quality_only"
    assert report["pool"]["candidates"] == len(pool.lineup)
    assert report["metrics"]["queries"] == len(pool.roster)
    assert report["confirmation"]["open"] is False
    assert report["confirmation"]["used_as_confirmation"] is False
    run_spec = json.loads((out_dir / "run_spec.json").read_text(encoding="utf-8"))
    assert run_spec["protocol_hash"] == report["protocol_hash"]
    assert run_spec["pool"]["hash"] == pool.hash
    assert run_spec["statistics"]["unit"] == "shape_lineage"
    assert run_spec["statistics_result"]["bootstrap"]["unit"] == "shape_lineage"
    assert run_spec["statistics_result"]["bootstrap"]["replicates"] == 200
    failures = json.loads((out_dir / "failure_counts.json").read_text(encoding="utf-8"))
    assert failures["total_rows"] > 0
    markdown = (out_dir / "report.md").read_text(encoding="utf-8")
    assert "measured points only" in markdown
    assert report["report_asset_id"]


def test_run_diagnosis_parquet_contains_every_roster_row(tmp_path: Path):
    store, pool = _pool(tmp_path)
    spec = _spec(pool, tmp_path)
    report = run_diagnosis(spec, store, scorer=_legal_scorer())
    out_dir = Path(report["output_dir"])
    import pyarrow.parquet as pq

    table = pq.read_table(out_dir / "per_query_metrics.parquet")
    assert table.num_rows == len(pool.roster)
    columns = set(table.column_names)
    assert {"query_id", "status", "historical_neighbours", "accepted", "cell_id"} <= columns
    summary = pq.read_table(out_dir / "diagnostic_summary.parquet")
    assert summary.num_rows == report["cell_count"]
    assert "present_denominator" in summary.column_names


def test_run_diagnosis_without_checkpoint_labels_the_shallow_baseline(tmp_path: Path):
    store, pool = _pool(tmp_path)
    report = run_diagnosis(_spec(pool, tmp_path), store)
    assert report["status"] == "QA_PASSED_SHALLOW_BASELINE"
    assert report["scorer"]["source"] == "shallow_observation_baseline"
    assert any("DEPLOYMENT_MODEL_NOT_PROVIDED" in warning for warning in report["warnings"])


def test_confirmation_split_is_refused_when_confirmation_is_closed(tmp_path: Path):
    store, pool = _pool(tmp_path)
    spec = _spec(pool, tmp_path, evaluation_split="confirm")
    with pytest.raises(SynLabError) as excinfo:
        run_diagnosis(spec, store, scorer=_legal_scorer())
    assert excinfo.value.code == ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION
    assert "confirmation" in excinfo.value.message


def test_opened_confirmation_is_recorded_as_such(tmp_path: Path):
    store, pool = _pool(tmp_path)
    spec = _spec(pool, tmp_path, evaluation_split="confirm",
                 confirmation={"open": True, "require_frozen_protocol": True})
    report = run_diagnosis(spec, store, scorer=_legal_scorer())
    assert report["ok"] is True
    assert report["confirmation"]["used_as_confirmation"] is True
    assert report["confirmation"]["opened_at"] is not None
    assert "opening is recorded" in report["confirmation"]["note"]


def test_missing_pool_raises_input_unavailable(tmp_path: Path):
    store = AssetStore(tmp_path / "empty")
    with pytest.raises(SynLabError) as excinfo:
        run_diagnosis({"protocol_id": "x", "candidate_pool_ref": None}, store)
    assert excinfo.value.code == ErrorCode.INPUT_UNAVAILABLE


def test_pool_without_features_cannot_be_diagnosed(tmp_path: Path):
    store, _specs = build_two_event_store(tmp_path, features=False)
    report = build_pool(store, None, PoolConfig(pool_id="bare", size_target=10,
                                                query_per_mother=1))
    assert report["ok"]
    spec = _spec(report["pool"], tmp_path)
    with pytest.raises(SynLabError) as excinfo:
        run_diagnosis(spec, store, scorer=_legal_scorer())
    assert excinfo.value.code == ErrorCode.INPUT_UNAVAILABLE
    assert "no diagnosis can be measured" in excinfo.value.message


def test_write_reports_falls_back_loudly_when_parquet_is_unavailable(tmp_path: Path, monkeypatch):
    run = {"cells": [{"cell_id": "clean", "status": "OK"}], "per_query": [], "curves": [],
           "failure_counts": {"total_rows": 0}, "measured_cells": 1, "cell_count": 1,
           "na_cells": 0}
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("pyarrow"):
            raise ImportError("pyarrow blocked for this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    written = write_reports(tmp_path / "out", run=run, run_spec={"pool_id": "p"},
                            protocol_id="proto")
    assert written["per_query_metrics.parquet"].startswith("PARQUET_FAILED")
    assert (tmp_path / "out" / "per_query_metrics.json").exists()
