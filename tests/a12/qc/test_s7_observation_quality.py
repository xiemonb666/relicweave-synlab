"""S7 contract: the observation-quality channels really reach the feature bundle.

Defect history (measured): ``synlab/qc/loader_probe.py::_observed_payload`` wrote
``"quality": np.zeros((1, 1))`` / ``"quality_valid": np.zeros((1, 1), bool)`` for every fragment,
so ``FeatureBundle.quality`` -- the tensor the model's quality head reads -- was all-zero whatever
the observation measured.  The measurements were never missing: the store's ``obs_result``
metadata carries them (14 ``OBS_EST`` channels per fragment on the small store used here).

These tests pin the contract on a **real** package exported by
``synlab.storage.export.export_training_package``, not on a hand-built payload: the point of the
fix is that the measurement survives the store -> package -> loader path.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from _fixtures import REPO_ROOT
from synlab.qc.loader_probe import load_features
from synlab.storage.export import OBSERVATION_QUALITY_KEY, TrainingPackage

#: a small package this repository can really export (3 observed fragments)
STORE = REPO_ROOT / "data" / "a12_exports" / "closed_loop" / "store"
RELEASE = "rel_852ab2a1e4c3_1790909619"


@pytest.fixture(scope="module")
def exported(tmp_path_factory) -> Path:
    """Export a small package with the current exporter (2 s, ~8 MB) and hand back its path."""
    if not (STORE / "releases" / RELEASE / "manifest.json").is_file():
        pytest.skip(f"store {STORE} carries no release {RELEASE}")
    from synlab.storage.export import export_training_package
    from synlab.storage.store import AssetStore

    out = tmp_path_factory.mktemp("s7") / "training_package"
    export_training_package(AssetStore(STORE), RELEASE, out,
                            formats=("parquet", "npz"), include_truth=True)
    return out


def test_package_carries_the_observation_quality_block(exported: Path) -> None:
    """The exporter writes the measured channels, with their provenance and units."""
    index = TrainingPackage(exported).observation_index()
    block = index.get(OBSERVATION_QUALITY_KEY)
    assert block is not None, "the exported obs index carries no observation-quality block"
    assert block["channels"], "the block declares no channel"
    assert block["estimator_version"] == ["obs_est.v1"]
    assert block["fragments_with_quality"] == index["rows"].__len__()
    assert block["fragments_without_quality"] == []
    # the block is a *research* sibling: the deployment rows keep their frozen shape
    for row in index["rows"].values():
        assert "quality" not in row
    for fragment_id, row in block["rows"].items():
        assert row["n_channels"] == len(row["values"]) == len(row["channels"])
        assert all(np.isfinite(np.asarray(row["values"], dtype=float)))


def test_loader_reads_real_quality_instead_of_zeros(exported: Path) -> None:
    """``features.quality`` is the measured vector -- not ``zeros((1, 1))``."""
    package = TrainingPackage(exported)
    fragment_ids = sorted(package.observation_index()["rows"])
    payloads = load_features(package, fragment_ids, token_budget=256)

    measured = package.observation_quality(fragment_ids[0])
    assert measured is not None
    for fragment_id in fragment_ids:
        payload = payloads[fragment_id]
        quality = np.asarray(payload["quality"])
        valid = np.asarray(payload["quality_valid"])
        assert quality.shape == (1, len(payload["quality_provenance"]["channels"]))
        assert quality.shape != (1, 1), "the loader is still writing the single zero slot"
        assert bool(valid.all())
        assert np.any(quality != 0.0), "every measured channel is zero"


def test_feature_bundle_quality_shape_and_masking(exported: Path) -> None:
    """The bundle keeps one region and one column per measured channel, all valid."""
    from synlab.training.adapter import FeatureBundle

    package = TrainingPackage(exported)
    fragment_ids = sorted(package.observation_index()["rows"])
    payloads = load_features(package, fragment_ids, token_budget=256)
    bundle = FeatureBundle.from_dict(payloads, token_budget=256).check_shapes()

    measured = package.observation_quality(fragment_ids[0])
    assert bundle.quality.shape == (len(fragment_ids), 1, len(measured["channels"]))
    assert int(bundle.quality_valid.sum()) == bundle.quality.size
    # the regression guard: the old loader produced exactly this
    assert bundle.quality.shape != (len(fragment_ids), 1, 1)


def test_unmeasured_fragment_is_masked_not_zero_filled(exported: Path) -> None:
    """A fragment with no measurement gets validity False, never a zero-valued label."""
    from synlab.qc.loader_probe import _quality_row

    values, valid, provenance = _quality_row(TrainingPackage(exported), "no_such_fragment")
    assert values.shape == (1, 1) and not bool(valid.any())
    assert provenance["available"] is False
    assert provenance["reason"]


def test_quality_fix_does_not_touch_the_label_side_target(exported: Path) -> None:
    """The D-task *target* still comes from the label table, not from this feature block.

    ``PackageLabelSource.quality_target_for`` reads ``research/labels/quality.parquet``; the S7
    fix only fills the *feature* tensor, so the two must stay independent.
    """
    from synlab.training.labels import PackageLabelSource

    package = TrainingPackage(exported)
    fragment_ids = sorted(package.observation_index()["rows"])
    source = PackageLabelSource.from_package(package)
    target, valid, report = source.quality_target_for(fragment_ids)
    assert target.shape == (len(fragment_ids), 1, 1)
    assert report["layer"] == "quality"
    assert report["missing_is_not_a_zero_label"] is True
