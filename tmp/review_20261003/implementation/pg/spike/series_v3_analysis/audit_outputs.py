"""Independent read-only consistency audit of the immutable series_v3 outputs."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tomllib
from collections import defaultdict, deque
from pathlib import Path


HERE = Path(__file__).parent
RUNS = Path(os.environ.get("PG_SPIKE_RUNS", HERE.parent / "series_v3")).resolve()
OUTPUT_DIR = RUNS.parent / f"{RUNS.name}_analysis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_JSON = OUTPUT_DIR / f"{RUNS.name}_audit.json"
OUTPUT_CSV = OUTPUT_DIR / "damage_trajectory.csv"
ISOLATED_CSV = OUTPUT_DIR / "isolated_points.csv"
HASHES = OUTPUT_DIR / f"{RUNS.name}_sha256.txt"
SOURCE = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_run(summary_path: Path) -> dict:
    run_dir = summary_path.parent
    summary = tomllib.loads(summary_path.read_text(encoding="utf-8"))
    points = read_csv(run_dir / "points.csv")
    bond_states = read_csv(run_dir / "bond_states.csv")
    broken_rows = read_csv(run_dir / "broken_bonds.csv")
    component_rows = read_csv(run_dir / "components.csv")

    n = int(summary["n_points"])
    point_ids = [int(row["point_id"]) for row in points]
    point_id_check = len(point_ids) == n and len(set(point_ids)) == n and set(point_ids) == set(range(1, n + 1))
    mass_csv = sum(float(row["mass_kg"]) for row in points)
    mass_summary = float(summary["total_point_mass_after_kg"])

    keys = [(int(row["point_i_global"]), int(row["point_j_global"])) for row in bond_states]
    edge_unique = len(keys) == len(set(keys)) and all(i < j for i, j in keys)
    states = {(int(row["point_i_global"]), int(row["point_j_global"])): row["active"].lower() == "true"
              for row in bond_states}
    broken_set = {key for key, active in states.items() if not active}
    broken_csv_set = {(int(row["point_i_global"]), int(row["point_j_global"])) for row in broken_rows}
    broken_consistent = broken_set == broken_csv_set == set(keys) - {key for key, active in states.items() if active}

    adjacency: dict[int, list[int]] = defaultdict(list)
    degree = [0] * (n + 1)
    for (i, j), active in states.items():
        if active:
            adjacency[i].append(j)
            adjacency[j].append(i)
            degree[i] += 1
            degree[j] += 1
    isolated = [i for i in range(1, n + 1) if degree[i] == 0]
    unseen = set(range(1, n + 1))
    graph_components: list[list[int]] = []
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        queue = deque([start])
        component = []
        while queue:
            point = queue.popleft()
            component.append(point)
            for neighbor in adjacency[point]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        graph_components.append(sorted(component))
    graph_components.sort(key=lambda group: (len(group), group[0]))
    reported_groups: dict[int, list[int]] = defaultdict(list)
    for row in component_rows:
        reported_groups[int(row["component_id"])].append(int(row["point_id"]))
    reported_components = sorted((sorted(group) for group in reported_groups.values()),
                                 key=lambda group: (len(group), group[0]))
    components_match = graph_components == reported_components

    z_by_id = {int(row["point_id"]): float(row["z_ref_m"]) for row in points}
    z_min, z_max = min(z_by_id.values()), max(z_by_id.values())
    bottom = {point for point, z in z_by_id.items() if abs(z - z_min) <= 1e-12}
    top = {point for point, z in z_by_id.items() if abs(z - z_max) <= 1e-12}
    boundary_components = []
    for group in graph_components:
        if set(group) <= bottom:
            role = "bottom_prescribed_velocity_layer"
        elif set(group) <= top:
            role = "top_prescribed_velocity_layer"
        else:
            role = "interior_or_mixed"
        boundary_components.append({"size_points": len(group), "role": role,
                                    "min_point_id": min(group), "max_point_id": max(group)})

    dx_mm = float(summary["dx_m"]) * 1000.0
    ref_xyz_mm = [
        [float(row[axis]) * 1000.0 for row in points]
        for axis in ("x_ref_m", "y_ref_m", "z_ref_m")
    ]
    center_spans_mm = [max(axis) - min(axis) for axis in ref_xyz_mm]
    discrete_domain = {
        "point_center_span_mm": center_spans_mm,
        "implied_union_of_full_point_cells_mm": [span + dx_mm for span in center_spans_mm],
        "point_cell_edge_mm": dx_mm,
        "unique_lattice_points_per_axis": [len(set(axis)) for axis in ref_xyz_mm],
        "point_volume_sum_mm3": sum(float(row["volume_m3"]) for row in points) * 1e9,
        "interpretation": "Full point-cell support inferred from center extrema plus dx; no boundary partial-volume correction is applied.",
    }

    damage_finite = all(float(row["damage"]) >= 0.0 and float(row["damage"]) <= 1.0 for row in points)
    energy_finite = all(float(row["strain_energy_density_J_m3"]) >= 0.0 for row in points)
    mass_match = abs(mass_csv - mass_summary) <= max(1e-15, abs(mass_summary) * 1e-12)
    expected_broken = int(summary["broken_undirected_bond_count"])
    return {
        "case": run_dir.relative_to(RUNS).as_posix(),
        "n_points": n,
        "discrete_domain": discrete_domain,
        "time_s": float(summary["time_s"]),
        "dt_s": float(summary["dt_s"]),
        "n_steps": int(summary["n_steps"]),
        "max_damage": float(summary["max_damage"]),
        "mean_damage": float(summary["mean_damage"]),
        "damaged_point_count": int(summary["damaged_point_count"]),
        "mass_points_csv_kg": mass_csv,
        "mass_summary_kg": mass_summary,
        "strain_energy_j": float(summary["strain_energy_j"]),
        "kinetic_energy_j": float(summary["kinetic_energy_j"]),
        "canonical_undirected_bond_count": len(keys),
        "broken_pair_count_csv": len(broken_rows),
        "broken_pair_count_summary": expected_broken,
        "active_graph_component_sizes": [len(group) for group in sorted(graph_components, key=lambda g: (-len(g), g[0]))],
        "intact_bond_component_count": len(graph_components),
        "isolated_point_ids": isolated,
        "components": boundary_components,
        "checks": {
            "point_ids_complete_unique": point_id_check,
            "canonical_edges_unique_and_ordered": edge_unique,
            "broken_bond_csv_matches_native_state": broken_consistent and len(broken_rows) == expected_broken,
            "graph_components_match_solver_adapter_output": components_match,
            "point_mass_csv_matches_fixed_point_mass_sum": mass_match,
            "damage_in_range": damage_finite,
            "strain_energy_density_finite_nonnegative": energy_finite,
            "two_directed_bond_states_equal": "PASS_BY_RUNNER_ASSERTION; each canonical pair had exactly two reciprocal states and mismatch aborts the run",
            "canonical_active_rule": "The runner accepts a pair only after reciprocal states compare equal; either directed state is therefore equivalent.",
        },
        "limitations": [
            "Component labels are connected components of the intact horizon-bond graph, not verified solid fragments.",
            "At high-load 50-step output, the two 36-point components are exactly the prescribed top and bottom velocity layers; do not interpret them as a ceramic fragment-size result.",
            "The regular point lattice has no reconstructed crack faces or calibrated fracture-surface roughness.",
            "Point-mass equality is a structural CSV/ID check; mass is fixed by construction and no independent conservation solver was tested.",
            "Total-energy conservation is UNKNOWN because prescribed velocity boundaries do external work and this spike has no full energy ledger.",
            "Mechanics parameters are UNVALIDATED_PROTOTYPE; this is solver-path evidence, not calibrated physical realism.",
        ],
    }


def main() -> None:
    summary_paths = sorted(RUNS.rglob("summary.toml"))
    results = [audit_run(path) for path in summary_paths if path.parent.name != "h1p5_auto_dt_probe"]
    by_case = {result["case"]: result for result in results}
    zero = by_case["zero_h1"]
    low = by_case["low_load_h1"]
    high = by_case["high_load_h1/steps_50"]
    fine = by_case["high_load_h1_dt_half"]
    coarse = by_case["high_load_h1p5_same_time"]
    high_curve = [by_case[f"high_load_h1/steps_{steps}"] for steps in (5, 10, 20, 35, 50)]
    baseline_duration = float(zero["time_s"])
    exact_dt_half = (fine["n_steps"] == 2 * high["n_steps"] and
                     abs(fine["dt_s"] * 2 - high["dt_s"]) <= high["dt_s"] * 1e-12 and
                     abs(fine["time_s"] - high["time_s"]) <= baseline_duration * 1e-12)
    high_vs_low_response = high["max_damage"] > low["max_damage"] and high["broken_pair_count_csv"] > low["broken_pair_count_csv"]
    fine_support = high["discrete_domain"]["implied_union_of_full_point_cells_mm"]
    coarse_support = coarse["discrete_domain"]["implied_union_of_full_point_cells_mm"]
    same_discrete_support = all(abs(a - b) <= 1e-9 for a, b in zip(fine_support, coarse_support))
    h_sensitivity = {
        "requested_uniform_box_dimensions_mm": [6.0, 6.0, 16.0],
        "same_discrete_support_domain": same_discrete_support,
        "fine_implied_point_cell_support_mm": fine_support,
        "coarse_implied_point_cell_support_mm": coarse_support,
        "fine_point_volume_sum_mm3": high["discrete_domain"]["point_volume_sum_mm3"],
        "coarse_point_volume_sum_mm3": coarse["discrete_domain"]["point_volume_sum_mm3"],
        "point_volume_difference_fraction_of_fine": (coarse["discrete_domain"]["point_volume_sum_mm3"] /
                                                       high["discrete_domain"]["point_volume_sum_mm3"] - 1.0),
        "same_horizon_m": 0.003,
        "same_time_s": [high["time_s"], coarse["time_s"]],
        "fine_spacing_m": 0.001,
        "coarse_spacing_m": 0.0015,
        "fine_max_damage": high["max_damage"],
        "coarse_max_damage": coarse["max_damage"],
        "fine_broken_pairs": high["broken_pair_count_csv"],
        "coarse_broken_pairs": coarse["broken_pair_count_csv"],
        "status": "FAIL: the requested box dimensions match, but uniform_box truncates the lattice differently; the actual point-cell supports and point-volume sums differ, so this is not a controlled same-domain spacing comparison.",
    }

    trajectory = OUTPUT_CSV
    with trajectory.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case", "time_s", "dt_s", "steps", "max_damage", "mean_damage",
                         "damaged_points", "broken_pairs", "intact_graph_components",
                         "component_sizes_points", "kinetic_energy_j", "strain_energy_j"])
        for result in results:
            writer.writerow([result["case"], result["time_s"], result["dt_s"], result["n_steps"],
                             result["max_damage"], result["mean_damage"], result["damaged_point_count"],
                             result["broken_pair_count_csv"], result["intact_bond_component_count"],
                             ";".join(map(str, result["active_graph_component_sizes"])),
                             result["kinetic_energy_j"], result["strain_energy_j"]])

    isolated_path = ISOLATED_CSV
    with isolated_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case", "point_id", "reference_x_m", "reference_y_m", "reference_z_m", "point_mass_kg"])
        for result in results:
            run_dir = RUNS / result["case"]
            for point_id in result["isolated_point_ids"]:
                row = next(row for row in read_csv(run_dir / "points.csv") if int(row["point_id"]) == point_id)
                writer.writerow([result["case"], point_id, row["x_ref_m"], row["y_ref_m"], row["z_ref_m"], row["mass_kg"]])

    inputs = []
    for path in sorted(p for p in RUNS.rglob("*") if p.is_file()):
        inputs.append({"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size})
    code_files = [
        SOURCE / "bar_tension.jl",
        SOURCE / "bar_tension_series.jl",
        SOURCE / "make_bar_preview.py",
    ]
    code_hashes = [{"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size}
                   for path in code_files]
    HASHES.write_text("\n".join(f"{entry['sha256']}  {entry['path']}" for entry in inputs + code_hashes) + "\n",
                      encoding="utf-8")

    audit = {
        "title": "Peridynamics.jl headless tensile-bar functional spike output audit",
        "backend_id": "peridynamics_jl_headless_0_5_4",
        "backend_version": "0.5.4+pgfrag.1",
        "raw_run_directory": str(RUNS.resolve()),
        "raw_run_outputs_immutable_after_hash_manifest": True,
        "requested_uniform_box_dimensions_mm": [6.0, 6.0, 16.0],
        "material": {"rho_kg_m3": 1000.0, "E_pa": 1000000.0, "nu": 0.25, "Gc_j_m2": 1.0,
                     "calibration_status": "UNVALIDATED_PROTOTYPE"},
        "fixtures": results,
        "assessments": {
            "zero_load_no_damage_or_broken_bonds": {
                "status": "PASS" if zero["max_damage"] == 0 and zero["broken_pair_count_csv"] == 0 else "FAIL",
                "max_damage": zero["max_damage"], "broken_pairs": zero["broken_pair_count_csv"],
            },
            "increased_load_increased_damage_response": {
                "status": "PASS" if high_vs_low_response else "FAIL",
                "low_speed_m_s": 0.1, "low_max_damage": low["max_damage"],
                "low_broken_pairs": low["broken_pair_count_csv"], "high_speed_m_s": 0.5,
                "high_max_damage": high["max_damage"], "high_broken_pairs": high["broken_pair_count_csv"],
            },
            "high_load_damage_and_bond_snapshots": [{
                "time_s": item["time_s"], "steps": item["n_steps"],
                "max_damage": item["max_damage"], "broken_pairs": item["broken_pair_count_csv"],
                "active_graph_component_sizes": item["active_graph_component_sizes"],
            } for item in high_curve],
            "dt_half_same_physical_duration": {
                "status": "PASS" if exact_dt_half else "FAIL",
                "baseline_steps": high["n_steps"], "baseline_dt_s": high["dt_s"],
                "fine_steps": fine["n_steps"], "fine_dt_s": fine["dt_s"],
                "baseline_time_s": high["time_s"], "fine_time_s": fine["time_s"],
                "baseline_damage": high["max_damage"], "fine_damage": fine["max_damage"],
                "baseline_broken_pairs": high["broken_pair_count_csv"],
                "fine_broken_pairs": fine["broken_pair_count_csv"],
                "interpretation": "Numerical response is close but not identical; this is a small timestep sensitivity check, not a convergence proof.",
            },
            "spacing_sensitivity": h_sensitivity,
            "native_bond_extraction": {
                "status": "PASS_FOR_THIS_SINGLE_CHUNK_SPIKE",
                "rule": "Native BondSystem directed endpoints map through chunk_handler.point_ids; each undirected pair must have exactly two reciprocal entries with equal bond_active state; emit one sorted (global_i,global_j) row; active graph uses the common reciprocal state.",
                "directed_state_mismatch_behavior": "abort before writing result summary",
                "all_isolated_point_ids_csv": str(isolated_path.resolve()),
            },
            "physical_fracture_realism": {
                "status": "PENDING_WITH_REASON",
                "reason": "This is a homogeneous regular point-lattice bar with toy uncalibrated parameters. It produces emergent bond failure and an intact-bond graph, but no resolved physical crack surface, material microstructure, contact, or real ceramic calibration.",
                "boundary_note": "At the high-load 50-step endpoint, component IDs 1 and 3 (36 points each) are exactly the imposed bottom/top velocity boundary layers. They are boundary-separation artifacts and must not be interpreted as a ceramic fragment distribution.",
            },
            "mass_and_energy": {
                "point_mass_csv_match": "STRUCTURAL_CHECK_ONLY: all IDs are complete and unique and CSV point mass sums to fixed model mass.",
                "independent_mass_conservation": "UNKNOWN",
                "strain_energy_density": "Computed via upstream Peridynamics.export_field(:strain_energy_density) after solve; loaded samples report finite nonzero values.",
                "total_energy_conservation": "UNKNOWN: prescribed velocity boundaries do external work; no full ledger audit in this spike.",
            },
            "other_capabilities": {
                "contact": "NOT_EXERCISED_IN_THIS_SPIKE",
                "GPU": "NOT_IMPLEMENTED/UNSUPPORTED_BY_THIS_BACKEND_ADAPTER",
                "crack_surface_and_A12_R2": "UNKNOWN/NOT_EMITTED; broken horizon interactions are not historical contact or R2.",
            },
        },
        "visuals": {
            "contact_sheet": str((RUNS / "bar_point_state_preview.png").resolve()),
            "high_load_detail": str((RUNS / "bar_high_load_50_detail.png").resolve()),
            "visual_semantics": "x-z projection of one material-reference y layer; current positions, per-point damage, intact-bond components, or z displacement; point symbols only, not a reconstructed surface. The dx=1.5 mm row has a 15 mm implied z point-cell support and 540 mm3 point-volume sum versus 16 mm and 576 mm3 for dx=1 mm, so nominal requested dimensions do not imply matched delivered domains.",
        },
        "raw_file_hash_manifest": str(HASHES.resolve()),
        "raw_files": inputs,
        "source_scripts": code_hashes,
    }
    OUTPUT_JSON.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT_JSON.resolve())
    print(OUTPUT_CSV.resolve())
    print(ISOLATED_CSV.resolve())
    print(HASHES.resolve())


if __name__ == "__main__":
    main()
