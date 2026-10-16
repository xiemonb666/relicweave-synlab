from __future__ import annotations

"""Offline candidate only. It consumes saved native Boolean arrays and never calls Boolean APIs."""

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
INPUT_NPZ = HERE / "frozen_retessellation_inputs.npz"
INPUT_MANIFEST = HERE / "frozen_retessellation_manifest.json"
OUTPUT_NPZ = HERE / "retessellated_candidate_outputs.npz"
OUTPUT_JSON = HERE / "retessellated_candidate_report.json"
CASE_IDS = ("P02_mesh32", "P02_mesh64", "P03_mesh32", "P03_mesh64")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def array_sha(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes(order="C")).hexdigest()


def face_areas(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    tri = vertices[faces]
    return np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) * 0.5


def signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    tri = vertices[faces]
    return float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)


def edge_uses(faces: np.ndarray) -> dict[tuple[int, int], list[tuple[int, int]]]:
    uses: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for face_id, face in enumerate(faces):
        ids = list(map(int, face))
        for u, v in ((ids[0], ids[1]), (ids[1], ids[2]), (ids[2], ids[0])):
            key = (u, v) if u < v else (v, u)
            direction = 1 if u < v else -1
            uses[key].append((int(face_id), direction))
    return uses


def component_count(faces: np.ndarray) -> int:
    if len(faces) == 0:
        return 0
    parent = list(range(len(faces)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for use in edge_uses(faces).values():
        if len(use) > 1:
            first = use[0][0]
            for face_id, _ in use[1:]:
                union(first, face_id)
    return len({find(i) for i in range(len(faces))})


def metrics(vertices: np.ndarray, faces: np.ndarray) -> dict:
    areas = face_areas(vertices, faces)
    uses = edge_uses(faces)
    boundary = [edge for edge, edge_use in uses.items() if len(edge_use) == 1]
    nonmanifold = [edge for edge, edge_use in uses.items() if len(edge_use) > 2]
    orientation_conflicts = [edge for edge, edge_use in uses.items()
                             if len(edge_use) == 2 and sum(d for _, d in edge_use) != 0]
    volume = signed_volume(vertices, faces)
    return {
        "vertices": int(len(vertices)), "faces": int(len(faces)),
        "boundary_edges": len(boundary), "boundary_edge_ids": [list(e) for e in boundary],
        "nonmanifold_edges": len(nonmanifold), "nonmanifold_edge_ids": [list(e) for e in nonmanifold],
        "orientation_conflict_edges": len(orientation_conflicts),
        "zero_area_faces_exact": int(np.count_nonzero(areas == 0.0)),
        "min_area_mm2": float(np.min(areas)) if len(areas) else None,
        "surface_area_mm2": float(areas.sum()), "signed_volume_mm3": volume,
        "positive_signed_volume": bool(volume > 0.0), "component_count_by_shared_edges": component_count(faces),
        "is_closed_oriented_positive_volume": bool(
            not boundary and not nonmanifold and not orientation_conflicts and volume > 0.0),
    }


def sorted_edge(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def oriented_long_edge(face: np.ndarray, endpoint_set: set[int]) -> tuple[int, int, int] | None:
    ids = list(map(int, face))
    for i in range(3):
        a, b = ids[i], ids[(i + 1) % 3]
        if {a, b} == endpoint_set:
            return a, b, ids[(i + 2) % 3]
    return None


def inspect_degenerate_loop(
    vertices: np.ndarray,
    faces: np.ndarray,
    face_areas_mm2: np.ndarray,
    uses: dict[tuple[int, int], list[tuple[int, int]]],
    face_id: int,
) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    face = np.asarray(faces[face_id], dtype=np.int64)
    if len(set(map(int, face))) != 3:
        return None, ["degenerate_face_does_not_have_three_distinct_vertex_ids"]
    xyz = vertices[face]
    if face_areas_mm2[face_id] != 0.0:
        return None, ["candidate_face_is_not_exact_zero_area"]
    pairs = ((0, 1), (1, 2), (2, 0))
    lengths = [float(np.linalg.norm(xyz[i] - xyz[j])) for i, j in pairs]
    max_length = max(lengths)
    if max_length <= 0.0 or lengths.count(max_length) != 1:
        return None, ["longest_edge_is_zero_or_ambiguous"]
    ai, bi = pairs[lengths.index(max_length)]
    mi = next(i for i in range(3) if i not in (ai, bi))
    a_id, b_id, m_id = int(face[ai]), int(face[bi]), int(face[mi])
    a, b, m = xyz[ai], xyz[bi], xyz[mi]
    line = b - a
    length_sq = float(np.dot(line, line))
    cross = np.cross(m - a, line)
    if not np.array_equal(cross, np.zeros(3, dtype=np.float64)):
        errors.append("middle_vertex_not_exactly_collinear_with_long_edge")
    t = float(np.dot(m - a, line) / length_sq)
    projected = a + t * line
    line_distance = float(np.linalg.norm(m - projected))
    if not (0.0 < t < 1.0):
        errors.append("middle_vertex_not_strictly_inside_long_edge")

    spans = {
        "long": sorted_edge(a_id, b_id),
        "short_a_mid": sorted_edge(a_id, m_id),
        "short_mid_b": sorted_edge(m_id, b_id),
    }
    neighbors: dict[str, dict] = {}
    for label, edge in spans.items():
        adjacent = [other_id for other_id, _ in uses.get(edge, []) if other_id != face_id]
        if len(uses.get(edge, [])) != 2 or len(adjacent) != 1:
            errors.append(f"{label}_edge_does_not_have_exactly_one_other_face"); continue
        other_id = adjacent[0]
        other_area = float(face_areas_mm2[other_id])
        if other_area <= 0.0:
            errors.append(f"{label}_edge_neighbor_is_not_positive_area")
        neighbors[label] = {"face_id": int(other_id), "area_mm2": other_area,
                            "edge_vertex_ids": list(edge)}
    if set(neighbors) != set(spans):
        return None, errors or ["incomplete_span_neighbor_evidence"]
    long_neighbor_id = neighbors["long"]["face_id"]
    oriented = oriented_long_edge(faces[long_neighbor_id], {a_id, b_id})
    if oriented is None:
        errors.append("long_edge_neighbor_does_not_contain_exact_endpoint_pair")
        return None, errors
    oriented_a, oriented_b, third = oriented
    if m_id in set(map(int, faces[long_neighbor_id])):
        errors.append("middle_vertex_already_in_long_neighbor_face")
    loop = {
        "degenerate_face_id": int(face_id), "degenerate_vertex_ids": list(map(int, face)),
        "degenerate_vertex_coordinates_mm": xyz.tolist(), "degenerate_area_mm2": float(face_areas_mm2[face_id]),
        "long_edge_endpoint_ids": [a_id, b_id], "middle_vertex_id": m_id,
        "long_edge_length_mm": max_length, "middle_projection_t": t,
        "middle_to_long_edge_distance_mm": line_distance,
        "middle_strictly_inside": bool(0.0 < t < 1.0),
        "span_neighbors": neighbors,
        "split_target_face_id": int(long_neighbor_id),
        "split_target_oriented_edge_ids": [oriented_a, oriented_b],
        "split_target_third_vertex_id": int(third),
        "all_preconditions_met": not errors,
        "rejections": errors,
    }
    return loop, errors


def analyze_case(vertices: np.ndarray, faces: np.ndarray) -> dict:
    areas = face_areas(vertices, faces)
    uses = edge_uses(faces)
    base = metrics(vertices, faces)
    rejection_reasons = []
    if base["boundary_edges"]:
        rejection_reasons.append("input_has_unexplained_boundary_edges; refusing to cap or alter positive-area opening")
    if base["nonmanifold_edges"]:
        rejection_reasons.append("input_has_nonmanifold_edges")
    if base["orientation_conflict_edges"]:
        rejection_reasons.append("input_has_orientation_conflicts")
    degenerate_ids = np.flatnonzero(areas == 0.0).astype(int).tolist()
    loops = []
    for face_id in degenerate_ids:
        row, errors = inspect_degenerate_loop(vertices, faces, areas, uses, face_id)
        if row is not None:
            loops.append(row)
        rejection_reasons.extend(f"face_{face_id}:{error}" for error in errors)
    if not degenerate_ids:
        rejection_reasons.append("no_exact_zero_area_faces_to_remove")
    expected_face_ids = set(degenerate_ids)
    if len(loops) != len(expected_face_ids):
        rejection_reasons.append("not_every_exact_zero_area_face_has_a_qualified_loop")
    long_targets = [x["split_target_face_id"] for x in loops if "split_target_face_id" in x]
    if len(long_targets) != len(set(long_targets)):
        rejection_reasons.append("split_target_long_neighbor_is_reused_or_conflicting")
    eligible = bool(not rejection_reasons and len(loops) == 7)
    return {"input_metrics": base, "exact_zero_area_face_ids": degenerate_ids,
            "loops": loops, "eligible": eligible,
            "rejection_reasons": sorted(set(rejection_reasons))}


def transform_case(vertices: np.ndarray, faces: np.ndarray, analysis: dict) -> tuple[np.ndarray, list[dict], list[dict]]:
    if not analysis["eligible"]:
        raise ValueError("transform_case may only run after every qualification gate passes")
    remove_ids = {row["degenerate_face_id"] for row in analysis["loops"]}
    split_by_face = {row["split_target_face_id"]: row for row in analysis["loops"]}
    output: list[list[int]] = []
    lineage: list[dict] = []
    split_checks: list[dict] = []
    for face_id, face_raw in enumerate(faces):
        face = list(map(int, face_raw))
        if face_id in remove_ids:
            lineage.append({"kind": "removed_zero_area_face", "parent_face_id": face_id,
                            "reason": "exactly_collinear_zero_area_triangle; corresponding long edge split and both short-span neighbors proven"})
            continue
        if face_id in split_by_face:
            loop = split_by_face[face_id]
            a, b = loop["split_target_oriented_edge_ids"]
            m, c = loop["middle_vertex_id"], loop["split_target_third_vertex_id"]
            children = ([a, m, c], [m, b, c])
            output.extend(children)
            parent_area = float(face_areas(vertices, faces[[face_id]])[0])
            child_areas = face_areas(vertices, np.asarray(children, dtype=np.int64))
            tri = vertices[np.asarray(face, dtype=np.int64)]
            parent_normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
            child_normals = []
            for child in children:
                child_xyz = vertices[np.asarray(child, dtype=np.int64)]
                child_normals.append(np.cross(child_xyz[1] - child_xyz[0], child_xyz[2] - child_xyz[0]))
            orientation_dots = [float(np.dot(parent_normal, normal)) for normal in child_normals]
            area_delta = float(child_areas.sum() - parent_area)
            split_checks.append({
                "parent_face_id": face_id, "parent_area_mm2": parent_area,
                "child_areas_mm2": child_areas.tolist(), "child_area_sum_delta_mm2": area_delta,
                "child_normal_dot_parent": orientation_dots,
                "middle_edge_distance_mm": loop["middle_to_long_edge_distance_mm"],
                "middle_projection_t": loop["middle_projection_t"],
                "local_partition_valid": bool(
                    all(float(a_) > 0.0 for a_ in child_areas)
                    and all(value > 0.0 for value in orientation_dots)
                    and loop["middle_to_long_edge_distance_mm"] == 0.0
                    and 0.0 < loop["middle_projection_t"] < 1.0),
            })
            lineage.append({"kind": "split_long_edge_face", "parent_face_id": face_id,
                            "children": [{"child_ordinal": i, "vertex_ids": child}
                                         for i, child in enumerate(children)],
                            "inserted_vertex_id": m, "winding_rule": "parent directed edge order retained"})
            continue
        output.append(face)
        lineage.append({"kind": "unchanged", "parent_face_id": face_id,
                        "child_vertex_ids": face})
    return np.ascontiguousarray(output, dtype=np.int64), lineage, split_checks


def case_result(vertices: np.ndarray, faces: np.ndarray, case_id: str) -> tuple[dict, np.ndarray | None]:
    before = analyze_case(vertices, faces)
    record = {"case_id": case_id, **before, "candidate_executed": False}
    if not before["eligible"]:
        record["status"] = "rejected_without_modification"
        record["candidate_metrics"] = None
        record["vertex_bytes_unchanged"] = True
        record["surface_area_delta_mm2"] = None
        record["signed_volume_delta_mm3"] = None
        record["component_count_preserved"] = None
        record["face_lineage"] = []
        return record, None

    candidate_faces, lineage, split_checks = transform_case(vertices, faces, before)
    candidate_vertices = vertices.copy()
    after = metrics(vertices, candidate_faces)
    before_metrics = before["input_metrics"]
    volume_delta = after["signed_volume_mm3"] - before_metrics["signed_volume_mm3"]
    area_delta = after["surface_area_mm2"] - before_metrics["surface_area_mm2"]
    volume_tol = max(1e-10, 1e-12 * max(0.0, before_metrics["signed_volume_mm3"]))
    area_tol = max(1e-10, 1e-12 * max(0.0, before_metrics["surface_area_mm2"]))
    removed_count = sum(row["kind"] == "removed_zero_area_face" for row in lineage)
    split_count = sum(row["kind"] == "split_long_edge_face" for row in lineage)
    unchanged_count = sum(row["kind"] == "unchanged" for row in lineage)
    gates = {
        "zero_boundary_edges": after["boundary_edges"] == 0,
        "zero_nonmanifold_edges": after["nonmanifold_edges"] == 0,
        "zero_orientation_conflicts": after["orientation_conflict_edges"] == 0,
        "zero_degenerate_faces": after["zero_area_faces_exact"] == 0,
        "positive_signed_volume": after["positive_signed_volume"],
        "signed_volume_within_tolerance": abs(volume_delta) <= volume_tol,
        "surface_area_within_tolerance": abs(area_delta) <= area_tol,
        "component_count_preserved": after["component_count_by_shared_edges"] == before_metrics["component_count_by_shared_edges"],
        "vertex_array_byte_identical": candidate_vertices.dtype == vertices.dtype
        and candidate_vertices.shape == vertices.shape
        and candidate_vertices.tobytes(order="C") == vertices.tobytes(order="C"),
        "exactly_qualified_zero_area_faces_removed": removed_count == len(before["exact_zero_area_face_ids"]) == 7,
        "exactly_qualified_long_faces_split": split_count == len(before["loops"]) == 7,
        "all_other_input_faces_unchanged": unchanged_count == len(faces) - removed_count - split_count,
        "every_local_split_preserves_positive_area_and_orientation": len(split_checks) == split_count
        and all(row["local_partition_valid"] for row in split_checks),
        "each_local_split_preserves_area_within_global_tolerance": all(
            abs(row["child_area_sum_delta_mm2"]) <= area_tol for row in split_checks),
    }
    record.update({"status": "accepted_candidate" if all(gates.values()) else "candidate_failed_acceptance",
                   "candidate_executed": True, "candidate_metrics": after,
                   "vertex_bytes_unchanged": gates["vertex_array_byte_identical"],
                   "surface_area_delta_mm2": area_delta, "surface_area_tolerance_mm2": area_tol,
                   "signed_volume_delta_mm3": volume_delta, "signed_volume_tolerance_mm3": volume_tol,
                   "component_count_preserved": gates["component_count_preserved"],
                   "acceptance_gates": gates, "local_split_checks": split_checks,
                   "face_lineage": lineage})
    return record, candidate_faces


def load_inputs() -> tuple[dict, dict[str, np.ndarray]]:
    manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    if file_sha(Path(__file__)) != manifest["source_candidate"]["sha256"]:
        raise RuntimeError("candidate source SHA256 does not match the frozen manifest")
    if file_sha(INPUT_NPZ) != manifest["frozen_archive"]["sha256"]:
        raise RuntimeError("frozen candidate NPZ SHA256 mismatch")
    with np.load(INPUT_NPZ, allow_pickle=False) as bundle:
        arrays = {name: np.ascontiguousarray(bundle[name]) for name in bundle.files}
    for name, expected in manifest["frozen_archive"]["arrays"].items():
        value = arrays[name]
        if list(value.shape) != expected["shape"] or value.dtype.str != expected["dtype"]:
            raise RuntimeError(f"frozen dtype or shape mismatch for {name}")
        if value.nbytes != expected["nbytes"] or array_sha(value) != expected["sha256_c_order_bytes"]:
            raise RuntimeError(f"frozen array content mismatch for {name}")
    return manifest, arrays


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline conforming retessellation candidate over frozen raw arrays.")
    parser.add_argument("--execute-approved", action="store_true",
                        help="run one saved-array transformation after explicit parent approval")
    args = parser.parse_args()
    if not args.execute_approved:
        print("Candidate transformation not run. Frozen arrays and source are prepared for review.")
        return 3
    if OUTPUT_NPZ.exists() or OUTPUT_JSON.exists():
        raise FileExistsError("Refusing to overwrite existing retessellation outputs")
    started = time.perf_counter()
    manifest, arrays = load_inputs()
    results = []
    candidate_arrays: dict[str, np.ndarray] = {}
    for case_id in CASE_IDS:
        vertices = arrays[f"{case_id}_raw_vertices_f64"]
        faces = arrays[f"{case_id}_raw_faces_i64"]
        result, repaired = case_result(vertices, faces, case_id)
        result["input_vertex_sha256"] = array_sha(vertices)
        result["input_face_sha256"] = array_sha(faces)
        if repaired is not None:
            candidate_arrays[f"{case_id}_candidate_vertices_f64"] = vertices.copy()
            candidate_arrays[f"{case_id}_candidate_faces_i64"] = repaired
        results.append(result)

    negative_id = manifest["negative_control"]["case_id"]
    neg_v = arrays[f"{negative_id}_hole_negative_vertices_f64"]
    neg_f = arrays[f"{negative_id}_hole_negative_faces_i64"]
    negative, negative_output_faces = case_result(neg_v, neg_f, f"{negative_id}_positive_area_hole_negative")
    negative["expected_disposition"] = "rejected_without_modification"
    negative["expected_rejection_reason"] = "unexplained three-edge boundary caused by omitted positive-area face"
    negative["negative_control_removed_face_id"] = manifest["negative_control"]["removed_positive_area_face_id"]
    negative["negative_control_removed_face_area_mm2"] = manifest["negative_control"]["removed_face_area_mm2"]
    negative["negative_control_output_modified"] = negative_output_faces is not None
    results.append(negative)

    report = {
        "schema": "a12.conforming-retessellation-candidate-result.v1",
        "argv": sys.argv, "cwd": str(Path.cwd()), "python_executable": sys.executable,
        "source_sha256": file_sha(Path(__file__)),
        "frozen_manifest_sha256": file_sha(INPUT_MANIFEST),
        "frozen_npz_sha256": file_sha(INPUT_NPZ),
        "candidate_boolean_calls": 0, "candidate_mesh_repairs_outside_local_split": 0,
        "abs_volume_used": False, "component_deletion_used": False,
        "face_lineage_scope": "parent_face_id refers only to saved raw Boolean output row IDs. Operand/mother/source-vs-candidate material ancestry is UNKNOWN and must not qualify physical R2 or pretraining use.",
        "elapsed_seconds": time.perf_counter() - started,
        "results": results,
        "interpretation_limit": "Offline saved-array topology candidate only; not production acceptance or physical wall/fracture validation.",
    }
    if candidate_arrays:
        np.savez_compressed(OUTPUT_NPZ, **candidate_arrays)
        report["candidate_npz"] = str(OUTPUT_NPZ)
        report["candidate_npz_sha256"] = file_sha(OUTPUT_NPZ)
    OUTPUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(OUTPUT_JSON), "candidate_npz": report.get("candidate_npz"),
                      "case_statuses": [r["status"] for r in results],
                      "negative_control_rejected": negative["status"] == "rejected_without_modification",
                      "candidate_boolean_calls": 0}, ensure_ascii=False))
    return 0 if all(r["status"] == "accepted_candidate" for r in results[:4]) and negative["status"] == "rejected_without_modification" else 2


if __name__ == "__main__":
    raise SystemExit(main())
