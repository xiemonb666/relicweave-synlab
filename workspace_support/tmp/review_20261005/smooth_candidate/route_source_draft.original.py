"""Fixed-case smooth meridian CAD candidate builder (source draft, unexecuted).

This script is intentionally scoped to the two checked-in fixed cases in
fixed_cases.json. It is not a general family generator. No CAD imports or
geometry work happen at module import time. Run only after main-agent review.

All coordinates are millimetres in the (radius, z) meridian plane. The inner
side is a direct radial translation of the outer control net; the declared
radial setting is not a normal wall thickness. The report preserves global
minimum normal thickness as UNKNOWN because finite all-hit rays are samples.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


PointRZ = tuple[float, float]
ControlNet = tuple[PointRZ, PointRZ, PointRZ, PointRZ, PointRZ, PointRZ]
CASE_FILE = Path(__file__).with_name("fixed_cases.json")
POSITION_TOL_MM = 1e-8
D1_TOL_MM_PER_PARAMETER = 1e-8
D2_TOL_MM_PER_PARAMETER2 = 1e-8
WIRE_TOL_MM = 1e-7
CURVE_SAMPLES_PER_SPAN = 41
WALL_SAMPLE_GRID = (16, 20)  # azimuth x meridian per trimmed revolution face


@dataclass(frozen=True)
class HermiteStation:
    point_rz_mm: PointRZ
    d1_rz_per_parameter: PointRZ
    d2_rz_per_parameter2: PointRZ


@dataclass(frozen=True)
class CurveSpan:
    controls_rz_mm: ControlNet
    parameter_width: float
    role: str


@dataclass(frozen=True)
class NativeCandidate:
    family: str
    body: Any
    wire: Any
    section_face: Any
    report: dict[str, Any]
    curve_spans: tuple[CurveSpan, ...]


def _add(a: PointRZ, b: PointRZ) -> PointRZ:
    return (a[0] + b[0], a[1] + b[1])


def _sub(a: PointRZ, b: PointRZ) -> PointRZ:
    return (a[0] - b[0], a[1] - b[1])


def _scale(k: float, value: PointRZ) -> PointRZ:
    return (k * value[0], k * value[1])


def _finite_pair(name: str, values: Sequence[float]) -> PointRZ:
    if len(values) != 2:
        raise ValueError(f"{name} must contain exactly two coordinates")
    point = (float(values[0]), float(values[1]))
    if not all(math.isfinite(value) for value in point):
        raise ValueError(f"{name} must contain finite coordinates")
    return point


def load_fixed_cases() -> dict[str, Any]:
    """Load the two immutable local fixture definitions beside this source."""
    payload = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    if payload.get("schema") != "vesselforge.smooth_surface_route.fixed_cases/0.2.0":
        raise ValueError("fixed-case schema does not match this source draft")
    if payload.get("units", {}).get("length") != "mm":
        raise ValueError("fixed cases must use millimetres")
    if set(payload.get("families", {})) != {"beaker", "bowl"}:
        raise ValueError("this draft accepts exactly the fixed beaker and bowl cases")
    return payload


def quintic_hermite_controls(
    start: HermiteStation,
    end: HermiteStation,
    *,
    parameter_width: float,
) -> ControlNet:
    """Return the six exact degree-5 Bezier poles for endpoint 0/1/2-jets."""
    h = float(parameter_width)
    if not math.isfinite(h) or h <= 0.0:
        raise ValueError("parameter_width must be finite and positive")
    p0, p1 = start.point_rz_mm, end.point_rz_mm
    d0 = _scale(h, start.d1_rz_per_parameter)
    d1 = _scale(h, end.d1_rz_per_parameter)
    a0 = _scale(h * h, start.d2_rz_per_parameter2)
    a1 = _scale(h * h, end.d2_rz_per_parameter2)
    return (
        p0,
        _add(p0, _scale(1.0 / 5.0, d0)),
        _add(_add(p0, _scale(2.0 / 5.0, d0)), _scale(1.0 / 20.0, a0)),
        _add(_add(p1, _scale(-2.0 / 5.0, d1)), _scale(1.0 / 20.0, a1)),
        _add(p1, _scale(-1.0 / 5.0, d1)),
        p1,
    )


def _line_controls(start: PointRZ, end: PointRZ) -> ControlNet:
    """Degree-5 exact line control net, with zero second derivative."""
    return tuple(
        (
            start[0] + (end[0] - start[0]) * index / 5.0,
            start[1] + (end[1] - start[1]) * index / 5.0,
        )
        for index in range(6)
    )  # type: ignore[return-value]


def _stations_from_case(case: dict[str, Any], shared: dict[str, Any]) -> tuple[HermiteStation, ...]:
    default_d2 = _finite_pair("station_second_derivatives_rz", shared["station_second_derivatives_rz"])
    return tuple(
        HermiteStation(
            point_rz_mm=_finite_pair("point_rz_mm", row["point_rz_mm"]),
            d1_rz_per_parameter=_finite_pair("d1_rz_per_parameter", row["d1_rz_per_parameter"]),
            d2_rz_per_parameter2=_finite_pair("d2_rz_per_parameter2", row.get("d2_rz_per_parameter2", default_d2)),
        )
        for row in case["outer_side_stations"]
    )


def _span_chain(stations: Sequence[HermiteStation], role: str) -> tuple[CurveSpan, ...]:
    if len(stations) < 2:
        raise ValueError(f"{role} needs at least two stations")
    return tuple(
        CurveSpan(
            controls_rz_mm=quintic_hermite_controls(stations[index], stations[index + 1], parameter_width=1.0),
            parameter_width=1.0,
            role=f"{role}:{index}",
        )
        for index in range(len(stations) - 1)
    )


def _translated_radially(span: CurveSpan, gap_mm: float, role: str) -> CurveSpan:
    controls = tuple((r - gap_mm, z) for r, z in span.controls_rz_mm)
    if any(r <= 0.0 for r, _ in controls):
        raise ValueError(f"{role} radial translation reaches or crosses the axis")
    return CurveSpan(controls, span.parameter_width, role)  # type: ignore[arg-type]


def _line_span(start: PointRZ, end: PointRZ, width: float, role: str) -> CurveSpan:
    if width <= 0.0 or not math.isfinite(width):
        raise ValueError(f"{role} parameter width must be finite and positive")
    return CurveSpan(_line_controls(start, end), float(width), role)


def _station_span(start: HermiteStation, end: HermiteStation, width: float, role: str) -> CurveSpan:
    return CurveSpan(quintic_hermite_controls(start, end, parameter_width=width), width, role)


def _bezier_derivatives(controls: Sequence[PointRZ]) -> tuple[tuple[PointRZ, ...], tuple[PointRZ, ...]]:
    degree = len(controls) - 1
    first = tuple(_scale(float(degree), _sub(controls[index + 1], controls[index])) for index in range(degree))
    second = tuple(
        _scale(float(degree * (degree - 1)), _add(_sub(controls[index + 2], _scale(2.0, controls[index + 1])), controls[index]))
        for index in range(degree - 1)
    )
    return first, second


def _bezier_value(controls: Sequence[PointRZ], t: float) -> PointRZ:
    points = list(controls)
    while len(points) > 1:
        points = [_add(_scale(1.0 - t, points[i]), _scale(t, points[i + 1])) for i in range(len(points) - 1)]
    return points[0]


def _edge_jet(span: CurveSpan, at_end: bool) -> tuple[PointRZ, PointRZ, PointRZ]:
    controls = span.controls_rz_mm
    first, second = _bezier_derivatives(controls)
    if at_end:
        point, d1, d2 = controls[-1], first[-1], second[-1]
    else:
        point, d1, d2 = controls[0], first[0], second[0]
    h = span.parameter_width
    return point, _scale(1.0 / h, d1), _scale(1.0 / (h * h), d2)


def _compare_join(left: CurveSpan, right: CurveSpan, *, name: str) -> dict[str, Any]:
    lp, ld1, ld2 = _edge_jet(left, True)
    rp, rd1, rd2 = _edge_jet(right, False)
    position_error = max(abs(lp[0] - rp[0]), abs(lp[1] - rp[1]))
    d1_error = max(abs(ld1[0] - rd1[0]), abs(ld1[1] - rd1[1]))
    d2_error = max(abs(ld2[0] - rd2[0]), abs(ld2[1] - rd2[1]))
    passed = (
        position_error <= POSITION_TOL_MM
        and d1_error <= D1_TOL_MM_PER_PARAMETER
        and d2_error <= D2_TOL_MM_PER_PARAMETER2
    )
    return {
        "join": name,
        "position_error_mm": position_error,
        "d1_error_mm_per_parameter": d1_error,
        "d2_error_mm_per_parameter2": d2_error,
        "status": "PASS" if passed else "FAIL",
    }


def _monotone(values: Sequence[float], *, increasing: bool) -> bool:
    if increasing:
        return all(values[index + 1] >= values[index] - 1e-12 for index in range(len(values) - 1))
    return all(values[index + 1] <= values[index] + 1e-12 for index in range(len(values) - 1))


def _fixed_case_outline_certificate(
    case: dict[str, Any],
    outer_side: Sequence[CurveSpan],
    inner_side: Sequence[CurveSpan],
    base_bridge: CurveSpan,
    lip_bridge: CurveSpan,
    outside_floor: CurveSpan,
    inner_floor: CurveSpan,
) -> dict[str, Any]:
    """Check exact Bernstein control-polygon conditions for these two fixtures.

    This is bounded to the fixed profiles. It does not establish a proof for
    arbitrary parameter values or for global 3D minimum normal thickness.
    """
    wall = float(case["wall_radial_setting_mm"])
    height = float(case["height_mm"])
    outer_max = float(case["max_radius_mm"])
    radial_pair = all(
        abs((outer.controls_rz_mm[index][0] - inner.controls_rz_mm[index][0]) - wall) <= POSITION_TOL_MM
        and abs(outer.controls_rz_mm[index][1] - inner.controls_rz_mm[index][1]) <= POSITION_TOL_MM
        for outer, inner in zip(outer_side, inner_side)
        for index in range(6)
    )
    side_z_monotone = all(_monotone([point[1] for point in span.controls_rz_mm], increasing=True) for span in outer_side)
    side_r_monotone_per_span = all(
        _monotone([point[0] for point in span.controls_rz_mm], increasing=True)
        or _monotone([point[0] for point in span.controls_rz_mm], increasing=False)
        for span in outer_side
    )
    inner_clearance = all(point[0] > 0.0 for span in inner_side for point in span.controls_rz_mm)
    side_radius_in_bounds = all(
        -POSITION_TOL_MM <= point[0] <= outer_max + POSITION_TOL_MM
        for span in outer_side
        for point in span.controls_rz_mm
    )
    base_monotone = (
        _monotone([point[0] for point in base_bridge.controls_rz_mm], increasing=True)
        and _monotone([point[1] for point in base_bridge.controls_rz_mm], increasing=True)
    )
    lip_monotone = (
        _monotone([point[0] for point in lip_bridge.controls_rz_mm], increasing=False)
        and all(point[1] >= height - POSITION_TOL_MM for point in lip_bridge.controls_rz_mm)
    )
    floor_monotone = (
        _monotone([point[0] for point in outside_floor.controls_rz_mm], increasing=True)
        and _monotone([point[0] for point in inner_floor.controls_rz_mm], increasing=False)
    )
    stations = case["outer_side_stations"]
    station_z_increasing = all(
        float(stations[index + 1]["point_rz_mm"][1]) > float(stations[index]["point_rz_mm"][1])
        for index in range(len(stations) - 1)
    )
    checks = {
        "outer_inner_control_nets_have_exact_radial_gap": radial_pair,
        "outer_and_inner_side_z_control_polygons_are_monotone": side_z_monotone,
        "each_side_span_r_control_polygon_is_monotone": side_r_monotone_per_span,
        "inner_side_stays_strictly_off_axis": inner_clearance,
        "side_control_radii_stay_inside_authored_maximum": side_radius_in_bounds,
        "base_bridge_r_and_z_control_polygons_are_monotone": base_monotone,
        "rounded_lip_r_is_monotone_and_z_stays_above_rim": lip_monotone,
        "floor_control_polygons_are_monotone": floor_monotone,
        "side_station_z_is_strictly_increasing": station_z_increasing,
    }
    return {
        "scope": "exact fixed-case Bernstein control polygon predicates plus explicit outline ordering; no arbitrary-parameter-domain claim",
        "checks": checks,
        "status": "PASS_FIXED_CASE" if all(checks.values()) else "FAIL",
        "family_wide_global_self_intersection": "UNKNOWN",
    }


def _make_native_edge(span: CurveSpan) -> Any:
    import cadquery as cq

    points = [cq.Vector(float(r), 0.0, float(z)) for r, z in span.controls_rz_mm]
    edge = cq.Edge.makeBezier(points)
    if not edge.isValid():
        raise ValueError(f"native Bezier edge is invalid: {span.role}")
    return edge


def _curve_sample_report(spans: Sequence[CurveSpan]) -> dict[str, Any]:
    details = []
    for span in spans:
        first_net, second_net = _bezier_derivatives(span.controls_rz_mm)
        samples = []
        min_radius: float | None = None
        min_speed = math.inf
        max_abs_curvature = 0.0
        for index in range(CURVE_SAMPLES_PER_SPAN):
            t = index / (CURVE_SAMPLES_PER_SPAN - 1)
            point = _bezier_value(span.controls_rz_mm, t)
            d1_local = _bezier_value(first_net, t)
            d2_local = _bezier_value(second_net, t)
            h = span.parameter_width
            d1 = _scale(1.0 / h, d1_local)
            d2 = _scale(1.0 / (h * h), d2_local)
            speed = math.hypot(*d1)
            if not math.isfinite(speed) or speed <= 1e-10:
                raise ValueError(f"sampled curve speed is degenerate on {span.role} at t={t}")
            curvature = (d1[0] * d2[1] - d1[1] * d2[0]) / (speed**3)
            if not math.isfinite(curvature):
                raise ValueError(f"sampled curvature is non-finite on {span.role} at t={t}")
            radius = 1.0 / abs(curvature) if abs(curvature) > 1e-12 else None
            if radius is not None:
                min_radius = radius if min_radius is None else min(min_radius, radius)
            min_speed = min(min_speed, speed)
            max_abs_curvature = max(max_abs_curvature, abs(curvature))
            samples.append(
                {
                    "t": float(t),
                    "point_rz_mm": [float(point[0]), float(point[1])],
                    "curvature_per_mm": float(curvature),
                    "radius_of_curvature_mm": None if radius is None else float(radius),
                    "d1_speed_mm_per_parameter": float(speed),
                }
            )
        details.append(
            {
                "role": span.role,
                "degree": 5,
                "parameter_width": span.parameter_width,
                "sample_count": len(samples),
                "minimum_sampled_speed_mm_per_parameter": float(min_speed),
                "maximum_absolute_sampled_curvature_per_mm": float(max_abs_curvature),
                "minimum_finite_sampled_curvature_radius_mm": None if min_radius is None else float(min_radius),
                "samples": samples,
            }
        )
    return {
        "method": "exact quintic Bezier control nets; analytic first/second derivatives evaluated at uniform parameter samples",
        "samples_per_span": CURVE_SAMPLES_PER_SPAN,
        "spans": details,
        "scope": "finite curvature samples; no whole-span lower curvature bound claimed",
    }


def build_native_candidate(family: str) -> NativeCandidate:
    """Construct and validate one fixed native OCC solid; never serializes STEP."""
    import cadquery as cq

    payload = load_fixed_cases()
    shared = payload["shared_construction"]
    if family not in payload["families"]:
        raise ValueError("family must be one of the fixed beaker or bowl fixtures")
    case = payload["families"][family]
    wall = float(case["wall_radial_setting_mm"])
    height = float(case["height_mm"])
    base = float(case["base_thickness_setting_mm"])
    outer_root_r = float(shared["outer_side_root_radius_mm"])
    underside_r = float(shared["outer_underside_radius_mm"])
    root_d1 = _finite_pair("shared_side_root_derivative", shared["shared_side_root_derivative_rz_per_parameter"])
    base_d2_start = _finite_pair("base_bridge_second_derivatives_start", shared["base_bridge_second_derivatives_rz"][0])
    base_d2_end = _finite_pair("base_bridge_second_derivatives_end", shared["base_bridge_second_derivatives_rz"][1])
    lip_d2_start = _finite_pair("lip_bridge_second_derivatives_start", shared["lip_bridge_second_derivatives_rz"][0])
    lip_d2_end = _finite_pair("lip_bridge_second_derivatives_end", shared["lip_bridge_second_derivatives_rz"][1])
    if abs(float(case["outer_side_stations"][0]["point_rz_mm"][0]) - outer_root_r) > POSITION_TOL_MM:
        raise ValueError("first side station must meet the configured outer base blend")
    if abs(float(case["outer_side_stations"][-1]["point_rz_mm"][0]) - float(case["outer_mouth_radius_mm"])) > POSITION_TOL_MM:
        raise ValueError("last outer side station must equal the declared outside mouth radius")
    if abs(float(case["outer_mouth_radius_mm"]) - (float(case["mouth_diameter_mm"]) / 2.0 + wall)) > POSITION_TOL_MM:
        raise ValueError("outer mouth radius must equal clear mouth radius plus radial setting")

    stations = _stations_from_case(case, shared)
    outer_side = _span_chain(stations, "outer_side")
    inner_side = tuple(_translated_radially(span, wall, f"inner_side:{index}") for index, span in enumerate(outer_side))

    # The line's width is selected so its shared-parameter endpoint derivative
    # equals the side-root derivative. The base blend is a direct quintic span.
    outside_floor_width = float(shared["outside_underside_parameter_width"])
    outside_floor = _line_span((0.0, 0.0), (underside_r, 0.0), outside_floor_width, "outer_underside")
    base_start = HermiteStation(
        (underside_r, 0.0), root_d1, base_d2_start
    )
    base_end = HermiteStation(
        (outer_root_r, base), root_d1, base_d2_end
    )
    base_bridge = _station_span(base_start, base_end, 1.0, "outer_base_blend")

    lip_d1 = float(shared["lip_tangent_scale_mm_per_parameter"])
    outer_mouth = float(case["outer_mouth_radius_mm"])
    inner_mouth = float(case["inner_mouth_radius_mm"])
    if abs((outer_mouth - inner_mouth) - wall) > POSITION_TOL_MM:
        raise ValueError("inner and outer mouth radii must retain the radial setting")
    lip_start = HermiteStation((outer_mouth, height), (0.0, lip_d1), lip_d2_start)
    lip_end = HermiteStation((inner_mouth, height), (0.0, -lip_d1), lip_d2_end)
    lip_bridge = _station_span(lip_start, lip_end, 1.0, "rounded_lip_bridge")

    inner_root_r = outer_root_r - wall
    if inner_root_r <= 0.0:
        raise ValueError("inner wall reaches the axis at the base")
    inner_floor_width = inner_root_r / root_d1[0]
    inner_floor = _line_span((inner_root_r, base), (0.0, base), inner_floor_width, "inner_floor")
    axis_closure = _line_span(
        (0.0, base),
        (0.0, 0.0),
        base / max(root_d1[0], 1e-12),
        "axis_closure_expected_singularity",
    )

    inner_side_reversed = tuple(
        CurveSpan(tuple(reversed(span.controls_rz_mm)), span.parameter_width, f"{span.role}:reversed")
        for span in reversed(inner_side)
    )
    curve_spans = (
        outside_floor,
        base_bridge,
        *outer_side,
        lip_bridge,
        *inner_side_reversed,
        inner_floor,
        axis_closure,
    )
    c2_joins = []
    for left, right in zip(curve_spans, curve_spans[1:]):
        if left.role == "inner_floor" or right.role == "axis_closure" or left.role == "axis_closure":
            continue
        c2_joins.append(_compare_join(left, right, name=f"{left.role} -> {right.role}"))
    if any(join["status"] != "PASS" for join in c2_joins):
        raise ValueError("one or more non-axis meridian joins failed the C2 data check")

    outline_certificate = _fixed_case_outline_certificate(
        case, outer_side, inner_side, base_bridge, lip_bridge, outside_floor, inner_floor
    )
    if outline_certificate["status"] != "PASS_FIXED_CASE":
        raise ValueError("fixed-case Bernstein control polygon preflight failed")

    outside_floor_edge = _make_native_edge(outside_floor)
    base_bridge_edge = _make_native_edge(base_bridge)
    outer_side_edges = tuple(_make_native_edge(span) for span in outer_side)
    lip_edge = _make_native_edge(lip_bridge)
    inner_side_edges = tuple(_make_native_edge(span) for span in inner_side_reversed)
    inner_floor_edge = _make_native_edge(inner_floor)
    axis_edge = _make_native_edge(axis_closure)
    ordered_edges = [
        outside_floor_edge,
        base_bridge_edge,
        *outer_side_edges,
        lip_edge,
        *inner_side_edges,
        inner_floor_edge,
        axis_edge,
    ]
    wires = cq.Wire.combine(ordered_edges, tol=WIRE_TOL_MM)
    if len(wires) != 1 or not wires[0].isValid() or not wires[0].IsClosed():
        raise ValueError("explicit material outline did not combine into one valid closed wire")
    section_face = cq.Face.makeFromWires(wires[0])
    if not section_face.isValid() or not math.isfinite(float(section_face.Area())) or section_face.Area() <= 0.0:
        raise ValueError("closed meridian did not make a valid positive-area material face")

    body = (
        cq.Workplane("XZ")
        .newObject([wires[0]])
        .toPending()
        .revolve(360.0, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), combine=False)
        .val()
    )
    solids, shells = body.Solids(), body.Shells()
    shell_closed = [bool(shell.Closed()) for shell in shells]
    if (
        not body.isValid()
        or len(solids) != 1
        or len(shells) != 1
        or not all(shell_closed)
        or not solids[0].isValid()
        or not math.isfinite(float(body.Volume()))
        or body.Volume() <= 0.0
    ):
        raise ValueError("revolved material section did not make exactly one valid positive-volume solid and shell")

    source_curve_samples = _curve_sample_report(curve_spans[:-1])
    report = {
        "schema": "vesselforge.smooth_surface_route.candidate/0.2.0",
        "experiment_id": "vf.direct-paired-quintic-section-revolve/0.2.0",
        "family": family,
        "units": {"length": "mm"},
        "candidate_scope": "ANALYTIC_CANDIDATE_ONLY",
        "status": "NATIVE_CAD_FIXED_CASE_CANDIDATE",
        "candidate_decision": "NOT_PROMOTED; fixed analytic geometry only; local ray and serialization evidence pending",
        "real_vessel_match": "NOT_VALIDATED",
        "material_or_physical_qualification": "NOT_VALIDATED",
        "construction": {
            "method": "explicit outer/inner degree-5 Bezier side spans plus explicit floor, base blend, rounded lip, and axis closure; one closed meridian face revolved 360 degrees",
            "side_wall_setting_semantics": "radial control-net separation at equal z parameter; not normal thickness",
            "radial_wall_setting_mm": wall,
            "base_thickness_setting_mm": base,
            "outer_mouth_radius_mm": outer_mouth,
            "inner_mouth_radius_mm": inner_mouth,
            "native_offset_api_used": False,
            "family_parameters": case,
        },
        "meridian_continuity": {
            "method": "exact degree-5 Bezier endpoint jets, compared after shared parameter-width scaling",
            "axis_join_policy": "axis closure endpoints are expected revolution singularities; excluded from C2 wall/material-surface joins",
            "position_tolerance_mm": POSITION_TOL_MM,
            "d1_tolerance_mm_per_parameter": D1_TOL_MM_PER_PARAMETER,
            "d2_tolerance_mm_per_parameter2": D2_TOL_MM_PER_PARAMETER2,
            "joins": c2_joins,
            "all_non_axis_joins_C2": all(join["status"] == "PASS" for join in c2_joins),
            "curve_samples": source_curve_samples,
        },
        "fixed_case_preflight": outline_certificate,
        "native_shape": {
            "valid": bool(body.isValid()),
            "solid_count": len(solids),
            "shell_count": len(shells),
            "shell_closed_flags": shell_closed,
            "open_boundary_shell_count": sum(not value for value in shell_closed),
            "solid_validity": [bool(solid.isValid()) for solid in solids],
            "volume_mm3": float(body.Volume()),
            "section_wire_valid": bool(wires[0].isValid()),
            "section_wire_closed": bool(wires[0].IsClosed()),
            "section_face_valid": bool(section_face.isValid()),
            "section_face_area_mm2": float(section_face.Area()),
            "boundary_check": "all native shells report Closed(); separate edge-face incidence table is not emitted",
        },
        "global_claims": {
            "family_wide_global_self_intersection": "UNKNOWN",
            "global_minimum_normal_wall_thickness": "UNKNOWN",
            "scope": "fixed beaker/bowl control nets only; no arbitrary parameter-domain proof",
        },
    }
    return NativeCandidate(family, body, wires[0], section_face, report, curve_spans)


def _solid_state(shape: Any, point: Any, tolerance: float = 1e-7) -> str:
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier

    classifier = BRepClass3d_SolidClassifier()
    classifier.Load(shape.wrapped)
    classifier.Perform(point, tolerance)
    return str(classifier.State())


def _cluster_hits(distances: Sequence[float], tolerance: float = 1e-5) -> list[float]:
    grouped: list[list[float]] = []
    for distance in sorted(float(value) for value in distances if math.isfinite(float(value)) and float(value) >= 0.0):
        if not grouped or distance - grouped[-1][-1] > tolerance:
            grouped.append([distance])
        else:
            grouped[-1].append(distance)
    return [sum(group) / len(group) for group in grouped]


def measure_all_hit_normal_walls(shape: Any, *, max_distance_mm: float, height_mm: float) -> dict[str, Any]:
    """Cast true outward-normal rays and classify every material interval."""
    import numpy as np
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepGProp import BRepGProp_Face
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_SurfaceOfRevolution
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Pnt2d, gp_Vec

    azimuth_steps, meridian_steps = WALL_SAMPLE_GRID
    intersector = IntCurvesFace_ShapeIntersector()
    intersector.Load(shape.wrapped, 1e-7)
    records: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    candidate_count = 0
    face_coverage: list[dict[str, Any]] = []
    for face_index, face in enumerate(shape.Faces()):
        surface = BRepAdaptor_Surface(face.wrapped, True)
        if surface.GetType() != GeomAbs_SurfaceOfRevolution:
            continue
        u_min, u_max, v_min, v_max = BRepTools.UVBounds_s(face.wrapped)
        normal_eval = BRepGProp_Face(face.wrapped)
        face_candidates = 0
        face_measured = 0
        for iu in range(azimuth_steps):
            u = u_min + (u_max - u_min) * (iu + 0.5) / azimuth_steps
            for iv in range(meridian_steps):
                v = v_min + (v_max - v_min) * (iv + 0.5) / meridian_steps
                trim = BRepClass_FaceClassifier(face.wrapped, gp_Pnt2d(u, v), 1e-7)
                if trim.State() not in (TopAbs_IN, TopAbs_ON):
                    continue
                point = surface.Value(u, v)
                normal = gp_Vec()
                normal_eval.Normal(u, v, point, normal)
                magnitude = float(normal.Magnitude())
                if not math.isfinite(magnitude) or magnitude < 1e-10:
                    unknown.append({"face_index": face_index, "u": u, "v": v, "reason": "degenerate_normal"})
                    continue
                normal.Normalize()
                xyz = np.asarray([point.X(), point.Y(), point.Z()], dtype=np.float64)
                nxyz = np.asarray([normal.X(), normal.Y(), normal.Z()], dtype=np.float64)
                # The rounded mouth bridge sits at or above the nominal rim.
                # Keep this ray set on the side wall and base transition only.
                if float(xyz[2]) >= float(height_mm) - 1e-8:
                    continue
                radius = float(math.hypot(xyz[0], xyz[1]))
                if radius < 1e-6:
                    continue
                radial = np.asarray([xyz[0] / radius, xyz[1] / radius, 0.0])
                radial_dot = float(np.dot(nxyz, radial))
                if radial_dot <= 0.25:
                    continue
                candidate_count += 1
                face_candidates += 1
                epsilon = 1e-4
                outside = xyz + epsilon * nxyz
                inward = -nxyz
                plus_state = _solid_state(shape, gp_Pnt(*outside.tolist()))
                surface_state = _solid_state(shape, gp_Pnt(*xyz.tolist()))
                if plus_state != "TopAbs_State.TopAbs_OUT" or surface_state == "TopAbs_State.TopAbs_OUT":
                    unknown.append(
                        {
                            "face_index": face_index,
                            "u": float(u),
                            "v": float(v),
                            "point_xyz_mm": xyz.tolist(),
                            "normal_out": nxyz.tolist(),
                            "reason": "outward_normal_or_surface_classification_unconfirmed",
                            "outside_state": plus_state,
                            "surface_state": surface_state,
                        }
                    )
                    continue
                line = gp_Lin(gp_Pnt(*outside.tolist()), gp_Dir(*inward.tolist()))
                intersector.Perform(line, 0.0, float(max_distance_mm))
                if not intersector.IsDone():
                    unknown.append({"face_index": face_index, "u": u, "v": v, "reason": "all_hit_query_not_done"})
                    continue
                raw_hits = [
                    float(intersector.WParameter(hit))
                    for hit in range(1, intersector.NbPnt() + 1)
                    if float(intersector.WParameter(hit)) > 1e-7
                ]
                hits = _cluster_hits(raw_hits)
                if len(hits) < 2:
                    unknown.append(
                        {"face_index": face_index, "u": u, "v": v, "reason": "fewer_than_two_distinct_boundary_hits", "hits_mm": hits}
                    )
                    continue
                bounds = [0.0, *hits, float(max_distance_mm)]
                interval_states = []
                state_unknown = False
                for lower, upper in zip(bounds, bounds[1:]):
                    if upper - lower <= 1e-7:
                        interval_states.append("DEGENERATE")
                        state_unknown = True
                        continue
                    midpoint = outside + (0.5 * (lower + upper)) * inward
                    state = _solid_state(shape, gp_Pnt(*midpoint.tolist()))
                    if state.endswith("TopAbs_IN"):
                        interval_states.append("IN_MATERIAL")
                    elif state.endswith("TopAbs_OUT"):
                        interval_states.append("OUTSIDE_OR_CAVITY")
                    else:
                        interval_states.append("UNKNOWN")
                        state_unknown = True
                # The ray starts outside. Its first material interval must be
                # bounded by the first two distinct all-hit intersections.
                if state_unknown or len(interval_states) < 3 or interval_states[0] != "OUTSIDE_OR_CAVITY" or interval_states[1] != "IN_MATERIAL" or interval_states[2] != "OUTSIDE_OR_CAVITY":
                    unknown.append(
                        {
                            "face_index": face_index,
                            "u": float(u),
                            "v": float(v),
                            "reason": "all_hit_intervals_do_not_show_outer_entry_material_inner_exit",
                            "all_hit_distances_mm": hits,
                            "interval_states": interval_states,
                        }
                    )
                    continue
                thickness = hits[1] - hits[0]
                if not math.isfinite(thickness) or thickness <= 0.0:
                    unknown.append({"face_index": face_index, "u": u, "v": v, "reason": "invalid_first_material_interval"})
                    continue
                records.append(
                    {
                        "face_index_zero_based": face_index,
                        "u": float(u),
                        "v": float(v),
                        "point_xyz_mm": xyz.tolist(),
                        "outward_normal": nxyz.tolist(),
                        "radial_normal_dot": radial_dot,
                        "all_hit_distances_mm": hits,
                        "all_interval_states": interval_states,
                        "first_material_interval_mm": [float(hits[0]), float(hits[1])],
                        "sampled_normal_wall_mm": float(thickness),
                    }
                )
                face_measured += 1
        face_coverage.append(
            {
                "face_index_zero_based": face_index,
                "uv_bounds": [float(u_min), float(u_max), float(v_min), float(v_max)],
                "outer_side_candidate_count": face_candidates,
                "measured_count": face_measured,
            }
        )
    distances = [record["sampled_normal_wall_mm"] for record in records]
    return {
        "method": "native trimmed revolution-face UV samples; OCC outward normal classification; all IntCurvesFace intersections sorted and tolerance clustered; every ray interval solid-classified",
        "selection": "outward radial-facing side and base-transition probes with radial_normal_dot > 0.25 and z below nominal rim; flat floor and rounded lip excluded",
        "sampling_grid_per_revolution_face": {"azimuth": azimuth_steps, "meridian": meridian_steps},
        "candidate_outer_side_samples": candidate_count,
        "measured_sample_count": len(records),
        "unknown_count": len(unknown),
        "unknown_first_50": unknown[:50],
        "face_coverage": face_coverage,
        "sampled_normal_wall_min_mm": float(min(distances)) if distances else None,
        "sampled_normal_wall_max_mm": float(max(distances)) if distances else None,
        "sampled_normal_wall_mean_mm": float(sum(distances) / len(distances)) if distances else None,
        "radial_setting_is_separate_from_these_measured_values": True,
        "samples": records,
        "scope": "finite measured rays only; global minimum normal thickness remains UNKNOWN",
    }


def step_roundtrip(candidate: NativeCandidate, step_path: Path) -> dict[str, Any]:
    """Separate optional STEP check; never called implicitly by construction."""
    import cadquery as cq

    step_path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(candidate.body, str(step_path), exportType="STEP")
    restored = cq.importers.importStep(str(step_path)).val()
    restored_solids, restored_shells = restored.Solids(), restored.Shells()
    restored_shell_closed = [bool(shell.Closed()) for shell in restored_shells]
    bbox_before = candidate.body.BoundingBox()
    bbox_after = restored.BoundingBox()
    before_bounds = [bbox_before.xmin, bbox_before.xmax, bbox_before.ymin, bbox_before.ymax, bbox_before.zmin, bbox_before.zmax]
    after_bounds = [bbox_after.xmin, bbox_after.xmax, bbox_after.ymin, bbox_after.ymax, bbox_after.zmin, bbox_after.zmax]
    volume_delta = float(restored.Volume() - candidate.body.Volume())
    bbox_deltas = [float(a - b) for a, b in zip(after_bounds, before_bounds)]
    roundtrip_pass = bool(
        restored.isValid()
        and len(restored_solids) == 1
        and len(restored_shells) == 1
        and all(restored_shell_closed)
        and abs(volume_delta) <= 0.01
        and max(abs(value) for value in bbox_deltas) <= 0.01
    )
    return {
        "status": "PASS" if roundtrip_pass else "FAIL",
        "step_path": str(step_path),
        "step_sha256": _sha256(step_path),
        "reloaded_valid": bool(restored.isValid()),
        "reloaded_solid_count": len(restored_solids),
        "reloaded_shell_count": len(restored_shells),
        "reloaded_shell_closed_flags": restored_shell_closed,
        "reloaded_open_boundary_shell_count": sum(not value for value in restored_shell_closed),
        "native_volume_mm3": float(candidate.body.Volume()),
        "reloaded_volume_mm3": float(restored.Volume()),
        "volume_delta_mm3": volume_delta,
        "native_bbox_mm": [float(value) for value in before_bounds],
        "reloaded_bbox_mm": [float(value) for value in after_bounds],
        "bbox_bound_deltas_mm": bbox_deltas,
        "acceptance_tolerances": {"absolute_volume_delta_mm3": 0.01, "absolute_bbox_bound_delta_mm": 0.01},
        "scope": "STEP geometry round-trip only; does not establish production serialization or physical qualification",
    }


def _mesh_triangles(shape: Any, *, linear_mm: float, angular_rad: float) -> Any:
    import numpy as np

    vertices, triangles = shape.tessellate(float(linear_mm), float(angular_rad))
    points = np.asarray([vertex.toTuple() for vertex in vertices], dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int64)
    return points[faces]


def render_native_body_and_section(candidate: NativeCandidate, output_png: Path) -> dict[str, Any]:
    """Render the actual native solid and a true half-space cut section."""
    import cadquery as cq
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.collections import PolyCollection
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    case = candidate.report["construction"]["family_parameters"]
    radius = float(case["max_radius_mm"])
    height = float(case["height_mm"])
    pad = max(5.0, 0.1 * radius)
    cutter = cq.Solid.makeBox(2 * (radius + pad), radius + 2 * pad, height + 2 * pad, cq.Vector(-radius - pad, 0.0, -pad))
    half_section = candidate.body.intersect(cutter)
    if half_section.isNull() or not half_section.isValid() or len(half_section.Solids()) != 1:
        raise ValueError("actual native half-space cut failed before rendering")

    body_triangles = _mesh_triangles(candidate.body, linear_mm=0.15, angular_rad=0.10)
    section_triangles = _mesh_triangles(half_section, linear_mm=0.15, angular_rad=0.10)
    cut_plane_mask = np.all(np.abs(section_triangles[:, :, 1]) <= 1e-5, axis=1)
    cut_plane_triangles = section_triangles[cut_plane_mask]
    if len(cut_plane_triangles) == 0:
        raise ValueError("native half-space result did not expose a tessellated y=0 section face")

    fig = plt.figure(figsize=(15.0, 7.2), facecolor="#f4f1e9")
    body_ax = fig.add_subplot(1, 2, 1, projection="3d")
    section_ax = fig.add_subplot(1, 2, 2)
    body_ax.set_facecolor("#f4f1e9")
    section_ax.set_facecolor("#f4f1e9")
    body_ax.add_collection3d(
        Poly3DCollection(body_triangles, facecolors="#abb9b4", edgecolors=(0.12, 0.18, 0.17, 0.10), linewidths=0.025)
    )
    body_ax.set_xlim(-radius - pad, radius + pad)
    body_ax.set_ylim(-radius - pad, radius + pad)
    body_ax.set_zlim(-pad, height + pad)
    body_ax.set_box_aspect((2 * radius + 2 * pad, 2 * radius + 2 * pad, height + 2 * pad))
    body_ax.view_init(elev=22, azim=-52)
    body_ax.set_axis_off()

    section_polygons = [triangle[:, (0, 2)] for triangle in cut_plane_triangles]
    section_ax.add_collection(PolyCollection(section_polygons, facecolors="#d49a76", edgecolors=(0.20, 0.15, 0.12, 0.16), linewidths=0.15))
    section_ax.set_xlim(-2.0, radius + pad)
    section_ax.set_ylim(-2.0, height + pad)
    section_ax.set_aspect("equal", adjustable="box")
    section_ax.set_xlabel("radius / mm")
    section_ax.set_ylabel("z / mm")
    section_ax.set_title("Actual y = 0 cut face from native B-rep")
    fig.suptitle(f"{candidate.family} • fixed analytic candidate • native CAD", fontsize=17, color="#28343a")
    fig.text(0.27, 0.04, "Full native solid", ha="center", color="#45545a")
    fig.text(0.74, 0.04, "Native half-space section face", ha="center", color="#45545a")
    fig.text(
        0.5,
        0.012,
        "ANALYTIC_CANDIDATE_ONLY • real-vessel match and physical qualification not validated • global normal minimum UNKNOWN",
        ha="center",
        fontsize=8,
        color="#68747a",
    )
    fig.subplots_adjust(left=0.02, right=0.98, top=0.90, bottom=0.13, wspace=0.06)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)
    return {
        "renderer": "tessellation of native OCC solid plus actual y>=0 half-space cut face",
        "full_body_triangle_count": int(len(body_triangles)),
        "half_section_triangle_count": int(len(section_triangles)),
        "cut_face_triangle_count": int(len(cut_plane_triangles)),
        "path": str(output_png),
        "sha256": _sha256(output_png),
    }


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_fixed_case(family: str, output: Path, *, include_step: bool) -> dict[str, Any]:
    import OCP
    import cadquery as cq

    candidate = build_native_candidate(family)
    max_distance = 4.0 * max(
        float(candidate.report["construction"]["family_parameters"]["height_mm"]),
        float(candidate.report["construction"]["family_parameters"]["max_radius_mm"]),
    )
    wall = measure_all_hit_normal_walls(
        candidate.body,
        max_distance_mm=max_distance,
        height_mm=float(candidate.report["construction"]["family_parameters"]["height_mm"]),
    )
    image_report = render_native_body_and_section(candidate, output / f"{family}_native_body_and_section.png")
    report = candidate.report
    report["runtime"] = {"cadquery_version": cq.__version__, "ocp_version": OCP.__version__, "linear_units": "mm"}
    report["normal_wall_sampling"] = wall
    report["render"] = image_report
    report["source_sha256"] = {
        "source": _sha256(Path(__file__).resolve()),
        "fixed_cases": _sha256(CASE_FILE),
    }
    if include_step:
        try:
            report["step_roundtrip"] = step_roundtrip(candidate, output / f"{family}_native_roundtrip.step")
        except Exception as exc:
            report["step_roundtrip"] = {
                "status": "FAIL",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            }
    else:
        report["step_roundtrip"] = {"status": "NOT_RUN_PENDING_REVIEW"}
    expected_local_wall_pass = wall["candidate_outer_side_samples"] > 0 and wall["unknown_count"] == 0 and wall["measured_sample_count"] > 0
    native_pass = (
        report["native_shape"]["valid"]
        and report["native_shape"]["solid_count"] == 1
        and report["native_shape"]["shell_count"] == 1
        and report["native_shape"]["open_boundary_shell_count"] == 0
        and report["native_shape"]["section_wire_closed"]
        and report["meridian_continuity"]["all_non_axis_joins_C2"]
        and report["fixed_case_preflight"]["status"] == "PASS_FIXED_CASE"
    )
    report["status"] = (
        "PASS_LOCAL_FIXED_CASE_GLOBAL_MINIMUM_UNKNOWN"
        if native_pass and expected_local_wall_pass
        else "FAIL_OR_LOCAL_EVIDENCE_UNKNOWN"
    )
    report["candidate_decision"] = "NOT_PROMOTED; analytic geometry candidate only; no real-vessel match or physical qualification"
    report_path = output / f"{family}_candidate_report.json"
    output.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("beaker", "bowl"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--step-roundtrip", action="store_true", help="separate STEP round-trip check; use only after review")
    args = parser.parse_args()
    report = run_fixed_case(args.family, args.output, include_step=args.step_roundtrip)
    step_status = report["step_roundtrip"].get("status")
    print(
        json.dumps(
            {
                "family": args.family,
                "status": report["status"],
                "step_status": step_status,
                "report": str(args.output / f"{args.family}_candidate_report.json"),
            },
            ensure_ascii=False,
        )
    )
    local_pass = report["status"] == "PASS_LOCAL_FIXED_CASE_GLOBAL_MINIMUM_UNKNOWN"
    step_pass = not args.step_roundtrip or step_status == "PASS"
    return 0 if local_pass and step_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
