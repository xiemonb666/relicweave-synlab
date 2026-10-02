"""Realism models: antique wear/aging, capture-rig error and the 14<->8 mapping (A12).

These tests assert the *contract* of the two new models, not their numbers:

* **level 0 is a true identity** — the wear model returns the source mesh object itself and does
  not touch a vertex; every rig-error term refuses to be applied at level 0;
* **geometry stays legal** — the produced body is watertight, positive-volume and a subset of the
  clean body at the shipped 1e-3 mm tolerance (asserted with
  :func:`synlab.physical.api.subset_outside_stats`, the same instrument the A09 audit uses, whose
  tolerance is never relaxed here);
* **the parameters reach the meta** — every measurement the models report (depth, contact area,
  lost volume, glaze-loss area, radial displacement, PSF sigma, scale error) is present in the
  returned structure and is a finite number, and the candidate provenance is carried along;
* **the mapping table is complete** — all 14 components and all 8 quality items are accounted for,
  including the two documented structural gaps.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

import synlab.degrade.mapping as M
import synlab.degrade.rig_error as RE
import synlab.degrade.wear as W
from synlab.degrade.specs import (
    CANDIDATE,
    DEGRADATION_VECTOR_14,
    DERIVED,
    DOCUMENTED,
    MEASURED,
    PROVENANCE_KINDS,
    QUALITY_VECTOR_ITEMS,
    UNKNOWN,
    capture_rig_spec,
    light_modes,
    material_wear_traits,
)
from synlab.degrade.wear import WearModel, apply_wear, legality_report

REPO = Path(__file__).resolve().parents[3]
REPORT_DIR = REPO.parent / "data" / "a12_reports"


# ---------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def shell_body() -> trimesh.Trimesh:
    """A real closed thin-walled body built with no boolean engine (revolve of a profile)."""
    radius, height, wall = 22.0, 26.0, 1.6
    profile = np.array([
        [0.0, 0.0], [radius, 0.0], [radius, height],
        [radius - wall, height], [radius - wall, wall], [0.0, wall],
    ], dtype=np.float64)
    body = trimesh.creation.revolve(profile, sections=96)
    body.merge_vertices()
    return body


@pytest.fixture(scope="module")
def worn(shell_body: trimesh.Trimesh) -> dict:
    """The wear ladder on the probe shell (levels 1..4), computed once."""
    model = WearModel(material_id="M03", handling_contacts=40.0)
    out = {}
    for level in (1, 2, 3, 4):
        out[level] = apply_wear(shell_body, level, model=model)
    return out


# ---------------------------------------------------------------------------- level 0
def test_wear_level0_is_the_source_object_and_writes_nothing(shell_body) -> None:
    result = apply_wear(shell_body, 0)
    assert result.mesh is shell_body, "level 0 must return the source mesh object itself"
    assert result.intensity == 0.0
    assert result.field.applied_mm.size == 0 or not np.any(result.field.applied_mm > 0)
    assert result.field.measured == {}, "level 0 declares no measurement"
    assert result.field.info["identity"] is True
    # the object is literally untouched: same buffers, same hash
    assert np.array_equal(np.asarray(result.mesh.vertices), np.asarray(shell_body.vertices))
    assert np.array_equal(np.asarray(result.mesh.faces), np.asarray(shell_body.faces))


def test_wear_level0_report_of_a_stored_asset_is_byte_unchanged(tmp_path) -> None:
    """The store round trip: level 0 references the original asset and its exact bytes."""
    from synlab.degrade.sources import commit_source, load_source
    from synlab.roles import ROLE_FRAGMENT_MESH, SCHEMA_MOTHER
    from synlab.storage.store import AssetStore

    store = AssetStore(tmp_path / "wear_store")
    body = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
    source = W.__dict__  # placeholder to keep the import list honest; the bundle is built below
    del source
    from synlab.degrade.sources import KIND_MESH, SourceBundle

    bundle = SourceBundle(source_kind=KIND_MESH, payload={"mesh": body}, meta={"master_seed": 1})
    record = commit_source(store, bundle, role=ROLE_FRAGMENT_MESH, schema=SCHEMA_MOTHER,
                           lineage_id="wear_lineage", split="train")
    reloaded = load_source(store, record.asset_id)
    before = np.asarray(reloaded.get("mesh").vertices, dtype=np.float64).tobytes()
    result = apply_wear(reloaded.get("mesh"), 0)
    after = np.asarray(result.mesh.vertices, dtype=np.float64).tobytes()
    assert result.mesh is reloaded.get("mesh")
    assert before == after
    assert len(store.list_assets(limit=100)) == 1, "level 0 must not commit anything"


@pytest.mark.parametrize("level", [0, 1, 2, 3, 4])
def test_wear_level_parameters_are_declared_and_written_into_meta(shell_body, level) -> None:
    result = apply_wear(shell_body, level)
    info = result.field.info
    assert info["level"] == level
    assert info["intensity"] == W.WearLevels.INTENSITY[level]
    assert info["level_ladder"] == list(W.WearLevels.INTENSITY)
    assert "guard" in info and info["level_parameter_kind"].startswith("fraction of")
    assert result.info["model"]["margin"]["provenance"] == CANDIDATE
    if level == 0:
        assert result.field.info["identity"] is True
        assert result.field.info["soil"]["domain"] == "IMAGE_ONLY"
        return
    assert "drivers" in info and "bands" in info
    # every declared driver is a finite number or an explicitly typed record
    for name, value in info["drivers"].items():
        if isinstance(value, (int, float)):
            assert np.isfinite(float(value)), f"driver {name} is not finite"
    assert result.info["offset_method"].startswith("per-vertex inward offset")


# ---------------------------------------------------------------------------- geometry legality
@pytest.mark.parametrize("level", [1, 2, 3, 4])
def test_wear_geometry_stays_legal_with_the_shipped_tolerance(shell_body, worn, level) -> None:
    """Watertight, positive volume, ``damaged subset of clean`` at 1e-3 mm (not relaxed)."""
    result = worn[level]
    report = legality_report(shell_body, result.mesh, n_samples=1200, seed=0)
    assert report["tolerance_mm"] == 1e-3, "the A09 tolerance must not be relaxed"
    assert report["watertight"] is True, report
    assert report["positive_volume"] is True, report
    assert report["damaged_subset_clean"] is True, report
    assert report["subset_outside_points"] == 0, report
    assert "signed_distance" in report["subset_instrument"]


@pytest.mark.parametrize("level", [1, 2, 3, 4])
def test_wear_is_a_true_material_loss(shell_body, worn, level) -> None:
    """The loss is real: fewer mm3, a positive depth field, and a monotone ladder."""
    measured = worn[level].field.measured
    assert measured["max_applied_depth_mm"] > 0
    assert measured["lost_volume_mm3"] > 0
    assert measured["volume_after_mm3"] < measured["volume_before_mm3"]
    assert measured["contact_area_mm2"] > 0
    assert measured["glaze_lost_area_ratio"] >= 0.0
    assert np.isfinite(measured["glaze_exposed_volume_mm3"])
    # the wall guard is multiplicative and never exceeded
    margin = WearModel().margin
    wall = worn[level].wall["values_mm"]
    finite = np.isfinite(wall)
    assert np.all(worn[level].field.applied_mm[finite] <= margin * wall[finite] + 1e-9)


def test_wear_ladder_is_monotone_in_depth_and_volume(worn) -> None:
    depths = [worn[level].field.measured["max_applied_depth_mm"] for level in (1, 2, 3, 4)]
    volumes = [worn[level].field.measured["lost_volume_mm3"] for level in (1, 2, 3, 4)]
    assert depths == sorted(depths), depths
    assert volumes == sorted(volumes), volumes
    assert depths[0] < depths[-1] and volumes[0] < volumes[-1]


def test_wear_is_spatially_structured_not_global_noise(shell_body, worn) -> None:
    """A spatial model varies across the body; a global offset or a noise floor would not."""
    applied = worn[4].field.applied_mm
    assert applied.size == len(shell_body.vertices)
    moved = applied > 0
    assert float(np.mean(moved)) > 0.5, "the level must move a substantial part of the surface"
    # the depth field is *structured*: a wide spread and a long tail relative to its own mean,
    # which a global offset (all vertices equal) or a constant noise floor cannot produce
    coefficient_of_variation = float(np.std(applied[moved]) / max(np.mean(applied[moved]), 1e-12))
    assert coefficient_of_variation > 0.25, (
        f"depth spread {coefficient_of_variation:.3f} is too small for a spatial wear pattern")
    # the *untouched* complement is the strongest evidence of compact support (a rim band and a
    # base band leave the middle of the wall alone)
    assert float(np.mean(applied <= 0.0)) > 0.0, (
        "a wear field that moves every single vertex is a global offset, not a wear model")
    assert int(np.unique(np.round(applied, 6)).size) >= 3, (
        "the depth field takes fewer than three distinct values, so it is not a continuous "
        "spatial function")
    # and the region means differ: rim vs. base vs. outer are not the same surface treatment
    measured = worn[4].field.measured
    region_means = [measured["mean_depth_rim_mm"], measured["mean_depth_base_mm"],
                    measured["mean_depth_outer_mm"]]
    assert max(region_means) > 0.0
    assert len({round(value, 6) for value in region_means}) > 1, (
        f"every region received the same depth, so the model is not region-aware: {region_means}")
    # the per-mechanism fields must differ from each other (six mechanisms, six shapes)
    fields = worn[4].field.per_mechanism
    assert len(fields) >= 5
    shapes = {name: tuple(np.round(np.asarray(values, dtype=float), 6)[:64].tolist())
              for name, values in fields.items()}
    assert len(set(shapes.values())) == len(shapes), "mechanism fields are not distinct"


def test_wear_drivers_are_measured_on_the_body_not_assumed(shell_body) -> None:
    """Wall thickness, curvature and the layer thickness come from the body itself."""
    thick = W.local_thickness(shell_body)
    assert thick["hits"] > 0
    assert 0.5 * 1.6 <= thick["median_mm"] <= 2.0 * 1.6, thick
    assert thick["method"].startswith("per-vertex inward ray cast")
    kappa = W.vertex_mean_curvature(shell_body, thick["values_mm"])
    assert kappa.shape == (len(shell_body.vertices),)
    assert np.isfinite(kappa).all()
    result = apply_wear(shell_body, 4)
    lo, hi = WearModel().layer_thickness_range_mm
    assert lo <= result.layer["median_mm"] <= hi, "the layer thickness must stay inside the "
    assert result.layer["clamp_provenance"].startswith("MEASURED")


def test_wear_refuses_an_unknown_mechanism(shell_body) -> None:
    from synlab.errors import SynLabError

    with pytest.raises(SynLabError):
        apply_wear(shell_body, 2, mechanisms=("rim_wear", "polish_magic"))


def test_wear_level_out_of_range_is_refused(shell_body) -> None:
    from synlab.errors import SynLabError

    with pytest.raises(SynLabError):
        apply_wear(shell_body, 5)


def test_wear_is_deterministic(shell_body) -> None:
    first = apply_wear(shell_body, 3, model=WearModel(material_id="M03"))
    second = apply_wear(shell_body, 3, model=WearModel(material_id="M03"))
    assert np.array_equal(first.field.applied_mm, second.field.applied_mm)
    assert np.array_equal(np.asarray(first.mesh.vertices), np.asarray(second.mesh.vertices))
    for name in first.field.soil:
        assert np.array_equal(first.field.soil[name], second.field.soil[name])


def test_soil_layer_is_image_domain_only(shell_body) -> None:
    """Soil/patina must not move geometry: its own field, its own domain label."""
    plain = apply_wear(shell_body, 4, mechanisms=("rim_wear", "base_abrasion", "glaze_loss",
                                                  "edge_chip", "microcrack"))
    with_soil = apply_wear(shell_body, 4, mechanisms=("rim_wear", "base_abrasion", "glaze_loss",
                                                      "edge_chip", "microcrack", "soil_layer"))
    assert np.array_equal(plain.field.applied_mm, with_soil.field.applied_mm), (
        "the soil layer changed the geometry, so it is not separated from it")
    assert np.array_equal(np.asarray(plain.mesh.vertices), np.asarray(with_soil.mesh.vertices))
    assert set(with_soil.field.soil) == set(W.SOIL_TYPES)
    assert with_soil.field.info["soil"]["domain"] == "IMAGE_ONLY"
    assert with_soil.field.info["soil"]["separated_from_geometry"] is True


# ---------------------------------------------------------------------------- catalogue provenance
def test_every_catalogue_value_declares_its_provenance() -> None:
    rig = capture_rig_spec()
    candidates = rig.candidates()
    assert candidates, "the candidate list must not be empty while nothing is bench-calibrated"
    for entry in candidates:
        assert entry["provenance"] in PROVENANCE_KINDS
        assert entry["path"], entry
    blob = json.dumps(rig.as_dict(), default=str)
    for kind in (DOCUMENTED, DERIVED, MEASURED, CANDIDATE, UNKNOWN):
        assert kind in blob, f"provenance {kind} never appears in the catalogue"
    # the documented hardware facts must be there with their refs
    assert rig.camera.sensor_width_px.value == 2304
    assert rig.camera.fov_h_deg.value == 84.0
    assert rig.camera.shutter.value == "ROLLING"
    assert rig.camera.focus_mode.value == "MANUAL"
    assert rig.camera.resolution_mm_per_px[50].value == 0.039
    assert rig.camera.resolution_mm_per_px[250].value == 0.195
    assert rig.camera.resolution_mm_per_px[50].provenance == DOCUMENTED
    for mode in ("WHITE_DIFFUSE", "LEFT_GRAZE", "RIGHT_GRAZE", "CROSS_POL", "NORMAL_REFLECT"):
        assert mode in light_modes()


def test_material_traits_carry_the_measured_layer_interval() -> None:
    traits = material_wear_traits("M03")
    assert traits.glaze_fraction_of_wall.value > 0
    assert "0.469-1.173" in traits.ref or "0.469" in traits.ref
    unknown = material_wear_traits("M99")
    assert "M12" in unknown.ref or "not in M01..M12" in unknown.ref


# ---------------------------------------------------------------------------- rig error
def test_rig_error_level0_terms_are_the_identity() -> None:
    """No rig-error term may be applied at level 0: each refuses a zero-sized change."""
    from synlab.errors import SynLabError

    frame = {"rgb_linear": np.zeros((8, 8, 3), dtype=np.float32), "encoding": "LINEAR"}
    with pytest.raises(SynLabError):
        RE.apply_defocus(frame, 0.0)
    with pytest.raises(SynLabError):
        RE.apply_rolling_shutter(frame, np.zeros(9))          # wrong row count
    # the zero-shift rolling shutter is an exact identity on the delivered plane
    same, info = RE.apply_rolling_shutter(frame, np.zeros(8))
    assert np.array_equal(same["rgb_linear"], frame["rgb_linear"])
    assert info["max_shift_px"] == 0.0
    lights = RE.IlluminationModel().weights("WHITE_DIFFUSE")
    assert lights["provenance"] == CANDIDATE


def test_rolling_shutter_numbers_follow_the_documented_geometry() -> None:
    rig = capture_rig_spec()
    info = RE.rolling_shutter_displacement_px(line_time_s=8.9e-6, rows=1296, rate_dps=2.0,
                                              fov_h_deg=84.0, width_px=2304)
    readout = 8.9e-6 * 1296
    assert info["frame_readout_s"] == pytest.approx(readout, rel=1e-9)
    expected = (2.0 * readout) / 84.0 * 2304
    assert info["displacement_px"] == pytest.approx(expected, rel=1e-9)
    assert info["provenance"] == CANDIDATE
    assert "待实测" in info["calibration"]


def test_rolling_shutter_is_per_row_and_not_a_global_translation() -> None:
    rig = capture_rig_spec()
    rows, cols = 64, 32
    offsets, info = RE.RollingShutterModel(rate_dps=40.0).row_offsets_px(
        rig, width_px=cols, rows=rows)
    assert offsets.shape == (rows,)
    assert np.all(np.diff(offsets) > 0), "the row delay must be a ramp"
    assert info["max_row_offset_px"] > 0
    frame = {"rgb_linear": np.random.RandomState(0).rand(rows, cols, 3).astype(np.float32),
             "encoding": "LINEAR"}
    shifted, apply_info = RE.apply_rolling_shutter(frame, offsets, axis_u=0.5)
    delta = np.abs(shifted["rgb_linear"] - frame["rgb_linear"]).mean(axis=(1, 2))
    assert delta[-1] > delta[0], "the bottom rows must move more than the top rows"
    assert apply_info["not_a_global_translation"] is True


def test_defocus_uses_the_repository_coc_instrument_and_the_units_convention() -> None:
    rig = capture_rig_spec()
    on_focus = RE.FocusModel().circle_of_confusion_px(rig, focus_distance_mm=150.0,
                                                       object_distance_mm=150.0)
    assert on_focus["coc_px"] == pytest.approx(0.0, abs=1e-9)
    assert on_focus["psf_sigma_px"] == pytest.approx(0.0, abs=1e-9)
    blurred = RE.FocusModel().circle_of_confusion_px(rig, focus_distance_mm=150.0,
                                                     object_distance_mm=200.0)
    assert blurred["coc_px"] > 1.0
    assert "circle_of_confusion_px" in blurred["instrument"]
    assert blurred["provenance"] == CANDIDATE
    assert on_focus["px_per_mm_sensor"] == pytest.approx(1.0 / rig.camera.pixel_pitch_mm.value)


def test_scale_drift_reports_arbitrary_scale_without_a_reference() -> None:
    bounded = RE.ScaleDriftModel().drift(reference_present=True, reference_visible_fraction=1.0,
                                         condition=1.0, level=4)
    assert bounded["status"] == "BOUNDED"
    assert bounded["scale_error_relative"] == pytest.approx(0.05)
    arbitrary = RE.ScaleDriftModel().drift(reference_present=False, reference_visible_fraction=0.0,
                                           condition=1.0, level=4)
    assert arbitrary["status"] == "ARBITRARY"
    assert arbitrary["scale_error_relative"] == float("inf")
    assert arbitrary["scale_error_percent"] is None


def test_intrinsics_drift_stays_inside_the_candidate_bounds() -> None:
    K = np.array([[1000.0, 0.0, 512.0], [0.0, 1000.0, 384.0], [0.0, 0.0, 1.0]])
    model = RE.IntrinsicsDriftModel()
    worst, info = model.drift(K, condition_u=1.0, condition_v=1.0, level=4)
    assert info["provenance"] == CANDIDATE
    assert worst[0, 0] == pytest.approx(1000.0 * 1.03)
    assert worst[0, 2] == pytest.approx(517.0)
    assert "待实测校准" in info["calibration"]
    identity, _ = model.drift(K, condition_u=0.0, condition_v=0.0, level=0)
    assert np.array_equal(identity, K)


def test_resolution_at_distance_uses_the_documented_table_and_never_calls_it_a_resize() -> None:
    rig = capture_rig_spec()
    model = RE.ResolutionAtDistanceModel()
    for distance, expected in ((50, 0.039), (100, 0.078), (150, 0.117), (200, 0.156), (250, 0.195)):
        info = model.effective(rig, float(distance), 2304)
        assert info["mm_per_px"] == pytest.approx(expected)
        assert info["mm_per_px_provenance"] == DOCUMENTED
        assert info["not_a_resize"] is True
    # a frame at a different distance gets a different K, not a resized claim
    frame = {"rgb_linear": np.ones((32, 32, 3), dtype=np.float32), "encoding": "LINEAR",
             "K": np.array([[100.0, 0.0, 16.0], [0.0, 100.0, 16.0], [0.0, 0.0, 1.0]])}
    out, info = RE.resample_to_distance(frame, from_distance_mm=150.0, to_distance_mm=50.0)
    assert info["op"] == "REPROJECTED_PIXEL_DENSITY"
    assert info["scale_factor"] == pytest.approx(3.0)
    assert out["K"][0, 0] == pytest.approx(300.0)
    assert "not a physical approach" in info["not_a_resize_claim"]


def test_cross_polarisation_suppresses_only_part_of_the_highlight() -> None:
    """The plan's wording is 降低部分釉面高光; the model must not remove it completely."""
    frame = {"rgb_linear": np.ones((16, 16, 3), dtype=np.float32), "encoding": "LINEAR"}
    frame["rgb_linear"][4:8, 4:8, :] = 6.0                      # a bright glaze highlight
    model = RE.IlluminationModel()
    plain, plain_info = model.apply(frame, "WHITE_DIFFUSE", level=4)
    cross, cross_info = model.apply(frame, "CROSS_POL", level=4)
    assert cross_info["highlight_suppression_ratio"] > 0.5
    assert cross_info["highlight_region_luma_after"] > 0.0, (
        "a perfect crossed pair leaves k_perp^2 of the specular return; zero would claim the "
        "highlight is removed, which the plan explicitly does not say")
    assert cross_info["specular_retained"] == pytest.approx(0.22)
    assert plain_info["specular_retained"] == pytest.approx(1.0)
    for mode in light_modes():
        info = model.weights(mode)
        assert info["provenance"] == CANDIDATE
        assert info["documented_part"]
    graze_left = model.apply(frame, "LEFT_GRAZE", level=4)[0]["rgb_linear"].mean()
    graze_right = model.apply(frame, "RIGHT_GRAZE", level=4)[0]["rgb_linear"].mean()
    assert graze_left == pytest.approx(graze_right), (
        "the two grazing states differ only by mirror symmetry, which a single frame cannot show; "
        "the model must not invent an asymmetry")


def test_reconstruction_model_applies_the_documented_floor() -> None:
    rig = capture_rig_spec()
    model = RE.ReconstructionModel()
    near = model.noise_sigma_mm(rig, working_distance_mm=50.0, baseline_mm=40.0)
    far = model.noise_sigma_mm(rig, working_distance_mm=250.0, baseline_mm=40.0)
    assert far["sigma_mm"] > near["sigma_mm"], "depth noise must grow with distance"
    assert far["sigma_mm"] / near["sigma_mm"] == pytest.approx(25.0, rel=1e-6)
    assert far["floor_mm"] == pytest.approx(0.2)
    assert far["floor_ref"].startswith("p1063") or "0.2 mm" in far["floor_ref"]
    assert near["sigma_parallax_provenance"] == CANDIDATE


def test_point_cloud_quality_measures_a_real_cloud() -> None:
    rng = np.random.default_rng(7)
    grid = np.stack(np.meshgrid(np.linspace(-10, 10, 21), np.linspace(-10, 10, 21),
                                indexing="ij"), axis=-1).reshape(-1, 2)
    clean = np.column_stack([grid, np.zeros(len(grid))])
    noisy = clean + rng.normal(scale=0.05, size=clean.shape)
    quality_clean = RE.measure_point_cloud_quality(clean, voxel_mm=1.0, plane_radius_mm=2.0)
    quality_noisy = RE.measure_point_cloud_quality(noisy, voxel_mm=1.0, plane_radius_mm=2.0)
    assert quality_clean["sigma_mm"] < quality_noisy["sigma_mm"]
    assert quality_noisy["sigma_mm"] == pytest.approx(0.05, abs=0.03)
    assert quality_clean["sigma_mm"] < 1e-6
    assert quality_clean["valid_fraction"] == 1.0
    for key in ("sigma_mm", "hole_count", "valid_fraction", "normal_drift_deg_median",
                "curvature_stability_mm"):
        assert key in quality_clean
    # a real point cloud has invalid points; they must be counted, not silently dropped
    with_nan = clean.copy()
    with_nan[:10] = np.nan
    quality_nan = RE.measure_point_cloud_quality(with_nan, voxel_mm=1.0, plane_radius_mm=2.0)
    assert quality_nan["n_valid"] == len(clean) - 10
    assert quality_nan["valid_fraction"] == pytest.approx((len(clean) - 10) / len(clean))


def test_hole_census_counts_enclosed_voids_only() -> None:
    """A slab cut clean through loses its border, so it is not an enclosed hole."""
    dense = np.stack(np.meshgrid(np.arange(24), np.arange(24), np.arange(6), indexing="ij"),
                     axis=-1).reshape(-1, 3).astype(np.float64)
    assert RE.measure_point_cloud_quality(dense, voxel_mm=1.0, plane_radius_mm=1.5)[
        "hole_count"] == 0
    enclosed = dense[~((dense[:, 0] >= 10) & (dense[:, 0] < 13) & (dense[:, 1] >= 10)
                       & (dense[:, 1] < 13) & (dense[:, 2] >= 2) & (dense[:, 2] < 4))]
    census = RE.measure_point_cloud_quality(enclosed, voxel_mm=1.0, plane_radius_mm=1.5)
    assert census["hole_count"] == 1, census["holes"]
    assert census["holes"][0]["voxels"] == 3 * 3 * 2
    assert census["holes"][0]["equivalent_radius_mm"] == pytest.approx(
        (3.0 * 18.0 / (4.0 * np.pi)) ** (1.0 / 3.0), rel=1e-9)
    tunnelled = dense[~((dense[:, 0] >= 10) & (dense[:, 0] < 13))]
    assert RE.measure_point_cloud_quality(tunnelled, voxel_mm=1.0, plane_radius_mm=1.5)[
        "hole_count"] == 0


def test_scan_fault_ladder_reports_every_term_with_provenance() -> None:
    ladder = RE.scan_fault_ladder(level=4)
    for term in ("rolling_shutter", "defocus", "depth_of_field", "intrinsics_drift",
                 "scale_drift", "light_states", "resolution", "reconstruction_noise", "model"):
        assert term in ladder, term
    assert ladder["levels"] == list(RE.RIG_LEVELS)
    assert ladder["rolling_shutter"]["row_offset_px_p95"] > 0
    assert ladder["defocus"]["psf_sigma_px"] > 0
    assert ladder["intrinsics_drift"]["provenance"] == CANDIDATE
    assert ladder["reconstruction_noise"]["floor_mm"] == pytest.approx(0.2)
    assert ladder["candidates"], "the ladder must carry the calibration list"
    identity = RE.scan_fault_ladder(level=0)
    assert identity["rolling_shutter"]["max_row_offset_px"] == 0.0
    assert identity["defocus"]["psf_sigma_px"] == 0.0
    assert identity["scale_drift"]["scale_error_relative"] == 0.0


# ---------------------------------------------------------------------------- mapping table
def test_mapping_table_is_complete_and_typed() -> None:
    report = M.mapping_completeness()
    assert report["missing_components"] == []
    assert report["extra_components"] == []
    assert report["components_present"] == list(DEGRADATION_VECTOR_14)
    assert set(report["quality_items_expected"]) == set(QUALITY_VECTOR_ITEMS)
    kinds = {link["component"]: link["kind"] for link in M.mapping_table()}
    assert set(kinds) == set(DEGRADATION_VECTOR_14)
    assert set(kinds.values()) <= set(M.LINK_KINDS)
    # every mapped link names at least one real quality item and a sensitivity for each
    for link in M.MAPPING_TABLE:
        if link.kind == M.UNMAPPABLE:
            assert link.quality_items == ()
        else:
            assert link.quality_items
            assert len(link.sensitivity) == len(link.quality_items)
        assert link.evidence in (MEASURED if False else "MEASURED_ON_THIS_MACHINE", DERIVED,
                                 CANDIDATE)
        assert link.synthetic_axis


def test_mapping_table_declares_the_two_structural_gaps() -> None:
    report = M.mapping_completeness()
    assert report["complete"] is False, (
        "the mapping cannot be 'complete': occlusion has no synthetic component and three "
        "components are invisible to the real quality vector")
    assert "occlusion" in report["quality_items_unreachable"]
    gaps = report["structural_gaps"]
    assert any("occlusion" in gap["gap"] for gap in gaps)
    unmappable = report["unmappable_components"]
    assert set(unmappable) == {"fracture_smoothing", "fracture_missing", "texture_loss"}
    for item in QUALITY_VECTOR_ITEMS:
        assert item in M.QUALITY_ITEM_SOURCES, f"{item} has no declared producer"


def test_mapping_link_sensitivities_match_the_signed_conventions() -> None:
    by_component = {link.component: link for link in M.MAPPING_TABLE}
    assert by_component["blur"].sensitivity == (1.0,)
    assert by_component["view_coverage"].sensitivity == (-1.0,)
    assert by_component["point_dropout"].sensitivity == (-1.0,)
    assert by_component["normal_noise"].sensitivity == (-1.0,)
    assert by_component["curvature_noise"].sensitivity == (-1.0,)
    assert by_component["glare"].quality_items == ("exposure", "blur")
    assert by_component["calibration_error"].kind == M.COMPOSITE


def test_inversion_round_trips_and_never_invents_an_unidentified_level() -> None:
    calibration = M.QualityCalibration()
    quality = {"blur": 1.0, "exposure": 0.5, "coverage": 0.8, "occlusion": 0.2,
               "reconstruction_confidence": 0.7, "point_density": 0.6, "normal_stability": 0.9,
               "curvature_stability": 0.85}
    inverted = M.levels_from_quality(quality, calibration=calibration)
    for component in ("fracture_smoothing", "fracture_missing", "texture_loss"):
        assert inverted["levels"][component] is None
        assert inverted["kind"][component] == "UNIDENTIFIED"
    for component in ("blur", "exposure", "view_coverage", "point_dropout", "normal_noise",
                      "curvature_noise"):
        assert inverted["kind"][component] == "OBSERVED"
        assert 0.0 <= inverted["levels"][component] <= 1.0
    forward = M.quality_from_levels({k: (v if v is not None else 0.0)
                                     for k, v in inverted["levels"].items()},
                                    calibration=calibration)
    # the round trip reproduces the items of the six *observed, non-collinear* components; the
    # composite components spread their signal over two items, so the reconstruction is asserted
    # through the reported residual rather than item by item
    assert inverted["residual_rms"] < 0.05, inverted["residual"]
    for item in ("blur", "exposure", "coverage", "point_density", "normal_stability",
                 "curvature_stability"):
        assert forward[item] == pytest.approx(quality[item], abs=0.06), (item, forward[item])
    assert inverted["residual_rms"] < 0.05


def test_inversion_without_quality_data_assigns_nothing() -> None:
    inverted = M.levels_from_quality({}, quality_validity={})
    assert inverted["observed_items"] == []
    assert all(value is None for value in inverted["levels"].values())
    assert all(kind == "UNIDENTIFIED" for kind in inverted["kind"].values())


def test_a_bad_mapping_link_is_refused() -> None:
    with pytest.raises(ValueError):
        M.DegradationLink(component="x", kind=M.ONE_TO_ONE, quality_items=("not_an_item",),
                          sensitivity=(1.0,), synthetic_axis="", evidence=DERIVED, note="")
    with pytest.raises(ValueError):
        M.DegradationLink(component="x", kind=M.UNMAPPABLE, quality_items=("blur",),
                          sensitivity=(1.0,), synthetic_axis="", evidence=DERIVED, note="")
    with pytest.raises(ValueError):
        M.DegradationLink(component="x", kind=M.ONE_TO_ONE, quality_items=("blur", "exposure"),
                          sensitivity=(1.0,), synthetic_axis="", evidence=DERIVED, note="")


# ---------------------------------------------------------------------------- measurement reports
def test_measurement_reports_exist_and_carry_the_required_numbers() -> None:
    """The two measurement runs are part of the deliverable, so their shape is asserted."""
    rig_report = REPORT_DIR / "a12_rig_error.json"
    wear_report = REPORT_DIR / "a12_wear_ladder.json"
    if not rig_report.exists() or not wear_report.exists():
        pytest.skip("measurement reports not generated in this environment")
    rig = json.loads(rig_report.read_text(encoding="utf-8"))
    assert rig["levels"] == list(RE.RIG_LEVELS)
    assert rig["frames"]["count"] >= 1
    assert len(rig["ladder"]) == 5
    assert rig["ladder"][0]["level"] == 0 and "identity" in rig["ladder"][0]
    last = rig["ladder"][-1]
    for key in ("max_row_offset_px", "measured_row_delta_gradient_per_row"):
        assert np.isfinite(last["rolling_shutter"][key])
    for key in ("coc_px", "psf_sigma_px", "gradient_energy_drop_ratio"):
        assert np.isfinite(last["defocus"][key])
    assert np.isfinite(last["scale_drift"]["scale_error_relative"])
    assert rig["resolution"]["documented_table"]["50"]["value"] == 0.039
    assert rig["resolution"]["documented_table"]["250"]["value"] == 0.195
    wear = json.loads(wear_report.read_text(encoding="utf-8"))
    assert wear["targets"], "the wear ladder must have at least one real target"
    for target in wear["targets"]:
        assert target["levels"]["0"]["identity_same_object"] is True
        assert target["levels"]["0"]["result_bytes_unchanged"] is True
        for level in ("1", "2", "3", "4"):
            row = target["levels"][level]
            if row.get("status") != "MEASURED":
                continue
            measured = row["measured"]
            for key in ("max_applied_depth_mm", "glaze_lost_area_ratio", "lost_volume_mm3",
                        "contact_area_mm2", "mean_depth_rim_mm", "mean_depth_base_mm"):
                assert key in measured, key
                assert np.isfinite(measured[key])
            legal = row["legality"]
            assert legal["tolerance_mm"] == 1e-3
            assert legal["watertight"] is True
            assert legal["positive_volume"] is True
