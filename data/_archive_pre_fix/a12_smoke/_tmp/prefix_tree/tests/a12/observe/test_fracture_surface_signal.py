"""The fracture surface's signal in the 2D chain: provenance resolution + rim pixels.

The defect this file guards against is measured in ``docs/a12/fracture_surface_signal.md``:
``rim`` (``surface_tag == 2``) had **0 pixels in 312 213 504** because the render target lost its
face provenance and ``resolve_target`` silently filled the tag map with zeros.  The tests here are
the two halves of the fix - the ladder that resolves the provenance, and the frames that must show
the fracture surface once it is resolved.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.cameras.api import camera_profiles  # noqa: E402
from synlab.errors import ErrorCode, SynLabError  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.observe.render import RenderSpec  # noqa: E402
from synlab.schemas.runtime import (  # noqa: E402
    ORIGIN_INTERFACE,
    ORIGIN_MOTHER_SURFACE,
    PhysicalComponent,
    PhysicalResult,
)
from synlab.seeds import make_rng  # noqa: E402
from synlab.storage.mesh_io import with_face_attrs  # noqa: E402

RIM = int(rt.ORIGIN_TO_TAG[ORIGIN_INTERFACE])


# ------------------------------------------------------------------ fixtures
def tagged_box(interface_faces: int = 4) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=[20.0, 20.0, 10.0])
    n = len(mesh.faces)
    origin = np.zeros(n, dtype=np.uint8)
    origin[:interface_faces] = ORIGIN_INTERFACE
    interface_id = np.full(n, -1, dtype=np.int32)
    interface_id[:interface_faces] = 0
    return with_face_attrs(mesh, origin_kind=origin, interface_id=interface_id)


def physical_result(mesh: trimesh.Trimesh) -> PhysicalResult:
    component = PhysicalComponent(
        component_id="F1#c0", clean_fragment_id="F1", mesh=mesh,
        volume_mm3=float(abs(mesh.volume)), is_representative=True, status="CORE",
        survivor_patch_ref=None, meta={})
    return PhysicalResult(
        mother_id="M", clean_ref="M:E1:v1", event_id="E1", recipe_id="P03:depth_mm:L1", version=1,
        components=[component], lost_volume_mm3=0.0, lost_volume_ratio=0.0,
        representative_map={"F1": "F1#c0"}, physical_truth=None, qa={"status": "PASS"},
        meta={"declared": {"roi": {"kind": "interface"}}, "level": 1, "axis_id": "P03"})


def small_spec(**overrides) -> rt.ObsSpec:
    base = dict(view_count=4, delivered_size=(96, 72), max_render_pixels=96 * 72,
                render_spec=RenderSpec(supersample=1), master_seed=7, lineage_id="iface_test")
    base.update(overrides)
    return rt.ObsSpec(**base)


# ------------------------------------------------------------------ the ladder
def test_a_physical_component_keeps_its_origin_kind_into_the_target() -> None:
    result = physical_result(tagged_box())
    target = rt.resolve_target(result, None)
    assert target.meta["surface_tag_source"] == "FACE_ORIGIN_KIND"
    assert int(np.count_nonzero(target.surface_tag == RIM)) == 4
    assert target.meta["surface_tag_face_histogram"][str(RIM)] == 4


def test_a_mapping_carrying_only_interface_id_still_tags_the_roi() -> None:
    mesh = tagged_box()
    attrs = dict((mesh.metadata or {}).get("face_attr_arrays") or {})
    attrs.pop("origin_kind", None)
    mesh.metadata["face_attr_arrays"] = attrs
    target = rt.resolve_target({"mesh": mesh, "fragment_id": "F1"}, None)
    assert target.meta["surface_tag_source"] == "FACE_INTERFACE_ID_ROI"
    assert int(np.count_nonzero(target.surface_tag == RIM)) == 4
    assert int(np.count_nonzero(target.surface_tag == 0)) == len(mesh.faces) - 4


def test_mother_face_tags_are_passed_through() -> None:
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])

    class Mother:
        mother_id = "V01-dispatch"
        vessel_id = "V01"
        material_id = "M01"
        params: dict = {}

        def __init__(self, mesh):
            self.mesh = mesh
            self.face_surface_tag = np.full(len(mesh.faces), 2, dtype=np.int32)

    target = rt.resolve_target(Mother(mesh), None)
    assert target.meta["surface_tag_source"] == "MOTHER_FACE_SURFACE_TAG"
    assert np.all(target.surface_tag == 2)


def test_a_mother_mesh_without_the_wrapper_uses_its_carried_tags() -> None:
    """``mvs_subset`` renders ``mother.mesh`` directly; the carried tags must be used."""
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    with_face_attrs(mesh, surface_tag=np.full(len(mesh.faces), 2, dtype=np.int32))
    target = rt.resolve_target(mesh, fragment_id="V01_surface")
    assert target.meta["surface_tag_source"] == "MOTHER_FACE_SURFACE_TAG"
    assert np.all(target.surface_tag == 2)


def test_a_target_without_provenance_is_refused_not_zeroed() -> None:
    box = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    with pytest.raises(SynLabError) as excinfo:
        rt.resolve_target(box, fragment_id="provenance_fixture")
    assert excinfo.value.code == ErrorCode.INPUT_UNAVAILABLE
    assert "OBS_TARGET_PROVENANCE_MISSING" in str(excinfo.value)


def test_an_unlabeled_target_is_rendered_only_when_asked_and_recorded() -> None:
    box = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    target = rt.resolve_target(box, fragment_id="unlabeled_fixture", allow_unlabeled=True)
    assert target.meta["surface_tag_source"] == "UNLABELED"
    assert np.all(target.surface_tag == 0)
    absence = target.meta["surface_tag_absence"]
    assert absence["code"] == "OBS_TARGET_PROVENANCE_MISSING"
    assert absence["faces"] == len(box.faces)
    assert "face_origin_kind" in absence["channels_looked_for"]


def test_a_channel_of_the_wrong_length_is_not_used_as_evidence() -> None:
    mesh = tagged_box()
    attrs = mesh.metadata["face_attr_arrays"]
    attrs["origin_kind"] = np.zeros(3, dtype=np.uint8)      # a channel for another mesh
    target = rt.resolve_target(mesh, fragment_id="short_channel")
    assert target.meta["face_origin_kind_length_mismatch"] == {"channel": 3,
                                                              "faces": len(mesh.faces)}
    assert target.face_origin_kind is None
    # the surviving channel still answers, and is named as the source
    assert target.meta["surface_tag_source"] == "FACE_INTERFACE_ID_ROI"
    # with no usable channel at all the target is refused instead of being zero-filled
    attrs.pop("interface_id")
    with pytest.raises(SynLabError):
        rt.resolve_target(mesh, fragment_id="no_channel")
    unlabeled = rt.resolve_target(mesh, fragment_id="no_channel", allow_unlabeled=True)
    assert unlabeled.meta["surface_tag_source"] == "UNLABELED"


# ------------------------------------------------------------------ the frames
def test_the_rendered_frames_carry_non_zero_rim_pixels() -> None:
    result = physical_result(tagged_box())
    target = rt.resolve_target(result, None)
    profile = camera_profiles()[1]
    spec = small_spec()
    bundles = rt.render_views(target, profile, spec, make_rng(3, "iface_test", "sensor"),
                              backend="software_rasterizer")
    assert bundles, "the renderer produced no views"
    total = 0
    for bundle in bundles:
        tag = np.asarray(bundle.render.surface_tag)
        total += int(np.count_nonzero(tag == RIM))
    assert total > 0, "the fracture surface produced no rim pixel in any view"


def test_the_observation_records_the_rim_pixels_it_delivered() -> None:
    result = physical_result(tagged_box())
    target = rt.resolve_target(result, None)
    profile = camera_profiles()[1]
    spec = small_spec()
    observation, _bundles = rt.route_proxy_scan(target, profile, spec,
                                                make_rng(5, "iface_test", "camera"),
                                                backend="software_rasterizer")
    block = observation.meta["surface_tag_pixels"]
    assert block["rim_tag"] == RIM
    assert block["rim_pixels"] > 0
    assert block["rim_fraction"] > 0.0
    assert block["tag_source"] == "FACE_ORIGIN_KIND"
    assert block["target_rim_faces"] == 4
    assert observation.meta["surface_tag_source"] == "FACE_ORIGIN_KIND"
    # every view is accounted for, so a view that lost the surface is visible in the record
    assert len(block["views"]) == len(observation.views)
    assert sum(entry["rim_pixels"] for entry in block["views"].values()) == block["rim_pixels"]
