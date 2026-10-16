from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[6]
REPORT = ROOT / "brep_candidate_report.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    report: dict[str, Any] = json.loads(REPORT.read_text(encoding="utf-8"))
    coarse_mesh = report["mesh"]["initial_0_05mm_mesh"]
    coarse_metric = coarse_mesh["mesh_to_native_BREP"]
    coarse_metric["canonical_reference_kind"] = "initial tessellation compared with the same native BREP reimport; no STEP used"
    coarse_metric["face_match_method"] = "identity triangle lineage on the native BREP solid"
    coarse_metric["sampling_method"] = "deterministic edge-midpoint and triangle-centroid samples linked to native BREP trimmed faces; not a full Hausdorff proof"
    coarse_mesh["coarse_mesh_artifact_retained"] = False
    coarse_mesh["artifacts"] = {"body_mesh": None, "body_mesh_lineage": None}

    body_metric = report["mesh"]["mesh_to_native_BREP"]
    body_metric["canonical_reference_kind"] = "same native BREP reimport; no STEP used"
    body_metric["face_match_method"] = "identity triangle lineage on the same reimported native BREP solid"
    body_metric["sampling_method"] = "deterministic edge-midpoint and triangle-centroid samples linked by native BREP face identity; not a full Hausdorff proof"

    source_paths = {
        "rejected_interpolated_candidate_report": REPO_ROOT / "relicweave-synlab/tmp/review_20261003/implementation/vf/smooth_cad/candidate_default_wall4/smooth_cad_spike_report.json",
        "accepted_exact_profile_script": REPO_ROOT / "relicweave-synlab/tmp/review_20261003/implementation/vf/smooth_cad/candidate2_native_2d_offset_wall4/candidate2_physical_profile.py",
        "accepted_exact_profile_report": REPO_ROOT / "relicweave-synlab/tmp/review_20261003/implementation/vf/smooth_cad/candidate2_native_2d_offset_wall4/candidate2_physical_profile_report.json",
        "previous_planar_offset_script": REPO_ROOT / "relicweave-synlab/tmp/review_20261003/implementation/vf/smooth_cad/candidate2_native_2d_offset_wall4/candidate2_planar_offset.py",
        "previous_planar_offset_report": REPO_ROOT / "relicweave-synlab/tmp/review_20261003/implementation/vf/smooth_cad/candidate2_native_2d_offset_wall4/candidate2_planar_offset_report.json",
        "failed_step_diagnostic_script": REPO_ROOT / "relicweave-synlab/tmp/review_20261003/implementation/vf/smooth_cad/candidate2_native_2d_offset_wall4/candidate2_step_roundtrip_diagnostics.py",
        "failed_step_diagnostic_report": REPO_ROOT / "relicweave-synlab/tmp/review_20261003/implementation/vf/smooth_cad/candidate2_native_2d_offset_wall4/candidate2_step_roundtrip_diagnostics.json",
        "failed_step_diagnostic_log": REPO_ROOT / "relicweave-synlab/tmp/review_20261003/implementation/vf/smooth_cad/candidate2_native_2d_offset_wall4/candidate2_step_roundtrip_diagnostics.log",
        "smooth_cad_experiment_helper": REPO_ROOT / "vesselforge/experiments/smooth_cad_spike.py",
        "brep_persistence_helper": REPO_ROOT / "vesselforge/experiments/brep_persistence_helper.py",
        "vesselforge_geometry_module": REPO_ROOT / "vesselforge/src/vesselforge/geometry.py",
        "candidate_builder": ROOT / "build_brep_candidate.py",
        "initial_mesh_diagnostic_script": ROOT / "diagnose_initial_mesh.py",
        "mesh_refinement_script": ROOT / "refine_native_brep_mesh.py",
        "report_finalizer": ROOT / "finalize_report.py",
        "python_runtime": REPO_ROOT / "third_party/vesselforge-runtime/venv/Scripts/python.exe",
    }
    report["source_sha256"] = {
        str(path.relative_to(REPO_ROOT)).replace("\\", "/"): sha256(path)
        for path in source_paths.values()
        if path.is_file()
    }
    refine_pyc = ROOT / "__pycache__" / "refine_native_brep_mesh.cpython-312.pyc"
    if refine_pyc.is_file():
        pyc_data = refine_pyc.read_bytes()
        _, compiled_source_size = struct.unpack("II", pyc_data[8:16])
        report["mesh_refinement"]["execution_code_cache"] = {
            "path": str(refine_pyc.relative_to(REPO_ROOT)).replace("\\", "/"),
            "sha256": sha256(refine_pyc),
            "compiled_source_size_bytes": compiled_source_size,
            "note": "Python bytecode cache compiled before the post-run report-label correction; remesh parameters and geometry code were unchanged by that correction",
        }
    report["sha256_manifest"] = "source_and_artifact_sha256.json"
    report["candidate_state"] = "BREP_CANDIDATE"
    report["status"] = "BREP_CANDIDATE"
    report["candidate_decision"] = "NOT_PROMOTED; native BREP candidate only; parent review required; forge.asset.v1 remains canonical STEP"
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "source_count": len(report["source_sha256"]), "report": str(REPORT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
