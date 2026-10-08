import csv
import hashlib
import json
import math
import tomllib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
CASE_NAMES = ("contact_baseline", "contact_halfdt", "nocontact_control")
BODIES = ("a", "b")


def vec(row, prefix):
    if prefix in ("initial_v", "final_v"):
        return tuple(float(row[f"{prefix}{axis}_m_per_s"]) for axis in "xyz")
    return tuple(float(row[f"{prefix}_{axis}_m"]) for axis in "xyz")


def norm(a):
    return math.sqrt(sum(x * x for x in a))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def scale(a, k):
    return tuple(x * k for x in a)


def read_case(name):
    case_dir = ROOT / name
    with (case_dir / "summary.toml").open("rb") as stream:
        summary = tomllib.load(stream)
    with (case_dir / "execution.toml").open("rb") as stream:
        execution = tomllib.load(stream)
    with (case_dir / "points.csv").open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert summary["submit_completed"] is True
    assert summary["process_exit_code"] == 0
    assert execution["exit_code"] == 0 and execution["timed_out_at_120_seconds"] is False
    assert len(rows) == summary["total_points"] == 16
    identities = {(row["body_name"], int(row["native_point_id"])) for row in rows}
    assert len(identities) == 16
    assert {body: sum(row["body_name"] == body for row in rows) for body in BODIES} == {"a": 8, "b": 8}
    assert all(sorted(int(row["native_point_id"]) for row in rows if row["body_name"] == body) == list(range(1, 9)) for body in BODIES)
    assert all(int(row["active_peridynamic_bonds"]) + int(row["broken_peridynamic_bonds"]) == 6 for row in rows)
    assert all(int(row["broken_peridynamic_bonds"]) == 0 for row in rows)
    return {"summary": summary, "execution": execution, "rows": rows, "dir": case_dir}


def body_rows(case, body):
    return [r for r in case["rows"] if r["body_name"] == body]


def weighted_vector(rows, prefix):
    mass = sum(float(r["mass_kg"]) for r in rows)
    return scale(tuple(sum(float(r["mass_kg"]) * v[i] for r in rows for v in [vec(r, prefix)]) / mass for i in range(3)), 1.0)


def momentum(rows, prefix):
    return tuple(sum(float(r["mass_kg"]) * vec(r, prefix)[i] for r in rows) for i in range(3))


def min_cross_body_distance(rows_a, rows_b, prefix):
    best = (math.inf, None, None)
    for a in rows_a:
        pa = vec(a, prefix)
        for b in rows_b:
            distance = norm(sub(pa, vec(b, prefix)))
            if distance < best[0]:
                best = (distance, a["point_label"], b["point_label"])
    return best


cases = {name: read_case(name) for name in ("preflight",) + CASE_NAMES}
with (ROOT / "path_migration.toml").open("rb") as stream:
    migration = tomllib.load(stream)
analysis = {
    "schema": "native_contact_minimal.independent_analysis.v1",
    "analysis_method": "Independent Python CSV/TOML parsing; exact sums and Euclidean distances; no simulator re-execution.",
    "unit_note": "Momentum in kg m/s; point position and distance in m; speed in m/s; native b_int in N/m^3.",
    "case_results": {},
    "pairwise_contact_vs_control": {},
    "pairwise_baseline_vs_halfdt": {},
    "checks": {},
    "artifact_migration": {
        "execution_argv_exit_runtime_unchanged": migration["execution_argv_exit_runtime_unchanged"],
        "source_path": migration["source_path"],
        "destination_path": migration["destination_path"],
        "case_names": [record["name"] for record in migration["cases"]],
    },
    "history_limits": {
        "time_integrated_contact_impulse_Ns": None,
        "contact_energy_J": None,
        "reason": "Only initial/final point states and final b_int were exported; there is no per-step contact-force or contact-energy history. Body delta-P is not a direct contact impulse integral."
    }
}

for name, case in cases.items():
    rows_a, rows_b = body_rows(case, "a"), body_rows(case, "b")
    p0_by_body = {body: momentum(body_rows(case, body), "initial_v") for body in BODIES}
    p1_by_body = {body: momentum(body_rows(case, body), "final_v") for body in BODIES}
    dp_by_body = {body: sub(p1_by_body[body], p0_by_body[body]) for body in BODIES}
    p0 = momentum(case["rows"], "initial_v")
    p1 = momentum(case["rows"], "final_v")
    center_a = weighted_vector(rows_a, "final")
    center_b = weighted_vector(rows_b, "final")
    velocity_a = weighted_vector(rows_a, "final_v")
    velocity_b = weighted_vector(rows_b, "final_v")
    initial_distance = min_cross_body_distance(rows_a, rows_b, "rest")
    final_distance = min_cross_body_distance(rows_a, rows_b, "final")
    b_int_max = max(abs(float(r[f"b_int_{axis}_N_per_m3"])) for r in case["rows"] for axis in "xyz")
    item = {
        "step_count": case["summary"]["step_count"],
        "solver_dt_s": case["summary"]["solver_dt_s"],
        "end_time_s": case["summary"]["end_time_s"],
        "native_material_stability_bound_s": case["summary"]["native_material_stability_bound_s"],
        "native_bound_safety_multiplier": case["summary"]["stability_bound_multiplier"],
        "actual_solver_dt_over_native_material_bound": case["summary"]["solver_dt_s"] / case["summary"]["native_material_stability_bound_s"],
        "contact_enabled": case["summary"]["contact_enabled"],
        "runner_exit_code": case["execution"]["exit_code"],
        "runner_runtime_seconds": case["execution"]["runtime_seconds"],
        "point_count": len(case["rows"]),
        "unique_point_labels": len({r["point_label"] for r in case["rows"]}),
        "masses_by_body_kg": {body: sum(float(r["mass_kg"]) for r in body_rows(case, body)) for body in BODIES},
        "active_bond_counts_by_body": case["summary"]["active_bond_counts_by_body"],
        "max_abs_external_b_N_per_m3": case["summary"]["external_force_max_abs_N_per_m3"],
        "max_abs_final_native_b_int_N_per_m3": b_int_max,
        "initial_total_momentum_kg_m_per_s": p0,
        "final_total_momentum_kg_m_per_s": p1,
        "total_delta_momentum_kg_m_per_s": sub(p1, p0),
        "delta_momentum_by_body_kg_m_per_s": dp_by_body,
        "delta_momentum_opposition_residual_kg_m_per_s": norm(add(dp_by_body["a"], dp_by_body["b"])),
        "initial_min_cross_body_point_distance_m": initial_distance[0],
        "final_min_cross_body_point_distance_m": final_distance[0],
        "final_min_distance_point_labels": [final_distance[1], final_distance[2]],
        "final_center_a_z_minus_center_b_z_m": center_a[2] - center_b[2],
        "cube_cell_envelope_edge_m": case["summary"]["cube_edge_m"],
        "final_nominal_cell_envelope_gap_m": (center_a[2] - center_b[2]) - case["summary"]["cube_edge_m"],
        "final_nominal_cell_envelope_overlap_m": max(0.0, case["summary"]["cube_edge_m"] - (center_a[2] - center_b[2])),
        "final_center_relative_velocity_a_minus_b_z_m_per_s": velocity_a[2] - velocity_b[2],
        "all_exported_points_included": True,
        "point_ids_by_body": {body: sorted(int(r["native_point_id"]) for r in body_rows(case, body)) for body in BODIES},
        "process_argv": case["execution"]["argv"],
        "native_source_sha256": case["summary"]["source_hashes_sha256"]["native_contact_script"],
        "original_runtime_output_path": case["summary"]["original_runtime_output_path"],
        "current_archive_path": case["summary"]["current_archive_path"],
    }
    radius = case["summary"]["contact_radius_m"]
    if not case["summary"]["contact_enabled"]:
        item["final_contact_state_classification"] = "no_contact_control"
    elif center_a[2] - center_b[2] < 0:
        item["final_contact_state_classification"] = "body_center_order_reversed; possible pass-through"
    elif velocity_a[2] - velocity_b[2] > 0 and final_distance[0] >= radius:
        item["final_contact_state_classification"] = "rebounded_and_separated_at_final_state"
    elif velocity_a[2] - velocity_b[2] > 0:
        item["final_contact_state_classification"] = "separating_at_final_state_but_points_within_contact_radius"
    elif final_distance[0] < radius:
        item["final_contact_state_classification"] = "within_contact_radius_and_still_closing_at_final_state"
    else:
        item["final_contact_state_classification"] = "not_rebounded_by_final_state"
    analysis["case_results"][name] = item

for contact_name in ("contact_baseline", "contact_halfdt"):
    contact = cases[contact_name]
    control = cases["nocontact_control"]
    by_id_control = {(r["body_name"], int(r["native_point_id"])): r for r in control["rows"]}
    position_delta = []
    velocity_delta = []
    for row in contact["rows"]:
        other = by_id_control[(row["body_name"], int(row["native_point_id"]))]
        position_delta.append(norm(sub(vec(row, "final"), vec(other, "final"))))
        velocity_delta.append(norm(sub(vec(row, "final_v"), vec(other, "final_v"))))
    analysis["pairwise_contact_vs_control"][contact_name] = {
        "max_final_point_position_difference_m": max(position_delta),
        "max_final_point_velocity_difference_m_per_s": max(velocity_delta),
        "mean_final_point_position_difference_m": sum(position_delta) / len(position_delta),
        "mean_final_point_velocity_difference_m_per_s": sum(velocity_delta) / len(velocity_delta),
    }

base = cases["contact_baseline"]
half = cases["contact_halfdt"]
by_id_half = {(r["body_name"], int(r["native_point_id"])): r for r in half["rows"]}
pos_diff = []
vel_diff = []
for row in base["rows"]:
    other = by_id_half[(row["body_name"], int(row["native_point_id"]))]
    pos_diff.append(norm(sub(vec(row, "final"), vec(other, "final"))))
    vel_diff.append(norm(sub(vec(row, "final_v"), vec(other, "final_v"))))
analysis["pairwise_baseline_vs_halfdt"] = {
    "max_final_point_position_difference_m": max(pos_diff),
    "max_final_point_velocity_difference_m_per_s": max(vel_diff),
    "mean_final_point_position_difference_m": sum(pos_diff) / len(pos_diff),
    "mean_final_point_velocity_difference_m_per_s": sum(vel_diff) / len(vel_diff),
    "interpretation": "Reported as a timestep sensitivity comparison only; no convergence claim is made."
}

control = cases["nocontact_control"]
T = control["summary"]["end_time_s"]
free_position_errors, free_velocity_errors = [], []
for row in control["rows"]:
    r0 = vec(row, "rest")
    v0 = vec(row, "initial_v")
    predicted = add(r0, scale(v0, T))
    free_position_errors.append(norm(sub(vec(row, "final"), predicted)))
    free_velocity_errors.append(norm(sub(vec(row, "final_v"), v0)))
bound = base["summary"]["native_material_stability_bound_s"]
source_root = ROOT.parents[4]
hash_paths = {
    "native_contact_script": Path(base["summary"]["native_source_path"]),
    "vendored_contact_physics": source_root / "pgfrag/src/pgfrag/resources/julia/vendor/Peridynamics.jl/src/physics/short_range_force_contact.jl",
    "upstream_contact_unit_test": source_root / "pgfrag/vendor/Peridynamics.jl/test/unit/physics/test_short_range_force_contact.jl",
    "julia_project": source_root / "pgfrag/src/pgfrag/resources/julia/Project.toml",
    "julia_manifest": source_root / "pgfrag/src/pgfrag/resources/julia/Manifest.toml",
}
hash_checks = {}
for key, path in hash_paths.items():
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    expected = base["summary"]["source_hashes_sha256"][key]
    hash_checks[key] = actual == expected
max_total_delta_p = max(norm(item["total_delta_momentum_kg_m_per_s"]) for item in analysis["case_results"].values())
max_opposition_residual = max(item["delta_momentum_opposition_residual_kg_m_per_s"] for item in analysis["case_results"].values())
analysis["checks"] = {
    "preflight_one_step_submit_exit_zero": cases["preflight"]["execution"]["exit_code"] == 0 and cases["preflight"]["summary"]["step_count"] == 1,
    "baseline_dt_equals_half_native_bound": math.isclose(base["summary"]["solver_dt_s"], 0.5 * bound, rel_tol=1e-14),
    "halfdt_is_half_baseline_dt": math.isclose(half["summary"]["solver_dt_s"], 0.5 * base["summary"]["solver_dt_s"], rel_tol=1e-14),
    "all_three_cases_same_final_time": max(cases[n]["summary"]["end_time_s"] for n in CASE_NAMES) - min(cases[n]["summary"]["end_time_s"] for n in CASE_NAMES) < 1e-15,
    "all_three_case_processes_exit_zero_within_120s": all(cases[n]["execution"]["exit_code"] == 0 and not cases[n]["execution"]["timed_out_at_120_seconds"] for n in CASE_NAMES),
    "fixed_geometry_material_and_initial_conditions_match_request": all(
        cases[n]["summary"]["point_spacing_m"] == 2.0e-3
        and cases[n]["summary"]["horizon_m"] == 3.0e-3
        and cases[n]["summary"]["points_per_body"] == 8
        and cases[n]["summary"]["total_points"] == 16
        and cases[n]["summary"]["initial_center_a_z_m"] == 2.25e-3
        and cases[n]["summary"]["initial_center_b_z_m"] == -2.25e-3
        and cases[n]["summary"]["initial_speed_m_per_s"] == 0.2
        and cases[n]["summary"]["density_kg_per_m3"] == 1000.0
        and cases[n]["summary"]["young_modulus_Pa"] == 1.0e6
        and cases[n]["summary"]["fracture_energy_J_per_m2"] == 1.0
        and cases[n]["summary"]["poisson_ratio"] == 0.25
        and cases[n]["summary"]["no_failure"] is True
        and cases[n]["summary"]["boundary_condition_count"] == 0
        for n in CASE_NAMES
    ),
    "contact_radius_and_penalty_match_request": all(cases[n]["summary"]["contact_enabled"] and cases[n]["summary"]["contact_radius_m"] == 2.0e-3 and cases[n]["summary"]["contact_penalty_factor"] == 1.0e6 for n in ("contact_baseline", "contact_halfdt"))
        and cases["nocontact_control"]["summary"]["contact_enabled"] is False,
    "path_migration_manifest_parses_and_lists_all_four_runs": migration["execution_argv_exit_runtime_unchanged"] and set(analysis["artifact_migration"]["case_names"]) == set(("preflight",) + CASE_NAMES),
    "archived_summaries_match_migration_paths_and_original_argv": all(
        cases[name]["summary"]["current_archive_path"] == str(ROOT / name)
        and cases[name]["summary"]["original_runtime_output_path"] == migration_case["original_runtime_output_path"]
        and cases[name]["execution"]["argv"][-1] == str(migration_case["original_runtime_output_path"])
        for name in ("preflight",) + CASE_NAMES
        for migration_case in migration["cases"] if migration_case["name"] == name
    ),
    "all_five_source_hashes_match_read_only_inputs": all(hash_checks.values()),
    "source_hash_checks": hash_checks,
    "free_control_max_position_error_vs_uniform_motion_m": max(free_position_errors),
    "free_control_max_velocity_error_vs_initial_m_per_s": max(free_velocity_errors),
    "no_external_force_in_all_cases": all(cases[n]["summary"]["external_force_max_abs_N_per_m3"] == 0.0 for n in CASE_NAMES),
    "all_peridynamic_bonds_active_and_unbroken": all(all(int(r["active_peridynamic_bonds"]) > 0 and int(r["broken_peridynamic_bonds"]) == 0 for r in cases[n]["rows"]) for n in CASE_NAMES),
    "maximum_total_delta_momentum_norm_kg_m_per_s": max_total_delta_p,
    "maximum_opposite_body_delta_p_residual_kg_m_per_s": max_opposition_residual,
    "total_momentum_conserved_to_1e-18_kg_m_per_s": max_total_delta_p <= 1e-18,
    "two_body_delta_momentum_equal_and_opposite_to_1e-18_kg_m_per_s": max_opposition_residual <= 1e-18,
    "baseline_contact_differs_from_control": analysis["pairwise_contact_vs_control"]["contact_baseline"]["max_final_point_velocity_difference_m_per_s"] > 0.0,
    "nocontact_control_final_pair_distance_positive": analysis["case_results"]["nocontact_control"]["final_min_cross_body_point_distance_m"] > 0.0,
    "time_integrated_contact_impulse_and_energy": "UNKNOWN (not exported; delta-P is not a direct contact impulse integral)"
}


def draw_plot():
    width, height = 1800, 900
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.text((35, 20), "POINT_CONTACT_NUMERICAL_PROTOTYPE - initial/final point positions, x-z projection (mm)", fill="#202020", font=font)
    draw.text((35, 42), "Numerical point-contact probe only; this does not represent CAD contact or real instrument fracture.", fill="#404040", font=font)
    panel_names = CASE_NAMES
    colors = {"a": (210, 95, 35), "b": (35, 115, 180)}
    all_z = [float(r["rest_z_m"]) * 1000 for name in panel_names for r in cases[name]["rows"]]
    all_z += [float(r["final_z_m"]) * 1000 for name in panel_names for r in cases[name]["rows"]]
    z_lo = math.floor((min(all_z) - 0.4) * 2) / 2
    z_hi = math.ceil((max(all_z) + 0.4) * 2) / 2
    panel_w = 580
    plot_top, plot_bottom = 150, 790
    plot_left_offset, plot_right_offset = 85, 545
    for panel_index, name in enumerate(panel_names):
        panel_left = 25 + panel_index * 590
        plot_left, plot_right = panel_left + plot_left_offset, panel_left + plot_right_offset
        plot_height = plot_bottom - plot_top
        plot_width = plot_right - plot_left
        scale_px = min(plot_height / (z_hi - z_lo), plot_width / 4.8)
        x_mid = 0.0
        x_half_span = plot_width / (2 * scale_px)
        x_lo, x_hi = x_mid - x_half_span, x_mid + x_half_span
        summary = cases[name]["summary"]
        draw.text((panel_left + 8, 82), name.upper(), fill="#202020", font=font)
        draw.text((panel_left + 8, 102), f"{summary['step_count']} steps, dt={summary['solver_dt_s']*1e6:.3f} us", fill="#404040", font=font)

        def px(x_mm):
            return plot_left + (x_mm - x_lo) * scale_px

        def py(z_mm):
            return plot_bottom - (z_mm - z_lo) * scale_px

        for z_tick in range(math.ceil(z_lo), math.floor(z_hi) + 1):
            y = py(z_tick)
            draw.line((plot_left, y, plot_right, y), fill="#e5e5e5", width=1)
            draw.text((plot_left - 28, y - 4), str(z_tick), fill="#505050", font=font)
        for x_tick in range(math.ceil(x_lo), math.floor(x_hi) + 1):
            x = px(x_tick)
            draw.line((x, plot_top, x, plot_bottom), fill="#eeeeee", width=1)
            draw.text((x - 3, plot_bottom + 9), str(x_tick), fill="#505050", font=font)
        draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), outline="#303030", width=1)
        draw.text((panel_left + panel_w // 2 - 22, 820), "x [mm]", fill="#202020", font=font)
        draw.text((panel_left + 12, plot_top - 17), "z [mm]", fill="#202020", font=font)
        rows_by_key = {(r["body_name"], int(r["native_point_id"])): r for r in cases[name]["rows"]}
        for body in BODIES:
            color = colors[body]
            for row in body_rows(cases[name], body):
                x0, z0 = float(row["rest_x_m"]) * 1000, float(row["rest_z_m"]) * 1000
                x1, z1 = float(row["final_x_m"]) * 1000, float(row["final_z_m"]) * 1000
                p0, p1 = (px(x0), py(z0)), (px(x1), py(z1))
                draw.line((p0[0], p0[1], p1[0], p1[1]), fill=(190, 190, 190), width=1)
                draw.ellipse((p0[0]-4, p0[1]-4, p0[0]+4, p0[1]+4), outline=color, width=2)
                draw.ellipse((p1[0]-4, p1[1]-4, p1[0]+4, p1[1]+4), fill=color, outline=color)
        draw.text((panel_left + 8, 852), f"A=orange, B=blue; open=initial, filled=final; final min pair distance={analysis['case_results'][name]['final_min_cross_body_point_distance_m']*1000:.3f} mm", fill="#303030", font=font)
    image.save(ROOT / "native_contact_minimal_points_xz.png", format="PNG", optimize=True)


draw_plot()
with (ROOT / "independent_analysis.json").open("w", encoding="utf-8") as stream:
    json.dump(analysis, stream, indent=2, sort_keys=True)
    stream.write("\n")

print(json.dumps({"checks": analysis["checks"], "cases": {n: {"runtime_s": analysis["case_results"][n]["runner_runtime_seconds"], "dp_a": analysis["case_results"][n]["delta_momentum_by_body_kg_m_per_s"]["a"], "dp_b": analysis["case_results"][n]["delta_momentum_by_body_kg_m_per_s"]["b"], "total_delta_p": analysis["case_results"][n]["total_delta_momentum_kg_m_per_s"], "final_min_distance_mm": analysis["case_results"][n]["final_min_cross_body_point_distance_m"] * 1000, "center_sep_z_mm": analysis["case_results"][n]["final_center_a_z_minus_center_b_z_m"] * 1000, "cell_envelope_overlap_mm": analysis["case_results"][n]["final_nominal_cell_envelope_overlap_m"] * 1000, "relative_v_z_m_s": analysis["case_results"][n]["final_center_relative_velocity_a_minus_b_z_m_per_s"], "classification": analysis["case_results"][n]["final_contact_state_classification"]} for n in CASE_NAMES}, "baseline_vs_control": analysis["pairwise_contact_vs_control"]["contact_baseline"], "baseline_vs_halfdt": analysis["pairwise_baseline_vs_halfdt"], "png": str(ROOT / "native_contact_minimal_points_xz.png")}, indent=2))
