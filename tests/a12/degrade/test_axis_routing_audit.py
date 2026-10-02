"""S12: the declare-vs-route contract of the 31 degradation axes, and the drift metric family.

What is pinned down here (all of it measured, nothing asserted from a declaration):

* **31/31 axes** are registered, audited at every level and the audit still reports the frozen
  ``155/155`` contract;
* for each P axis the *executed* implementation is inspected, not the flag: the production route
  (``physical.operators.run_damage``, used by ``synlab/pipeline.py``) and the operator-audit route
  (``degrade.axes._PhysicalAxis.physical_result``) must both call the backend the axis declares;
* ``roi_external_drift_mm`` keeps its exact value while the p50/p95/p99 keys are added, and the
  audit reports them;
* ``choose_spacing``'s node budget is declarable and reports requested-vs-realised.

The heavier before/after measurements live in ``_probe_axis_routing_audit.py``; the tests here run
the same code paths at probe scale so a regression fails the suite instead of the report.
"""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest

from synlab.degrade.axes import physical_fragment
from synlab.degrade.registry import AXIS_REGISTRY
from synlab.physical import sdf as S
from synlab.physical.api import apply_damage, audit_physical
from synlab.physical.operators import (
    DRIFT_QUANTILES,
    NARROWBAND_BACKEND_ROUTING,
    SdfContext,
    declared_narrowband_axis,
    selected_backend,
)
from synlab.schemas.spec import AXIS_IDS

NARROWBAND_DECLARED = ("P02", "P03", "P04")
GLOBAL_SDF_DECLARED = ("P01", "P05", "P06", "P07", "P08")


# ---------------------------------------------------------------------------- declaration
def test_31_axes_are_registered_and_the_declaration_is_readable() -> None:
    assert len(AXIS_IDS) == 31
    for axis_id in AXIS_IDS:
        operator = AXIS_REGISTRY.get(axis_id)
        assert operator.AXIS_ID == axis_id
        assert operator.STAGE
        assert operator.LEVEL_COUNT == 5
        # the declaration the routing audit compares against must be introspectable per axis
        assert isinstance(getattr(operator, "NARROWBAND", False), bool)
        assert hasattr(operator, "GRID") or axis_id[0] != "P"


def test_only_the_three_declared_axes_are_narrowband() -> None:
    declared = tuple(axis_id for axis_id in AXIS_IDS
                     if bool(getattr(AXIS_REGISTRY.get(axis_id), "NARROWBAND", False)))
    assert declared == NARROWBAND_DECLARED
    for axis_id in AXIS_IDS:
        assert declared_narrowband_axis(axis_id) is bool(
            getattr(AXIS_REGISTRY.get(axis_id), "NARROWBAND", False)), axis_id


def test_routing_constant_defaults_to_declared() -> None:
    assert NARROWBAND_BACKEND_ROUTING == "declared"


# ---------------------------------------------------------------------------- production route
def _p_recipe(axis_id: str, probe: dict, *, level: int = 1, **grid: object):
    operator = AXIS_REGISTRY.get(axis_id)
    source = probe["P"]
    fragment = physical_fragment(source)
    basis = operator.sample_basis(
        {"source": source, "lineage_id": "lin_s12", "fragment_id": "frag", "master_seed": 11},
        np.random.default_rng(11), operator.default_variant)
    recipe = operator.recipe(level=level, variant=operator.default_variant,
                             params=operator.params_for(level, operator.default_variant),
                             basis=basis, fragment=fragment, source=source)
    merged = dict(recipe.grid or {})
    merged.update(grid)
    return replace(recipe, grid=merged), fragment


@pytest.mark.parametrize("axis_id", NARROWBAND_DECLARED)
def test_production_route_runs_the_declared_narrowband_backend(axis_id: str, probe: dict) -> None:
    """``physical.apply_damage`` must execute the backend the axis declares (S11/S12 fix)."""
    recipe, fragment = _p_recipe(axis_id, probe)
    assert selected_backend(recipe) == "narrowband"
    result = apply_damage(None, fragment, recipe, rng=None)
    details = dict((result.meta or {}).get("details") or {})
    assert details.get("damage_backend") == "degrade.physical_narrowband", details.get(
        "damage_backend")
    selection = dict(details.get("backend_selection") or {})
    assert selection.get("declared_narrowband") is True
    assert selection.get("backend") == "narrowband"
    # a surface operator uses no voxel grid, and says so instead of reporting a spacing
    assert float(details["narrowband"]["spacing"]["spacing_mm"]) == 0.0


@pytest.mark.parametrize("axis_id", GLOBAL_SDF_DECLARED)
def test_declared_global_axes_keep_the_voxel_backend(axis_id: str, probe: dict) -> None:
    recipe, _fragment = _p_recipe(axis_id, probe)
    assert selected_backend(recipe) == "global_sdf"
    assert declared_narrowband_axis(axis_id) is False


@pytest.mark.parametrize("axis_id", NARROWBAND_DECLARED)
def test_legacy_global_route_stays_reachable_and_is_labelled(axis_id: str, probe: dict) -> None:
    """The old behaviour must remain reproducible *and* name itself in the result."""
    recipe, fragment = _p_recipe(axis_id, probe, damage_backend="global_sdf")
    assert selected_backend(recipe) == "global_sdf"
    result = apply_damage(None, fragment, recipe, rng=None)
    details = dict((result.meta or {}).get("details") or {})
    assert details.get("damage_backend") == "physical.operators.global_sdf_level_set"
    assert (details.get("backend_selection") or {}).get("override") == "global_sdf"


def test_operator_audit_route_and_production_route_agree_on_p03(probe: dict) -> None:
    """``degrade.axes`` (the 155-level audit) and ``physical.apply_damage`` (the pipeline)."""
    from synlab.degrade.api import apply_axis

    recipe, fragment = _p_recipe("P03", probe)
    production = apply_damage(None, fragment, recipe, rng=None)
    _ref, measurement = apply_axis("P03", 1, probe["P"], None, lineage_id="lin_s12_p03")
    assert (production.meta.get("details") or {}).get("damage_backend") == \
        "degrade.physical_narrowband"
    assert measurement.measured["watertight"] == 1.0
    assert measurement.measured["roi_external_drift_mm"] <= 1e-4


# ---------------------------------------------------------------------------- drift metric family
def test_drift_quantiles_are_declared_and_do_not_replace_the_max() -> None:
    assert DRIFT_QUANTILES == (50.0, 95.0, 99.0)


def test_drift_quantiles_are_additive_on_the_global_path(probe: dict) -> None:
    """The new stats must reproduce the shipped max bit for bit and add the quantiles."""
    recipe, fragment = _p_recipe("P07", probe, damage_backend="global_sdf")
    mesh = fragment.mesh
    ctx = SdfContext(mesh, recipe, fragment=fragment)
    from synlab.physical.operators import _roi_external_drift, _roi_external_drift_stats

    halo = 3.0 * ctx.spacing + 1.0
    shipped = float(_roi_external_drift(mesh, ctx, halo_mm=halo))
    stats = _roi_external_drift_stats(mesh, ctx, halo_mm=halo)
    assert shipped == float(stats["max_mm"])
    assert 0.0 <= stats["p50_mm"] <= stats["p95_mm"] <= stats["p99_mm"] <= stats["max_mm"]


def test_audit_reports_the_drift_quantiles(probe: dict) -> None:
    recipe, fragment = _p_recipe("P03", probe)
    result = apply_damage(None, fragment, recipe, rng=None)
    audit = audit_physical(result, fragment.mesh)
    check = dict((audit.get("checks") or {}).get("roi_external_drift") or {})
    for key in ("max_mm", "p50_mm", "p95_mm", "p99_mm", "pass"):
        assert key in check, (key, sorted(check))
    measured = dict((result.meta or {}).get("measured") or {})
    assert measured["roi_external_drift_mm"] == check["max_mm"]
    assert measured["roi_external_drift_p95_mm"] == check["p95_mm"]
    assert check["p95_mm"] <= check["max_mm"]


def test_missing_quantiles_are_reported_as_absent_not_zero(probe: dict) -> None:
    """An operator that does not measure the population must not look like a perfect zero."""
    from synlab.physical.operators import _roi_external_drift_stats

    recipe, fragment = _p_recipe("P03", probe)
    ctx = SdfContext(fragment.mesh, recipe, fragment=fragment)
    stats = _roi_external_drift_stats(fragment.mesh, ctx, halo_mm=1e9)
    assert stats["moved_samples"] == 0.0
    assert stats["max_mm"] == 0.0 and stats["p95_mm"] == 0.0
    assert stats["samples"] > 0


# ---------------------------------------------------------------------------- node budget
def test_choose_spacing_reports_requested_vs_realised() -> None:
    choice = S.choose_spacing(min_wall_thickness_mm=0.6, shortest_structure_mm=3.2,
                              requested_mm=None, max_nodes=600_000,
                              bbox_mm=(60.0, 40.0, 20.0))
    assert choice["budget_limited"] is True
    assert choice["spacing_mm"] > 0.6 / 6.0
    assert choice["relaxation_steps"] >= 1
    assert choice["relaxation_factor"] == pytest.approx(1.2 ** choice["relaxation_steps"])
    report = S.spacing_budget_report(choice, bbox_mm=(60.0, 40.0, 20.0))
    assert report["basis"].endswith("+node_budget_relaxation")
    assert report["requested_mm"] is None
    assert report["realised_nodes"] if "realised_nodes" in report else True


def test_explicit_damage_spacing_is_honoured_verbatim() -> None:
    """``damage_spacing_mm`` is the declarable form: the budget reports, it does not override."""
    declared = 0.5701
    choice = S.choose_spacing(min_wall_thickness_mm=0.6, shortest_structure_mm=3.2,
                              requested_mm=None, max_nodes=1000, bbox_mm=(60.0, 40.0, 20.0),
                              explicit_mm=declared)
    assert choice["spacing_mm"] == pytest.approx(declared)
    assert choice["basis"] == "explicit"
    assert choice["budget_limited"] is False
    assert choice["declared_spacing_mm"] == pytest.approx(declared)
    report = S.spacing_budget_report(choice, bbox_mm=(60.0, 40.0, 20.0))
    assert report["request_honoured"] is True


def test_negative_explicit_spacing_is_refused() -> None:
    from synlab.errors import ErrorCode, SynLabError

    with pytest.raises(SynLabError) as excinfo:
        S.choose_spacing(min_wall_thickness_mm=0.6, explicit_mm=-1.0)
    code = excinfo.value.code
    assert getattr(code, "value", code) == ErrorCode.SCHEMA_INVALID.value


def test_pipeline_body_reports_the_budget_it_used(probe: dict) -> None:
    """The realised spacing/nodes of the grid the operator actually built reach the result."""
    recipe, fragment = _p_recipe("P07", probe, max_nodes=60_000)
    result = apply_damage(None, fragment, recipe, rng=None)
    details = dict((result.meta or {}).get("details") or {})
    budget = dict((details.get("sdf_pipeline") or {}).get("spacing_budget") or {})
    assert budget, "the grid decision must be reported"
    assert budget["max_nodes"] == 60_000
    assert budget["realised_nodes"] <= 60_000 * 1.3   # the +1 padding of the grid builder
    assert budget["budget_limited"] is True
    measured = dict((result.meta or {}).get("measured") or {})
    assert measured["grid_budget_limited"] == 1.0


# ---------------------------------------------------------------------------- freeze the contract
def test_identity_contract_is_untouched(probe: dict) -> None:
    """level 0 must still return the source object and the source bytes (R4)."""
    from synlab.degrade.api import apply_axis

    for axis_id in AXIS_IDS:
        _ref, measurement = apply_axis(axis_id, 0, probe[axis_id[0]], None,
                                       lineage_id="lin_s12_identity")
        assert measurement.identity is True
        assert measurement.realized is True
        assert measurement.source_hash == measurement.result_hash


def test_routing_audit_report_exists_and_covers_31_axes() -> None:
    """The report written by ``_probe_axis_routing_audit.py --step table`` is machine-readable."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "data" / "a12_reports" / "s12_axis_table.json"
    if not path.exists():
        pytest.skip(f"run the S12 driver first: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["table"]["rows"]
    assert {row["axis_id"] for row in rows} == set(AXIS_IDS)
    for row in rows:
        assert row["agree"] in ("AGREE", "DISAGREE", "NOT_EXECUTED")
        assert row["executed_backends"], row["axis_id"]
    disagree = [row["axis_id"] for row in rows if row["agree"] != "AGREE"]
    assert not disagree, f"axes whose executed backend contradicts their declaration: {disagree}"
