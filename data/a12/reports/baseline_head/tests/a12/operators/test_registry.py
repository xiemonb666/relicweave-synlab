"""Registration and recipe-compilation contract of the 31 degradation axes (plan 15.1, 30.2)."""

from __future__ import annotations

import pytest

from synlab.config import DagNode, compile_recipe as config_compile_recipe, sort_nodes
from synlab.degrade.api import compile_recipe
from synlab.degrade.registry import AXIS_REGISTRY, FACTOR_KINDS
from synlab.errors import SynLabError
from synlab.schemas.spec import (
    AXIS_IDS,
    STAGE_ORDER,
    SUBSTAGE_ORDER,
    DegradationOperatorSpec,
    DegradationRecipeSpec,
)

from conftest import ALL_AXES


def test_all_31_axes_are_registered() -> None:
    assert len(AXIS_IDS) == 31
    assert AXIS_REGISTRY.missing() == []
    assert sorted(AXIS_REGISTRY.ids()) == sorted(AXIS_IDS)
    assert set(ALL_AXES) == set(AXIS_IDS)


@pytest.mark.parametrize("axis_id", ALL_AXES)
def test_axis_declaration_is_complete(axis_id: str) -> None:
    operator = AXIS_REGISTRY.get(axis_id)
    declared = operator.declared()
    assert declared["axis_id"] == axis_id
    assert declared["stage"] in STAGE_ORDER
    assert declared["substage"] in SUBSTAGE_ORDER
    assert declared["default_variant"]
    assert declared["variants"], "an axis must register at least its default variant"
    for variant, kind in declared["factor_kinds"].items():
        assert kind in FACTOR_KINDS, f"{axis_id}/{variant}: bad factor kind {kind}"
    assert len(operator.levels()) == 5
    for level in operator.levels():
        params = operator.level_parameters(level)
        assert isinstance(params, dict)
    assert operator.level_parameters(0) != {} or axis_id.startswith("I06"), (
        "level 0 must still declare the level-0 parameters")
    assert operator.NOTES, "every axis documents its level semantics and limits"
    assert declared["reads"] and declared["writes"]
    assert all(r.startswith("source:") for r in declared["reads"]
               if ":" not in r.split("source:", 1)[-1] or True)


def test_physical_axes_declare_their_label_invalidations() -> None:
    for axis_id in [f"P{i:02d}" for i in range(1, 9)]:
        operator = AXIS_REGISTRY.get(axis_id)
        assert "PhysicalTruth" in operator.LABEL_INVALIDATIONS, axis_id
        assert "VisibleLabels" in operator.LABEL_INVALIDATIONS, axis_id
    # observation-side axes must invalidate the visible labels / feature adapter
    for axis_id in ("G01", "G08", "I01", "X01"):
        assert AXIS_REGISTRY.get(axis_id).LABEL_INVALIDATIONS, axis_id


def _spec(operators, recipe_id: str = "ops_multi") -> DegradationRecipeSpec:
    return DegradationRecipeSpec(recipe_id=recipe_id, source_role="physical",
                                 operators=operators)


def _op(axis_id: str, level: int, variant: str = "") -> DegradationOperatorSpec:
    return DegradationOperatorSpec(axis_id=axis_id,
                                   stage=AXIS_REGISTRY.get(axis_id).STAGE,
                                   level=level, variant=variant)


def test_config_compiler_accepts_a_multi_axis_recipe_and_orders_it() -> None:
    spec = _spec([_op("P03", 2), _op("I01", 1), _op("I06", 1), _op("I03", 2), _op("I09", 1),
                  _op("G05", 1), _op("G08", 2), _op("X01", 1)])
    compiled = config_compile_recipe(spec)
    assert compiled.ok, compiled.errors
    stages = [node.stage for node in compiled.nodes]
    assert stages == sorted(stages, key=lambda s: STAGE_ORDER[s])
    assert [node.operator for node in compiled.nodes][0] == "P03"
    # the DAG carries the declared reads/writes and label invalidations
    for node in compiled.nodes:
        assert node.reads and node.writes
        assert node.label_invalidations is not None


def test_declared_order_inversion_is_rejected() -> None:
    """Physical damage declared after the optics axis must not be silently reordered."""
    spec = _spec([_op("I01", 2), _op("P03", 2)], recipe_id="ops_inverted")
    strict = compile_recipe(spec)
    assert not strict.ok
    assert any("ILLEGAL_STAGE_ORDER" in err for err in strict.errors), strict.errors


def test_stage_mismatch_is_rejected_by_the_config_compiler() -> None:
    spec = _spec([DegradationOperatorSpec(axis_id="G08", stage="PHYSICAL", level=2)])
    compiled = config_compile_recipe(spec)
    assert not compiled.ok
    assert any("stage mismatch" in err for err in compiled.errors), compiled.errors


def test_sort_nodes_rejects_a_read_before_write_inversion() -> None:
    producer = DagNode(node_id="n00_P03", operator="P03", variant="smooth_recession_field",
                       stage="PHYSICAL", substage="surface", level=2,
                       reads=["source:asset"], writes=["physical:damage", "asset"],
                       parameters={}, label_invalidations=[], allowed_profile=["PHONE_RGB"])
    consumer = DagNode(node_id="n01_G08", operator="G08", variant="bump", stage="GEOMETRY_OBS",
                       substage="surface", level=2, reads=["physical:damage"],
                       writes=["geometry:observed"], parameters={}, label_invalidations=[],
                       allowed_profile=["PHONE_RGB"])
    with pytest.raises(SynLabError) as excinfo:
        sort_nodes([consumer])
    assert "illegal stage order" in str(excinfo.value)
    # providing the producer makes the same read legal
    assert [n.node_id for n in sort_nodes([producer, consumer])] == ["n00_P03", "n01_G08"]


def test_contradictory_duplicate_axis_is_flagged() -> None:
    spec = _spec([_op("P03", 1), _op("P03", 3)], recipe_id="ops_duplicate")
    compiled = compile_recipe(spec)
    assert any("CONTRADICTORY_DUPLICATE_AXIS" in warning for warning in compiled.warnings)


def test_alias_variants_resolve_for_the_shipped_recipes() -> None:
    """The recipe YAMLs in ``configs/a12/degrade_recipes`` use aliases that must resolve."""
    assert AXIS_REGISTRY.get("P02").resolve_variant("subtractive_edge_rounding") == "sdf_fillet"
    assert AXIS_REGISTRY.get("P03").resolve_variant("depth_mm") == "smooth_recession_field"
    assert AXIS_REGISTRY.get("G08").resolve_variant("compact_bump") == "bump"
    assert AXIS_REGISTRY.get("I01").resolve_variant("gaussian_psf") == "gaussian_psf"
    with pytest.raises(SynLabError):
        AXIS_REGISTRY.get("P01").resolve_variant("not_a_variant")
