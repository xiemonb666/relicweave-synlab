"""Run-level audits: closure, permission boundary, split integrity, coverage (plan 21.1, 25.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..jobs.scheduler import Scheduler
from ..roles import (
    FORBIDDEN_FEATURE_FIELDS,
    ROLE_FEATURE_BUNDLE,
    ROLE_LABEL_BUNDLE,
    ROLE_MOTHER_MESH,
    ROLE_OBS_RESULT,
)
from ..storage.release import ReleaseManager
from ..storage.store import QA_FAIL, QA_PASS, AssetStore, health_check


def audit_run(store: AssetStore, run_id: str) -> dict[str, Any]:
    """Audit a generation run. Returns a report; never mutates data."""
    problems: list[str] = []
    warnings: list[str] = []
    try:
        run = store.get_run(run_id)
    except SynLabError as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown run {run_id}: {exc.message}",
                          stage="qc.audit") from exc
    scheduler = Scheduler(store)
    jobs = scheduler.list_jobs(run_id=run_id, limit=10000)
    if not jobs:
        warnings.append("run has no jobs recorded")
    state_counts: dict[str, int] = {}
    for job in jobs:
        state_counts[job.state] = state_counts.get(job.state, 0) + 1
    unfinished = [j.job_id for j in jobs if j.state in ("PENDING", "RUNNING", "RETRYABLE",
                                                        "OUTPUT_READY", "QA_PASS", "BLOCKED")]
    if unfinished:
        warnings.append(f"{len(unfinished)} jobs not COMMITTED (state summary {state_counts})")

    assets = store.list_assets(limit=100000)
    run_assets = [a for a in assets if (a.meta or {}).get("run_id") == run_id]
    if not run_assets:
        # fall back to assets referenced by the run's jobs
        referenced: set[str] = set()
        for job in jobs:
            referenced.update(job.outputs)
        run_assets = [a for a in assets if a.asset_id in referenced]
    qa_failed = [a.asset_id for a in run_assets if a.qa_status == QA_FAIL]
    if qa_failed:
        problems.append(f"assets with QA_FAIL referenced by run: {qa_failed[:5]}")
    if not run_assets:
        problems.append("run produced no assets")

    health = health_check(str(store.root))
    if not health["ok"]:
        problems.append(f"store health check failed: {health['problems'][:3]}")

    manager = ReleaseManager(store)
    closure = manager.verify_closure([a.asset_id for a in run_assets]) if run_assets else {"ok": True,
                                                                                          "problems": []}
    if not closure["ok"]:
        problems.append(f"reference closure failed: {closure['problems'][:3]}")

    # split integrity: one lineage must not appear in two splits
    lineage_splits: dict[str, set[str]] = {}
    for asset in run_assets:
        if asset.lineage_id and asset.split:
            lineage_splits.setdefault(asset.lineage_id, set()).add(asset.split)
    crossing = {k: sorted(v) for k, v in lineage_splits.items() if len(v) > 1}
    if crossing:
        problems.append(f"lineages crossing splits: {list(crossing)[:5]}")

    # permission boundary: features must not carry answer fields
    leakage: list[str] = []
    for asset in run_assets:
        if asset.role != ROLE_FEATURE_BUNDLE:
            continue
        forbidden = sorted(set(asset.meta or {}) & FORBIDDEN_FEATURE_FIELDS)
        if forbidden:
            leakage.append(f"{asset.asset_id}:{forbidden}")
        declared = set((asset.meta or {}).get("feature_fields", []) or [])
        bad = sorted(declared & FORBIDDEN_FEATURE_FIELDS)
        if bad:
            leakage.append(f"{asset.asset_id}:declared={bad}")
    if leakage:
        problems.append(f"forbidden fields inside feature bundles: {leakage[:5]}")

    # labels must exist separately from features
    feature_assets = [a for a in run_assets if a.role == ROLE_FEATURE_BUNDLE]
    label_assets = [a for a in run_assets if a.role == ROLE_LABEL_BUNDLE]
    if feature_assets and not label_assets:
        problems.append("feature bundles committed without separate label bundles")

    roles: dict[str, int] = {}
    for asset in run_assets:
        roles[asset.role] = roles.get(asset.role, 0) + 1

    coverage = {
        "mothers": roles.get(ROLE_MOTHER_MESH, 0),
        "observations": roles.get(ROLE_OBS_RESULT, 0),
        "features": roles.get(ROLE_FEATURE_BUNDLE, 0),
        "labels": roles.get(ROLE_LABEL_BUNDLE, 0),
        "by_role": roles,
    }
    report = {
        "schema": "synlab.audit_report.v1",
        "run_id": run_id,
        "run": {"status": run["status"], "scope": run["scope"], "profile": run.get("profile"),
                "spec_hash": run["spec_hash"]},
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "counts": {"jobs": len(jobs), "job_states": state_counts, "assets": len(run_assets)},
        "coverage": coverage,
        "store_health": health,
        "closure": {"ok": closure["ok"], "problems": closure["problems"][:5],
                    "files_checked": closure.get("files_checked")},
        "lineage_splits": {k: sorted(v) for k, v in lineage_splits.items()},
    }
    report["report_hash"] = hash_json({k: v for k, v in report.items() if k != "report_hash"})
    return report


def write_audit_report(store: AssetStore, report: dict[str, Any], name: str) -> Path:
    path = store.root / "reports" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
