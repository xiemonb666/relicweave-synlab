from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "brep_candidate_report.json"


def main() -> int:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    coarse_mesh = report["mesh"]["initial_0_05mm_mesh"]
    detailed = report["mesh_refinement"]["initial_0_05mm_mesh_detail"]
    crosscheck = coarse_mesh["mesh_to_native_BREP"]
    result = {
        "body_brep_sha256": report["artifacts"]["body_brep_sha256"],
        "native_tessellation_parameters": {
            "absolute_linear_deflection_mm": coarse_mesh["absolute_chord_target_mm"],
            "angular_deflection_rad": coarse_mesh["angular_tolerance_rad"],
        },
        "mesh_nodes": int(coarse_mesh["topology"]["vertices"]),
        "mesh_faces": int(coarse_mesh["topology"]["triangles"]),
        "coarse_mesh_artifact_retained": False,
        "coarse_mesh_disposition": "only its metrics are retained; product surface.npz contains the accepted 0.02 mm mesh",
        "deterministic_trimmed_face_deviation": detailed,
        "existing_sampled_mesh_function_crosscheck": {
            "method": "vesselforge.geometry.sampled_mesh_to_cad_metrics on the same reimported native BREP and triangle lineage",
            "max_sampled_deviation_mm": crosscheck["max_sampled_deviation_mm"],
            "valid_sample_count": crosscheck["valid_sample_count"],
            "sample_count": crosscheck["sample_count"],
            "unknown_sample_count": crosscheck["unknown_sample_count"],
            "maximum_matches_detailed_result": bool(
                crosscheck["max_sampled_deviation_mm"] is not None
                and abs(crosscheck["max_sampled_deviation_mm"] - detailed["max_sampled_deviation_mm"]) <= 1e-10
            ),
            "method_note": "legacy helper field names are stored with native BREP labels in the report; face lineage is identity from the native BREP mesh",
        },
    }
    target = ROOT / "initial_mesh_error_detail.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
