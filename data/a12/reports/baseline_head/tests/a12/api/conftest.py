"""Shared fixtures for the A12 API tests.

Everything runs against a real :class:`AssetStore` in a temporary directory and, where a
job has to execute, a real :class:`synlab.api.worker.Worker` or a real worker subprocess.
No endpoint is stubbed and no response is fabricated.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.api import create_app  # noqa: E402
from synlab.api.capabilities import capability_report  # noqa: E402
from synlab.roles import ROLE_MOTHER_MESH, SCHEMA_MOTHER  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

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


@pytest.fixture()
def store_root(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture()
def store(store_root: Path) -> AssetStore:
    return AssetStore(store_root)


@pytest.fixture()
def cube_asset(store: AssetStore) -> str:
    """Commit a real mm/Z-up cube and record payload integrity (the API's trusted path)."""
    from synlab.api.integrity import record_integrity

    record = store.commit_asset(
        role=ROLE_MOTHER_MESH, schema=SCHEMA_MOTHER, unit="mm", frame="W_mm",
        payload=cube_arrays(), qa={"watertight": True, "edge_mm": CUBE_EDGE_MM},
        qa_status="QA_PASS", meta={"vessel_id": "V01", "material_id": "M01",
                                   "workspace": "default", "test_fixture": True},
        lineage_id="lin_test_cube",
    )
    record_integrity(store, record.asset_id, source="producer")
    return record.asset_id


def make_client(store_root: Path, role: str = "researcher", workspace: str | None = None,
                **kwargs: Any) -> TestClient:
    app = create_app(store_root, role=role, workspace=workspace, **kwargs)
    return TestClient(app)


@pytest.fixture()
def researcher(store_root: Path) -> Iterator[TestClient]:
    client = make_client(store_root, "researcher")
    yield client
    client.close()


@pytest.fixture()
def operator(store_root: Path) -> Iterator[TestClient]:
    client = make_client(store_root, "operator")
    yield client
    client.close()


@pytest.fixture()
def deployment(store_root: Path) -> Iterator[TestClient]:
    client = make_client(store_root, "deployment_client")
    yield client
    client.close()


# --------------------------------------------------------------------------- helpers
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
    import subprocess

    python = sys.executable
    cmd = [python, "-m", "synlab.api.worker", "--store-root", str(store_root), "--once",
           "--json", "--quiet"]
    if workspace:
        cmd.extend(["--workspace", workspace])
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), env=env,
                               timeout=600)
    assert completed.returncode == 0, (
        f"worker failed rc={completed.returncode}\nstdout={completed.stdout}\nstderr={completed.stderr}")
    return json.loads(completed.stdout.strip().splitlines()[-1])


def probe_status(key: str) -> str:
    return capability_report(refresh=True)["modules"][key]["status"]
