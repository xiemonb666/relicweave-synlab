"""The 16 families build, evaluate and stay inside their declared envelopes.

Every assertion here is measured on the frozen recipe and the real fixture mother; no
golden images and no fixed tiles are involved.  Documented fixture: ``small_mother`` from
``pattern_fixtures`` (``synlab.mothers.api`` is a different work package).
"""

from __future__ import annotations

import numpy as np
import pytest

from synlab import registry
from synlab.errors import SynLabError
from synlab.patterns import api
from synlab.patterns.params import FAMILY_MODELS, FAMILY_NAMES, LINE_WIDTH_RANGE, SPACING_RANGE

FAMILIES = sorted(FAMILY_MODELS)
TIERS = (1, 2, 3)


def test_registry_lists_all_16_families_with_models():
    entries = {e.id: e for e in registry.REGISTRY.list("pattern")}
    assert set(entries) == set(FAMILIES)
    for family_id, entry in entries.items():
        assert entry.param_model is FAMILY_MODELS[family_id]
        schema = entry.param_schema
        assert schema["type"] == "object"
        assert "complexity" in schema["properties"]
        assert entry.applicable["complexity_tiers"] == [1, 2, 3]
        assert entry.status in ("IMPLEMENTED", "QA_PASSED")
        assert entry.name == FAMILY_NAMES[family_id]


@pytest.mark.parametrize("family_id", FAMILIES)
def test_registry_builder_resolves_and_builds(family_id, small_mother, rng_factory):
    builder = registry.REGISTRY.resolve_builder("pattern", family_id)
    recipe = builder(small_mother, {"complexity": 1}, rng_factory("registry", family_id))
    assert recipe.family_id == family_id


@pytest.mark.parametrize("family_id", FAMILIES)
@pytest.mark.parametrize("tier", TIERS)
def test_family_builds_and_evaluates_channels(family_id, tier, small_mother, recipe_factory,
                                              outer_points_factory):
    recipe = recipe_factory(small_mother, family_id, tier, allow_aux_layers=False)
    # recipe contract: family / palette / regions / bands / warp / height / hash / version
    assert recipe.family_id == family_id
    assert recipe.version
    assert len(recipe.palette) >= 2
    assert recipe.channels == ("albedo", "roughness", "height_mm", "pattern_region")
    assert recipe.resource_hash.startswith("sha256:")
    meta = recipe.meta
    assert meta["recipe_hash"] == api.recipe_hash(recipe)
    region = meta["regions"][0]
    assert region["s_max_mm"] > region["s_min_mm"]
    assert meta["chart"]["x_period_mm"] > 0
    assert "height" in meta and meta["height"]["mode"] in ("none", "relief", "engrave")
    assert meta["warp"]["enabled"] in (False, True)
    assert isinstance(meta["bands"], dict)
    if recipe.params.get("plain"):
        # a genuinely plain recipe: no motif is invented and the measurement says so
        assert meta["spectrum"]["status"] in ("FLAT_FIELD", "OK")
        assert not meta["bands"]
    elif meta["bands"]:
        for key, entry in meta["bands"].items():
            assert entry["bands"], f"{key} must carry measured per-band energy"
            assert entry["field_stats"]["n"] > 0
    else:
        bands = meta["spectrum"].get("bands") or []
        assert len(bands) >= 3, "non-Fourier families report the measured FFT bands"
        assert any(b["energy_fraction"] > 0 for b in bands)
    assert meta["spectrum"]["status"] in ("OK", "FLAT_FIELD")
    assert meta["footprint_source"]
    assert meta["color_space"] == "linear_srgb_primaries"

    points = outer_points_factory(small_mother, 400)
    channels = api.evaluate(recipe, small_mother, points, region["surface_tag"])
    assert channels.albedo.shape == (points.shape[0], 3)
    assert channels.albedo.dtype == np.float32
    assert np.all(np.isfinite(channels.albedo))
    assert channels.albedo.min() >= 0.0 and channels.albedo.max() <= 1.0
    assert channels.roughness.shape == (points.shape[0],)
    assert np.all(np.isfinite(channels.roughness))
    assert channels.roughness.min() >= 0.0 and channels.roughness.max() <= 1.0
    assert channels.height_mm.shape == (points.shape[0],)
    assert np.all(np.isfinite(channels.height_mm))
    assert channels.height_mm.dtype == np.float32
    assert channels.pattern_region.dtype == np.uint8
    assert set(np.unique(channels.pattern_region)) <= {0, 1}
    assert channels.meta["rng"].startswith("NONE")
    if channels.pattern_region.any():
        covered = channels.albedo[channels.pattern_region.astype(bool)]
        assert covered.std(axis=0).max() > 0.0 or family_id == "PAT01"


@pytest.mark.parametrize("family_id", FAMILIES)
def test_tiers_change_real_parameters(family_id, small_mother, recipe_factory):
    hashes = []
    complexities = []
    for tier in TIERS:
        recipe = recipe_factory(small_mother, family_id, tier, allow_aux_layers=False)
        hashes.append(api.recipe_hash(recipe))
        complexities.append(recipe.params["complexity"])
    assert complexities == list(TIERS)
    assert len(set(hashes)) == len(TIERS), "each tier must freeze different parameters"


@pytest.mark.parametrize("family_id", FAMILIES)
def test_declared_millimetre_scale_is_inside_the_frozen_bands(family_id, small_mother,
                                                             recipe_factory):
    """Declared lengths live in the plan bands; a family-specific length is extra."""
    recipe = recipe_factory(small_mother, family_id, 1, allow_aux_layers=False)
    params = recipe.params
    line_width = float(params.get("line_width_mm", 0.0))
    if line_width and family_id != "PAT06":      # PAT06 draws dots, not lines
        assert LINE_WIDTH_RANGE[0] - 1e-9 <= line_width <= LINE_WIDTH_RANGE[1] + 1e-9
    spacing = float(params.get("spacing_requested_mm") or 0.0)
    if spacing:
        assert SPACING_RANGE[0] - 1e-9 <= spacing <= SPACING_RANGE[1] + 1e-9
    footprint = float(params["footprint_mm"])
    assert footprint > 0.0
    assert footprint <= float(params["requested_footprint_mm"]) + 1e-12
    if family_id == "PAT06":
        diameter = params["dot_diameter_requested_mm"]
        assert 0.6 <= diameter <= 12.0
        assert footprint <= 0.45 * min(params["radius_mm"],
                                       *(params["var_radius_mm"] or [params["radius_mm"]])) + 1e-9
    elif line_width:
        assert footprint <= 0.5 * 0.5 * line_width + 1e-9, "footprint must leave a line core"


def test_families_are_different_algorithms(small_mother, recipe_factory):
    """The 16 ids must be 16 algorithms: distinct frozen keys and distinct fields."""
    from synlab.patterns.api import pattern_field

    grid_x, grid_s = np.meshgrid(np.linspace(0.0, 120.0, 60), np.linspace(0.0, 28.0, 40),
                                 indexing="xy")
    keys: dict[str, tuple] = {}
    fields: dict[str, bytes] = {}
    flat: set[str] = set()
    for family_id in FAMILIES:
        recipe = recipe_factory(small_mother, family_id, 1, allow_aux_layers=False)
        values = pattern_field(recipe, grid_x.reshape(-1), grid_s.reshape(-1)).modulation
        keys[family_id] = tuple(sorted(recipe.params.keys()))
        fields[family_id] = np.round(values, 6).tobytes()
        if float(np.abs(values).max()) == 0.0:
            flat.add(family_id)
    assert len(set(keys.values())) == len(FAMILIES), "parameter schemas must differ per family"
    # PAT01 tier 1 is a genuinely plain recipe; every other family must produce a field
    assert flat <= {"PAT01"}, f"families with an all-zero field: {sorted(flat)}"
    non_zero = {f: v for f, v in fields.items() if f not in flat}
    assert len(set(non_zero.values())) == len(non_zero), "pattern fields must not be duplicates"


def test_height_channels_only_for_geometric_families(small_mother, recipe_factory,
                                                    outer_points_factory):
    points = outer_points_factory(small_mother, 300)
    for family_id in FAMILIES:
        recipe = recipe_factory(small_mother, family_id, 1, allow_aux_layers=False)
        channels = api.evaluate(recipe, small_mother, points, "outer_wall")
        if recipe.meta["height"]["mode"] == "none":
            assert np.all(channels.height_mm == 0.0)
            assert recipe.meta["appearance_only_normal_map"] is False
        else:
            assert np.abs(channels.height_mm).max() > 0.0
            assert recipe.meta["height"]["appearance_only_normal_map"] is False


def test_geometric_families_declare_geometry_before_fracture(small_mother, recipe_factory):
    for family_id in ("PAT14", "PAT15"):
        recipe = recipe_factory(small_mother, family_id, 1, allow_aux_layers=False)
        height = recipe.meta["height"]
        assert height["mode"] in ("relief", "engrave")
        assert height["amplitude_mm"] > 0.0
        assert "GEOMETRY_BEFORE_FRACTURE" in height["policy"]
        assert height["max_wall_fraction"] > 0.0
        assert recipe.meta["geometry_before_fracture"] is True


def test_unknown_family_and_bad_params_are_structured_errors(small_mother, rng_factory):
    with pytest.raises(SynLabError) as excinfo:
        api.build_pattern(small_mother, {"family": "PAT99"}, rng_factory())
    assert excinfo.value.code == "SCHEMA_INVALID"
    with pytest.raises(SynLabError):
        api.build_pattern(small_mother, {"family": "PAT03", "params": {"line_width_mm": 12.0}},
                          rng_factory())
    with pytest.raises(SynLabError):
        api.build_pattern(small_mother, {"family": "PAT03", "params": {"nonsense": 1}},
                          rng_factory())
    with pytest.raises(SynLabError) as excinfo:
        api.build_pattern(small_mother, {"family": "PAT03"}, None)
    assert excinfo.value.code == "SCHEMA_INVALID"


def test_spec_can_be_a_string_or_model(small_mother, rng_factory):
    recipe = api.build_pattern(small_mother, "PAT02", rng_factory("string-spec"))
    assert recipe.family_id == "PAT02"
    from synlab.patterns.params import PatternSpec

    spec = PatternSpec(family="PAT02", complexity=2, palette_id="celadon")
    recipe = api.build_pattern(small_mother, spec, rng_factory("model-spec"))
    assert recipe.family_id == "PAT02"
    assert recipe.params["complexity"] == 2
    assert recipe.meta["palette_id"] == "celadon"


def test_sampled_family_and_quota_classes(small_mother, rng_factory):
    seen = set()
    for index in range(24):
        recipe = api.build_pattern(small_mother, {"allow_aux_layers": False},
                                   rng_factory("sample", index))
        seen.add(recipe.family_id)
    assert len(seen) >= 6, "sampled families should cover more than a couple of ids"
    plain = api.build_pattern(small_mother, {"quota_class": "PLAIN"}, rng_factory("plain"))
    assert plain.family_id == "PAT01"
    strong = {api.build_pattern(small_mother, {"quota_class": "STRONG_REPEAT"},
                                rng_factory("strong", i)).family_id for i in range(8)}
    assert strong <= {"PAT04", "PAT07", "PAT08", "PAT09"}
