from __future__ import annotations

import numpy as np
import pytest

from synlab.errors import SynLabError
from synlab.patterns.api import audit_pattern, evaluate
from synlab.patterns.charts import resolve_frame, surface_samples
from synlab.patterns.reference_styles import (
    GENERATION_MODE,
    build_reference_pattern,
    list_reference_styles,
    reference_style_record,
    sample_reference_style,
)
from synlab.patterns.serialize import (
    recipe_from_dict,
    recipe_hash,
    recipe_to_dict,
    resource_hash,
)
from synlab.seeds import make_rng


TOKUSA = "daily_hasami_tokusa"
JUN = "historical_met_jun_plain"
HACILAR = "research_met_hacilar_chevron"


def _outer_face_centres(mother):
    faces = np.asarray(mother.mesh.faces, dtype=np.int64)
    tags = np.asarray(mother.face_surface_tag, dtype=np.int64)
    outer = next(index for index, name in mother.surface_tag_names.items()
                 if name == "outer_wall")
    return np.asarray(mother.mesh.triangles_center)[tags == int(outer)], int(outer)


def test_reference_catalog_separates_buildable_and_research_records():
    buildable = {item["style_id"] for item in list_reference_styles()}
    all_records = {item["style_id"] for item in list_reference_styles(include_research=True)}
    assert buildable == {TOKUSA, JUN}
    assert all_records == {TOKUSA, JUN, HACILAR}
    assert reference_style_record(HACILAR)["render_status"] == "RESEARCH_ONLY_NOT_BUILDABLE"


@pytest.mark.parametrize(
    ("style_id", "family", "palette_id"),
    [(TOKUSA, "PAT03", "reference_tokusa_sandy_rust_proxy"),
     (JUN, "PAT01", "reference_jun_bluegrey_proxy")],
)
def test_build_returns_standard_recipe_and_is_deterministic(
        small_mother, style_id, family, palette_id):
    first = build_reference_pattern(small_mother, style_id, 9142)
    second = build_reference_pattern(small_mother, style_id, 9142)
    assert first.family_id == family
    assert first.meta["palette_id"] == palette_id
    assert first.meta["regions"][0]["surface_tag"] == "outer_wall"
    assert first.meta["reference_style"]["generation_mode"] == GENERATION_MODE
    assert first.meta["reference_style"]["distribution_claim"].startswith("none;")
    assert first.meta["recipe_hash"] == recipe_hash(first) == recipe_hash(second)
    assert first.resource_hash == resource_hash(
        [{"kind": "NONE", "detail": "family has no external resource"}], first.params)
    assert recipe_to_dict(first)["recipe_hash"] == recipe_to_dict(second)["recipe_hash"]


def test_tokusa_is_longitudinal_stripe_process_not_generic_horizontal_bands(small_mother):
    recipe = build_reference_pattern(small_mother, TOKUSA, 71)
    assert recipe.family_id == "PAT03"
    assert recipe.params["groups"][0]["theta_deg"] == 0.0
    assert recipe.params["groups"][0]["n_int"] > 1
    assert recipe.params["n_groups"] == 1
    assert recipe.meta["reference_style"]["mapping"]["surface_tag"] == "outer_wall"
    assert recipe.meta["reference_style"]["palette_status"] == \
        "SOURCE_DESCRIPTION_GUIDED_UNCALIBRATED_DESIGN_PROXY"
    assert recipe.meta["aux_layers"] == []


def test_plain_jun_is_unpatterned_and_uses_proxy_body_color(small_mother):
    recipe = build_reference_pattern(small_mother, JUN, 73)
    points, tag = _outer_face_centres(small_mother)
    channels = evaluate(recipe, small_mother, points, tag)
    assert recipe.family_id == "PAT01"
    assert recipe.params["plain"] is True
    assert recipe.params["basis"] is None
    assert recipe.meta["reference_style"]["palette_limits"].startswith("A flat blue-gray")
    assert np.allclose(channels.albedo, np.asarray(recipe.meta["palette"]["body"]), atol=1e-6)
    assert np.all(channels.height_mm == 0.0)


def test_sample_evaluates_only_the_source_surface_and_round_trips(small_mother):
    frame = resolve_frame(small_mother, "outer_wall")
    points, _ = surface_samples(small_mother, 1600,
                                make_rng(12, "reference-style-samples"), tag=frame.tag)
    recipe, channels = sample_reference_style(
        small_mother, TOKUSA, points, "outer_wall", seed=12)
    assert channels.pattern_region.sum() > 0
    assert np.all(channels.height_mm == 0.0)
    restored = recipe_from_dict(recipe_to_dict(recipe))
    replay = evaluate(restored, small_mother, points, "outer_wall")
    assert np.array_equal(channels.albedo, replay.albedo)
    assert np.array_equal(channels.pattern_region, replay.pattern_region)
    with pytest.raises(SynLabError, match="restricted to outer_wall"):
        sample_reference_style(small_mother, TOKUSA, points, "inner_wall", seed=12)


def test_overrides_stay_within_documented_design_ranges_and_cannot_migrate_process(
        small_mother):
    recipe = build_reference_pattern(
        small_mother, TOKUSA, 20,
        overrides={"line_width_mm": 1.4, "spacing_mm": 12.0, "s_margin_frac": 0.18})
    assert recipe.params["groups"][0]["width_mm"] == pytest.approx(1.4)
    assert recipe.params["spacing_requested_mm"] == pytest.approx(12.0)
    assert recipe.meta["regions"][0]["s_margin_frac"] == pytest.approx(0.18)
    for bad in ({"family": "PAT14"}, {"surface_tag": "inner_wall"},
                {"height": "engrave"}, {"spacing_mm": 2.0}):
        with pytest.raises(SynLabError):
            build_reference_pattern(small_mother, TOKUSA, 20, overrides=bad)
    with pytest.raises(SynLabError, match="research-only"):
        build_reference_pattern(small_mother, HACILAR, 20)


def test_tokusa_audit_seam_determinism_geometry_inheritance_and_no_fracture_paint(
        small_mother):
    before_vertices = np.asarray(small_mother.mesh.vertices).copy()
    before_faces = np.asarray(small_mother.mesh.faces).copy()
    recipe = build_reference_pattern(small_mother, TOKUSA, 115)
    audit = audit_pattern(recipe, small_mother, n_pairs=128,
                          scale_samples=64, geometry_probe=False)
    assert audit["pass"], audit.get("failures")
    assert audit["seam"]["chart_space"]["pass"]
    assert audit["determinism"]["pass"]
    assert audit["inheritance"]["pass"]
    points, _ = _outer_face_centres(small_mother)
    body = np.asarray(recipe.meta["palette"]["body"], dtype=np.float32)
    interface = evaluate(recipe, small_mother, points[:4], "interface")
    assert interface.meta["unpatterned_reason"] == "new_fracture_surface_exposes_body"
    assert np.allclose(interface.albedo, body, atol=1e-6)
    assert np.array_equal(np.asarray(small_mother.mesh.vertices), before_vertices)
    assert np.array_equal(np.asarray(small_mother.mesh.faces), before_faces)
