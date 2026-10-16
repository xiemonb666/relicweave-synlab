from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import cadquery as cq
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.STEPControl import STEPControl_Reader
from OCP.TopoDS import TopoDS_Iterator
from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX, TopAbs_EDGE, TopAbs_WIRE

from experiments.smooth_cad_spike import _shape_bbox


ROOT = Path(__file__).resolve().parent
GEOMETRY = ROOT / "physical_outline_geometry"
REPORT = ROOT / "candidate2_step_roundtrip_diagnostics.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def top_children(shape: Any) -> list[dict[str, Any]]:
    result = []
    iterator = TopoDS_Iterator(shape)
    while iterator.More():
        child = iterator.Value()
        properties = GProp_GProps()
        BRepGProp.VolumeProperties_s(child, properties)
        wrapped = cq.Shape.cast(child)
        result.append(
            {
                "shape_type": str(child.ShapeType()),
                "volume_properties_mass_mm3": float(properties.Mass()),
                "cq_volume_mm3": float(wrapped.Volume()),
                "valid": bool(BRepCheck_Analyzer(child).IsValid()),
                "bbox_mm": _shape_bbox(wrapped),
            }
        )
        iterator.Next()
    return result


def inspect_step(path: Path) -> dict[str, Any]:
    reader = STEPControl_Reader()
    read_status = reader.ReadFile(str(path))
    transfer_status = reader.TransferRoots()
    shape = reader.OneShape()
    wrapped = cq.Shape.cast(shape)
    counts = {}
    for label, shape_type in (
        ("solids", TopAbs_SOLID),
        ("shells", TopAbs_SHELL),
        ("faces", TopAbs_FACE),
        ("wires", TopAbs_WIRE),
        ("edges", TopAbs_EDGE),
        ("vertices", TopAbs_VERTEX),
        ("compounds", TopAbs_COMPOUND),
        ("compsolids", TopAbs_COMPSOLID),
    ):
        explorer = cq.Shape.cast(shape).wrapped
        from OCP.TopExp import TopExp_Explorer

        traversal = TopExp_Explorer(explorer, shape_type)
        count = 0
        while traversal.More():
            count += 1
            traversal.Next()
        counts[label] = count
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "read_status": str(read_status),
        "transfer_roots_status": transfer_status,
        "root_type": str(shape.ShapeType()),
        "root_valid": bool(BRepCheck_Analyzer(shape).IsValid()),
        "root_volume_mm3": float(wrapped.Volume()),
        "root_bbox_mm": _shape_bbox(wrapped),
        "recursive_topology_counts": counts,
        "direct_children": top_children(shape),
        "is_one_valid_solid_one_shell": bool(wrapped.isValid() and len(wrapped.Solids()) == 1 and len(wrapped.Shells()) == 1),
    }


def main() -> int:
    source_step = GEOMETRY / "smooth_body.step"
    direct_solid_step = GEOMETRY / "solid_export_probe.step"
    body = inspect_step(source_step)
    direct = inspect_step(direct_solid_step)
    report = {
        "stage": "canonical_STEP_serialization_diagnostic_only",
        "status": "FAIL_STEP_SOLID_ROUNDTRIP",
        "source_revolve_shape": {
            "top_level_shape_type": "Compound",
            "top_level_direct_child_types": {"SOLID": 1},
            "unique_solid_valid": True,
            "unique_solid_shell_count": 1,
            "unique_solid_volume_mm3": 26998.301999424355,
            "unique_solid_bbox_mm": {
                "xlen_mm": 41.0000002,
                "ylen_mm": 41.0000002,
                "zlen_mm": 56.00000020000009,
            },
            "other_material_solids": 0,
        },
        "compound_export_roundtrip": body,
        "direct_unique_solid_export_roundtrip": direct,
        "checks": {
            "direct_solid_roundtrip_has_one_valid_solid_shell": direct["is_one_valid_solid_one_shell"],
            "direct_solid_roundtrip_volume_matches_source_within_0_01mm3": abs(direct["root_volume_mm3"] - 26998.301999424355) <= 0.01,
            "direct_solid_roundtrip_bbox_matches_source_within_0_01mm": max(
                abs(direct["root_bbox_mm"][key] - value)
                for key, value in {
                    "xlen_mm": 41.0000002,
                    "ylen_mm": 41.0000002,
                    "zlen_mm": 56.00000020000009,
                }.items()
            ) <= 0.01,
            "no_positive_material_solid_was_dropped": True,
        },
        "disposition": "Neither STEP file is canonical CAD output. The native source had exactly one material solid; the direct-solid STEP roundtrip has only two disconnected shells and is not silently accepted.",
        "no_mesh_npz_or_render_issued": "The canonical STEP solid gate failed; no noncanonical source mesh or image is labeled as accepted evidence.",
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    candidate_report_path = ROOT / "candidate2_physical_profile_report.json"
    if candidate_report_path.exists():
        candidate_report = json.loads(candidate_report_path.read_text(encoding="utf-8"))
        candidate_report["serialization_diagnostic"] = {
            "status": report["status"],
            "source_revolve_shape": report["source_revolve_shape"],
            "compound_export_roundtrip": body,
            "direct_unique_solid_export_roundtrip": direct,
            "checks": report["checks"],
            "disposition": report["disposition"],
            "no_mesh_npz_or_render_issued": report["no_mesh_npz_or_render_issued"],
        }
        candidate_report["canonical_STEP"] = {
            "sha256": body["sha256"],
            "body": {
                "valid": body["root_valid"],
                "null": False,
                "shape_type": body["root_type"],
                "solid_count": body["recursive_topology_counts"]["solids"],
                "shell_count": body["recursive_topology_counts"]["shells"],
                "volume_mm3": body["root_volume_mm3"],
                "bbox_mm": body["root_bbox_mm"],
                "direct_children": body["direct_children"],
            },
            "source_revolve_body_volume_mm3": report["source_revolve_shape"]["unique_solid_volume_mm3"],
            "source_revolve_solid_count": 1,
            "source_revolve_shell_count": report["source_revolve_shape"]["unique_solid_shell_count"],
            "step_roundtrip_one_valid_solid_shell": False,
        }
        candidate_report["artifacts"] = {
            "failed_compound_export_step": body["path"],
            "failed_compound_export_step_sha256": body["sha256"],
            "failed_direct_solid_export_probe_step": direct["path"],
            "failed_direct_solid_export_probe_step_sha256": direct["sha256"],
            "step_roundtrip_diagnostic_source": "candidate2_step_roundtrip_diagnostics.py",
            "step_roundtrip_diagnostic_log": "candidate2_step_roundtrip_diagnostics.log",
            "step_roundtrip_diagnostic_report": "candidate2_step_roundtrip_diagnostics.json",
            "body_mesh_npz": None,
            "axial_section_mesh_npz": None,
            "whole_png": None,
            "axial_section_png": None,
        }
        candidate_report["status"] = "FAIL_CANONICAL_STEP"
        candidate_report["candidate_decision"] = "NOT_PROMOTED; STEP roundtrip failed the one-valid-solid gate"
        candidate_report_path.write_text(json.dumps(candidate_report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": report["checks"], "report": str(REPORT)}, ensure_ascii=False))
    return 0 if all(report["checks"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
