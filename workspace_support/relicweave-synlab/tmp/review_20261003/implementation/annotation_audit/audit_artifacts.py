from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq


ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge")
VF = ROOT / r"relicweave-synlab\tmp\review_20261003\implementation\vf\artifacts\four_bands_brep_semantics1_final"
PG = ROOT / r"relicweave-synlab\tmp\review_20261003\implementation\pg\jobs\osb_fracture_branch_001"
WHEEL = ROOT / r"relicweave-synlab\tmp\review_20261003\implementation\pg\wheel_test\jobs\wheel_osb_smoke_001"
PKG = ROOT / r"relicweave-synlab\data\a12_exports\experiment_ready\training_package"
REPORT = ROOT / r"relicweave-synlab\data\a12_exports\experiment_ready\experiment_ready_report.json"
FREEZE = ROOT / r"relicweave-synlab\data\a12_exports\trainable\next_experiment\release_freeze_blocked.json"
OUT = ROOT / r"relicweave-synlab\tmp\review_20261003\implementation\annotation_audit\artifact_audit.json"
OUT_V2 = ROOT / r"relicweave-synlab\tmp\review_20261003\implementation\annotation_audit\artifact_audit_v2.json"
LINEAGE_ID = re.compile(r"LIN\d{4}_V\d{2}_M\d{2}_PAT\d{2}")
SEMANTIC_ALIAS_KEYS = {
    "lineage", "lineage_id", "mother", "mother_id", "fragment", "fragment_id",
    "query_id", "historical_n_g", "parent", "parent_id", "event_id", "historical_r2",
}
SEMANTIC_SENSITIVE_KEYS = SEMANTIC_ALIAS_KEYS | {
    "parentid", "motherid", "fragmentid", "eventid", "seed", "seed_ref", "recipe",
    "recipe_id", "shape_parameters", "shape_params", "truth_pose", "t_wf", "t_wo",
    "t_wc", "object_pose_t_wo", "vertices_material_xyz_mm", "rest_coordinates",
    "rest_xyz", "split", "lineage_cluster", "context_id", "batch_id", "bag_id",
    "stratum_id", "excavation_area_id", "frame_id_source",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def artifact_record(path: Path) -> dict:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha(path)}


def audit_vf() -> dict:
    mpath = VF / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    semantics = json.loads((VF / manifest["provenance"]["spec"]["face_semantics_report"]).read_text(encoding="utf-8"))
    geometry_report = json.loads((VF / manifest["validation"]["report"]).read_text(encoding="utf-8"))
    dictionary = json.loads((VF / "metadata/data_dictionary.json").read_text(encoding="utf-8"))
    with np.load(VF / manifest["geometry"]["surface_npz"], allow_pickle=False) as z:
        surface = {k: np.asarray(z[k]) for k in z.files}
    with np.load(VF / manifest["fields"]["surface_fields_npz"], allow_pickle=False) as z:
        fields = {k: np.asarray(z[k]) for k in z.files}
    with np.load(VF / manifest["provenance"]["spec"]["mesh_lineage_npz"], allow_pickle=False) as z:
        lineage = {k: np.asarray(z[k]) for k in z.files}
    v, f = surface["vertices_mm"], surface["faces"]
    region = fields["face_region"]
    source_face = lineage["face_source_brep_index"]
    code_by_brep_face = np.asarray([row["region_code"] for row in semantics["faces"]], dtype=region.dtype)
    file_checks = []
    for rel, declared in sorted(manifest["files"].items()):
        p = VF / Path(*rel.split("/"))
        actual_sha = sha(p)
        file_checks.append({"path": rel, "bytes_declared": declared["bytes"], "bytes_actual": p.stat().st_size,
                            "sha256_declared": declared["sha256"], "sha256_actual": actual_sha,
                            "hash_and_size_match": p.stat().st_size == declared["bytes"] and actual_sha == declared["sha256"]})
    return {
        "package_path": str(VF.resolve()), "manifest": artifact_record(mpath), "schema": manifest.get("schema"),
        "units": manifest.get("units"), "frame": manifest.get("frame"),
        "manifest_fields": sorted(manifest), "file_checks": file_checks,
        "surface": {"vertices": int(len(v)), "faces": int(len(f)),
                    "vertex_dtype": str(v.dtype), "face_dtype": str(f.dtype),
                    "bounds_mm": [[float(x) for x in v[:, i].minmax()] for i in range(3)] if hasattr(v[:, 0], "minmax") else [[float(v[:, i].min()), float(v[:, i].max())] for i in range(3)],
                    "arrays": {k: {"shape": list(a.shape), "dtype": str(a.dtype)} for k, a in surface.items()}},
        "fields": {"arrays": {k: {"shape": list(a.shape), "dtype": str(a.dtype)} for k, a in fields.items()},
                   "region_counts": {str(int(k)): int(n) for k, n in zip(*np.unique(region, return_counts=True))},
                   "albedo_range": [float(fields["albedo_linear_rgb"].min()), float(fields["albedo_linear_rgb"].max())],
                   "roughness_range": [float(fields["roughness"].min()), float(fields["roughness"].max())],
                   "material_coordinates_equal_surface_vertices": bool(np.array_equal(fields["vertices_material_xyz_mm"], v))},
        "lineage": {"arrays": {k: {"shape": list(a.shape), "dtype": str(a.dtype)} for k, a in lineage.items()},
                    "source_face_count": len(semantics["faces"]), "triangle_source_indices_valid": bool(source_face.min() >= 0 and source_face.max() < len(semantics["faces"])),
                    "region_follows_brep_lineage": bool(np.array_equal(region, code_by_brep_face[source_face.astype(np.int64)]))},
        "material": manifest.get("material"), "ornament": manifest.get("ornament"),
        "provenance": manifest.get("provenance"),
        "semantic_report": {"path": manifest["provenance"]["spec"]["face_semantics_report"],
                            "schema": semantics.get("schema"), "status": semantics.get("status"),
                            "classifier": semantics.get("classifier"), "backend": semantics.get("backend"),
                            "canonical_step_sha256": semantics.get("canonical_step_sha256"),
                            "face_count": semantics.get("canonical_step_face_count"), "counts": semantics.get("counts"),
                            "unknown_face_indices": semantics.get("unknown_face_indices"),
                            "classification_basis_counts": dict(Counter(str(row.get("classification_basis")) for row in semantics.get("faces", [])))},
        "geometry_qa": {"scope": geometry_report.get("scope"), "status": geometry_report.get("status"),
                        "measurements": geometry_report.get("measurements"),
                        "limitations": geometry_report.get("limitations"), "checks": geometry_report.get("checks")},
        "data_dictionary": dictionary,
    }


def audit_pg_job(job_root: Path) -> dict:
    result_path = job_root / "output/result.json"
    job_path = job_root / "job.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    out = job_root / "output"
    points_fields, points = csv_rows(out / "points.csv")
    bonds_fields, bonds = csv_rows(out / "bond_states.csv")
    broken_fields, broken = csv_rows(out / "broken_bonds.csv")
    components_fields, components = csv_rows(out / "components.csv")
    isolated_fields, isolated = csv_rows(out / "isolated_points.csv")
    ids = [int(row["point_id"]) for row in points]
    mass = np.asarray([float(row["mass_kg"]) for row in points])
    volume = np.asarray([float(row["volume_m3"]) for row in points])
    degree = Counter()
    for row in bonds:
        if row["active"].lower() == "true":
            degree[int(row["point_i_global"])] += 1
            degree[int(row["point_j_global"])] += 1
    return {
        "job": artifact_record(job_path), "result": artifact_record(result_path),
        "job_schema": job.get("schema"), "result_schema": result.get("schema"),
        "result_status": result.get("status"), "backend_id": result.get("backend_id"),
        "backend_version": result.get("backend_version"), "core_version": result.get("core_version"),
        "backend_provenance": result.get("backend_provenance"),
        "input": result.get("input"), "initial_condition": result.get("initial_condition"),
        "material": result.get("material"), "units": result.get("units"), "frame": result.get("frame"),
        "solver": result.get("solver"), "state": result.get("state"), "validation": result.get("validation"),
        "missing_capabilities": result.get("missing_capabilities"),
        "tables": {
            "points.csv": {"columns": points_fields, "rows": len(points), "ids_complete_unique_1_to_n": len(set(ids)) == len(ids) and set(ids) == set(range(1, len(ids) + 1)),
                           "mass_sum_kg": float(mass.sum()), "volume_sum_mm3": float(volume.sum() * 1e9),
                           "degree_min_max": [min(degree.get(i, 0) for i in ids), max(degree.get(i, 0) for i in ids)],
                           "degree_zero_count": sum(degree.get(i, 0) == 0 for i in ids), "degree_one_count": sum(degree.get(i, 0) == 1 for i in ids),
                           "damage_range": [min(float(r["damage"]) for r in points), max(float(r["damage"]) for r in points)]},
            "bond_states.csv": {"columns": bonds_fields, "rows": len(bonds), "active_rows": sum(r["active"].lower() == "true" for r in bonds), "inactive_rows": sum(r["active"].lower() == "false" for r in bonds)},
            "broken_bonds.csv": {"columns": broken_fields, "rows": len(broken)},
            "components.csv": {"columns": components_fields, "rows": len(components), "component_point_counts": {k: v for k, v in sorted(Counter(r["component_id"] for r in components).items())},
                                 "component_mass_kg": {k: float(sum(float(r["point_mass_kg"]) for r in components if r["component_id"] == k)) for k in sorted({r["component_id"] for r in components})}},
            "isolated_points.csv": {"columns": isolated_fields, "rows": len(isolated), "retains_refcoords_mass": all(all(r.get(k) for k in ("point_id", "x_ref_m", "y_ref_m", "z_ref_m", "mass_kg")) for r in isolated)},
        },
        "output_files": [artifact_record(p) for p in sorted(out.iterdir()) if p.is_file()],
    }


def recursively_collect(node, keys: set[str], strings: list[str]):
    if isinstance(node, dict):
        for k, v in node.items():
            keys.add(str(k))
            recursively_collect(v, keys, strings)
    elif isinstance(node, list):
        for item in node:
            recursively_collect(item, keys, strings)
    elif isinstance(node, str):
        strings.append(node)


def scan_tree(node, path: str = "$", *, keys: list[dict] | None = None,
              id_occurrences: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """Collect JSON/row key and value evidence with paths; IDs in keys matter too."""
    if keys is None:
        keys = []
    if id_occurrences is None:
        id_occurrences = []
    if isinstance(node, dict):
        for raw_key, value in node.items():
            key = str(raw_key)
            key_path = f"{path}.{key}"
            keys.append({"key": key, "path": key_path})
            if LINEAGE_ID.search(key):
                id_occurrences.append({"source": "key", "text": key, "path": key_path})
            scan_tree(value, key_path, keys=keys, id_occurrences=id_occurrences)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            scan_tree(value, f"{path}[{index}]", keys=keys, id_occurrences=id_occurrences)
    elif isinstance(node, str) and LINEAGE_ID.search(node):
        id_occurrences.append({"source": "value", "text": node, "path": path})
    return keys, id_occurrences


def classify_metadata_key(key: str, container_path: str) -> str:
    """Treat a Zarr level attribute as storage layout, not an answer label."""
    name = key.lower()
    normalized_path = container_path.replace("\\", "/").lower()
    if name == "level" and normalized_path.rsplit("/", 1)[-1] == "zarr.json":
        return "zarr_storage_metadata"
    if name in SEMANTIC_SENSITIVE_KEYS:
        return "sensitive_semantic_metadata"
    return "ordinary_metadata"


def audit_deploy_metadata_v2() -> dict:
    """Rescan only deployment JSON metadata and Parquet row containers, not payload arrays."""
    deploy = PKG / "deploy"
    old_audit = OUT
    old_audit_data = json.loads(old_audit.read_text(encoding="utf-8")) if old_audit.exists() else {}
    deployment_files = []
    all_key_occurrences: list[dict] = []
    id_occurrences: list[dict] = []
    zarr_level_fields: list[dict] = []
    for path in sorted(p for p in deploy.rglob("*") if p.is_file() and p.suffix.lower() in {".json", ".parquet"}):
        rel = path.relative_to(PKG).as_posix()
        keys: list[dict] = []
        hits: list[dict] = []
        if path.suffix.lower() == ".json":
            node = json.loads(path.read_text(encoding="utf-8"))
            keys, hits = scan_tree(node)
        else:
            table = pq.read_table(path)
            for field in table.schema:
                keys.append({"key": field.name, "path": f"$.schema.{field.name}"})
            for row_index, row in enumerate(table.to_pylist()):
                row_keys, row_hits = scan_tree(row, f"$[{row_index}]")
                keys.extend(row_keys)
                hits.extend(row_hits)
        for item in keys:
            item_with_file = {**item, "file": rel}
            all_key_occurrences.append(item_with_file)
            if item["key"].lower() == "level" and classify_metadata_key(item["key"], path.name) == "zarr_storage_metadata":
                zarr_level_fields.append(item_with_file)
        for item in hits:
            id_occurrences.append({**item, "file": rel})
        deployment_files.append({
            "path": rel, "bytes": path.stat().st_size, "sha256": sha(path),
            "container": "json_metadata" if path.suffix.lower() == ".json" else "parquet_rows",
            "field_keys": sorted({item["key"] for item in keys})[:200],
            "lineage_style_id_occurrence_count": len(hits),
            "lineage_style_id_sources": sorted({item["source"] for item in hits}),
            "lineage_style_id_examples": hits[:8],
        })
    alias_keys = sorted({item["key"] for item in all_key_occurrences if item["key"].lower() in SEMANTIC_ALIAS_KEYS})
    sensitive_keys = sorted({item["key"] for item in all_key_occurrences if item["key"].lower() in SEMANTIC_SENSITIVE_KEYS})
    classified_sensitive = [
        {**item, "classification": classify_metadata_key(item["key"], item["file"].split("/")[-1])}
        for item in all_key_occurrences
        if classify_metadata_key(item["key"], item["file"].split("/")[-1]) == "sensitive_semantic_metadata"
    ]
    classified_levels = [
        {**item, "classification": "zarr_storage_metadata"} for item in zarr_level_fields
    ]
    distinct_raw_ids = sorted({item["text"] for item in id_occurrences})
    return {
        "audit_date": "2026-10-03",
        "scope": "deployment .json metadata and .parquet schema/rows only; no payload arrays or full-package rehash",
        "package_path": str(PKG.resolve()),
        "historical_audit": artifact_record(old_audit) if old_audit.exists() else None,
        "historical_audit_id_count_values_only": old_audit_data.get("a12_experiment_ready_export", {}).get("lineage_style_ids_found_in_deploy_containers", {}).get("count"),
        "deployment_files_scanned": deployment_files,
        "deployment_file_count": len(deployment_files),
        "lineage_style_ids": {
            "distinct_raw_strings_from_keys_and_values": len(distinct_raw_ids),
            "occurrence_count": len(id_occurrences),
            "source_counts": dict(Counter(item["source"] for item in id_occurrences)),
            "examples": distinct_raw_ids[:24],
            "key_only_occurrence_examples": [item for item in id_occurrences if item["source"] == "key"][:12],
        },
        "identity_answer_alias_keys_present": alias_keys,
        "semantic_sensitive_keys_present": sensitive_keys,
        "semantic_sensitive_key_occurrence_count": len(classified_sensitive),
        "semantic_sensitive_key_occurrence_examples": classified_sensitive[:32],
        "zarr_level_storage_metadata": {
            "classification": "storage layout metadata; not an answer/truth label by itself",
            "occurrence_count": len(classified_levels),
            "examples": classified_levels[:16],
        },
        "self_checks": run_boundary_self_checks(),
    }


def run_boundary_self_checks() -> dict:
    key_only_node = {"LIN0042_V03_M07_PAT11_E02": {"index": 0}}
    key_only_keys, key_only_hits = scan_tree(key_only_node)
    aliases_node = {name: "fixture" for name in ("lineage", "mother", "fragment", "query_id", "historical_N_G")}
    alias_keys, _ = scan_tree(aliases_node)
    zarr_node = {"zarr_format": 3, "node_type": "array", "attributes": {"level": 0}}
    zarr_keys, _ = scan_tree(zarr_node)
    level_occurrence = next(item for item in zarr_keys if item["key"] == "level")
    checks = {
        "key_only_lineage_id_detected": any(hit["source"] == "key" for hit in key_only_hits),
        "identity_answer_aliases_classified_sensitive": all(
            key.lower() in SEMANTIC_ALIAS_KEYS and classify_metadata_key(key, "queries.parquet") == "sensitive_semantic_metadata"
            for key in {item["key"] for item in alias_keys}
        ),
        "zarr_level_is_storage_metadata_not_truth_label": (
            classify_metadata_key(level_occurrence["key"], "deploy/scale/zarr.json") == "zarr_storage_metadata"
            and level_occurrence["key"].lower() not in SEMANTIC_SENSITIVE_KEYS
        ),
    }
    checks["all_pass"] = all(checks.values())
    return checks


def inspect_npz_keys(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        return sorted(name[:-4] for name in zf.namelist() if name.endswith(".npy"))


def audit_export() -> dict:
    export_path = PKG / "export_manifest.json"
    exp = json.loads(export_path.read_text(encoding="utf-8"))
    card = json.loads((PKG / "dataset_card.json").read_text(encoding="utf-8"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    policy = json.loads((ROOT / r"relicweave-synlab\synlab\schemas\view_channels.json").read_text(encoding="utf-8"))
    deploy = PKG / "deploy"
    forbidden = {str(x).lower() for x in (ROOT / r"relicweave-synlab\synlab\roles.py").read_text(encoding="utf-8").split("FORBIDDEN_FEATURE_FIELDS = frozenset({", 1)[1].split("})", 1)[0].replace("\n", " ").replace('"', " ").replace(",", " ").split()}
    capture = {x["key"].lower() for x in policy.get("capture_context_fields", {}).get("fields", [])}
    deployment_files = []
    all_keys: set[str] = set()
    identifier_values = []
    for p in sorted(x for x in deploy.rglob("*") if x.is_file()):
        rel = p.relative_to(PKG).as_posix()
        keys: set[str] = set()
        strings: list[str] = []
        typ = p.suffix.lower()
        if typ == ".json":
            try:
                recursively_collect(json.loads(p.read_text(encoding="utf-8")), keys, strings)
            except Exception as exc:
                keys.add(f"JSON_READ_ERROR:{type(exc).__name__}")
        elif typ == ".npz":
            keys.update(inspect_npz_keys(p))
        elif typ == ".tar":
            with tarfile.open(p, "r") as tf:
                keys.update(Path(m.name).stem for m in tf.getmembers() if m.isfile() and m.name.endswith(".npy"))
        elif typ == ".parquet":
            pf = pq.ParquetFile(p)
            keys.update(pf.schema_arrow.names)
            tab = pq.read_table(p)
            for col in tab.column_names:
                if col in {"query_id", "lineage", "mother", "fragment", "historical_N_G", "status", "context_id", "batch_id", "bag_id", "stratum_id", "excavation_area_id"}:
                    vals = tab[col].to_pylist()
                    strings.extend(str(x) for x in vals if x is not None)
        elif p.name == "zarr.json":
            try:
                recursively_collect(json.loads(p.read_text(encoding="utf-8")), keys, strings)
            except Exception:
                pass
        all_keys.update(keys)
        identifiers = sorted({s for s in [*strings, *keys] if LINEAGE_ID.search(s)})
        identifier_values.extend(identifiers)
        deployment_files.append({"path": rel, "bytes": p.stat().st_size, "sha256": sha(p), "kind": typ or "extensionless",
                                 "field_keys": sorted(keys)[:100], "contains_lineage_style_id": bool(identifiers),
                                 "lineage_id_examples": identifiers[:5]})
    # Exact-name comparison reproduces the current source scan and a second semantic-key inventory exposes aliases.
    exact_hits = sorted(k for k in all_keys if k.lower() in forbidden and k.lower() not in capture)
    aliases = sorted(k for k in all_keys if k.lower() in {"lineage", "mother", "fragment", "query_id", "historical_n_g", "context_id", "batch_id", "stratum_id", "excavation_area_id", "frame_id_source"})
    sensitive_key_names = {"parent", "parent_id", "parentid", "mother", "mother_id", "motherid",
                           "lineage", "lineage_id", "fragment", "fragment_id", "fragmentid",
                           "event_id", "eventid", "seed", "seed_ref", "recipe", "recipe_id",
                           "shape_parameters", "shape_params", "historical_r2", "historical_n_g",
                           "truth_pose", "query_id", "t_wf", "t_wo", "t_wc", "object_pose_t_wo",
                           "vertices_material_xyz_mm", "rest_coordinates", "rest_xyz", "split"}
    sensitive_keys_present = sorted(k for k in all_keys if k.lower() in sensitive_key_names)
    relevant = {}
    for rel in ("deploy/obs/index.json", "deploy/geometry/index.json", "deploy/tokens/index.json", "deploy/deploy_index.json", "deploy/queries.parquet",
                "degrade/index.json", "degrade/sources.json", "degrade/variants.json",
                "research/context/index.json", "research/synthetic_extras/index.json",
                "research/relations.parquet", "research/fracture/fragments.parquet", "research/fracture/interfaces.parquet",
                "research/labels/clean.parquet", "research/labels/physical.parquet", "research/labels/visible.parquet",
                "research/labels/quality.parquet", "research/labels/correspondence.parquet"):
        p = PKG / rel
        if p.exists():
            rec = artifact_record(p)
            if p.suffix == ".parquet":
                pf = pq.ParquetFile(p)
                rec["row_count"] = pf.metadata.num_rows
                rec["columns"] = pf.schema_arrow.names
                tab = pq.read_table(p)
                if rel.endswith("relations.parquet"):
                    rec["kind_counts"] = dict(Counter(str(x) for x in tab["kind"].to_pylist()))
                    rec["valid_count"] = sum(x is True for x in tab["valid"].to_pylist()) if "valid" in tab.column_names else None
                    rec["loss_mask_count"] = sum(x is True for x in tab["loss_mask"].to_pylist()) if "loss_mask" in tab.column_names else None
                if rel.endswith("queries.parquet"):
                    rec["rows_examples"] = [{k: tab[k][i].as_py() for k in tab.column_names} for i in range(min(2, pf.metadata.num_rows))]
            relevant[rel] = rec
    contexts = []
    for p in [PKG / "deploy/context/packs.json", PKG / "deploy/context/index.json"]:
        if p.exists():
            contexts.append({"path": p.relative_to(PKG).as_posix(), "sha256": sha(p), "text": p.read_text(encoding="utf-8")[:8000]})
    sys.path.insert(0, str((ROOT / "relicweave-synlab").resolve()))
    from synlab.storage.export import TrainingPackage
    package_verify = TrainingPackage(PKG).verify_files()
    table_summaries = {}
    for rel in ("research/relations.parquet", "research/fracture/fragments.parquet",
                "research/fracture/interfaces.parquet", "research/labels/correspondence.parquet",
                "research/labels/quality.parquet", "research/labels/physical.parquet",
                "research/labels/clean.parquet", "research/labels/visible.parquet"):
        p = PKG / rel
        if not p.exists():
            continue
        tab = pq.read_table(p)
        records = tab.to_pylist()
        summary = {"sha256": sha(p), "rows": len(records), "columns": tab.column_names}
        for field in ("kind", "split", "qa_status", "source_kind", "relation_kind", "valid", "loss_mask", "label_layer", "passed"):
            if field in tab.column_names:
                summary[field + "_counts"] = dict(Counter(str(row.get(field)) for row in records))
        for field in ("lineage", "lineage_id", "lineage_cluster"):
            if field in tab.column_names:
                group_splits: dict[str, set[str]] = {}
                for row in records:
                    group = str(row.get(field) or "")
                    group_splits.setdefault(group, set()).add(str(row.get("split") or ""))
                nonempty = {group: sorted(value for value in splits if value)
                            for group, splits in group_splits.items() if group}
                mixed = {group: sorted(splits) for group, splits in group_splits.items()
                         if group and len(splits) > 1}
                summary[field + "_group_count"] = len(nonempty)
                summary[field + "_groups_across_multiple_split_values"] = mixed
                summary[field + "_group_split_counts"] = dict(Counter(
                    ",".join(splits) or "<missing>" for splits in nonempty.values()))
        if rel.endswith("relations.parquet"):
            summary["relation_reason_counts"] = dict(Counter(str(row.get("reason")) for row in records))
        if rel.endswith("interfaces.parquet"):
            summary["area_mm2_range"] = [min(float(row["area_mm2"]) for row in records),
                                          max(float(row["area_mm2"]) for row in records)]
            summary["sample_rows"] = records[:2]
        if rel.endswith("correspondence.parquet"):
            summary["sample_rows"] = records[:2]
        table_summaries[rel] = summary
    return {
        "package_path": str(PKG.resolve()), "export_manifest": artifact_record(export_path),
        "package_schema": exp.get("package_schema"), "release_id": exp.get("release_id"),
        "release_profile": exp.get("release_profile"), "release_scope": exp.get("release_scope"),
        "export_build": exp.get("build"), "manifest_counts": exp.get("counts"),
        "separation": exp.get("separation"), "views": exp.get("views"),
        "reference_closure": exp.get("reference_closure"),
        "deployment_channel_policy": exp.get("view_channel_policy"),
        "policy_hash": exp.get("view_channel_policy_hash"), "policy_deploy_keys": [x.get("key") for x in policy["views"]["deploy"]["channels"]],
        "release_report": {"path": str(REPORT.resolve()), "sha256": sha(REPORT), "base": report.get("base"), "freeze": report.get("freeze")},
        "freeze_blocked": {"path": str(FREEZE.resolve()), "sha256": sha(FREEZE), "frozen": freeze.get("frozen"),
                            "profile": freeze.get("profile"), "gates": freeze.get("gates"),
                            "required_gates": freeze.get("required_gates"), "error": freeze.get("error")},
        "dataset_card": artifact_record(PKG / "dataset_card.json"),
        "dataset_card_counts": card.get("package", {}).get("counts"),
        "package_integrity_verification": package_verify,
        "package_bytes_total": exp.get("bytes_total"), "package_files_total": exp.get("counts_total"),
        "package_asset_roles": exp.get("assets"),
        "exact_forbidden_key_hits_recomputed": exact_hits,
        "semantic_identity_and_answer_alias_keys_present": aliases,
        "semantic_sensitive_keys_present": sensitive_keys_present,
        "semantic_sensitive_key_list": sorted(sensitive_key_names),
        "lineage_style_ids_found_in_deploy_containers": {"count": len(set(identifier_values)), "examples": sorted(set(identifier_values))[:16]},
        "deployment_files": deployment_files, "selected_artifacts": relevant, "context_files": contexts,
        "research_label_and_split_summaries": table_summaries,
    }


def main() -> None:
    if sys.argv[1:] == ["--deploy-metadata-only"]:
        audit = audit_deploy_metadata_v2()
        OUT_V2.write_text(json.dumps(audit, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(OUT_V2.resolve()), "deployment_file_count": audit["deployment_file_count"],
                          "lineage_style_ids": audit["lineage_style_ids"], "self_checks": audit["self_checks"]},
                         indent=2, ensure_ascii=False))
        return
    audit = {"audit_date": "2026-10-03", "vf": audit_vf(), "pg_osb_fracture_branch_001": audit_pg_job(PG),
             "pg_wheel_osb_smoke_001": audit_pg_job(WHEEL), "a12_experiment_ready_export": audit_export()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(audit, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT.resolve()), "vf_manifest_sha256": audit["vf"]["manifest"]["sha256"],
                      "vf_vertex_face_counts": audit["vf"]["surface"],
                      "pg_points": audit["pg_osb_fracture_branch_001"]["tables"]["points.csv"]["rows"],
                      "a12_deploy_exact_forbidden_hits": audit["a12_experiment_ready_export"]["exact_forbidden_key_hits_recomputed"],
                      "a12_alias_keys": audit["a12_experiment_ready_export"]["semantic_identity_and_answer_alias_keys_present"],
                      "a12_identifiers": audit["a12_experiment_ready_export"]["lineage_style_ids_found_in_deploy_containers"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
