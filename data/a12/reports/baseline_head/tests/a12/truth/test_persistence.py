"""Persistence and layer-separation tests (A01/A08 evidence).

The store is real (SQLite + blobs); the producers here are hand fixtures so the *encoding* the
L0 gate and ``synlab.relations.gallery`` read is checked independently of the fracture backend.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.roles import ROLE_CLEAN_TRUTH, ROLE_PHYSICAL_TRUTH, ROLE_VISIBLE_LABELS
from synlab.schemas.runtime import PhysicalComponent, PhysicalResult, RELATION_R2
from synlab.storage.store import QA_PASS, AssetStore
from synlab.truth.api import (
    build_labels,
    commit_truth,
    finalize_clean_truth,
    load_truth,
    update_residual_truth,
    update_visibility_truth,
)

from truth_fixtures import cavity_adjacency_event, event_with_correspondence, two_block_event


@pytest.fixture()
def store(tmp_path: Path) -> AssetStore:
    return AssetStore(tmp_path / "store")


def test_clean_truth_round_trip_keeps_relations_and_samples(store: AssetStore) -> None:
    mother, event = event_with_correspondence()
    clean = finalize_clean_truth(mother, event)
    record = commit_truth(store, clean, role=ROLE_CLEAN_TRUTH, lineage_id="lin_truth",
                          split="dev", ancestry=["mother_asset"])
    assert record.qa_status == QA_PASS
    assert record.meta["r2_count"] == 1
    assert record.meta["relation_count"] == 1

    # the documented L0-gate encoding: a JSON blob named ``relations``
    rows = json.loads(store.load_bytes(record.asset_id, "relations").decode("utf-8"))
    assert rows[0]["a"] == "A" and rows[0]["b"] == "B"
    assert rows[0]["kind"] == RELATION_R2
    assert rows[0]["area_mm2"] == pytest.approx(400.0)
    assert rows[0]["valid"] is True and rows[0]["loss_mask"] is True
    # ... and the mapping encoding the relations gallery reads
    assert record.meta["relations"] == rows

    arrays = store.load_arrays(record.asset_id)
    assert "corr_point_a" in arrays and "iface_area_mm2" in arrays

    loaded = load_truth(store, record.asset_id, role=ROLE_CLEAN_TRUTH)
    assert loaded.mother_id == clean.mother_id
    assert loaded.event_id == clean.event_id
    assert len(loaded.relations) == len(clean.relations)
    assert loaded.relations[("A", "B")].kind == RELATION_R2
    assert loaded.relations[("A", "B")].area_mm2 == pytest.approx(400.0)
    assert len(loaded.correspondence) == len(clean.correspondence)
    assert len(loaded.interfaces) == len(clean.interfaces)
    assert loaded.interfaces[0].area_mm2 == pytest.approx(400.0)
    assert np.allclose(loaded.interfaces[0].sample_points_a, clean.interfaces[0].sample_points_a)
    assert loaded.qa["pass"] is True


def test_physical_and_visible_layers_round_trip(store: AssetStore) -> None:
    mother, event = event_with_correspondence()
    clean = finalize_clean_truth(mother, event)
    clean_record = commit_truth(store, clean, role=ROLE_CLEAN_TRUTH, lineage_id="lin",
                                split="dev")
    physical = _identity_physical(clean, event)
    physical_truth = update_residual_truth(clean, physical)
    record = commit_truth(store, physical_truth, role=ROLE_PHYSICAL_TRUTH, lineage_id="lin",
                          split="dev", ancestry=[clean_record.asset_id])
    loaded = load_truth(store, record.asset_id, role=ROLE_PHYSICAL_TRUTH)
    assert loaded.qa["historical_r2_preserved"] is True
    assert loaded.association_counts["EXACT_SURVIVOR"] > 0
    assert record.meta["history"]["association_kind"] == "EXACT_SURVIVOR"
    assert loaded.current_fit_valid["A"] is True

    observation = _synthetic_observation(clean, event)
    visible = update_visibility_truth(loaded, observation)
    visible_record = commit_truth(store, visible, role=ROLE_VISIBLE_LABELS, lineage_id="lin",
                                  split="dev", ancestry=[record.asset_id])
    reloaded = load_truth(store, visible_record.asset_id, role=ROLE_VISIBLE_LABELS)
    assert reloaded.qa["views"] == len(observation.views)
    assert set(reloaded.per_view) == set(visible.per_view)
    assert reloaded.qa["samples_visible"] >= 1
    assert np.asarray(reloaded.meta["correspondence_visible_counts"]).shape[0] == \
        reloaded.qa["correspondence_samples"]


def test_role_mismatch_is_refused(store: AssetStore) -> None:
    from synlab.errors import SynLabError

    mother, event = two_block_event()
    clean = finalize_clean_truth(mother, event)
    with pytest.raises(SynLabError):
        commit_truth(store, clean, role=ROLE_VISIBLE_LABELS, lineage_id="lin", split="dev")


def test_labels_stay_out_of_features(store: AssetStore) -> None:
    from synlab.errors import SynLabError

    mother, event = event_with_correspondence()
    clean = finalize_clean_truth(mother, event)
    features = {"descriptor": np.zeros((4, 8), dtype=np.float32), "token_count": 4}
    bundle = build_labels(clean, features=features, split="dev")
    assert bundle["features"] is features
    assert bundle["separation"]["features_untouched"] is True
    assert bundle["labels"]["r2_count"] == 1
    assert "relations" in bundle["labels"]
    # a feature payload that carries an answer field must be refused, not silently accepted
    with pytest.raises(SynLabError):
        build_labels(clean, features={**features, "relation_kind": np.zeros(4, dtype=np.int8)})
    with pytest.raises(SynLabError):
        build_labels(clean, features={**features, "r2_count": 1})


def test_cavity_relation_survives_the_round_trip(store: AssetStore) -> None:
    mother, event = cavity_adjacency_event()
    clean = finalize_clean_truth(mother, event)
    record = commit_truth(store, clean, role=ROLE_CLEAN_TRUTH, lineage_id="lin", split="dev")
    rows = json.loads(store.load_bytes(record.asset_id, "relations").decode("utf-8"))
    assert rows[0]["kind"] == "UNKNOWN"
    assert rows[0]["loss_mask"] is False
    assert record.meta["r2_count"] == 0


# ------------------------------------------------------------------- stubs
def _identity_physical(clean, event) -> PhysicalResult:
    """The level-0 case: every clean fragment survives unchanged, one component each."""
    components = []
    for fragment in event.fragments:
        mesh = fragment.mesh
        components.append(PhysicalComponent(
            component_id=f"comp_{fragment.fragment_id}", clean_fragment_id=fragment.fragment_id,
            mesh=mesh, volume_mm3=float(abs(mesh.volume)), is_representative=True, status="CORE",
            survivor_patch_ref=None, meta={"identity": True},
        ))
    total = float(sum(c.volume_mm3 for c in components))
    target = event.fragments[0]
    # the damage ledger describes the *target* fragment (that is what ``apply_damage`` writes)
    ledger = {
        "source_volume_mm3": float(abs(target.mesh.volume)),
        "damaged_volume_mm3": float(abs(target.mesh.volume)),
        "lost_volume_mm3": 0.0,
        "conservation_ok": True,
        "clean_fragment_id": target.fragment_id,
    }
    del total
    return PhysicalResult(
        mother_id=clean.mother_id, clean_ref="fixture", event_id=clean.event_id,
        recipe_id="P03:L0", version=1, components=components, lost_volume_mm3=0.0,
        lost_volume_ratio=0.0, representative_map={c.clean_fragment_id: c.component_id
                                                   for c in components},
        physical_truth=None,
        qa={"status": "PASS", "identity": True},
        meta={"ledger": ledger, "identity": True, "level": 0, "axis_id": "P03",
              "variant": "DEFAULT", "geometry_changed": False},
    )


def _synthetic_observation(clean, event) -> object:
    """A pinhole view whose depth/id channels are filled exactly at the correspondence points."""
    from synlab.schemas.runtime import ObsView, ObservationResult, ViewFrame

    width = height = 128
    K = np.array([[200.0, 0.0, 64.0], [0.0, 200.0, 64.0], [0.0, 0.0, 1.0]])
    # camera at x = 60 looking towards -x at the shared plane x = 0 (OpenCV: +z forward, +y down)
    T_WC = np.eye(4)
    T_WC[0:3, 0] = np.array([0.0, 1.0, 0.0])    # right
    T_WC[0:3, 1] = np.array([0.0, 0.0, -1.0])   # down
    T_WC[0:3, 2] = np.array([-1.0, 0.0, 0.0])   # forward
    T_WC[0:3, 3] = np.array([60.0, 0.0, 0.0])
    frame = ViewFrame(view_id="v000", K=K, T_WC=T_WC, image_size=(width, height),
                      profile_id="TEST", tier="LOCAL", u_position_mm=0.0,
                      working_distance_mm=60.0, focus_setting="fixed",
                      source_kind="SENSOR_SIM")
    depth = np.full((height, width), np.nan, dtype=np.float64)
    id_map = np.full((height, width), -1, dtype=np.int64)
    uncertain = np.zeros((height, width), dtype=bool)
    visible = np.zeros((height, width), dtype=bool)
    T_CW = np.linalg.inv(T_WC)
    for row in event.meta["correspondence"]:
        point = np.asarray(row["point_a_mm"], dtype=np.float64)
        camera = T_CW @ np.append(point, 1.0)
        u = K[0, 0] * camera[0] / camera[2] + K[0, 2]
        v = K[1, 1] * camera[1] / camera[2] + K[1, 2]
        ui, vi = int(round(u)), int(round(v))
        if 0 <= ui < width and 0 <= vi < height and camera[2] > 0:
            depth[vi, ui] = camera[2]
            id_map[vi, ui] = 0
            visible[vi, ui] = True
    view = ObsView(
        view_id="v000", frame=frame, rgb=np.zeros((height, width, 3), dtype=np.uint8),
        rgb_linear=np.zeros((height, width, 3), dtype=np.float32), depth_z=depth,
        id_map=id_map, surface_tag=np.where(visible, 2, 0).astype(np.int16),
        deployment_mask=visible, roi=None, uncertain_mask=uncertain,
        quality={"observed_fraction": float(np.mean(visible))}, source_kind="SENSOR_SIM",
    )
    return ObservationResult(
        mother_id=clean.mother_id, fragment_id=event.fragments[0].fragment_id,
        component_id=f"comp_{event.fragments[0].fragment_id}", route="proxy_scan",
        input_profile="SENSOR_PROXY", observation_id="obs_fixture", views=[view],
        points=np.zeros((0, 3), dtype=np.float32), normals=np.zeros((0, 3), dtype=np.float32),
        point_valid=np.zeros(0, dtype=bool), normal_valid=np.zeros(0, dtype=bool),
        scale_valid=True, frame_id="W_mm", quality={},
    )
