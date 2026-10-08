"""Measured resource profile for a run (plan 23.1, 23.4): real timings, not estimates."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..errors import ErrorCode, SynLabError
from ..jobs.scheduler import Scheduler
from ..storage.store import AssetStore, health_check


def profile_run(store: AssetStore, run_id: str) -> dict[str, Any]:
    scheduler = Scheduler(store)
    jobs = scheduler.list_jobs(run_id=run_id, limit=10000)
    if not jobs:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"run {run_id} has no jobs to profile",
                          stage="qc.profile")
    by_stage: dict[str, dict[str, Any]] = {}
    for job in jobs:
        stage = by_stage.setdefault(job.stage, {"jobs": 0, "seconds": 0.0, "attempts": 0,
                                                "states": {}, "assets": 0})
        stage["jobs"] += 1
        stage["attempts"] += job.attempt
        stage["seconds"] += max(0.0, job.updated_at - job.created_at)
        stage["states"][job.state] = stage["states"].get(job.state, 0) + 1
        stage["assets"] += len(job.outputs)
    assets = [a for a in store.list_assets(limit=100000) if (a.meta or {}).get("run_id") == run_id]
    bytes_total = 0
    per_role_bytes: dict[str, int] = {}
    for asset in assets:
        for name, rel in (asset.files or {}).items():
            path = store.root / Path(*str(rel).split("/"))
            if path.exists():
                size = path.stat().st_size
                bytes_total += size
                per_role_bytes[asset.role] = per_role_bytes.get(asset.role, 0) + size
    durations = sorted(max(0.0, job.updated_at - job.created_at) for job in jobs)
    p50 = durations[len(durations) // 2] if durations else 0.0
    p95 = durations[min(len(durations) - 1, int(len(durations) * 0.95))] if durations else 0.0
    report = {
        "ok": True,
        "run_id": run_id,
        "jobs": len(jobs),
        "by_stage": by_stage,
        "per_job_seconds": {"p50": p50, "p95": p95, "max": durations[-1] if durations else 0.0},
        "assets": len(assets),
        "bytes_total": bytes_total,
        "bytes_per_role": per_role_bytes,
        "store_health": health_check(str(store.root)),
        "generated_at": time.time(),
        "note": ("wall time and bytes are measured from committed jobs/assets; CPU RSS and GPU VRAM "
                 "per job are recorded by workers in job spec when available"),
    }
    return report


def record_worker_metrics(store: AssetStore, run_id: str, job_id: str, metrics: dict[str, Any]) -> None:
    """Persist real worker metrics (RSS/VRAM/IO) alongside the run for later profiling."""
    store.append_event(run_id=run_id, job_id=job_id, type="job.metrics", state="RUNNING",
                       message="worker metrics", payload=metrics)
