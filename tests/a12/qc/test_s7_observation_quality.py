"""Quality measurements stay on the research side of deploy schema v2."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from _fixtures import REPO_ROOT
from synlab.errors import ErrorCode, SynLabError
from synlab.qc.loader_probe import load_features
from synlab.storage.export import TrainingPackage

STORE = REPO_ROOT / "data" / "a12_exports" / "closed_loop" / "store"
RELEASE = "rel_852ab2a1e4c3_1790909619"


@pytest.fixture(scope="module")
def exported(tmp_path_factory) -> Path:
    if not (STORE / "releases" / RELEASE / "manifest.json").is_file():
        pytest.skip(f"store {STORE} carries no release {RELEASE}")
    from synlab.storage.export import export_training_package
    from synlab.storage.store import AssetStore

    out = tmp_path_factory.mktemp("s7_v2") / "training_package"
    export_training_package(AssetStore(STORE), RELEASE, out,
                            formats=("parquet", "npz", "tar"), include_truth=True)
    return out


def test_deploy_index_contains_no_research_quality_block(exported: Path) -> None:
    deploy = TrainingPackage(exported)
    index = deploy.observation_index()
    assert set(index) == {"schema", "channels", "rows"}
    assert index["schema"] == "synlab.obs_index.v2"
    assert index["rows"]
    assert all(set(row) == {"shard", "views", "shape", "hash", "channels",
                            "view_pos_source"} for row in index["rows"].values())


def test_measured_quality_remains_joinable_in_research(exported: Path) -> None:
    package = TrainingPackage(exported, access="research")
    observed = package.observed_ids()
    assert observed
    measured = package.observation_quality(observed[0])
    assert measured is not None
    assert measured["channels"]
    assert measured["provenance"]["estimator_version"] == ["obs_est.v1"]
    assert len(measured["channels"]) == len(measured["values"])
    assert np.all(np.isfinite(np.asarray(measured["values"], dtype=float)))


def test_research_quality_is_not_a_forward_feature(exported: Path) -> None:
    package = TrainingPackage(exported, access="research")
    fragment_ids = package.observed_ids()
    payloads = load_features(package, fragment_ids)
    for payload in payloads.values():
        assert payload["quality"].shape == (1, 1)
        assert not payload["quality_valid"].any()
        assert payload["quality_provenance"]["available"] is False


def test_unobserved_truth_member_is_not_synthesized_as_zero_features(exported: Path) -> None:
    package = TrainingPackage(exported, access="research")
    observed = set(package.observed_ids())
    unobserved = [str(row["fragment_id"]) for row in package.queries()
                  if row.get("fragment_id") and row["fragment_id"] not in observed]
    assert unobserved, "fixture must contain a truth-only/unobserved fragment"
    with pytest.raises(SynLabError) as caught:
        load_features(package, [unobserved[0]])
    assert caught.value.code == ErrorCode.INPUT_UNAVAILABLE
