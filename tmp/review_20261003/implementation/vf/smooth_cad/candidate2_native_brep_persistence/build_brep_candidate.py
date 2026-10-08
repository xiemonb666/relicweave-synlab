from __future__ import annotations

import hashlib
import json
import math
import traceback
from pathlib import Path
from typing import Any

import cadquery as cq
import numpy as np
import OCP
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
from OCP.GeomAbs import GeomAbs_JoinType
from OCP.GeomConvert import GeomConvert
from OCP.gp import gp_Pnt, gp_Vec

from experiments.smooth_cad_spike import (
    MESH_ANGULAR_RAD,
    _native_curve_inventory,
    _shape_bbox,
    measure_floor_thickness,
    sample_sidewall_normal_rays,
)
from vesselforge.geometry import (
    VesselSpec,
    mesh_shape,
    mesh_topology_metrics,
    sampled_mesh_to_cad_metrics,
)
from vesselforge.schema import sha256_file


ROOT = Path(__file__).resolve().parent
GEOMETRY = ROOT / "geometry"
REPORT_PATH = ROOT / "brep_candidate_report.json"
DESIGN_ROOT = ROOT.parent / "candidate2_native_2d_offset_wall4"

import sys

sys.path.insert(0, str(DESIGN_ROOT))
import candidate2_physical_profile as design  # noqa: E402


WALL_MM = 4.0
SPEC = VesselSpec(
    body_width_mm=41.0,
    body_height_mm=56.0,
    wall_mm=WALL_MM,
    tessellation_linear_mm=0.05,
    tessellation_angular_rad=MESH_ANGULAR_RAD,
)


def write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shape_summary(shape: cq.Shape) -> dict[str, Any]:
    solids = shape.Solids()
    return {
        "valid": bool(shape.isValid()),
        "null": bool(shape.isNull()),
        "shape_type": str(shape.ShapeType()),
        "solid_count": len(solids),
        "shell_count": len(shape.Shells()),
        "volume_mm3": float(shape.Volume()),
        "bbox_mm": _shape_bbox(shape) if not shape.isNull() else None,
        "solid_validity": [bool(solid.isValid()) for solid in solids],
        "solid_volumes_mm3": [float(solid.Volume()) for solid in solids],
        "solid_shell_counts": [len(solid.Shells()) for solid in solids],
    }


def tolerance_inventory(shape: cq.Shape) -> dict[str, Any]:
    values: dict[str, list[float]] = {"vertex_mm": [], "edge_mm": [], "face_mm": []}
    for vertex in shape.Vertices():
        values["vertex_mm"].append(float(BRep_Tool.Tolerance_s(vertex.wrapped)))
    for edge in shape.Edges():
        values["edge_mm"].append(float(BRep_Tool.Tolerance_s(edge.wrapped)))
    for face in shape.Faces():
        values["face_mm"].append(float(BRep_Tool.Tolerance_s(face.wrapped)))
    return {
        "method": "native BRep_Tool.Tolerance_s on every canonical subshape; all units mm",
        "by_subshape_type": {
            kind: {
                "count": len(items),
                "minimum_mm": min(items) if items else None,
                "maximum_mm": max(items) if items else None,
            }
            for kind, items in values.items()
        },
        "maximum_mm": max((max(items) for items in values.values() if items), default=None),
    }


def fail(report: dict[str, Any], status: str, reason: str) -> int:
    report["status"] = status
    report.setdefault("failures", []).append(reason)
    write_report(report)
    print(json.dumps({"status": status, "reason": reason, "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 2


def canonical_compare(source: cq.Shape, restored: cq.Shape, tolerance_mm: float = 0.01) -> dict[str, Any]:
    source_bbox = _shape_bbox(source)
    restored_bbox = _shape_bbox(restored)
    bbox_keys = ("xlen_mm", "ylen_mm", "zlen_mm")
    deltas = {key: float(restored_bbox[key] - source_bbox[key]) for key in bbox_keys}
    source_solid = source.Solids()[0] if len(source.Solids()) == 1 else None
    restored_solid = restored.Solids()[0] if len(restored.Solids()) == 1 else None
    source_volume = float(source_solid.Volume()) if source_solid is not None else None
    restored_volume = float(restored_solid.Volume()) if restored_solid is not None else None
    volume_delta = restored_volume - source_volume if source_volume is not None and restored_volume is not None else None
    return {
        "source": shape_summary(source),
        "restored": shape_summary(restored),
        "bbox_length_deltas_mm": deltas,
        "max_abs_bbox_length_delta_mm": max(abs(value) for value in deltas.values()),
        "source_unique_solid_volume_mm3": source_volume,
        "restored_unique_solid_volume_mm3": restored_volume,
        "solid_volume_delta_mm3": volume_delta,
        "tolerance_mm": tolerance_mm,
        "one_valid_solid_shell_preserved": bool(
            source.isValid()
            and restored.isValid()
            and len(source.Solids()) == 1
            and len(restored.Solids()) == 1
            and len(source.Shells()) == 1
            and len(restored.Shells()) == 1
            and source.Solids()[0].isValid()
            and restored.Solids()[0].isValid()
        ),
        "volume_preserved": bool(volume_delta is not None and abs(volume_delta) <= tolerance_mm),
        "bbox_preserved": bool(max(abs(value) for value in deltas.values()) <= tolerance_mm),
    }


def make_candidate_shape() -> tuple[cq.Shape, dict[str, Any]]:
    lower = design.bezier_as_bspline(design.LOWER_POLES_RZ)
    upper = design.bezier_as_bspline(design.UPPER_POLES_RZ)
    side_wire = cq.Wire.assembleEdges([lower, upper])
    if not side_wire.isValid() or side_wire.IsClosed() or len(side_wire.Edges()) != 2:
        raise ValueError("physical profile did not produce a valid open 2-edge meridian wire")
    source_edge_reports = [design.native_edge_report(edge) for edge in [lower, upper]]
    join = design.derivative_join_report(lower, upper)
    curvature = design.curvature_report([lower, upper])
    if not all(edge["is_C2"] for edge in source_edge_reports) or not join["C2_join"]:
        raise ValueError("native meridian failed internal C2 derivative checks")
    if curvature["samples_below_threshold"]:
        raise ValueError("source profile sampled curvature radius fell below wall plus margin")

    offset = BRepOffsetAPI_MakeOffset()
    offset.Init(GeomAbs_JoinType.GeomAbs_Arc, True)
    offset.AddWire(side_wire.wrapped)
    offset.Perform(WALL_MM)
    offset.Build()
    raw = offset.Shape()
    if not offset.IsDone() or raw.IsNull():
        raise ValueError("native OCC planar offset failed to produce a shape")
    offset_shape = cq.Shape.cast(raw)
    offset_wires = offset_shape.Wires()
    if len(offset_wires) != 1 or not offset_wires[0].isValid() or offset_wires[0].IsClosed():
        raise ValueError("native inward offset is not one valid open wire")
    offset_wire = offset_wires[0]
    endpoints = [vertex.Center().toTuple() for vertex in offset_wire.Vertices()]
    bottom_inner = min(endpoints, key=lambda point: float(point[2]))
    top_inner = max(endpoints, key=lambda point: float(point[2]))
    bottom_error = float(np.linalg.norm(np.asarray(bottom_inner) - np.asarray([12.5, 0.0, WALL_MM])))
    top_error = float(np.linalg.norm(np.asarray(top_inner) - np.asarray([14.0, 0.0, 56.0])))
    if max(bottom_error, top_error) > 0.10:
        raise ValueError("native offset endpoints do not meet the bottom floor and vertical lip")
    profile_edges = [
        cq.Edge.makeLine(cq.Vector(0.0, 0.0, 0.0), lower.startPoint()),
        lower,
        upper,
        cq.Edge.makeLine(upper.endPoint(), cq.Vector(14.0, 0.0, 56.0)),
        *[edge.reverse() for edge in reversed(offset_wire.Edges())],
        cq.Edge.makeLine(cq.Vector(12.5, 0.0, WALL_MM), cq.Vector(0.0, 0.0, WALL_MM)),
        cq.Edge.makeLine(cq.Vector(0.0, 0.0, WALL_MM), cq.Vector(0.0, 0.0, 0.0)),
    ]
    profiles = cq.Wire.combine(profile_edges, tol=1e-6)
    if len(profiles) != 1 or not profiles[0].isValid() or not profiles[0].IsClosed():
        raise ValueError("closed material meridian did not form one valid wire")
    face = cq.Face.makeFromWires(profiles[0])
    if not face.isValid() or face.Area() <= 0:
        raise ValueError("closed material meridian did not form one positive-area face")
    constructed = cq.Workplane("XZ").newObject([profiles[0]]).toPending().revolve(
        360.0, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), combine=False
    ).val()
    if not constructed.isValid() or len(constructed.Solids()) != 1 or len(constructed.Shells()) != 1:
        raise ValueError("revolved source body is not one valid solid/shell")
    if len(constructed.Solids()) != 1:
        raise ValueError("refusing to drop any extra source material solids")
    return constructed.Solids()[0], {
        "source_meridian": {"native_edges": source_edge_reports, "internal_join": join, "curvature": curvature},
        "offset": {
            "api": "BRepOffsetAPI_MakeOffset",
            "distance_mm": WALL_MM,
            "is_done": bool(offset.IsDone()),
            "valid": bool(offset_shape.isValid()),
            "wire_count": len(offset_wires),
            "offset_wire_edge_count": len(offset_wire.Edges()),
            "bottom_endpoint_error_mm": bottom_error,
            "top_endpoint_error_mm": top_error,
        },
        "closed_profile": {"valid": bool(profiles[0].isValid()), "face_valid": bool(face.isValid()), "face_area_mm2": float(face.Area())},
        "constructed_compound": shape_summary(constructed),
    }


def main() -> int:
    if GEOMETRY.exists() and any(GEOMETRY.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty native BREP candidate folder: {GEOMETRY}")
    GEOMETRY.mkdir(parents=True, exist_ok=True)
    source_script = DESIGN_ROOT / "candidate2_physical_profile.py"
    first_report = DESIGN_ROOT / "candidate2_physical_profile_report.json"
    report: dict[str, Any] = {
        "experiment_id": "vf.c2-meridian-constrained-brep-canonical/1.0.0",
        "model_version": "physical-open-cup-profile-v1",
        "stage": "serialization_alternative_only_native_brep",
        "status": "RUNNING",
        "candidate_decision": "NOT_PROMOTED; production STEP contract unchanged; parent review required",
        "production_generator_changed": False,
        "production_asset_contract_changed": False,
        "production_semantics_changed": False,
        "construction": {
            "reuse": "same two degree-5 C2 B-spline spans, same +4 mm native planar offset, and same closed material meridian recorded by candidate2_native_2d_offset_wall4",
            "body_dimensions_mm": {"nominal_height": 56.0, "nominal_width": 41.0, "wall": 4.0},
            "persistence": "CadQuery Shape.exportBrep then Shape.importBrep; no STEP is written or fabricated for this candidate",
            "cadquery_version": cq.__version__,
            "ocp_version": OCP.__version__,
            "linear_units": "mm",
            "brep_precision_policy": "native per-subshape OCC tolerances are measured and reported; roundtrip acceptance uses volume and bbox length deltas <=0.01 mm / mm^3",
            "depends_on_kernel_native_brep": True,
        },
        "reference_STEP_failure": {
            "report": "../candidate2_native_2d_offset_wall4/candidate2_physical_profile_report.json",
            "status": "FAIL_CANONICAL_STEP",
            "note": "the old failed STEP and direct-solid STEP probe remain preserved; this BREP candidate does not claim that production STEP serialization or the existing asset contract is supported",
        },
        "limitations": [
            "Body-only open-cup family spike; no handle, fused root, or root fillet.",
            "BREP_CANDIDATE is an experimental native-persistence result, not production promotion or A12 adapter support.",
            "BREP persistence depends on OCC/CadQuery version and native tolerances; cross-machine portability is unverified.",
            "Sampled profile curvature and normal-ray wall distances are finite evidence, not a global proof.",
            "Production B-spline face semantics remain UNKNOWN and production files are unchanged.",
        ],
    }
    write_report(report)
    try:
        source_solid, construction_details = make_candidate_shape()
        report["construction_details"] = construction_details
        report["native_source_solid"] = shape_summary(source_solid)
        report["native_source_tolerances"] = tolerance_inventory(source_solid)
        if not source_solid.isValid() or len(source_solid.Solids()) != 1 or len(source_solid.Shells()) != 1:
            return fail(report, "FAIL_SOURCE_SOLID", "source body is not exactly one valid material solid and shell")

        body_brep = GEOMETRY / "smooth_body.brep"
        written = bool(source_solid.exportBrep(str(body_brep)))
        report["native_BREP_persistence"] = {
            "writer": "CadQuery Shape.exportBrep -> OCP BRepTools native BREP writer",
            "reader": "CadQuery Shape.importBrep -> OCP BRepTools native BREP reader",
            "writer_returned_true": written,
            "file_bytes": body_brep.stat().st_size if body_brep.exists() else None,
            "file_header": body_brep.read_bytes()[:256].decode("ascii", errors="replace") if body_brep.exists() else None,
            "sha256": sha256(body_brep) if body_brep.exists() else None,
            "kernel_versions": {"cadquery": cq.__version__, "ocp": OCP.__version__},
        }
        if not written or not body_brep.exists():
            return fail(report, "FAIL_BREP_WRITE", "native BREP writer did not produce an artifact")
        canonical = cq.Shape.importBrep(str(body_brep))
        comparison = canonical_compare(source_solid, canonical)
        report["native_BREP_roundtrip"] = comparison
        report["canonical_native_tolerances"] = tolerance_inventory(canonical)
        if not (
            comparison["one_valid_solid_shell_preserved"]
            and comparison["volume_preserved"]
            and comparison["bbox_preserved"]
        ):
            return fail(report, "FAIL_BREP_ROUNDTRIP", "native BREP roundtrip failed one-solid/shell, volume, or bbox preservation")

        vertices, faces, lineage = mesh_shape(canonical, SPEC)
        topology = mesh_topology_metrics(vertices, faces)
        mesh_cad = sampled_mesh_to_cad_metrics(canonical, vertices, faces, lineage)
        np.savez_compressed(GEOMETRY / "surface.npz", vertices_mm=vertices.astype(np.float64), faces=faces.astype(np.int32))
        np.savez_compressed(GEOMETRY / "mesh_lineage.npz", face_source_brep_index=lineage.astype(np.int32))
        # This helper is used only as a metric implementation. Its result is
        # labeled below as a native-BREP comparison, not a canonical STEP test.
        mesh_cad["canonical_reference_kind"] = "native BREP reimport; no STEP used"
        wall = sample_sidewall_normal_rays(canonical)
        floor = measure_floor_thickness(canonical)
        bbox = _shape_bbox(canonical)
        report["canonical_native_BREP"] = {
            "shape": shape_summary(canonical),
            "bbox_mm": bbox,
            "actual_height_mm": bbox["zlen_mm"],
            "actual_width_mm": max(bbox["xlen_mm"], bbox["ylen_mm"]),
            "nominal_height_mm": SPEC.body_height_mm,
            "nominal_width_mm": SPEC.body_width_mm,
            "radial_overshoot_mm": max(bbox["xlen_mm"], bbox["ylen_mm"]) / 2.0 - SPEC.body_width_mm / 2.0,
            "native_bspline_inventory": _native_curve_inventory(canonical),
        }
        report["wall"] = {"declared_mm": WALL_MM, "sidewall_normal_rays": wall, "floor_thickness": floor}
        report["mesh"] = {
            "absolute_chord_target_mm": SPEC.tessellation_linear_mm,
            "angular_tolerance_rad": SPEC.tessellation_angular_rad,
            "topology": topology,
            "mesh_to_native_BREP": mesh_cad,
            "sampling_acceptance_max_mm": 0.10,
        }

        box = cq.Solid.makeBox(120.0, 70.0, 100.0, cq.Vector(-40.0, 0.0, -20.0))
        cut = canonical.intersect(box).clean()
        cut_solids = cut.Solids()
        cut_volume = float(sum(solid.Volume() for solid in cut_solids))
        ratio = cut_volume / max(float(canonical.Volume()), 1e-12)
        cut_valid = bool(
            not cut.isNull()
            and cut.isValid()
            and cut_solids
            and all(solid.isValid() and solid.Volume() > 0.0 for solid in cut_solids)
            and abs(ratio - 0.5) <= 0.01
        )
        report["native_half_section"] = {
            "method": "canonical native-BREP solid intersected with the true y>=0 half-space box; any count of solids is permitted only if all are valid and combined volume is half within 1%",
            "shape": shape_summary(cut),
            "solid_count": len(cut_solids),
            "solid_validity": [bool(solid.isValid()) for solid in cut_solids],
            "solid_volumes_mm3": [float(solid.Volume()) for solid in cut_solids],
            "retained_volume_mm3": cut_volume,
            "full_volume_mm3": float(canonical.Volume()),
            "retained_volume_fraction": ratio,
            "acceptance": cut_valid,
        }
        if not cut_valid:
            return fail(report, "FAIL_NATIVE_HALF_SECTION", "native half-space cut is empty, invalid, or not volume preserving")

        cut_brep = GEOMETRY / "axial_half_section.brep"
        cut_written = bool(cut.exportBrep(str(cut_brep)))
        if not cut_written or not cut_brep.exists():
            return fail(report, "FAIL_SECTION_BREP_WRITE", "native half-section BREP writer failed")
        canonical_cut = cq.Shape.importBrep(str(cut_brep))
        cut_source_summary = shape_summary(cut)
        cut_roundtrip_summary = shape_summary(canonical_cut)
        cut_roundtrip = bool(
            canonical_cut.isValid()
            and len(canonical_cut.Solids()) == len(cut_solids)
            and all(solid.isValid() for solid in canonical_cut.Solids())
            and abs(canonical_cut.Volume() - cut.Volume()) <= 0.01
            and max(
                abs(_shape_bbox(canonical_cut)[key] - _shape_bbox(cut)[key])
                for key in ("xlen_mm", "ylen_mm", "zlen_mm")
            )
            <= 0.01
        )
        report["native_half_section_BREP_roundtrip"] = {
            "sha256": sha256(cut_brep),
            "source": cut_source_summary,
            "restored": cut_roundtrip_summary,
            "same_valid_solid_count": len(canonical_cut.Solids()) == len(cut_solids),
            "volume_delta_mm3": float(canonical_cut.Volume() - cut.Volume()),
            "bbox_delta_max_mm": max(
                abs(_shape_bbox(canonical_cut)[key] - _shape_bbox(cut)[key])
                for key in ("xlen_mm", "ylen_mm", "zlen_mm")
            ),
            "roundtrip_preserved": cut_roundtrip,
        }
        if not cut_roundtrip:
            return fail(report, "FAIL_SECTION_BREP_ROUNDTRIP", "native half-section BREP roundtrip did not preserve valid solids, volume, and bbox")

        cut_vertices, cut_faces, cut_lineage = mesh_shape(canonical_cut, SPEC)
        cut_topology = mesh_topology_metrics(cut_vertices, cut_faces)
        cut_mesh_cad = sampled_mesh_to_cad_metrics(canonical_cut, cut_vertices, cut_faces, cut_lineage)
        cut_mesh_cad["canonical_reference_kind"] = "native BREP half-section reimport; no STEP used"
        np.savez_compressed(GEOMETRY / "axial_section.npz", vertices_mm=cut_vertices.astype(np.float64), faces=cut_faces.astype(np.int32))
        np.savez_compressed(GEOMETRY / "axial_section_lineage.npz", face_source_brep_index=cut_lineage.astype(np.int32))
        report["axial_section_mesh"] = {
            "topology": cut_topology,
            "mesh_to_native_BREP_section": cut_mesh_cad,
            "sampling_acceptance_max_mm": 0.10,
        }

        source_script_hash = sha256(source_script) if source_script.exists() else None
        report["checks"] = {
            "source_profile_native_C2": bool(construction_details["source_meridian"]["internal_join"]["C2_join"]),
            "source_profile_sampled_rho_at_least_5mm": bool(construction_details["source_meridian"]["curvature"]["samples_below_threshold"] == 0),
            "body_native_BREP_one_valid_solid_shell": comparison["one_valid_solid_shell_preserved"],
            "body_native_BREP_volume_bbox_preserved": comparison["volume_preserved"] and comparison["bbox_preserved"],
            "body_actual_height_within_0_10mm": abs(bbox["zlen_mm"] - SPEC.body_height_mm) <= 0.10,
            "body_actual_width_within_0_10mm": abs(max(bbox["xlen_mm"], bbox["ylen_mm"]) - SPEC.body_width_mm) <= 0.10,
            "body_mesh_watertight_positive": bool(topology["watertight"] and topology["signed_volume_mm3"] > 0),
            "body_mesh_to_cad_under_0_10mm": bool(mesh_cad["unknown_sample_count"] == 0 and mesh_cad["max_sampled_deviation_mm"] is not None and mesh_cad["max_sampled_deviation_mm"] <= 0.10),
            "wall_ray_sampling_no_unknowns": bool(wall["candidate_outer_side_samples"] > 0 and wall["unknown_count"] == 0),
            "sampled_wall_within_0_10mm_of_4mm": bool(wall["sampled_wall_min_mm"] is not None and wall["sampled_wall_max_mm"] is not None and abs(wall["sampled_wall_min_mm"] - WALL_MM) <= 0.10 and abs(wall["sampled_wall_max_mm"] - WALL_MM) <= 0.10),
            "floor_thickness_within_0_05mm": bool(floor.get("status") == "MEASURED_FROM_CANONICAL_STEP_PLANAR_FACES" and abs(floor["distance_mm"] - WALL_MM) <= 0.05),
            "native_half_section_valid_and_volume_preserving": cut_valid,
            "half_section_BREP_roundtrip_preserved": cut_roundtrip,
            "section_mesh_watertight_positive": bool(cut_topology["watertight"] and cut_topology["signed_volume_mm3"] > 0),
            "section_mesh_to_cad_under_0_10mm": bool(cut_mesh_cad["unknown_sample_count"] == 0 and cut_mesh_cad["max_sampled_deviation_mm"] is not None and cut_mesh_cad["max_sampled_deviation_mm"] <= 0.10),
        }
        report["native_BREP_artifacts"] = {
            "body_brep": "geometry/smooth_body.brep",
            "body_brep_sha256": sha256(body_brep),
            "half_section_brep": "geometry/axial_half_section.brep",
            "half_section_brep_sha256": sha256(cut_brep),
            "body_mesh_npz": "geometry/surface.npz",
            "body_mesh_lineage_npz": "geometry/mesh_lineage.npz",
            "axial_section_mesh_npz": "geometry/axial_section.npz",
            "axial_section_lineage_npz": "geometry/axial_section_lineage.npz",
            "source_profile_file": "../candidate2_native_2d_offset_wall4/candidate2_physical_profile.py",
            "source_profile_sha256": source_script_hash,
        }
        report["status"] = "BREP_CANDIDATE" if all(report["checks"].values()) else "FAIL_OR_UNKNOWN_BREP_CANDIDATE"
        report["candidate_decision"] = "NOT_PROMOTED; BREP-native candidate only; production STEP/asset.v1 and A12 support remain unchanged"
        write_report(report)
        print(json.dumps({"status": report["status"], "checks": report["checks"], "report": str(REPORT_PATH)}, ensure_ascii=False))
        return 0 if report["status"] == "BREP_CANDIDATE" else 2
    except Exception as exc:
        report["status"] = "FAIL_EXCEPTION"
        report["exception"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        write_report(report)
        print(json.dumps({"status": report["status"], "exception": report["exception"], "report": str(REPORT_PATH)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
