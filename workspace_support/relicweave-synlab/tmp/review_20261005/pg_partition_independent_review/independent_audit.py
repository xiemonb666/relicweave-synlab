#!/usr/bin/env python3
"""Independent, read-only audit of the copied PG-Frag toy endpoint fixture.

The only writes are independent_audit.json and independent_audit.md beside
this script. The source fixture is read as bytes and never modified.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
SOURCE_ROOT = REPO_ROOT / "relicweave-synlab/tests/fixtures/pgfrag/result_v1_toy_endpoint"

SOURCE_FILES = [
    "job.json",
    "output/result.json",
    "output/data_dictionary.json",
    "output/points.csv",
    "output/components.csv",
    "output/bond_states.csv",
    "output/broken_bonds.csv",
    "output/isolated_points.csv",
]


def read_bytes(relative: str) -> bytes:
    return (SOURCE_ROOT / relative).read_bytes()


def read_json(relative: str) -> dict[str, Any]:
    return json.loads(read_bytes(relative).decode("utf-8"))


def read_csv(relative: str) -> list[dict[str, str]]:
    raw = read_bytes(relative)
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"), newline="")))


class UnionFind:
    def __init__(self, values: list[int]) -> None:
        self.parent = {value: value for value in values}
        self.rank = {value: 0 for value in values}

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        a, b = self.find(left), self.find(right)
        if a == b:
            return
        if self.rank[a] < self.rank[b]:
            a, b = b, a
        self.parent[b] = a
        if self.rank[a] == self.rank[b]:
            self.rank[a] += 1


def norm_partition(labels: dict[int, Any], point_ids: list[int]) -> list[tuple[int, ...]]:
    buckets: dict[Any, list[int]] = defaultdict(list)
    for point_id in point_ids:
        buckets[labels[point_id]].append(point_id)
    return sorted((tuple(sorted(members)) for members in buckets.values()), key=lambda x: x[0])


def partition_witness(left: dict[int, Any], right: dict[int, Any], point_ids: list[int]) -> dict[str, Any] | None:
    """Return a point-pair whose same/different relation differs."""
    ids = sorted(point_ids)
    for index, first in enumerate(ids):
        for second in ids[index + 1 :]:
            left_same = left[first] == left[second]
            right_same = right[first] == right[second]
            if left_same != right_same:
                return {
                    "point_pair": [first, second],
                    "left_same_component": left_same,
                    "right_same_component": right_same,
                }
    return None


def bounds(rows: list[dict[str, str]], suffix: str) -> dict[str, Any]:
    names = [f"{axis}_{suffix}_m" for axis in "xyz"]
    result: dict[str, Any] = {}
    for axis, name in zip("xyz", names):
        values = [float(row[name]) for row in rows]
        result[axis] = {
            "min_m": min(values),
            "max_m": max(values),
            "extent_m": max(values) - min(values),
            "min_mm": min(values) * 1000.0,
            "max_mm": max(values) * 1000.0,
            "extent_mm": (max(values) - min(values)) * 1000.0,
        }
    return result


def main() -> None:
    hashes: dict[str, dict[str, Any]] = {}
    for relative in SOURCE_FILES:
        raw = read_bytes(relative)
        hashes[relative] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    job = read_json("job.json")
    result = read_json("output/result.json")
    dictionary = read_json("output/data_dictionary.json")
    points_raw = read_csv("output/points.csv")
    components_raw = read_csv("output/components.csv")
    bonds_raw = read_csv("output/bond_states.csv")
    broken_raw = read_csv("output/broken_bonds.csv")
    isolated_raw = read_csv("output/isolated_points.csv")

    point_id_rows = [int(row["point_id"]) for row in points_raw]
    component_id_rows = [int(row["point_id"]) for row in components_raw]
    points = {int(row["point_id"]): row for row in points_raw}
    components = {int(row["point_id"]): row for row in components_raw}
    point_ids = sorted(points)
    expected_ids = list(range(1, len(points) + 1))

    declared_output_hashes = {item["path"]: item for item in result.get("outputs", [])}
    manifest_checks: dict[str, Any] = {}
    for rel in SOURCE_FILES:
        if not rel.startswith("output/") or rel == "output/result.json":
            continue
        output_name = rel.split("/", 1)[1]
        declared = declared_output_hashes.get(output_name)
        actual = hashes[rel]
        manifest_checks[rel] = {
            "present_in_result_manifest": declared is not None,
            "declared_bytes": declared.get("bytes") if declared else None,
            "actual_bytes": actual["bytes"],
            "declared_sha256": declared.get("sha256") if declared else None,
            "actual_sha256": actual["sha256"],
            "bytes_match": bool(declared and declared.get("bytes") == actual["bytes"]),
            "sha256_match": bool(declared and declared.get("sha256") == actual["sha256"]),
        }

    output_hash_bind_ok = all(x["bytes_match"] and x["sha256_match"] for x in manifest_checks.values())
    job_hash_matches_result = hashes["job.json"]["sha256"] == result.get("input", {}).get("job_sha256")

    # Inspect the actual declared unit/frame metadata for the columns used below.
    used_columns = {
        "points.csv": ["point_id", "x_ref_m", "y_ref_m", "z_ref_m", "x_current_m", "y_current_m", "z_current_m", "n_active_bonds", "mass_kg", "volume_m3", "damage", "intact_bond_component_id"],
        "components.csv": ["point_id", "component_id", "point_mass_kg"],
        "bond_states.csv": ["point_i_global", "point_j_global", "active", "reference_length_m", "current_length_m"],
        "broken_bonds.csv": ["point_i_global", "point_j_global", "reference_length_m", "current_length_m"],
        "isolated_points.csv": ["point_id", "x_ref_m", "y_ref_m", "z_ref_m", "mass_kg"],
    }
    column_metadata: dict[str, dict[str, dict[str, Any]]] = {}
    for table, names in used_columns.items():
        cols = dictionary["tables"][table]["columns"]
        column_metadata[table] = {name: {"dtype": cols[name]["dtype"], "unit": cols[name]["unit"], "frame": cols[name]["frame"]} for name in names}

    uf = UnionFind(point_ids)
    degree = {point_id: 0 for point_id in point_ids}
    original_degree = {point_id: 0 for point_id in point_ids}
    inactive_incident = {point_id: 0 for point_id in point_ids}
    bond_pairs: set[tuple[int, int]] = set()
    inactive_pairs: set[tuple[int, int]] = set()
    active_pairs: set[tuple[int, int]] = set()
    bond_lengths: dict[tuple[int, int], tuple[float, float]] = {}
    bond_errors: list[dict[str, Any]] = []
    for row_number, row in enumerate(bonds_raw, start=2):
        i = int(row["point_i_global"])
        j = int(row["point_j_global"])
        key = (i, j)
        active_token = row["active"]
        active = active_token == "true"
        if i >= j or i not in points or j not in points:
            bond_errors.append({"row": row_number, "pair": [i, j], "reason": "invalid/noncanonical endpoint IDs"})
            continue
        if active_token not in {"true", "false"}:
            bond_errors.append({"row": row_number, "pair": [i, j], "reason": f"invalid active token: {active_token!r}"})
            continue
        if key in bond_pairs:
            bond_errors.append({"row": row_number, "pair": [i, j], "reason": "duplicate canonical pair"})
        bond_pairs.add(key)
        bond_lengths[key] = (float(row["reference_length_m"]), float(row["current_length_m"]))
        original_degree[i] += 1
        original_degree[j] += 1
        if active:
            active_pairs.add(key)
            degree[i] += 1
            degree[j] += 1
            uf.union(i, j)
        else:
            inactive_pairs.add(key)
            inactive_incident[i] += 1
            inactive_incident[j] += 1

    graph_root = {point_id: uf.find(point_id) for point_id in point_ids}
    graph_groups: dict[int, list[int]] = defaultdict(list)
    for point_id, root in graph_root.items():
        graph_groups[root].append(point_id)
    graph_partition = sorted((tuple(sorted(members)) for members in graph_groups.values()), key=lambda x: x[0])

    point_labels = {point_id: int(row["intact_bond_component_id"]) for point_id, row in points.items()}
    component_labels = {point_id: int(row["component_id"]) for point_id, row in components.items()}
    graph_partition_set = {frozenset(group) for group in graph_partition}
    point_partition = norm_partition(point_labels, point_ids)
    component_partition = norm_partition(component_labels, point_ids)
    point_partition_set = {frozenset(group) for group in point_partition}
    component_partition_set = {frozenset(group) for group in component_partition}
    point_vs_graph_match = point_partition_set == graph_partition_set
    components_vs_graph_match = component_partition_set == graph_partition_set
    point_vs_components_match = point_partition_set == component_partition_set

    degree_mismatches = [
        {"point_id": point_id, "points_csv_n_active_bonds": int(points[point_id]["n_active_bonds"]), "recomputed_active_degree": degree[point_id]}
        for point_id in point_ids
        if int(points[point_id]["n_active_bonds"]) != degree[point_id]
    ]
    inactive_keys_from_broken: set[tuple[int, int]] = set()
    broken_length_mismatches: list[dict[str, Any]] = []
    for row_number, row in enumerate(broken_raw, start=2):
        i, j = int(row["point_i_global"]), int(row["point_j_global"])
        key = (i, j)
        inactive_keys_from_broken.add(key)
        if key not in bond_lengths:
            broken_length_mismatches.append({"row": row_number, "pair": [i, j], "reason": "pair absent from bond_states.csv"})
            continue
        ref, cur = bond_lengths[key]
        if float(row["reference_length_m"]) != ref or float(row["current_length_m"]) != cur:
            broken_length_mismatches.append({"row": row_number, "pair": [i, j], "reason": "length values differ from bond_states.csv"})

    broken_missing = sorted(inactive_pairs - inactive_keys_from_broken)
    broken_extra = sorted(inactive_keys_from_broken - inactive_pairs)
    zero_degree_ids = sorted(point_id for point_id, count in degree.items() if count == 0)
    isolated_ids = sorted(int(row["point_id"]) for row in isolated_raw)
    isolated_metadata_mismatches: list[dict[str, Any]] = []
    for row in isolated_raw:
        point_id = int(row["point_id"])
        if point_id not in points:
            isolated_metadata_mismatches.append({"point_id": point_id, "reason": "absent from points.csv"})
            continue
        point = points[point_id]
        for axis in "xyz":
            if float(row[f"{axis}_ref_m"]) != float(point[f"{axis}_ref_m"]):
                isolated_metadata_mismatches.append({"point_id": point_id, "field": f"{axis}_ref_m"})
        if float(row["mass_kg"]) != float(point["mass_kg"]):
            isolated_metadata_mismatches.append({"point_id": point_id, "field": "mass_kg"})

    total_mass_points = sum(float(row["mass_kg"]) for row in points_raw)
    total_mass_components = sum(float(row["point_mass_kg"]) for row in components_raw)
    total_volume = sum(float(row["volume_m3"]) for row in points_raw)
    rho = float(job["material"]["rho_kg_m3"])
    mass_residuals = [
        {"point_id": point_id, "mass_kg": float(points[point_id]["mass_kg"]), "rho_times_volume_kg": rho * float(points[point_id]["volume_m3"])}
        for point_id in point_ids
        if not math.isclose(float(points[point_id]["mass_kg"]), rho * float(points[point_id]["volume_m3"]), rel_tol=1e-12, abs_tol=1e-18)
    ]
    metadata_mass_mismatches = [
        {"point_id": point_id, "points_mass_kg": float(points[point_id]["mass_kg"]), "components_mass_kg": float(components[point_id]["point_mass_kg"])}
        for point_id in point_ids
        if float(points[point_id]["mass_kg"]) != float(components[point_id]["point_mass_kg"])
    ]

    damage_formula_mismatches = []
    for point_id in point_ids:
        initial = original_degree[point_id]
        expected_damage = inactive_incident[point_id] / initial if initial else 0.0
        actual_damage = float(points[point_id]["damage"])
        if not math.isclose(actual_damage, expected_damage, rel_tol=1e-12, abs_tol=1e-15):
            damage_formula_mismatches.append({"point_id": point_id, "damage": actual_damage, "inactive_incident": inactive_incident[point_id], "initial_degree": initial, "recomputed_ratio": expected_damage})

    # Component-level independent summaries retain singleton components.
    group_summaries: list[dict[str, Any]] = []
    for group_index, members in enumerate(graph_partition, start=1):
        group_rows = [points[point_id] for point_id in members]
        group_summaries.append({
            "ordinal_by_min_point_id": group_index,
            "point_count": len(members),
            "min_point_id": min(members),
            "max_point_id": max(members),
            "sample_first_12_point_ids": list(members[:12]),
            "point_mass_sum_kg": sum(float(row["mass_kg"]) for row in group_rows),
            "reference_bbox_m": bounds(group_rows, "ref"),
            "current_bbox_m": bounds(group_rows, "current"),
            "declared_points_labels": sorted({point_labels[point_id] for point_id in members}),
            "declared_components_labels": sorted({component_labels[point_id] for point_id in members}),
        })

    degree_histogram = dict(sorted(Counter(degree.values()).items()))
    inactive_incident_histogram = dict(sorted(Counter(inactive_incident.values()).items()))
    declared_state = result.get("state", {})
    summary = {
        "source_files": hashes,
        "result_manifest_checks": manifest_checks,
        "source_binding_checks": {
            "all_declared_output_files_match_copied_bytes": output_hash_bind_ok,
            "copied_job_sha256_matches_result_input_declaration": job_hash_matches_result,
            "result_json_self_sha256": hashes["output/result.json"]["sha256"],
        },
        "dataset": {
            "job_id": job.get("job_id"),
            "job_initial_condition": job.get("initial_condition"),
            "material_model": job.get("material", {}).get("model"),
            "calibration_status": job.get("material", {}).get("calibration_status"),
            "point_count": len(points_raw),
            "points_ids_complete_1_based": len(points) == len(points_raw) and point_ids == expected_ids,
            "canonical_bond_rows": len(bonds_raw),
            "active_bond_rows": len(active_pairs),
            "inactive_bond_rows": len(inactive_pairs),
            "broken_bond_rows": len(broken_raw),
            "isolated_point_rows": len(isolated_raw),
            "zero_active_degree_points": len(zero_degree_ids),
            "graph_component_count_including_singletons": len(graph_partition),
            "declared_result_state": {
                "point_count": declared_state.get("point_count"),
                "canonical_initial_bond_pairs": declared_state.get("canonical_initial_bond_pairs"),
                "broken_bond_pairs_at_endpoint": declared_state.get("broken_bond_pairs_at_endpoint"),
                "intact_bond_graph_component_count": declared_state.get("intact_bond_graph_component_count"),
            },
            "degree_histogram_active_per_point": degree_histogram,
            "degree_min": min(degree.values()) if degree else None,
            "degree_max": max(degree.values()) if degree else None,
            "degree_mean": sum(degree.values()) / len(degree) if degree else None,
            "inactive_incident_histogram_per_point": inactive_incident_histogram,
            "total_point_volume_m3": total_volume,
            "total_mass_points_kg": total_mass_points,
            "total_mass_components_kg": total_mass_components,
            "mass_sum_delta_kg": total_mass_points - total_mass_components,
            "mass_vs_rho_times_volume_mismatches": len(mass_residuals),
            "reference_bbox": bounds(points_raw, "ref"),
            "current_bbox": bounds(points_raw, "current"),
            "components": group_summaries,
        },
        "checks": {
            "point_roster_complete_unique_1_to_N": {"pass": len(point_id_rows) == len(set(point_id_rows)) and point_ids == expected_ids, "witness": None if len(point_id_rows) == len(set(point_id_rows)) and point_ids == expected_ids else {"observed_first_last": [point_ids[:5], point_ids[-5:]], "row_count": len(point_id_rows), "unique_count": len(set(point_id_rows)), "expected_count": len(points_raw)}},
            "canonical_bond_endpoints_valid_unique": {"pass": not bond_errors and len(bond_pairs) == len(bonds_raw), "witnesses": bond_errors[:5]},
            "components_csv_partition_equals_union_find": {"pass": components_vs_graph_match, "declared_component_count": len(component_partition), "recomputed_component_count": len(graph_partition), "pair_witness": partition_witness(component_labels, graph_root, point_ids)},
            "points_csv_partition_equals_union_find": {"pass": point_vs_graph_match, "declared_component_count": len(point_partition), "recomputed_component_count": len(graph_partition), "pair_witness": partition_witness(point_labels, graph_root, point_ids)},
            "points_and_components_partitions_equal_allowing_label_permutation": {"pass": point_vs_components_match, "literal_labels_equal_at_every_point": all(point_labels[x] == component_labels[x] for x in point_ids), "pair_witness": partition_witness(point_labels, component_labels, point_ids)},
            "points_active_degree_matches_active_bond_incidence": {"pass": not degree_mismatches, "mismatch_count": len(degree_mismatches), "witnesses": degree_mismatches[:10], "degree_sum_equals_twice_active_edges": sum(degree.values()) == 2 * len(active_pairs)},
            "broken_bonds_equals_exact_inactive_pair_set": {"pass": not broken_missing and not broken_extra and not broken_length_mismatches and len(inactive_keys_from_broken) == len(broken_raw), "inactive_pair_count": len(inactive_pairs), "broken_pair_count": len(inactive_keys_from_broken), "inactive_missing_from_broken_first_10": [list(x) for x in broken_missing[:10]], "unexpected_broken_pairs_first_10": [list(x) for x in broken_extra[:10]], "length_mismatch_witnesses": broken_length_mismatches[:10]},
            "isolated_roster_equals_zero_active_degree_points_including_singletons": {"pass": isolated_ids == zero_degree_ids and not isolated_metadata_mismatches, "isolated_file_ids": isolated_ids, "recomputed_zero_degree_ids": zero_degree_ids, "metadata_mismatch_witnesses": isolated_metadata_mismatches[:10]},
            "component_metadata_mass_equals_points_mass": {"pass": not metadata_mass_mismatches, "mismatch_count": len(metadata_mass_mismatches), "witnesses": metadata_mass_mismatches[:10]},
            "point_mass_equals_job_density_times_volume": {"pass": not mass_residuals, "mismatch_count": len(mass_residuals), "witnesses": mass_residuals[:10]},
            "damage_equals_endpoint_inactive_incident_fraction_empirically": {"pass": not damage_formula_mismatches, "mismatch_count": len(damage_formula_mismatches), "witnesses": damage_formula_mismatches[:10], "formula_status": "independent empirical check; dictionary calls damage upstream material-model point damage"},
            "result_declared_state_counts_match_independent_counts": {
                "pass": declared_state.get("point_count") == len(points_raw) and declared_state.get("canonical_initial_bond_pairs") == len(bonds_raw) and declared_state.get("broken_bond_pairs_at_endpoint") == len(broken_raw) and declared_state.get("intact_bond_graph_component_count") == len(graph_partition),
                "independently_recomputed": {"points": len(points_raw), "bonds": len(bonds_raw), "inactive": len(inactive_pairs), "components": len(graph_partition)},
                "declared": {"points": declared_state.get("point_count"), "bonds": declared_state.get("canonical_initial_bond_pairs"), "inactive": declared_state.get("broken_bond_pairs_at_endpoint"), "components": declared_state.get("intact_bond_graph_component_count")},
            },
        },
        "limitations": [
            "This input is explicitly a uniform_box_bar_fixture with UNVALIDATED_PROTOTYPE material calibration; it has no physical forge geometry and grants no physical-fragment qualification.",
            "An intact-bond graph connected component is a graph partition only; it does not establish a rigid or transferable fragment.",
            "Endpoint inactive bond pairs do not provide fracture event times, positive-area crack faces, paired-surface lineage, contact state, or historical R2 adjacency.",
            "This audit checks copied source bytes and recomputes the declared endpoint graph partition; it does not validate fracture mechanics, calibration, energy completeness, general timestep stability, or geometry/mesh fitness.",
        ],
    }

    (SCRIPT_DIR / "independent_audit.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    checks = summary["checks"]
    failed = [name for name, item in checks.items() if not item["pass"]]
    count = summary["dataset"]
    manifest_failed = [name for name, item in manifest_checks.items() if not item["bytes_match"] or not item["sha256_match"]]
    lines = [
        "# Independent PG-Frag endpoint partition audit",
        "",
        "This report analyzes only the copied toy endpoint fixture. It independently rebuilds the graph with union-find over all active canonical bonds, initializes every point (so isolates remain singleton components), and compares partitions as sets of point IDs. Label numbers are allowed to differ.",
        "",
        "## Finding",
        "",
        f"Independent reconstruction found **{count['graph_component_count_including_singletons']} intact-bond graph components** from {count['point_count']} points and {count['active_bond_rows']} active edges. `components.csv` partition match: **{checks['components_csv_partition_equals_union_find']['pass']}**; `points.csv` partition match: **{checks['points_csv_partition_equals_union_find']['pass']}**; both declared partitions agree with each other allowing label renumbering: **{checks['points_and_components_partitions_equal_allowing_label_permutation']['pass']}**.",
        "",
        f"The graph contains {count['canonical_bond_rows']} canonical pairs total: {count['active_bond_rows']} active and {count['inactive_bond_rows']} inactive. `broken_bonds.csv` independently matches the inactive pair set and lengths: **{checks['broken_bonds_equals_exact_inactive_pair_set']['pass']}**. Recomputed active degrees match all point declarations: **{checks['points_active_degree_matches_active_bond_incidence']['pass']}**. Zero-degree points: {count['zero_active_degree_points']}; isolated roster check: **{checks['isolated_roster_equals_zero_active_degree_points_including_singletons']['pass']}**.",
        "",
        f"Point mass sums to {count['total_mass_points_kg']:.17g} kg (components table {count['total_mass_components_kg']:.17g} kg; delta {count['mass_sum_delta_kg']:.3g} kg), and point volume sums to {count['total_point_volume_m3']:.17g} m³. Point mass equals job density × volume at every point: **{checks['point_mass_equals_job_density_times_volume']['pass']}**.",
        "",
        f"The copied job hash matches the result declaration: **{job_hash_matches_result}**. All copied table/dictionary bytes match `result.json` output manifest: **{output_hash_bind_ok}**. Full byte counts and SHA-256 digests for all eight inputs are in `independent_audit.json`.",
        "",
        "## Independently reconstructed components",
        "",
        "Component rows below are graph partitions ordered by minimum point ID; bounds are in the dictionary's right-handed z-up frame. These are endpoint graph components, not physical fragments.",
        "",
        "| Graph component | Points | Point IDs | Mass (kg) | Reference bbox (mm) | Current bbox (mm) | Declared point labels | Declared component labels |",
        "|---:|---:|---|---:|---|---|---|---|",
    ]
    for item in count["components"]:
        ref = item["reference_bbox_m"]
        cur = item["current_bbox_m"]
        def bbox_text(box: dict[str, Any]) -> str:
            return "; ".join(f"{axis} {box[axis]['min_mm']:.6g}…{box[axis]['max_mm']:.6g}" for axis in "xyz")
        lines.append(
            f"| {item['ordinal_by_min_point_id']} | {item['point_count']} | {item['min_point_id']}–{item['max_point_id']} | {item['point_mass_sum_kg']:.9g} | {bbox_text(ref)} | {bbox_text(cur)} | {item['declared_points_labels']} | {item['declared_components_labels']} |"
        )
    lines += [
        "",
        "## Coordinate extents and independent checks",
        "",
        "Coordinates are reported in meters in the JSON; table values above use millimeters only for readability. Point columns state `x/y/z_ref_m` and `x/y/z_current_m` in `right_handed_z_up` frame.",
        "",
        f"Active degree histogram: `{json.dumps(count['degree_histogram_active_per_point'], separators=(',', ':'))}`; inactive incident-pair histogram: `{json.dumps(count['inactive_incident_histogram_per_point'], separators=(',', ':'))}`.",
        "",
        f"The independent inactive-incidence fraction equals the emitted damage at every point: **{checks['damage_equals_endpoint_inactive_incident_fraction_empirically']['pass']}**. The dictionary describes damage as upstream material-model point damage; this is an observed consistency check, not a claim that the dictionary specifies this exact formula.",
        "",
        "The dictionary's actual selected fields and units are: `points.csv` uses point IDs/component IDs and bond counts as unit `1`, reference/current xyz in `m`, xyz velocity in `m/s`, damage in `1`, strain-energy density in `J/m³`, volume in `m³`, and mass in `kg`; its coordinate and velocity frame is `right_handed_z_up`. `components.csv` has `component_id` in `1`, point mass in `kg`, damage in `1`. `bond_states.csv` and `broken_bonds.csv` use endpoint IDs in `1` and reference/current lengths in `m`; the active flag is boolean in `1`. `isolated_points.csv` uses point ID in `1`, reference xyz in `m`, and mass in `kg`.",
        "",
        f"Checks failing: {failed if failed else 'none'}. Output manifest mismatches: {manifest_failed if manifest_failed else 'none'}.",
        "",
        "## Reader gap and scope",
        "",
        "The current production reader [`pgfrag_result.py`](../../../synlab/qa/source_readers/pgfrag_result.py#L573) validates source-file hashes, typed rows, degree declarations, inactive/broken-pair equality, and isolated-point membership, but it does not recompute graph connectivity or validate the intact graph component count. Its report initializes `source_binding.component_partition_validation.status` to `UNKNOWN` because connectivity is not recomputed (lines 573–575), and that field remains UNKNOWN after successful source parsing. It also requires literal per-row equality between the integer labels in `components.csv` and `points.csv` ([line 431](../../../synlab/qa/source_readers/pgfrag_result.py#L431)); this fixture happens to use the same labels, while this independent audit compares partition membership and would allow renumbering. The union-find comparison fills that bounded source-correctness check for this copied fixture only.",
        "",
        "The producer's `result.json` says validation PASS for bounded endpoint serialization, while separately labeling physical calibration pending and contact/surface/event history outside scope. This audit does not upgrade endpoint graph components into fragments, nor establish crack geometry, R2 lineage, energy completeness, calibrated physics, or forge-ready assets.",
        "",
        "## Input byte binding",
        "",
        "See `independent_audit.json` → `source_files` for all eight input byte counts and SHA-256 digests, and `result_manifest_checks` for independent output-manifest comparisons.",
    ]
    (SCRIPT_DIR / "independent_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
