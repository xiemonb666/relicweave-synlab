"""Named helpers shared by the A12 API tests.

Keep these outside ``conftest`` so test modules do not depend on pytest's
basename-based ``conftest`` import behavior during full-suite collection.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient

from synlab.api import create_app
from synlab.api.capabilities import capability_report

REPO_ROOT = Path(__file__).resolve().parents[3]
CUBE_EDGE_MM = 100.0


def cube_arrays(edge_mm: float = CUBE_EDGE_MM) -> dict[str, np.ndarray]:
    """A real 100 mm edge cube: 8 vertices, 12 triangles, centred on the origin."""
    half = edge_mm / 2.0
    vertices = np.array([
        [-half, -half, -half], [+half, -half, -half], [+half, +half, -half], [-half, +half, -half],
        [-half, -half, +half], [+half, -half, +half], [+half, +half, +half], [-half, +half, +half],
    ], dtype=np.float64)
    faces = np.array([
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6],
        [3, 0, 4], [3, 4, 7],
    ], dtype=np.int64)
    return {"mesh.vertices": vertices, "mesh.faces": faces}


def valid_spec(**overrides: Any) -> dict[str, Any]:
    """A minimal, genuinely valid ``synlab.v3`` spec for the local development profile."""
    spec: dict[str, Any] = {
        "schema": "synlab.v3",
        "data_scope": "SYNTHETIC",
        "release_profile": "SANDBOX_CORE",
        "experiment_purpose": "DEVELOPMENT",
        "master_seed": 20261001,
        "implementation": {"require_poc_before_custom": False},
        "dataset": {
            "target_mothers": 1,
            "target_fragments_estimate": 8,
            "vessel_ids": ["V01"],
            "material_ids": ["M01"],
            "pattern_ids": ["PAT01"],
            "layer_combo_ids": ["L01"],
        },
        "fracture": {"backend": "rough_shared_cut"},
    }
    spec.update(overrides)
    return spec


def make_client(store_root: Path, role: str = "researcher", workspace: str | None = None,
                **kwargs: Any) -> TestClient:
    return TestClient(create_app(store_root, role=role, workspace=workspace, **kwargs))


def create_job(client: TestClient, *, stage: str = "freeze_spec", key: str | None = None,
               spec: dict[str, Any] | None = None, input_refs: list[str] | None = None,
               **extra: Any):
    body = {
        "schema_version": "synlab.v3",
        "idempotency_key": key or f"test-{stage}-{time.time_ns()}",
        "stage": stage,
        "spec": spec if spec is not None else valid_spec(),
        "input_refs": input_refs or [],
    }
    body.update(extra)
    return client.post("/api/synlab/jobs", json=body)


def run_worker_once(store_root: Path, *, workspace: str | None = None) -> dict[str, Any]:
    """Execute ready jobs in a real subprocess so the request thread stays free."""
    cmd = [sys.executable, "-m", "synlab.api.worker", "--store-root", str(store_root), "--once",
           "--json", "--quiet"]
    if workspace:
        cmd.extend(["--workspace", workspace])

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), env=env,
                               timeout=600)
    assert completed.returncode == 0, (
        f"worker failed rc={completed.returncode}\nstdout={completed.stdout}\nstderr={completed.stderr}")
    return json.loads(completed.stdout.strip().splitlines()[-1])


def probe_status(key: str) -> str:
    return capability_report(refresh=True)["modules"][key]["status"]
