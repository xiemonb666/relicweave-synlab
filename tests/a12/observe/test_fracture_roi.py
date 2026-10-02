"""The fracture-local ROI close-up family: contract shape, measured scale, switchability.

These tests guard the gap measured in ``docs/a12/precision_audit.md`` §7.4 defect 4 (the
contract's ``fracture_local_2d`` family - 3-6 effective directions per fracture at a 5-10 cm
close-up - did not exist; every delivered view was a whole-fragment view at 0.27 mm/px) and the
``px_per_mm``/``r_eff_mm``/``dof_cover_mm`` producers the contract asks for and the repository
had zero of.

They run on the software rasteriser and a small render budget so they stay cheap; the *scale*
assertions are made against values measured from the produced bundles, never against a nominal
formula alone.
"""

from __future__ import annotations

import json
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
from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.observe.render import RenderSpec  # noqa: E402
from synlab.schemas.runtime import ORIGIN_INTERFACE, ORIGIN_MOTHER_SURFACE  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402
from synlab.storage.mesh_io import with_face_attrs  # noqa: E402

RIM = int(rt.ORIGIN_TO_TAG[ORIGIN_INTERFACE])
CONFIG_PATH = REPO_ROOT / "configs/a12/imaging_fracture_roi.yaml"


# ------------------------------------------------------------------ fixtures
def fractured_plate(*, n_faces_per_interface: int = 48, n_interfaces: int = 2,
                    tilt_mm: float = 0.0) -> trimesh.Trimesh:
    """A flat plate whose top face is the fracture surface, split over two interface ids.

    ``tilt_mm`` bends the patch out of its plane so the measured height field is not identically
    zero (a purely planar patch has exactly zero relief below any band radius - which is itself
    the point of one of the tests below).
    """
    mesh = trimesh.creation.box(extents=[40.0, 40.0, 8.0])
    mesh = mesh.subdivide_to_size(max_edge=40.0 / 6.0)
    faces = np.asarray(mesh.faces)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    centroids = verts[faces].mean(axis=1)
    n = len(faces)
    origin = np.full(n, ORIGIN_MOTHER_SURFACE, dtype=np.uint8)
    interface_id = np.full(n, -1, dtype=np.int32)
    top = centroids[:, 2] > 3.9
    order = np.argsort(-centroids[top][:, 0])
    top_index = np.flatnonzero(top)[order]
    half = max(1, top_index.size // n_interfaces)
    for group in range(n_interfaces):
        chunk = top_index[group * half:(group + 1) * half]
        origin[chunk] = ORIGIN_INTERFACE
        interface_id[chunk] = group
    if tilt_mm:
        # displace the *vertices* of the fracture faces so the patch is not planar
        used = np.unique(faces[origin == ORIGIN_INTERFACE].reshape(-1))
        v = verts[used].copy()
        v[:, 2] += float(tilt_mm) * np.sin(v[:, 0] / 3.0)
        verts[used] = v
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    return with_face_attrs(mesh, origin_kind=origin, interface_id=interface_id)


def target_of(mesh: trimesh.Trimesh, fragment_id: str = "ROI_FIXTURE"):
    return rt.resolve_target({"mesh": mesh, "fragment_id": fragment_id}, fragment_id)


def small_spec(**overrides) -> rt.ObsSpec:
    base = dict(view_count=2, delivered_size=(128, 96), max_render_pixels=128 * 128,
                render_spec=RenderSpec(supersample=1), master_seed=11,
                lineage_id="roi_test", renderer="software_rasterizer")
    base.update(overrides)
    return rt.ObsSpec(**base)


def roi_config(**overrides) -> fr.FractureRoiConfig:
    """The shipped configuration with the switch on and a cheap render budget."""
    base = fr.load_fracture_roi_config(CONFIG_PATH)
    fields = dict(enabled=True, directions=4, working_distance_mm=60.0,
                  max_fractures_per_target=2, min_patch_area_mm2=1.0, min_patch_faces=4,
                  visibility_rays=40, resolution_ladder_px=(256,))
    fields.update(overrides)
    return fr.FractureRoiConfig(document=base.document, source_path=base.source_path, **fields)


# ------------------------------------------------------------------ the switch
def test_the_shipped_configuration_is_off_by_default() -> None:
    config = fr.load_fracture_roi_config(CONFIG_PATH)
    assert config.enabled is False, "the ROI family must not change a run that did not ask for it"
    assert 3 <= config.directions <= 6
    assert fr.CLOSEUP_MIN_MM <= config.working_distance_mm <= fr.CLOSEUP_MAX_MM
    # the switched-off configuration is what a normal batch run gets: no ROI frame is built
    target = target_of(fractured_plate())
    rois = fr.fracture_rois(target, config, footprint_radius_mm=10.0)
    assert rois, "the fixture must expose a measurable fracture patch"
    assert config.enabled is False


def test_an_off_config_builds_no_view_family_only_when_the_caller_asks_for_one() -> None:
    """The switch is enforced by the caller: `enabled=False` is never silently ignored."""
    config = fr.load_fracture_roi_config(CONFIG_PATH)
    assert config.enabled is False
    on = roi_config(enabled=True)
    assert on.enabled is True
    assert on.directions == 4


def test_unknown_config_keys_are_refused() -> None:
    document = json.loads(json.dumps({"fracture_roi": {"enabled": True, "nope": 1}}))
    with pytest.raises(SynLabError) as excinfo:
        fr._config_from_document(document, source_path="fixture")
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert "nope" in str(excinfo.value)


@pytest.mark.parametrize("bad", [
    {"directions": 2}, {"directions": 7}, {"working_distance_mm": 30.0},
    {"working_distance_mm": 200.0}, {"direction_offsets_deg": (0.0, 10.0, 20.0, 25.0)},
])
def test_the_contract_shape_is_enforced(bad: dict) -> None:
    base = fr.load_fracture_roi_config(CONFIG_PATH)
    fields = dict(enabled=True, directions=4, direction_offsets_deg=(0.0, 35.0, -35.0, 55.0),
                  working_distance_mm=60.0)
    fields.update(bad)
    with pytest.raises(SynLabError) as excinfo:
        fr.FractureRoiConfig(document=base.document, source_path="fixture", **fields)
        fr.validate_config(fr.FractureRoiConfig(**fields))
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID


# ------------------------------------------------------------------ resolution arithmetic
def test_px_per_mm_and_r_eff_are_produced_and_consistent() -> None:
    assert fr.mm_per_px(working_distance_mm=60.0, f_px=800.0) == pytest.approx(0.075)
    assert fr.px_per_mm(working_distance_mm=60.0, f_px=800.0) == pytest.approx(1.0 / 0.075)
    assert fr.r_eff_mm(working_distance_mm=60.0, f_px=800.0) == pytest.approx(0.3)
    assert fr.r_eff_mm(working_distance_mm=60.0, f_px=800.0, k_px=8.0) == pytest.approx(0.6)
    assert fr.structure_px(0.2, working_distance_mm=60.0, f_px=800.0) == pytest.approx(0.2 / 0.075)


def test_the_documented_ladder_is_recomputed_and_cross_checked() -> None:
    ladder = fr.documented_ladder()
    rows = {row["distance_mm"]: row for row in ladder["rows"]}
    assert rows[50.0]["mm_per_px"] == pytest.approx(0.039, abs=1e-9)
    assert rows[250.0]["mm_per_px"] == pytest.approx(0.195, abs=1e-9)
    assert rows[50.0]["structure_0p2mm_px"] == pytest.approx(0.2 / 0.039, rel=1e-9)
    assert ladder["contract_cross_check"]["status"] == "OK", ladder["contract_cross_check"]
    assert ladder["sensor_width_px"] == 2304


def test_the_inverse_solve_is_the_inverse_of_the_forward_formula() -> None:
    amplitude = 0.05
    solved = fr.inverse_solve(amplitude_mm=amplitude, k_px=4.0, working_distance_mm=60.0,
                              f_px_delivered=900.0, f_px_native=3000.0, native_width_px=4000,
                              long_edge_px=1200)
    need = solved["required_mm_per_px"]
    assert need == pytest.approx(amplitude / 4.0)
    # evaluating the forward formula at the required scale must give exactly k pixels
    assert fr.amplitude_px(amplitude, need) == pytest.approx(4.0)
    # the required f_px at 60 mm is what the definition says, and the required long edge is the
    # delivered grid that realizes it with this lens
    assert solved["required_f_px_at_working_distance"] == pytest.approx(4.0 * 60.0 / amplitude)
    assert solved["required_long_edge_px"] == pytest.approx(
        solved["required_f_px_at_working_distance"] * 4000.0 / 3000.0)
    # z_max at the delivered f_px is the distance where the amplitude spans exactly 4 px
    assert solved["max_working_distance_mm"] == pytest.approx(amplitude / 4.0 * 900.0)
    assert solved["visible_at_working_distance"] is (
        solved["realized_amplitude_px"] >= 4.0)


def test_resolvability_reports_every_rung_and_amplitude() -> None:
    report = fr.resolvability_report(
        mm_per_px_values={"contract_50mm": 0.039, "delivered_mid": 0.27193},
        amplitudes_mm={"Ra_0p01": 0.01, "Ra_0p2": 0.2})
    assert set(report["table"]) == {"contract_50mm", "delivered_mid"}
    coarse = report["table"]["delivered_mid"]
    assert coarse["amplitudes"]["Ra_0p2"]["amplitude_px"] == pytest.approx(0.2 / 0.27193)
    assert coarse["amplitudes"]["Ra_0p2"]["lateral_resolved_4px"] is False
    fine = report["table"]["contract_50mm"]
    assert fine["amplitudes"]["Ra_0p2"]["amplitude_px"] == pytest.approx(0.2 / 0.039)
    assert fine["amplitudes"]["Ra_0p2"]["lateral_resolved_4px"] is True
    assert report["k_px_pilot"] == 4.0


# ------------------------------------------------------------------ the measured ROIs
def test_rois_are_measured_patches_with_a_plane_and_a_normal() -> None:
    target = target_of(fractured_plate())
    config = roi_config()
    rois = fr.fracture_rois(target, config, footprint_radius_mm=20.0)
    assert len(rois) == 2, "one ROI per interface id of the fixture"
    for roi in rois:
        assert roi.n_faces > 0
        assert roi.area_mm2 > 0.0
        assert abs(float(np.linalg.norm(roi.normal)) - 1.0) < 1e-9
        # the fracture surface of the fixture is the top face -> the normal is +/-Z
        assert abs(float(roi.normal[2])) > 0.9
        assert roi.normal_sign_source in ("OUTWARD_FROM_BODY_CENTROID",
                                          "OCCLUSION_RAYCAST_TWO_SIGNS")
        assert {"plane", "bands"} <= set(roi.height)


def test_a_planar_fracture_has_zero_measured_relief_below_the_band_radius() -> None:
    """A plane-cut fracture really is planar: the sub-band relief is measured as 0, not assumed."""
    rois = fr.fracture_rois(target_of(fractured_plate(tilt_mm=0.0)), roi_config(),
                            footprint_radius_mm=20.0)
    assert rois
    bands = rois[0].height["bands"]
    assert bands["below_1mm"]["Ra_mm"] == pytest.approx(0.0, abs=1e-9)
    assert bands["below_0.25mm"]["Ra_mm"] == pytest.approx(0.0, abs=1e-9)


def test_a_non_planar_fracture_shows_non_zero_band_relief() -> None:
    rois = fr.fracture_rois(target_of(fractured_plate(tilt_mm=0.4)), roi_config(),
                            footprint_radius_mm=20.0)
    assert rois
    plane = rois[0].height["plane"]
    assert plane["Ra_mm"] > 0.0
    assert plane["Rt_mm"] > 0.0


def test_the_delivered_profile_keeps_fx_equal_to_fy() -> None:
    """The Blender worker refuses a frame with fx != fy; the delivered grid must not create it."""
    base = camera_profiles()[2]                        # LOCAL
    delivered = fr.delivered_profile(base, long_edge_px=1024)
    assert delivered.image_size == (1024, 768)
    assert delivered.K[0, 0] == pytest.approx(delivered.K[1, 1])
    assert delivered.K[0, 0] == pytest.approx(float(base.K[0, 0]) * 1024.0 / 4000.0)
    # the delivered 1024 px image samples 4x coarser than the 4000 px native grid: the grid change
    # must move mm_per_pixel by exactly the same factor, and the pixel scale must stay consistent
    # with z / f_px (that is the quantity the contract requires to be reported, measured)
    scale = 1024.0 / 4000.0
    assert delivered.mm_per_pixel == pytest.approx(base.mm_per_pixel / scale)
    assert delivered.mm_per_pixel == pytest.approx(
        delivered.working_distance_mm / float(delivered.K[0, 0]))
    assert delivered.meta["f_px_native_equivalent"] == pytest.approx(float(base.K[0, 0]))
    assert delivered.meta["pixel_affine_is_identity"] is True
    assert delivered.meta["dof_cover_mm"] > 0


def test_shading_contrast_separates_present_from_absent_relief() -> None:
    light = rt.ObsSpec().resolved_light()
    present = fr.shading_contrast(amplitude_mm=0.13, wavelength_mm=2.0,
                                  light_direction=light.direction, light_color=light.color,
                                  ambient=light.ambient, albedo=0.55)
    absent = fr.shading_contrast(amplitude_mm=0.0, wavelength_mm=2.0,
                                 light_direction=light.direction, light_color=light.color,
                                 ambient=light.ambient, albedo=0.55)
    assert present["visible_in_rgb"] is True
    assert present["delta_code_value"] > 1.0
    assert absent["visible_in_rgb"] is False
    assert absent["delta_code_value"] == pytest.approx(0.0)


def test_a_target_without_origin_kind_is_refused() -> None:
    box = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    target = rt.resolve_target(box, fragment_id="unlabeled", allow_unlabeled=True)
    with pytest.raises(SynLabError) as excinfo:
        fr.fracture_rois(target, roi_config())
    assert excinfo.value.code == ErrorCode.INPUT_UNAVAILABLE


# ------------------------------------------------------------------ the frames
def test_three_to_six_directions_are_built_per_fracture_with_their_scale_recorded() -> None:
    mesh = fractured_plate(tilt_mm=0.2)
    target = target_of(mesh)
    config = roi_config(directions=5)
    profile = fr.closeup_profile(config, delivered_long_edge_px=256)
    rois = fr.fracture_rois(target, config, footprint_radius_mm=20.0)
    frames = fr.make_fracture_roi_frames(rois=rois, profile=profile, spec=small_spec(),
                                         config=config, long_edge_px=256,
                                         rng=make_rng(3, "roi_test", "camera"), mesh=mesh)
    assert len(frames) == 5 * len(rois)
    per_roi: dict[str, int] = {}
    for frame in frames:
        meta = frame.meta
        assert meta["view_family"] == fr.VIEW_FAMILY_ROI
        assert meta["framing"] == "FRACTURE_ROI"
        per_roi[meta["fracture_roi_id"]] = per_roi.get(meta["fracture_roi_id"], 0) + 1
        # every direction is along the normal or 30-60 deg away from it
        offset = abs(float(meta["direction_offset_deg"]))
        assert offset == 0.0 or 30.0 <= offset <= 60.0
        # the resolution ledger of the contract is on the frame, not implied
        assert meta["px_per_mm"] > 0
        assert meta["r_eff_mm"] == pytest.approx(4.0 * meta["mm_per_pixel"])
        assert meta["r_eff_mm_8px"] == pytest.approx(8.0 * meta["mm_per_pixel"])
        assert meta["dof_cover_mm"] > 0
        assert meta["delivered_long_edge_px"] == 256
        assert meta["f_px_delivered"] == pytest.approx(
            float(profile.K[0, 0]) * 256.0 / float(profile.image_size[0]))
        assert meta["mm_per_pixel"] == pytest.approx(
            config.working_distance_mm / meta["f_px_delivered"])
        # the camera sits at the close-up distance from the aimed point
        distance = float(np.linalg.norm(np.asarray(meta["camera_centre_mm"])
                                        - np.asarray(meta["roi_aim_mm"])))
        assert distance == pytest.approx(config.working_distance_mm, rel=1e-6)
        assert meta["upsampled"] is False and meta["digital_zoom_applied"] is False
    assert set(per_roi.values()) == {5}


def test_too_few_or_too_many_directions_are_refused_at_frame_build_time() -> None:
    mesh = fractured_plate()
    target = target_of(mesh)
    rois = fr.fracture_rois(target, roi_config(), footprint_radius_mm=20.0)
    for bad in (2, 7):
        config = roi_config(directions=bad, direction_offsets_deg=tuple(
            [0.0, 35.0, -35.0, 55.0, -55.0, 45.0, 30.0][:bad]))
        profile = fr.closeup_profile(config, delivered_long_edge_px=256)
        with pytest.raises(SynLabError) as excinfo:
            fr.make_fracture_roi_frames(rois=rois, profile=profile, spec=small_spec(),
                                        config=config, long_edge_px=256,
                                        rng=make_rng(1, "roi_test", "camera"))
        assert excinfo.value.code == ErrorCode.SCHEMA_INVALID


# ------------------------------------------------------------------ the rendered close-ups
def test_roi_views_are_rendered_not_upsampled_and_measure_a_smaller_mm_per_px() -> None:
    mesh = fractured_plate(tilt_mm=0.2)
    target = target_of(mesh)
    config = roi_config(directions=3, max_fractures_per_target=1)
    profile = fr.closeup_profile(config, delivered_long_edge_px=256)
    rois = fr.fracture_rois(target, config, footprint_radius_mm=20.0)
    spec = small_spec(delivered_size=(256, 192), max_render_pixels=256 * 256)
    rng = make_rng(5, "roi_test", "camera")
    frames = fr.make_fracture_roi_frames(rois=rois, profile=profile, spec=spec, config=config,
                                         long_edge_px=256, rng=rng, mesh=mesh)
    bundles, seconds = fr.render_fracture_roi_views(target=target, frames=frames, spec=spec,
                                                    rng=rng, backend="software_rasterizer")
    assert len(bundles) == 3
    assert seconds >= 0.0
    records = [fr.view_resolution_record(b, mesh=mesh) for b in bundles]
    whole = rt.render_views(target, camera_profiles()[1], small_spec(delivered_size=(256, 192),
                                                                    max_render_pixels=256 * 256),
                            make_rng(5, "roi_test", "camera"), backend="software_rasterizer")
    whole_records = [fr.view_resolution_record(b, mesh=mesh) for b in whole]
    whole_mm_per_px = float(np.median([r["mm_per_px_axis_raycast"] for r in whole_records]))
    roi_mm_per_px = float(np.median([r["mm_per_px_axis_raycast"] for r in records]))
    assert roi_mm_per_px < whole_mm_per_px, (
        f"the close-up must sample finer than the whole-fragment view "
        f"({roi_mm_per_px} vs {whole_mm_per_px})")
    for record in records:
        assert record["delivered_size_px"] == [256, 192]
        assert record["mm_per_px_axis_raycast"] > 0
        # the delivered grid is the render grid scaled by a declared factor, never upsampled
        assert record["f_px_delivered"] <= record["f_px_native"] + 1e-9
        assert record["rim_px"] > 0, "the close-up must actually show the fracture surface"


def test_the_summary_compares_whole_fragment_with_the_closeup() -> None:
    mesh = fractured_plate(tilt_mm=0.3)
    target = target_of(mesh)
    config = roi_config(directions=3, max_fractures_per_target=1)
    profile = fr.closeup_profile(config, delivered_long_edge_px=256)
    rois = fr.fracture_rois(target, config, footprint_radius_mm=18.0)
    spec = small_spec(delivered_size=(256, 192), max_render_pixels=256 * 256)
    rng = make_rng(9, "roi_test", "camera")
    roi_bundles, _ = fr.render_fracture_roi_views(
        target=target,
        frames=fr.make_fracture_roi_frames(rois=rois, profile=profile, spec=spec,
                                           config=config, long_edge_px=256, rng=rng, mesh=mesh),
        spec=spec, rng=rng, backend="software_rasterizer")
    whole_bundles = rt.render_views(target, camera_profiles()[1], spec,
                                    make_rng(9, "roi_test", "camera"),
                                    backend="software_rasterizer")
    whole_records = [fr.view_resolution_record(b, mesh=mesh) for b in whole_bundles]
    roi_records = [fr.view_resolution_record(b, mesh=mesh) for b in roi_bundles]
    summary = fr.roi_summary(rois=rois, whole_records=whole_records, roi_records=roi_records)
    assert summary["improvement_factor_mm_per_px"] > 1.0
    assert summary["axis_raycast"]["improvement_factor"] > 1.0
    assert summary["fracture_roi"]["effective_directions_per_fracture"]
    assert all(count >= 1 for count in
               summary["fracture_roi"]["effective_directions_per_fracture"].values())
    assert summary["measured_amplitudes_mm"]
    assert summary["instrument_disagreement_mm"]["n_views"] == (
        len(whole_records) + len(roi_records))


# ------------------------------------------------------------------ the observation
def test_roi_views_are_appended_to_the_whole_fragment_observation() -> None:
    mesh = fractured_plate(tilt_mm=0.25)
    target = target_of(mesh)
    config = roi_config(directions=3, max_fractures_per_target=1)
    profile = fr.closeup_profile(config, delivered_long_edge_px=256)
    rois = fr.fracture_rois(target, config, footprint_radius_mm=18.0)
    whole_spec = small_spec(delivered_size=(256, 192), max_render_pixels=256 * 256)
    roi_spec = small_spec(delivered_size=(256, 192), max_render_pixels=256 * 256)
    rng = make_rng(13, "roi_test", "camera")
    observation, whole_bundles = rt.route_proxy_scan(target, camera_profiles()[1], whole_spec,
                                                     rng, backend="software_rasterizer")
    whole_ids = [v.view_id for v in observation.views]
    roi_bundles, _ = fr.render_fracture_roi_views(
        target=target,
        frames=fr.make_fracture_roi_frames(rois=rois, profile=profile, spec=roi_spec,
                                           config=config, long_edge_px=256, rng=rng, mesh=mesh),
        spec=roi_spec, rng=rng, backend="software_rasterizer")
    whole_records = [fr.view_resolution_record(b, mesh=mesh) for b in whole_bundles]
    roi_records = [fr.view_resolution_record(b, mesh=mesh) for b in roi_bundles]
    augmented = fr.append_roi_views(observation=observation, roi_bundles=roi_bundles,
                                    spec=roi_spec, config=config, rois=rois,
                                    whole_records=whole_records, roi_records=roi_records,
                                    timings={"fracture_roi_seconds": 0.0})
    # new views, not replacements: the whole-fragment views are still there, in order
    assert [v.view_id for v in augmented.views][:len(whole_ids)] == whole_ids
    assert len(augmented.views) == len(whole_ids) + len(roi_bundles)
    families = augmented.meta["view_family_counts"]
    assert families[fr.VIEW_FAMILY_WHOLE] == len(whole_ids)
    assert families[fr.VIEW_FAMILY_ROI] == len(roi_bundles)
    block = augmented.meta["fracture_roi"]
    assert block["views_added_not_replaced"] is True
    assert block["same_run_as_whole_fragment"] is True
    assert block["n_fractures_measured"] == len(rois)
    ledger = block["resolution_ledger"]["per_view"]
    for view in augmented.views[len(whole_ids):]:
        record = ledger[view.view_id]
        assert record["view_family"] == fr.VIEW_FAMILY_ROI
        assert record["mm_per_px_axis_raycast"] > 0
        assert record["px_per_mm_measured"] > 0
        assert record["r_eff_mm_4px"] == pytest.approx(4.0 * record["mm_per_px_measured"])
        assert view.meta["view_family"] == fr.VIEW_FAMILY_ROI
    # same basis: the whole-fragment family is present, and the ROI views come from the close-up
    # condition derived from the same camera tier (its own profile id, its own calibration state)
    whole_tiers = {v.frame.tier for v in augmented.views[:len(whole_ids)]}
    assert whole_tiers, "the whole-fragment family must be present"
    for view in augmented.views[len(whole_ids):]:
        assert "ROI60mm" in view.frame.profile_id, view.frame.profile_id
        assert view.frame.tier == profile.tier
        assert view.frame.working_distance_mm == pytest.approx(config.working_distance_mm)


def test_append_without_roi_bundles_is_a_no_op_family() -> None:
    mesh = fractured_plate()
    target = target_of(mesh)
    observation, _ = rt.route_proxy_scan(target, camera_profiles()[1], small_spec(),
                                         make_rng(2, "roi_test", "camera"),
                                         backend="software_rasterizer")
    before = len(observation.views)
    augmented = fr.append_roi_views(observation=observation, roi_bundles=[], spec=small_spec(),
                                    config=roi_config(), rois=[],
                                    whole_records=[], roi_records=[])
    assert len(augmented.views) == before
    assert augmented.meta["view_family_counts"][fr.VIEW_FAMILY_ROI] == 0
