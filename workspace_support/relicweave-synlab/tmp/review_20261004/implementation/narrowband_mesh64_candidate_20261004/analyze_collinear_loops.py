from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import trimesh

OUT = Path(__file__).resolve().parent
CASES = [(axis, mode) for axis in ("P02", "P03") for mode in ("mesh32", "mesh64")]


def edge_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def array_sha(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes(order="C")).hexdigest()


def main() -> None:
    report = {
        "schema": "a12.narrowband-collinear-loop-tjunction-preflight.v1",
        "source_kind": "read-only saved native output and clean output NPZ arrays; no operator, Boolean, repair, or retessellation executed",
        "degenerate_height_threshold_mm": 1e-12,
        "cases": [],
    }
    for axis, mode in CASES:
        result_path = OUT / f"result_{axis}_{mode}.json"
        result = json.loads(result_path.read_text(encoding="utf-8-sig"))
        npz_path = OUT / f"output_{axis}_{mode}.npz"
        with np.load(npz_path, allow_pickle=False) as arrays:
            raw_v = np.ascontiguousarray(arrays["raw_vertices"], dtype=np.float64)
            raw_f = np.ascontiguousarray(arrays["raw_faces"], dtype=np.int64)
            clean_v = np.ascontiguousarray(arrays["clean_vertices"], dtype=np.float64)
            clean_f = np.ascontiguousarray(arrays["clean_faces"], dtype=np.int64)

        raw_mesh = trimesh.Trimesh(vertices=raw_v, faces=raw_f, process=False)
        keep = np.asarray(raw_mesh.nondegenerate_faces(height=1e-12), dtype=bool)
        deg_ids = np.flatnonzero(~keep)
        edge_faces: dict[tuple[int, int], list[int]] = defaultdict(list)
        for face_id, face in enumerate(raw_f):
            a, b, c = map(int, face)
            for u, v in ((a, b), (b, c), (c, a)):
                edge_faces[edge_key(u, v)].append(int(face_id))

        clean_face_keys = {tuple(sorted(map(int, f))) for f in clean_f}
        removed_face_ids = [i for i, face in enumerate(raw_f)
                            if tuple(sorted(map(int, face))) not in clean_face_keys]
        removed_face_edge_set = set()
        loop_rows = []
        for face_id in deg_ids:
            face = tuple(map(int, raw_f[face_id]))
            xyz = raw_v[np.asarray(face)]
            pairs = [(0, 1), (1, 2), (2, 0)]
            lengths = [float(np.linalg.norm(xyz[i] - xyz[j])) for i, j in pairs]
            i0, i1 = pairs[int(np.argmax(lengths))]
            imid = next(i for i in range(3) if i not in (i0, i1))
            a_idx, b_idx, m_idx = face[i0], face[i1], face[imid]
            a, b, m = xyz[i0], xyz[i1], xyz[imid]
            ab = b - a
            ab2 = float(np.dot(ab, ab))
            t = float(np.dot(m - a, ab) / ab2) if ab2 else None
            projection = a + t * ab if t is not None else a
            line_distance = float(np.linalg.norm(m - projection))
            area = float(raw_mesh.area_faces[face_id])
            loop_edges = [edge_key(a_idx, b_idx), edge_key(a_idx, m_idx), edge_key(m_idx, b_idx)]
            adjacent = {}
            for label, key in zip(("long", "short_a_mid", "short_mid_b"), loop_edges):
                other = [n for n in edge_faces[key] if n != face_id]
                adjacent[label] = {
                    "edge_vertex_ids": list(key),
                    "raw_incidence_count": len(edge_faces[key]),
                    "neighbor_face_ids": other,
                    "neighbor_faces": [
                        {"output_face_id": int(n),
                         "degenerate_height_1e-12": bool(not keep[n]),
                         "area_mm2": float(raw_mesh.area_faces[n])}
                        for n in other
                    ],
                }
                removed_face_edge_set.add(key)
            all_three_positive = all(
                len(adjacent[key]["neighbor_faces"]) == 1
                and not adjacent[key]["neighbor_faces"][0]["degenerate_height_1e-12"]
                and adjacent[key]["neighbor_faces"][0]["area_mm2"] > 0
                for key in ("long", "short_a_mid", "short_mid_b"))
            loop_rows.append({
                "raw_output_face_id": int(face_id),
                "vertex_ids_in_face_order": list(face),
                "vertex_coordinates_mm": xyz.tolist(),
                "face_area_mm2": area,
                "long_edge_endpoint_vertex_ids": [a_idx, b_idx],
                "middle_vertex_id": m_idx,
                "long_edge_length_mm": float(np.sqrt(ab2)),
                "middle_projection_parameter_t": t,
                "middle_projection_is_strictly_interior": bool(t is not None and 0.0 < t < 1.0),
                "middle_to_long_edge_distance_mm": line_distance,
                "adjacency": adjacent,
                "positive_adjacent_faces_on_all_three_collinear_spans": all_three_positive,
                "conforming_split_candidate_if_exactly_collinear": bool(all_three_positive and t is not None and 0.0 < t < 1.0),
            })

        raw_edge_set = set(edge_faces)
        clean_edge_faces: dict[tuple[int, int], int] = defaultdict(int)
        for face in clean_f:
            a, b, c = map(int, face)
            for u, v in ((a, b), (b, c), (c, a)):
                clean_edge_faces[edge_key(u, v)] += 1
        clean_boundary = {edge for edge, count in clean_edge_faces.items() if count == 1}
        loop_edge_union = set()
        for face_id in deg_ids:
            face = list(map(int, raw_f[face_id]))
            loop_edge_union.update(edge_key(face[i], face[j]) for i, j in ((0, 1), (1, 2), (2, 0)))
        clean_matches_only_removed_degenerate_loop_edges = clean_boundary == loop_edge_union
        case_record = {
            "axis_id": axis,
            "path": mode,
            "result_json_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "output_npz_sha256": hashlib.sha256(npz_path.read_bytes()).hexdigest(),
            "raw_vertex_array_sha256": array_sha(raw_v),
            "raw_face_array_sha256": array_sha(raw_f),
            "clean_vertex_array_sha256": array_sha(clean_v),
            "clean_face_array_sha256": array_sha(clean_f),
            "raw_metrics": next(s for s in result["stages"] if s["stage"].endswith(".native_boolean_output")),
            "clean_metrics": next(s for s in result["stages"] if s["stage"] == "clean_mesh.actual_function_output"),
            "degenerate_raw_output_face_ids": deg_ids.astype(int).tolist(),
            "faces_missing_from_clean_output_by_same_vertex_ids": removed_face_ids,
            "clean_boundary_edge_count": len(clean_boundary),
            "boundary_edges_equal_union_of_removed_degenerate_face_edges": clean_matches_only_removed_degenerate_loop_edges,
            "all_degenerate_loop_edges_have_raw_incidence_two": all(len(edge_faces[e]) == 2 for e in loop_edge_union),
            "loops": loop_rows,
            "operand_face_provenance_available": False,
            "face_provenance_limit": "Saved native output arrays preserve output face row IDs only. Manifold input face IDs/merge relation or source-vs-candidate ownership were not exported, so neighboring raw output face IDs cannot be mapped back to input faces/materials.",
        }
        report["cases"].append(case_record)

    report["cross_case_summary"] = {
        "all_cases_have_seven_raw_degenerate_faces": all(len(c["degenerate_raw_output_face_ids"]) == 7 for c in report["cases"]),
        "all_cases_have_21_clean_boundary_edges": all(c["clean_metrics"]["boundary_edges"] == 21 for c in report["cases"]),
        "all_cases_clean_boundary_edges_are_exactly_removed_face_edges": all(c["boundary_edges_equal_union_of_removed_degenerate_face_edges"] for c in report["cases"]),
        "all_cases_show_collinear_interior_middle_vertices": all(
            all(loop["middle_projection_is_strictly_interior"] and loop["middle_to_long_edge_distance_mm"] <= 1e-12 for loop in c["loops"])
            for c in report["cases"]),
        "all_cases_have_positive_area_neighbor_on_long_and_both_short_spans": all(
            all(loop["positive_adjacent_faces_on_all_three_collinear_spans"] for loop in c["loops"])
            for c in report["cases"]),
        "interpretation": "If these predicates hold, the saved topology supports a local conforming edge-split hypothesis: split the positive-area long-edge neighbor at the already-existing collinear middle vertex, then remove the zero-area face. This is only a preflight hypothesis, not an executed repair or proof of globally valid geometry.",
    }
    path = OUT / "collinear_loop_tjunction_preflight.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(path), "bytes": path.stat().st_size,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "cross_case_summary": report["cross_case_summary"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
