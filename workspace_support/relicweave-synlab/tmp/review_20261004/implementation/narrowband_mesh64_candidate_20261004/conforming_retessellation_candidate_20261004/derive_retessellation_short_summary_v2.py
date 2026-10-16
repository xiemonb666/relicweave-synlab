from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
FILES = {
    "source": HERE / "conforming_retessellate_candidate.py",
    "manifest": HERE / "frozen_retessellation_manifest.json",
    "inputs": HERE / "frozen_retessellation_inputs.npz",
    "report": HERE / "retessellated_candidate_report.json",
    "arrays": HERE / "retessellated_candidate_outputs.npz",
    "conversion_receipt": HERE / "candidate_execution_receipt.json",
    "render_v1_receipt": HERE / "render_receipt.json",
    "render_v2_source": HERE / "render_retessellation_before_after_v2.py",
    "render_v2_receipt": HERE / "render_v2_receipt.json",
    "render_v2_png": HERE / "retessellation_before_after_local_topology_v2.png",
    "preflight_manifest": PARENT / "preflight_manifest.json",
    "preflight_snapshot": PARENT / "postexecution_preflight_hash_snapshot.json",
    "preflight_addendum": PARENT / "candidate_execution_addendum.json",
}
EXPECTED = {
    "source": "6398ee6a02b010e172cd709c17403b81e868fe6784536c257976c6edb2ecaf10",
    "manifest": "3f46fb25978ba0e1210067494c8dc538448b962c483bcc56865f93fdd1fc9391",
    "inputs": "d80707312638ce2830847f2dc198632c5456963a6043715d27436b3db3ce6dc2",
    "report": "6b4078337fab9f7c0d4e4d8cdaaa2e0e4442968b4aaa5274a95a9ec1820abcba",
    "arrays": "e00404f67bf13ced471e3c7c8d0596b3b50efd4c9b17f4175142712a5e5a04a0",
    "preflight_manifest": "0d5d7d5dac802f55198324ef5c3bd8870e21705aace96b43afbba3dd72afddaa",
    "preflight_snapshot": "d89098941890098a9ac6e40b6d436850b60f5fea7f15b6fb8c15e368887288f1",
    "preflight_addendum": "7032f43f921fa5d6842a268b1f0a34cfd8737efe06d89257cbbbaa39b3383f5e",
}
def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()
actual = {k: sha(v) for k, v in FILES.items()}
for k, v in EXPECTED.items():
    if actual[k] != v:
        raise SystemExit(f"frozen hash mismatch: {k}")
report = json.loads(FILES["report"].read_text(encoding="utf-8"))
run = json.loads(FILES["conversion_receipt"].read_text(encoding="utf-8"))
r1 = json.loads(FILES["render_v1_receipt"].read_text(encoding="utf-8"))
r2 = json.loads(FILES["render_v2_receipt"].read_text(encoding="utf-8"))
if len(report["results"]) != 5 or not all(x["status"] == "accepted_candidate" for x in report["results"][:4]):
    raise SystemExit("four saved case status invariant failed")
negative = report["results"][4]
if negative["status"] != "rejected_without_modification" or negative["negative_control_output_modified"]:
    raise SystemExit("negative control invariant failed")
# Compact metric tuple order is declared below; complete named metrics and face lineage remain in report.
metric_order = ["vertices", "faces", "boundary_edges", "nonmanifold_edges", "orientation_conflict_edges", "zero_area_faces_exact", "surface_area_mm2", "signed_volume_mm3", "positive_signed_volume", "component_count_by_shared_edges"]
cases = []
for item in report["results"][:4]:
    b, a = item["input_metrics"], item["candidate_metrics"]
    cases.append({
        "id": item["case_id"], "status": item["status"],
        "raw_metrics_tuple": [b[k] for k in metric_order],
        "candidate_metrics_tuple": [a[k] for k in metric_order] + [a["min_area_mm2"]],
        "checks": {
            "acceptance_gates_true_count": sum(bool(x) for x in item["acceptance_gates"].values()),
            "acceptance_gates_total": len(item["acceptance_gates"]),
            "all_acceptance_gates_true": all(item["acceptance_gates"].values()),
            "vertex_bytes_unchanged": item["vertex_bytes_unchanged"],
            "component_count_preserved": item["component_count_preserved"],
            "area_delta_mm2": item["surface_area_delta_mm2"],
            "area_tolerance_mm2": item["surface_area_tolerance_mm2"],
            "signed_volume_delta_mm3": item["signed_volume_delta_mm3"],
            "signed_volume_tolerance_mm3": item["signed_volume_tolerance_mm3"],
            "local_splits": len(item["local_split_checks"]),
            "max_local_area_sum_delta_mm2": max(abs(x["child_area_sum_delta_mm2"]) for x in item["local_split_checks"]),
            "max_middle_to_long_edge_distance_mm": max(x["middle_edge_distance_mm"] for x in item["local_split_checks"]),
        },
    })
summary = {
    "schema": "a12.conforming-retessellation-short-summary.v2",
    "generated_utc": datetime.now(timezone.utc).isoformat(),
    "classification": "offline saved-array geometry candidate only; not production acceptance",
    "preflight_22_item_record": {
        "verified_at_utc": "2026-10-04T05:07:10Z",
        "manifest_sha256": actual["preflight_manifest"],
        "point_in_time_snapshot_sha256": actual["preflight_snapshot"],
        "execution_addendum_sha256": actual["preflight_addendum"],
        "verified_artifact_count": 22,
    },
    "metric_tuple_orders": {
        "raw": metric_order,
        "candidate": metric_order + ["min_area_mm2"],
    },
    "conversion": {
        "argv": run["argv"], "cwd": run["cwd"], "python": run["python_executable"],
        "exit": run["process_exit"], "elapsed_s": run["elapsed_seconds"],
        "invocations": 1, "cases": 5, "boolean_calls": 0, "retries": 0,
        "cases_accepted": cases,
        "negative": {
            "case": negative["case_id"], "status": negative["status"],
            "reason": negative["rejection_reasons"], "boundary_edges": negative["input_metrics"]["boundary_edges"],
            "omitted_raw_face_row": negative["negative_control_removed_face_id"],
            "omitted_face_area_mm2": negative["negative_control_removed_face_area_mm2"],
            "modified": negative["negative_control_output_modified"],
        },
    },
    "render": {
        "v1_sha256": r1["png"]["sha256"],
        "v1_note": "preserved; negative-control reference panel had wrong projection",
        "v2_sha256": r2["png"]["sha256"], "v2_receipt_sha256": actual["render_v2_receipt"],
        "v2_process_exit": r2["process_exit"], "projection": "four X-Z panels at Y=9 mm; negative-control X-Y panels at Z=-1.6 mm",
        "conversion_rerun": False,
    },
    "artifact_dir": str(HERE),
    "artifact_hashes": {k: actual[k] for k in ("source", "manifest", "inputs", "report", "arrays", "conversion_receipt", "render_v2_source", "render_v2_receipt", "render_v2_png")},
    "limits": [
        "Seven exact zero-area collinear faces per saved case; split the unique neighboring long face at an existing interior midpoint and removed only its matched zero-area face.",
        "All four cases: zero boundary/nonmanifold/orientation-conflict/zero-area faces after candidate; positive signed volume; area and volume unchanged within saved tolerances; vertex bytes and components unchanged; all candidate gates true.",
        "Negative removed positive-area row 4688 (0.6328125 mm^2), causing a three-edge opening; candidate rejected it unchanged, with no capping or filling.",
        "Lineage covers only raw Boolean output face rows; material/source-vs-candidate provenance is UNKNOWN. No physical R2 or pretraining eligibility.",
        "Topology and numeric gates do not establish physical wall thickness, crack geometry, fracture truth, or production readiness; no production code/tests/Boolean/solver ran here.",
    ],
}
out = HERE / "retessellation_short_summary_v2.json"
blob = json.dumps(summary, separators=(",", ":"), ensure_ascii=False) + "\n"
if len(blob.encode("utf-8")) > 8192:
    raise SystemExit(f"summary exceeds 8 KiB: {len(blob.encode('utf-8'))}")
out.write_text(blob, encoding="utf-8")
print(json.dumps({"summary": str(out), "bytes": out.stat().st_size, "sha256": sha(out),
                  "four_case_gates_true": all(c["checks"]["all_acceptance_gates_true"] for c in cases),
                  "negative_rejected_unchanged": negative["status"] == "rejected_without_modification" and not negative["negative_control_output_modified"]}, indent=2))
