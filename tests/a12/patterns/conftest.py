"""Shared fixtures for the pattern tests.

All mothers here are the analytic fixtures from :mod:`pattern_fixtures`, because
``synlab.mothers.api.create_mother`` is implemented by a different workstream.  Tests
that rely on them are named ``fixture_*`` or state it in their docstring.
"""

from __future__ import annotations

import numpy as np
import pytest

import pattern_fixtures as fx
from synlab import seeds
from synlab.patterns import api

MASTER_SEED = 20261001


@pytest.fixture(scope="session")
def small_mother():
    """Small closed lathe fixture (outer/inner cylinder charts + planar base chart)."""
    return fx.make_small_mother()


@pytest.fixture(scope="session")
def cylinder_mother():
    """Full-size fixture body with a real wall thickness of 4 mm."""
    return fx.make_cylinder_mother()


@pytest.fixture(scope="session")
def thin_wall_mother():
    """Fixture body with a 1.6 mm wall for the engraving depth guard."""
    return fx.make_thin_wall_mother()


@pytest.fixture(scope="session")
def coarse_mother():
    """Deliberately coarse fixture (few sections) for the precision-refusal path."""
    return fx.make_cylinder_mother(radius_mm=40.0, height_mm=55.0, wall_mm=4.0, base_mm=5.0,
                                   sections=24, mother_id="fixture_coarse")


@pytest.fixture()
def rng_factory():
    def make(lineage_id: str = "L001", module: str = "pattern") -> np.random.Generator:
        return seeds.make_rng(MASTER_SEED, lineage_id, module)
    return make


@pytest.fixture(scope="session")
def recipe_factory():
    """Build a frozen recipe with deterministic streams (cached per family/tier)."""
    cache: dict[tuple, object] = {}

    def make(mother, family: str, complexity: int = 1, **spec):
        key = (mother.mother_id, family, complexity, tuple(sorted(spec.items())))
        if key not in cache:
            rng = seeds.make_rng(MASTER_SEED, "recipe", family, complexity)
            payload = {"family": family, "complexity": complexity, **spec}
            cache[key] = api.build_pattern(mother, payload, rng)
        return cache[key]

    return make


@pytest.fixture(scope="session")
def outer_points_factory():
    cache: dict[tuple[str, int], np.ndarray] = {}

    def make(mother, n: int = 400, seed: int = 7) -> np.ndarray:
        key = (mother.mother_id, n)
        if key not in cache:
            cache[key] = fx.outer_points(mother, n, np.random.default_rng(seed))
        return cache[key]

    return make
