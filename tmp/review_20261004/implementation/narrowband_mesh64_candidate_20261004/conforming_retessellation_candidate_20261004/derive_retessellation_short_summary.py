from __future__ import annotations
import hashlib, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
REPORT = HERE / "retessellated_candidate_report.json"
RUN = HERE / "candidate_execution_receipt.json"
RENDER_V1 = HERE / "render_receipt.json"
RENDER_V2 = HERE / "render_v2_receipt.json"
FROZEN_MANIFEST = HERE / "frozen_retessellation_manifest.json"
FROZEN_INPUTS = HERE / "frozen_retessellation_inputs.npz"
OUTPUTS = HERE / "retessellated_candidate_outputs.npz"
SOURCE = HERE / "conforming_retessellate_candidate.py"
PREFLIGHT_MANIFEST = PARENT / "preflight_manifest.json"
PREFLIGHT_SNAPSHOT = PARENT / "postexecution_preflight_hash_snapshot.json"
PREFLIGHT_ADDENDUM = PARENT / "candidate_execution_addendum.json"
OUT = HERE / "retessellation_short_summary.json"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def case_summary(item: dict) -> dict:
    before, after = item["input_metrics"], item["candidate_metrics"]
    checks = item["local_split_checks"]
    gates = item["acceptance_gates"]
    return {
        "case_id": item["case_id"],
        "status": item["status"],
        "eligible_exact_collinear_loops": len(item["exact_zero_area_face_ids"]),
        "zero_area_raw_face_rows": item["exact_zero_area_face_ids"],
        "split_parent_raw_face_rows": [x["parent_face_id"] for x in item["face_lineage"] if x["kind"] == "split_long_edge_face"],
        "raw": {k: before[k] for k in ("vertices", "faces", "boundary_edges", "nonmanifold_edges", "orientation_conflict_edges", "zero_area_faces_exact", "surface_area_mm2", "signed_volume_mm3", "positive_signed_volume", "component_count_by_shared_edges")},
        "candidate": {k: after[k] for k in ("vertices", "faces", "boundary_edges", "nonmanifold_edges", "orientation_conflict_edges", "zero_area_faces_exact", "min_area_mm2", "surface_area_mm2", "signed_volume_mm3", "positive_signed_volume", "component_count_by_shared_edges")},
        "vertex_bytes_unchanged": item["vertex_bytes_unchanged"],
        "surface_area_delta_mm2": item["surface_area_delta_mm2"],
        "surface_area_tolerance_mm2": item["surface_area_tolerance_mm2"],
        "signed_volume_delta_mm3": item["signed_volume_delta_mm3"],
        "signed_volume_tolerance_mm3": item["signed_volume_tolerance_mm3"],
        "component_count_preserved": item["component_count_preserved"],
        "local_split_count": len(checks),
        "max_local_area_sum_delta_mm2": max(abs(x["child_area_sum_delta_mm2"]) for x in checks),
        "max_midpoint_distance_mm": max(x["middle_edge_distance_mm"] for x in checks),
        "all_acceptance_gates_true": bool(gates) and all(gates.values()),
    }

report = json.loads(REPORT.read_text(encoding="utf-8"))
run = json.loads(RUN.read_text(encoding="utf-8"))
r1 = json.loads(RENDER_V1.read_text(encoding="utf-8"))
r2 = json.loads(RENDER_V2.read_text(encoding="utf-8"))
expected = {
    "source": "6398ee6a02b010e172cd709c17403b81e868fe6784536c257976c6edb2ecaf10",
    "manifest": "3f46fb25978ba0e1210067494c8dc538448b962c483bcc56865f93fdd1fc9391",
    "inputs": "d80707312638ce2830847f2dc198632c5456963a6043715d27436b3db3ce6dc2",
    "report": "6b4078337fab9f7c0d4e4d8cdaaa2e0e4442968b4aaa5274a95a9ec1820abcba",
    "outputs": "e00404f67bf13ced471e3c7c8d0596b3b50efd4c9b17f4175142712a5e5a04a0",
    "preflight_manifest": "0d5d7d5dac802f55198324ef5c3bd8870e21705aace96b43afbba3dd72afddaa",
    "preflight_snapshot": "d89098941890098a9ac6e40b6d436850b60f5fea7f15b6fb8c15e368887288f1",
    "preflight_addendum": "7032f43f921fa5d6842a268b1f0a34cfd8737efe06d89257cbbbaa39b3383f5e",
}
actual = {
    "source": sha(SOURCE), "manifest": sha(FROZEN_MANIFEST), "inputs": sha(FROZEN_INPUTS),
    "report": sha(REPORT), "outputs": sha(OUTPUTS),
    "preflight_manifest": sha(PREFLIGHT_MANIFEST), "preflight_snapshot": sha(PREFLIGHT_SNAPSHOT),
    "preflight_addendum": sha(PREFLIGHT_ADDENDUM),
}
if actual != expected:
    raise SystemExit(f"frozen/provenance hash mismatch: {actual}")
if len(report["results"]) != 5 or not all(x["status"] == "accepted_candidate" for x in report["results"][:4]):
    raise SystemExit("candidate report case-count/status invariant failed")
negative = report["results"][4]
if negative["status"] != "rejected_without_modification" or negative["negative_control_output_modified"]:
    raise SystemExit("negative control rejection invariant failed")

summary = {
    "schema": "a12.conforming-retessellation-short-summary.v1",
    "generated_utc": "2026-10-04",
    "classification": "offline saved-array geometry candidate only; not production acceptance",
    "historical_preflight": {
        "verified_artifact_count": 22,
        "verified_at_utc": "2026-10-04T05:07:10Z",
        "manifest_sha256": actual["preflight_manifest"],
        "point_in_time_snapshot_sha256": actual["preflight_snapshot"],
        "execution_addendum_sha256": actual["preflight_addendum"],
        "note": "Historical hashes bind the already-completed Mesh32/Mesh64 source/input preflight. Later authorized source edits are outside this candidate run and do not retroactively change that record.",
    },
    "conversion": {
        "python_executable": run["python_executable"], "cwd": run["cwd"], "argv": run["argv"],
        "process_exit": run["process_exit"], "elapsed_seconds": run["elapsed_seconds"],
        "planned_cases": run["planned_conversion_cases"], "boolean_calls": run["actual_boolean_calls"],
        "retries": run["retry_count"], "conversion_invocations": 1,
        "source_sha256": actual["source"], "frozen_manifest_sha256": actual["manifest"],
        "frozen_inputs_sha256": actual["inputs"], "execution_receipt_sha256": sha(RUN),
        "raw_result_json_sha256": actual["report"], "saved_candidate_npz_sha256": actual["outputs"],
        "cases": [case_summary(x) for x in report["results"][:4]],
        "negative_control": {
            "case_id": negative["case_id"], "status": negative["status"],
            "rejection_reason": negative["rejection_reasons"],
            "removed_positive_area_face_row": negative["negative_control_removed_face_id"],
            "omitted_face_area_mm2": negative["negative_control_removed_face_area_mm2"],
            "input_boundary_edges": negative["input_metrics"]["boundary_edges"],
            "candidate_modified_input": negative["negative_control_output_modified"],
        },
    },
    "rendering": {
        "v1_png_sha256": r1["png"]["sha256"],
        "v1_disposition": "preserved; superseded because the negative-control reference panel used X-Z projection instead of X-Y",
        "v2_png_sha256": r2["png"]["sha256"],
        "v2_render_receipt_sha256": sha(RENDER_V2),
        "v2_process_exit": r2["process_exit"], "conversion_or_boolean_rerun": False,
        "projection": "four local views use X-Z at Y=9 mm; negative-control views use X-Y at Z=-1.6 mm",
    },
    "scope_and_limits": [
        "Each of the four saved raw arrays had seven exact zero-area collinear faces; the candidate split one adjacent long face at the existing strict interior midpoint and removed only its matched zero-area face.",
        "All four cases reported zero boundary/nonmanifold/orientation-conflict/zero-area faces; positive signed volume; unchanged vertex bytes and component count; surface area and signed volume deltas exactly zero within recorded tolerances; every reported acceptance gate was true.",
        "The negative control omitted positive-area raw face row 4688 (0.6328125 mm^2), producing three boundary edges. It was rejected without modification; it was not capped or filled.",
        "Lineage identifies only parent rows in the saved raw Boolean output. Boolean face provenance/source-versus-candidate material ancestry is UNKNOWN; do not use this candidate for physical R2 qualification or pretraining.",
        "The observed topological and metric gates do not establish physical wall thickness, crack geometry, fracture truth, or production readiness. No production code, tests, Boolean, or solver were run in this conversion task.",
    ],
    "artifact_paths": {
        "raw_report": str(REPORT), "raw_and_negative_inputs": str(FROZEN_INPUTS),
        "candidate_output_arrays": str(OUTPUTS), "conversion_receipt": str(RUN),
        "final_png_v2": str(HERE / "retessellation_before_after_local_topology_v2.png"),
        "final_png_v2_receipt": str(RENDER_V2),
    },
}
OUT.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"summary": str(OUT), "bytes": OUT.stat().st_size, "sha256": sha(OUT),
                  "case_count": len(summary["conversion"]["cases"]), "all_four_gates_true": all(x["all_acceptance_gates_true"] for x in summary["conversion"]["cases"]),
                  "negative_rejected_unchanged": negative["status"] == "rejected_without_modification" and not negative["negative_control_output_modified"]}, indent=2))
