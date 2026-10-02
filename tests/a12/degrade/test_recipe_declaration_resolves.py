"""S12: the two declaration gaps this task found, pinned so they cannot come back.

Both gaps were *declaration vs execution* mismatches, found by auditing all 31 axes instead of
only P03:

1. **backend routing** — ``degrade/axes.py`` declared P02/P03/P04 as narrow-band surface operators
   while ``physical.operators.run_damage`` (the route ``synlab/pipeline.py`` uses) ran a global
   voxel level set.  Fixed in ``physical/operators.py`` (``NARROWBAND_BACKEND_ROUTING = "declared"``);
   the contract tests live in ``test_axis_routing_audit.py``.
2. **recipe variant names** — 5 of the 10 declared recipes in ``configs/a12/physical_recipes.json``
   named their variant after the *parameter* the level moves (``contact_loss_target``,
   ``recession_strength``, ``retained_fraction``, ``coverage``, ``depth_mm``), which is not a
   registered variant of the axis.  ``_load_damage_recipe`` therefore raised ``SCHEMA_INVALID``
   for P01/P04/P05/P06/P07 instead of building the declared recipe.  Fixed by adding the aliases in
   ``degrade/axes.py`` — the same convention P02/P03 already used.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synlab.degrade.registry import AXIS_REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[3]
RECIPE_REGISTRY = REPO_ROOT / "configs" / "a12" / "physical_recipes.json"


def _declared_recipes() -> list[dict]:
    data = json.loads(RECIPE_REGISTRY.read_text(encoding="utf-8"))
    return list(data.get("recipes", []))


def test_the_recipe_registry_is_non_empty_and_well_formed() -> None:
    recipes = _declared_recipes()
    assert recipes, f"no declared recipe in {RECIPE_REGISTRY}"
    for recipe in recipes:
        assert recipe.get("recipe_id")
        operators = recipe.get("operators") or []
        assert operators, recipe
        assert operators[0].get("axis_id")


@pytest.mark.parametrize("recipe", _declared_recipes(), ids=lambda r: r.get("recipe_id", "?"))
def test_every_declared_recipe_variant_resolves(recipe: dict) -> None:
    """A declared variant name must resolve to a registered variant of its axis."""
    first = (recipe.get("operators") or [{}])[0]
    axis_id = str(first.get("axis_id", ""))
    variant = str(first.get("variant", "") or "")
    operator = AXIS_REGISTRY.get(axis_id)
    resolved = operator.resolve_variant(variant or None)
    assert resolved in operator.variants()
    # the declaration is either the registered name itself or a documented alias
    assert variant in ("", resolved) or operator.ALIASES.get(variant) == resolved


@pytest.mark.parametrize("recipe", _declared_recipes(), ids=lambda r: r.get("recipe_id", "?"))
def test_every_declared_recipe_builds_a_real_basis(recipe: dict, archived_body: dict,
                                                   sandbox_config: str) -> None:
    """``_load_damage_recipe`` must produce a recipe with a frozen basis, not a fallback.

    ``basis_source == "degrade.registry"`` is the contract: the recipe the pipeline applies is the
    one the axis audit exercises.  A ``FALLBACK_LEVEL_TABLE`` recipe would carry no ``basis`` and
    the P operators that read frozen decisions (P03/P07 FourierField, P04 cutter pose) could not
    run at all.
    """
    from synlab.config import load_generation_spec
    from synlab.pipeline import _load_damage_recipe

    mesh = archived_body["mesh"]
    fragment_id = archived_body["fragment_id"]
    from types import SimpleNamespace

    fragment = SimpleNamespace(mesh=mesh, fragment_id=fragment_id,
                               volume_mm3=float(abs(mesh.volume)), is_tiny=False,
                               meta={"material_id": ""})
    spec = load_generation_spec(sandbox_config)
    built = _load_damage_recipe(str(recipe["recipe_id"]), spec, fragment=fragment,
                               master_seed=spec.master_seed, lineage_id="lin_s12_recipe")
    first = (recipe.get("operators") or [{}])[0]
    assert built.axis_id == str(first.get("axis_id"))
    assert built.meta.get("basis_source") == "degrade.registry"
    assert built.basis, "the declared recipe must carry its frozen basis"
    operator = AXIS_REGISTRY.get(built.axis_id)
    assert built.variant in operator.variants()
    assert built.params, "the declared recipe must carry its level parameters"
