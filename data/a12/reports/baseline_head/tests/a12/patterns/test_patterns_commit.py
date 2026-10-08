"""Asset-store round trip for recipes and channel payloads (roles, hashes, idempotency)."""

from __future__ import annotations

import numpy as np
import pytest

from synlab.errors import SynLabError
from synlab.patterns import api
from synlab.patterns.commit import load_pattern_channels
from synlab.roles import ROLE_PATTERN_CHANNELS, ROLE_PATTERN_RECIPE, SCHEMA_PATTERN
from synlab.storage.store import QA_PASS, AssetStore


@pytest.fixture()
def store(tmp_path):
    return AssetStore(tmp_path / "store")


def test_commit_and_load_recipe_round_trip(store, small_mother, recipe_factory,
                                           outer_points_factory):
    recipe = recipe_factory(small_mother, "PAT03", 2, allow_aux_layers=False)
    points = outer_points_factory(small_mother, 64)
    channels = api.evaluate(recipe, small_mother, points, "outer_wall")
    record = api.commit_pattern(store, recipe, channels, lineage_id="L001", split="train",
                                mother_id=small_mother.mother_id, qa={"seam": 0.0},
                                qa_status=QA_PASS)
    assert record.role == ROLE_PATTERN_RECIPE
    assert record.schema == SCHEMA_PATTERN
    assert record.unit == "mm"
    assert record.lineage_id == "L001"
    assert record.split == "train"
    assert record.qa_status == QA_PASS
    assert record.meta["channels_asset"]

    loaded = api.load_pattern(store, record.asset_id)
    assert loaded.family_id == recipe.family_id
    assert loaded.seed_ref == recipe.seed_ref
    assert loaded.params == recipe.params
    assert loaded.palette == recipe.palette
    assert loaded.resource_hash == recipe.resource_hash
    assert api.recipe_hash(loaded) == api.recipe_hash(recipe)

    channels_asset = record.meta["channels_asset"]
    restored = load_pattern_channels(store, channels_asset)
    assert np.array_equal(np.asarray(restored.albedo, dtype=np.float32),
                          np.asarray(channels.albedo, dtype=np.float32))
    assert np.array_equal(restored.pattern_region, channels.pattern_region)
    assert np.allclose(restored.height_mm, channels.height_mm, atol=1e-6)


def test_commit_is_idempotent(store, small_mother, recipe_factory):
    recipe = recipe_factory(small_mother, "PAT06", 1, allow_aux_layers=False)
    first = api.commit_pattern(store, recipe, None, lineage_id="L002")
    second = api.commit_pattern(store, recipe, None, lineage_id="L002")
    assert first.asset_id == second.asset_id
    assert store.count_assets(role=ROLE_PATTERN_RECIPE) == 1


def test_commit_without_channels_has_no_channel_asset(store, small_mother, recipe_factory):
    recipe = recipe_factory(small_mother, "PAT13", 1, allow_aux_layers=False)
    record = api.commit_pattern(store, recipe, None)
    assert record.meta.get("channels_asset") is None
    assert store.count_assets(role=ROLE_PATTERN_CHANNELS) == 0


def test_loading_the_wrong_role_is_a_structured_error(store, small_mother, recipe_factory,
                                                      outer_points_factory):
    recipe = recipe_factory(small_mother, "PAT02", 1, allow_aux_layers=False)
    points = outer_points_factory(small_mother, 16)
    channels = api.evaluate(recipe, small_mother, points, "outer_wall")
    record = api.commit_pattern(store, recipe, channels)
    channels_asset = record.meta["channels_asset"]
    with pytest.raises(SynLabError) as excinfo:
        api.load_pattern(store, channels_asset)
    assert excinfo.value.code == "SCHEMA_INVALID"
    with pytest.raises(SynLabError) as excinfo:
        load_pattern_channels(store, record.asset_id)
    assert excinfo.value.code == "SCHEMA_INVALID"


def test_commit_validates_its_inputs(store, small_mother):
    with pytest.raises(SynLabError):
        api.commit_pattern(store, {"not": "a recipe"}, None)
    with pytest.raises(SynLabError):
        api.commit_pattern("not a store", None, None)


def test_unknown_asset_id_is_reported(store):
    with pytest.raises(SynLabError) as excinfo:
        api.load_pattern(store, "asset_does_not_exist")
    assert excinfo.value.code == "ASSET_HASH_MISMATCH"
