from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from synlab.qc import leakage
from synlab.roles import (
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_LABEL_BUNDLE,
    ROLE_OBS_FUSED,
    ROLE_OBS_RESULT,
    ROLE_OBS_VIEW,
    ROLE_PHYSICAL_TRUTH,
    ROLE_PROVENANCE,
    ROLE_VISIBLE_LABELS,
)
from synlab.storage.store import QA_PASS, AssetStore


def _commit(store: AssetStore, role: str, *, payload: dict[str, Any] | None = None,
            meta: dict[str, Any] | None = None, ancestry: tuple[str, ...] = ()) -> str:
    return store.commit_asset(
        role=role,
        schema=f"test.{role}.v1",
        unit="1",
        frame="none",
        payload=payload or {},
        meta=meta or {},
        qa_status=QA_PASS,
        ancestry=ancestry,
    ).asset_id


def _feature(store: AssetStore, *, ancestry: tuple[str, ...] = (),
             run_id: str = "run-a", meta: dict[str, Any] | None = None,
             arrays: dict[str, np.ndarray] | None = None) -> str:
    feature_meta = {"run_id": run_id, **(meta or {})}
    feature_arrays = arrays or {
        "point_cloud__xyz": np.arange(9, dtype=np.float32).reshape(3, 3),
    }
    return _commit(store, ROLE_FEATURE_BUNDLE, payload=feature_arrays, meta=feature_meta,
                   ancestry=ancestry)


@pytest.mark.parametrize("truth_role", [
    ROLE_CLEAN_TRUTH,
    ROLE_PHYSICAL_TRUTH,
    ROLE_VISIBLE_LABELS,
    ROLE_LABEL_BUNDLE,
])
def test_truth_roles_are_rejected_as_direct_feature_dependencies(tmp_path, truth_role):
    store = AssetStore(tmp_path / "store")
    truth_id = _commit(store, truth_role)
    _feature(store, ancestry=(truth_id,))

    report = leakage.run_negative_control(store)

    assert report["status"] == "FAIL"
    assert report["checks"]["truth_isolation"] is False
    assert any(truth_role in path for path in report["checks"]["truth_dependency_paths"])


def test_truth_dependency_through_generic_wrapper_is_rejected(tmp_path):
    store = AssetStore(tmp_path / "store")
    truth_id = _commit(store, ROLE_CLEAN_TRUTH)
    wrapper_id = _commit(store, ROLE_PROVENANCE, ancestry=(truth_id,))
    _feature(store, ancestry=(wrapper_id,))

    report = leakage.run_negative_control(store)

    assert report["status"] == "FAIL"
    assert report["checks"]["truth_isolation"] is False
    assert any("provenance:" in path and "clean_truth:" in path
               for path in report["checks"]["truth_dependency_paths"])


@pytest.mark.parametrize("observation_role", [ROLE_OBS_RESULT, ROLE_OBS_VIEW, ROLE_OBS_FUSED])
def test_truth_ancestry_stops_at_legal_observation_boundary(tmp_path, observation_role):
    store = AssetStore(tmp_path / "store")
    truth_id = _commit(store, ROLE_CLEAN_TRUTH)
    physical_id = _commit(store, "physical_component", ancestry=(truth_id,))
    observation_id = _commit(store, observation_role, ancestry=(physical_id,))
    _feature(
        store,
        ancestry=(observation_id,),
        meta={"observation_id": "obs-a", "fragment_id": "frag-a", "mother_id": "mother-a"},
    )

    report = leakage.run_negative_control(store)

    assert report["status"] == "PASS"
    assert report["checks"]["truth_isolation"] is True
    assert report["checks"]["feature_field_leakage"] is True


@pytest.mark.parametrize("feature_meta,arrays", [
    ({}, {"relation__kind": np.array([1], dtype=np.int8)}),
    ({"feature_fields": ["gt_normal_p95"]}, None),
    ({"nested": {"research": {"mother_id": "mother-answer"}}}, None),
])
def test_actual_arrays_declared_and_nested_metadata_fields_are_checked(
        tmp_path, feature_meta, arrays):
    store = AssetStore(tmp_path / "store")
    _feature(store, meta=feature_meta, arrays=arrays)

    report = leakage.run_negative_control(store)

    assert report["status"] == "FAIL"
    assert report["checks"]["feature_field_leakage"] is False
    assert report["checks"]["feature_field_violations"]


def test_unmatched_run_id_fails_closed_with_zero_selected_denominator(tmp_path):
    store = AssetStore(tmp_path / "store")
    _feature(store, run_id="run-present")

    report = leakage.run_negative_control(store, run_id="run-absent")

    assert report["status"] == "FAIL"
    assert report["checks"]["feature_scope"] == {
        "requested_run_id": "run-absent",
        "available_in_store": 1,
        "selected_and_checked": 0,
        "selection": "exact run_id match",
    }


def test_unresolved_ancestry_is_not_reported_as_isolated(tmp_path):
    store = AssetStore(tmp_path / "store")
    _feature(store, ancestry=("asset_missing",))

    report = leakage.run_negative_control(store)

    assert report["status"] == "FAIL"
    assert report["checks"]["truth_isolation"] is False
    assert report["checks"]["unresolved_ancestry_count"] == 1


def test_feature_asset_iteration_is_not_truncated_at_ten_thousand():
    assets = [SimpleNamespace(asset_id=f"asset-{i}", role=ROLE_FEATURE_BUNDLE,
                              meta={"run_id": "large-run"}) for i in range(10_007)]

    class PagedStore:
        def list_assets(self, *, role: str, limit: int, offset: int):
            assert role == ROLE_FEATURE_BUNDLE
            return assets[offset:offset + limit]

    selected = leakage._feature_assets(PagedStore(), "large-run")  # type: ignore[arg-type]

    assert len(selected) == 10_007
    assert selected[-1].asset_id == "asset-10006"
