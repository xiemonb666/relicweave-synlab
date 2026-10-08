from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path.cwd().resolve()
OUT = Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

PREVIOUS_DIAG = (ROOT / "tmp/review_20261004/implementation/"
                 "narrowband_diagnosis_20261004/diagnosis.json")
PREVIOUS_PNG = (ROOT / "tmp/review_20261004/implementation/"
                "narrowband_diagnosis_20261004/actual_mesh_boundary_projections.png")
SNAPSHOT_SDF = (ROOT / "tmp/review_20261004/implementation/"
                "explicit_spacing_fix_20261004/sdf.py.original")
PREPARED_NPZ = OUT / "frozen_inputs.npz"
PREPARED_META = OUT / "frozen_inputs.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def array_record(value: np.ndarray) -> dict:
    array = np.ascontiguousarray(value)
    return {
        "dtype": array.dtype.str,
        "shape": list(array.shape),
        "nbytes": int(array.nbytes),
        "sha256_c_order_bytes": sha256_bytes(array.tobytes(order="C")),
    }


def mesh_metrics(vertices: np.ndarray, faces: np.ndarray) -> dict:
    vertices = np.ascontiguousarray(vertices)
    faces = np.ascontiguousarray(faces)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    f = np.asarray(mesh.faces, dtype=np.int64)
    if len(f):
        pairs = np.sort(np.concatenate((f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]])), axis=1)
        _, counts = np.unique(pairs, axis=0, return_counts=True)
        boundary = int(np.count_nonzero(counts == 1))
        nonmanifold = int(np.count_nonzero(counts > 2))
        nondegenerate = mesh.nondegenerate_faces(height=1e-12)
        degenerate = int(len(f) - int(nondegenerate.sum()))
        areas = np.asarray(mesh.area_faces, dtype=np.float64)
        min_area = float(np.min(areas)) if len(areas) else None
    else:
        boundary = nonmanifold = degenerate = 0
        min_area = None
    try:
        signed_volume = float(mesh.volume)
    except Exception as exc:  # retain failure as evidence
        signed_volume = None
        volume_error = f"{type(exc).__name__}: {exc}"
    else:
        volume_error = None
    try:
        watertight = bool(mesh.is_watertight)
        winding = bool(mesh.is_winding_consistent)
        is_volume = bool(mesh.is_volume)
    except Exception as exc:
        watertight = winding = is_volume = None
        topology_error = f"{type(exc).__name__}: {exc}"
    else:
        topology_error = None
    bounds = np.asarray(mesh.bounds, dtype=np.float64) if len(vertices) else None
    return {
        "vertices": int(len(vertices)), "faces": int(len(faces)),
        "vertex_dtype": vertices.dtype.str, "face_dtype": faces.dtype.str,
        "boundary_edges": boundary, "nonmanifold_edges": nonmanifold,
        "degenerate_faces_height_1e-12": degenerate,
        "min_face_area_mm2": min_area,
        "watertight": watertight, "winding_consistent": winding, "is_volume": is_volume,
        "signed_volume_mm3": signed_volume,
        "bounds_mm": bounds.tolist() if bounds is not None else None,
        "volume_error": volume_error, "topology_error": topology_error,
    }


def assert_prior_mesh(axis_case: dict, name: str, current: dict) -> None:
    expected = axis_case[name]
    for key in ("vertices", "faces", "boundary_edges", "nonmanifold_edges",
                "degenerate_faces", "watertight", "winding_consistent", "is_volume"):
        actual_key = ("degenerate_faces_height_1e-12"
                      if key == "degenerate_faces" else key)
        if current[actual_key] != expected[key]:
            raise RuntimeError(f"{axis_case['axis_id']} {name} {key}: "
                               f"current={current[actual_key]!r}, prior={expected[key]!r}")
    if abs(float(current["signed_volume_mm3"]) - float(expected["signed_volume_mm3"])) > 2e-8:
        raise RuntimeError(f"{axis_case['axis_id']} {name} signed volume diverged from prior diagnostic")


def relevant_hashes() -> dict:
    rels = [
        "synlab/degrade/axes.py", "synlab/degrade/physical_narrowband.py",
        "synlab/degrade/narrowband.py", "synlab/degrade/api.py",
        "synlab/degrade/fields.py", "synlab/physical/fields.py",
        "synlab/physical/sdf.py", "synlab/degrade/registry.py",
        "tmp/review_20261004/implementation/narrowband_diagnosis_20261004/diagnose_narrowband.py",
        "tmp/review_20261004/implementation/narrowband_diagnosis_20261004/diagnosis.json",
    ]
    result = {}
    for rel in rels:
        path = ROOT / rel
        if path.is_file():
            result[rel] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    return result


def main() -> None:
    import manifold3d
    from synlab.degrade import api as degrade_api
    from synlab.degrade import narrowband as NB
    from synlab.degrade.axes import physical_fragment
    from synlab.degrade.registry import AXIS_REGISTRY
    from synlab.physical import fields as F
    from synlab.physical.fields import FourierField
    from synlab.degrade import physical_narrowband as PNB

    prior = json.loads(PREVIOUS_DIAG.read_text(encoding="utf-8"))
    prior_cases = {row["axis_id"]: row for row in prior["p02_p03_cases"]}
    from synlab.degrade.api import probe_sources

    source_bundle = probe_sources()["P"]
    fragment = physical_fragment(source_bundle)
    source_mesh = fragment.mesh
    source_v = np.ascontiguousarray(np.asarray(source_mesh.vertices, dtype=np.float64))
    source_f = np.ascontiguousarray(np.asarray(source_mesh.faces, dtype=np.int64))
    source_metrics = mesh_metrics(source_v, source_f)
    prior_source = prior_cases["P02"]["source"]
    for key in ("vertices", "faces", "boundary_edges", "watertight", "is_volume"):
        if source_metrics[key] != prior_source[key]:
            raise RuntimeError(f"rough probe source {key} differs from saved diagnostic")
    if abs(source_metrics["signed_volume_mm3"] - prior_source["signed_volume_mm3"]) > 2e-8:
        raise RuntimeError("rough probe signed volume differs from saved diagnostic")

    arrays: dict[str, np.ndarray] = {}
    cases = []
    source_array_hashes = {
        "vertices": array_record(source_v), "faces": array_record(source_f)
    }
    for axis_id, lineage_id in (("P02", "lin_p02"), ("P03", "lin_p03")):
        old_case = prior_cases[axis_id]
        operator = AXIS_REGISTRY.get(axis_id)
        variant = operator.default_variant
        master_seed = int((source_bundle.meta or {}).get(
            "master_seed", degrade_api.DEFAULT_MASTER_SEED))
        context = degrade_api._context_for(
            source_bundle, axis_id=axis_id, lineage_id=lineage_id,
            master_seed=master_seed)
        context["variant"] = variant
        basis = operator.sample_basis(
            context, degrade_api._default_rng(context, axis_id, variant), variant)
        if basis.basis_id != old_case["basis_id"]:
            raise RuntimeError(f"{axis_id} basis ID mismatch: {basis.basis_id} != {old_case['basis_id']}")
        params = dict(operator.params_for(1, variant))
        recipe = operator.recipe(level=1, variant=variant, params=params,
                                 basis=basis, fragment=fragment, source=source_bundle)
        roi_ids, roi_info = F.roi_faces(source_mesh, fragment,
                                        dict(recipe.roi or {"kind": "interface"}))

        if axis_id == "P02":
            strength = float(recipe.parameter("recession_strength", 0.0))
            edge_width = float(recipe.parameter("edge_width_mm",
                                                recipe.meta.get("edge_width_mm", 0.4)))
            effective_radius = edge_width * strength
            edges, edge_info = NB.roi_boundary_edges(
                source_mesh, roi_ids,
                min_angle_deg=float(recipe.meta.get("min_edge_angle_deg", 45.0)))
            sections = NB.edge_sections(source_mesh, edges)
            vertex_depth, depth_stats = NB.edge_recession_depth(
                source_v, sections, effective_radius)
            candidate_mesh = NB._offset_body(source_mesh, vertex_depth)
            field_arrays = {
                "roi_face_ids_i64": np.ascontiguousarray(roi_ids, dtype=np.int64),
                "roi_boundary_edges_i64": np.ascontiguousarray(edges, dtype=np.int64),
                "vertex_depth_f64": np.ascontiguousarray(vertex_depth, dtype=np.float64),
            }
            operator_inputs = {
                "recession_strength": strength, "edge_width_mm": edge_width,
                "effective_radius_mm": effective_radius,
                "min_edge_angle_deg": float(recipe.meta.get("min_edge_angle_deg", 45.0)),
                "roi_info": jsonable(roi_info), "edge_info": jsonable(edge_info),
                "edge_section_info": jsonable(sections),
                "vertex_depth_stats": jsonable(depth_stats),
                "offset_body_constructions": 1,
                "boolean_calls_during_freeze": 0,
            }
        else:
            # Replay only the already-recorded L1 depth/scale decision. This avoids calling the
            # known-defective paired_thickness guard again and does not alter the P03 field.
            old_applied = float(old_case["measured"]["applied_depth_mm"])
            depth = float(recipe.parameter("depth_mm", 0.0))
            old_guard = (old_case["narrowband_details"].get("thickness_guard") or [{}])[0]
            scale = float(old_guard.get("scale", old_applied / depth))
            if abs(depth * scale - old_applied) > 1e-12:
                raise RuntimeError("saved P03 applied depth and scale disagree")
            field = FourierField.from_payload(recipe.basis["field"])
            transfer = np.asarray(source_mesh.triangles_center, dtype=np.float64)
            raw = np.zeros(len(source_mesh.faces), dtype=np.float64)
            raw[roi_ids] = np.clip(field(transfer[roi_ids]), 0.0, 1.0)
            normalizer = float(max(np.percentile(raw[roi_ids], 99.0), 1e-6))
            amplitude = np.clip(raw / normalizer, 0.0, 1.0)
            face_depth = amplitude * depth * scale
            candidate_mesh, detail = NB.recessed_body(
                source_mesh, roi_ids, face_depth, recipe.basis)
            vertex_depth = np.asarray(detail["vertex_depth_field"], dtype=np.float64)
            field_arrays = {
                "roi_face_ids_i64": np.ascontiguousarray(roi_ids, dtype=np.int64),
                "raw_face_field_f64": np.ascontiguousarray(raw, dtype=np.float64),
                "normalized_face_amplitude_f64": np.ascontiguousarray(amplitude, dtype=np.float64),
                "face_depth_f64": np.ascontiguousarray(face_depth, dtype=np.float64),
                "vertex_depth_f64": np.ascontiguousarray(vertex_depth, dtype=np.float64),
            }
            operator_inputs = {
                "depth_mm": depth, "recorded_guard_scale": scale,
                "applied_depth_mm": old_applied,
                "corr_length_mm": float(recipe.parameter("corr_length_mm", 6.0)),
                "normalizer": normalizer,
                "field_id": str(field.field_id),
                "field_payload": jsonable(recipe.basis["field"]),
                "field_detail": jsonable({k: v for k, v in detail.items()
                                           if k != "vertex_depth_field"}),
                "roi_info": jsonable(roi_info),
                "offset_body_constructions": 1,
                "paired_thickness_calls_during_freeze": 0,
                "boolean_calls_during_freeze": 0,
            }

        candidate_v = np.ascontiguousarray(np.asarray(candidate_mesh.vertices, dtype=np.float64))
        candidate_f = np.ascontiguousarray(np.asarray(candidate_mesh.faces, dtype=np.int64))
        candidate_metrics = mesh_metrics(candidate_v, candidate_f)
        # The prior diagnostic captured the exact pre-Boolean candidate topology and volume.
        prior_offset = next(row for row in old_case["diagnostic_events"]
                            if row.get("stage") == "offset_body_after_repair")
        assert_prior_mesh(old_case, "source", source_metrics)
        if candidate_metrics["vertices"] != prior_offset["vertices"] \
                or candidate_metrics["faces"] != prior_offset["faces"] \
                or candidate_metrics["boundary_edges"] != prior_offset["boundary_edges"] \
                or candidate_metrics["degenerate_faces_height_1e-12"] != prior_offset["degenerate_faces"] \
                or abs(candidate_metrics["signed_volume_mm3"] - prior_offset["signed_volume_mm3"]) > 2e-8:
            raise RuntimeError(f"{axis_id} reconstructed candidate does not match saved pre-Boolean metrics")

        arrays[f"{axis_id}_source_vertices_f64"] = source_v
        arrays[f"{axis_id}_source_faces_i64"] = source_f
        arrays[f"{axis_id}_candidate_vertices_f64"] = candidate_v
        arrays[f"{axis_id}_candidate_faces_i64"] = candidate_f
        for name, value in field_arrays.items():
            arrays[f"{axis_id}_{name}"] = value
        cast_hashes = {}
        for mesh_name, vertices, faces in (
            ("candidate", candidate_v, candidate_f), ("source", source_v, source_f)):
            cast_hashes[mesh_name] = {
                "mesh32_vertices_f32": array_record(np.ascontiguousarray(vertices, dtype=np.float32)),
                "mesh32_faces_u32": array_record(np.ascontiguousarray(faces, dtype=np.uint32)),
                "mesh64_vertices_f64": array_record(np.ascontiguousarray(vertices, dtype=np.float64)),
                "mesh64_faces_u64": array_record(np.ascontiguousarray(faces, dtype=np.uint64)),
            }
        cases.append({
            "axis_id": axis_id, "level": 1, "lineage_id": lineage_id,
            "variant": variant, "basis_id": basis.basis_id,
            "source_provenance": (source_bundle.meta or {}).get("provenance"),
            "source_content_hash": source_bundle.content_hash(),
            "source_metrics": source_metrics,
            "candidate_metrics": candidate_metrics,
            "operator_inputs": operator_inputs,
            "basis_payload": jsonable(basis.payload),
            "recipe": {
                "recipe_id": recipe.recipe_id, "params": jsonable(recipe.params),
                "roi": jsonable(recipe.roi), "grid": jsonable(recipe.grid),
                "qa": jsonable(recipe.qa), "meta": jsonable(recipe.meta),
            },
            "frozen_arrays": {name: array_record(value) for name, value in
                               {f"{axis_id}_source_vertices_f64": source_v,
                                f"{axis_id}_source_faces_i64": source_f,
                                f"{axis_id}_candidate_vertices_f64": candidate_v,
                                f"{axis_id}_candidate_faces_i64": candidate_f,
                                **{f"{axis_id}_{k}": v for k, v in field_arrays.items()}}.items()},
            "cast_array_hashes": cast_hashes,
            "operand_order_for_intersection": ["candidate", "source"],
            "cast_policy": {
                "mesh32": "same frozen float64 coordinates independently cast to contiguous float32; faces independently cast to contiguous uint32, matching Trimesh 5.1.0 boolean_manifold adapter",
                "mesh64": "same frozen float64 coordinates passed unchanged as contiguous float64; faces independently cast to contiguous uint64",
            },
        })

    if not np.array_equal(arrays["P02_source_vertices_f64"], arrays["P03_source_vertices_f64"]):
        raise RuntimeError("P02/P03 frozen source vertex arrays are not byte-equivalent")
    if not np.array_equal(arrays["P02_source_faces_i64"], arrays["P03_source_faces_i64"]):
        raise RuntimeError("P02/P03 frozen source face arrays are not byte-equivalent")

    np.savez_compressed(PREPARED_NPZ, **arrays)
    # Verify exact byte preservation through the compressed archive before writing metadata.
    with np.load(PREPARED_NPZ, allow_pickle=False) as check:
        for name, expected in arrays.items():
            actual = np.ascontiguousarray(check[name])
            if not np.array_equal(actual, expected) or array_record(actual) != array_record(expected):
                raise RuntimeError(f"NPZ round-trip byte mismatch for {name}")

    code_paths = [
        ROOT / "synlab/degrade/axes.py", ROOT / "synlab/degrade/physical_narrowband.py",
        ROOT / "synlab/degrade/narrowband.py", ROOT / "synlab/degrade/api.py",
        ROOT / "synlab/physical/fields.py", ROOT / "synlab/physical/sdf.py",
        ROOT / "synlab/physical/recipe.py", ROOT / "synlab/degrade/registry.py",
        PREVIOUS_DIAG, PREVIOUS_PNG, SNAPSHOT_SDF,
    ]
    code_file_hashes = {str(path): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
                        for path in code_paths if path.is_file()}
    try:
        import scipy
        scipy_version = scipy.__version__
    except Exception:
        scipy_version = None
    pkg = {
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": sys.platform,
        "numpy_version": np.__version__,
        "trimesh_version": importlib.metadata.version("trimesh"),
        "manifold3d_version": importlib.metadata.version("manifold3d"),
        "scipy_version": scipy_version,
        "trimesh_boolean_module": str(Path(trimesh.boolean.__file__).resolve()),
        "trimesh_boolean_module_sha256": sha256_file(Path(trimesh.boolean.__file__).resolve()),
        "manifold3d_module": str(Path(manifold3d.__file__).resolve()),
        "manifold3d_module_sha256": sha256_file(Path(manifold3d.__file__).resolve()),
    }
    metadata = {
        "schema": "a12.narrowband-mesh64-frozen-inputs.v1",
        "repo_root": str(ROOT), "output_dir": str(OUT),
        "fixture": "BUILTIN_PROBE_FIXTURE_ROUGH_INTERFACE",
        "source_metrics": source_metrics,
        "source_array_hashes": source_array_hashes,
        "probe_source_metadata": jsonable({k: v for k, v in (source_bundle.meta or {}).items()
                                            if isinstance(v, (str, int, float, bool, list, dict, type(None)))}),
        "cases": cases,
        "construction_counts": {
            "preparation_invocations": 1,
            "offset_body_constructions": 2,
            "operator_cases": 2,
            "boolean_calls": 0,
            "candidate_boolean_attempts": 0,
            "P03_paired_thickness_calls": 0,
        },
        "frozen_archive": {
            "path": str(PREPARED_NPZ), "bytes": PREPARED_NPZ.stat().st_size,
            "sha256": sha256_file(PREPARED_NPZ),
            "arrays": {name: array_record(value) for name, value in arrays.items()},
        },
        "dependencies": pkg,
        "source_file_hashes": code_file_hashes,
        "historical_diagnostic_source_hashes": prior.get("source_hashes_sha256", {}),
        "reconstruction_checks": {
            "basis_ids_match_prior_diagnostic": True,
            "source_topology_and_signed_volume_match_prior_diagnostic": True,
            "candidate_pre_boolean_topology_and_signed_volume_match_prior_diagnostic": True,
            "P02_P03_source_arrays_byte_equivalent": True,
            "compressed_archive_roundtrip_byte_equivalent": True,
        },
        "candidate_execution": {
            "status": "NOT_RUN_WAITING_FOR_MAIN_REVIEW",
            "mesh32_boolean_calls": 0, "mesh64_boolean_calls": 0,
            "max_boolean_attempts_if_approved": 4,
        },
    }
    PREPARED_META.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    print(json.dumps({
        "output_npz": str(PREPARED_NPZ), "npz_bytes": PREPARED_NPZ.stat().st_size,
        "npz_sha256": sha256_file(PREPARED_NPZ),
        "metadata": str(PREPARED_META), "metadata_sha256": sha256_file(PREPARED_META),
        "basis_ids": {x["axis_id"]: x["basis_id"] for x in cases},
        "candidate_volumes_signed_mm3": {x["axis_id"]: x["candidate_metrics"]["signed_volume_mm3"]
                                          for x in cases},
        "offset_body_constructions": 2, "boolean_calls": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
