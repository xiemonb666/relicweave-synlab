"""Fixtures for the degradation-axis routing audit (``tests/a12/degrade``).

The audit needs two kinds of source:

* the **real probe bundles** of :func:`synlab.degrade.api.probe_sources` (the same bundles the
  31-axis / 155-level operator contract audits), and
* one **real archived body** from ``data/a12_degrade/store`` when a test has to reproduce an
  S11/S12 number that was measured on that body (the 1.1402 mm grid, the 0.35424 mm drift).

Nothing here writes to the store; the archived body is only read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: The recipe ids of ``configs/a12/physical_recipes.json`` used by the P-axis before/after runs.
RECIPE_OF_AXIS = {"P02": "P02_round_edge_mid", "P03": "P03_depth_light",
                  "P04": "P04_chip_mid"}


@pytest.fixture(scope="session")
def probe() -> dict:
    """The four real probe bundles (physical / image / geometry / estimate)."""
    from synlab.degrade.api import probe_sources

    return probe_sources()


@pytest.fixture(scope="session")
def archived_body() -> dict:
    """The largest archived fragment mesh, or ``None`` when the store is absent.

    A missing store is an *unavailable fixture*, never a silent pass: the tests that need it are
    skipped with an explicit reason.  (``data/a12_degrade/store`` is present in this checkout, so
    the S12 numbers in ``docs/a12/degrade_axis_routing.md`` were produced with it.)
    """
    store_root = REPO_ROOT / "data" / "a12_degrade" / "store"
    if not store_root.exists():
        pytest.skip(f"archived store not present: {store_root}")
    sys.path.insert(0, str(REPO_ROOT / "tests" / "a12" / "degrade"))
    from _probe_axis_routing_audit import load_store_body

    _store, mesh, fragment_id = load_store_body(store_root)
    return {"mesh": mesh, "fragment_id": fragment_id, "store_root": str(store_root)}


@pytest.fixture(scope="session")
def sandbox_config() -> str:
    return str(REPO_ROOT / "configs" / "a12" / "sandbox.yaml")
