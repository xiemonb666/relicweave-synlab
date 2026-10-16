"""Transactional scheduler: leases, fencing, retries, dependency gating, recovery.

Implements plan 6.2 (1-6) and 30.17: a single SQLite writer claims jobs with a lease and
fencing token, output files are written to an attempt-private directory, and a stale
worker can never commit because its fencing token no longer matches.
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..storage.store import AssetStore, _dumps
from .state import JobState, require_transition

DEFAULT_LEASE_SECONDS = 900.0
MAX_ATTEMPTS = 3


@dataclass
class JobRecord:
    job_id: str
    run_id: str
    stage: str
    state: str
    attempt: int
    owner: str | None
    lease_token: str | None
    fencing: int
    spec: dict[str, Any]
    inputs: list[str]
    outputs: list[str]
    error: dict[str, Any] | None
    created_at: float
    updated_at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id, "run_id": self.run_id, "stage": self.stage, "state": self.state,
            "attempt": self.attempt, "owner": self.owner, "fencing": self.fencing,
            "inputs": self.inputs, "outputs": self.outputs, "error": self.error,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "progress": self.spec.get("progress"),
        }


class Scheduler:
    def __init__(self, store: AssetStore, *, owner: str | None = None,
                 lease_seconds: float = DEFAULT_LEASE_SECONDS):
        self.store = store
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.lease_seconds = lease_seconds

    # ------------------------------------------------------------------ creation
    def create_job(self, *, job_id: str, run_id: str, stage: str, spec: dict[str, Any],
                   inputs: Sequence[str] = (), depends_on: Sequence[str] = ()) -> JobRecord:
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """INSERT INTO jobs(job_id, run_id, stage, inputs_json, state, attempt,
                       spec_json, created_at, updated_at)
                       VALUES (?,?,?,?,?,0,?,?,?)""",
                    (job_id, run_id, stage, _dumps(list(inputs)), JobState.PENDING.value,
                     _dumps(spec), time.time(), time.time()),
                )
                for dep in depends_on:
                    conn.execute("INSERT OR IGNORE INTO dependencies(job_id, depends_on) VALUES (?,?)",
                                 (job_id, dep))
                self._assert_acyclic(conn)
                conn.execute(
                    """INSERT INTO events(run_id, job_id, type, state, revision, message, payload_json, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (run_id, job_id, "job.created", JobState.PENDING.value, 0, stage,
                     _dumps({"deps": list(depends_on)}), time.time()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get_job(job_id)

    def _assert_acyclic(self, conn: Any) -> None:
        rows = conn.execute("SELECT job_id, depends_on FROM dependencies").fetchall()
        graph: dict[str, list[str]] = {}
        for row in rows:
            graph.setdefault(row["job_id"], []).append(row["depends_on"])
        state: dict[str, int] = {}
        def visit(node: str, stack: set[str]) -> None:
            if state.get(node) == 2:
                return
            if node in stack:
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  f"dependency cycle detected at {node}", stage="scheduler.dag")
            stack.add(node)
            for nxt in graph.get(node, []):
                visit(nxt, stack)
            stack.discard(node)
            state[node] = 2
        for node in list(graph):
            visit(node, set())

    # ------------------------------------------------------------------ queries
    def get_job(self, job_id: str) -> JobRecord:
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown job {job_id}", stage="scheduler.get_job")
        return self._row(row)

    def _row(self, row: Any) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"], run_id=row["run_id"], stage=row["stage"], state=row["state"],
            attempt=int(row["attempt"]), owner=row["owner"], lease_token=row["lease_token"],
            fencing=int(row["fencing"]), spec=json.loads(row["spec_json"]),
            inputs=json.loads(row["inputs_json"]), outputs=json.loads(row["output_json"]),
            error=json.loads(row["error_json"]) if row["error_json"] else None,
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def list_jobs(self, *, run_id: str | None = None, state: str | None = None,
                  limit: int = 200, cursor: int = 0) -> list[JobRecord]:
        query = "SELECT * FROM jobs WHERE 1=1"
        params: list[Any] = []
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        if state:
            query += " AND state = ?"
            params.append(state)
        query += " ORDER BY created_at ASC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(cursor)])
        with self.store.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row(r) for r in rows]

    def dependencies(self, job_id: str) -> list[str]:
        with self.store.connect() as conn:
            rows = conn.execute("SELECT depends_on FROM dependencies WHERE job_id = ?", (job_id,)).fetchall()
        return [r["depends_on"] for r in rows]

    def ready(self, limit: int = 16) -> list[JobRecord]:
        """PENDING jobs whose dependencies are all COMMITTED."""
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE state = ? ORDER BY created_at ASC LIMIT ?",
                (JobState.PENDING.value, int(limit * 4)),
            ).fetchall()
            out = []
            for row in rows:
                deps = conn.execute("SELECT depends_on FROM dependencies WHERE job_id = ?",
                                    (row["job_id"],)).fetchall()
                ok = True
                for dep in deps:
                    dep_row = conn.execute("SELECT state FROM jobs WHERE job_id = ?",
                                           (dep["depends_on"],)).fetchone()
                    if dep_row is None or dep_row["state"] != JobState.COMMITTED.value:
                        ok = False
                        break
                if ok:
                    out.append(self._row(row))
                if len(out) >= limit:
                    break
        return out

    # ------------------------------------------------------------------ lease / claim
    def claim(self, job_id: str, *, owner: str | None = None) -> tuple[JobRecord, str, int]:
        """Atomically claim a job: sets RUNNING, mints a lease token, bumps the fence."""
        owner = owner or self.owner
        now = time.time()
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown job {job_id}", stage="scheduler.claim")
            state = JobState(row["state"])
            if state not in (JobState.PENDING, JobState.RETRYABLE):
                conn.execute("ROLLBACK")
                raise SynLabError(ErrorCode.LEASE_STALE,
                                  f"job {job_id} not claimable in state {state.value}",
                                  stage="scheduler.claim")
            for dep in conn.execute("SELECT depends_on FROM dependencies WHERE job_id = ?", (job_id,)).fetchall():
                dep_row = conn.execute("SELECT state FROM jobs WHERE job_id = ?", (dep["depends_on"],)).fetchone()
                if dep_row is None or dep_row["state"] != JobState.COMMITTED.value:
                    conn.execute("ROLLBACK")
                    raise SynLabError(ErrorCode.LEASE_STALE,
                                      f"job {job_id} dependency {dep['depends_on']} not COMMITTED",
                                      stage="scheduler.claim")
            attempt = int(row["attempt"]) + 1
            token = uuid.uuid4().hex
            fence = int(row["fencing"]) + 1
            conn.execute(
                """UPDATE jobs SET state=?, owner=?, lease_token=?, fencing=?, heartbeat=?,
                   lease_expires=?, attempt=?, updated_at=? WHERE job_id=?""",
                (JobState.RUNNING.value, owner, token, fence, now, now + self.lease_seconds,
                 attempt, now, job_id),
            )
            conn.execute(
                """INSERT INTO events(run_id, job_id, type, state, revision, message, payload_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (row["run_id"], job_id, "job.running", JobState.RUNNING.value, fence, owner,
                 _dumps({"attempt": attempt}), now),
            )
            conn.execute("COMMIT")
        return self.get_job(job_id), token, fence

    def heartbeat(self, job_id: str, token: str, fence: int) -> None:
        now = time.time()
        with self.store.connect() as conn:
            cur = conn.execute(
                """UPDATE jobs SET heartbeat=?, lease_expires=?, updated_at=?
                   WHERE job_id=? AND lease_token=? AND fencing=?""",
                (now, now + self.lease_seconds, now, job_id, token, fence),
            )
            if cur.rowcount != 1:
                raise SynLabError(ErrorCode.LEASE_STALE, f"heartbeat rejected for {job_id}",
                                  stage="scheduler.heartbeat")

    def _check_fence(self, conn: Any, job_id: str, token: str | None, fence: int | None) -> Any:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown job {job_id}", stage="scheduler.fence")
        if token is not None and row["lease_token"] != token:
            raise SynLabError(ErrorCode.LEASE_STALE,
                              f"stale lease token for {job_id}", stage="scheduler.fence")
        if fence is not None and int(row["fencing"]) != int(fence):
            raise SynLabError(ErrorCode.LEASE_STALE,
                              f"stale fencing token for {job_id}", stage="scheduler.fence")
        return row

    # ------------------------------------------------------------------ transitions
    def transition(self, job_id: str, dst: JobState | str, *, token: str | None = None,
                   fence: int | None = None, message: str = "",
                   payload: dict[str, Any] | None = None,
                   error: dict[str, Any] | None = None) -> JobRecord:
        dst = JobState(dst)
        now = time.time()
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._check_fence(conn, job_id, token, fence)
            require_transition(row["state"], dst)
            conn.execute("UPDATE jobs SET state=?, updated_at=?, error_json=? WHERE job_id=?",
                         (dst.value, now, _dumps(error) if error else row["error_json"], job_id))
            conn.execute(
                """INSERT INTO events(run_id, job_id, type, state, revision, message, payload_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (row["run_id"], job_id, f"job.{dst.value.lower()}", dst.value, int(row["fencing"]),
                 message, _dumps(payload or {}), now),
            )
            conn.execute("COMMIT")
        return self.get_job(job_id)

    def record_outputs(self, job_id: str, asset_ids: Sequence[str], *, token: str | None = None,
                       fence: int | None = None) -> JobRecord:
        now = time.time()
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._check_fence(conn, job_id, token, fence)
            merged = sorted(set(json.loads(row["output_json"])) | set(asset_ids))
            conn.execute("UPDATE jobs SET output_json=?, updated_at=? WHERE job_id=?",
                         (_dumps(merged), now, job_id))
            conn.execute("COMMIT")
        return self.get_job(job_id)

    # ------------------------------------------------------------------ failure paths
    def fail(self, job_id: str, exc: SynLabError, *, token: str | None = None,
             fence: int | None = None) -> JobRecord:
        record = self.get_job(job_id)
        current = JobState(record.state)
        retryable = bool(exc.retryable) and record.attempt < MAX_ATTEMPTS
        target = JobState.RETRYABLE if retryable else JobState.FAILED
        if current in (JobState.RUNNING, JobState.OUTPUT_READY, JobState.QA_PASS):
            return self.transition(job_id, target, token=token, fence=fence, message=exc.message,
                                   error=exc.to_dict())
        if current is JobState.RETRYABLE and not retryable:
            return self.transition(job_id, JobState.FAILED, token=token, fence=fence,
                                   message=exc.message, error=exc.to_dict())
        if current is JobState.PENDING and not retryable:
            # failed before it ever ran (validation / dependency error): terminal failure
            return self.transition(job_id, JobState.FAILED, token=token, fence=fence,
                                   message=exc.message, error=exc.to_dict())
        return record

    def requeue(self, job_id: str, *, token: str | None = None, fence: int | None = None) -> JobRecord:
        """RETRYABLE -> PENDING with a new execution attempt (content seed unchanged)."""
        return self.transition(job_id, JobState.PENDING, token=token, fence=fence,
                               message="retry scheduled")

    def block_dependents(self, job_id: str, reason: str) -> list[str]:
        """Move PENDING dependents of a failed job to BLOCKED (plan 6.1)."""
        blocked: list[str] = []
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT job_id FROM dependencies WHERE depends_on = ?", (job_id,)).fetchall()
            for row in rows:
                child = conn.execute("SELECT state FROM jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
                if child and child["state"] == JobState.PENDING.value:
                    conn.execute("UPDATE jobs SET state=?, updated_at=? WHERE job_id=?",
                                 (JobState.BLOCKED.value, time.time(), row["job_id"]))
                    conn.execute(
                        """INSERT INTO events(run_id, job_id, type, state, revision, message, payload_json, created_at)
                           VALUES ((SELECT run_id FROM jobs WHERE job_id=?),?,?,?,0,?,?,?)""",
                        (row["job_id"], row["job_id"], "job.blocked", JobState.BLOCKED.value,
                         reason, "{}", time.time()),
                    )
                    blocked.append(row["job_id"])
        return blocked

    # ------------------------------------------------------------------ recovery
    def recover_expired(self, now: float | None = None) -> list[dict[str, Any]]:
        """Reclaim jobs whose lease expired; a stale worker cannot re-commit (fence bump)."""
        now = now or time.time()
        recovered: list[dict[str, Any]] = []
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT * FROM jobs WHERE state = ? AND lease_expires IS NOT NULL AND lease_expires < ?",
                (JobState.RUNNING.value, now),
            ).fetchall()
            for row in rows:
                next_state = JobState.PENDING if int(row["attempt"]) < MAX_ATTEMPTS else JobState.FAILED
                fence = int(row["fencing"]) + 1
                conn.execute(
                    "UPDATE jobs SET state=?, fencing=?, owner=NULL, lease_token=NULL, updated_at=? WHERE job_id=?",
                    (next_state.value, fence, now, row["job_id"]),
                )
                conn.execute(
                    """INSERT INTO events(run_id, job_id, type, state, revision, message, payload_json, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (row["run_id"], row["job_id"], "job.recovered", next_state.value, fence,
                     f"expired lease from {row['owner']}", _dumps({"attempt": row["attempt"]}), now),
                )
                recovered.append({"job_id": row["job_id"], "from": row["state"], "to": next_state.value,
                                  "fencing": fence})
            conn.execute("COMMIT")
        return recovered

    # ------------------------------------------------------------------ idempotency
    def idempotent_lookup(self, key: str, payload: dict[str, Any]) -> tuple[str, str] | None:
        payload_hash = hash_json(payload)
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM idempotency WHERE idempotency_key = ?", (key,)).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != payload_hash:
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                f"idempotency key {key} reused with a different payload",
                stage="scheduler.idempotency",
            )
        return row["job_id"], row["run_id"]

    def idempotent_record(self, key: str, payload: dict[str, Any], job_id: str, run_id: str) -> None:
        with self.store.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO idempotency(idempotency_key, payload_hash, job_id, run_id, created_at)
                   VALUES (?,?,?,?,?)""",
                (key, hash_json(payload), job_id, run_id, time.time()),
            )
