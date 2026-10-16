"""GPU lease with explicit drain before handover (plan 6.2 step 3, 30.17)."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

from ..errors import ErrorCode, SynLabError
from ..storage.store import AssetStore, _dumps


@dataclass
class Lease:
    device: str
    owner: str
    token: str
    acquired_at: float
    expires_at: float
    state: str
    pid: int | None


class LeaseManager:
    """One writer per device; a stale lease must be drained before a new owner starts.

    The GPU is never handed over on lease expiry alone: the previous process group must
    be stopped and the device verified released, otherwise the state is GPU_DRAIN_PENDING
    and no new occupant is allowed to start.
    """

    def __init__(self, store: AssetStore, *, ttl_seconds: float = 1800.0):
        self.store = store
        self.ttl = ttl_seconds

    def acquire(self, device: str, owner: str, *, pid: int | None = None,
                force: bool = False) -> Lease:
        now = time.time()
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM gpu_leases WHERE device = ?", (device,)).fetchone()
            if row is not None:
                expired = row["expires_at"] < now
                if not expired and not force:
                    conn.execute("ROLLBACK")
                    raise SynLabError(
                        ErrorCode.BUDGET_EXCEEDED,
                        f"GPU {device} held by {row['owner']} (state={row['state']})",
                        stage="lease.acquire",
                    )
                if expired and row["state"] != "DRAINED":
                    conn.execute(
                        "UPDATE gpu_leases SET state=? WHERE device=?",
                        ("DRAINING", device),
                    )
                    conn.execute("COMMIT")
                    raise SynLabError(
                        ErrorCode.GPU_DRAIN_PENDING,
                        f"GPU {device} lease expired ({row['owner']}); stop the previous "
                        f"process group and call confirm_drained() before acquiring",
                        stage="lease.acquire",
                        retryable=True,
                        measurements={"previous_owner": row["owner"], "pid": row["pid"]},
                    )
            token = uuid.uuid4().hex
            conn.execute(
                """INSERT INTO gpu_leases(device, owner, token, acquired_at, expires_at, state, pid, meta_json)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(device) DO UPDATE SET owner=excluded.owner, token=excluded.token,
                   acquired_at=excluded.acquired_at, expires_at=excluded.expires_at,
                   state='HELD', pid=excluded.pid, meta_json=excluded.meta_json""",
                (device, owner, token, now, now + self.ttl, "HELD", pid or os.getpid(), "{}"),
            )
            conn.execute("COMMIT")
        return Lease(device=device, owner=owner, token=token, acquired_at=now,
                     expires_at=now + self.ttl, state="HELD", pid=pid or os.getpid())

    def heartbeat(self, device: str, token: str) -> None:
        with self.store.connect() as conn:
            cur = conn.execute(
                "UPDATE gpu_leases SET expires_at=? WHERE device=? AND token=?",
                (time.time() + self.ttl, device, token),
            )
            if cur.rowcount != 1:
                raise SynLabError(ErrorCode.LEASE_STALE, f"GPU lease lost for {device}",
                                  stage="lease.heartbeat")

    def release(self, device: str, token: str) -> None:
        with self.store.connect() as conn:
            conn.execute("DELETE FROM gpu_leases WHERE device=? AND token=?", (device, token))

    def confirm_drained(self, device: str, *, stopped_pid: int | None = None) -> dict[str, Any]:
        """Mark a device as verified drained so the next acquire can proceed."""
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM gpu_leases WHERE device = ?", (device,)).fetchone()
            if row is None:
                return {"device": device, "state": "FREE"}
            conn.execute("UPDATE gpu_leases SET state='DRAINED', meta_json=? WHERE device=?",
                         (_dumps({"stopped_pid": stopped_pid, "confirmed_at": time.time()}), device))
        return {"device": device, "state": "DRAINED", "stopped_pid": stopped_pid}

    def status(self) -> list[dict[str, Any]]:
        with self.store.connect() as conn:
            rows = conn.execute("SELECT * FROM gpu_leases").fetchall()
        return [dict(r) for r in rows]
