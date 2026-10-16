from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(REPO_ROOT / "vesselforge" / "src"))
sys.path.insert(0, str(REPO_ROOT / "vesselforge"))

import cadquery as cq
import numpy as np

from experiments.brep_persistence_helper import (
    save_actual_brep_preview,
    sampled_mesh_to_native_brep_detail,
)
from vesselforge.geometry import (
    VesselSpec,
    mesh_shape,
    mesh_topology_metrics,
    sampled_mesh_to_cad_metrics,
)

REPORT_PATH = ROOT / "brep_candidate_report.json"
BODY_BREP = ROOT / "geometry" / "smooth_body.brep"
GEOMETRY = ROOT / "geometry"
PREVIEW = ROOT / "renders" / "native_brep_and_half_section.png"
LINEAR_DEFLECTION_MM = 0.02
ANGULAR_DEFLECTION_RAD = 0.08
MAX_FACES_BUDGET = 200000
MAX_SECONDS_BUDGET = 120.0
WALL_MM = 4.0
SPEC = VesselSpec(
    body_width_mm=41.0,
    body_height_mm=56.0,
    wall_mm=WALL_MM,
    tessellation_linear_mm=LINEAR_DEFLECTION_MM,
    tessellation_angular_rad=ANGULAR_DEFLECTION_RAD,
)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_label(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            native_key = (
                key.replace("canonical_step", "canonical_native_brep")
                .replace("matched_step", "matched_native_brep")
                .replace("step_face", "native_brep_face")
                .replace("step_trimmed", "native_brep_trimmed")
                .replace("step_point_to_trimmed_face", "native_brep_point_to_trimmed_face")
                .replace("source_step", "source_native_brep")
            )
            result[native_key] = native_label(item)
        return result
    if isinstance(value, list):
        return [native_label(item) for item in value]
    if isinstance(value, str):
        return value.replace("canonical STEP", "canonical native BREP").replace("canonical STEP-imported", "canonical native BREP reimported").replace("STEP-imported", "native-BREP-imported").replace("STEP B-rep", "native BREP").replace("STEP face", "native BREP face").replace("STEP trimmed", "native BREP trimmed").replace("CANONICAL_STEP", "CANONICAL_NATIVE_BREP").replace("STEP", "BREP").replace("no BREP used", "no STEP used")
    return value


def write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def finish(report: dict[str, Any], status: str, reason: str, start: float) -> int:
    report["status"] = status
    report["candidate_state"] = status
    report["candidate_decision"] = "NOT_PROMOTED; native BREP candidate only; parent review required; forge.asset.v1 remains canonical STEP"
    report.setdefault("mesh_refinement", {})["failure_reason"] = reason
    report["mesh_refinement"]["status"] = "FAIL"
    report["mesh_refinement"]["elapsed_seconds"] = time.monotonic() - start
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    write_report(report)
    print(json.dumps({"status": status, "reason": reason, "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 2


def main() -> int:
    start = time.monotonic()
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    if not (report.get("native_BREP_roundtrip", {}).get("one_valid_solid_shell_preserved") and BODY_BREP.is_file()):
        return finish(report, "FAIL_REFINEMENT_PRECONDITION", "native BREP roundtrip evidence is missing or failed", start)
    if report.get("serialization_policy", {}).get("body_write_attempt_count") != 1:
        return finish(report, "FAIL_REFINEMENT_PRECONDITION", "the single native body write was not recorded", start)
    body_hash_before = file_sha256(BODY_BREP)
    if body_hash_before != report["artifacts"]["body_brep_sha256"]:
        return finish(report, "FAIL_REFINEMENT_PRECONDITION", "native BREP hash differs from the recorded candidate", start)

    coarse_detail_path = ROOT / "initial_mesh_error_detail.json"
    coarse_detail = json.loads(coarse_detail_path.read_text(encoding="utf-8")) if coarse_detail_path.is_file() else None
    initial_mesh_report = native_label(report.get("mesh"))
    report["mesh_refinement"] = {
        "attempt_count": 1,
        "geometry_changed": False,
        "native_brep_rewritten": False,
        "native_brep_write_attempt_count_stays": 1,
        "native_brep_sha256_before": body_hash_before,
        "native_brep_sha256_after": None,
        "native_brep_reimport_for_tessellation_only": True,
        "selection_reason": "initial 0.05 mm mesh had a single sampled edge-midpoint deviation of 0.115315794 mm on the upper spline face; refine absolute chord deflection to 0.02 mm while holding angular deflection at 0.08 rad",
        "parameters": {
            "linear_absolute_deflection_mm": LINEAR_DEFLECTION_MM,
            "angular_deflection_rad": ANGULAR_DEFLECTION_RAD,
            "max_total_faces": MAX_FACES_BUDGET,
            "max_wall_seconds": MAX_SECONDS_BUDGET,
        },
        "initial_0_05mm_mesh_detail": coarse_detail.get("detailed_trimmed_face_deviation") if coarse_detail else None,
        "status": "RUNNING",
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_report(report)

    restored = cq.Shape.importBrep(str(BODY_BREP))
    if (
        not restored.isValid()
        or len(restored.Solids()) != 1
        or len(restored.Shells()) != 1
        or abs(restored.Volume() - report["native_BREP_roundtrip"]["source_volume_mm3"]) > 0.01
    ):
        return finish(report, "FAIL_REFINEMENT_BREP_READ", "the same recorded BREP did not reimport with its accepted solid/shell/volume", start)

    body_vertices, body_faces, body_lineage = mesh_shape(restored, SPEC)
    body_face_count = int(len(body_faces))
    body_node_count = int(len(body_vertices))
    if body_face_count > MAX_FACES_BUDGET or time.monotonic() - start > MAX_SECONDS_BUDGET:
        report["mesh_refinement"]["body_nodes"] = body_node_count
        report["mesh_refinement"]["body_faces"] = body_face_count
        report["mesh_refinement"]["face_budget_exceeded"] = body_face_count > MAX_FACES_BUDGET
        return finish(report, "FAIL_REFINEMENT_BUDGET", "body tessellation exceeded the predeclared face or time budget", start)

    body_topology = mesh_topology_metrics(body_vertices, body_faces)
    body_raw_metric = sampled_mesh_to_cad_metrics(restored, body_vertices, body_faces, body_lineage)
    body_metric_detail = sampled_mesh_to_native_brep_detail(restored, body_vertices, body_faces, body_lineage)
    metrics_consistent = bool(
        body_raw_metric["unknown_sample_count"] == body_metric_detail["unknown_sample_count"]
        and body_raw_metric["sample_count"] == body_metric_detail["sample_count"]
        and body_raw_metric["max_sampled_deviation_mm"] is not None
        and body_metric_detail["max_sampled_deviation_mm"] is not None
        and abs(body_raw_metric["max_sampled_deviation_mm"] - body_metric_detail["max_sampled_deviation_mm"]) <= 1e-10
    )

    body_mesh_path = GEOMETRY / "surface.npz"
    body_lineage_path = GEOMETRY / "mesh_lineage.npz"
    np.savez_compressed(body_mesh_path, vertices_mm=body_vertices.astype(np.float64), faces=body_faces.astype(np.int32))
    np.savez_compressed(body_lineage_path, face_source_brep_index=body_lineage.astype(np.int32))

    halfspace = cq.Solid.makeBox(120.0, 70.0, 100.0, cq.Vector(-40.0, 0.0, -20.0))
    section = restored.intersect(halfspace)
    section_volume_fraction = float(section.Volume() / max(float(restored.Volume()), 1e-12))
    if (
        section.isNull()
        or not section.isValid()
        or len(section.Solids()) != 1
        or abs(section_volume_fraction - 0.5) > 0.01
    ):
        return finish(report, "FAIL_REFINEMENT_SECTION", "actual half-space cut failed during the predeclared remesh preview", start)
    section_vertices, section_faces, section_lineage = mesh_shape(section, SPEC)
    section_face_count = int(len(section_faces))
    section_node_count = int(len(section_vertices))
    total_face_count = body_face_count + section_face_count
    if total_face_count > MAX_FACES_BUDGET or time.monotonic() - start > MAX_SECONDS_BUDGET:
        report["mesh_refinement"]["body_nodes"] = body_node_count
        report["mesh_refinement"]["body_faces"] = body_face_count
        report["mesh_refinement"]["section_nodes"] = section_node_count
        report["mesh_refinement"]["section_faces"] = section_face_count
        report["mesh_refinement"]["total_faces"] = total_face_count
        report["mesh_refinement"]["face_budget_exceeded"] = total_face_count > MAX_FACES_BUDGET
        return finish(report, "FAIL_REFINEMENT_BUDGET", "body plus section tessellation exceeded the predeclared face or time budget", start)

    section_topology = mesh_topology_metrics(section_vertices, section_faces)
    body_spec_metric = {
        "absolute_chord_target_mm": SPEC.tessellation_linear_mm,
        "angular_tolerance_rad": SPEC.tessellation_angular_rad,
        "face_count": body_face_count,
        "node_count": body_node_count,
        "topology": body_topology,
        "mesh_to_native_BREP": {
            **native_label(body_raw_metric),
            "canonical_reference_kind": "same reimported native BREP; no STEP used",
            "statistics": body_metric_detail,
            "sample_acceptance_max_mm": 0.10,
            "sample_statistics_consistent": metrics_consistent,
        },
    }
    section_spec_metric = {
        "absolute_chord_target_mm": SPEC.tessellation_linear_mm,
        "angular_tolerance_rad": SPEC.tessellation_angular_rad,
        "face_count": section_face_count,
        "node_count": section_node_count,
        "topology": section_topology,
        "actual_halfspace_volume_fraction": section_volume_fraction,
        "source": "same reimported BREP intersected with y>=0 half-space; no STEP, no BREP section serialization",
    }

    section_mesh_path = GEOMETRY / "axial_section.npz"
    section_lineage_path = GEOMETRY / "axial_section_lineage.npz"
    np.savez_compressed(section_mesh_path, vertices_mm=section_vertices.astype(np.float64), faces=section_faces.astype(np.int32))
    np.savez_compressed(section_lineage_path, face_source_brep_index=section_lineage.astype(np.int32))
    preview_summary = save_actual_brep_preview(
        PREVIEW,
        body_vertices,
        body_faces,
        section_vertices,
        section_faces,
    )

    report["mesh"] = {
        **body_spec_metric,
        "initial_0_05mm_mesh": initial_mesh_report,
        "refinement_parameters_and_budget": report["mesh_refinement"]["parameters"],
        "section_mesh": section_spec_metric,
        "artifacts": {
            "body_mesh": body_mesh_path.relative_to(ROOT).as_posix(),
            "body_mesh_lineage": body_lineage_path.relative_to(ROOT).as_posix(),
            "half_section_mesh": section_mesh_path.relative_to(ROOT).as_posix(),
            "half_section_mesh_lineage": section_lineage_path.relative_to(ROOT).as_posix(),
        },
    }
    report["actual_png"] = preview_summary
    report["mesh_refinement"]["body_nodes"] = body_node_count
    report["mesh_refinement"]["body_faces"] = body_face_count
    report["mesh_refinement"]["section_nodes"] = section_node_count
    report["mesh_refinement"]["section_faces"] = section_face_count
    report["mesh_refinement"]["total_faces"] = total_face_count
    report["mesh_refinement"]["face_budget_exceeded"] = False
    report["mesh_refinement"]["elapsed_seconds"] = time.monotonic() - start
    report["mesh_refinement"]["native_brep_sha256_after"] = file_sha256(BODY_BREP)
    report["mesh_refinement"]["native_brep_hash_unchanged"] = body_hash_before == file_sha256(BODY_BREP)
    report["mesh_refinement"]["status"] = "PASS" if body_metric_detail["max_sampled_deviation_mm"] is not None and body_metric_detail["max_sampled_deviation_mm"] <= 0.10 and body_metric_detail["unknown_sample_count"] == 0 and metrics_consistent else "FAIL"

    checks = report.get("checks", {})
    checks["body_mesh_to_cad_under_0_10mm"] = bool(
        report["mesh_refinement"]["status"] == "PASS"
    )
    checks["body_mesh_topology_watertight_positive"] = bool(body_topology["watertight"] and body_topology["signed_volume_mm3"] > 0)
    checks["mesh_refinement_same_brep_within_budget"] = bool(
        report["mesh_refinement"]["native_brep_hash_unchanged"]
        and not report["mesh_refinement"]["face_budget_exceeded"]
        and report["mesh_refinement"]["elapsed_seconds"] <= MAX_SECONDS_BUDGET
    )
    report["checks"] = checks
    report["artifacts"]["body_mesh_sha256"] = file_sha256(body_mesh_path)
    report["artifacts"]["body_mesh_lineage_sha256"] = file_sha256(body_lineage_path)
    report["artifacts"]["half_section_mesh"] = section_mesh_path.relative_to(ROOT).as_posix()
    report["artifacts"]["half_section_mesh_sha256"] = file_sha256(section_mesh_path)
    report["artifacts"]["half_section_mesh_lineage"] = section_lineage_path.relative_to(ROOT).as_posix()
    report["artifacts"]["half_section_mesh_lineage_sha256"] = file_sha256(section_lineage_path)
    report["artifacts"]["actual_png"] = PREVIEW.relative_to(ROOT).as_posix()
    report["artifacts"]["actual_png_sha256"] = file_sha256(PREVIEW)
    report["status"] = "BREP_CANDIDATE" if all(checks.values()) else "FAIL_OR_UNKNOWN_BREP_CANDIDATE"
    report["candidate_state"] = report["status"]
    report["candidate_decision"] = "NOT_PROMOTED; native BREP candidate only; parent review required; forge.asset.v1 remains canonical STEP"
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    write_report(report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "mesh_refinement": report["mesh_refinement"],
                "checks": checks,
                "report": str(REPORT_PATH),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "BREP_CANDIDATE" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.is_file() else {}
        report["status"] = "FAIL_REFINEMENT_EXCEPTION"
        report["candidate_state"] = report["status"]
        report.setdefault("mesh_refinement", {})["status"] = "FAIL"
        report["mesh_refinement"]["exception"] = {"type": type(exc).__name__, "message": str(exc)}
        report["mesh_refinement"]["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_report(report)
        print(json.dumps({"status": report["status"], "exception": report["mesh_refinement"]["exception"]}, ensure_ascii=False))
        raise
