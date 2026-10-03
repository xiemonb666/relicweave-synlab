"""Fail-closed postassembly QA on the small synthetic P02 production route."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from synlab.degrade.axes import _FragmentView
from synlab.degrade.registry import AXIS_REGISTRY
from synlab.degrade.sources import KIND_PHYSICAL, SourceBundle
from synlab.physical.api import apply_damage, audit_physical
from synlab.physical.recipe import DamageRecipe
from synlab.schemas.runtime import ORIGIN_INTERFACE, ORIGIN_MOTHER_SURFACE
from synlab.storage.mesh_io import with_face_attrs


SEED = 20261003
LINEAGE = "physical_qa_repair_small_box_20261003"


def _closed_box_source():
    base = trimesh.creation.box(extents=(8.0, 8.0, 2.4))
    vertices, faces = trimesh.remesh.subdivide_to_size(
        np.asarray(base.vertices, dtype=np.float64),
        np.asarray(base.faces, dtype=np.int64), max_edge=2.4)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.merge_vertices()
    centers = np.asarray(mesh.triangles_center, dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    interface = (normals[:, 2] > 0.9) & (centers[:, 2] > 1.19)
    origin = np.full(len(mesh.faces), ORIGIN_MOTHER_SURFACE, dtype=np.uint8)
    interface_id = np.full(len(mesh.faces), -1, dtype=np.int32)
    origin[interface] = ORIGIN_INTERFACE
    interface_id[interface] = 1
    with_face_attrs(mesh, origin_kind=origin, interface_id=interface_id)
    area = np.asarray(mesh.area_faces, dtype=np.float64)
    layer = interface & ((np.arange(len(mesh.faces)) % 3) != 1)
    substrate = np.tile(np.array([0.57, 0.50, 0.40], dtype=np.float32),
                        (len(mesh.faces), 1))
    appearance = {
        "texel_albedo": np.where(
            layer[:, None], np.array([0.78, 0.20, 0.11], dtype=np.float32),
            substrate).astype(np.float32),
        "texel_substrate_albedo": substrate,
        "texel_area_mm2": area,
        "texel_layer": layer.astype(np.int32),
        "texel_roughness": np.full(len(mesh.faces), 0.62, dtype=np.float32),
        "texel_positions": centers.copy(),
        "pattern_region": layer.copy(),
        "interface_region": interface.copy(),
    }
    fragment = _FragmentView(
        mesh, "probe_fragment_small", meta={"material_id": "M03", "appearance": appearance},
        face_attrs={"origin_kind": origin, "interface_id": interface_id})
    source = SourceBundle(
        source_kind=KIND_PHYSICAL,
        payload={"mesh": mesh, "fragment": fragment, "appearance": appearance},
        role="probe", schema="probe", unit="mm", frame="F_mm",
        lineage_id=LINEAGE, fragment_id="probe_fragment_small",
        meta={"material_id": "M03", "master_seed": SEED,
              "provenance": "SYNTHETIC_SMALL_BOX_FIXTURE"})
    clean_truth = SimpleNamespace(mother_id="M_probe", event_id="E_probe", version=1)
    return mesh, fragment, source, clean_truth


def _recipe(axis_id: str, level: int, fragment, source):
    operator = AXIS_REGISTRY.get(axis_id)
    variant = operator.default_variant
    basis = operator.sample_basis(
        {"source": source, "lineage_id": LINEAGE,
         "fragment_id": "probe_fragment_small", "master_seed": SEED},
        np.random.default_rng(SEED), variant)
    return operator.recipe(
        level=level, variant=variant, params=operator.params_for(level, variant),
        basis=basis, fragment=fragment, source=source)


def test_p02_production_route_fails_closed_on_the_three_edge_boundary_loop():
    mesh, fragment, source, clean_truth = _closed_box_source()
    recipe = _recipe("P02", 4, fragment, source)

    result = apply_damage(clean_truth, fragment, recipe, rng=None)
    post = result.qa["postassembly"]
    closure = result.qa["pinhole_closure"]
    audit = audit_physical(result, mesh)

    assert result.qa["realized"] is True  # effect exists; it is not final QA
    assert result.qa["status"] == "FAIL"
    assert post["status"] == "FAIL"
    assert "NOT_WATERTIGHT" in post["failure_codes"]
    assert post["checks"]["watertight"]["pass"] is False
    assert closure["pinholes_filled"] == 0
    assert closure["pinhole_closures"][0]["boundary"]["boundary_edges"] == 3
    assert closure["pinhole_closures"][0]["loops"][0]["diagonal_mm"] == pytest.approx(
        2.8284271247461903)
    assert result.components[0].mesh.is_watertight is False
    assert audit["status"] == "FAIL"
    assert "NOT_WATERTIGHT" in audit["failure_codes"]


@pytest.mark.parametrize("axis_id", ("P01", "P02"))
def test_closed_identity_controls_pass_for_p01_and_p02(axis_id: str):
    mesh, fragment, source, clean_truth = _closed_box_source()
    recipe = _recipe(axis_id, 0, fragment, source)

    result = apply_damage(clean_truth, fragment, recipe, rng=None)
    audit = audit_physical(result, mesh)

    assert result.qa["status"] == "PASS"
    assert result.qa["postassembly"]["status"] == "PASS"
    assert result.qa["postassembly"]["checks"]["watertight"]["pass"] is True
    assert audit["status"] == "PASS", audit["failure_codes"]


@pytest.mark.parametrize("axis_id", ("P05", "P06"))
def test_appearance_only_p05_p06_keep_healthy_closed_entity_positive(axis_id: str):
    mesh, fragment, source, clean_truth = _closed_box_source()
    recipe = _recipe(axis_id, 1, fragment, source)

    result = apply_damage(clean_truth, fragment, recipe, rng=None)
    audit = audit_physical(result, mesh)

    assert result.qa["realized"] is True
    assert result.qa["status"] == "PASS"
    assert result.qa["postassembly"]["status"] == "PASS"
    assert result.qa["postassembly"]["checks"]["watertight"]["pass"] is True
    assert audit["status"] == "PASS", audit["failure_codes"]


def test_open_complete_entity_identity_returns_a_diagnostic_fail_without_repair():
    opened = trimesh.creation.box(extents=(4.0, 4.0, 4.0))
    opened.update_faces(np.arange(1, len(opened.faces)))
    opened.remove_unreferenced_vertices()
    fragment = _FragmentView(opened, "open_entity", meta={})
    recipe = DamageRecipe(axis_id="P02", variant="sdf_fillet", level=0)

    result = apply_damage(None, fragment, recipe, rng=None)

    assert result.qa["status"] == "FAIL"
    assert result.qa["postassembly"]["checks"]["watertight"]["source"] is False
    assert "SOURCE_NOT_WATERTIGHT" in result.qa["failure_codes"]
    assert result.qa["postassembly"]["checks"]["watertight"]["open_mesh_reason"]
    assert result.components[0].mesh is opened
    assert result.components[0].mesh.is_watertight is False


def test_closed_inverted_entity_is_not_rescued_by_absolute_recorded_volume():
    inverted = trimesh.creation.box(extents=(4.0, 4.0, 4.0))
    inverted.invert()
    assert inverted.is_watertight is True
    assert inverted.is_winding_consistent is True
    assert float(inverted.volume) < 0.0
    fragment = _FragmentView(inverted, "inverted_entity", meta={})

    result = apply_damage(None, fragment,
                          DamageRecipe(axis_id="P02", variant="sdf_fillet", level=0))
    post = result.qa["postassembly"]
    audit = audit_physical(result, inverted)

    assert result.qa["status"] == "FAIL"
    assert result.components[0].volume_mm3 > 0.0  # stored magnitude must not rescue signed volume
    assert post["checks"]["positive_volume"]["source_volume_mm3"] < 0.0
    assert post["checks"]["positive_volume"]["components"][
        result.components[0].component_id]["signed_mesh_volume_mm3"] < 0.0
    assert "SOURCE_NON_POSITIVE_VOLUME" in post["failure_codes"]
    assert "NON_POSITIVE_VOLUME" in post["failure_codes"]
    assert post["checks"]["conservation"]["source_geometry_match_pass"] is False
    assert post["checks"]["conservation"]["component_geometry_match_pass"] is False
    assert audit["status"] == "FAIL"
    assert audit["checks"]["positive_volume"]["pass"] is False


def test_missing_ledger_conservation_remains_unknown_and_fails_closed():
    mesh, fragment, source, clean_truth = _closed_box_source()
    result = apply_damage(clean_truth, fragment, _recipe("P02", 0, fragment, source))
    result.meta["ledger"].pop("conservation_ok")

    audit = audit_physical(result, mesh)

    assert audit["status"] == "FAIL"
    assert audit["checks"]["postassembly"]["checks"]["conservation"]["status"] == "UNKNOWN"
    assert audit["checks"]["postassembly"]["checks"]["conservation"]["pass"] is None
    assert "LEDGER_CONSERVATION_UNKNOWN" in audit["failure_codes"]
