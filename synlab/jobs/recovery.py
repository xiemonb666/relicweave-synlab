"""Recovery from safe points: stale leases, retryable jobs, blocked dependents (plan 6.2, 30.17)."""

from __future__ import annotations

import time
import uuid
from typing import Any

from ..errors import ErrorCode, SynLabError
from ..storage.store import AssetStore
from .scheduler import MAX_ATTEMPTS, Scheduler
from .state import JobState


def resume_run(store: AssetStore, run_id: str) -> dict[str, Any]:
    """Reclaim expired leases, requeue retryable jobs and unblock repaired dependents."""
    scheduler = Scheduler(store)
    try:
        store.get_run(run_id)
    except SynLabError as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, exc.message, stage="jobs.resume") from exc

    recovered = [r for r in scheduler.recover_expired() if True]
    requeued: list[str] = []
    unblocked: list[str] = []
    still_blocked: list[dict[str, str]] = []
    exhausted: list[str] = []

    jobs = scheduler.list_jobs(run_id=run_id, limit=10000)
    for job in jobs:
        if job.state == JobState.RETRYABLE.value:
            if job.attempt >= MAX_ATTEMPTS:
                scheduler.transition(job.job_id, JobState.FAILED, message="retry budget exhausted")
                exhausted.append(job.job_id)
            else:
                scheduler.requeue(job.job_id)
                requeued.append(job.job_id)
        elif job.state == JobState.BLOCKED.value:
            deps = scheduler.dependencies(job.job_id)
            ready = True
            for dep in deps:
                dep_state = scheduler.get_job(dep).state
                if dep_state != JobState.COMMITTED.value:
                    ready = False
                    still_blocked.append({"job_id": job.job_id, "dependency": dep, "state": dep_state})
                    break
            if ready:
                scheduler.transition(job.job_id, JobState.PENDING, message="dependencies repaired")
                unblocked.append(job.job_id)

    remaining = scheduler.list_jobs(run_id=run_id, limit=10000)
    states: dict[str, int] = {}
    for job in remaining:
        states[job.state] = states.get(job.state, 0) + 1
    report = {
        "run_id": run_id,
        "ok": True,
        "recovered_leases": recovered,
        "requeued": requeued,
        "unblocked": unblocked,
        "still_blocked": still_blocked,
        "exhausted": exhausted,
        "job_states": states,
        "generated_at": time.time(),
        "note": ("content seeds are never changed by a retry; only execution attempts increase. "
                 "A stale worker cannot commit because its fencing token is obsolete."),
    }
    store.append_event(run_id=run_id, job_id=None, type="run.resumed", state="RUNNING",
                       message="recovery pass", payload={"requeued": len(requeued),
                                                         "unblocked": len(unblocked)})
    return report


def recovery_probe(store: AssetStore) -> dict[str, Any]:
    """Fault-injection probe used by the A17/A34 acceptance items.

    Kills a fake worker mid-write (leaving an attempt directory), expires its lease and
    verifies that (a) the stale owner cannot commit and (b) a fresh attempt can.
    """
    from ..canonical import hash_json

    scheduler = Scheduler(store, lease_seconds=0.5)
    run_id = f"probe_recovery_{uuid.uuid4().hex[:8]}"
    store.create_run(run_id, hash_json({"probe": True}), scope="SANDBOX", profile="SANDBOX_CORE")
    job_id = f"probe_job_{uuid.uuid4().hex[:8]}"
    scheduler.create_job(job_id=job_id, run_id=run_id, stage="probe", spec={})
    record, token, fence = scheduler.claim(job_id)
    attempt_dir = store.attempt_dir(f"{job_id}_attempt{record.attempt}")
    partial = attempt_dir / "partial.bin"
    partial.write_bytes(b"partial write from a worker that will be killed")
    time.sleep(0.6)
    recovered = scheduler.recover_expired()
    stale_commit_blocked = False
    try:
        scheduler.transition(job_id, JobState.OUTPUT_READY, token=token, fence=fence)
    except SynLabError as exc:
        stale_commit_blocked = exc.code == ErrorCode.LEASE_STALE
    record2, token2, fence2 = scheduler.claim(job_id)
    scheduler.transition(job_id, JobState.OUTPUT_READY, token=token2, fence=fence2)
    scheduler.transition(job_id, JobState.QA_PASS, token=token2, fence=fence2)
    scheduler.transition(job_id, JobState.COMMITTED, token=token2, fence=fence2)
    return {
        "ok": stale_commit_blocked and scheduler.get_job(job_id).state == JobState.COMMITTED.value,
        "stale_commit_blocked": stale_commit_blocked,
        "recovered": recovered,
        "final_state": scheduler.get_job(job_id).state,
        "partial_file_isolated": partial.exists(),
    }
