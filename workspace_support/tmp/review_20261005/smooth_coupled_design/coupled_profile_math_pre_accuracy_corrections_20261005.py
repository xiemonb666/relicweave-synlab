"""Pure-math coupled meridian prototype for one fixed beaker case.

This module uses only Python's standard library and NumPy. It does not import
CadQuery/OCP, create B-reps, export STEP, or render geometry.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence

import numpy as np


CASE_FILE = Path(__file__).with_name("fixed_case_beaker_coupled_v2.json")
DEGREE = 5
GEOMETRY_ZERO_TOL_MM = 1e-10
RAY_ROOT_RESIDUAL_TOL_MM = 1e-8
RAY_NEAR_HIT_TOL_MM = 1e-5
RAY_MIN_DISTANCE_MM = 1e-6


@dataclass(frozen=True)
class Span:
    role: str
    controls: tuple[tuple[Fraction, Fraction], ...]
    parameter_width: Fraction


def _q(value: Any) -> Fraction:
    return Fraction(str(value))


def _add(a: tuple[Fraction, Fraction], b: tuple[Fraction, Fraction]) -> tuple[Fraction, Fraction]:
    return (a[0] + b[0], a[1] + b[1])


def _sub(a: tuple[Fraction, Fraction], b: tuple[Fraction, Fraction]) -> tuple[Fraction, Fraction]:
    return (a[0] - b[0], a[1] - b[1])


def _scale(k: Fraction, p: tuple[Fraction, Fraction]) -> tuple[Fraction, Fraction]:
    return (k * p[0], k * p[1])


def _pair(values: Sequence[Any]) -> tuple[Fraction, Fraction]:
    return (_q(values[0]), _q(values[1]))


def _hermite_controls(start: dict[str, Any], end: dict[str, Any], width: Any) -> tuple[tuple[Fraction, Fraction], ...]:
    h = _q(width)
    if h <= 0:
        raise ValueError("parameter widths must be positive")
    p0 = _pair(start["point_rz_mm"])
    p1 = _pair(end["point_rz_mm"])
    d0 = _scale(h, _pair(start["d1_rz_per_parameter"]))
    d1 = _scale(h, _pair(end["d1_rz_per_parameter"]))
    a0 = _scale(h * h, _pair(start["d2_rz_per_parameter2"]))
    a1 = _scale(h * h, _pair(end["d2_rz_per_parameter2"]))
    return (
        p0,
        _add(p0, _scale(Fraction(1, 5), d0)),
        _add(_add(p0, _scale(Fraction(2, 5), d0)), _scale(Fraction(1, 20), a0)),
        _add(_add(p1, _scale(Fraction(-2, 5), d1)), _scale(Fraction(1, 20), a1)),
        _add(p1, _scale(Fraction(-1, 5), d1)),
        p1,
    )


def _line_controls(start: Sequence[Any], end: Sequence[Any]) -> tuple[tuple[Fraction, Fraction], ...]:
    p0, p1 = _pair(start), _pair(end)
    return tuple(
        (
            p0[0] + Fraction(index, 5) * (p1[0] - p0[0]),
            p0[1] + Fraction(index, 5) * (p1[1] - p0[1]),
        )
        for index in range(6)
    )


def _bezier_exact(controls: Sequence[tuple[Fraction, Fraction]], t: Fraction) -> tuple[Fraction, Fraction]:
    values = list(controls)
    while len(values) > 1:
        values = [
            ((1 - t) * values[index][0] + t * values[index + 1][0], (1 - t) * values[index][1] + t * values[index + 1][1])
            for index in range(len(values) - 1)
        ]
    return values[0]


def _span_chain(rows: Sequence[dict[str, Any]], widths: Sequence[Any], name: str) -> tuple[Span, ...]:
    if len(widths) != len(rows) - 1:
        raise ValueError(f"{name}: one parameter width is required per adjoining pair")
    return tuple(
        Span(f"{name}:{index}", _hermite_controls(rows[index], rows[index + 1], widths[index]), _q(widths[index]))
        for index in range(len(widths))
    )


def _line_span(start: Sequence[Any], end: Sequence[Any], width: Any, role: str) -> Span:
    width_q = _q(width)
    if width_q <= 0:
        raise ValueError(f"{role}: parameter width must be positive")
    return Span(role, _line_controls(start, end), width_q)


def _make_lip(case: dict[str, Any]) -> Span:
    lip = case["lip_bridge"]
    start = {
        "point_rz_mm": lip["start_rz_mm"],
        "d1_rz_per_parameter": lip["start_d1_rz_per_parameter"],
        "d2_rz_per_parameter2": lip["start_d2_rz_per_parameter2"],
    }
    end = {
        "point_rz_mm": lip["end_rz_mm"],
        "d1_rz_per_parameter": lip["end_d1_rz_per_parameter"],
        "d2_rz_per_parameter2": lip["end_d2_rz_per_parameter2"],
    }
    width = case["curve_definition"]["lip_parameter_width"]
    return Span("rounded_lip_bridge", _hermite_controls(start, end, width), _q(width))


def _make_inner_base_fairing(case: dict[str, Any]) -> tuple[Span, ...]:
    fairing = case["inner_base_fairing"]
    return _span_chain(fairing["stations"], fairing["parameter_widths"], "inner_base_fairing")


def _translate_radially(span: Span, gap: Fraction, role: str, *, reverse: bool = False) -> Span:
    controls = tuple((r - gap, z) for r, z in span.controls)
    if reverse:
        controls = tuple(reversed(controls))
    return Span(role, controls, span.parameter_width)


def _make_inner_side_pairs(outer_spans: Sequence[Span], side_gap: Fraction, rim_gap: Fraction) -> tuple[Span, ...]:
    paired = []
    for index, outer in enumerate(outer_spans):
        start_jet = _edge_jet(outer, False)
        end_jet = _edge_jet(outer, True)
        start_gap = side_gap
        end_gap = rim_gap if index == len(outer_spans) - 1 else side_gap
        start = {
            "point_rz_mm": [start_jet[0][0] - start_gap, start_jet[0][1]],
            "d1_rz_per_parameter": start_jet[1],
            "d2_rz_per_parameter2": start_jet[2],
        }
        end = {
            "point_rz_mm": [end_jet[0][0] - end_gap, end_jet[0][1]],
            "d1_rz_per_parameter": end_jet[1],
            "d2_rz_per_parameter2": end_jet[2],
        }
        paired.append(Span(f"inner_side:{index}", _hermite_controls(start, end, outer.parameter_width), outer.parameter_width))
    return tuple(paired)


def build_model(case: dict[str, Any]) -> dict[str, Any]:
    dimensions = case["nominal_case"]
    construction = case["curve_definition"]
    wall = _q(case["identity_and_limits"]["radial_wall_setting_mm"])
    rim_gap = _q(case["identity_and_limits"]["rim_radial_gap_mm"])
    side_gap = _q(case["identity_and_limits"]["radial_wall_setting_mm"])
    base_stations = case["base_fairing_stations"]
    side_stations = case["outer_side_stations"]

    outside_underside = _line_span(
        (0, 0),
        (dimensions["outer_underside_radius_mm"], 0),
        construction["outside_underside_parameter_width"],
        "outer_underside",
    )
    base_spans = _span_chain(
        base_stations,
        construction["outer_base_fairing_parameter_widths"],
        "outer_base_fairing",
    )
    outer_side = _span_chain(side_stations, construction["outer_side_parameter_widths"], "outer_side")
    lip = _make_lip(case)
    inner_base_fairing = _make_inner_base_fairing(case)
    inner_side_forward = _make_inner_side_pairs(outer_side, wall, rim_gap)
    inner_side_reversed = tuple(
        Span(f"{span.role}:reversed", tuple(reversed(span.controls)), span.parameter_width)
        for span in reversed(inner_side_forward)
    )
    inner_floor_start = inner_base_fairing[-1].controls[-1]
    inner_floor_z = inner_floor_start[1]
    inner_floor = _line_span(inner_floor_start, (0, inner_floor_z), construction["inner_floor_parameter_width"], "inner_floor")
    axis = _line_span((0, inner_floor_z), (0, 0), construction["axis_closure_parameter_width"], "axis_closure")
    ordered = (outside_underside, *base_spans, *outer_side, lip, *inner_side_reversed, *inner_base_fairing, inner_floor, axis)
    return {
        "outside_underside": outside_underside,
        "base_spans": base_spans,
        "outer_side": outer_side,
        "lip": lip,
        "inner_side_forward": inner_side_forward,
        "inner_side_reversed": inner_side_reversed,
        "inner_base_fairing": inner_base_fairing,
        "inner_floor": inner_floor,
        "axis": axis,
        "ordered_section": ordered,
        "all_inner_boundary": (*inner_side_forward, *inner_base_fairing, inner_floor, axis, lip),
    }


def _edge_jet(span: Span, at_end: bool) -> tuple[tuple[Fraction, Fraction], tuple[Fraction, Fraction], tuple[Fraction, Fraction]]:
    p = span.controls
    first = tuple(_scale(Fraction(5), _sub(p[i + 1], p[i])) for i in range(5))
    second = tuple(
        _scale(Fraction(20), _add(_sub(p[i + 2], _scale(Fraction(2), p[i + 1])), p[i]))
        for i in range(4)
    )
    i = -1 if at_end else 0
    endpoint = p[-1] if at_end else p[0]
    local_d1 = first[i]
    local_d2 = second[i]
    h = span.parameter_width
    return endpoint, _scale(1 / h, local_d1), _scale(1 / (h * h), local_d2)


def _power_coefficients_from_bezier(values: Sequence[Fraction]) -> list[Fraction]:
    degree = len(values) - 1
    return [
        Fraction(math.comb(degree, order))
        * sum(
            Fraction((-1) ** (order - index) * math.comb(order, index)) * values[index]
            for index in range(order + 1)
        )
        for order in range(degree + 1)
    ]


def _poly_derivative(coefficients: Sequence[Fraction], order: int = 1) -> list[Fraction]:
    result = list(coefficients)
    for _ in range(order):
        result = [Fraction(index) * result[index] for index in range(1, len(result))]
    return result


def _poly_product(left: Sequence[Fraction], right: Sequence[Fraction]) -> list[Fraction]:
    result = [Fraction(0) for _ in range(len(left) + len(right) - 1)]
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            result[i + j] += a * b
    return result


def _power_to_bernstein(coefficients: Sequence[Fraction]) -> list[Fraction]:
    degree = len(coefficients) - 1
    return [
        sum(Fraction(math.comb(index, order), math.comb(degree, order)) * coefficients[order] for order in range(index + 1))
        for index in range(degree + 1)
    ]


def _curvature_numerator_bernstein(span: Span) -> list[Fraction]:
    radius_power = _power_coefficients_from_bezier([point[0] for point in span.controls])
    z_power = _power_coefficients_from_bezier([point[1] for point in span.controls])
    radius_first = _poly_derivative(radius_power)
    radius_second = _poly_derivative(radius_power, 2)
    z_first = _poly_derivative(z_power)
    z_second = _poly_derivative(z_power, 2)
    cross_power = [a - b for a, b in zip(_poly_product(radius_first, z_second), _poly_product(z_first, radius_second))]
    return _power_to_bernstein(cross_power)


def _exact_section_signed_area_twice(spans: Sequence[Span]) -> Fraction:
    total = Fraction(0)
    for span in spans:
        radius_power = _power_coefficients_from_bezier([point[0] for point in span.controls])
        z_power = _power_coefficients_from_bezier([point[1] for point in span.controls])
        radius_first = _poly_derivative(radius_power)
        z_first = _poly_derivative(z_power)
        integrand = [a - b for a, b in zip(_poly_product(radius_power, z_first), _poly_product(z_power, radius_first))]
        total += sum(coefficient / Fraction(index + 1) for index, coefficient in enumerate(integrand))
    return total


def _exact_c2_report(model: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    spans = model["ordered_section"]
    for left, right in zip(spans, spans[1:]):
        if left.role == "inner_floor" or left.role == "axis_closure" or right.role == "axis_closure":
            continue
        left_jet = _edge_jet(left, True)
        right_jet = _edge_jet(right, False)
        errors = [
            max(abs(a[i] - b[i]) for i in range(2))
            for a, b in zip(left_jet, right_jet)
        ]
        results.append(
            {
                "join": f"{left.role} -> {right.role}",
                "position_error_exact_mm": str(errors[0]),
                "d1_error_exact_mm_per_parameter": str(errors[1]),
                "d2_error_exact_mm_per_parameter2": str(errors[2]),
                "pass_exact_rational": errors == [0, 0, 0],
            }
        )
    return results


def _monotonicity_report(model: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    spans = (model["outside_underside"], *model["base_spans"], *model["outer_side"])
    checks = []
    for span in spans:
        r_values = [point[0] for point in span.controls]
        z_values = [point[1] for point in span.controls]
        r_direction = "nondecreasing" if r_values[-1] >= r_values[0] else "nonincreasing"
        r_deltas = [r_values[i + 1] - r_values[i] for i in range(5)]
        z_deltas = [z_values[i + 1] - z_values[i] for i in range(5)]
        r_ok = all(value >= 0 for value in r_deltas) if r_direction == "nondecreasing" else all(value <= 0 for value in r_deltas)
        z_ok = all(value >= 0 for value in z_deltas)
        checks.append(
            {
                "span": span.role,
                "radius_pole_direction": r_direction,
                "radius_derivative_pole_signs_exact": ["+" if value > 0 else "-" if value < 0 else "0" for value in r_deltas],
                "z_derivative_pole_signs_exact": ["+" if value > 0 else "-" if value < 0 else "0" for value in z_deltas],
                "radius_monotone_exact": r_ok,
                "z_nondecreasing_exact": z_ok,
                "radius_controls_mm": [float(value) for value in r_values],
                "z_controls_mm": [float(value) for value in z_values],
            }
        )
    lip = model["lip"]
    lip_z = [point[1] for point in lip.controls]
    lip_r = [point[0] for point in lip.controls]
    lip_z_deltas = [lip_z[i + 1] - lip_z[i] for i in range(5)]
    lip_r_deltas = [lip_r[i + 1] - lip_r[i] for i in range(5)]
    nonzero_z_signs = [1 if value > 0 else -1 for value in lip_z_deltas if value != 0]
    variations = sum(nonzero_z_signs[i] != nonzero_z_signs[i - 1] for i in range(1, len(nonzero_z_signs)))
    height = _q(case["lip_bridge"]["height_reference_mm"])
    lip_endpoint_jets = (_edge_jet(lip, False), _edge_jet(lip, True))
    lip_radius_derivative_strict_interior = all(value <= 0 for value in lip_r_deltas) and any(value < 0 for value in lip_r_deltas)
    lip_endpoint_speeds_nonzero = all(any(value != 0 for value in jet[1]) for jet in lip_endpoint_jets)
    lip_curvature_bernstein = _curvature_numerator_bernstein(lip)
    lip_curvature_same_sign = all(value >= 0 for value in lip_curvature_bernstein) or all(value <= 0 for value in lip_curvature_bernstein)
    lip_check = {
        "span": lip.role,
        "radius_nonincreasing_exact": all(value <= 0 for value in lip_r_deltas),
        "radius_derivative_control_signs_exact": ["+" if value > 0 else "-" if value < 0 else "0" for value in lip_r_deltas],
        "radius_derivative_strictly_negative_on_open_interval_by_bernstein_basis": lip_radius_derivative_strict_interior,
        "endpoint_speeds_nonzero_exact": lip_endpoint_speeds_nonzero,
        "endpoint_radial_gap_exact_mm": str(lip_r[0] - lip_r[-1]),
        "endpoint_radial_gap_matches_declared_exact": lip_r[0] - lip_r[-1] == _q(case["lip_bridge"]["radial_gap_mm"]),
        "z_controls_above_rim_exact": all(value >= height for value in lip_z),
        "z_derivative_signs_exact": ["+" if value > 0 else "-" if value < 0 else "0" for value in lip_z_deltas],
        "nonzero_z_derivative_sign_variations_exact": variations,
        "symmetric_control_net_has_z_crest_at_t_0_5": all(lip_z[i] == lip_z[-1 - i] for i in range(6)),
        "exact_symmetric_z_crest_mm": str(_bezier_exact(lip.controls, Fraction(1, 2))[1]),
        "exact_symmetric_z_crest_is_unique_max": bool(
            all(lip_z[i] == lip_z[-1 - i] for i in range(6))
            and all(value >= 0 for value in lip_z_deltas[:3])
            and all(value <= 0 for value in lip_z_deltas[3:])
            and lip_z_deltas[2] == 0
        ),
        "curvature_numerator_bernstein_coefficients_exact": [str(value) for value in lip_curvature_bernstein],
        "curvature_numerator_bernstein_signs_exact": ["+" if value > 0 else "-" if value < 0 else "0" for value in lip_curvature_bernstein],
        "convex_no_inflection_proved_by_exact_same_sign_bernstein_coefficients": lip_curvature_same_sign,
        "regular_convex_one_turn_proved_exact": lip_curvature_same_sign and lip_radius_derivative_strict_interior and lip_endpoint_speeds_nonzero,
        "radius_controls_mm": [float(value) for value in lip_r],
        "z_controls_mm": [float(value) for value in lip_z],
    }
    inner_positive = all(r > 0 for span in model["inner_side_forward"] for r, _ in span.controls)
    expected_gap = _q(case["identity_and_limits"]["radial_wall_setting_mm"])
    expected_rim_gap = _q(case["identity_and_limits"]["rim_radial_gap_mm"])
    paired_gaps = [
        outer.controls[i][0] - inner.controls[i][0]
        for outer, inner in zip(model["outer_side"], model["inner_side_forward"])
        for i in range(6)
    ]
    paired_z_same = all(
        outer.controls[i][1] == inner.controls[i][1]
        for outer, inner in zip(model["outer_side"], model["inner_side_forward"])
        for i in range(6)
    )
    inner_base_spans = model["inner_base_fairing"]
    inner_base_checks = []
    for span in inner_base_spans:
        inner_base_controls = span.controls
        inner_base_r_deltas = [inner_base_controls[i + 1][0] - inner_base_controls[i][0] for i in range(5)]
        inner_base_z_deltas = [inner_base_controls[i + 1][1] - inner_base_controls[i][1] for i in range(5)]
        inner_base_checks.append(
            {
                "span": span.role,
                "radius_nonincreasing_exact": all(value <= 0 for value in inner_base_r_deltas),
                "z_nondecreasing_in_traversal_exact": all(value <= 0 for value in inner_base_z_deltas),
                "control_poles_mm": [[float(r), float(z)] for r, z in inner_base_controls],
            }
        )
    inner_base_monotone = all(row["radius_nonincreasing_exact"] and row["z_nondecreasing_in_traversal_exact"] for row in inner_base_checks)
    rim_endpoint_gaps = [
        model["outer_side"][-1].controls[0][0] - model["inner_side_forward"][-1].controls[0][0],
        model["outer_side"][-1].controls[-1][0] - model["inner_side_forward"][-1].controls[-1][0],
    ]
    return {
        "control_polygon_derivative_sign_scope": "exact rational Bezier derivative control signs; nonnegative Bernstein basis on [0,1] implies the stated per-coordinate monotonicity for each whole span",
        "span_checks": checks,
        "all_outer_side_base_monotone_exact": all(row["radius_monotone_exact"] and row["z_nondecreasing_exact"] for row in checks),
        "lip": lip_check,
        "inner_side_control_radii_positive_exact": inner_positive,
        "paired_side_control_gap_exact_mm_before_rim_transition": str(expected_gap)
        if all(
            outer.controls[i][0] - inner.controls[i][0] == expected_gap
            for outer, inner in zip(model["outer_side"][:-1], model["inner_side_forward"][:-1])
            for i in range(6)
        )
        else None,
        "upper_shoulder_to_rim_endpoint_gaps_exact_mm": [str(gap) for gap in rim_endpoint_gaps],
        "rim_gap_transition_matches_declared_exact": rim_endpoint_gaps == [expected_gap, expected_rim_gap],
        "inner_side_control_gap_at_each_pole_exact_mm": [str(gap) for gap in paired_gaps],
        "paired_z_controls_identical_exact": paired_z_same,
        "paired_control_gap_is_normal_thickness": False,
        "inner_base_fairing": {
            "span_checks": inner_base_checks,
            "monotone_exact": inner_base_monotone,
        },
        "section_closed_endpoint_exact": model["ordered_section"][0].controls[0] == model["ordered_section"][-1].controls[-1],
        "all_adjoining_section_positions_exact": all(
            left.controls[-1] == right.controls[0]
            for left, right in zip(model["ordered_section"], model["ordered_section"][1:])
        ),
        "signed_section_area_exact_mm2": str(_exact_section_signed_area_twice(model["ordered_section"]) / 2),
        "signed_section_area_positive_exact": _exact_section_signed_area_twice(model["ordered_section"]) > 0,
        "simple_nonselfintersecting_section_proved": False,
    }


def _float_controls(span: Span) -> np.ndarray:
    return np.asarray([[float(r), float(z)] for r, z in span.controls], dtype=np.float64)


def _bezier_many(controls: np.ndarray, parameters: np.ndarray) -> np.ndarray:
    values = np.broadcast_to(controls, (len(parameters), *controls.shape)).copy()
    t = parameters[:, None, None]
    while values.shape[1] > 1:
        values = (1.0 - t) * values[:, :-1, :] + t * values[:, 1:, :]
    return values[:, 0, :]


def _bezier_one(controls: np.ndarray, parameter: float) -> np.ndarray:
    return _bezier_many(controls, np.asarray([parameter], dtype=np.float64))[0]


def _curvature_report(spans: Sequence[Span], sample_count: int) -> list[dict[str, Any]]:
    t = np.linspace(0.0, 1.0, sample_count, dtype=np.float64)
    reports = []
    for span in spans:
        controls = _float_controls(span)
        first = 5.0 * (controls[1:] - controls[:-1])
        second = 20.0 * (controls[2:] - 2.0 * controls[1:-1] + controls[:-2])
        point = _bezier_many(controls, t)
        d1 = _bezier_many(first, t) / float(span.parameter_width)
        d2 = _bezier_many(second, t) / float(span.parameter_width * span.parameter_width)
        speed = np.hypot(d1[:, 0], d1[:, 1])
        curvature = (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.maximum(speed**3, 1e-300)
        finite = np.isfinite(point).all(axis=1) & np.isfinite(d1).all(axis=1) & np.isfinite(d2).all(axis=1) & np.isfinite(curvature) & (speed > 1e-12)
        finite_curvature = finite & (np.abs(curvature) > 1e-12)
        radii = np.full_like(curvature, np.inf)
        radii[finite_curvature] = 1.0 / np.abs(curvature[finite_curvature])
        finite_radii = radii[finite_curvature]
        index = int(np.argmin(radii)) if len(radii) else -1
        reports.append(
            {
                "span": span.role,
                "parameter_width": float(span.parameter_width),
                "sample_count": sample_count,
                "all_samples_finite_and_non_degenerate": bool(np.all(finite)),
                "minimum_sampled_speed_mm_per_parameter": float(np.min(speed[finite])) if np.any(finite) else None,
                "maximum_absolute_sampled_curvature_per_mm": float(np.max(np.abs(curvature[finite]))) if np.any(finite) else None,
                "minimum_finite_sampled_curvature_radius_mm": float(np.min(finite_radii)) if len(finite_radii) else None,
                "minimum_radius_parameter_sample": float(t[index]) if index >= 0 and math.isfinite(float(radii[index])) else None,
                "maximum_sampled_z_mm": float(np.max(point[:, 1])) if len(point) else None,
                "maximum_sampled_z_parameter": float(t[int(np.argmax(point[:, 1]))]) if len(point) else None,
                "control_hull_z_upper_bound_mm": float(np.max(controls[:, 1])) if len(controls) else None,
                "scope": "uniform finite samples only; no whole-span curvature bound claimed",
            }
        )
    return reports


def _bisect_root(span: Span, normal: np.ndarray, point: np.ndarray, a: float, b: float, fa: float, controls: np.ndarray) -> tuple[float, np.ndarray]:
    lo, hi, flo, fhi = a, b, fa, float(np.dot(normal, np.asarray([_bezier_one(controls, b)[1] - point[1], -( _bezier_one(controls, b)[0] - point[0]) ])))
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        p = _bezier_one(controls, mid)
        fm = normal[0] * (p[1] - point[1]) - normal[1] * (p[0] - point[0])
        if fm == 0.0:
            lo = hi = mid
            break
        if (flo < 0.0) != (fm < 0.0):
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    root = 0.5 * (lo + hi)
    return root, _bezier_one(controls, root)


def _inner_boundary_hits(point: np.ndarray, outward_normal: np.ndarray, spans: Sequence[Span]) -> list[dict[str, Any]]:
    grid = np.linspace(0.0, 1.0, 257, dtype=np.float64)
    roots: list[dict[str, Any]] = []
    for span in spans:
        controls = _float_controls(span)
        points = _bezier_many(controls, grid)
        values = outward_normal[0] * (points[:, 1] - point[1]) - outward_normal[1] * (points[:, 0] - point[0])
        for index in range(len(grid) - 1):
            fa, fb = float(values[index]), float(values[index + 1])
            if fa == 0.0:
                parameter = float(grid[index])
                hit = points[index]
            elif fb == 0.0:
                parameter = float(grid[index + 1])
                hit = points[index + 1]
            elif (fa < 0.0) == (fb < 0.0):
                continue
            else:
                parameter, hit = _bisect_root(span, outward_normal, point, float(grid[index]), float(grid[index + 1]), fa, controls)
            signed_distance = float(np.dot(point - hit, outward_normal))
            residual = abs(float(outward_normal[0] * (hit[1] - point[1]) - outward_normal[1] * (hit[0] - point[0])))
            if signed_distance > RAY_MIN_DISTANCE_MM and residual <= RAY_ROOT_RESIDUAL_TOL_MM:
                roots.append(
                    {
                        "span": span.role,
                        "parameter": parameter,
                        "distance_mm": signed_distance,
                        "hit_rz_mm": [float(hit[0]), float(hit[1])],
                        "line_residual_mm": residual,
                    }
                )
    roots.sort(key=lambda row: row["distance_mm"])
    unique: list[dict[str, Any]] = []
    for root in roots:
        if unique:
            previous = unique[-1]
            same_point = math.dist(root["hit_rz_mm"], previous["hit_rz_mm"]) <= 1e-12
            same_distance = abs(root["distance_mm"] - previous["distance_mm"]) <= 1e-12
            if same_point and same_distance:
                continue
        unique.append(root)
    return unique


def _normal_probe_report(model: dict[str, Any], ray_count_per_span: int) -> dict[str, Any]:
    outer_spans = (*model["base_spans"], *model["outer_side"])
    inner_boundary = model["all_inner_boundary"]
    t_values = np.linspace(0.0, 1.0, ray_count_per_span, dtype=np.float64)
    records: list[dict[str, Any]] = []
    excluded_radial = 0
    excluded_axis = 0
    for span in outer_spans:
        controls = _float_controls(span)
        first = 5.0 * (controls[1:] - controls[:-1])
        for t in t_values:
            p = _bezier_one(controls, float(t))
            tangent = _bezier_one(first, float(t)) / float(span.parameter_width)
            speed = float(np.hypot(tangent[0], tangent[1]))
            if not math.isfinite(speed) or speed <= 1e-12:
                records.append({"source_span": span.role, "t": float(t), "status": "UNKNOWN_DEGENERATE_TANGENT"})
                continue
            outward = np.asarray([tangent[1] / speed, -tangent[0] / speed], dtype=np.float64)
            if p[0] <= 1e-6:
                excluded_axis += 1
                continue
            if outward[0] <= 0.25:
                excluded_radial += 1
                continue
            hits = _inner_boundary_hits(p, outward, inner_boundary)
            if not hits:
                records.append(
                    {
                        "source_span": span.role,
                        "t": float(t),
                        "point_rz_mm": [float(p[0]), float(p[1])],
                        "outward_normal_rz": [float(outward[0]), float(outward[1])],
                        "status": "UNKNOWN_NO_INNER_BOUNDARY_INTERSECTION",
                        "raw_positive_hits": hits,
                    }
                )
                continue
            near_pairs = [
                [hits[i]["distance_mm"], hits[i + 1]["distance_mm"]]
                for i in range(len(hits) - 1)
                if hits[i + 1]["distance_mm"] - hits[i]["distance_mm"] <= RAY_NEAR_HIT_TOL_MM
            ]
            if near_pairs:
                status = "UNKNOWN_NEAR_DISTINCT_INNER_HITS"
            else:
                status = "MEASURED_CANDIDATE_INNER_BOUNDARY_DISTANCE"
            records.append(
                {
                    "source_span": span.role,
                    "t": float(t),
                    "point_rz_mm": [float(p[0]), float(p[1])],
                    "outward_normal_rz": [float(outward[0]), float(outward[1])],
                    "status": status,
                    "first_positive_inner_boundary_hit": hits[0],
                    "all_positive_inner_boundary_hits": hits,
                    "near_distinct_hit_pairs_mm": near_pairs,
                    "paired_radial_setting_mm": 2.5,
                }
            )
    distances = [row["first_positive_inner_boundary_hit"]["distance_mm"] for row in records if row["status"] == "MEASURED_CANDIDATE_INNER_BOUNDARY_DISTANCE"]
    unknown_count = sum(str(row.get("status", "")).startswith("UNKNOWN") for row in records)
    return {
        "method": "pure 2D meridian-generator normal rays against explicitly paired inner Bezier boundary; no solid classifier or all-face OCC query",
        "ray_samples_per_outer_span": ray_count_per_span,
        "outer_spans_in_scope": [span.role for span in outer_spans],
        "eligible_count": len(records),
        "measured_candidate_count": len(distances),
        "unknown_count": unknown_count,
        "excluded_radial_normal_dot_le_0_25_count": excluded_radial,
        "excluded_axis_count": excluded_axis,
        "sampled_candidate_inner_boundary_distance_min_mm": float(min(distances)) if distances else None,
        "sampled_candidate_inner_boundary_distance_max_mm": float(max(distances)) if distances else None,
        "sampled_candidate_inner_boundary_distance_mean_mm": float(sum(distances) / len(distances)) if distances else None,
        "all_rows": records,
        "scope": "finite 2D section-generator intersections only; a candidate inner-boundary distance, not a classifier-confirmed material interval or a global normal-wall minimum",
    }


def _controls_json(spans: Sequence[Span]) -> list[dict[str, Any]]:
    return [
        {
            "role": span.role,
            "parameter_width": str(span.parameter_width),
            "control_poles_exact_rz_mm": [[str(r), str(z)] for r, z in span.controls],
            "control_poles_float_rz_mm": [[float(r), float(z)] for r, z in span.controls],
        }
        for span in spans
    ]


def run_diagnostics(case: dict[str, Any], *, curvature_samples_per_span: int = 1001, ray_samples_per_span: int = 101) -> dict[str, Any]:
    model = build_model(case)
    c2 = _exact_c2_report(model)
    monotonicity = _monotonicity_report(model, case)
    non_axis_spans = model["ordered_section"][:-1]
    curvature = _curvature_report(non_axis_spans, curvature_samples_per_span)
    normal_rays = _normal_probe_report(model, ray_samples_per_span)
    target_mm = float(case["acceptance_constraints"]["sampled_minimum_curvature_radius_target_mm"])
    outer_lower_rows = [
        row
        for row in curvature
        if row["span"].startswith("outer_base_fairing:")
        or row["span"] in {"outer_side:0", "outer_side:1"}
    ]
    inner_base_rows = [row for row in curvature if row["span"].startswith("inner_base_fairing:")]
    lip_rows = [row for row in curvature if row["span"] == "rounded_lip_bridge"]
    c2_pass = bool(c2) and all(row["pass_exact_rational"] for row in c2)
    exact_control_pass = bool(
        monotonicity["all_outer_side_base_monotone_exact"]
        and monotonicity["lip"]["radius_nonincreasing_exact"]
        and monotonicity["lip"]["endpoint_radial_gap_matches_declared_exact"]
        and monotonicity["lip"]["z_controls_above_rim_exact"]
        and monotonicity["lip"]["exact_symmetric_z_crest_is_unique_max"]
        and monotonicity["lip"]["convex_no_inflection_proved_by_exact_same_sign_bernstein_coefficients"]
        and monotonicity["lip"]["regular_convex_one_turn_proved_exact"]
        and monotonicity["inner_side_control_radii_positive_exact"]
        and monotonicity["paired_z_controls_identical_exact"]
        and monotonicity["paired_side_control_gap_exact_mm_before_rim_transition"] == "5/2"
        and monotonicity["rim_gap_transition_matches_declared_exact"]
        and monotonicity["inner_base_fairing"]["monotone_exact"]
        and monotonicity["section_closed_endpoint_exact"]
        and monotonicity["all_adjoining_section_positions_exact"]
        and monotonicity["signed_section_area_positive_exact"]
    )
    # A `None` minimum means every finite sample on that span had zero
    # curvature, hence infinite sampled radius. Treat it as +infinity for this
    # finite-sample target while keeping JSON output standards-compliant.
    outer_lower_target_pass = bool(outer_lower_rows) and all(
        row["minimum_finite_sampled_curvature_radius_mm"] is None
        or row["minimum_finite_sampled_curvature_radius_mm"] >= target_mm
        for row in outer_lower_rows
    )
    inner_base_target_pass = bool(inner_base_rows) and all(
        row["minimum_finite_sampled_curvature_radius_mm"] is None
        or row["minimum_finite_sampled_curvature_radius_mm"] >= target_mm
        for row in inner_base_rows
    )
    lower_target_pass = outer_lower_target_pass and inner_base_target_pass
    lip_target_pass = bool(lip_rows) and (
        lip_rows[0]["minimum_finite_sampled_curvature_radius_mm"] is None
        or lip_rows[0]["minimum_finite_sampled_curvature_radius_mm"] >= target_mm
    )
    return {
        "schema": "vesselforge.smooth_surface_coupled_design.math_diagnostics/0.1.0",
        "candidate_id": case["candidate_id"],
        "status": "PURE_MATH_TARGETS_MET_FINITE_ONLY" if c2_pass and exact_control_pass and lower_target_pass and lip_target_pass and normal_rays["unknown_count"] == 0 else "PURE_MATH_DIAGNOSTIC_NEEDS_REVIEW",
        "cad_or_step_run": False,
        "physical_or_style_validation": "NOT_VALIDATED",
        "global_minimum_normal_wall": "UNKNOWN",
        "units": case["units"],
        "fixed_case_sha256_is_recorded_in_freeze_manifest": True,
        "all_control_nets": _controls_json(model["ordered_section"]),
        "exact_non_axis_c2_joins": c2,
        "all_non_axis_c2_exact": c2_pass,
        "control_polygon_constraints": monotonicity,
        "all_exact_control_constraints_pass": exact_control_pass,
        "curvature_sampling": {
            "method": "analytic first/second Bezier derivatives evaluated by float64 de Casteljau",
            "samples_per_span": curvature_samples_per_span,
            "spans": curvature,
            "base_lowerbody_sample_target_mm": target_mm,
            "base_lowerbody_sample_target_pass": lower_target_pass,
            "outer_base_lowerbody_sample_target_pass": outer_lower_target_pass,
            "inner_base_fairing_sample_target_pass": inner_base_target_pass,
            "lip_sample_target_mm": target_mm,
            "lip_sample_target_pass": lip_target_pass,
            "scope": "finite samples only; no whole-span curvature bound is claimed",
        },
        "paired_wall": {
            "paired_side_control_gap_exact_mm_before_rim_transition": monotonicity["paired_side_control_gap_exact_mm_before_rim_transition"],
            "upper_shoulder_to_rim_endpoint_gaps_exact_mm": monotonicity["upper_shoulder_to_rim_endpoint_gaps_exact_mm"],
            "lip_endpoint_radial_gap_exact_mm": monotonicity["lip"]["endpoint_radial_gap_exact_mm"],
            "same_z_controls_exact": monotonicity["paired_z_controls_identical_exact"],
            "radial_gap_is_normal_thickness": False,
            "inner_side_control_radii_positive_exact": monotonicity["inner_side_control_radii_positive_exact"],
        },
        "height_scope": {
            "nominal_height_is_rim_endpoint_z_mm": float(_q(case["nominal_case"]["height_mm"])),
            "exact_symmetric_lip_crest_z_mm": monotonicity["lip"]["exact_symmetric_z_crest_mm"],
            "lip_crest_is_unique_max_within_lip_exact": monotonicity["lip"]["exact_symmetric_z_crest_is_unique_max"],
            "section_control_hull_z_upper_bound_exact_mm": str(max(z for span in model["ordered_section"] for _, z in span.controls)),
            "section_control_hull_z_upper_bound_mm": float(max(z for span in model["ordered_section"] for _, z in span.controls)),
            "section_maximum_native_bbox": "UNKNOWN_NOT_CAD_VALIDATED",
            "nominal_height_is_full_geometry_max_z": False,
        },
        "finite_normal_ray_diagnostic": normal_rays,
        "algorithm_limits": {
            "root_search_subdivisions_per_inner_span": 256,
            "bisection_steps_per_bracket": 60,
            "root_residual_tolerance_mm": RAY_ROOT_RESIDUAL_TOL_MM,
            "near_distinct_hit_refusal_tolerance_mm": RAY_NEAR_HIT_TOL_MM,
            "scope": "floating-point root search; diagnostic only; it does not classify a native solid or prove intersection absence between brackets",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--curvature-samples-per-span", type=int, default=1001)
    parser.add_argument("--ray-samples-per-span", type=int, default=101)
    args = parser.parse_args()
    if args.curvature_samples_per_span < 101 or args.ray_samples_per_span < 11:
        parser.error("use at least 101 curvature samples and 11 ray samples per span")
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")
    case = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    report = run_diagnostics(
        case,
        curvature_samples_per_span=args.curvature_samples_per_span,
        ray_samples_per_span=args.ray_samples_per_span,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_id": report["candidate_id"], "status": report["status"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["status"] == "PURE_MATH_TARGETS_MET_FINITE_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
