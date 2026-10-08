from __future__ import annotations

import ast
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
CASE_IDS = ("P02_mesh32", "P02_mesh64", "P03_mesh32", "P03_mesh64")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def array_sha(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes(order="C")).hexdigest()


def face_areas(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    tri = vertices[faces]
    return np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) * 0.5


def edge_uses(faces: np.ndarray) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = defaultdict(int)
    for face in faces:
        ids = list(map(int, face))
        for u, v in ((ids[0], ids[1]), (ids[1], ids[2]), (ids[2], ids[0])):
            counts[(u, v) if u < v else (v, u)] += 1
    return counts


def choose_positive_area_hole_control(vertices: np.ndarray, faces: np.ndarray) -> tuple[int, float, np.ndarray, list[list[int]]]:
    areas = face_areas(vertices, faces)
    degenerate_ids = set(np.flatnonzero(areas == 0.0).astype(int).tolist())
    uses = edge_uses(faces)
    degenerate_vertices = set(map(int, faces[list(degenerate_ids)].reshape(-1)))
    candidates = []
    for face_id, face in enumerate(faces):
        if face_id in degenerate_ids or float(areas[face_id]) <= 0.0:
            continue
        ids = list(map(int, face))
        if len(set(ids)) != 3 or degenerate_vertices.intersection(ids):
            continue
        edges = [((ids[0], ids[1]) if ids[0] < ids[1] else (ids[1], ids[0])),
                 ((ids[1], ids[2]) if ids[1] < ids[2] else (ids[2], ids[1])),
                 ((ids[2], ids[0]) if ids[2] < ids[0] else (ids[0], ids[2]))]
        if all(uses[e] == 2 for e in edges):
            candidates.append((float(areas[face_id]), int(face_id), edges))
    if not candidates:
        raise RuntimeError("no isolated positive-area triangular face qualifies for the negative control")
    # The largest isolated positive-area triangle gives a clear three-edge opening.
    area, face_id, expected_edges = max(candidates, key=lambda row: (row[0], -row[1]))
    negative_faces = np.ascontiguousarray(np.delete(faces, face_id, axis=0), dtype=np.int64)
    after = edge_uses(negative_faces)
    boundary = sorted([list(edge) for edge, count in after.items() if count == 1])
    nonmanifold = [list(edge) for edge, count in after.items() if count > 2]
    if set(map(tuple, boundary)) != set(expected_edges) or nonmanifold:
        raise RuntimeError("negative control does not create exactly the selected positive-area triangle's three boundary edges")
    return face_id, area, negative_faces, boundary


def main() -> None:
    frozen: dict[str, np.ndarray] = {}
    case_rows = []
    source_root = SOURCE
    for case_id in CASE_IDS:
        axis, mode = case_id.split("_", 1)
        npz_path = source_root / f"output_{axis}_{mode}.npz"
        result_path = source_root / f"result_{axis}_{mode}.json"
        result = json.loads(result_path.read_text(encoding="utf-8-sig"))
        if result.get("status") != "completed" or result.get("boolean_calls_attempted") != 1:
            raise RuntimeError(f"saved worker receipt is not a completed single-call output: {case_id}")
        with np.load(npz_path, allow_pickle=False) as source_arrays:
            if "raw_vertices" not in source_arrays.files or "raw_faces" not in source_arrays.files:
                raise RuntimeError(f"saved worker NPZ is missing raw arrays: {case_id}")
            vertices = np.ascontiguousarray(source_arrays["raw_vertices"], dtype=np.float64)
            faces = np.ascontiguousarray(source_arrays["raw_faces"], dtype=np.int64)
        frozen[f"{case_id}_raw_vertices_f64"] = vertices
        frozen[f"{case_id}_raw_faces_i64"] = faces
        case_rows.append({
            "case_id": case_id,
            "source_output_npz": {"path": str(npz_path.resolve()), "bytes": npz_path.stat().st_size,
                                  "sha256": sha(npz_path)},
            "source_result_json": {"path": str(result_path.resolve()), "bytes": result_path.stat().st_size,
                                   "sha256": sha(result_path)},
            "vertices": {"dtype": vertices.dtype.str, "shape": list(vertices.shape),
                         "nbytes": vertices.nbytes, "sha256_c_order_bytes": array_sha(vertices)},
            "faces": {"dtype": faces.dtype.str, "shape": list(faces.shape),
                      "nbytes": faces.nbytes, "sha256_c_order_bytes": array_sha(faces)},
        })

    negative_case_id = "P02_mesh64"
    base_v = frozen[f"{negative_case_id}_raw_vertices_f64"]
    base_f = frozen[f"{negative_case_id}_raw_faces_i64"]
    removed_id, removed_area, negative_f, expected_boundary = choose_positive_area_hole_control(base_v, base_f)
    frozen[f"{negative_case_id}_hole_negative_vertices_f64"] = base_v.copy()
    frozen[f"{negative_case_id}_hole_negative_faces_i64"] = negative_f

    archive_path = HERE / "frozen_retessellation_inputs.npz"
    if archive_path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen input archive: {archive_path}")
    np.savez_compressed(archive_path, **frozen)
    arrays_meta = {name: {"dtype": value.dtype.str, "shape": list(value.shape),
                          "nbytes": value.nbytes, "sha256_c_order_bytes": array_sha(value)}
                   for name, value in frozen.items()}
    candidate_source = HERE / "conforming_retessellate_candidate.py"
    ast.parse(candidate_source.read_text(encoding="utf-8"), filename=str(candidate_source))
    candidate_plan = {
        "scope": "offline local edge-conformance candidate only; no production code, operator, Boolean, or test",
        "qualification": ["three distinct vertex IDs", "exact zero area and exact collinearity",
                          "middle vertex strictly inside unique longest edge", "one positive-area neighbor on long edge and both short spans",
                          "each edge incidence exactly two before change", "long-edge target face unique across all loops"],
        "operation": "replace each qualified positive-area long-edge neighbor with two winding-preserving child faces using the existing middle vertex, then remove exactly the corresponding zero-area triangle",
        "forbidden": ["move or create vertices", "fill positive-area holes", "abs(signed_volume)", "delete components", "generic mesh healing", "rerun any Boolean"],
        "acceptance": {"boundary_edges": 0, "nonmanifold_edges": 0, "orientation_conflict_edges": 0,
                       "exact_zero_area_faces": 0, "signed_volume_positive": True,
                       "signed_volume_abs_delta_max_mm3": 1e-10,
                       "signed_volume_relative_delta_max": 1e-12,
                       "surface_area_tolerance": "max(1e-10 mm^2, 1e-12 * abs(raw surface area))",
                       "vertices_byte_identical": True, "component_count_preserved": True},
        "negative_control": "A positive-area triangle is omitted from a closed saved raw mesh. The candidate must reject its three unexplained boundary edges without modifying or capping that input.",
        "face_lineage": "Lineage points only to saved raw Boolean output face-row IDs. Operand/mother/source-versus-candidate material ancestry is UNKNOWN; it must not qualify physical R2 or pretraining use.",
        "no_execution_yet": True,
    }
    manifest = {
        "schema": "a12.conforming-retessellation-frozen-inputs.v1",
        "repo_root": str(Path.cwd().resolve()), "output_dir": str(HERE.resolve()),
        "source_candidate": {"path": str(candidate_source.resolve()), "bytes": candidate_source.stat().st_size,
                             "sha256": sha(candidate_source)},
        "source_preparation_script": {"path": str(Path(__file__).resolve()), "bytes": Path(__file__).stat().st_size,
                                       "sha256": sha(Path(__file__))},
        "source_preflight_manifest_sha256": sha(source_root / "preflight_manifest.json"),
        "source_execution_addendum_sha256": sha(source_root / "candidate_execution_addendum.json"),
        "source_postexecution_hash_snapshot_sha256": sha(source_root / "postexecution_preflight_hash_snapshot.json"),
        "cases": case_rows,
        "negative_control": {"case_id": negative_case_id, "kind": "single_positive_area_triangle_removed",
                              "removed_positive_area_face_id": removed_id,
                              "removed_face_area_mm2": removed_area,
                              "expected_boundary_edges": expected_boundary,
                              "expected_boundary_edge_count": 3,
                              "purpose": "must be rejected; no automatic cap of a positive-area opening"},
        "frozen_archive": {"path": str(archive_path.resolve()), "bytes": archive_path.stat().st_size,
                           "sha256": sha(archive_path), "arrays": arrays_meta},
        "planned_run": {"source_is_not_executed_by_freezer": True, "candidate_execution_authorized": False,
                        "candidate_boolean_calls": 0, "candidate_repair_calls": 0,
                        "candidate_cases": list(CASE_IDS) + [f"{negative_case_id}_positive_area_hole_negative"]},
        "candidate_plan": candidate_plan,
    }
    manifest_path = HERE / "frozen_retessellation_manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen manifest: {manifest_path}")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"frozen_archive": str(archive_path), "archive_sha256": sha(archive_path),
                      "manifest": str(manifest_path), "manifest_sha256": sha(manifest_path),
                      "negative_control_face_id": removed_id, "negative_control_face_area_mm2": removed_area,
                      "negative_control_boundary_edge_count": len(expected_boundary),
                      "candidate_source_sha256": sha(candidate_source), "candidate_not_executed": True},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
