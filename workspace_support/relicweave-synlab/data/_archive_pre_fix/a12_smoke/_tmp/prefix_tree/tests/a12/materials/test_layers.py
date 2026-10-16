"""Layer stacks L01..L04 and the real geometric layer bodies (plan 8.2)."""

from __future__ import annotations

import numpy as np
import pytest

from synlab.errors import ErrorCode, SynLabError
from synlab.materials.api import combo_definition, combo_geometric_layers, combo_ids, layer_combo
from synlab.materials.layers import build_layer_shell, erode_mother, measure_layer_thickness
from synlab.materials.api import MODE_GEOMETRIC, MODE_SHADING
from synlab.mothers.api import audit_mother, create_mother, geometry_hash
from synlab.registry import REGISTRY
from synlab.seeds import make_rng

SEED_A = 4242


def test_four_layer_combos_registered():
    ids = combo_ids()
    assert ids == ["L01", "L02", "L03", "L04"]
    for combo_id in ids:
        entry = REGISTRY.get("layer_combo", combo_id)
        assert entry.param_model is not None, combo_id
        assert entry.builder is not None, combo_id
        definition = combo_definition(combo_id)
        assert definition["layers"], combo_id


@pytest.mark.parametrize("combo_id", ["L01", "L02", "L03", "L04"])
def test_layer_combo_builds_an_ordered_stack(combo_id):
    specs = layer_combo(combo_id, {}, make_rng(SEED_A, "layer", combo_id))
    assert specs, combo_id
    # the body is layer 1 and always a shading layer: a shading layer never claims a body
    assert specs[0].layer_id == 1
    assert specs[0].mode == MODE_SHADING
    ids = [spec.layer_id for spec in specs]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    for spec in specs:
        assert spec.mode in (MODE_SHADING, MODE_GEOMETRIC)
        assert 0.0 <= spec.albedo[0] <= 1.0
        assert spec.thickness_mm >= 0.0
        if spec.mode == MODE_SHADING:
            assert spec.thickness_mm == 0.0, (
                f"{combo_id}/{spec.name}: a shading layer must not claim a thickness")


def test_geometric_and_shading_combos_are_not_conflated():
    geometric = {combo_id: combo_geometric_layers(combo_id, {}, make_rng(SEED_A, "layer"))
                 for combo_id in ("L01", "L03")}
    shading = {combo_id: combo_geometric_layers(combo_id, {}, make_rng(SEED_A, "layer"))
               for combo_id in ("L02", "L04")}
    for combo_id, entries in geometric.items():
        assert entries, f"{combo_id} declares a geometric layer but exposes none"
        for entry in entries:
            assert entry["thickness_mm"] > 0
            assert entry["min_thickness_mm"] > 0
    for combo_id, entries in shading.items():
        assert entries == [], f"{combo_id} is appearance-only but exposes a geometric layer"


def test_geometric_layer_is_a_real_watertight_body():
    mother = create_mother("V01", "M01", {}, make_rng(SEED_A, "shape"), mother_id="V01-layer")
    entries = combo_geometric_layers("L01", {}, make_rng(SEED_A, "layer"))
    assert len(entries) == 1
    shell = build_layer_shell(mother, entries[0])
    assert shell.mesh.is_watertight, "the geometric layer is not watertight"
    assert float(shell.mesh.volume) > 0
    assert shell.inner_mesh.is_watertight, "the layer interface is not watertight"
    assert shell.qa["mode"] == MODE_GEOMETRIC
    assert shell.qa["ok"], shell.qa
    assert shell.volume_mm3 > 0
    assert shell.interface_area_mm2 > 0
    # the measured thickness is the real one, not the requested parameter: at least the minimum
    # everywhere and controlled around the request (a curved outline is locally thicker because
    # a normal ray crosses it twice)
    assert shell.qa["p05_mm"] >= shell.min_thickness_mm - 1e-6, shell.qa
    assert shell.qa["median_mm"] <= shell.thickness_requested_mm * 1.8 + 0.3, shell.qa
    assert shell.qa["median_mm"] >= 0.5 * shell.thickness_requested_mm, shell.qa
    # the layer body is thinner than the mother it was cut from
    assert shell.volume_mm3 < float(mother.mesh.volume)


def test_geometric_layer_needs_room():
    mother = create_mother("V01", "M01", {}, make_rng(SEED_A, "shape"), mother_id="V01-thick")
    with pytest.raises(SynLabError) as info:
        build_layer_shell(mother, {"layer_id": 2, "name": "too_thick", "material_id": "M06",
                                   "thickness_mm": 400.0, "min_thickness_mm": 0.4})
    assert info.value.code in (ErrorCode.MOTHER_INVALID, ErrorCode.SCHEMA_INVALID)


def test_shading_layer_does_not_change_the_geometry_hash():
    """A SHADING_LAYER only changes appearance: the mother geometry hash is untouched."""
    mother = create_mother("V03", "M05", {}, make_rng(SEED_A, "shape"), mother_id="V03-shading")
    before = geometry_hash(mother.mesh)
    specs = layer_combo("L02", {}, make_rng(SEED_A, "layer"))
    assert all(spec.mode == MODE_SHADING for spec in specs)
    assert combo_geometric_layers("L02") == []
    # applying the shading stack must not touch the mesh at all
    for spec in specs:
        assert spec.thickness_mm == 0.0
    assert geometry_hash(mother.mesh) == before
    after = audit_mother(mother, max_thickness_probes=32, run_self_intersection=False)
    assert after["geometry_hash"] == before


def test_erode_mother_returns_a_valid_inner_solid():
    mother = create_mother("V19", "M01", {}, make_rng(SEED_A, "shape"), mother_id="V19-erode")
    inner = erode_mother(mother.mesh, thickness_mm=1.5)
    assert inner.is_watertight
    assert float(inner.volume) > 0
    assert float(inner.volume) < float(mother.mesh.volume)


def test_measure_layer_thickness_reports_real_values():
    mother = create_mother("V21", "M03", {}, make_rng(SEED_A, "shape"), mother_id="V21-measure")
    inner = erode_mother(mother.mesh, thickness_mm=2.0)
    from synlab.mothers.solids import boolean_difference

    layer = boolean_difference([mother.mesh, inner])
    measured = measure_layer_thickness(mother.mesh, layer, max_probes=8)
    assert measured["n_valid"] > 0
    assert 0.0 < measured["min_mm"] <= measured["max_mm"]
    assert measured["p05_mm"] <= measured["median_mm"] <= measured["max_mm"]


def test_layer_combo_rejects_unknown_parameters():
    with pytest.raises(SynLabError) as info:
        layer_combo("L01", {"not_a_field": 1}, make_rng(1, "layer"))
    assert info.value.code == ErrorCode.SCHEMA_INVALID
    with pytest.raises(SynLabError) as info:
        layer_combo("L99", {}, make_rng(1, "layer"))
    assert info.value.code == ErrorCode.SCHEMA_INVALID


def test_glaze_combo_thickness_is_a_real_parameter():
    thin = layer_combo("L01", {"glaze_thickness_mm": 0.2}, make_rng(SEED_A, "layer"))
    thick = layer_combo("L01", {"glaze_thickness_mm": 2.0}, make_rng(SEED_A, "layer"))
    assert thin[1].thickness_mm == pytest.approx(0.2)
    assert thick[1].thickness_mm == pytest.approx(2.0)
    assert thin[1].mode == MODE_GEOMETRIC and thick[1].mode == MODE_GEOMETRIC
