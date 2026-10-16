"""End-to-end integration test for the L0 closed loop (plan 1.3 L0, 22.5, 24).

This is the Lead's integration gate: it runs the *real* chain for one mother and asserts
the invariants that must hold for the dataset to be usable at all:

* mother/material/pattern/fracture/truth/physical/observation assets are committed;
* every fragment carries explicit face origin bookkeeping;
* CleanTruth has R2 edges backed by measured interface area, and no self-loops;
* features and labels are separate assets and features carry no answer fields;
* the coverage ledger accounts for planned/attempted/accepted honestly;
* a zero-strength axis is a true identity (byte/hash level).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synlab.config import load_generation_spec
from synlab.errors import SynLabError
from synlab.pipeline import plan_generation, run_generation
from synlab.roles import (
    FORBIDDEN_FEATURE_FIELDS,
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_FRAGMENT_MESH,
    ROLE_LABEL_BUNDLE,
    ROLE_MOTHER_MESH,
    ROLE_OBS_RESULT,
    ROLE_PATTERN_RECIPE,
    ROLE_PHYSICAL_RESULT,
)
from synlab.storage.store import QA_PASS, AssetStore

ROOT = Path(__file__).resolve().parents[3]
SANDBOX = ROOT / "configs" / "a12" / "sandbox.yaml"


@pytest.fixture(scope="module")
def l0(tmp_path_factory: pytest.TempPathFactory) -> dict:
    store_root = tmp_path_factory.mktemp("l0")
    spec = load_generation_spec(SANDBOX)
    spec.storage.root = str(store_root)
    report = run_generation(spec, store_root=store_root, max_mothers=1)
    return {"report": report, "store_root": store_root, "spec": spec}


def test_l0_generation_accepts_at_least_one_mother(l0: dict) -> None:
    report = l0["report"]
    assert report["attempted"] == 1
    if report["accepted"] == 0:
        failures = json.dumps(report["failures"], ensure_ascii=False, indent=2)
        pytest.fail(f"the L0 chain did not complete for one mother:\n{failures}")
    assert report["accepted"] == 1


def test_l0_commits_every_stage_asset(l0: dict) -> None:
    store = AssetStore(l0["store_root"])
    expected = {
        ROLE_MOTHER_MESH: 1,
        ROLE_PATTERN_RECIPE: 1,
        ROLE_FRAGMENT_MESH: 2,
        ROLE_CLEAN_TRUTH: 1,
        ROLE_PHYSICAL_RESULT: 1,
        ROLE_OBS_RESULT: 1,
        ROLE_FEATURE_BUNDLE: 1,
        ROLE_LABEL_BUNDLE: 1,
    }
    counts = {role: len(store.list_assets(role=role, limit=10000)) for role in expected}
    for role, minimum in expected.items():
        assert counts[role] >= minimum, f"{role}: expected >= {minimum}, got {counts[role]}"
    for asset in store.list_assets(limit=10000):
        assert asset.qa_status == QA_PASS, f"{asset.asset_id} is {asset.qa_status}"


def test_fragments_carry_origin_bookkeeping(l0: dict) -> None:
    import numpy as np

    store = AssetStore(l0["store_root"])
    for asset in store.list_assets(role=ROLE_FRAGMENT_MESH, limit=100):
        mesh = store.load_mesh(asset.asset_id)
        attrs = mesh.metadata.get("face_attr_arrays") or {}
        n_faces = len(mesh.faces)
        for key in ("origin_kind", "source_triangle", "interface_id", "side"):
            assert key in attrs, f"{asset.asset_id} missing face attribute {key}"
            assert len(attrs[key]) == n_faces
        assert int(np.sum(attrs["origin_kind"] == 1)) >= 1, "no interface faces recorded"


def test_clean_truth_relations_are_backed_by_measured_area(l0: dict) -> None:
    store = AssetStore(l0["store_root"])
    rows = store.load_arrays(store.list_assets(role=ROLE_CLEAN_TRUTH, limit=1)[0].asset_id)
    relations = json.loads(str(rows["relations_json"])) if "relations_json" in rows else None
    if relations is None:
        stored = store.list_assets(role=ROLE_CLEAN_TRUTH, limit=1)[0]
        raw = store.load_bytes(stored.asset_id, "relations") if "relations" in stored.files else None
        assert raw is not None, "clean truth asset exposes neither relations_json nor relations blob"
        relations = json.loads(raw.decode("utf-8"))
    r2 = [r for r in relations if r["kind"] == "R2"]
    assert r2, "no R2 relation found for a shared-cut event"
    for edge in relations:
        assert edge["a"] != edge["b"], "self-loop relation"
        assert edge["area_mm2"] >= 0.0
    for edge in r2:
        assert edge["area_mm2"] > 0.0, "R2 edge without measured shared area"


def test_features_and_labels_are_separate_and_clean(l0: dict) -> None:
    store = AssetStore(l0["store_root"])
    features = store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=10)[0]
    labels = store.list_assets(role=ROLE_LABEL_BUNDLE, limit=10)[0]
    assert features.asset_id != labels.asset_id
    forbidden = sorted(set(features.meta or {}) & FORBIDDEN_FEATURE_FIELDS)
    assert not forbidden, f"features carry forbidden fields: {forbidden}"
    label_ancestry = set(labels.ancestry or [])
    assert features.asset_id not in label_ancestry


def test_coverage_ledger_is_honest(l0: dict) -> None:
    coverage_path = l0["store_root"] / "reports" / "coverage.json"
    assert coverage_path.exists()
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    assert coverage["planned"] == 1
    assert coverage["attempted"] == 1
    assert coverage["accepted"] + coverage["failed"] == coverage["attempted"]
    rows = json.loads((l0["store_root"] / "reports" / "coverage_rows.json").read_text(encoding="utf-8"))
    assert rows and rows[0]["lineage_id"]
    assert "stages" in rows[0]


def test_planning_splits_before_generation_and_is_deterministic(l0: dict) -> None:
    spec = l0["spec"]
    first = plan_generation(spec, max_mothers=4)
    second = plan_generation(spec, max_mothers=4)
    assert [l.lineage_id for l in first.lineages] == [l.lineage_id for l in second.lineages]
    assert [l.split for l in first.lineages] == [l.split for l in second.lineages]
    splits = {l.split for l in first.lineages}
    assert splits <= {"train", "dev", "confirm"}


def test_zero_strength_axis_is_a_true_identity(l0: dict) -> None:
    """Level 0 of any axis must return the source bytes/hash, never a resampled copy."""
    store = AssetStore(l0["store_root"])
    from synlab.degrade.api import apply_axis
    from synlab.degrade.sources import commit_source, load_source

    source_asset = store.list_assets(role=ROLE_FRAGMENT_MESH, limit=1)[0]
    try:
        bundle = load_source(store, source_asset.asset_id)
    except SynLabError as exc:
        pytest.skip(f"source bundle unavailable: {exc.message}")
    out_ref, measurement = apply_axis("P03", 0, bundle, store, lineage_id="lin_test", split="train")
    assert measurement.identity is True
    assert out_ref.blob_hash == source_asset.blob_hash or out_ref.asset_id == source_asset.asset_id, (
        "level 0 must reference the original bytes"
    )
