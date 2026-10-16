from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import cadquery as cq
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

from experiments.smooth_cad_spike import (
    MESH_ANGULAR_RAD,
    MESH_TARGET_MM,
    _shape_bbox,
    _native_curve_inventory,
    build_shelled_body,
    diagnose_handle_fusion,
    make_c2_meridian_wire,
    measure_floor_thickness,
    sample_sidewall_normal_rays,
)
from vesselforge.geometry import (
    VesselSpec,
    build_components,
    mesh_shape,
    mesh_topology_metrics,
    sampled_mesh_to_cad_metrics,
    scaled_outer_profile,
)
from vesselforge.schema import sha256_file

ROOT = Path(__file__).resolve().parent
STEP_PATH = ROOT / "geometry" / "smooth_body.step"
REPORT_PATH = ROOT / "smooth_cad_spike_report.json"


def box_bbox(box: Bnd_Box) -> list[float] | None:
    try:
        return [float(v) for v in box.Get()]
    except Exception:
        return None


def shape_metrics(shape: cq.Shape) -> dict[str, object]:
    try:
        bbox = _shape_bbox(shape) if not shape.isNull() else None
    except Exception:
        bbox = None
    return {
        "is_valid": bool(shape.isValid()),
        "is_null": bool(shape.isNull()),
        "solid_count": len(shape.Solids()),
        "shell_count": len(shape.Shells()),
        "volume_mm3": float(shape.Volume()),
        "bbox_mm": bbox,
        "solid_validity": [bool(solid.isValid()) for solid in shape.Solids()],
        "solid_volumes_mm3": [float(solid.Volume()) for solid in shape.Solids()],
        "solid_shell_counts": [len(solid.Shells()) for solid in shape.Solids()],
    }


def section_wire(shape: cq.Shape) -> tuple[dict[str, object], dict[str, np.ndarray]]:
    # A plane face large enough in both local axes; the earlier bounded face
    # accidentally clipped the negative-X meridian.
    cutting_face = BRepBuilderAPI_MakeFace(
        gp_Pln(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 1.0, 0.0)),
        -100.0,
        100.0,
        -100.0,
        100.0,
    ).Face()
    algorithm = BRepAlgoAPI_Section(shape.wrapped, cutting_face, False)
    algorithm.Approximation(True)
    algorithm.Build()
    section = cq.Shape.cast(algorithm.Shape())
    edges = section.Edges()
    wires = cq.Wire.combine(edges, tol=1e-5)
    edge_points: list[list[float]] = []
    offsets = [0]
    edge_records: list[dict[str, object]] = []
    for index, edge in enumerate(edges):
        adaptor = BRepAdaptor_Curve(edge.wrapped)
        first = float(adaptor.FirstParameter())
        last = float(adaptor.LastParameter())
        sample_count = 2 if "Line" in str(adaptor.GetType()) else 161
        values = np.linspace(first, last, sample_count, dtype=np.float64)
        sampled = []
        for value in values:
            point = adaptor.Value(float(value))
            sampled.append([float(point.X()), float(point.Y()), float(point.Z())])
        edge_points.extend(sampled)
        offsets.append(len(edge_points))
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(edge.wrapped, box, False, False)
        edge_records.append(
            {
                "edge_index_zero_based": index,
                "curve_type": str(adaptor.GetType()),
                "first_parameter": first,
                "last_parameter": last,
                "sample_count": sample_count,
                "bbox_mm": box_bbox(box),
                "start_xyz_mm": sampled[0],
                "end_xyz_mm": sampled[-1],
            }
        )
    wire_metrics = {
        "method": "OpenCascade BRepAlgoAPI_Section of canonical STEP body with a plane face spanning ±100 mm in both plane parameters; edges assembled with CadQuery Wire.combine(tol=1e-5)",
        "section_algorithm_done": bool(algorithm.IsDone()),
        "section_edge_count": len(edges),
        "section_vertex_count": len(section.Vertices()),
        "section_solid_count": len(section.Solids()),
        "section_shell_count": len(section.Shells()),
        "section_shape_valid": bool(section.isValid()),
        "section_shape_volume_mm3_non_solid_diagnostic_only": float(section.Volume()),
        "wire_count": len(wires),
        "wires": [
            {
                "closed": bool(wire.IsClosed()),
                "valid": bool(wire.isValid()),
                "edge_count": len(wire.Edges()),
                "length_mm": float(wire.Length()),
                "bbox_mm": _shape_bbox(wire),
            }
            for wire in wires
        ],
        "edge_records": edge_records,
        "scope": "exact canonical STEP intersection edges, discretized only for NPZ/PNG linework; not a volumetric half-section",
    }
    try:
        face = cq.Face.makeFromWires(wires[0]) if len(wires) == 1 and wires[0].IsClosed() else None
        wire_metrics["planar_fill_face"] = (
            {"valid": bool(face.isValid()), "area_mm2": float(face.Area())} if face is not None else None
        )
    except Exception as exc:
        wire_metrics["planar_fill_face"] = {
            "valid": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    return wire_metrics, {
        "edge_points_mm": np.asarray(edge_points, dtype=np.float64),
        "edge_offsets": np.asarray(offsets, dtype=np.int32),
        "edge_curve_type": np.asarray([str(BRepAdaptor_Curve(edge.wrapped).GetType()) for edge in edges]),
    }


def volumetric_section_diagnostics(shape: cq.Shape) -> dict[str, object]:
    body = shape
    positive_y_box = cq.Solid.makeBox(120.0, 70.0, 100.0, cq.Vector(-40.0, 0.0, -20.0))
    negative_y_box = cq.Solid.makeBox(120.0, 70.0, 100.0, cq.Vector(-40.0, -70.0, -20.0))
    negative_x_box = cq.Solid.makeBox(70.0, 120.0, 100.0, cq.Vector(-70.0, -60.0, -20.0))
    positive_half = body.intersect(positive_y_box).clean()
    negative_half_cut = body.cut(negative_y_box).clean()
    negative_x_half = body.intersect(negative_x_box).clean()
    return {
        "production_section_helper_contract": "one valid solid after intersection with a half-space box",
        "positive_y_halfspace_intersection": shape_metrics(positive_half),
        "negative_y_removed_by_cut": shape_metrics(negative_half_cut),
        "negative_x_halfspace_intersection": shape_metrics(negative_x_half),
        "negative_y_cut_volume_exceeds_parent": bool(negative_half_cut.Volume() > body.Volume()),
        "acceptance": "FAIL: no volume-preserving valid half-section solid was produced; empty commons and an invalid over-volume cut are not accepted as real geometry",
    }


def main() -> int:
    if not STEP_PATH.is_file():
        raise FileNotFoundError(STEP_PATH)
    spec = replace(
        VesselSpec(),
        body_width_mm=41.0,
        body_height_mm=56.0,
        wall_mm=4.0,
        tessellation_linear_mm=MESH_TARGET_MM,
        tessellation_angular_rad=MESH_ANGULAR_RAD,
    )
    body = cq.importers.importStep(str(STEP_PATH)).val()
    if not body.isValid() or len(body.Solids()) != 1 or len(body.Shells()) != 1:
        raise ValueError("canonical STEP body is not one valid solid/shell")

    # Mesh only the already-exported canonical STEP body; this does not rebuild
    # another candidate body.
    vertices, triangles, lineage = mesh_shape(body, spec)
    topology = mesh_topology_metrics(vertices, triangles)
    mesh_cad = sampled_mesh_to_cad_metrics(body, vertices, triangles, lineage)
    np.savez_compressed(
        ROOT / "geometry" / "surface.npz",
        vertices_mm=vertices.astype(np.float64),
        faces=triangles.astype(np.int32),
    )
    np.savez_compressed(
        ROOT / "geometry" / "mesh_lineage.npz",
        face_source_brep_index=lineage.astype(np.int32),
    )

    meridian_sketch, source_meridian = make_c2_meridian_wire(spec)
    wire_metrics, section_arrays = section_wire(body)
    np.savez_compressed(ROOT / "geometry" / "axial_section.npz", **section_arrays)
    wall = sample_sidewall_normal_rays(body)
    floor = measure_floor_thickness(body)
    body_box = _shape_bbox(body)
    native_curves = _native_curve_inventory(body)
    side_candidates = [edge for edge in native_curves if edge["bbox_mm"]["zlen_mm"] >= spec.body_height_mm - 1.0]
    side_meridian = max(side_candidates, key=lambda item: item["bbox_mm"]["zlen_mm"]) if side_candidates else None

    # The legacy handle is regenerated only to run the explicitly bounded fuse
    # diagnostic; it is not fused into or delivered with the smooth body.
    _, handle_only, _ = build_components(spec)
    handle_diag = diagnose_handle_fusion(body, handle_only)
    cut_diag = volumetric_section_diagnostics(body)
    files = sorted(path for path in (ROOT / "geometry").iterdir() if path.is_file())
    report: dict[str, object] = {
        "experiment_id": "vf.c2-meridian-native-inward-shell-spike/1.0.0",
        "stage": "candidate_default_wall4_initial_native_3d_shell",
        "status": "FAIL_NATIVE_HALFSECTION_BOOLEAN",
        "production_generator_changed": False,
        "candidate_decision": "NOT_PROMOTED; main agent review required",
        "construction": {
            "method": "legacy outer profile control points → one native interpolating C2 B-spline meridian → OCC revolve → remove top cap → native inward shell(-4 mm, kind='arc')",
            "cadquery_version": cq.__version__,
            "spec": spec.__dict__,
            "source_profile_control_points_mm": scaled_outer_profile(spec),
            "source_meridian_native_curve": source_meridian,
            "source_meridian_wire_edge_count": len(meridian_sketch.val().Edges()),
            "canonical_STEP_native_BSpline_edges": native_curves,
            "height_spanning_STEP_meridian_edge": side_meridian,
            "STEP_sha256": sha256_file(STEP_PATH),
        },
        "canonical_STEP_body": {
            "valid": bool(body.isValid()),
            "solid_count": len(body.Solids()),
            "shell_count": len(body.Shells()),
            "volume_mm3": float(body.Volume()),
            "bbox_mm": body_box,
            "actual_height_mm": body_box["zlen_mm"],
            "actual_width_mm": max(body_box["xlen_mm"], body_box["ylen_mm"]),
            "nominal_height_mm": spec.body_height_mm,
            "nominal_width_mm": spec.body_width_mm,
            "height_delta_mm": body_box["zlen_mm"] - spec.body_height_mm,
            "width_delta_mm": max(body_box["xlen_mm"], body_box["ylen_mm"]) - spec.body_width_mm,
        },
        "wall": {
            "declared_mm": spec.wall_mm,
            "normal_ray_sampling": wall,
            "floor_thickness": floor,
            "scope": "finite canonical STEP sidewall samples and planar floor separation; not a global minimum-wall proof",
        },
        "native_section": {
            "volumetric_halfspace_boolean": cut_diag,
            "section_wire": wire_metrics,
        },
        "mesh": {
            "absolute_chord_target_mm": MESH_TARGET_MM,
            "angular_tolerance_rad": MESH_ANGULAR_RAD,
            "topology": topology,
            "mesh_to_canonical_STEP": mesh_cad,
            "absolute_sampling_acceptance_mm": 0.10,
            "scope": "finite edge-midpoint and triangle-centroid samples; not a global Hausdorff proof",
        },
        "handle_fusion_diagnostic": handle_diag,
        "semantics": {
            "status": "UNKNOWN_EXPECTED",
            "reason": "production face semantics currently recognizes analytic cylinder/cone prototype faces; the delivered BSpline/offset surface is not to be silently assigned a region",
            "production_semantics_changed": False,
        },
        "artifacts": {
            "body_step": "geometry/smooth_body.step",
            "surface_npz": "geometry/surface.npz",
            "lineage_npz": "geometry/mesh_lineage.npz",
            "axial_section_wire_npz": "geometry/axial_section.npz",
            "files_sha256": {path.relative_to(ROOT).as_posix(): sha256_file(path) for path in files},
        },
        "rendering": {
            "renderer": "Blender 5.2.2 EEVEE",
            "whole_porcelain_png": "renders/whole_porcelain.png",
            "native_section_wire_png": "renders/native_section_wire.png",
            "native_section_wire_png_scope": "unfilled linework from the ten canonical STEP section edges; the OCC planar fill face was invalid",
            "mesh_boolean_cut_visualization": {
                "status": "FAILED_EMPTY",
                "vertices": 0,
                "faces": 0,
                "non_manifold_edges": 0,
                "source": "Blender Boolean modifier on the canonical STEP tessellation; render intentionally skipped after empty result",
            },
        },
        "checks": {
            "canonical_body_valid_one_solid_one_shell": bool(body.isValid() and len(body.Solids()) == 1 and len(body.Shells()) == 1),
            "delivered_mesh_watertight_positive": bool(topology["watertight"] and topology["signed_volume_mm3"] > 0),
            "source_meridian_c2": bool(source_meridian["is_C2_at_all_internal_knots"]),
            "step_meridian_c2": bool(side_meridian is not None and side_meridian["is_C2_at_all_internal_knots"]),
            "mesh_deviation_sampled_under_0_10mm": bool(mesh_cad["unknown_sample_count"] == 0 and mesh_cad["max_sampled_deviation_mm"] is not None and float(mesh_cad["max_sampled_deviation_mm"]) <= 0.10),
            "wall_rays_all_known": bool(wall["candidate_outer_side_samples"] > 0 and wall["unknown_count"] == 0),
            "floor_face_distance_within_0_05mm": bool(floor.get("status") == "MEASURED_FROM_CANONICAL_STEP_PLANAR_FACES" and abs(float(floor["distance_mm"]) - spec.wall_mm) <= 0.05),
            "native_volumetric_halfsection_valid_and_nonempty": bool(any(item["solid_count"] == 1 and item["is_valid"] and item["volume_mm3"] > 0 for item in (cut_diag["positive_y_halfspace_intersection"], cut_diag["negative_y_removed_by_cut"], cut_diag["negative_x_halfspace_intersection"]))),
            "native_section_wire_closed": bool(wire_metrics["wire_count"] == 1 and wire_metrics["wires"][0]["closed"] and wire_metrics["wires"][0]["valid"]),
            "native_section_fill_face_valid": bool((wire_metrics.get("planar_fill_face") or {}).get("valid", False)),
        },
        "limitations": [
            "This candidate is not promoted because native volumetric half-section boolean checks returned empty/invalid results despite a valid one-solid canonical body.",
            "The exact section intersection is saved as closed wire linework only; OCC failed to form a valid planar fill face from that wire.",
            "A valid body label cannot substitute for the failed half-section topology evidence.",
            "No handle is included; root/handle geometry remains PENDING and no root fillet or stress claim is made.",
            "Native shell and sampled rays do not prove a global wall minimum or offset self-intersection absence.",
            "No historical type/style authenticity, material calibration, impact, or fracture validation is claimed.",
        ],
    }
    report["status"] = "FAIL_NATIVE_HALFSECTION_BOOLEAN"
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT_PATH), "status": report["status"], "checks": report["checks"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
