"""Shared fixtures for the A12 API tests.

Everything runs against a real :class:`AssetStore` in a temporary directory and, where a
job has to execute, a real :class:`synlab.api.worker.Worker` or a real worker subprocess.
No endpoint is stubbed and no response is fabricated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from synlab.roles import ROLE_MOTHER_MESH, SCHEMA_MOTHER  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402
from tests.a12.api.api_test_support import (
    CUBE_EDGE_MM,
    cube_arrays,
    make_client,
)


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


