"""Reconcile the saved one-ray failure against exact source meridian math.

This script imports only the Python source definitions and reads the saved
JSON report. It does not import CadQuery/OCP or construct native geometry.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE_PATH = ROOT / "vesselforge" / "experiments" / "smooth_surface_route_20261004" / "route_source_draft.py"
CASES_PATH = ROOT / "vesselforge" / "experiments" / "smooth_surface_route_20261004" / "fixed_cases.json"
REPORT_PATH = HERE / "run_beaker" / "beaker_candidate_report.json"
SPEC = importlib.util.spec_from_file_location("smooth_route_source_analysis", SOURCE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load source definitions from {SOURCE_PATH}")
SOURCE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SOURCE
SPEC.loader.exec_module(SOURCE)

report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
unknown = report["normal_wall_sampling"]["unknown"][0]
xyz = tuple(float(value) for value in unknown["point_xyz_mm"])
reported_normal = tuple(float(value) for value in unknown["normal_out"])
radius = math.hypot(xyz[0], xyz[1])
query_rz = (radius, xyz[2])

case = cases["families"]["beaker"]
shared = cases["shared_construction"]
stations = SOURCE._stations_from_case(case, shared)
outer_spans = SOURCE._span_chain(stations, "outer_side")
sampled_candidates = []
for span in outer_spans:
    for step in range(10001):
        t = step / 10000.0
        point = SOURCE._bezier_value(span.controls_rz_mm, t)
        gap = math.hypot(point[0] - query_rz[0], point[1] - query_rz[1])
        sampled_candidates.append((gap, span, t, point))
distance_mm, span, t, curve_point = min(sampled_candidates, key=lambda item: item[0])
first_net, second_net = SOURCE._bezier_derivatives(span.controls_rz_mm)
d1_local = SOURCE._bezier_value(first_net, t)
d2_local = SOURCE._bezier_value(second_net, t)
parameter_width = span.parameter_width
dr = d1_local[0] / parameter_width
dz = d1_local[1] / parameter_width
d2r = d2_local[0] / (parameter_width * parameter_width)
d2z = d2_local[1] / (parameter_width * parameter_width)
speed = math.hypot(dr, dz)
curvature = (dr * d2z - dz * d2r) / speed**3
normal_rz = (dz / speed, -dr / speed)
radial_unit = (xyz[0] / radius, xyz[1] / radius)
expected_world_normal = (
    normal_rz[0] * radial_unit[0],
    normal_rz[0] * radial_unit[1],
    normal_rz[1],
)
normal_dot = sum(a * b for a, b in zip(expected_world_normal, reported_normal))
normal_angle_deg = math.degrees(math.acos(max(-1.0, min(1.0, normal_dot))))

nearest_report_samples = []
for span_record in report["meridian_continuity"]["curve_samples"]["spans"]:
    for sample in span_record["samples"]:
        point = sample["point_rz_mm"]
        gap = math.hypot(point[0] - query_rz[0], point[1] - query_rz[1])
        nearest_report_samples.append((gap, span_record["role"], sample))
nearest_report_samples.sort(key=lambda item: item[0])

result = {
    "method": "pure fixed-case Bezier evaluation; no native CAD or OCC classification run",
    "unknown": {
        "reason": unknown["reason"],
        "face_index_zero_based": unknown["face_index"],
        "u": unknown["u"],
        "v": unknown["v"],
        "xyz_mm": xyz,
        "rz_mm": query_rz,
        "normal_xyz": reported_normal,
        "outside_classifier_state": unknown["outside_state"],
        "surface_classifier_state": unknown["surface_state"],
    },
    "nearest_exact_outer_curve": {
        "role": span.role,
        "uniform_search_t": t,
        "source_rz_mm": curve_point,
        "distance_to_reported_rz_mm": distance_mm,
        "tangent_rz_per_parameter": [dr, dz],
        "curvature_per_mm": curvature,
        "curvature_radius_mm": None if abs(curvature) <= 1e-15 else 1.0 / abs(curvature),
        "outward_profile_normal_rz": list(normal_rz),
        "expected_world_normal_xyz": list(expected_world_normal),
        "dot_with_reported_native_normal": normal_dot,
        "angle_to_reported_native_normal_deg": normal_angle_deg,
        "offset_epsilon_mm_in_source": 1e-4,
        "normal_probe_move_xyz_mm": [1e-4 * value for value in reported_normal],
    },
    "nearest_saved_curve_samples": [
        {
            "role": role,
            "t": sample["t"],
            "point_rz_mm": sample["point_rz_mm"],
            "distance_mm": gap,
            "curvature_per_mm": sample["curvature_per_mm"],
            "radius_of_curvature_mm": sample["radius_of_curvature_mm"],
        }
        for gap, role, sample in nearest_report_samples[:5]
    ],
    "face_coverage_record": next(
        face
        for face in report["normal_wall_sampling"]["face_coverage"]
        if face["face_index_zero_based"] == unknown["face_index"]
    ),
}
print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
