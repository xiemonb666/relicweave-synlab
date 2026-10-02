"""Generic asset access must separate mixed research payloads from deployable artifacts."""

from __future__ import annotations

import io
import json

import numpy as np
import pytest

from synlab.roles import ROLE_FEATURE_BUNDLE, SCHEMA_FEATURE
from synlab.api.integrity import record_integrity


def _commit(store, role: str, payload: dict, *, meta: dict | None = None,
            schema: str = "synlab.test.v1", ancestry: tuple[str, ...] = (),
            lineage_id: str | None = None, split: str | None = None) -> str:
    record = store.commit_asset(
        role=role, schema=schema, unit="1", frame="none", payload=payload,
        meta={"workspace": "default", **(meta or {})}, qa_status="QA_PASS",
        ancestry=ancestry, lineage_id=lineage_id, split=split,
    )
    record_integrity(store, record.asset_id, source="producer")
    return record.asset_id


def _feature_asset(store, *, extra_arrays: dict | None = None) -> str:
    arrays = {
        "point_cloud__xyz": np.array([[1.0, 2.0, 3.0]], dtype=np.float32),
        "point_cloud__valid": np.array([True]),
        "quality__names": np.array(["blur"], dtype="<U16"),
        "quality__values": np.array([0.25], dtype=np.float32),
        "quality__valid": np.array([True]),
        **(extra_arrays or {}),
    }
    record = store.commit_asset(
        role=ROLE_FEATURE_BUNDLE, schema=SCHEMA_FEATURE, unit="mm", frame="S_mm",
        payload=arrays,
        meta={"workspace": "default", "run_id": "run_private_probe",
              "feature_fields": ["schema", "run_id", "dropped_forbidden_fields", *arrays]},
        qa_status="QA_PASS", ancestry=["asset_0123456789abcdef"],
        lineage_id="lineage_private_probe", split="train_private_probe",
    )
    record_integrity(store, record.asset_id, source="producer")
    return record.asset_id


@pytest.mark.parametrize(
    ("role", "payload"),
    [
        ("obs_result", {"v000.id_map": np.array([[17]], dtype=np.int32),
                         "v000.surface_tag": np.array([[5]], dtype=np.int16),
                         "v000.T_WC": np.eye(4)}),
        ("obs_view", {"frames.research_mask": np.array([[True]]),
                       "frames.T_WC": np.eye(4)}),
        ("obs_fused_geometry", {"points": np.array([[0.0, 0.0, 0.0]]),
                                 "reference_points": np.array([[8.0, 8.0, 8.0]]),
                                 "depth_error_field": np.array([2.0])}),
    ],
)
def test_mixed_observation_roles_are_researcher_only_for_generic_assets(
    role, payload, store, researcher, operator, deployment,
):
    asset_id = _commit(store, role, payload, meta={"fragment_id": "private_fragment"})

    researcher_listing = researcher.get("/api/synlab/assets", params={"role": role})
    assert researcher_listing.status_code == 200
    assert asset_id in {row["asset_id"] for row in researcher_listing.json()["items"]}
    assert researcher.get(f"/api/synlab/assets/{asset_id}").status_code == 200
    assert researcher.get(f"/api/synlab/assets/{asset_id}/files/{role}",
                          params={"key": "arrays"}).status_code == 200

    for client in (operator, deployment):
        default_items = client.get("/api/synlab/assets").json()["items"]
        assert asset_id not in {row["asset_id"] for row in default_items}
        denied_list = client.get("/api/synlab/assets", params={"role": role})
        assert denied_list.status_code == 403
        assert denied_list.json()["error"]["code"] == "ROLE_FORBIDDEN"
        denied_meta = client.get(f"/api/synlab/assets/{asset_id}")
        assert denied_meta.status_code == 403
        assert denied_meta.json()["error"]["code"] == "ROLE_FORBIDDEN"
        denied_file = client.get(f"/api/synlab/assets/{asset_id}/files/{role}",
                                 params={"key": "arrays"})
        assert denied_file.status_code == 403
        assert denied_file.json()["error"]["code"] == "ROLE_FORBIDDEN"


def test_deployment_feature_metadata_is_projected_and_arrays_remain_available(
    store, deployment, operator,
):
    asset_id = _feature_asset(store)

    listing = deployment.get("/api/synlab/assets").json()
    item = next(row for row in listing["items"] if row["asset_id"] == asset_id)
    metadata = deployment.get(f"/api/synlab/assets/{asset_id}")
    assert metadata.status_code == 200
    asset = metadata.json()["asset"]
    serialized = json.dumps({"item": item, "asset": asset, "outer": metadata.json()})
    for private_value in ("run_private_probe", "lineage_private_probe", "train_private_probe",
                          "asset_0123456789abcdef"):
        assert private_value not in serialized
    assert asset["metadata_view"]["kind"] == "deployment_projection"
    assert asset["interpretation_hash_scope"].startswith("canonical stored record")
    assert "interpretation_hash" in asset
    assert set(asset["metadata_view"]["array_keys"]) == {
        "point_cloud__xyz", "point_cloud__valid", "quality__names", "quality__values",
        "quality__valid",
    }
    assert "ancestry" not in asset and "lineage_id" not in asset and "split" not in asset

    default_download = deployment.get(f"/api/synlab/assets/{asset_id}/files/feature_bundle")
    assert default_download.status_code == 200
    assert default_download.headers["X-SynLab-File-Key"] == "arrays"
    with np.load(io.BytesIO(default_download.content), allow_pickle=False) as arrays:
        assert set(arrays.files) == set(asset["metadata_view"]["array_keys"])
    assert deployment.get(f"/api/synlab/assets/{asset_id}/files/feature_bundle",
                         params={"key": "meta"}).status_code == 403

    # Operator behavior remains unchanged: it can inspect the operational feature metadata.
    operator_asset = operator.get(f"/api/synlab/assets/{asset_id}").json()["asset"]
    assert operator_asset["meta"]["run_id"] == "run_private_probe"
    assert operator_asset["lineage_id"] == "lineage_private_probe"


def test_deployment_rejects_feature_bundle_with_injected_answer_array(store, deployment):
    asset_id = _feature_asset(store, extra_arrays={"relation": np.array(["R2"], dtype="<U8")})

    for response in (
        deployment.get("/api/synlab/assets", params={"role": ROLE_FEATURE_BUNDLE}),
        deployment.get(f"/api/synlab/assets/{asset_id}"),
        deployment.get(f"/api/synlab/assets/{asset_id}/files/feature_bundle"),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ROLE_FORBIDDEN"


def test_deployment_generic_role_filter_fails_closed_but_keeps_display_lod(
    store, deployment,
):
    display_id = _commit(store, "display_lod_glb", {"glb": b"display-only-glb"},
                         schema="synlab.display_glb.v1")

    listing = deployment.get("/api/synlab/assets").json()
    assert display_id in {row["asset_id"] for row in listing["items"]}
    assert deployment.get("/api/synlab/assets", params={"role": "mother_mesh"}).status_code == 403
    assert deployment.get("/api/synlab/assets", params={"role": "obs_result"}).status_code == 403
    assert deployment.get(f"/api/synlab/assets/{display_id}").status_code == 200
    download = deployment.get(f"/api/synlab/assets/{display_id}/files/display_lod_glb")
    assert download.status_code == 200
    assert download.content == b"display-only-glb"
