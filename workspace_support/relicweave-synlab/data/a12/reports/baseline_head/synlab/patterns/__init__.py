"""``synlab.patterns`` - the 16-family procedural ornament module (plan section 9).

Importing this package registers PAT01..PAT16 with the central registry and exposes the
frozen façade from :mod:`synlab.patterns.api`::

    from synlab import seeds
    from synlab.patterns import api

    rng = seeds.make_rng(master_seed, lineage_id, "pattern")
    recipe = api.build_pattern(mother, {"family": "PAT03", "complexity": 2}, rng)
    channels = api.evaluate(recipe, mother, points_mm, "outer_wall")
    audit = api.audit_pattern(recipe, mother, n_pairs=1000)

``evaluate`` is a pure function of the frozen recipe: it draws no randomness, so a
fragment always sees the ornament the mother had before it broke.
"""

from __future__ import annotations

from .api import (apply_pattern_geometry, audit_pattern, build_pattern, commit_pattern,
                  evaluate, load_pattern, pattern_field, recipe_from_dict, recipe_hash,
                  recipe_to_dict)
from .families import REGISTERED, register_families
from .params import FAMILY_MODELS, FAMILY_NAMES, PALETTE_IDS, PatternSpec

__all__ = [
    "build_pattern", "evaluate", "apply_pattern_geometry", "audit_pattern",
    "commit_pattern", "load_pattern", "pattern_field", "recipe_hash", "recipe_to_dict",
    "recipe_from_dict", "FAMILY_MODELS", "FAMILY_NAMES", "PALETTE_IDS", "PatternSpec",
    "REGISTERED", "register_families",
]
