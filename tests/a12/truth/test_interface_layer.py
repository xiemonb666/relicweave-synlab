"""``iface_*`` in the physical and visible truth layers.

The clean layer always carried the fracture-surface geometry; the physical and visible layers used
to drop it (measured: 0 ``iface_*`` arrays in 43 ``physical_truth`` and 41 ``visible_labels``
assets, ``docs/a12/modality_census.md`` §6.3).  These tests pin the fields, their semantics and
their round trip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.roles import (  # noqa: E402
    ROLE_CLEAN_TRUTH,
    ROLE_PHYSICAL_TRUTH,
    ROLE_VISIBLE_LABELS,
)
from synlab.schemas.runtime import (  # noqa: E402
    ObsView,
    ObservationResult,
    PhysicalComponent,
    PhysicalResult,
    ViewFrame,
)
from synlab.storage.mesh_io import with_face_attrs  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402
from synlab.truth.api import (  # noqa: E402
    commit_truth,
    finalize_clean_truth,
    load_truth,
    measure_interface_faces,
    update_residual_truth,
    update_visibility_truth,
)

from truth_fixtures import CUT, event_with_correspondence, two_block_event  # noqa: E402


@pytest.fixture()
def store(tmp_path: Path) -> AssetStore:
    return AssetStore(tmp_path / "store")


def damaged_physical(clean, event, *, tagged: bool = True) -> PhysicalResult:
    """One component: the first block, with its interface faces marked in both channels."""
    fragment = event.fragments[0]
    mesh = fragment.mesh
    if tagged:
        origin = np.asarray(fragment.face_origin_kind, dtype=np.uint8)
        interface_id = np.full(origin.shape[0], -1, dtype=np.int32)
        interface_id[origin == CUT] = 0
        with_face_attrs(mesh, origin_kind=origin, interface_id=interface_id)
    component = PhysicalComponent(
        component_id=f"{fragment.fragment_id}#c0", clean_fragment_id=fragment.fragment_id,
        mesh=mesh, volume_mm3=float(abs(mesh.volume)), is_representative=True, status="CORE",
        survivor_patch_ref=None, meta={})
    return PhysicalResult(
        mother_id=clean.mother_id, clean_ref="fixture", event_id=clean.event_id,
        recipe_id="P03:depth_mm:L1", version=1, components=[component],
        lost_volume_mm3=0.0, lost_volume_ratio=0.0,
        representative_map={fragment.fragment_id: component.component_id}, physical_truth=None,
        qa={"status": "PASS"},
        meta={"ledger": {"source_volume_mm3": float(abs(mesh.volume)),
                         "damaged_volume_mm3": float(abs(mesh.volume)),
                         "lost_volume_mm3": 0.0, "conservation_ok": True,
                         "clean_fragment_id": fragment.fragment_id},
              "identity": False, "level": 1, "axis_id": "P03", "geometry_changed": True})


def synthetic_observation(clean, event, *, rim: bool = True) -> ObservationResult:
    """One pinhole frame whose depth/id/rim channels are filled at the correspondence points."""
    width = height = 128
    K = np.array([[200.0, 0.0, 64.0], [0.0, 200.0, 64.0], [0.0, 0.0, 1.0]])
    T_WC = np.eye(4)
    T_WC[0:3, 0] = [0.0, 1.0, 0.0]
    T_WC[0:3, 1] = [0.0, 0.0, -1.0]
    T_WC[0:3, 2] = [-1.0, 0.0, 0.0]
    T_WC[0:3, 3] = [60.0, 0.0, 0.0]
    frame = ViewFrame(view_id="v000", K=K, T_WC=T_WC, image_size=(width, height),
                      profile_id="TEST", tier="LOCAL", u_position_mm=0.0,
                      working_distance_mm=60.0, focus_setting="fixed", source_kind="SENSOR_SIM")
    depth = np.full((height, width), np.nan, dtype=np.float64)
    id_map = np.full((height, width), -1, dtype=np.int64)
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
    surface_tag = np.where(visible, 2 if rim else 0, 0).astype(np.int16)
    view = ObsView(
        view_id="v000", frame=frame, rgb=np.zeros((height, width, 3), dtype=np.uint8),
        rgb_linear=np.zeros((height, width, 3), dtype=np.float32), depth_z=depth, id_map=id_map,
        surface_tag=surface_tag, deployment_mask=visible, roi=None,
        uncertain_mask=np.zeros((height, width), dtype=bool), quality={}, source_kind="SENSOR_SIM")
    return ObservationResult(
        mother_id=clean.mother_id, fragment_id=event.fragments[0].fragment_id,
        component_id=f"comp_{event.fragments[0].fragment_id}", route="proxy_scan",
        input_profile="SENSOR_PROXY", observation_id="obs_fixture", views=[view],
        points=np.zeros((0, 3), dtype=np.float32), normals=np.zeros((0, 3), dtype=np.float32),
        point_valid=np.zeros(0, dtype=bool), normal_valid=np.zeros(0, dtype=bool),
        scale_valid=True, frame_id="W_mm", quality={})


# ------------------------------------------------------------------ the physical layer
def test_physical_truth_carries_the_interface_table() -> None:
    mother, event = event_with_correspondence()
    clean = finalize_clean_truth(mother, event)
    physical = damaged_physical(clean, event)
    truth = update_residual_truth(clean, physical)
    assert truth.meta["iface_ids"] == [0]
    assert truth.meta["iface_declared_area_mm2"]["0"] == pytest.approx(400.0)
    assert truth.meta["interface_table"]["iface_id"].tolist() == [0]
    assert truth.meta["iface_new_faces_by_id"]["0"] > 0
    assert truth.meta["iface_new_area_total_mm2"] > 0.0
    assert truth.meta["iface_faces_with_channel"] == len(physical.components[0].mesh.faces)
    assert truth.meta["iface_faces_without_channel"] == 0
    # the measured count is exactly the marked channel, not an estimate
    origin = physical.components[0].mesh.metadata["face_attr_arrays"]["origin_kind"]
    assert truth.meta["iface_new_faces_by_id"]["0"] == int(np.count_nonzero(origin == CUT))
    # the paired-mate samples of that interface are referenced by slice
    table = truth.meta["interface_table"]
    assert table["iface_corr_stop"][0] > table["iface_corr_start"][0]


def test_a_component_without_channels_is_reported_as_unmeasured() -> None:
    mother, event = event_with_correspondence()
    clean = finalize_clean_truth(mother, event)
    physical = damaged_physical(clean, event, tagged=False)
    truth = update_residual_truth(clean, physical)
    assert truth.meta["iface_faces_with_channel"] == 0
    assert truth.meta["iface_faces_without_channel"] > 0
    assert truth.meta["iface_components_without_channel"]
    # an absent channel yields a zero count *and* the reason, never a silent zero
    assert truth.meta["iface_new_faces_total"] == 0
    assert truth.meta["iface_origin_kind_faces"] == {}


def test_measure_interface_faces_reads_only_the_attached_channels() -> None:
    mother, event = two_block_event()
    clean = finalize_clean_truth(mother, event)
    physical = damaged_physical(clean, event)
    measured = measure_interface_faces(physical.components)
    assert measured["per_interface"][0]["faces"] > 0
    assert measured["faces_without_channel"] == 0
    assert measured["origin_kind_faces"].get("1", 0) > 0


def test_the_physical_interface_table_survives_the_store(store: AssetStore) -> None:
    mother, event = event_with_correspondence()
    clean = finalize_clean_truth(mother, event)
    physical = damaged_physical(clean, event)
    truth = update_residual_truth(clean, physical)
    record = commit_truth(store, truth, role=ROLE_PHYSICAL_TRUTH, lineage_id="lin", split="dev")
    arrays = store.load_arrays(record.asset_id)
    for key in ("iface_id", "iface_area_mm2", "iface_new_faces", "iface_new_area_mm2",
                "iface_corr_start", "iface_corr_stop"):
        assert key in arrays, key
    assert float(np.sum(arrays["iface_new_area_mm2"])) > 0.0
    loaded = load_truth(store, record.asset_id, role=ROLE_PHYSICAL_TRUTH)
    assert loaded.meta["interface_table"]["iface_id"].tolist() == [0]
    assert loaded.meta["iface_new_faces_by_id"]["0"] == truth.meta["iface_new_faces_by_id"]["0"]
    assert "corr_point_a" in arrays


# ------------------------------------------------------------------ the visible layer
def test_visible_labels_carry_the_interface_visibility() -> None:
    mother, event = event_with_correspondence()
    clean = finalize_clean_truth(mother, event)
    physical_truth = update_residual_truth(clean, damaged_physical(clean, event))
    visible = update_visibility_truth(physical_truth, synthetic_observation(clean, event))
    assert visible.meta["iface_ids"] == [0]
    assert visible.meta["iface_rim_pixels"] > 0
    assert visible.meta["iface_rim_visible"] is True
    assert visible.qa["iface_rim_pixels"] > 0
    assert visible.qa["iface_rim_visible"] is True
    assert visible.qa["iface_interface_count"] == 1
    assert visible.meta["iface_visible_samples_by_id"]["0"] >= 1
    table = visible.meta["interface_visible_table"]
    assert table["iface_corr_samples"][0] > 0
    assert table["iface_visible_samples"][0] >= 1
    assert set(visible.meta["iface_field_semantics"]) == {
        "iface_id", "iface_corr_samples", "iface_visible_samples", "iface_projected_samples",
        "iface_visible_projections"}


def test_visible_truth_reports_zero_rim_pixels_when_there_are_none() -> None:
    """The honest negative: the field exists and says 0, it does not disappear."""
    mother, event = event_with_correspondence()
    clean = finalize_clean_truth(mother, event)
    physical_truth = update_residual_truth(clean, damaged_physical(clean, event))
    visible = update_visibility_truth(physical_truth,
                                      synthetic_observation(clean, event, rim=False))
    assert visible.meta["iface_rim_pixels"] == 0
    assert visible.meta["iface_rim_visible"] is False
    assert visible.meta["iface_ids"] == [0]


def test_the_visible_interface_table_survives_the_store(store: AssetStore) -> None:
    mother, event = event_with_correspondence()
    clean = finalize_clean_truth(mother, event)
    clean_record = commit_truth(store, clean, role=ROLE_CLEAN_TRUTH, lineage_id="lin", split="dev")
    physical_truth = update_residual_truth(clean, damaged_physical(clean, event))
    physical_record = commit_truth(store, physical_truth, role=ROLE_PHYSICAL_TRUTH,
                                   lineage_id="lin", split="dev",
                                   ancestry=[clean_record.asset_id])
    visible = update_visibility_truth(physical_truth, synthetic_observation(clean, event))
    record = commit_truth(store, visible, role=ROLE_VISIBLE_LABELS, lineage_id="lin", split="dev",
                          ancestry=[physical_record.asset_id])
    arrays = store.load_arrays(record.asset_id)
    for key in ("iface_id", "iface_corr_samples", "iface_visible_samples",
                "iface_projected_samples"):
        assert key in arrays, key
    assert record.meta["iface_rim_pixels"] > 0
    assert record.meta["iface_rim_visible"] is True
    loaded = load_truth(store, record.asset_id, role=ROLE_VISIBLE_LABELS)
    assert loaded.meta["iface_rim_pixels"] == record.meta["iface_rim_pixels"]
    assert loaded.meta["interface_visible_table"]["iface_id"].tolist() == [0]
    assert loaded.meta["iface_visible_samples_by_id"]["0"] >= 1
