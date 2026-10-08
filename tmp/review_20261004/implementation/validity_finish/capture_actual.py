from __future__ import annotations

import json
import runpy
from dataclasses import replace
from pathlib import Path

import numpy as np
import trimesh

from synlab.degrade.axes import _FragmentView
from synlab.degrade.api import _apply_impl, probe_sources
from synlab.degrade.registry import get_operator
from synlab.degrade.physical_narrowband import run_narrowband_damage
from synlab.degrade.sources import KIND_PHYSICAL, SourceBundle
from synlab.schemas.runtime import ORIGIN_INTERFACE, ORIGIN_MOTHER_SURFACE
from synlab.storage.mesh_io import with_face_attrs


qa_tests = runpy.run_path("tests/a12/operators/test_postassembly_qa_20261003.py")
label_tests = runpy.run_path("tests/a12/degrade/test_label_status_evidence_20261003.py")
actual = {"narrowband_small_box": {}, "minimal_88_face_box": {},
          "probe_narrowband": {}, "probe_apply_axis": {}, "label_qa_failure_route": {}}

for axis_id, level in (("P02", 4), ("P03", 1), ("P04", 1)):
    mesh, fragment, source, _clean_truth = qa_tests["_closed_box_source"]()
    recipe = qa_tests["_recipe"](axis_id, level, fragment, source)
    try:
        result = run_narrowband_damage(mesh, recipe, fragment=fragment)
        post = result.qa.get("postassembly", {})
        actual["narrowband_small_box"][axis_id] = {
            "source_face_count": int(len(mesh.faces)),
            "source_watertight": bool(mesh.is_watertight),
            "geometry_hash_algorithm": post.get("geometry_hash_algorithm"),
            "status": result.qa.get("status"),
            "realized": result.qa.get("realized"),
            "component_count": len(result.components),
            "postassembly_status": post.get("status"),
            "failure_codes": post.get("failure_codes", []),
            "checks": {
                key: value.get("status")
                for key, value in (post.get("checks") or {}).items()
                if isinstance(value, dict) and "status" in value
            },
            "component_geometry_hashes": post.get("component_geometry_hashes", []),
        }
    except Exception as exc:  # retain the actual route's structured/ordinary failure
        actual["narrowband_small_box"][axis_id] = {
            "exception": f"{type(exc).__name__}: {exc}"
        }

route_tests = runpy.run_path("tests/a12/degrade/test_axis_routing_audit.py")
probe = probe_sources()
for axis_id in ("P02", "P03", "P04"):
    recipe, fragment = route_tests["_p_recipe"](axis_id, probe)
    result = run_narrowband_damage(fragment.mesh, recipe, fragment=fragment)
    post = result.qa.get("postassembly", {})
    details = result.meta.get("details", {})
    actual["probe_narrowband"][axis_id] = {
        "source_face_count": int(len(fragment.mesh.faces)),
        "result_face_counts": [int(len(component.mesh.faces)) for component in result.components],
        "realized": result.qa.get("realized"),
        "result_status": result.qa.get("status"),
        "postassembly_status": post.get("status"),
        "failure_codes": post.get("failure_codes", []),
        "checks": {
            key: value.get("status")
            for key, value in (post.get("checks") or {}).items()
            if isinstance(value, dict) and "status" in value
        },
        "measured": result.meta.get("measured", {}),
        "narrowband_detail_keys": sorted((details.get("narrowband") or {}).keys()),
        "narrowband_spacing": (details.get("narrowband") or {}).get("spacing"),
        "sdf_spacing": (details.get("sdf_pipeline") or {}).get("spacing"),
    }
for axis_id, lineage in (("P02", "lin_p02"), ("P03", "lin_p03")):
    operator = get_operator(axis_id)
    original_validate = operator.validate
    operator.validate = lambda *_args, **_kwargs: None
    try:
        output, _record, measurement = _apply_impl(axis_id, 1, probe["P"], None,
                                                   lineage_id=lineage, commit=False)
        physical = output.get("physical_result")
        physical_qa = getattr(physical, "qa", {}) or {}
        post = physical_qa.get("postassembly", {})
        actual["probe_apply_axis"][axis_id] = {
            "measurement_realized": measurement.realized,
            "measurement_valid": measurement.valid,
            "physical_realized": physical_qa.get("realized"),
            "physical_status": physical_qa.get("status"),
            "postassembly_status": post.get("status"),
            "failure_codes": post.get("failure_codes", []),
            "checks": {
                key: value.get("status")
                for key, value in (post.get("checks") or {}).items()
                if isinstance(value, dict) and "status" in value
            },
            "measured": measurement.measured,
        }
    finally:
        operator.validate = original_validate

base = trimesh.creation.box(extents=(8.0, 8.0, 2.4))
vertices, faces = trimesh.remesh.subdivide_to_size(
    np.asarray(base.vertices, dtype=np.float64), np.asarray(base.faces, dtype=np.int64),
    max_edge=4.0)
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
substrate = np.tile(np.array([0.57, 0.50, 0.40], dtype=np.float32), (len(mesh.faces), 1))
appearance = {
    "texel_albedo": np.where(layer[:, None], np.array([0.78, 0.20, 0.11], dtype=np.float32),
                             substrate).astype(np.float32),
    "texel_substrate_albedo": substrate,
    "texel_area_mm2": area,
    "texel_layer": layer.astype(np.int32),
    "texel_roughness": np.full(len(mesh.faces), 0.62, dtype=np.float32),
    "texel_positions": centers.copy(),
    "pattern_region": layer.copy(),
    "interface_region": interface.copy(),
}
fragment = _FragmentView(mesh, "box_88_faces", meta={"material_id": "M03",
                           "appearance": appearance},
                         face_attrs={"origin_kind": origin, "interface_id": interface_id})
source = SourceBundle(source_kind=KIND_PHYSICAL,
                      payload={"mesh": mesh, "fragment": fragment,
                               "appearance": appearance},
                      unit="mm", frame="F_mm", fragment_id="box_88_faces",
                      meta={"material_id": "M03", "master_seed": 20261003})
for axis_id, level in (("P02", 4), ("P03", 1), ("P04", 1)):
    recipe = qa_tests["_recipe"](axis_id, level, fragment, source)
    try:
        result = run_narrowband_damage(mesh, recipe, fragment=fragment)
        post = result.qa.get("postassembly", {})
        component_rows = post.get("components", [])
        actual["minimal_88_face_box"][axis_id] = {
            "source_face_count": int(len(mesh.faces)),
            "result_face_counts": [int(len(component.mesh.faces))
                                   for component in result.components],
            "geometry_hash_algorithm": post.get("geometry_hash_algorithm"),
            "status": result.qa.get("status"),
            "realized": result.qa.get("realized"),
            "component_count": len(result.components),
            "postassembly_status": post.get("status"),
            "failure_codes": post.get("failure_codes", []),
            "checks": {
                key: value.get("status")
                for key, value in (post.get("checks") or {}).items()
                if isinstance(value, dict) and "status" in value
            },
            "components": [{
                "component_id": row.get("component_id"),
                "faces": next((int(len(component.mesh.faces))
                               for component in result.components
                               if component.component_id == row.get("component_id")), None),
                "signed_volume_mm3": row.get("mesh", {}).get("signed_volume_mm3"),
                "watertight": row.get("mesh", {}).get("watertight"),
                "winding_consistent": row.get("mesh", {}).get("winding_consistent"),
                "recorded_volume_mm3": row.get("recorded_volume_mm3"),
                "geometry_hash": row.get("geometry_hash"),
            } for row in component_rows],
            "source_geometry": {
                "signed_volume_mm3": (post.get("checks", {}).get("positive_volume", {})
                                       .get("source_volume_mm3")),
                "watertight": (post.get("checks", {}).get("watertight", {})
                               .get("source")),
                "winding_consistent": (post.get("checks", {}).get("winding_consistent", {})
                                       .get("source")),
            },
            "boundary_edges": [
                qa_tests["_boundary_loops"](component.mesh)[1].get("boundary_edges")
                for component in result.components
            ],
            "conservation": (post.get("checks") or {}).get("conservation", {}),
        }
    except Exception as exc:
        actual["minimal_88_face_box"][axis_id] = {
            "source_face_count": int(len(mesh.faces)),
            "exception": f"{type(exc).__name__}: {exc}"
        }

source = label_tests["_physical_source"]()
operator = get_operator("P06")
original = operator.physical_result


def force_result_qa_failure(recipe, fragment, clean_truth):
    physical = original(recipe, fragment, clean_truth)
    physical.qa["status"] = "FAIL"
    return physical


operator.physical_result = force_result_qa_failure
try:
    _result, _record, measurement = _apply_impl("P06", 1, source, None, commit=False)
    actual["label_qa_failure_route"] = {
        "measurement_valid": measurement.valid,
        "measurement_realized": measurement.realized,
        "label_status": measurement.extra.get("label_status"),
        "label_validity": measurement.extra.get("label_validity"),
        "dependencies": measurement.extra.get("label_dependency_status"),
    }
finally:
    operator.physical_result = original

path = Path("tmp/review_20261004/implementation/validity_finish/actualJSON.json")
path.write_text(json.dumps(actual, indent=2, sort_keys=True, default=str), encoding="utf-8")
print(path.read_text(encoding="utf-8"))
