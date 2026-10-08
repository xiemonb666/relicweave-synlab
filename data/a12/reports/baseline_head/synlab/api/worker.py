"""Independent worker process: ``python -m synlab.api.worker --store-root <dir>``.

Heavy computation must not run inside a request thread (plan 21.1), so the FastAPI
process only validates, enqueues and queries; this process claims jobs from the SQLite
scheduler, executes them with a lease + fencing token, and commits results atomically.

Exit codes: ``0`` = ran to completion (including "no ready jobs"), ``2`` = unusable
configuration, ``3`` = the store failed its integrity check.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import ErrorCode, SynLabError
from ..jobs.leases import LeaseManager
from ..jobs.resources import ResourceBudget, ResourceGuard
from ..jobs.scheduler import Scheduler
from ..jobs.state import JobState
from ..storage.store import AssetStore, health_check
from .handlers import HANDLERS, JobContext, estimate_for
from .tables import ensure_api_schema

GPU_DEVICE = "gpu:0"
HANDLER_CRASH = "HANDLER_CRASH"


@dataclass
class WorkerConfig:
    store_root: Path
    owner: str = "synlab-api-worker"
    poll_seconds: float = 1.0
    once: bool = False
    max_jobs: int | None = None
    lease_seconds: float = 900.0
    budget: ResourceBudget = field(default_factory=ResourceBudget)
    workspace: str | None = None
    verbose: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"store_root_configured": True, "owner": self.owner,
                "poll_seconds": self.poll_seconds, "once": self.once, "max_jobs": self.max_jobs,
                "lease_seconds": self.lease_seconds, "workspace": self.workspace}


class Worker:
    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self.store = AssetStore(config.store_root)
        ensure_api_schema(self.store)
        self.scheduler = Scheduler(self.store, owner=config.owner,
                                   lease_seconds=config.lease_seconds)
        self.guard = ResourceGuard(self.store, config.budget, root=str(self.store.root))
        self.leases = LeaseManager(self.store)
        self.stop_requested = False
        self.processed = 0
        self.failed = 0
        self.blocked = 0
        self.admission_blocked = 0
        self.startup_report: dict[str, Any] = {}

    # ------------------------------------------------------------------ lifecycle
    def request_stop(self, *_args: Any) -> None:
        self.stop_requested = True
        if self.config.verbose:
            print("[worker] stop requested; finishing the current job", file=sys.stderr)

    def preflight(self) -> dict[str, Any]:
        report = {"store_schema": None, "recovered": [], "jobs_by_state": {}}
        with self.store.connect() as conn:
            row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            report["store_schema"] = row["value"] if row else None
            for state_row in conn.execute("SELECT state, COUNT(*) AS n FROM jobs GROUP BY state"):
                report["jobs_by_state"][state_row["state"]] = int(state_row["n"])
        report["recovered"] = self.scheduler.recover_expired()
        self.startup_report = report
        return report

    # ------------------------------------------------------------------ main loop
    def run(self) -> int:
        self.preflight()
        while not self.stop_requested:
            did_work = self.tick()
            if self.config.once and not did_work:
                break
            if self.config.max_jobs is not None and self.processed >= self.config.max_jobs:
                break
            if self.config.once:
                break
            if not did_work:
                time.sleep(self.config.poll_seconds)
        return 0

    def tick(self) -> bool:
        """Claim and execute at most one ready job.  Returns True when work happened."""
        ready = self.scheduler.ready(limit=8)
        if not ready:
            return False
        for job in ready:
            if self.stop_requested:
                return False
            if self.config.workspace is not None:
                job_ws = (job.spec or {}).get("workspace", "default")
                if job_ws != self.config.workspace:
                    continue
            return self._execute(job.job_id)
        return False

    def _execute(self, job_id: str) -> bool:
        job = self.scheduler.get_job(job_id)
        stage = job.stage
        if stage not in HANDLERS:
            self.scheduler.claim(job_id)
            self.scheduler.fail(job_id, SynLabError(
                ErrorCode.SCHEMA_INVALID, f"no handler for stage {stage!r}", stage="worker.dispatch"))
            self.failed += 1
            return True
        stage_spec_obj = None
        from .stages import stage_spec as _stage_spec

        stage_spec_obj = _stage_spec(stage)
        estimate = estimate_for(stage)

        # ---- admission control before any lease is taken
        try:
            reservation = self.guard.admit(job_id, estimate, requires_gpu=stage_spec_obj.requires_gpu,
                                           heavy=(stage_spec_obj.cost_class == "heavy"))
        except SynLabError as exc:
            # capacity is a *queueing* condition: the job stays PENDING and keeps its draft.
            self.store.append_event(run_id=job.run_id, job_id=job_id, type="job.admission_blocked",
                                    state=JobState.PENDING.value, revision=0, message=exc.message,
                                    payload={"error": exc.to_dict(), "stage": stage})
            self.admission_blocked += 1
            if self.config.verbose:
                print(f"[worker] {job_id} admission blocked: {exc.message}", file=sys.stderr)
            return False

        lease = None
        if stage_spec_obj.requires_gpu:
            try:
                lease = self.leases.acquire(GPU_DEVICE, self.config.owner)
            except SynLabError as exc:
                self.guard.release(reservation["reservation_id"])
                self.store.append_event(run_id=job.run_id, job_id=job_id, type="job.gpu_blocked",
                                        state=JobState.PENDING.value, revision=0, message=exc.message,
                                        payload={"error": exc.to_dict()})
                self.blocked += 1
                return False

        try:
            record, token, fence = self.scheduler.claim(job_id)
        except SynLabError as exc:
            self.guard.release(reservation["reservation_id"])
            if lease is not None:
                self.leases.release(GPU_DEVICE, lease.token)
            self.store.append_event(run_id=job.run_id, job_id=job_id, type="job.claim_rejected",
                                    state=job.state, revision=0, message=exc.message,
                                    payload={"error": exc.to_dict()})
            self.blocked += 1
            return False

        ctx = JobContext(store=self.store, scheduler=self.scheduler, guard=self.guard, job=record,
                         token=token, fence=fence,
                         workspace=(record.spec or {}).get("workspace", "default"))
        started = time.time()
        try:
            result = HANDLERS[stage](ctx)
        except SynLabError as exc:
            self.scheduler.fail(job_id, exc, token=token, fence=fence)
            current = self.scheduler.get_job(job_id)
            if current.state == JobState.FAILED.value:
                blocked = self.scheduler.block_dependents(job_id, exc.message)
                if blocked:
                    self.store.append_event(run_id=job.run_id, job_id=job_id, type="job.dependents_blocked",
                                            state=JobState.BLOCKED.value, revision=fence,
                                            message=f"{len(blocked)} dependents blocked",
                                            payload={"blocked": blocked})
                self.failed += 1
            else:
                self.blocked += 1
            if self.config.verbose:
                print(f"[worker] {job_id} {stage} failed: [{exc.code}] {exc.message}", file=sys.stderr)
        except BaseException as exc:  # noqa: BLE001 - crash must become a structured failure
            crash = SynLabError(HANDLER_CRASH, f"{type(exc).__name__}: {exc}",
                                stage=f"handler.{stage}")
            self.scheduler.fail(job_id, crash, token=token, fence=fence)
            self.failed += 1
            if self.config.verbose:
                print(f"[worker] {job_id} {stage} crashed: {crash.message}", file=sys.stderr)
        else:
            self._commit_success(record, result, token=token, fence=fence, started=started)
            self.processed += 1
        finally:
            self.guard.release(reservation["reservation_id"])
            if lease is not None:
                self.leases.release(GPU_DEVICE, lease.token)
        return True

    def _commit_success(self, job: Any, result: dict[str, Any], *, token: str, fence: int,
                        started: float) -> None:
        outputs = list(result.get("outputs") or [])
        if outputs:
            self.scheduler.record_outputs(job.job_id, outputs, token=token, fence=fence)
        self.scheduler.transition(job.job_id, JobState.OUTPUT_READY, token=token, fence=fence,
                                  message="outputs committed",
                                  payload={"outputs": outputs, "elapsed_s": time.time() - started})
        qa_status = "QA_PASS" if outputs else "QA_FAIL"
        self.scheduler.transition(job.job_id, JobState.QA_PASS, token=token, fence=fence,
                                  message=qa_status)
        self.scheduler.transition(job.job_id, JobState.COMMITTED, token=token, fence=fence,
                                  message="committed",
                                  payload={"metrics": result.get("metrics", {}),
                                           "outputs": outputs})
        if self.config.verbose:
            print(f"[worker] {job.job_id} {job.stage} committed outputs={outputs}")


# --------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synlab.api.worker",
                                     description="A12 SynLab background worker")
    parser.add_argument("--store-root", required=True, help="asset store root directory")
    parser.add_argument("--owner", default=f"synlab-worker:{Path.cwd().name}")
    parser.add_argument("--poll", type=float, default=1.0, help="idle poll interval in seconds")
    parser.add_argument("--once", action="store_true", help="drain ready jobs then exit")
    parser.add_argument("--max-jobs", type=int, default=None, help="stop after N completed jobs")
    parser.add_argument("--lease-seconds", type=float, default=900.0)
    parser.add_argument("--workspace", default=None, help="only execute jobs in this workspace")
    parser.add_argument("--health-check", action="store_true",
                        help="run the store integrity check before starting")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json", action="store_true", help="print a JSON run report on exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store_root = Path(args.store_root).expanduser()
    if not store_root.exists():
        print(f"[worker] store root does not exist: {store_root}", file=sys.stderr)
        return 2
    config = WorkerConfig(store_root=store_root, owner=args.owner, poll_seconds=args.poll,
                          once=args.once, max_jobs=args.max_jobs, lease_seconds=args.lease_seconds,
                          workspace=args.workspace, verbose=not args.quiet)
    if args.health_check:
        report = health_check(store_root)
        if not report["ok"]:
            print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
            return 3
    worker = Worker(config)
    signal.signal(signal.SIGINT, worker.request_stop)
    try:
        signal.signal(signal.SIGTERM, worker.request_stop)
    except (AttributeError, ValueError):  # pragma: no cover - platform dependent
        pass
    code = worker.run()
    report = {
        "owner": config.owner,
        "processed": worker.processed,
        "failed": worker.failed,
        "blocked": worker.blocked,
        "admission_blocked": worker.admission_blocked,
        "startup": worker.startup_report,
        "config": config.as_dict(),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    elif not args.quiet:
        print(f"[worker] processed={worker.processed} failed={worker.failed} "
              f"blocked={worker.blocked} admission_blocked={worker.admission_blocked}")
    return code


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
