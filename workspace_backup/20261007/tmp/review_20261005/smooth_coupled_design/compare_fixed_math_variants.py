"""Small, named pure-math comparisons; this module never creates CAD geometry."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = ROOT / "vesselforge/experiments/smooth_surface_coupled_design_20261005"
SOURCE = EXPERIMENT / "coupled_profile_math.py"
CASE = EXPERIMENT / "fixed_case_beaker.json"
FINAL_CASE = EXPERIMENT / "fixed_case_beaker_coupled_v2.json"
spec = importlib.util.spec_from_file_location("coupled_profile_math", SOURCE)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)
base = json.loads(CASE.read_text(encoding="utf-8"))


def set_station(row: dict, point=None, d1=None) -> None:
    if point is not None:
        row["point_rz_mm"] = point
    if d1 is not None:
        row["d1_rz_per_parameter"] = d1


variants = []

def build_coupled_tilted_root_candidate(*, base_mid_z: float, base_mid_dr: float, base_mid_dz: float, inner_mid_r: float, inner_mid_z: float, inner_mid_dr: float, inner_mid_dz: float, lower_r: float, lower_z: float, lower_dr: float, lower_dz: float, lower_body_r: float, lower_body_z: float, first_side_width: float = 0.5, lip_scale: float = 7.0) -> dict:
    candidate = copy.deepcopy(base)
    candidate["candidate_id"] = "beaker-coupled-fairing-math-v2"
    candidate["status"] = "PURE_MATH_PROTOTYPE_ONLY_NOT_CAD_VALIDATED"
    candidate["scope"] = "One fixed coupled analytic beaker profile; real style, native geometry, material, manufacture, and reusable family range are unknown."
    candidate["nominal_case"]["outer_side_root_rz_mm"] = [20.0, 10.0]
    candidate["nominal_case"]["inner_mouth_radius_mm"] = 34.0
    candidate["nominal_case"]["clear_mouth_diameter_mm"] = 68.0
    candidate["nominal_case"]["height_semantics"] = "rim_endpoint_z_mm; lip crest is higher and full geometry height/bbox is not validated"
    candidate["identity_and_limits"]["rim_radial_gap_mm"] = 3.5
    candidate["identity_and_limits"]["rim_gap_semantics"] = "local thickened rim endpoint gap from 2.5 mm at shoulder to 3.5 mm at mouth; style and functional suitability unknown"
    candidate["identity_and_limits"]["radial_wall_semantics"] = "2.5 mm paired radial control gap through the shoulder; not normal wall thickness. A separate rim transition increases the endpoint gap to 3.5 mm."
    candidate["acceptance_constraints"]["sampled_minimum_curvature_radius_target_mm"] = 1.25
    set_station(candidate["base_fairing_stations"][1], point=[16.0, base_mid_z], d1=[base_mid_dr, base_mid_dz])
    set_station(candidate["base_fairing_stations"][2], point=[20.0, 10.0], d1=[8.0, 12.0])
    set_station(candidate["outer_side_stations"][0], point=[20.0, 10.0], d1=[8.0, 12.0])
    set_station(candidate["outer_side_stations"][1], point=[lower_r, lower_z], d1=[lower_dr, lower_dz])
    set_station(candidate["outer_side_stations"][2], point=[lower_body_r, lower_body_z], d1=[10.0, 17.0])
    set_station(candidate["outer_side_stations"][3], point=[38.0, 50.0], d1=[8.0, 20.0])
    set_station(candidate["outer_side_stations"][-1], d1=[0.0, 7.0])
    candidate["curve_definition"]["outer_base_fairing_parameter_widths"] = [0.5, 0.5]
    candidate["curve_definition"]["outer_side_parameter_widths"] = [first_side_width, 0.75, 0.75, 1.0, 1.0, 1.0]
    candidate["curve_definition"]["inner_floor_parameter_width"] = 3.0
    candidate["curve_definition"]["inner_side_pairing"] = "side spans before the last shoulder-to-rim span use exact 2.5 mm radial endpoint/control gap; the last span uses a degree-5 C2 endpoint fit from 2.5 mm at shoulder to 3.5 mm at rim; no claim of normal offset"
    set_station(candidate["base_fairing_stations"][0], point=[12.0, 0.0], d1=[4.0, 0.0])
    candidate["inner_base_fairing"] = {
        "stations": [
            {"name": "inner_wall_root", "point_rz_mm": [17.5, 10.0], "d1_rz_per_parameter": [-8.0, -12.0], "d2_rz_per_parameter2": [0.0, 0.0]},
            {"name": "inner_base_transition", "point_rz_mm": [inner_mid_r, inner_mid_z], "d1_rz_per_parameter": [-inner_mid_dr, -inner_mid_dz], "d2_rz_per_parameter2": [0.0, 0.0]},
            {"name": "inner_floor_tangent", "point_rz_mm": [12.0, 4.5], "d1_rz_per_parameter": [-4.0, 0.0], "d2_rz_per_parameter2": [0.0, 0.0]},
        ],
        "parameter_widths": [0.5, 0.5],
    }
    candidate["lip_bridge"]["start_rz_mm"] = [37.5, 110.0]
    candidate["lip_bridge"]["end_rz_mm"] = [34.0, 110.0]
    candidate["lip_bridge"]["radial_gap_mm"] = 3.5
    candidate["lip_bridge"]["start_d1_rz_per_parameter"] = [0.0, lip_scale]
    candidate["lip_bridge"]["end_d1_rz_per_parameter"] = [0.0, -lip_scale]
    candidate["lip_bridge"]["tangent_scale_mm_per_parameter"] = lip_scale
    candidate["acceptance_constraints"]["sampled_minimum_curvature_radius_target_mm"] = 1.25
    candidate["acceptance_constraints"]["sampled_curvature_design_target"] = "finite 1001-sample minimum radius >= 1.25 mm for outer/inner base fairings, first two lower-body spans, and lip; sample target only, never a whole-span bound"
    candidate["acceptance_constraints"]["lip_convexity"] = "compute exact Bernstein signs for r' z'' - z' r''; state convex/no-inflection only if exact same-sign coefficients establish it"
    candidate["acceptance_constraints"]["normal_thickness_scope"] = "101 fixed meridian-generator rays per eligible outer base/side span; preserve unknowns and all raw hits; candidate inner-boundary distance is not native material interval or a global normal-wall minimum"
    candidate["parameter_bounds_for_this_candidate_only"] = {
        "shared_outer_wall_root_rz_mm": {"fixed": [20.0, 10.0], "range_mm": [[20.0, 20.0], [10.0, 10.0]]},
        "outer_base_transition_1_rz_mm": {"fixed": [15.0, 1.5], "range_mm": [[15.0, 15.0], [1.5, 1.5]]},
        "outer_base_transition_2_rz_mm": {"fixed": [18.0, 6.5], "range_mm": [[18.0, 18.0], [6.5, 6.5]]},
        "lower_body_transition_rz_mm": {"fixed": [24.0, 17.0], "range_mm": [[24.0, 24.0], [17.0, 17.0]]},
        "inner_base_transition_rz_mm": {"fixed": [13.75, 7.5], "range_mm": [[13.75, 13.75], [7.5, 7.5]]},
        "inner_floor_tangent_rz_mm": {"fixed": [10.0, 4.5], "range_mm": [[10.0, 10.0], [4.5, 4.5]]},
        "side_radial_control_gap_mm": {"fixed": 2.5, "candidate_bound_mm": [2.5, 2.5]},
        "thickened_rim_radial_endpoint_gap_mm": {"fixed": 3.5, "candidate_bound_mm": [3.5, 3.5], "motivation": "greater than 2.5 mm half-turn feasibility lower limit for a 1.25 mm convex-lip sample design target; this is not a style claim"},
        "lip_vertical_tangent_scale_mm_per_parameter": {"fixed": lip_scale, "candidate_bound_mm": [lip_scale, lip_scale]},
        "fixed_candidate_values_are_not_auto_optimized": True,
        "bound_scope": "frozen single beaker candidate; not a reusable family or manufacturing range",
    }
    return candidate


# One coupled fixed hypothesis: an added outside base station gradually rotates
# the shared root tangent. The inside fairing gets one intermediate station and
# a longer floor run. The final outside span aligns with the root chord.
v = build_coupled_tilted_root_candidate(base_mid_z=5.0, base_mid_dr=6.0, base_mid_dz=7.5, inner_mid_r=15.0, inner_mid_z=7.5, inner_mid_dr=6.0, inner_mid_dz=6.0, lower_r=24.0, lower_z=16.0, lower_dr=5.0, lower_dz=7.5, lower_body_r=30.0, lower_body_z=30.0)
v["base_fairing_stations"] = [
    {"name": "underside_tangent", "point_rz_mm": [12.0, 0.0], "d1_rz_per_parameter": [4.0, 0.0], "d2_rz_per_parameter2": [0.0, 0.0]},
    {"name": "base_transition_1", "point_rz_mm": [15.0, 1.5], "d1_rz_per_parameter": [4.0, 3.0], "d2_rz_per_parameter2": [0.0, 0.0]},
    {"name": "base_transition_2", "point_rz_mm": [18.0, 6.5], "d1_rz_per_parameter": [8.0, 14.0], "d2_rz_per_parameter2": [0.0, 0.0]},
    {"name": "shared_wall_root", "point_rz_mm": [20.0, 10.0], "d1_rz_per_parameter": [8.0, 14.0], "d2_rz_per_parameter2": [0.0, 0.0]},
]
v["curve_definition"]["outer_base_fairing_parameter_widths"] = [0.5, 0.4, 0.3]
v["outer_side_stations"][0]["d1_rz_per_parameter"] = [8.0, 14.0]
v["outer_side_stations"][1]["point_rz_mm"] = [24.0, 17.0]
v["outer_side_stations"][1]["d1_rz_per_parameter"] = [5.0, 8.75]
v["inner_base_fairing"]["stations"] = [
    {"name": "inner_wall_root", "point_rz_mm": [17.5, 10.0], "d1_rz_per_parameter": [-8.0, -14.0], "d2_rz_per_parameter2": [0.0, 0.0]},
    {"name": "inner_base_transition", "point_rz_mm": [13.75, 7.5], "d1_rz_per_parameter": [-6.0, -5.0], "d2_rz_per_parameter2": [0.0, 0.0]},
    {"name": "inner_floor_tangent", "point_rz_mm": [10.0, 4.5], "d1_rz_per_parameter": [-4.0, 0.0], "d2_rz_per_parameter2": [0.0, 0.0]},
]
v["inner_base_fairing"]["parameter_widths"] = [0.3, 0.5]
v["curve_definition"]["inner_floor_parameter_width"] = 2.5
if FINAL_CASE.exists():
    raise SystemExit(f"refusing to overwrite final case: {FINAL_CASE}")
FINAL_CASE.write_text(json.dumps(v, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
variants.append(("coupled_tilted_root_D_three_span_outer_base_and_one_inner_adjustment", v))

rows = []
for name, candidate in variants:
    report = module.run_diagnostics(candidate, curvature_samples_per_span=301, ray_samples_per_span=13)
    radii = {
        row["span"]: row["minimum_finite_sampled_curvature_radius_mm"]
        for row in report["curvature_sampling"]["spans"]
    }
    lower_values = [
        radii[key]
        for key in ("outer_base_fairing:0", "outer_base_fairing:1", "outer_side:0", "outer_side:1")
        if radii[key] is not None
    ]
    inner_base_radii = [
        row["minimum_finite_sampled_curvature_radius_mm"]
        for row in report["curvature_sampling"]["spans"]
        if row["span"].startswith("inner_base_fairing:")
        and row["minimum_finite_sampled_curvature_radius_mm"] is not None
    ]
    ray_rows = report["finite_normal_ray_diagnostic"]["all_rows"]
    measured_ray_rows = [row for row in ray_rows if row.get("status") == "MEASURED_CANDIDATE_INNER_BOUNDARY_DISTANCE"]
    min_ray = min(measured_ray_rows, key=lambda row: row["first_positive_inner_boundary_hit"]["distance_mm"]) if measured_ray_rows else None
    failing_monotone_spans = [
        row["span"]
        for row in report["control_polygon_constraints"]["span_checks"]
        if not row["radius_monotone_exact"] or not row["z_nondecreasing_exact"]
    ]
    rows.append(
        {
            "name": name,
            "status": report["status"],
            "exact_constraints_pass": report["all_exact_control_constraints_pass"],
            "exact_c2_pass": report["all_non_axis_c2_exact"],
            "failed_c2_joins": [row["join"] for row in report["exact_non_axis_c2_joins"] if not row["pass_exact_rational"]],
            "failed_monotone_spans": failing_monotone_spans,
            "base_lower_sample_min_mm": min(lower_values) if lower_values else None,
            "base_span_radii_mm": [radii["outer_base_fairing:0"], radii["outer_base_fairing:1"]],
            "inner_base_fairing_sample_min_mm": min(inner_base_radii) if inner_base_radii else None,
            "first_two_side_radii_mm": [radii["outer_side:0"], radii["outer_side:1"]],
            "lip_sample_min_mm": radii["rounded_lip_bridge"],
            "ray_unknown_count": report["finite_normal_ray_diagnostic"]["unknown_count"],
            "ray_candidate_min_mm": report["finite_normal_ray_diagnostic"]["sampled_candidate_inner_boundary_distance_min_mm"],
            "ray_radial_cutoff_excluded": report["finite_normal_ray_diagnostic"]["excluded_radial_normal_dot_le_0_25_count"],
            "minimum_ray_location": ({"span": min_ray["source_span"], "t": min_ray["t"], "point_rz_mm": min_ray["point_rz_mm"], "distance_mm": min_ray["first_positive_inner_boundary_hit"]["distance_mm"], "hit": min_ray["first_positive_inner_boundary_hit"]} if min_ray else None),
        }
    )

print(json.dumps(rows, indent=2, ensure_ascii=False))
