"""Determinism: the query path is a pure function of the frozen recipe.

Plan 9.6: query order, batch size and worker count must not change the field, a fragment
id must not redraw anything, and ``pattern.evaluate`` must never draw randomness.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from synlab.patterns import api

FAMILIES = ("PAT02", "PAT03", "PAT05", "PAT06", "PAT10", "PAT12", "PAT13", "PAT14")


@pytest.mark.parametrize("family_id", FAMILIES)
def test_repeat_and_batch_and_order_invariance(family_id, small_mother, recipe_factory,
                                               outer_points_factory):
    recipe = recipe_factory(small_mother, family_id, 1, allow_aux_layers=False)
    points = outer_points_factory(small_mother, 257)
    tag = recipe.meta["regions"][0]["surface_tag"]
    first = api.evaluate(recipe, small_mother, points, tag)
    second = api.evaluate(recipe, small_mother, points, tag)
    assert np.array_equal(first.albedo, second.albedo)
    assert np.array_equal(first.roughness, second.roughness)
    assert np.array_equal(first.height_mm, second.height_mm)
    assert np.array_equal(first.pattern_region, second.pattern_region)

    pieces = [api.evaluate(recipe, small_mother, points[i:i + 13], tag)
              for i in range(0, points.shape[0], 13)]
    batched = np.vstack([chunk.albedo for chunk in pieces])
    assert np.array_equal(batched, first.albedo)

    order = np.argsort(-points[:, 2])
    reordered = api.evaluate(recipe, small_mother, points[order], tag)
    assert np.array_equal(reordered.albedo, first.albedo[order])
    assert np.array_equal(reordered.pattern_region, first.pattern_region[order])


def test_evaluate_draws_no_randomness(small_mother, recipe_factory, outer_points_factory):
    recipe = recipe_factory(small_mother, "PAT03", 2, allow_aux_layers=True)
    points = outer_points_factory(small_mother, 128)
    tag = recipe.meta["regions"][0]["surface_tag"]

    legacy_before = np.random.get_state()
    python_before = random.getstate()
    recipe_hash_before = api.recipe_hash(recipe)
    api.evaluate(recipe, small_mother, points, tag)
    assert np.array_equal(legacy_before[1], np.random.get_state()[1])
    assert legacy_before[0] == np.random.get_state()[0]
    assert python_before == random.getstate()
    assert api.recipe_hash(recipe) == recipe_hash_before

    import synlab.seeds as seeds

    original_make, original_seed = seeds.make_rng, seeds.seed64

    def _boom(*args, **kwargs):
        raise AssertionError("evaluate must not call the seed helpers")

    seeds.make_rng, seeds.seed64 = _boom, _boom
    try:
        result = api.evaluate(recipe, small_mother, points, tag)
    finally:
        seeds.make_rng, seeds.seed64 = original_make, original_seed
    assert result.albedo.shape[0] == points.shape[0]


def test_fragment_identity_does_not_enter_the_field(small_mother, recipe_factory,
                                                   outer_points_factory):
    """Two 'fragments' querying the same mother see the mother's original field."""
    recipe = recipe_factory(small_mother, "PAT03", 1, allow_aux_layers=False)
    points = outer_points_factory(small_mother, 200)
    tag = recipe.meta["regions"][0]["surface_tag"]
    fragment_a = points[:100]
    fragment_b = points[100:]
    first_a = api.evaluate(recipe, small_mother, fragment_a, tag).albedo
    _ = api.evaluate(recipe, small_mother, fragment_b, tag)
    again_a = api.evaluate(recipe, small_mother, fragment_a, tag).albedo
    assert np.array_equal(first_a, again_a)
    combined = api.evaluate(recipe, small_mother, points, tag).albedo
    assert np.array_equal(np.vstack([first_a, combined[100:]]), combined)


def test_same_seed_rebuilds_the_same_recipe(small_mother, rng_factory):
    spec = {"family": "PAT05", "complexity": 2, "palette_id": "celadon"}
    first = api.build_pattern(small_mother, spec, rng_factory("rebuild"))
    second = api.build_pattern(small_mother, spec, rng_factory("rebuild"))
    assert api.recipe_hash(first) == api.recipe_hash(second)
    assert first.params == second.params
    assert first.resource_hash == second.resource_hash


def test_different_seed_gives_a_different_freeze(small_mother, rng_factory):
    spec = {"family": "PAT05", "complexity": 2, "palette_id": "celadon"}
    first = api.build_pattern(small_mother, spec, rng_factory("seed-a"))
    second = api.build_pattern(small_mother, spec, rng_factory("seed-b"))
    assert api.recipe_hash(first) != api.recipe_hash(second)


def test_audit_determinism_section(small_mother, recipe_factory):
    recipe = recipe_factory(small_mother, "PAT06", 2, allow_aux_layers=False)
    audit = api.audit_pattern(recipe, small_mother, n_pairs=64, geometry_probe=False,
                              scale_samples=0)
    section = audit["determinism"]
    for key in ("repeat_identical", "batch_invariance", "order_invariance",
                "rng_state_untouched", "frozen_params_unchanged", "no_seed_module_use",
                "fragment_id_independence"):
        assert section[key]["pass"] is True, key
    assert section["pass"] is True
