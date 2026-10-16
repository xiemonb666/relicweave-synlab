from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from synlab.errors import SynLabError
from synlab.integrations.reference_generator import (
    compose_reference_instance,
    load_reference_mother,
    sample_outer_wall_texture,
)
from synlab.materials.reference_materials import (
    reference_material,
    sample_reference_material,
)
from synlab.patterns.api import evaluate
from synlab.patterns.reference_styles import build_reference_pattern


WORKSPACE = Path(__file__).resolve().parents[2]
VF_OUTPUTS = (WORKSPACE / "vesselforge" / "experiments" / "continuation_20261015"
              / "reference_forms" / "outputs")
DAILY_FULL_BELLY = VF_OUTPUTS / "family_daily_full_belly_v1"
DAILY_FINAL = VF_OUTPUTS / "daily_aberdeen_108x53_v6_final"
DAILY_RECIPE_BASELINE = (VF_OUTPUTS / "reference_generation_outputs_v2"
                         / "daily_baseline_tokusa")


def test_loader_binds_real_candidate_triangles_by_exact_lineage_and_keeps_geometry() -> None:
    mother = load_reference_mother(DAILY_FINAL)
    assert mother.n_faces == 25_598
    assert mother.mesh.is_watertight
    assert mother.mesh.volume == pytest.approx(32_985.51424547626, abs=0.02)
    assert mother.meta["candidate_status"] == "SIZE_REFERENCE_GEOMETRY_CANDIDATE_ONLY"
    assert "NOT_ESTABLISHED" in mother.meta["source_profile_fidelity"]
    assert mother.meta["refinement_status"] == "SOURCE_PROFILE_FIDELITY_NOT_ESTABLISHED"
    assert mother.meta["lineage"]["native_face_source_segment_indices"]["1"] == [1]
    assert mother.meta["lineage"]["native_face_roles"][1] == "body_inner"
    names = np.asarray([mother.tag_name(tag) for tag in mother.face_surface_tag])
    assert set(names) == {"outer_wall", "inner_wall", "rim", "foot", "base"}
    assert len(mother.charts) == 2
    assert all("FINITE_POLYLINE_APPROXIMATION" in chart.meta["reference_curve_sampling"][
        "arclength_status"] for chart in mother.charts)
    assert mother.meta["geometry_array_sha256"]


def test_composition_uses_real_pattern_and_material_fields_without_changing_geometry() -> None:
    instance = compose_reference_instance(
        DAILY_FULL_BELLY,
        "daily_aberdeen_porcelain_celadon",
        "daily_hasami_tokusa",
        {"material": 314, "pattern": 271},
        {"material": {"coating_roughness": 0.23},
         "pattern": {"line_width_mm": 1.7, "spacing_mm": 11.0}},
    )
    assert instance.metrics["geometry_unchanged"] is True
    assert instance.metrics["geometry_array_sha256_before"] == instance.metrics[
        "geometry_array_sha256_after"]
    assert instance.metrics["pattern_region_triangle_count"] > 0
    assert instance.metrics["max_abs_pattern_height_mm"] == 0.0
    assert instance.metrics["physical_properties_status"] == "UNKNOWN"
    assert instance.metrics["training_export_status"] == "NOT_REQUESTED_NOT_EXPORTED"
    assert instance.pattern_recipe.params["line_width_mm"] == pytest.approx(1.7)
    assert instance.material_profile["source_conditioned"]["controls"][
        "coating_roughness"]["value"] == pytest.approx(0.23)
    tags = instance.fields["face_surface_tag"]
    painted = instance.fields["pattern_region"].astype(bool)
    assert np.all(tags[painted] == 0)  # outer_wall is the selected source style region
    assert np.any(np.abs(instance.fields["combined_albedo_linear_rgb"]
                         - instance.fields["material_albedo_linear_rgb"]) > 1e-5)
    assert instance.recipe["generation_mode"] == "NEW_REFERENCE_GUIDED_DESIGN"
    assert instance.provenance["interpretation"].find("not an exact source-object clone") >= 0


def test_original_surface_coating_and_fresh_interface_stay_tag_scoped() -> None:
    mother = load_reference_mother(DAILY_FINAL)
    profile = reference_material("daily_aberdeen_porcelain_celadon", seed=10)
    assert profile["coating_surface_policy"]["version"] == 1
    assert profile["field_kernel_version"] == 2
    recipe = build_reference_pattern(mother, "daily_hasami_tokusa", seed=12)
    tag_names = np.asarray([mother.tag_name(tag) for tag in mother.face_surface_tag], dtype=object)
    centers = np.asarray(mother.mesh.triangles_center)
    sampled = sample_reference_material(profile, centers, tag_names)
    layer_by_tag = {
        tag: set(np.asarray(sampled["layer_name"], dtype=object)[tag_names == tag])
        for tag in set(tag_names.tolist())
    }
    for coated in ("outer_wall", "inner_wall", "rim"):
        assert layer_by_tag[coated] == {"source_named_surface_finish"}
    for bare in ("foot", "base"):
        assert "source_named_surface_finish" not in layer_by_tag[bare]

    interface_material = sample_reference_material(profile, centers[:4], "interface")
    interface_pattern = evaluate(recipe, mother, centers[:4], "interface")
    assert set(interface_material["layer_name"]) == {"body"}
    assert int(np.count_nonzero(interface_pattern.pattern_region)) == 0
    assert np.all(interface_pattern.height_mm == 0.0)


def test_exact_inside_floor_lineage_gets_interior_finish_and_underside_stays_bare() -> None:
    mother = load_reference_mother(DAILY_RECIPE_BASELINE)
    lineage = mother.meta["lineage"]
    assert lineage["inside_floor_surface_binding"]["source_segment_index"] == 0
    assert lineage["inside_floor_surface_binding"]["source_native_face_index"] == 0
    assert lineage["native_face_roles"][0] == "base"
    assert lineage["native_face_surface_roles"][0] == "inner_floor"
    assert lineage["native_face_source_segment_indices"]["0"] == [0]
    assert lineage["native_face_roles"][15] == "base"
    assert lineage["native_face_surface_roles"][15] == "base"

    source_faces = np.asarray(mother.meta["triangle_source_brep_face_index"])
    floor_faces = source_faces == 0
    underside_faces = source_faces == 15
    assert np.any(floor_faces)
    assert np.any(underside_faces)
    names = np.asarray([mother.tag_name(tag) for tag in mother.face_surface_tag], dtype=object)
    assert set(names[floor_faces]) == {"inner_wall"}
    assert set(names[underside_faces]) == {"base"}
    # The floor triangles are the exact source plane at z=10 mm, not a nearby body selection.
    assert np.allclose(mother.mesh.triangles_center[floor_faces, 2], 10.0, atol=1e-8)

    profile = reference_material("daily_aberdeen_porcelain_celadon", seed=20)
    sampled = sample_reference_material(
        profile, mother.mesh.triangles_center, names)
    layers = np.asarray(sampled["layer_name"], dtype=object)
    assert set(layers[floor_faces]) == {"source_named_surface_finish"}
    assert set(layers[underside_faces]) == {"body"}
    assert mother.chart_for_tag(1).meta["surface_chart_scope"][
        "inside_floor_pattern_chart"] == "NOT_PROVIDED"


def test_continuous_texture_matches_original_chart_and_has_a_periodic_seam() -> None:
    instance = compose_reference_instance(
        DAILY_FULL_BELLY,
        "daily_aberdeen_porcelain_celadon",
        "daily_hasami_tokusa",
        {"material": 501, "pattern": 502},
        {"material": {"coating_roughness": 0.19},
         "pattern": {"line_width_mm": 1.2, "spacing_mm": 11.0}},
    )
    texture = sample_outer_wall_texture(instance, n_theta=128, n_s=64)
    metrics = texture["metrics"]
    chart_check = metrics["general_chart_validation"]
    seam_check = metrics["periodic_seam_validation"]
    assert chart_check["method"] == "ORIGINAL_UNMODIFIED_GENERAL_CHART_UV_AND_REGION_MASK"
    assert chart_check["sample_count"] == 25
    assert chart_check["passed"] is True
    assert chart_check["maximum_s_error_mm"] <= chart_check["maximum_allowed_s_error_mm"]
    assert seam_check["passed"] is True
    assert metrics["grid_sampling"].startswith("CELL_CENTERED_UNIFORM_FINITE_POLYLINE_ARCLENGTH")
    assert texture["outer_texture_linear_rgb"].shape == (64, 128, 3)


def test_met_photo_panel_uses_one_surface_field_for_faces_and_continuous_texture(
        tmp_path: Path) -> None:
    from synlab.integrations.reference_generator import (
        BLUEWHITE_PANEL_STYLE,
        write_reference_instance,
    )

    instance = compose_reference_instance(
        DAILY_FINAL,
        "historical_met_50899_porcelain_clear_underglaze",
        BLUEWHITE_PANEL_STYLE,
        {"material": 9301, "pattern": 9302},
        {"pattern": {"n_s": 80, "n_theta": 256}},
    )
    assert instance.pattern_recipe is None
    assert instance.pigment_panel is not None
    assert instance.recipe["pattern"]["family_id"] is None
    assert instance.recipe["pattern"]["field_family_id"].startswith("met_50899_photo_projection")
    assert instance.recipe["pattern"]["source_field"]["source_mask_sha256"] == (
        "bc166ca1adf15907f8049f39e81a8cfe75486818e231a2d4b998c49797782da5")
    assert instance.metrics["geometry_unchanged"] is True
    assert instance.metrics["pattern_roughness_unchanged"] is True
    assert instance.metrics["pattern_ior_unchanged"] is True
    assert instance.pigment_panel.receipt["panel"]["tiling_or_repetition"] is False

    tags = instance.fields["face_surface_tag"]
    outer = tags == 0
    non_outer = ~outer
    density = instance.fields["face_pigment_density"]
    assert np.all(density[non_outer] == 0.0)
    assert set(tags[instance.fields["pattern_region"].astype(bool)]) == {0}
    assert np.array_equal(
        instance.fields["combined_albedo_linear_rgb"][non_outer],
        instance.fields["material_albedo_linear_rgb"][non_outer])
    assert np.array_equal(instance.fields["combined_roughness"],
                          instance.fields["material_roughness"])

    outer_chart = instance.mother.chart_for_tag(0)
    selected = np.flatnonzero(outer)[::max(1, np.count_nonzero(outer) // 19)][:19]
    centers = instance.fields["face_centers_mm"][selected]
    uv = outer_chart.uv(centers)
    theta = np.mod(np.arctan2(centers[:, 1], centers[:, 0]), 2.0 * np.pi)
    expected_face_density = instance.pigment_panel.sample_density(
        uv[:, 1], theta, component="total")
    assert np.allclose(density[selected], expected_face_density, atol=2e-7, rtol=0.0)

    texture = sample_outer_wall_texture(instance, n_theta=128, n_s=64)
    s_grid, theta_grid = np.meshgrid(texture["s_centers_mm"],
                                     texture["theta_centers_rad"], indexing="ij")
    expected_texture_density = instance.pigment_panel.sample_density(
        s_grid, theta_grid, component="total")
    assert np.allclose(texture["outer_pigment_density"], expected_texture_density,
                       atol=1e-7, rtol=0.0)
    assert texture["metrics"]["general_chart_validation"]["passed"] is True
    assert texture["metrics"]["periodic_seam_validation"]["passed"] is True

    bundle = tmp_path / "photo-panel"
    write_reference_instance(instance, bundle)
    assert (bundle / "bluewhite_panel_fields.npz").is_file()
    panel_receipt = json.loads((bundle / "bluewhite_panel_receipt.json").read_text(
        encoding="utf-8"))
    assert panel_receipt["schema"] == "synlab.patterns.bluewhite_panel_receipt.v2"
    with np.load(bundle / "bluewhite_panel_fields.npz", allow_pickle=False) as arrays:
        assert np.array_equal(arrays["total_density"], instance.pigment_panel.total_density)
    with np.load(bundle / "geometry_and_fields.npz", allow_pickle=False) as arrays:
        assert np.array_equal(arrays["face_pigment_density"], density)
    sha_receipt = json.loads((bundle / "sha256_receipt.json").read_text(encoding="utf-8"))
    assert "bluewhite_panel_fields.npz" in sha_receipt["file_sha256"]
    assert "bluewhite_panel_receipt.json" in sha_receipt["file_sha256"]


def test_source_resolved_mode_is_explicit_replayable_and_accepts_bounded_texture_shape(
        tmp_path: Path) -> None:
    from synlab.integrations.reference_generator import (
        BLUEWHITE_PANEL_STYLE,
        sample_outer_wall_texture,
        validate_bluewhite_panel_controls,
        write_reference_instance,
    )
    from synlab.patterns.bluewhite_panel import SOURCE_RESOLVED_STATIONARY_SAMPLING

    controls = {
        "continuous_sampling_mode": SOURCE_RESOLVED_STATIONARY_SAMPLING,
        "duration": 0.0,
        "n_s": 64,
        "n_theta": 128,
    }
    resolved = validate_bluewhite_panel_controls(controls)
    assert resolved["continuous_sampling_mode"] == SOURCE_RESOLVED_STATIONARY_SAMPLING
    with pytest.raises(SynLabError, match="continuous_sampling_mode"):
        validate_bluewhite_panel_controls({"continuous_sampling_mode": "source_blur"})

    instance = compose_reference_instance(
        DAILY_FINAL, "historical_met_50899_porcelain_clear_underglaze",
        BLUEWHITE_PANEL_STYLE, {"material": 1601, "pattern": 1602},
        {"pattern": controls},
    )
    assert instance.pigment_panel is not None
    assert instance.recipe["pattern"]["mapping_and_spread_controls"][
        "continuous_sampling_mode"] == SOURCE_RESOLVED_STATIONARY_SAMPLING
    assert instance.pigment_panel.receipt["appearance_controls"][
        "continuous_sampling_mode"] == SOURCE_RESOLVED_STATIONARY_SAMPLING
    texture = sample_outer_wall_texture(instance, n_theta=160, n_s=80)
    assert texture["outer_texture_linear_rgb"].shape == (80, 160, 3)
    assert texture["metrics"]["grid_shape_s_theta"] == [80, 160]
    assert texture["metrics"]["texture_output_preflight_upper_bound_bytes"] < 64 * 1024 * 1024
    with pytest.raises(SynLabError, match="bounded sampling limits"):
        sample_outer_wall_texture(instance, n_theta=4096, n_s=2048)

    output = tmp_path / "source-resolved-panel"
    write_reference_instance(instance, output, texture=texture)
    with np.load(output / "appearance_texture.npz", allow_pickle=False) as arrays:
        assert arrays["outer_texture_linear_rgb"].shape == (80, 160, 3)
    with np.load(output / "bluewhite_panel_fields.npz", allow_pickle=False) as arrays:
        assert arrays["normalized_source_density"].shape == (1160, 2000)
        assert arrays["normalized_source_density"].dtype == instance.pigment_panel.source_density.dtype
        np.testing.assert_array_equal(arrays["normalized_source_density"],
                                      instance.pigment_panel.source_density)
    receipt = json.loads((output / "bluewhite_panel_receipt.json").read_text(
        encoding="utf-8"))
    assert receipt["mass_accounting"]["scope"] == "DISCRETE_GRID_MASS_ONLY"


def test_bluewhite_compatibility_uses_material_class_and_keeps_legacy_instance_constructor() -> None:
    from synlab.integrations.reference_generator import (
        BLUEWHITE_PANEL_STYLE,
        ReferenceInstance,
        validate_bluewhite_material_compatibility,
    )

    # This stoneware profile carries no named cobalt-decoration source fact. Its ceramic
    # substrate class is still sufficient for the explicitly separate appearance route.
    material = reference_material("historical_met_jun_stoneware_glaze", seed=5)
    process = material["source_conditioned"]["process_compatibility"]
    assert "source_named_decoration" not in process
    compatible = validate_bluewhite_material_compatibility(material)
    assert compatible["status"] == "COMPATIBLE_SUBSTRATE_CLASS"
    assert compatible["material_class"] == "stoneware"

    for material_class in ("metal", "unclassified"):
        profile = {"source_conditioned": {"material_class": material_class}}
        with pytest.raises(SynLabError, match="known ceramic substrate class"):
            validate_bluewhite_material_compatibility(profile)
    with pytest.raises(SynLabError, match="known ceramic substrate class"):
        validate_bluewhite_material_compatibility({})

    instance = compose_reference_instance(
        DAILY_FINAL,
        "historical_met_jun_stoneware_glaze",
        BLUEWHITE_PANEL_STYLE,
        {"material": 5011, "pattern": 5012},
        {"pattern": {"duration": 0.0, "n_s": 48, "n_theta": 96}},
    )
    assert instance.pigment_panel is not None
    assert instance.recipe["pattern"]["substrate_compatibility"]["status"] == (
        "COMPATIBLE_SUBSTRATE_CLASS")

    # The original positional field order remains intact for existing callers.
    legacy = ReferenceInstance(None, {}, None, {}, {}, {}, {})
    assert legacy.pigment_panel is None


def test_bluewhite_panel_replay_source_hash_and_controls_fail_closed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import synlab.integrations.reference_generator as generator

    arguments = (
        DAILY_FINAL,
        "historical_met_50899_porcelain_clear_underglaze",
        generator.BLUEWHITE_PANEL_STYLE,
        {"material": 441, "pattern": 442},
    )
    controls = {"pattern": {"n_s": 64, "n_theta": 128}}
    left = compose_reference_instance(*arguments, controls)
    right = compose_reference_instance(*arguments, controls)
    assert left.recipe == right.recipe
    assert left.provenance == right.provenance
    for name in left.fields:
        assert np.array_equal(left.fields[name], right.fields[name]), name
    assert np.array_equal(left.pigment_panel.total_density, right.pigment_panel.total_density)

    with pytest.raises(SynLabError, match="unsupported blue-white panel controls"):
        compose_reference_instance(*arguments, {"pattern": {"icon_scale": 2.0}})
    with pytest.raises(SynLabError, match="unsupported blue-white panel controls"):
        compose_reference_instance(*arguments, {
            "pattern": {"glaze_white_linear_rgb": [0.9, 0.9, 0.9]}})

    changed = tmp_path / "changed-mask.png"
    changed.write_bytes(generator.BLUEWHITE_SOURCE_MASK_PATH.read_bytes() + b"changed")
    monkeypatch.setattr(generator, "BLUEWHITE_SOURCE_MASK_PATH", changed)
    with pytest.raises(SynLabError, match="source mask hash mismatch"):
        compose_reference_instance(*arguments, controls)


def test_recipe_cli_accepts_bounded_variable_counts_and_rejects_unknown_keys() -> None:
    from experiments.continuation_20261015.reference_generation.run_generation import (
        _validate_recipe,
    )

    item = {
        "name": "panel_check",
        "design": {"model": "FootedBowlDesign", "overrides": {"name": "panel_check"}},
        "material": {"style_id": "historical_met_jun_stoneware_glaze",
                     "controls": {}},
        "pattern": {"style_id": "met_50899_partial_dragon_panel",
                    "controls": {"duration": 0.0, "n_s": 32, "n_theta": 96}},
        "seeds": {"material": 1, "pattern": 2},
    }
    recipe = {
        "schema": "synlab.footed_bowl_reference_generation_recipe.v2",
        "recipe_id": "one_panel_test",
        "family": "footed_bowl",
        "geometry": {"preset": "daily", "design_model": "FootedBowlDesign"},
        "instances": [item],
    }
    _validate_recipe(recipe)
    two = json.loads(json.dumps(recipe))
    second = json.loads(json.dumps(item))
    second["name"] = "panel_check_two"
    two["instances"].append(second)
    _validate_recipe(two)
    eight = json.loads(json.dumps(recipe))
    for index in range(2, 9):
        variant = json.loads(json.dumps(item))
        variant["name"] = f"panel_check_{index + 1}"
        eight["instances"].append(variant)
    _validate_recipe(eight)
    zero = json.loads(json.dumps(recipe))
    zero["instances"] = []
    with pytest.raises(ValueError, match="between one and eight"):
        _validate_recipe(zero)
    nine = json.loads(json.dumps(eight))
    extra = json.loads(json.dumps(item))
    extra["name"] = "panel_check_nine"
    nine["instances"].append(extra)
    with pytest.raises(ValueError, match="between one and eight"):
        _validate_recipe(nine)
    unknown = json.loads(json.dumps(recipe))
    unknown["ignored_recipe_flag"] = True
    with pytest.raises(ValueError, match="unsupported keys"):
        _validate_recipe(unknown)


def test_replay_resolves_identical_recipe_and_fields_and_style_keeps_explicit_override() -> None:
    args = (DAILY_FULL_BELLY, "historical_met_jun_stoneware_glaze",
            "daily_hasami_tokusa", {"material": 99, "pattern": 100})
    controls = {"material": {"coating_roughness": 0.27},
                "pattern": {"line_width_mm": 2.0, "spacing_mm": 13.0}}
    left = compose_reference_instance(*args, controls)
    right = compose_reference_instance(*args, controls)
    assert left.recipe == right.recipe
    assert left.provenance == right.provenance
    assert left.metrics == right.metrics
    for key in left.fields:
        assert np.array_equal(left.fields[key], right.fields[key]), key
    assert left.pattern_recipe.params["line_width_mm"] == pytest.approx(2.0)
    assert left.material_profile["source_conditioned"]["controls"][
        "coating_roughness"]["value"] == pytest.approx(0.27)


def test_unrecognized_controls_and_tampered_source_lineage_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(SynLabError, match="unknown composition control groups"):
        compose_reference_instance(DAILY_FINAL, "daily_aberdeen_porcelain_celadon",
                                   "daily_hasami_tokusa", 3, {"geometry": {"height": 60}})

    copied = tmp_path / "candidate"
    shutil.copytree(DAILY_FINAL, copied)
    lineage_path = copied / "geometry" / "face_lineage.json"
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    lineage["faces"]["1"]["role"] = "body_outer"
    lineage_path.write_text(json.dumps(lineage), encoding="utf-8")
    with pytest.raises(SynLabError, match="source hash mismatch for face_lineage.json"):
        load_reference_mother(copied)


def test_recipe_output_contains_geometry_and_per_face_fields(tmp_path: Path) -> None:
    from synlab.integrations.reference_generator import write_reference_instance

    instance = compose_reference_instance(
        DAILY_FINAL,
        "historical_met_jun_stoneware_glaze",
        "historical_met_jun_plain",
        {"material": 7, "pattern": 8},
    )
    written = write_reference_instance(instance, tmp_path / "instance")
    output = tmp_path / "instance"
    with np.load(output / "geometry_and_fields.npz", allow_pickle=False) as arrays:
        assert arrays["vertices_mm"].shape == instance.mother.mesh.vertices.shape
        assert arrays["faces"].shape == instance.mother.mesh.faces.shape
        assert np.array_equal(arrays["face_combined_albedo_linear_rgb"],
                              instance.fields["combined_albedo_linear_rgb"])
        assert np.array_equal(arrays["face_source_brep_face_index"],
                              instance.fields["source_brep_face_index"])
        assert np.array_equal(arrays["face_display_normal_group"],
                              instance.fields["display_normal_group"])
        source_profile = instance.mother.chart_for_tag(0).meta["arrays"]["profile_rzs"]
        assert np.array_equal(arrays["outer_profile_rz_mm"], source_profile[:, :2])
    assert (output / "recipe.json").is_file()
    assert (output / "provenance.json").is_file()
    assert (output / "sha256_receipt.json").is_file()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["geometry_array_sha256"] == instance.metrics["geometry_array_sha256_after"]
    assert manifest["training_export"] == "NONE"
    assert written["files"]["geometry_and_fields.npz"] == hashlib.sha256(
        (output / "geometry_and_fields.npz").read_bytes()).hexdigest()
    receipt = json.loads((output / "sha256_receipt.json").read_text(encoding="utf-8"))
    assert receipt["geometry_array_sha256"] == manifest["geometry_array_sha256"]
    assert receipt["canonical_recipe_sha256"] == manifest["canonical_recipe_sha256"]
    assert receipt["file_sha256"]["recipe.json"] == hashlib.sha256(
        (output / "recipe.json").read_bytes()).hexdigest()
    assert manifest["file_sha256"]["sha256_receipt.json"] == hashlib.sha256(
        (output / "sha256_receipt.json").read_bytes()).hexdigest()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_reference_instance(instance, output)
