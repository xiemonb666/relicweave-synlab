"""Fixtures for the 31-axis operator test suite (``tests/a12/operators``).

The sources are the *real* probe bundles produced by
:func:`synlab.degrade.api.probe_sources`: a real proxy-scan observation (128x96, 4 views) plus a
labelled synthetic probe body.  Every bundle carries ``meta['provenance']`` so a test failure can
never be confused with a production asset.
"""

from __future__ import annotations

import pytest

from synlab.degrade.api import probe_sources
from synlab.degrade.sources import commit_source, load_source
from synlab.roles import (
    ROLE_FEATURE_BUNDLE,
    ROLE_OBS_FUSED,
    ROLE_OBS_VIEW,
    ROLE_PHYSICAL_COMPONENT,
    SCHEMA_FEATURE,
    SCHEMA_OBS,
    SCHEMA_PHYSICAL,
)
from synlab.storage.store import AssetStore

#: role / schema used when a probe bundle is committed for the identity tests.
ROLE_SCHEMA = {
    "P": (ROLE_PHYSICAL_COMPONENT, SCHEMA_PHYSICAL),
    "I": (ROLE_OBS_VIEW, SCHEMA_OBS),
    "G": (ROLE_OBS_FUSED, SCHEMA_OBS),
    "X": (ROLE_FEATURE_BUNDLE, SCHEMA_FEATURE),
}

@pytest.fixture(scope="session")
def probe() -> dict:
    """The four real probe bundles (physical / image / geometry / estimate)."""
    return probe_sources()


@pytest.fixture(scope="session")
def source_store(tmp_path_factory: pytest.TempPathFactory) -> AssetStore:
    return AssetStore(tmp_path_factory.mktemp("degrade_operators"))


@pytest.fixture(scope="session")
def stored_sources(source_store: AssetStore, probe: dict) -> dict:
    """Probe bundles committed to a real store and read back (so they carry ``asset_id``)."""
    out = {}
    for key, bundle in probe.items():
        role, schema = ROLE_SCHEMA[key]
        record = commit_source(source_store, bundle, role=role, schema=schema,
                               lineage_id="operators_lineage", split="train")
        reloaded = load_source(source_store, record.asset_id)
        reloaded.meta["provenance"] = bundle.meta.get("provenance", "UNKNOWN")
        out[key] = reloaded
    return out
