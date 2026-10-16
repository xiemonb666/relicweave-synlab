"""Aggregate resource admission control (plan 6.4, 23.1).

Admission is decided on the sum of *all* concurrent reservations, never on the idle
capacity each job happens to observe.  Disk fraction thresholds gate new heavy tasks.
"""

from __future__ import annotations

import shutil
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..errors import ErrorCode, SynLabError
from ..storage.store import AssetStore, _dumps


@dataclass
class ResourceBudget:
    cpu_workers: int = 4
    threads_per_worker: int = 2
    cpu_rss_budget_gb: float = 30.0
    gpu_device: int = 0
    gpu_concurrency: int = 1
    gpu_budget_gb: float = 24.0
    disk_soft_fraction: float = 0.70
    disk_restrict_fraction: float = 0.80
    disk_stop_fraction: float = 0.90
    reserve_temp_peak: bool = True


@dataclass
class Estimate:
    rss_gb: float = 1.0
    vram_gb: float = 0.0
    temp_disk_gb: float = 0.5
    persistent_disk_gb: float = 0.0
    cpu_seconds: float = 10.0
    assumptions: dict[str, Any] = field(default_factory=dict)


class ResourceGuard:
    def __init__(self, store: AssetStore, budget: ResourceBudget, root: str | None = None):
        self.store = store
        self.budget = budget
        self.root = root or str(store.root)

    # ------------------------------------------------------------------ disk
    def disk_report(self) -> dict[str, Any]:
        usage = shutil.disk_usage(self.root)
        fraction = usage.used / usage.total
        level = "OK"
        if fraction >= self.budget.disk_stop_fraction:
            level = "STOP"
        elif fraction >= self.budget.disk_restrict_fraction:
            level = "RESTRICT"
        elif fraction >= self.budget.disk_soft_fraction:
            level = "WARN"
        return {
            "total_gb": usage.total / 2**30,
            "free_gb": usage.free / 2**30,
            "used_fraction": fraction,
            "level": level,
        }

    # ------------------------------------------------------------------ reservations
    def reserved(self) -> dict[str, float]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT kind, SUM(amount) AS total FROM reservations WHERE released_at IS NULL GROUP BY kind"
            ).fetchall()
        return {row["kind"]: float(row["total"] or 0.0) for row in rows}

    def admit(self, job_id: str, estimate: Estimate, *, requires_gpu: bool = False,
              heavy: bool = True) -> dict[str, Any]:
        disk = self.disk_report()
        if heavy and disk["level"] == "STOP":
            raise SynLabError(
                ErrorCode.BUDGET_EXCEEDED,
                f"disk usage {disk['used_fraction']:.2%} at/above stop threshold",
                stage="resource.admit", measurements=disk,
            )
        if heavy and disk["level"] == "RESTRICT":
            raise SynLabError(
                ErrorCode.BUDGET_EXCEEDED,
                f"disk usage {disk['used_fraction']:.2%} restricts new heavy tasks",
                stage="resource.admit", measurements=disk,
            )
        current = self.reserved()
        rss = current.get("rss_gb", 0.0) + estimate.rss_gb
        if rss > self.budget.cpu_rss_budget_gb:
            raise SynLabError(
                ErrorCode.BUDGET_EXCEEDED,
                f"aggregate RSS reservation {rss:.1f} GB exceeds budget {self.budget.cpu_rss_budget_gb} GB",
                stage="resource.admit",
                measurements={"requested": estimate.rss_gb, "reserved": current},
            )
        vram = current.get("vram_gb", 0.0)
        if requires_gpu:
            vram += estimate.vram_gb
            if vram > self.budget.gpu_budget_gb:
                raise SynLabError(
                    ErrorCode.BUDGET_EXCEEDED,
                    f"aggregate VRAM reservation {vram:.1f} GB exceeds budget {self.budget.gpu_budget_gb} GB",
                    stage="resource.admit",
                )
        temp = current.get("temp_disk_gb", 0.0) + estimate.temp_disk_gb
        free_gb = disk["free_gb"]
        if self.budget.reserve_temp_peak and temp > free_gb * (1 - self.budget.disk_soft_fraction):
            raise SynLabError(
                ErrorCode.BUDGET_EXCEEDED,
                f"temp disk reservation {temp:.1f} GB does not fit free {free_gb:.1f} GB under soft guard",
                stage="resource.admit",
            )
        reservation_id = "res_" + uuid.uuid4().hex[:16]
        with self.store.connect() as conn:
            for kind, amount in (("rss_gb", estimate.rss_gb), ("vram_gb", estimate.vram_gb if requires_gpu else 0.0),
                                 ("temp_disk_gb", estimate.temp_disk_gb),
                                 ("persistent_disk_gb", estimate.persistent_disk_gb)):
                if amount:
                    conn.execute(
                        """INSERT INTO reservations(reservation_id, job_id, kind, amount, created_at)
                           VALUES (?,?,?,?,?)""",
                        (f"{reservation_id}:{kind}", job_id, kind, amount, time.time()),
                    )
        return {"reservation_id": reservation_id, "disk": disk, "reserved": current,
                "estimate": estimate.assumptions}

    def release(self, reservation_id: str) -> None:
        with self.store.connect() as conn:
            conn.execute("UPDATE reservations SET released_at=? WHERE reservation_id LIKE ?",
                         (time.time(), f"{reservation_id}%"))

    def budget_report(self, planned_jobs: int = 1, estimates: list[Estimate] | None = None) -> dict[str, Any]:
        estimates = estimates or [Estimate()]
        total_rss = sum(e.rss_gb for e in estimates) * planned_jobs
        total_vram = max((e.vram_gb for e in estimates), default=0.0)
        total_temp = sum(e.temp_disk_gb for e in estimates) * planned_jobs
        persistent = sum(e.persistent_disk_gb for e in estimates) * planned_jobs
        disk = self.disk_report()
        feasible = (
            total_rss <= self.budget.cpu_rss_budget_gb
            and total_vram <= self.budget.gpu_budget_gb
            and total_temp <= disk["free_gb"] * (1 - self.budget.disk_soft_fraction) + persistent
        )
        return {
            "feasible": feasible,
            "jobs": planned_jobs,
            "rss_gb": total_rss,
            "rss_budget_gb": self.budget.cpu_rss_budget_gb,
            "vram_gb": total_vram,
            "vram_budget_gb": self.budget.gpu_budget_gb,
            "temp_disk_gb": total_temp,
            "persistent_disk_gb": persistent,
            "disk": disk,
            "assumptions": [e.assumptions for e in estimates],
            "note": "development initial values; not a measured throughput guarantee",
        }
