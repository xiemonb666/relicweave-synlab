from __future__ import annotations

import json
import math
import traceback
from pathlib import Path
from typing import Any

import cadquery as cq
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
from OCP.GeomAbs import GeomAbs_BSplineCurve, GeomAbs_JoinType
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
    export_step,
    mesh_shape,
    mesh_topology_metrics,
    sampled_mesh_to_cad_metrics,
)
from vesselforge.schema import sha256_file


ROOT = Path(__file__).resolve().parent
GEOMETRY = ROOT / "physical_outline_geometry"
REPORT_PATH = ROOT / "candidate2_physical_profile_report.json"
WALL_MM = 4.0
CURVATURE_MARGIN_MM = 1.0
OUTER_FLOOR_RADIUS_MM = 12.5

# One constrained open-cup design. The lower and upper degree-5 Bezier spans
# meet with matching first and second native derivatives. At the base the
# first three poles lie on the flat floor; the lower transition is scaled to
# an 8 mm quarter-turn, giving sampled curvature radii above wall + 1 mm.
# The upper span is monotone in z and returns gently to the vertical open lip.
LOWER_POLES_RZ = [
    (12.5, 0.0),
    (12.5 + 8.0 / 3.0, 0.0),
    (12.5 + 16.0 / 3.0, 0.0),
    (20.5, 8.0 / 3.0),
    (20.5, 16.0 / 3.0),
    (20.5, 8.0),
]
UPPER_POLES_RZ = [
    (20.5, 8.0),
    (20.5, 8.0 + 8.0 / 3.0),
    (20.5, 8.0 + 16.0 / 3.0),
    (18.0, 51.0),
    (18.0, 53.5),
    (18.0, 56.0),
]


def save_report(report: dict[str, Any]) -> None:
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def as_vec(values: tuple[float, float]) -> cq.Vector:
    radius, height = values
    return cq.Vector(float(radius), 0.0, float(height))


def bezier_as_bspline(poles_rz: list[tuple[float, float]]) -> cq.Edge:
    bezier = cq.Edge.makeBezier([as_vec(point) for point in poles_rz])
    native_bezier = BRepAdaptor_Curve(bezier.wrapped).Bezier()
    native_bspline = GeomConvert.CurveToBSplineCurve_s(native_bezier)
    edge = cq.Edge(BRepBuilderAPI_MakeEdge(native_bspline).Edge())
    if not edge.isValid():
        raise ValueError("native converted Bezier B-spline edge is invalid")
    return edge


def derivative(edge: cq.Edge, parameter: float, order: int) -> np.ndarray:
    curve = BRepAdaptor_Curve(edge.wrapped)
    point, first, second = gp_Pnt(), gp_Vec(), gp_Vec()
    if order == 1:
        curve.D1(float(parameter), point, first)
        value = first
    else:
        curve.D2(float(parameter), point, first, second)
        value = second
    result = np.asarray([value.X(), value.Y(), value.Z()], dtype=np.float64)
    if not np.all(np.isfinite(result)):
        raise ValueError("native profile derivative is non-finite")
    return result


def native_edge_report(edge: cq.Edge) -> dict[str, Any]:
    adaptor = BRepAdaptor_Curve(edge.wrapped)
    if adaptor.GetType() != GeomAbs_BSplineCurve:
        raise ValueError("delivered profile edge is not a native B-spline")
    curve = adaptor.BSpline()
    return {
        "valid": bool(edge.isValid()),
        "edge_type": "BSPLINE",
        "degree": int(curve.Degree()),
        "continuity": str(curve.Continuity()),
        "is_C2": bool(curve.IsCN(2)),
        "first_parameter": float(curve.FirstParameter()),
        "last_parameter": float(curve.LastParameter()),
        "knots": [float(curve.Knot(i)) for i in range(1, curve.NbKnots() + 1)],
        "multiplicities": [int(curve.Multiplicity(i)) for i in range(1, curve.NbKnots() + 1)],
        "start_xyz_mm": list(edge.startPoint().toTuple()),
        "end_xyz_mm": list(edge.endPoint().toTuple()),
    }


def derivative_join_report(left: cq.Edge, right: cq.Edge) -> dict[str, Any]:
    left_curve = BRepAdaptor_Curve(left.wrapped)
    right_curve = BRepAdaptor_Curve(right.wrapped)
    left_end = float(left_curve.LastParameter())
    right_start = float(right_curve.FirstParameter())
    left_d1 = derivative(left, left_end, 1)
    right_d1 = derivative(right, right_start, 1)
    left_d2 = derivative(left, left_end, 2)
    right_d2 = derivative(right, right_start, 2)
    d1_relative = float(np.linalg.norm(left_d1 - right_d1) / max(np.linalg.norm(left_d1), np.linalg.norm(right_d1), 1e-12))
    d2_absolute = float(np.linalg.norm(left_d2 - right_d2))
    return {
        "left_end_d1": left_d1.tolist(),
        "right_start_d1": right_d1.tolist(),
        "d1_relative_jump": d1_relative,
        "left_end_d2": left_d2.tolist(),
        "right_start_d2": right_d2.tolist(),
        "d2_absolute_jump_mm_per_parameter2": d2_absolute,
        "C2_join": bool(d1_relative <= 1e-8 and d2_absolute <= 1e-7),
    }


def curvature_report(edges: list[cq.Edge], sample_count_per_edge: int = 20001) -> dict[str, Any]:
    samples = []
    per_edge = []
    for edge_index, edge in enumerate(edges):
        curve = BRepAdaptor_Curve(edge.wrapped)
        edge_samples = []
        for parameter in np.linspace(curve.FirstParameter(), curve.LastParameter(), sample_count_per_edge):
            point, first, second = gp_Pnt(), gp_Vec(), gp_Vec()
            curve.D2(float(parameter), point, first, second)
            d1 = np.asarray([first.X(), first.Y(), first.Z()], dtype=np.float64)
            d2 = np.asarray([second.X(), second.Y(), second.Z()], dtype=np.float64)
            speed = float(np.linalg.norm(d1))
            cross = float(np.linalg.norm(np.cross(d1, d2)))
            kappa = cross / speed**3 if speed > 1e-15 else math.inf
            radius = 1.0 / kappa if kappa > 1e-15 and math.isfinite(kappa) else math.inf
            record = {
                "edge_index": edge_index,
                "parameter": float(parameter),
                "radius_mm": float(radius),
                "point_xyz_mm": [float(point.X()), float(point.Y()), float(point.Z())],
            }
            edge_samples.append(record)
        minimum = min(edge_samples, key=lambda item: item["radius_mm"])
        per_edge.append(
            {
                "edge_index": edge_index,
                "sample_count": len(edge_samples),
                "minimum_sampled_radius_mm": minimum["radius_mm"],
                "minimum_sample": minimum,
                "samples_below_wall_plus_margin": sum(
                    item["radius_mm"] < WALL_MM + CURVATURE_MARGIN_MM for item in edge_samples
                ),
            }
        )
        samples.extend(edge_samples)
    minimum = min(samples, key=lambda item: item["radius_mm"])
    return {
        "method": "native BRepAdaptor_Curve.D2 curvature on each delivered profile B-spline; deterministic uniform parameter sampling",
        "sample_count_per_edge": sample_count_per_edge,
        "total_sample_count": len(samples),
        "minimum_sampled_radius_mm": minimum["radius_mm"],
        "minimum_sample": minimum,
        "wall_mm": WALL_MM,
        "required_margin_mm": CURVATURE_MARGIN_MM,
        "threshold_mm": WALL_MM + CURVATURE_MARGIN_MM,
        "samples_below_threshold": sum(item["radius_mm"] < WALL_MM + CURVATURE_MARGIN_MM for item in samples),
        "per_edge": per_edge,
        "scope": "sampled curvature evidence, not a formal continuous-domain minimum proof",
    }


def shape_summary(shape: cq.Shape) -> dict[str, Any]:
    bbox = _shape_bbox(shape) if not shape.isNull() else None
    solids = shape.Solids()
    return {
        "valid": bool(shape.isValid()),
        "null": bool(shape.isNull()),
        "shape_type": str(shape.ShapeType()),
        "solid_count": len(solids),
        "shell_count": len(shape.Shells()),
        "volume_mm3": float(shape.Volume()),
        "bbox_mm": bbox,
        "solid_validity": [bool(solid.isValid()) for solid in solids],
        "solid_volumes_mm3": [float(solid.Volume()) for solid in solids],
        "solid_shell_counts": [len(solid.Shells()) for solid in solids],
    }


def fail(report: dict[str, Any], status: str, message: str) -> int:
    report["status"] = status
    report.setdefault("failures", []).append(message)
    save_report(report)
    print(json.dumps({"status": status, "message": message, "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 2


def main() -> int:
    GEOMETRY.mkdir(parents=True, exist_ok=True)
    spec = VesselSpec(
        body_width_mm=41.0,
        body_height_mm=56.0,
        wall_mm=WALL_MM,
        tessellation_linear_mm=0.05,
        tessellation_angular_rad=MESH_ANGULAR_RAD,
    )
    report: dict[str, Any] = {
        "experiment_id": "vf.c2-meridian-constrained-planar-offset-revolve/1.0.0",
        "model_version": "physical-open-cup-profile-v1",
        "stage": "second_and_final_construction_representation_constrained_outline",
        "status": "RUNNING",
        "candidate_decision": "NOT_PROMOTED; parent visual and technical review required",
        "production_generator_changed": False,
        "production_semantics_changed": False,
        "construction": {
            "method": "two exact native degree-5 Bezier spans converted to B-splines and joined as one C2 meridian wire; OCC native planar normal offset +4 mm; close material meridian; revolve 360 degrees",
            "cadquery_version": cq.__version__,
            "spec": spec.__dict__,
            "outer_floor_radius_mm": OUTER_FLOOR_RADIUS_MM,
            "control_poles_rz_mm": {"lower_transition": LOWER_POLES_RZ, "upper_body": UPPER_POLES_RZ},
            "design_reason": "The legacy interpolating profile had a 0.0725 mm minimum sampled curvature radius and 664/10001 points below 4 mm, making a 4 mm normal offset singular. This new monotone-z silhouette is designed with a broad lower turn and exact C2 span join.",
            "not_an_exact_legacy_style_clone": True,
        },
        "limitations": [
            "This is a body-only open-cup family spike; no handle, fused root, or root fillet is included.",
            "A sampled curvature minimum above wall plus margin is finite evidence, not a proof over every curve parameter.",
            "Sampled normal-ray wall distances do not prove global minimum thickness.",
            "Production B-spline face semantics remain UNKNOWN; production code was not changed.",
            "No global wall-thickness or production style equivalence claim is made.",
        ],
    }
    save_report(report)
    try:
        edges = [bezier_as_bspline(LOWER_POLES_RZ), bezier_as_bspline(UPPER_POLES_RZ)]
        side_wire = cq.Wire.assembleEdges(edges)
        if not side_wire.isValid() or side_wire.IsClosed() or len(side_wire.Edges()) != 2:
            return fail(report, "FAIL_SOURCE_WIRE", "native C2 side meridian did not form one valid open two-edge wire")

        native_edges = [native_edge_report(edge) for edge in edges]
        joins = derivative_join_report(edges[0], edges[1])
        curvature = curvature_report(edges)
        # The lower tangent is the flat-bottom direction; the upper tangent is
        # vertical at the lip. Both have zero second derivative at their joins.
        bottom_d1 = derivative(edges[0], BRepAdaptor_Curve(edges[0].wrapped).FirstParameter(), 1)
        bottom_d2 = derivative(edges[0], BRepAdaptor_Curve(edges[0].wrapped).FirstParameter(), 2)
        lip_d1 = derivative(edges[-1], BRepAdaptor_Curve(edges[-1].wrapped).LastParameter(), 1)
        lip_d2 = derivative(edges[-1], BRepAdaptor_Curve(edges[-1].wrapped).LastParameter(), 2)
        endpoint_constraints = {
            "bottom_tangent_is_flat_and_forward": bool(abs(bottom_d1[2]) <= 1e-8 and bottom_d1[0] > 0),
            "bottom_second_derivative_norm": float(np.linalg.norm(bottom_d2)),
            "lip_tangent_is_vertical_and_upward": bool(abs(lip_d1[0]) <= 1e-8 and lip_d1[2] > 0),
            "lip_second_derivative_norm": float(np.linalg.norm(lip_d2)),
            "endpoint_C2_to_adjacent_flat_lines": bool(np.linalg.norm(bottom_d2) <= 1e-7 and np.linalg.norm(lip_d2) <= 1e-7),
        }
        report["source_meridian"] = {
            "native_edges": native_edges,
            "internal_join": joins,
            "endpoint_constraints": endpoint_constraints,
            "sampled_curvature": curvature,
            "wire_valid": bool(side_wire.isValid()),
            "wire_edge_count": len(side_wire.Edges()),
        }
        if not all(item["is_C2"] for item in native_edges) or not joins["C2_join"]:
            return fail(report, "FAIL_SOURCE_C2", "native profile spans or their internal join failed the derivative C2 checks")
        if not endpoint_constraints["endpoint_C2_to_adjacent_flat_lines"]:
            return fail(report, "FAIL_ENDPOINT_C2", "floor/lip tangent or second-derivative endpoint constraint failed")
        if curvature["samples_below_threshold"]:
            return fail(report, "FAIL_CURVATURE_PREFLIGHT", "sampled source curvature radius fell below wall plus margin")

        offset_builder = BRepOffsetAPI_MakeOffset()
        offset_builder.Init(GeomAbs_JoinType.GeomAbs_Arc, True)
        offset_builder.AddWire(side_wire.wrapped)
        offset_builder.Perform(float(WALL_MM))
        offset_builder.Build()
        report["offset"] = {
            "api": "OCP BRepOffsetAPI_MakeOffset",
            "distance_mm": WALL_MM,
            "side_wire_valid": bool(side_wire.isValid()),
            "side_wire_closed": bool(side_wire.IsClosed()),
            "is_done": bool(offset_builder.IsDone()),
        }
        raw_offset = offset_builder.Shape()
        report["offset"]["is_null"] = bool(raw_offset.IsNull())
        if raw_offset.IsNull() or not offset_builder.IsDone():
            return fail(report, "FAIL_NATIVE_OFFSET", "native OCC inward planar offset returned a null or incomplete shape")
        offset_shape = cq.Shape.cast(raw_offset)
        offset_wires = offset_shape.Wires()
        if not offset_wires and offset_shape.Edges():
            offset_wires = cq.Wire.combine(offset_shape.Edges(), tol=1e-6)
        offset_summary = [
            {
                "valid": bool(wire.isValid()),
                "closed": bool(wire.IsClosed()),
                "edge_count": len(wire.Edges()),
                "bbox_mm": _shape_bbox(wire),
                "vertices_xyz_mm": [list(vertex.Center().toTuple()) for vertex in wire.Vertices()],
            }
            for wire in offset_wires
        ]
        report["offset"].update(
            {
                "shape_valid": bool(offset_shape.isValid()),
                "shape_type": str(offset_shape.ShapeType()),
                "wire_count": len(offset_wires),
                "wires": offset_summary,
                "join_style": "GeomAbs_Arc",
            }
        )
        if len(offset_wires) != 1 or not offset_wires[0].isValid() or offset_wires[0].IsClosed():
            return fail(report, "FAIL_OFFSET_TOPOLOGY", "native inward offset did not produce one valid open wire without branch trimming")

        offset_wire = offset_wires[0]
        endpoints = [vertex.Center().toTuple() for vertex in offset_wire.Vertices()]
        if len(endpoints) < 2:
            return fail(report, "FAIL_OFFSET_ENDPOINTS", "native inward offset has fewer than two endpoints")
        bottom_inner = min(endpoints, key=lambda point: float(point[2]))
        top_inner = max(endpoints, key=lambda point: float(point[2]))
        expected_bottom = np.asarray([OUTER_FLOOR_RADIUS_MM, 0.0, WALL_MM])
        expected_top = np.asarray([18.0 - WALL_MM, 0.0, 56.0])
        bottom_error = float(np.linalg.norm(np.asarray(bottom_inner) - expected_bottom))
        top_error = float(np.linalg.norm(np.asarray(top_inner) - expected_top))
        report["offset_trim_endpoints"] = {
            "bottom_xyz_mm": list(bottom_inner),
            "top_xyz_mm": list(top_inner),
            "expected_bottom_xyz_mm": expected_bottom.tolist(),
            "expected_top_xyz_mm": expected_top.tolist(),
            "bottom_error_mm": bottom_error,
            "top_error_mm": top_error,
            "acceptance_mm": 0.10,
            "trim_policy": "only natural native offset endpoints are accepted; no offset branch is discarded",
        }
        if max(bottom_error, top_error) > 0.10:
            return fail(report, "FAIL_OFFSET_ENDPOINTS", "native offset endpoints do not meet the designed horizontal floor and vertical lip")

        outer_bottom = edges[0].startPoint()
        outer_lip = edges[-1].endPoint()
        profile_edges = [
            cq.Edge.makeLine(cq.Vector(0.0, 0.0, 0.0), outer_bottom),
            *edges,
            cq.Edge.makeLine(outer_lip, cq.Vector(18.0 - WALL_MM, 0.0, 56.0)),
            *[edge.reverse() for edge in reversed(offset_wire.Edges())],
            cq.Edge.makeLine(cq.Vector(OUTER_FLOOR_RADIUS_MM, 0.0, WALL_MM), cq.Vector(0.0, 0.0, WALL_MM)),
            cq.Edge.makeLine(cq.Vector(0.0, 0.0, WALL_MM), cq.Vector(0.0, 0.0, 0.0)),
        ]
        profile_wires = cq.Wire.combine(profile_edges, tol=1e-6)
        report["closed_material_profile"] = {
            "wire_count": len(profile_wires),
            "wires": [
                {"valid": bool(wire.isValid()), "closed": bool(wire.IsClosed()), "edge_count": len(wire.Edges()), "length_mm": float(wire.Length())}
                for wire in profile_wires
            ],
        }
        if len(profile_wires) != 1 or not profile_wires[0].isValid() or not profile_wires[0].IsClosed():
            return fail(report, "FAIL_MATERIAL_WIRE", "offset, bottom, rim, and outer meridian did not form one valid closed material wire")
        profile_face = cq.Face.makeFromWires(profile_wires[0])
        report["closed_material_profile"].update({"face_valid": bool(profile_face.isValid()), "face_area_mm2": float(profile_face.Area())})
        if not profile_face.isValid() or not math.isfinite(profile_face.Area()) or profile_face.Area() <= 0:
            return fail(report, "FAIL_MATERIAL_FACE", "closed material meridian did not make one valid positive-area face")

        constructed = (
            cq.Workplane("XZ")
            .newObject([profile_wires[0]])
            .toPending()
            .revolve(360.0, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), combine=False)
            .val()
        )
        report["constructed_body"] = shape_summary(constructed)
        if not constructed.isValid() or len(constructed.Solids()) != 1 or len(constructed.Shells()) != 1:
            return fail(report, "FAIL_REVOLVED_BODY", "revolving the native closed material section did not produce one valid solid/shell")

        body_step = GEOMETRY / "smooth_body.step"
        export_step(constructed, str(body_step))
        canonical = cq.importers.importStep(str(body_step)).val()
        canonical_bbox = _shape_bbox(canonical) if not canonical.isNull() else None
        report["canonical_STEP"] = {
            "sha256": sha256_file(body_step),
            "body": shape_summary(canonical),
            "bbox_mm": canonical_bbox,
            "source_revolve_body_volume_mm3": float(constructed.Volume()),
            "source_revolve_solid_count": len(constructed.Solids()),
            "source_revolve_shell_count": len(constructed.Shells()),
        }
        if canonical.isNull() or not canonical.isValid() or len(canonical.Solids()) != 1 or len(canonical.Shells()) != 1:
            return fail(report, "FAIL_CANONICAL_STEP", "canonical STEP reimport is not one valid solid/shell")
        vertices, faces, lineage = mesh_shape(canonical, spec)
        topology = mesh_topology_metrics(vertices, faces)
        mesh_cad = sampled_mesh_to_cad_metrics(canonical, vertices, faces, lineage)
        np.savez_compressed(GEOMETRY / "surface.npz", vertices_mm=vertices.astype(np.float64), faces=faces.astype(np.int32))
        np.savez_compressed(GEOMETRY / "mesh_lineage.npz", face_source_brep_index=lineage.astype(np.int32))

        cut_box = cq.Solid.makeBox(120.0, 70.0, 100.0, cq.Vector(-40.0, 0.0, -20.0))
        native_cut = canonical.intersect(cut_box).clean()
        cut_solids = native_cut.Solids()
        cut_volume = float(sum(solid.Volume() for solid in cut_solids))
        volume_ratio = cut_volume / max(float(canonical.Volume()), 1e-12)
        cut_acceptance = bool(
            not native_cut.isNull()
            and native_cut.isValid()
            and len(cut_solids) > 0
            and all(solid.isValid() and solid.Volume() > 0 for solid in cut_solids)
            and abs(volume_ratio - 0.5) <= 0.01
        )
        report["native_half_section"] = {
            "method": "canonical STEP body intersected with a true y>=0 half-space box; multiple solids are permitted only if each is valid and their total retained volume is half within 1%",
            "result": shape_summary(native_cut),
            "valid_solid_count": sum(bool(solid.isValid()) for solid in cut_solids),
            "solid_volumes_mm3": [float(solid.Volume()) for solid in cut_solids],
            "total_cut_solid_volume_mm3": cut_volume,
            "full_body_volume_mm3": float(canonical.Volume()),
            "fraction_of_full_volume": volume_ratio,
            "acceptance": cut_acceptance,
        }
        if not cut_acceptance:
            return fail(report, "FAIL_NATIVE_HALF_SECTION", "native axial half-space cut is empty, invalid, or not volume-preserving")

        section_step = GEOMETRY / "axial_half_section.step"
        export_step(native_cut, str(section_step))
        canonical_cut = cq.importers.importStep(str(section_step)).val()
        canonical_cut_solids = canonical_cut.Solids()
        if (
            canonical_cut.isNull()
            or not canonical_cut.isValid()
            or not canonical_cut_solids
            or not all(solid.isValid() for solid in canonical_cut_solids)
        ):
            return fail(report, "FAIL_SECTION_STEP", "native cutaway STEP reimport is not valid")
        cut_vertices, cut_faces, cut_lineage = mesh_shape(canonical_cut, spec)
        cut_topology = mesh_topology_metrics(cut_vertices, cut_faces)
        cut_mesh_cad = sampled_mesh_to_cad_metrics(canonical_cut, cut_vertices, cut_faces, cut_lineage)
        np.savez_compressed(GEOMETRY / "axial_section.npz", vertices_mm=cut_vertices.astype(np.float64), faces=cut_faces.astype(np.int32))
        np.savez_compressed(GEOMETRY / "axial_section_lineage.npz", face_source_brep_index=cut_lineage.astype(np.int32))

        wall = sample_sidewall_normal_rays(canonical)
        floor = measure_floor_thickness(canonical)
        bbox = _shape_bbox(canonical)
        native_curves = _native_curve_inventory(canonical)
        report["canonical_STEP"] = {
            "sha256": sha256_file(body_step),
            "body": shape_summary(canonical),
            "bbox_mm": bbox,
            "actual_height_mm": bbox["zlen_mm"],
            "actual_width_mm": max(bbox["xlen_mm"], bbox["ylen_mm"]),
            "nominal_height_mm": spec.body_height_mm,
            "nominal_width_mm": spec.body_width_mm,
            "radial_overshoot_mm": max(bbox["xlen_mm"], bbox["ylen_mm"]) / 2.0 - spec.body_width_mm / 2.0,
            "native_bspline_inventory": native_curves,
        }
        report["wall"] = {
            "declared_mm": WALL_MM,
            "sidewall_normal_rays": wall,
            "floor_thickness": floor,
        }
        report["mesh"] = {
            "absolute_chord_target_mm": spec.tessellation_linear_mm,
            "angular_tolerance_rad": spec.tessellation_angular_rad,
            "topology": topology,
            "mesh_to_canonical_STEP": mesh_cad,
            "sampling_acceptance_max_mm": 0.10,
        }
        report["axial_section_mesh"] = {
            "topology": cut_topology,
            "mesh_to_canonical_section_STEP": cut_mesh_cad,
            "step_sha256": sha256_file(section_step),
        }
        report["checks"] = {
            "native_side_meridian_is_C2": all(item["is_C2"] for item in native_edges) and joins["C2_join"],
            "floor_and_lip_endpoint_C2": endpoint_constraints["endpoint_C2_to_adjacent_flat_lines"],
            "sampled_curvature_radius_at_least_wall_plus_margin": curvature["samples_below_threshold"] == 0,
            "native_offset_is_simple_valid_open_wire": len(offset_wires) == 1 and offset_wires[0].isValid() and not offset_wires[0].IsClosed(),
            "offset_ends_match_floor_and_lip_within_0_10mm": max(bottom_error, top_error) <= 0.10,
            "closed_material_profile_valid_face": bool(profile_face.isValid()),
            "canonical_step_one_valid_solid_shell": bool(canonical.isValid() and len(canonical.Solids()) == 1 and len(canonical.Shells()) == 1),
            "actual_height_within_0_10mm": abs(bbox["zlen_mm"] - spec.body_height_mm) <= 0.10,
            "actual_width_within_0_10mm": abs(max(bbox["xlen_mm"], bbox["ylen_mm"]) - spec.body_width_mm) <= 0.10,
            "canonical_mesh_watertight_positive": bool(topology["watertight"] and topology["signed_volume_mm3"] > 0),
            "mesh_to_cad_sampling_under_0_10mm": bool(mesh_cad["unknown_sample_count"] == 0 and mesh_cad["max_sampled_deviation_mm"] is not None and mesh_cad["max_sampled_deviation_mm"] <= 0.10),
            "wall_sampling_no_unknowns": bool(wall["unknown_count"] == 0 and wall["candidate_outer_side_samples"] > 0),
            "sampled_wall_within_0_10mm_of_requested": bool(wall["sampled_wall_min_mm"] is not None and wall["sampled_wall_max_mm"] is not None and abs(wall["sampled_wall_min_mm"] - WALL_MM) <= 0.10 and abs(wall["sampled_wall_max_mm"] - WALL_MM) <= 0.10),
            "floor_thickness_within_0_05mm": bool(floor.get("status") == "MEASURED_FROM_CANONICAL_STEP_PLANAR_FACES" and abs(floor["distance_mm"] - WALL_MM) <= 0.05),
            "native_half_section_volume_preserving": cut_acceptance,
            "axial_section_mesh_watertight_positive": bool(cut_topology["watertight"] and cut_topology["signed_volume_mm3"] > 0),
            "axial_section_mesh_to_cad_sampling_under_0_10mm": bool(cut_mesh_cad["unknown_sample_count"] == 0 and cut_mesh_cad["max_sampled_deviation_mm"] is not None and cut_mesh_cad["max_sampled_deviation_mm"] <= 0.10),
        }
        report["artifacts"] = {
            "body_step": "physical_outline_geometry/smooth_body.step",
            "body_mesh_npz": "physical_outline_geometry/surface.npz",
            "body_mesh_lineage_npz": "physical_outline_geometry/mesh_lineage.npz",
            "axial_half_section_step": "physical_outline_geometry/axial_half_section.step",
            "axial_half_section_mesh_npz": "physical_outline_geometry/axial_section.npz",
            "axial_half_section_lineage_npz": "physical_outline_geometry/axial_section_lineage.npz",
            "files_sha256": {
                path.relative_to(ROOT).as_posix(): sha256_file(path)
                for path in sorted(GEOMETRY.iterdir())
                if path.is_file()
            },
        }
        report["status"] = "PASS_CANDIDATE_ONLY" if all(report["checks"].values()) else "FAIL_OR_UNKNOWN_CANDIDATE"
        save_report(report)
        print(json.dumps({"status": report["status"], "checks": report["checks"], "report": str(REPORT_PATH)}, ensure_ascii=False))
        return 0 if report["status"] == "PASS_CANDIDATE_ONLY" else 2
    except Exception as exc:
        report["status"] = "FAIL_EXCEPTION"
        report["exception"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        save_report(report)
        print(json.dumps({"status": report["status"], "exception": report["exception"], "report": str(REPORT_PATH)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
