"""Reference-bound ceramic recipes and their source/evidence boundary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - direct execution guard
    sys.path.insert(0, str(REPO_ROOT))

from synlab.errors import ErrorCode, SynLabError  # noqa: E402
from synlab.materials.api import (  # noqa: E402
    build_material_profile,
    commit_material,
    load_material,
    material_at,
)
from synlab.materials.fields import (  # noqa: E402
    _hash_ids,
    _hash_ids_v2,
    _lattice_values,
    field_stack,
    value_noise,
)
from synlab.materials.reference_materials import (  # noqa: E402
    list_reference_materials,
    process_compatibility,
    reference_material,
    sample_reference_material,
)
from synlab.storage.store import AssetStore  # noqa: E402


def test_source_styles_are_bound_to_primary_object_records():
    rows = {row["style_id"]: row for row in list_reference_materials()}
    assert set(rows) == {
        "daily_aberdeen_porcelain_celadon",
        "historical_met_50899_porcelain_clear_underglaze",
        "historical_met_jun_stoneware_glaze",
        "historical_smithsonian_colonoware_unglazed",
    }
    aberdeen = rows["daily_aberdeen_porcelain_celadon"]
    assert aberdeen["source_id"] == "aberdeen_ABDMS095708.121"
    assert "emuseum.aberdeencity.gov.uk" in aberdeen["source_url"]
    assert {fact["field"] for fact in aberdeen["source_material_facts"]} >= {
        "medium", "maker", "height_mm", "overall_diameter_mm", "foot_ring_diameter_mm",
    }
    assert aberdeen["optical_measurements"] == "UNKNOWN"
    assert aberdeen["mechanics"] == "UNKNOWN"


def test_met_50899_recipe_keeps_source_facts_separate_from_clear_glaze_proxy():
    style_id = "historical_met_50899_porcelain_clear_underglaze"
    row = {item["style_id"]: item for item in list_reference_materials()}[style_id]
    assert row["material_id"] == "M04"
    assert row["material_class"] == "porcelain"
    assert row["source_id"] == "met_29.149.50"
    assert row["source_url"] == "https://www.metmuseum.org/art/collection/search/50899"
    facts = {fact["field"]: fact["value"] for fact in row["source_material_facts"]}
    assert facts["accession_number"] == "29.149.50"
    assert facts["height_mm"] == 184
    assert facts["medium"] == \
        "Porcelain painted in underglaze cobalt blue (Jingdezhen ware)"
    assert facts["object_image_rights"] == "Public Domain"
    assert "diameter_mm" not in facts and "overall_diameter_mm" not in facts

    profile = reference_material(style_id, seed=1905)
    source = profile["source_conditioned"]
    assert profile["material_id"] == "M04"
    assert source["source_object"]["object_id"] == "50899"
    assert source["source_object"]["accession_number"] == "29.149.50"
    assert source["optical_measurements_status"] == "UNKNOWN"
    assert source["mechanics_status"] == "UNKNOWN"
    assert profile["mechanics"]["status"] == "UNKNOWN"
    assert source["controls"]["coating_present"]["status"] == "DESIGN_CHOICE"
    assert source["controls"]["physical_glaze_thickness_mm"]["status"] == "UNKNOWN"
    assert all(value["status"] == "DESIGN_CHOICE"
               for key, value in source["controls"].items()
               if key not in ("coating_present", "physical_glaze_thickness_mm"))
    assert profile["layers"][0]["name"] == "clear_glaze_appearance_proxy"
    assert source["layer_semantics"]["mode"] == "SHADING_LAYER"
    assert source["layer_semantics"]["physical_solid_status"] == "NOT_CREATED"
    assert source["layer_semantics"]["physical_thickness_status"] == "UNKNOWN"

    process = source["process_compatibility"]["source_named_decoration"]
    assert process["process"] == "underglaze_cobalt"
    assert process["status"] == "SOURCE_FACT"
    assert process["appearance_composition"] == "SEPARATE_FROM_SUBSTRATE_PROFILE"
    assert process["compatibility"]["status"] == "COMPATIBLE_SUBSTRATE_CLASS"
    assert process["compatibility"]["effect_scope"] == "SEPARATE_APPEARANCE_LAYER"

    # Height is source metadata; no radial extent is fabricated to place a vase mesh.
    assert profile["outer_reference"]["r_outer_mm"] is None
    assert profile["outer_reference"]["r_inner_mm"] is None
    assert profile["outer_reference"]["z_rim_mm"] == pytest.approx(184.0)
    assert "diameter" in profile["outer_reference"]["note"]


def test_met_50899_semantic_coating_is_geometry_independent_and_samples_are_finite():
    profile = reference_material("historical_met_50899_porcelain_clear_underglaze", seed=1906)
    points = np.array([
        [35.0, 0.0, 62.0],       # source-height-bounded wall sample
        [35.0, 0.0, 62.0],       # same point, inner face
        [1000.0, -500.0, 900.0], # arbitrary mesh coordinate; tags still select the layer
        [35.0, 0.0, 62.0],       # foot
        [35.0, 0.0, 62.0],       # base
        [35.0, 0.0, 62.0],       # fresh fracture
    ])
    tags = ["outer_wall", "inner_wall", "rim", "foot", "base", "new_fracture"]
    sample = sample_reference_material(profile, points, tags)
    assert sample["layer_id"] == [2, 2, 2, 1, 1, 1]
    assert sample["layer_name"] == [
        "clear_glaze_appearance_proxy", "clear_glaze_appearance_proxy",
        "clear_glaze_appearance_proxy", "body", "body", "body",
    ]
    assert sample["layer_depth_mm"] == pytest.approx([0.0] * len(tags))
    assert sample["transmission"] == pytest.approx([0.02, 0.02, 0.02, 0.0, 0.0, 0.0])
    assert set(profile["coating_surface_policy"]["coated_tags"]) == {
        "outer_wall", "inner_wall", "rim",
    }
    assert "new_fracture" in profile["coating_surface_policy"]["bare_body_tags"]
    assert all("dragon" not in str(layer).lower() and "cobalt" not in str(layer).lower()
               for layer in profile["layers"])

    # Semantic surface queries use face tags, not the profile's optional envelope metadata.
    altered_reference = {**profile, "outer_reference": {
        **profile["outer_reference"], "r_outer_mm": 99999.0, "z_rim_mm": 1.0,
    }}
    repeat = sample_reference_material(altered_reference, points, tags)
    assert repeat == sample
    for channel in ("albedo", "roughness", "transmission", "ior", "grain",
                    "porosity", "direction", "layer_depth_mm"):
        values = np.asarray(sample[channel], dtype=np.float64)
        assert np.all(np.isfinite(values)), channel
        assert np.all(values >= 0.0), channel

    again = reference_material("historical_met_50899_porcelain_clear_underglaze", seed=1906)
    assert profile["profile_hash"] == again["profile_hash"]
    assert sample_reference_material(again, points, tags) == sample


def test_reference_profile_tags_numeric_appearance_as_design_choice_and_mechanics_unknown():
    profile = reference_material("daily_aberdeen_porcelain_celadon", seed=405)
    assert profile["material_id"] == "M04"
    source = profile["source_conditioned"]
    assert source["source_object"]["object_id"] == "ABDMS095708.121"
    assert source["optical_measurements_status"] == "UNKNOWN"
    assert source["mechanics_status"] == "UNKNOWN"
    assert profile["mechanics"]["status"] == "UNKNOWN"
    assert all(value["status"] == "DESIGN_CHOICE"
               for key, value in source["controls"].items()
               if key != "coating_present" and key != "physical_glaze_thickness_mm")
    assert source["controls"]["coating_present"]["status"] == "SOURCE_FACT"
    assert source["controls"]["physical_glaze_thickness_mm"]["status"] == "UNKNOWN"
    assert source["layer_semantics"]["mode"] == "SHADING_LAYER"
    assert source["layer_semantics"]["physical_solid_status"] == "NOT_CREATED"
    assert source["layer_semantics"]["physical_thickness_status"] == "UNKNOWN"


def test_same_mother_point_changes_from_celadon_appearance_to_exposed_porcelain_body():
    profile = reference_material("daily_aberdeen_porcelain_celadon", seed=405)
    # Within the Aberdeen source envelope (D 108 mm, H 53 mm). The exact meridian is not
    # published, so this is a deterministic lower-wall query coordinate, not an image-registered
    # physical point. A radial reference would put it 24 mm below the nominal radius and choose
    # body for a 0.22 mm appearance band.
    point = np.array([[30.0, 0.0, 11.0]])
    outer = sample_reference_material(profile, point, "outer_wall")
    fracture_face = sample_reference_material(profile, point, "interface")

    assert outer["layer_id"] == [2]
    assert fracture_face["layer_id"] == [1]
    assert outer["layer_name"] == ["source_named_surface_finish"]
    assert fracture_face["layer_name"] == ["body"]
    assert not np.allclose(outer["albedo"], fracture_face["albedo"])
    assert outer["roughness"][0] == pytest.approx(0.14, abs=0.03)
    assert fracture_face["roughness"][0] == pytest.approx(0.40, abs=0.03)
    assert outer["ior"][0] == pytest.approx(1.51)
    assert fracture_face["ior"][0] == pytest.approx(1.56)
    assert outer["transmission"] == pytest.approx([0.02])
    assert fracture_face["transmission"] == pytest.approx([0.0])
    # The field itself remains mother-coordinate based; the returned grain channel includes
    # the engine's explicit fresh-fracture-face adjustment.
    assert fracture_face["grain"] == pytest.approx(
        [min(1.0, outer["grain"][0] + 0.15)])
    assert outer["porosity"] == pytest.approx(fracture_face["porosity"])
    assert outer["layer_depth_mm"] == pytest.approx([0.0])
    assert profile["coating_surface_policy"]["mode"] == "original_surface_tags"
    assert profile["outer_reference"]["mode"] == "original_surface_tags"
    again = material_at(profile, point, "outer_wall")
    assert np.allclose(outer["albedo"], again.albedo.tolist())


def test_original_ceramic_surface_tags_cover_inner_outer_rim_but_not_foot_base_or_fracture():
    profile = reference_material("daily_aberdeen_porcelain_celadon", seed=406)
    # Landmark coordinates are bounded by the source's measured envelope and foot diameter;
    # the catalogue does not provide a complete section or mesh registration.
    points = np.array([
        [30.0, 0.0, 11.0],  # lower outer wall inside source D/H envelope
        [28.0, 0.0, 27.0],  # inner wall
        [54.0, 0.0, 53.0],  # rim envelope
        [15.5, 0.0, 0.0],   # foot-ring radius from source record
        [0.0, 0.0, 3.0],    # base
        [30.0, 0.0, 11.0],  # fracture at the same mother coordinate as outer wall
    ])
    tags = ["outer_wall", "inner_wall", "rim", "foot", "base", "interface"]
    sample = sample_reference_material(profile, points, tags)
    assert sample["layer_id"] == [2, 2, 2, 1, 1, 1]
    assert sample["layer_depth_mm"] == pytest.approx([0.0] * len(tags))
    assert sample["transmission"] == pytest.approx([0.02, 0.02, 0.02, 0.0, 0.0, 0.0])
    assert sample["ior"][:3] == pytest.approx([1.51] * 3)
    assert sample["ior"][3:] == pytest.approx([1.56] * 3)
    assert not np.allclose(sample["albedo"][0], sample["albedo"][-1])


def test_volume_sampling_requires_explicit_depth_and_does_not_claim_solid_glaze():
    profile = reference_material("daily_aberdeen_porcelain_celadon", seed=407)
    points = np.array([[30.0, 0.0, 11.0], [30.0, 0.0, 11.0]])
    with pytest.raises(SynLabError, match="explicit depth_mm"):
        sample_reference_material(profile, points, "volume")
    volume = sample_reference_material(profile, points, "volume", depth_mm=[0.0, 0.30])
    assert volume["layer_id"] == [2, 1]
    assert volume["layer_depth_mm"] == pytest.approx([0.0, 0.30])
    with pytest.raises(SynLabError, match="only for explicit volume-tag"):
        sample_reference_material(profile, points[:1], "outer_wall", depth_mm=0.1)
    with pytest.raises(SynLabError, match="non-negative"):
        sample_reference_material(profile, points[:1], "volume", depth_mm=-0.1)
    with pytest.raises(SynLabError, match="unsupported semantic surface tags"):
        sample_reference_material(profile, points[:1], "unclassified_face")
    semantics = profile["source_conditioned"]["layer_semantics"]
    assert semantics["physical_solid_status"] == "NOT_CREATED"
    assert semantics["physical_thickness_status"] == "UNKNOWN"
    assert semantics["depth_band_parameter"] == \
        "DESIGN_CHOICE_FOR_EXPLICIT_VOLUME_QUERY_ONLY"


def test_glazed_stoneware_and_unglazed_earthenware_have_distinct_source_conditioned_profiles():
    glazed = reference_material("historical_met_jun_stoneware_glaze", seed=9)
    unglazed = reference_material("historical_smithsonian_colonoware_unglazed", seed=9)
    point = np.array([[50.0, 0.0, 40.0]])

    jun_outer = sample_reference_material(glazed, point, "outer_wall")
    colonoware_outer = sample_reference_material(unglazed, point, "outer_wall")
    assert jun_outer["layer_id"] == [2]
    assert colonoware_outer["layer_id"] == [1]
    assert jun_outer["transmission"] == [0.0]
    assert colonoware_outer["transmission"] == [0.0]
    assert not np.allclose(jun_outer["albedo"], colonoware_outer["albedo"])
    assert glazed["source_conditioned"]["source_object"]["facts"][0]["value"].startswith("Stoneware")
    unglazed_facts = {fact["field"]: fact["value"]
                      for fact in unglazed["source_conditioned"]["source_object"]["facts"]}
    assert unglazed_facts["surface"] == "unglazed"
    assert unglazed["source_conditioned"]["material_class_evidence_status"] == \
        "DESIGN_CLASSIFICATION"
    assert unglazed["source_conditioned"]["layer_semantics"]["physical_solid_status"] == \
        "NOT_APPLICABLE_SOURCE_IS_UNGLAZED"


def test_process_compatibility_distinguishes_clay_glaze_paint_and_engraving():
    assert process_compatibility("porcelain", "ceramic_glaze_firing")["status"] == \
        "COMPATIBLE_SUBSTRATE_CLASS"
    assert process_compatibility("wood", "ceramic_glaze_firing")["status"] == \
        "INCOMPATIBLE_FOR_CLAY_BODY_GLAZE"
    assert process_compatibility("metal", "ceramic_glaze_firing")["status"] == \
        "INCOMPATIBLE_FOR_CLAY_BODY_GLAZE"
    paint = process_compatibility("stoneware", "surface_paint")
    engraving = process_compatibility("stoneware", "engrave_body")
    assert paint["effect_scope"] == "SHADING_LAYER"
    assert engraving["effect_scope"] == "GEOMETRIC_LAYER"
    assert paint["status"] != engraving["status"]
    underglaze = process_compatibility("porcelain", "underglaze_cobalt")
    assert underglaze["status"] == "COMPATIBLE_SUBSTRATE_CLASS"
    assert underglaze["effect_scope"] == "SEPARATE_APPEARANCE_LAYER"
    assert process_compatibility("metal", "underglaze_cobalt")["status"] == \
        "INCOMPATIBLE_FOR_CERAMIC_UNDERGLAZE"
    unknown = process_compatibility("porcelain", "unknown_kiln_process")
    assert unknown["status"] == "UNKNOWN"


def test_controls_change_real_material_samples_and_invalid_controls_fail_closed():
    base = reference_material("historical_met_jun_stoneware_glaze", seed=10)
    variant = reference_material("historical_met_jun_stoneware_glaze", {
        "body_albedo_linear_rgb": [0.16, 0.18, 0.20],
        "coating_albedo_linear_rgb": [0.42, 0.20, 0.10],
        "coating_roughness": 0.28,
        "coating_ior": 1.65,
        "coating_band_mm": 0.8,
    }, seed=10)
    outer_point = np.array([[30.0, 0.0, 30.0]])
    body_point = np.array([[30.0, 0.0, 30.0]])
    assert not np.allclose(sample_reference_material(base, outer_point, "outer_wall")["albedo"],
                           sample_reference_material(variant, outer_point, "outer_wall")["albedo"])
    base_rough = sample_reference_material(base, outer_point, "outer_wall")["roughness"][0]
    variant_rough = sample_reference_material(variant, outer_point, "outer_wall")["roughness"][0]
    assert variant_rough - base_rough == pytest.approx(0.12, abs=1e-5)
    assert sample_reference_material(variant, outer_point, "outer_wall")["ior"][0] == \
        pytest.approx(1.65)
    assert sample_reference_material(variant, body_point, "interface")["layer_id"] == [1]
    assert sample_reference_material(variant, body_point, "interface")["albedo"][0] == \
        pytest.approx([0.16, 0.18, 0.20], abs=0.03)

    field_variant = reference_material("historical_met_jun_stoneware_glaze", {
        "grain_scale_mm": 1.7,
        "pore_scale_mm": 7.0,
    }, seed=10)
    field_points = np.random.default_rng(8).uniform(-80.0, 80.0, size=(256, 3))
    before_field = sample_reference_material(base, field_points, "interface")
    after_field = sample_reference_material(field_variant, field_points, "interface")
    assert not np.allclose(before_field["grain"], after_field["grain"])
    assert base["stats"]["pore_scale_mm"] != field_variant["stats"]["pore_scale_mm"]
    assert len(before_field["porosity"]) == len(field_points)
    assert np.any(np.asarray(before_field["porosity"]) > 0.0)
    no_pore_contrast = reference_material("historical_met_jun_stoneware_glaze",
                                          {"pore_amount": 0.0}, seed=10)
    stronger_pore_contrast = reference_material("historical_met_jun_stoneware_glaze",
                                                {"pore_amount": 0.8}, seed=10)
    no_pore_sample = sample_reference_material(no_pore_contrast, field_points, "interface")
    stronger_pore_sample = sample_reference_material(stronger_pore_contrast, field_points,
                                                     "interface")
    pore_mask = np.asarray(before_field["porosity"]) > 0.0
    assert np.array_equal(no_pore_sample["porosity"], stronger_pore_sample["porosity"])
    assert np.any(pore_mask)
    assert not np.allclose(np.asarray(no_pore_sample["albedo"])[pore_mask],
                           np.asarray(stronger_pore_sample["albedo"])[pore_mask])

    with pytest.raises(SynLabError) as info:
        reference_material("historical_smithsonian_colonoware_unglazed",
                           {"coating_roughness": 0.2})
    assert info.value.code == ErrorCode.SCHEMA_INVALID
    with pytest.raises(SynLabError) as info:
        reference_material("daily_aberdeen_porcelain_celadon",
                           {"coating_ior": 4.0})
    assert info.value.code == ErrorCode.SCHEMA_INVALID


def test_profile_and_actual_sample_are_json_serializable_and_seeded():
    first = reference_material("daily_aberdeen_porcelain_celadon", seed=719)
    second = reference_material("daily_aberdeen_porcelain_celadon", seed=719)
    different = reference_material("daily_aberdeen_porcelain_celadon", seed=720)
    assert first["profile_hash"] == second["profile_hash"]
    assert first["profile_hash"] != different["profile_hash"]
    payload = sample_reference_material(first, np.array([[30.0, 0.0, 20.0]]), "outer_wall")
    json.dumps({"profile": first, "sample": payload}, ensure_ascii=False, allow_nan=False)


def test_reference_profile_round_trips_through_material_asset_store(tmp_path):
    profile = reference_material("daily_aberdeen_porcelain_celadon", seed=721)
    store = AssetStore(tmp_path / "store")
    record = commit_material(store, profile, lineage_id="reference-material-test", split="train")
    loaded = load_material(store, record.asset_id)
    assert loaded["profile_hash"] == profile["profile_hash"]
    assert loaded["source_conditioned"] == profile["source_conditioned"]
    point = np.array([[30.0, 0.0, 40.0]])
    before = sample_reference_material(profile, point, "outer_wall")
    after = sample_reference_material(loaded, point, "outer_wall")
    assert before == after


def test_unknown_source_style_is_rejected():
    with pytest.raises(SynLabError) as info:
        reference_material("unverified_generic_porcelain")
    assert info.value.code == ErrorCode.SCHEMA_INVALID


def test_reference_kernel_corrects_unsigned_hash_range_and_actual_pore_field_but_legacy_is_stable():
    points = np.random.default_rng(443).uniform(-40.0, 40.0, size=(2048, 3))
    legacy_default = field_stack(points, seed_salt=987, grain_scale_mm=1.0,
                                 pore_scale_mm=0.5)
    legacy_explicit = field_stack(points, seed_salt=987, grain_scale_mm=1.0,
                                  pore_scale_mm=0.5, kernel_version=1)
    for channel in legacy_default:
        assert np.array_equal(legacy_default[channel], legacy_explicit[channel]), channel
    lattice_points = np.random.default_rng(441).integers(-1000, 1000, size=(4096, 3),
                                                          dtype=np.int64)
    old_lattice = _lattice_values(_hash_ids(lattice_points, 987))
    new_lattice = _lattice_values(_hash_ids_v2(lattice_points, 987))
    repeat_lattice = _lattice_values(_hash_ids_v2(lattice_points, 987))
    other_seed_lattice = _lattice_values(_hash_ids_v2(lattice_points, 988))
    assert np.min(old_lattice) >= 0.0 and np.max(old_lattice) < 0.5
    assert np.min(new_lattice) >= 0.0 and np.max(new_lattice) < 1.0
    assert np.max(new_lattice) > 0.99
    assert np.median(new_lattice) == pytest.approx(0.5, abs=0.04)
    assert np.array_equal(new_lattice, repeat_lattice)
    assert not np.array_equal(new_lattice, other_seed_lattice)

    scalar_noise = value_noise(points, cell_mm=0.5, salt=987, kernel_version=2)
    assert np.min(scalar_noise) >= 0.0 and np.max(scalar_noise) <= 1.0
    assert np.min(scalar_noise) < 0.2 and np.max(scalar_noise) > 0.8
    v1 = field_stack(points, seed_salt=987, grain_scale_mm=1.0, pore_scale_mm=0.5,
                     kernel_version=1)
    v2 = field_stack(points, seed_salt=987, grain_scale_mm=1.0, pore_scale_mm=0.5,
                     kernel_version=2)
    # Signed arithmetic shifts lost one output bit: the old [0,.5) lattice range never
    # crosses the unchanged .62 pore threshold. The corrected v2 range produces a real mask.
    assert np.max(v1["porosity"]) == 0.0
    assert np.max(v2["porosity"]) > 0.0
    assert np.count_nonzero(v2["porosity"]) > 10

    legacy = build_material_profile("M04", {}, np.random.default_rng(987))
    reference = reference_material("daily_aberdeen_porcelain_celadon", seed=987)
    assert "field_kernel_version" not in legacy
    assert legacy["field_kernel"] == "value_noise+aggregate+fiber"
    assert reference["field_kernel_version"] == 2
    assert reference["field_kernel"].endswith("splitmix64-logical-u64-v2")
    old_sample = material_at(legacy, points[:16], "outer_wall")
    assert np.all(old_sample.porosity == 0.0)
    new_sample = material_at(reference, points, "interface")
    assert np.count_nonzero(new_sample.porosity) > 10


def test_reference_batch_order_and_chunking_do_not_change_any_sample_channel():
    profile = reference_material("daily_aberdeen_porcelain_celadon", seed=801)
    points = np.array([
        [30.0, 0.0, 11.0], [28.0, 0.0, 27.0], [54.0, 0.0, 53.0],
        [15.5, 0.0, 0.0], [0.0, 0.0, 3.0], [30.0, 0.0, 11.0],
    ])
    tags = np.array(["outer_wall", "inner_wall", "rim", "foot", "base", "interface"])
    whole = material_at(profile, points, tags)
    order = np.array([3, 0, 5, 2, 1, 4])
    shuffled = material_at(profile, points[order], tags[order])
    for channel in ("layer_id", "albedo", "roughness", "direction", "grain", "porosity",
                    "ior", "layer_depth_mm"):
        expected = np.asarray(getattr(whole, channel))[order]
        actual = np.asarray(getattr(shuffled, channel))
        assert np.array_equal(actual, expected), channel

    chunked = [material_at(profile, points[start:end], tags[start:end])
               for start, end in ((0, 2), (2, 5), (5, 6))]
    for channel in ("layer_id", "albedo", "roughness", "direction", "grain", "porosity",
                    "ior", "layer_depth_mm"):
        actual = np.concatenate([np.asarray(getattr(part, channel)) for part in chunked], axis=0)
        assert np.array_equal(actual, np.asarray(getattr(whole, channel))), channel
