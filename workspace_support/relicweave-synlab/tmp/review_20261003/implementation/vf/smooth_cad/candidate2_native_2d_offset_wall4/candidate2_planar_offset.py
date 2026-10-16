from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import cadquery as cq
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
from OCP.GeomAbs import GeomAbs_BSplineCurve, GeomAbs_JoinType
from OCP.gp import gp_Pnt, gp_Vec

from experiments.smooth_cad_spike import (
    MESH_ANGULAR_RAD,
    _native_curve_inventory,
    _shape_bbox,
    make_c2_meridian_wire,
    measure_floor_thickness,
    sample_sidewall_normal_rays,
)
from vesselforge.geometry import (
    VesselSpec,
    export_step,
    mesh_shape,
    mesh_topology_metrics,
    sampled_mesh_to_cad_metrics,
    scaled_outer_profile,
)
from vesselforge.schema import sha256_file

ROOT = Path(__file__).resolve().parent
GEOMETRY = ROOT / "geometry"
GEOMETRY.mkdir(parents=True, exist_ok=True)
REPORT_PATH = ROOT / "candidate2_planar_offset_report.json"


def save_report(report: dict[str, object]) -> None:
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def shape_summary(shape: cq.Shape) -> dict[str, object]:
    try:
        bbox = _shape_bbox(shape) if not shape.isNull() else None
    except Exception:
        bbox = None
    return {
        "valid": bool(shape.isValid()),
        "null": bool(shape.isNull()),
        "solid_count": len(shape.Solids()),
        "shell_count": len(shape.Shells()),
        "volume_mm3": float(shape.Volume()),
        "bbox_mm": bbox,
        "solid_validity": [bool(s.isValid()) for s in shape.Solids()],
        "solid_volumes_mm3": [float(s.Volume()) for s in shape.Solids()],
        "solid_shell_counts": [len(s.Shells()) for s in shape.Solids()],
    }


def source_curvature(edge: cq.Edge, samples: int = 10001) -> dict[str, object]:
    curve = BRepAdaptor_Curve(edge.wrapped)
    values = []
    for parameter in np.linspace(curve.FirstParameter(), curve.LastParameter(), samples):
        point, first, second = gp_Pnt(), gp_Vec(), gp_Vec()
        curve.D2(float(parameter), point, first, second)
        tangent = np.asarray([first.X(), first.Y(), first.Z()], dtype=np.float64)
        second_derivative = np.asarray([second.X(), second.Y(), second.Z()], dtype=np.float64)
        speed = float(np.linalg.norm(tangent))
        curvature = float(np.linalg.norm(np.cross(tangent, second_derivative)) / speed**3) if speed > 1e-15 else math.inf
        radius = 1.0 / curvature if curvature > 1e-15 and math.isfinite(curvature) else math.inf
        values.append((radius, float(parameter), float(point.X()), float(point.Z()), curvature, speed))
    minimum = min(values, key=lambda item: item[0])
    below = [item for item in values if item[0] < 4.0]
    return {
        "method": "native BRepAdaptor_Curve.D2 curvature on the source STEP-plane meridian",
        "sample_count": samples,
        "minimum_radius_mm": minimum[0],
        "minimum_at": {"parameter": minimum[1], "radius_mm": minimum[2], "z_mm": minimum[3], "curvature_per_mm": minimum[4], "speed_mm_per_parameter": minimum[5]},
        "samples_with_radius_below_wall": len(below),
        "wall_mm": 4.0,
        "interpretation": "normal offset is singular/branching where local radius is below the offset distance; OCC trimming must yield an explicitly valid profile, otherwise reject",
    }


def main() -> int:
    spec = replace(
        VesselSpec(),
        body_width_mm=41.0,
        body_height_mm=56.0,
        wall_mm=4.0,
        tessellation_linear_mm=0.05,
        tessellation_angular_rad=MESH_ANGULAR_RAD,
    )
    report: dict[str, object] = {
        "experiment_id": "vf.c2-meridian-planar-normal-offset-revolve/1.0.0",
        "stage": "second_and_final_native_construction_representation",
        "status": "FAIL_OFFSET_NOT_BUILT",
        "production_generator_changed": False,
        "candidate_decision": "NOT_PROMOTED; main agent review required",
        "construction": {
            "method": "source C2 interpolating B-spline meridian → native OCC BRepOffsetAPI_MakeOffset on the open planar side wire with IsOpenResult=True, distance=-wall → trim at the base floor/rim → assemble closed material profile → revolve",
            "cadquery_version": cq.__version__,
            "spec": spec.__dict__,
            "source_profile_control_points_mm": scaled_outer_profile(spec),
        },
        "limitations": [
            "This is the one authorized alternate construction representation; no retries or wall counterfactuals are attempted.",
            "No cavity is filled by a solid subtraction and no same-height radial subtraction is used.",
            "Production geometry and face semantics remain unchanged.",
        ],
    }

    sketch, source_meridian = make_c2_meridian_wire(spec)
    spline_edges = []
    for edge in sketch.val().Edges():
        adaptor = BRepAdaptor_Curve(edge.wrapped)
        if adaptor.GetType() == GeomAbs_BSplineCurve and edge.BoundingBox().zlen > spec.body_height_mm - 1.0:
            spline_edges.append(edge)
    if len(spline_edges) != 1:
        report["status"] = "FAIL_SOURCE_MERIDIAN_EDGE_COUNT"
        report["source_meridian"] = source_meridian
        report["source_edge_count"] = len(spline_edges)
        save_report(report)
        print(json.dumps({"status": report["status"], "report": str(REPORT_PATH)}, indent=2))
        return 2
    outer_edge = spline_edges[0]
    curvature = source_curvature(outer_edge)
    report["construction"]["source_meridian_native_curve"] = source_meridian
    report["construction"]["source_meridian_curvature_preflight"] = curvature

    source_wire = cq.Wire.assembleEdges([outer_edge])
    offset_builder = BRepOffsetAPI_MakeOffset()
    offset_state: dict[str, object] = {
        "api": "OCP BRepOffsetAPI_MakeOffset",
        "join": "GeomAbs_Arc",
        "is_open_result": True,
        "distance_mm": -float(spec.wall_mm),
        "source_wire_valid": bool(source_wire.isValid()),
        "source_wire_closed": bool(source_wire.IsClosed()),
        "source_wire_edge_count": len(source_wire.Edges()),
    }
    try:
        offset_builder.Init(GeomAbs_JoinType.GeomAbs_Arc, True)
        offset_builder.AddWire(source_wire.wrapped)
        offset_builder.Perform(-float(spec.wall_mm))
        offset_builder.Build()
        offset_state["is_done"] = bool(offset_builder.IsDone())
        raw_offset = offset_builder.Shape()
        offset_state["is_null"] = bool(raw_offset.IsNull())
        if raw_offset.IsNull():
            raise ValueError("OCC returned a null open-wire offset shape")
        offset_shape = cq.Shape.cast(raw_offset)
    except Exception as exc:
        offset_state.update({"error_type": type(exc).__name__, "error": str(exc)})
        report["offset"] = offset_state
        report["status"] = "FAIL_OFFSET_NOT_BUILT"
        report["checks"] = {
            "native_source_meridian_c2": bool(source_meridian["is_C2_at_all_internal_knots"]),
            "source_curvature_radius_ge_wall_everywhere": bool(curvature["samples_with_radius_below_wall"] == 0),
            "native_2d_offset_shape_built": False,
            "closed_profile_valid": False,
            "revolved_canonical_step_valid": False,
        }
        report["limitations"].append("The mature native open-wire offset call did not return a usable shape; no second candidate solid was built.")
        save_report(report)
        print(json.dumps({"status": report["status"], "offset": offset_state, "curvature": curvature, "report": str(REPORT_PATH)}, indent=2))
        return 2

    wires = offset_shape.Wires()
    if not wires and offset_shape.Edges():
        wires = cq.Wire.combine(offset_shape.Edges(), tol=1e-5)
    offset_state.update(
        {
            "shape_valid": bool(offset_shape.isValid()),
            "shape_type": str(offset_shape.ShapeType()),
            "wire_count": len(wires),
            "edge_count": len(offset_shape.Edges()),
            "wires": [
                {
                    "valid": bool(wire.isValid()),
                    "closed": bool(wire.IsClosed()),
                    "edge_count": len(wire.Edges()),
                    "length_mm": float(wire.Length()),
                    "bbox_mm": _shape_bbox(wire),
                    "vertices_xyz_mm": [list(vertex.Center().toTuple()) for vertex in wire.Vertices()],
                }
                for wire in wires
            ],
        }
    )
    report["offset"] = offset_state
    if len(wires) != 1 or not wires[0].isValid() or wires[0].IsClosed():
        report["status"] = "FAIL_OFFSET_TOPOLOGY"
        report["checks"] = {
            "native_source_meridian_c2": bool(source_meridian["is_C2_at_all_internal_knots"]),
            "source_curvature_radius_ge_wall_everywhere": bool(curvature["samples_with_radius_below_wall"] == 0),
            "native_2d_offset_shape_built": True,
            "one_valid_open_offset_wire": False,
            "closed_profile_valid": False,
            "revolved_canonical_step_valid": False,
        }
        save_report(report)
        print(json.dumps({"status": report["status"], "offset": offset_state, "curvature": curvature, "report": str(REPORT_PATH)}, indent=2))
        return 2

    offset_wire = wires[0]
    vertices = [vertex.Center().toTuple() for vertex in offset_wire.Vertices()]
    if len(vertices) < 2:
        report["status"] = "FAIL_OFFSET_ENDPOINTS"
        report["checks"] = {"native_2d_offset_shape_built": True, "one_valid_open_offset_wire": True, "two_trim_endpoints_available": False}
        save_report(report)
        print(json.dumps({"status": report["status"], "offset": offset_state, "report": str(REPORT_PATH)}, indent=2))
        return 2
    bottom_point = min(vertices, key=lambda point: float(point[2]))
    top_point = max(vertices, key=lambda point: float(point[2]))
    expected_bottom = np.asarray([14.0, 0.0, spec.wall_mm])
    expected_top = np.asarray([spec.body_width_mm / 2.0 - spec.wall_mm, 0.0, spec.body_height_mm])
    bottom_error = float(np.linalg.norm(np.asarray(bottom_point) - expected_bottom))
    top_error = float(np.linalg.norm(np.asarray(top_point) - expected_top))
    report["offset_trim_endpoints"] = {
        "bottom_xyz_mm": list(bottom_point),
        "top_xyz_mm": list(top_point),
        "expected_bottom_xyz_mm": expected_bottom.tolist(),
        "expected_top_xyz_mm": expected_top.tolist(),
        "bottom_error_mm": bottom_error,
        "top_error_mm": top_error,
        "trim_method": "native offset endpoints checked against the horizontal inner floor z=4 and vertical lip offset r=14; no branch is deleted manually",
    }
    if max(bottom_error, top_error) > 0.10:
        report["status"] = "FAIL_OFFSET_TRIM_ENDS"
        report["checks"] = {"native_2d_offset_shape_built": True, "one_valid_open_offset_wire": True, "offset_endpoints_match_floor_and_lip_within_0_10mm": False}
        save_report(report)
        print(json.dumps({"status": report["status"], "trim_endpoints": report["offset_trim_endpoints"], "report": str(REPORT_PATH)}, indent=2))
        return 2

    outer_start = outer_edge.startPoint()
    outer_end = outer_edge.endPoint()
    inner_floor_axis = cq.Vector(0.0, 0.0, spec.wall_mm)
    base_axis = cq.Vector(0.0, 0.0, 0.0)
    outer_bottom = cq.Vector(*outer_start.toTuple())
    outer_lip = cq.Vector(*outer_end.toTuple())
    offset_bottom = cq.Vector(*bottom_point)
    offset_top = cq.Vector(*top_point)
    profile_edges = [
        cq.Edge.makeLine(base_axis, outer_bottom),
        outer_edge,
        cq.Edge.makeLine(outer_lip, offset_top),
        *[edge.reverse() for edge in reversed(offset_wire.Edges())],
        cq.Edge.makeLine(offset_bottom, inner_floor_axis),
        cq.Edge.makeLine(inner_floor_axis, base_axis),
    ]
    profile_wires = cq.Wire.combine(profile_edges, tol=1e-5)
    profile_summary = {
        "wire_count": len(profile_wires),
        "wires": [
            {"valid": bool(wire.isValid()), "closed": bool(wire.IsClosed()), "edge_count": len(wire.Edges()), "length_mm": float(wire.Length())}
            for wire in profile_wires
        ],
    }
    report["closed_material_profile"] = profile_summary
    if len(profile_wires) != 1 or not profile_wires[0].IsClosed() or not profile_wires[0].isValid():
        report["status"] = "FAIL_CLOSED_PROFILE_WIRE"
        report["checks"] = {"native_2d_offset_shape_built": True, "offset_endpoints_match_floor_and_lip_within_0_10mm": True, "closed_profile_one_valid_wire": False}
        save_report(report)
        print(json.dumps({"status": report["status"], "closed_profile": profile_summary, "report": str(REPORT_PATH)}, indent=2))
        return 2
    try:
        profile_face = cq.Face.makeFromWires(profile_wires[0])
        profile_summary["face_valid"] = bool(profile_face.isValid())
        profile_summary["face_area_mm2"] = float(profile_face.Area())
    except Exception as exc:
        profile_summary.update({"face_valid": False, "face_error_type": type(exc).__name__, "face_error": str(exc)})
        report["status"] = "FAIL_CLOSED_PROFILE_FACE"
        report["checks"] = {"native_2d_offset_shape_built": True, "closed_profile_one_valid_wire": True, "closed_profile_face_valid": False}
        save_report(report)
        print(json.dumps({"status": report["status"], "closed_profile": profile_summary, "report": str(REPORT_PATH)}, indent=2))
        return 2
    if not profile_face.isValid():
        report["status"] = "FAIL_CLOSED_PROFILE_FACE"
        report["checks"] = {"native_2d_offset_shape_built": True, "closed_profile_one_valid_wire": True, "closed_profile_face_valid": False}
        save_report(report)
        print(json.dumps({"status": report["status"], "closed_profile": profile_summary, "report": str(REPORT_PATH)}, indent=2))
        return 2

    profile_wire = profile_wires[0]
    body = cq.Workplane("XZ").newObject([profile_wire]).toPending().revolve(
        360.0, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), combine=False
    ).val()
    report["revolved_body"] = shape_summary(body)
    if not body.isValid() or len(body.Solids()) != 1 or len(body.Shells()) != 1:
        report["status"] = "FAIL_REVOLVED_BODY_TOPOLOGY"
        save_report(report)
        print(json.dumps({"status": report["status"], "body": report["revolved_body"], "report": str(REPORT_PATH)}, indent=2))
        return 2

    body_step = GEOMETRY / "smooth_body.step"
    export_step(body, str(body_step))
    canonical = cq.importers.importStep(str(body_step)).val()
    vertices, faces, lineage = mesh_shape(canonical, spec)
    topology = mesh_topology_metrics(vertices, faces)
    mesh_cad = sampled_mesh_to_cad_metrics(canonical, vertices, faces, lineage)
    np.savez_compressed(GEOMETRY / "surface.npz", vertices_mm=vertices.astype(np.float64), faces=faces.astype(np.int32))
    np.savez_compressed(GEOMETRY / "mesh_lineage.npz", face_source_brep_index=lineage.astype(np.int32))
    wall = sample_sidewall_normal_rays(canonical)
    floor = measure_floor_thickness(canonical)
    bbox = _shape_bbox(canonical)
    curves = _native_curve_inventory(canonical)
    section_box = cq.Solid.makeBox(120.0, 70.0, 100.0, cq.Vector(-40.0, 0.0, -20.0))
    half_section = canonical.intersect(section_box).clean()
    cut_metrics = shape_summary(half_section)
    section_solids = half_section.Solids()
    half_volume = float(sum(solid.Volume() for solid in section_solids))
    volume_ratio = half_volume / max(float(canonical.Volume()), 1e-12)
    report["canonical_STEP"] = {
        "sha256": sha256_file(body_step),
        "body": shape_summary(canonical),
        "bbox_mm": bbox,
        "actual_height_mm": bbox["zlen_mm"],
        "actual_width_mm": max(bbox["xlen_mm"], bbox["ylen_mm"]),
        "nominal_height_mm": spec.body_height_mm,
        "nominal_width_mm": spec.body_width_mm,
        "radial_overshoot_mm": max(bbox["xlen_mm"], bbox["ylen_mm"]) / 2.0 - spec.body_width_mm / 2.0,
        "native_curves": curves,
    }
    report["wall"] = {"declared_mm": spec.wall_mm, "sidewall_normal_rays": wall, "floor_thickness": floor}
    report["mesh"] = {
        "absolute_chord_target_mm": spec.tessellation_linear_mm,
        "angular_tolerance_rad": spec.tessellation_angular_rad,
        "topology": topology,
        "mesh_to_canonical_STEP": mesh_cad,
        "sampling_acceptance_max_mm": 0.10,
    }
    report["native_half_section"] = {
        "method": "canonical STEP solid intersected with the historical axial half-space box; accept any number of solids only if each is valid and total volume is half the axisymmetric body within 1%",
        "result": cut_metrics,
        "valid_solid_count": sum(bool(solid.isValid()) for solid in section_solids),
        "total_cut_solid_volume_mm3": half_volume,
        "fraction_of_full_volume": volume_ratio,
        "acceptance": bool(section_solids and all(solid.isValid() for solid in section_solids) and abs(volume_ratio - 0.5) <= 0.01),
    }
    report["artifacts"] = {
        "body_step": "geometry/smooth_body.step",
        "mesh_npz": "geometry/surface.npz",
        "lineage_npz": "geometry/mesh_lineage.npz",
        "files_sha256": {path.relative_to(ROOT).as_posix(): sha256_file(path) for path in sorted(GEOMETRY.iterdir()) if path.is_file()},
    }
    report["checks"] = {
        "native_source_meridian_c2": bool(source_meridian["is_C2_at_all_internal_knots"]),
        "source_curvature_radius_ge_wall_everywhere": bool(curvature["samples_with_radius_below_wall"] == 0),
        "offset_api_produced_simple_valid_profile": True,
        "canonical_step_one_valid_solid_shell": bool(canonical.isValid() and len(canonical.Solids()) == 1 and len(canonical.Shells()) == 1),
        "actual_height_within_0_10mm": abs(bbox["zlen_mm"] - spec.body_height_mm) <= 0.10,
        "actual_width_within_0_10mm": abs(max(bbox["xlen_mm"], bbox["ylen_mm"]) - spec.body_width_mm) <= 0.10,
        "canonical_mesh_watertight_positive": bool(topology["watertight"] and topology["signed_volume_mm3"] > 0),
        "mesh_to_cad_sampling_under_0_10mm": bool(mesh_cad["unknown_sample_count"] == 0 and mesh_cad["max_sampled_deviation_mm"] is not None and mesh_cad["max_sampled_deviation_mm"] <= 0.10),
        "wall_sampling_no_unknowns": bool(wall["unknown_count"] == 0 and wall["candidate_outer_side_samples"] > 0),
        "sampled_wall_within_0_10mm_of_requested": bool(wall["sampled_wall_min_mm"] is not None and wall["sampled_wall_max_mm"] is not None and abs(wall["sampled_wall_min_mm"] - spec.wall_mm) <= 0.10 and abs(wall["sampled_wall_max_mm"] - spec.wall_mm) <= 0.10),
        "floor_thickness_within_0_05mm": bool(floor.get("status") == "MEASURED_FROM_CANONICAL_STEP_PLANAR_FACES" and abs(floor["distance_mm"] - spec.wall_mm) <= 0.05),
        "native_half_section_valid_volume_preserving": report["native_half_section"]["acceptance"],
    }
    report["status"] = "PASS_CANDIDATE_ONLY" if all(report["checks"].values()) else "FAIL_OR_UNKNOWN_CANDIDATE"
    report["candidate_decision"] = "NOT_PROMOTED; main agent review required"
    report["limitations"].extend(
        [
            "Curvature and wall ray sampling are finite evidence, not a proof of global minimum wall or offset self-intersection freedom.",
            "No handle/root is included; root remains PENDING and no fillet/stress claim is made.",
            "Semantics for the new native surfaces remain UNKNOWN in production and were not changed.",
        ]
    )
    save_report(report)
    print(json.dumps({"status": report["status"], "checks": report["checks"], "report": str(REPORT_PATH)}, indent=2))
    return 0 if all(report["checks"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
