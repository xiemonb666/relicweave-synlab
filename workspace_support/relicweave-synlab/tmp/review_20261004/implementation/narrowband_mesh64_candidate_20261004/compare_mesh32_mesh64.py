from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
FROZEN_NPZ = OUT / "frozen_inputs.npz"
FROZEN_META = OUT / "frozen_inputs.json"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def array_digest(array: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(array)
    return sha_bytes(contiguous.tobytes(order="C"))


def safe_text(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def mesh_from_arrays(vertices: np.ndarray, faces: np.ndarray):
    import trimesh

    return trimesh.Trimesh(vertices=np.ascontiguousarray(vertices),
                           faces=np.ascontiguousarray(faces), process=False)


def boundary_report(mesh) -> dict:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(faces) == 0:
        bedges = np.empty((0, 2), dtype=np.int64)
        nonmanifold = np.empty((0, 2), dtype=np.int64)
    else:
        pairs = np.sort(np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]],
                                        faces[:, [2, 0]])), axis=1)
        unique, counts = np.unique(pairs, axis=0, return_counts=True)
        bedges = unique[counts == 1]
        nonmanifold = unique[counts > 2]
    rows = []
    for edge in bedges:
        a, b = map(int, edge)
        rows.append({
            "vertex_indices": [a, b],
            "p0_mm": vertices[a].tolist(),
            "p1_mm": vertices[b].tolist(),
        })
    return {"edges": rows, "boundary_edge_count": int(len(bedges)),
            "nonmanifold_edge_count": int(len(nonmanifold))}


def mesh_report(mesh, *, native_status=None, stage: str) -> dict:
    vertices = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.faces)
    if len(faces):
        try:
            degenerate = int(len(faces) - int(mesh.nondegenerate_faces(height=1e-12).sum()))
        except Exception as exc:
            degenerate = None
            degenerate_error = f"{type(exc).__name__}: {exc}"
        else:
            degenerate_error = None
        areas = np.asarray(mesh.area_faces, dtype=np.float64)
        min_area = float(np.nanmin(areas)) if len(areas) else None
    else:
        degenerate = 0
        degenerate_error = None
        min_area = None
    try:
        signed_volume = float(mesh.volume)
        volume_error = None
    except Exception as exc:
        signed_volume = None
        volume_error = f"{type(exc).__name__}: {exc}"
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
    result = {
        "stage": stage,
        "vertices": int(len(vertices)), "faces": int(len(faces)),
        "vertex_dtype": vertices.dtype.str, "face_dtype": faces.dtype.str,
        "boundary_edges": boundary_report(mesh)["boundary_edge_count"],
        "nonmanifold_edges": boundary_report(mesh)["nonmanifold_edge_count"],
        "degenerate_faces_height_1e-12": degenerate,
        "min_face_area_mm2": min_area,
        "signed_volume_mm3": signed_volume,
        "watertight": watertight, "winding_consistent": winding, "is_volume": is_volume,
        "bounds_mm": bounds.tolist() if bounds is not None else None,
        "volume_error": volume_error, "topology_error": topology_error,
        "degenerate_error": degenerate_error,
        "native_status": native_status,
    }
    result["boundary_coordinates"] = boundary_report(mesh)["edges"]
    return result


def input_hash_check(case_id: str, arrays: dict[str, np.ndarray], meta: dict) -> None:
    case = next(row for row in meta["cases"] if row["axis_id"] == case_id)
    for name, expected in case["frozen_arrays"].items():
        actual = np.ascontiguousarray(arrays[name])
        if actual.dtype.str != expected["dtype"] or list(actual.shape) != expected["shape"]:
            raise RuntimeError(f"frozen array dtype/shape changed: {name}")
        if actual.nbytes != expected["nbytes"] or array_digest(actual) != expected["sha256_c_order_bytes"]:
            raise RuntimeError(f"frozen array byte hash changed: {name}")


def clean_mesh_trace(mesh, S) -> tuple[object, list[dict]]:
    import trimesh

    work = mesh.copy()
    stages = [mesh_report(work, stage="clean_mesh.input")]
    work.merge_vertices()
    stages.append(mesh_report(work, stage="clean_mesh.after_merge_vertices"))
    mask = work.nondegenerate_faces(height=1e-12)
    before = len(work.faces)
    work.update_faces(mask)
    stage = mesh_report(work, stage="clean_mesh.after_degenerate_face_filter")
    stage["faces_removed_at_stage"] = int(before - len(work.faces))
    stages.append(stage)
    work.remove_unreferenced_vertices()
    stages.append(mesh_report(work, stage="clean_mesh.after_remove_unreferenced_vertices"))
    trimesh.repair.fix_winding(work)
    stages.append(mesh_report(work, stage="clean_mesh.after_fix_winding"))
    trimesh.repair.fix_inversion(work)
    stages.append(mesh_report(work, stage="clean_mesh.after_fix_inversion"))
    actual = S.clean_mesh(mesh)
    stages.append(mesh_report(actual, stage="clean_mesh.actual_function_output"))
    return actual, stages


def load_frozen(case_id: str) -> tuple[dict[str, np.ndarray], dict]:
    meta = json.loads(FROZEN_META.read_text(encoding="utf-8"))
    archive_sha = hashlib.sha256(FROZEN_NPZ.read_bytes()).hexdigest()
    if archive_sha != meta["frozen_archive"]["sha256"]:
        raise RuntimeError("frozen NPZ whole-file SHA256 does not match frozen_inputs.json")
    with np.load(FROZEN_NPZ, allow_pickle=False) as frozen:
        arrays = {name: np.ascontiguousarray(frozen[name]) for name in frozen.files}
    input_hash_check(case_id, arrays, meta)
    return arrays, meta


def native_input_inspection(case_id: str, path: str,
                            arrays: dict[str, np.ndarray]) -> tuple[dict, dict]:
    import manifold3d

    suffix = "mesh32" if path == "mesh32" else "mesh64"
    result = {}
    manifolds = {}
    for label in ("candidate", "source"):
        vertices = arrays[f"{case_id}_{label}_vertices_f64"]
        faces = arrays[f"{case_id}_{label}_faces_i64"]
        if suffix == "mesh32":
            vertex_cast = np.ascontiguousarray(vertices, dtype=np.float32)
            face_cast = np.ascontiguousarray(faces, dtype=np.uint32)
            native_mesh = manifold3d.Mesh(vert_properties=vertex_cast, tri_verts=face_cast)
            vertex_dtype, face_dtype = vertex_cast.dtype.str, face_cast.dtype.str
            back_fn = "to_mesh"
        else:
            vertex_cast = np.ascontiguousarray(vertices, dtype=np.float64)
            face_cast = np.ascontiguousarray(faces, dtype=np.uint64)
            native_mesh = manifold3d.Mesh64(vert_properties=vertex_cast, tri_verts=face_cast)
            vertex_dtype, face_dtype = vertex_cast.dtype.str, face_cast.dtype.str
            back_fn = "to_mesh64"
        manifold = manifold3d.Manifold(mesh=native_mesh)
        manifolds[label] = manifold
        status = str(manifold.status())
        roundtrip = getattr(manifold, back_fn)()
        out_vertices = np.asarray(roundtrip.vert_properties)
        out_faces = np.asarray(roundtrip.tri_verts)
        # These are pre-Boolean input constructor/round-trip metrics, not a repair step.
        roundtrip_mesh = mesh_from_arrays(out_vertices[:, :3], out_faces.astype(np.int64, copy=False))
        result[label] = {
            "cast_vertex_dtype": vertex_dtype, "cast_face_dtype": face_dtype,
            "cast_vertices_sha256": array_digest(vertex_cast),
            "cast_faces_sha256": array_digest(face_cast),
            "constructor_status": status,
            "is_empty": bool(manifold.is_empty()),
            "num_triangles": int(manifold.num_tri()),
            "native_volume_mm3": float(manifold.volume()),
            "roundtrip_dtype": {
                "vertex_properties": out_vertices.dtype.str, "tri_verts": out_faces.dtype.str,
                "vertex_properties_shape": list(out_vertices.shape),
                "tri_verts_shape": list(out_faces.shape),
            },
            "roundtrip_mesh_metrics": mesh_report(
                roundtrip_mesh, native_status=status, stage=f"{path}.input.{label}.native_roundtrip"),
        }
    return result, manifolds


def worker(case_id: str, path: str) -> int:
    import manifold3d
    import trimesh
    from synlab.physical import sdf as S

    result_path = OUT / f"result_{case_id}_{path}.json"
    output_path = OUT / f"output_{case_id}_{path}.npz"
    if result_path.exists() or output_path.exists():
        print(json.dumps({"case": case_id, "path": path,
                          "status": "refused_existing_output_preserved",
                          "existing_result": result_path.exists(),
                          "existing_output": output_path.exists()}, ensure_ascii=False))
        return 4
    started = time.perf_counter()
    arrays, meta = load_frozen(case_id)
    case = next(row for row in meta["cases"] if row["axis_id"] == case_id)
    cand_v = arrays[f"{case_id}_candidate_vertices_f64"]
    cand_f = arrays[f"{case_id}_candidate_faces_i64"]
    src_v = arrays[f"{case_id}_source_vertices_f64"]
    src_f = arrays[f"{case_id}_source_faces_i64"]
    cand = mesh_from_arrays(cand_v, cand_f)
    source = mesh_from_arrays(src_v, src_f)
    record = {
        "schema": "a12.narrowband-mesh64-single-attempt.v1",
        "axis_id": case_id, "level": 1, "path": path,
        "basis_id": case["basis_id"], "frozen_npz_sha256": meta["frozen_archive"]["sha256"],
        "argv": sys.argv, "cwd": str(Path.cwd()),
        "boolean_calls_attempted": 0, "elapsed_seconds": None,
        "status": "started", "inputs": {}, "stages": [], "errors": [],
    }
    record["inputs"]["candidate"] = mesh_report(cand, stage="frozen_input.candidate_float64")
    record["inputs"]["source"] = mesh_report(source, stage="frozen_input.source_float64")
    try:
        if path == "mesh32" and not all(mesh.is_volume for mesh in (cand, source)):
            raise ValueError("Not all meshes are volumes!")
        record["native_inputs"], input_manifolds = native_input_inspection(
            case_id, path, arrays)
        record["native_input_statuses_for_boolean"] = {
            label: str(input_manifolds[label].status()) for label in ("candidate", "source")}
        if path == "mesh32":
            # This is an exact two-input transcription of Trimesh 5.1.0's inspected
            # boolean_manifold implementation so the raw Manifold status remains observable.
            # Its check_volume, float32/uint32 casts, Manifold XOR, to_mesh, and Trimesh
            # process=False conversion are unchanged; no global monkeypatch is used.
            record["boolean_order"] = ["candidate", "source"]
            record["boolean_api"] = (
                "Trimesh 5.1.0 boolean_manifold intersection body, transcribed exactly: "
                "check_volume; float32/uint32 Mesh constructors; left ^ right; to_mesh; "
                "Trimesh(process=False)")
            record["boolean_adapter_source_sha256"] = hashlib.sha256(
                Path(trimesh.boolean.__file__).read_bytes()).hexdigest()
            call_started = time.perf_counter()
            record["boolean_calls_attempted"] = 1
            output = input_manifolds["candidate"] ^ input_manifolds["source"]
            record["boolean_elapsed_seconds"] = time.perf_counter() - call_started
            record["native_output_status"] = str(output.status())
            record["native_output"] = {
                "is_empty": bool(output.is_empty()), "num_triangles": int(output.num_tri()),
                "native_volume_mm3": float(output.volume()),
            }
            raw_native = output.to_mesh()
            raw_native_arrays = {
                "native_vertex_properties": np.ascontiguousarray(raw_native.vert_properties),
                "native_tri_verts": np.ascontiguousarray(raw_native.tri_verts),
            }
            raw = trimesh.Trimesh(vertices=raw_native.vert_properties,
                                  faces=raw_native.tri_verts, process=False)
        else:
            record["boolean_order"] = ["candidate", "source"]
            record["boolean_api"] = "manifold3d.Manifold(Mesh64(candidate)) ^ Manifold(Mesh64(source)); to_mesh64()"
            call_started = time.perf_counter()
            record["boolean_calls_attempted"] = 1
            output = input_manifolds["candidate"] ^ input_manifolds["source"]
            record["boolean_elapsed_seconds"] = time.perf_counter() - call_started
            record["native_output_status"] = str(output.status())
            record["native_output"] = {
                "is_empty": bool(output.is_empty()), "num_triangles": int(output.num_tri()),
                "native_volume_mm3": float(output.volume()),
            }
            raw_native = output.to_mesh64()
            raw_native_arrays = {
                "native_vertex_properties": np.ascontiguousarray(raw_native.vert_properties),
                "native_tri_verts": np.ascontiguousarray(raw_native.tri_verts),
            }
            out_vertices = np.asarray(raw_native.vert_properties)
            out_faces = np.asarray(raw_native.tri_verts)
            raw = mesh_from_arrays(out_vertices[:, :3], out_faces.astype(np.int64, copy=False))
        record["stages"].append(mesh_report(raw, native_status=record.get("native_output_status"),
                                           stage=f"{path}.native_boolean_output"))
        cleaned, clean_stages = clean_mesh_trace(raw, S)
        record["stages"].extend(clean_stages)
        record["status"] = "completed"
        record["output_npz"] = str(output_path)
        save_arrays = {
            "raw_vertices": np.ascontiguousarray(raw.vertices),
            "raw_faces": np.ascontiguousarray(raw.faces),
            "clean_vertices": np.ascontiguousarray(cleaned.vertices),
            "clean_faces": np.ascontiguousarray(cleaned.faces),
            **raw_native_arrays,
        }
        np.savez_compressed(record["output_npz"], **save_arrays)
        record["output_arrays"] = {name: {
            "dtype": np.asarray(value).dtype.str, "shape": list(np.asarray(value).shape),
            "sha256_c_order_bytes": array_digest(np.asarray(value))
        } for name, value in save_arrays.items()}
    except Exception as exc:
        record["status"] = "failed"
        record["errors"].append({
            "type": type(exc).__name__, "message": str(exc),
            "traceback": traceback.format_exc(),
        })
    finally:
        record["elapsed_seconds"] = time.perf_counter() - started
        record["result_json"] = str(result_path)
        result_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    print(json.dumps({"case": case_id, "path": path, "status": record["status"],
                      "boolean_calls_attempted": record["boolean_calls_attempted"],
                      "elapsed_seconds": record["elapsed_seconds"],
                      "result_json": record["result_json"]}, ensure_ascii=False))
    return 0 if record["status"] == "completed" else 2


def orchestrate() -> int:
    protected = [OUT / "candidate_progress.json", OUT / "candidate_comparison.json"]
    protected.extend(OUT / f"result_{axis}_{path}.json"
                     for axis in ("P02", "P03") for path in ("mesh32", "mesh64"))
    protected.extend(OUT / f"output_{axis}_{path}.npz"
                     for axis in ("P02", "P03") for path in ("mesh32", "mesh64"))
    existing = [str(path) for path in protected if path.exists()]
    if existing:
        print(json.dumps({"status": "refused_existing_outputs_preserved",
                          "existing_paths": existing}, ensure_ascii=False))
        return 4
    attempts = []
    tasks = [(axis, path) for axis in ("P02", "P03") for path in ("mesh32", "mesh64")]
    for axis, path in tasks:
        argv = [sys.executable, str(Path(__file__).resolve()), "--worker", axis, path]
        started = time.perf_counter()
        row = {"axis_id": axis, "path": path, "argv": argv,
               "cwd": str(ROOT), "timeout_seconds": 60,
               "planned_boolean_call_count": 1,
               "actual_boolean_call_count": None,
               "actual_call_count_status": "unknown_until_worker_receipt"}
        try:
            completed = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                                       timeout=60, check=False)
            row.update({"exit_code": completed.returncode,
                        "stdout": safe_text(completed.stdout),
                        "stderr": safe_text(completed.stderr),
                        "elapsed_seconds": time.perf_counter() - started,
                        "timed_out": False})
            result_path = OUT / f"result_{axis}_{path}.json"
            if result_path.is_file():
                row["result_json"] = str(result_path)
                row["result_json_sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
                worker_result = json.loads(result_path.read_text(encoding="utf-8"))
                row["actual_boolean_call_count"] = worker_result.get("boolean_calls_attempted")
                row["actual_call_count_status"] = "reported_by_completed_worker_receipt"
            else:
                row["actual_call_count_status"] = (
                    "unknown_no_worker_receipt; process may have failed before recording progress")
        except subprocess.TimeoutExpired as exc:
            row.update({"exit_code": None, "stdout": safe_text(exc.stdout),
                        "stderr": safe_text(exc.stderr),
                        "elapsed_seconds": time.perf_counter() - started,
                        "timed_out": True, "timeout_failure_preserved": True,
                        "actual_boolean_call_count": None,
                        "actual_call_count_status": (
                            "unknown_timeout; the call may have begun but no completed worker receipt exists")})
        except OSError as exc:
            row.update({"exit_code": None, "stdout": None,
                        "stderr": f"{type(exc).__name__}: {exc}",
                        "elapsed_seconds": time.perf_counter() - started,
                        "timed_out": False,
                        "actual_boolean_call_count": 0,
                        "actual_call_count_status": "zero_process_launch_failed_before_worker_start"})
        attempts.append(row)
        live = {
            "schema": "a12.narrowband-mesh64-candidate-progress.v1",
            "candidate_authorization": "explicit --execute-approved supplied",
            "planned_boolean_calls_max": 4,
            "attempts": attempts,
        }
        (OUT / "candidate_progress.json").write_text(
            json.dumps(live, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    aggregate = {
        "schema": "a12.narrowband-mesh32-mesh64-comparison.v1",
        "repo_root": str(ROOT), "candidate_authorization": "explicit --execute-approved supplied",
        "attempt_count": len(attempts), "boolean_call_attempt_cap": 4,
        "attempts": attempts,
        "interpretation_limit": "At most two rough-probe cases; this is not production acceptance or physical wall-thickness validation.",
    }
    (OUT / "candidate_comparison.json").write_text(
        json.dumps(aggregate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if all(row.get("exit_code") == 0 for row in attempts) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded native Mesh32/Mesh64 Boolean comparison.")
    parser.add_argument("--execute-approved", action="store_true",
                        help="run at most one Mesh32 and one Mesh64 Boolean per frozen case")
    parser.add_argument("--worker", nargs=2, metavar=("AXIS", "PATH"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        axis, path = args.worker
        if axis not in {"P02", "P03"} or path not in {"mesh32", "mesh64"}:
            parser.error("invalid internal worker pair")
        return worker(axis, path)
    if not args.execute_approved:
        print("Candidate execution not authorized. Frozen inputs are ready; no Boolean was called.")
        return 3
    if not FROZEN_NPZ.is_file() or not FROZEN_META.is_file():
        parser.error("frozen input archive/manifest missing")
    return orchestrate()


if __name__ == "__main__":
    raise SystemExit(main())
