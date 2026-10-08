from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from synlab.qc.leakage import run_negative_control


REPO = Path(__file__).resolve().parents[3]
STORE_ROOT = REPO / "data" / "a12_trainable" / "store"
DB_PATH = STORE_ROOT / "metadata.sqlite"
REPORT_PATH = Path(__file__).resolve().parent / "current_store_audit.json"


def _json(value):
    return json.loads(value) if value else {}


def _walk_key_values(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key).lower(), value, path + (str(key),)
            yield from _walk_key_values(value, path + (str(key),))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_key_values(value, path + (str(index),))


class ReadOnlyStore:
    def __init__(self, root: Path, rows: list[sqlite3.Row]):
        self.root = root
        self._rows = rows
        self._by_id = {row["asset_id"]: row for row in rows}

    @staticmethod
    def _record(row):
        return SimpleNamespace(
            asset_id=row["asset_id"], role=row["role"], schema=row["schema"],
            unit=row["unit"], frame=row["frame"], qa_status=row["qa_status"],
            qa=_json(row["qa_json"]), files=_json(row["files_json"]),
            meta=_json(row["meta_json"]), ancestry=_json(row["ancestry_json"]),
            lineage_id=row["lineage_id"], split=row["split"],
        )

    def list_assets(self, *, role=None, limit=500, offset=0, **_filters):
        selected = [r for r in self._rows if role is None or r["role"] == role]
        selected.sort(key=lambda r: (r["created_at"], r["asset_id"]))
        return [self._record(row) for row in selected[offset:offset + limit]]

    def count_assets(self, *, role=None, **_filters):
        return sum(1 for row in self._rows if role is None or row["role"] == role)

    def get_asset(self, asset_id):
        return self._record(self._by_id[asset_id])

    def resolve_asset_path(self, asset_id, name):
        record = self.get_asset(asset_id)
        rel = record.files[name]
        return self.root.joinpath(*rel.split("/")), "not-rehashed-by-read-only-census"

    def load_arrays(self, asset_id):
        record = self.get_asset(asset_id)
        rel = record.files.get("arrays")
        if not rel:
            return {}
        path = self.root.joinpath(*rel.split("/"))
        with np.load(path, allow_pickle=False) as payload:
            return {key: payload[key] for key in payload.files}


uri = "file:" + DB_PATH.as_posix() + "?mode=ro"
connection = sqlite3.connect(uri, uri=True)
connection.row_factory = sqlite3.Row
asset_rows = connection.execute("SELECT * FROM assets ORDER BY created_at, asset_id").fetchall()
run_rows = connection.execute(
    "SELECT run_id, status, scope, profile, created_at FROM runs ORDER BY created_at, run_id"
).fetchall()
connection.close()

roles = Counter(row["role"] for row in asset_rows)
qa_by_role: dict[str, Counter] = defaultdict(Counter)
lineage_assets: Counter = Counter()
lineages_by_role: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
factor_values: dict[str, set[str]] = defaultdict(set)
factor_counts: dict[str, Counter] = defaultdict(Counter)
factor_by_role: dict[str, Counter] = defaultdict(Counter)
feature_runs: Counter = Counter()
provenance_runs: Counter = Counter()
axis_asset_ids: dict[str, list[str]] = defaultdict(list)
field_name_counts: Counter = Counter()

aliases = {
    "vessel": {"vessel_id", "vessel", "vessel_type", "vessel_family"},
    "material": {"material_id", "material", "material_type"},
    "pattern": {"pattern_id", "pattern", "pattern_family", "family_id"},
    "materialized_axis": {"axis_id"},
}

for row in asset_rows:
    role = row["role"]
    qa_by_role[role][row["qa_status"]] += 1
    lineage = row["lineage_id"]
    if lineage:
        lineage_assets[lineage] += 1
        lineages_by_role[role][lineage].add(row["asset_id"])
    meta = _json(row["meta_json"])
    for key, value, path in _walk_key_values(meta):
        field_name_counts[key] += 1
        if key == "run_id" and value is not None:
            if role == "feature_bundle":
                feature_runs[str(value)] += 1
            elif role == "provenance":
                provenance_runs[str(value)] += 1
        for factor, factor_aliases in aliases.items():
            if key in factor_aliases and isinstance(value, (str, int, float)):
                label = str(value)
                factor_values[factor].add(label)
                factor_counts[factor][label] += 1
                factor_by_role[factor][role] += 1
                if factor == "materialized_axis":
                    axis_asset_ids[label].append(row["asset_id"])

readonly_store = ReadOnlyStore(STORE_ROOT, asset_rows)
leakage = run_negative_control(readonly_store, run_id=None)

report = {
    "audit_time_local": datetime.now().astimezone().isoformat(timespec="seconds"),
    "store_root": str(STORE_ROOT),
    "sqlite_access": "mode=ro; metadata.sqlite only; no AssetStore constructor; no assets changed",
    "run_filter": {
        "feature_and_provenance_filter": None,
        "scope": "all feature/provenance assets in this store",
        "feature_run_id_counts": dict(sorted(feature_runs.items())),
        "provenance_run_id_counts": dict(sorted(provenance_runs.items())),
    },
    "counts": {
        "assets_total": len(asset_rows),
        "roles": dict(sorted(roles.items())),
        "qa_by_role": {role: dict(sorted(counts.items()))
                       for role, counts in sorted(qa_by_role.items())},
        "lineage": {
            "unique_nonempty_lineage_ids": len(lineage_assets),
            "assets_with_lineage": sum(lineage_assets.values()),
            "largest_lineages_asset_counts": dict(lineage_assets.most_common(20)),
            "unique_lineages_by_role": {
                role: len(lineages) for role, lineages in sorted(lineages_by_role.items())
            },
        },
        "factors": {
            name: {
                "distinct_values": len(factor_values[name]),
                "assets_with_field_count": sum(factor_counts[name].values()),
                "value_asset_counts": dict(factor_counts[name].most_common(50)),
                "assets_by_role": dict(sorted(factor_by_role[name].items())),
            }
            for name in aliases
        },
        "materialized_axis_asset_ids": {
            axis: ids for axis, ids in sorted(axis_asset_ids.items())
        },
        "run_records": {
            "count": len(run_rows),
            "by_status": dict(sorted(Counter(row["status"] for row in run_rows).items())),
            "ids": [{"run_id": row["run_id"], "status": row["status"],
                     "scope": row["scope"], "profile": row["profile"]} for row in run_rows],
        },
        "metadata_key_counts_top_80": dict(field_name_counts.most_common(80)),
    },
    "feature_leakage": {
        "status": leakage["status"],
        "ok": leakage["ok"],
        "problems": leakage["problems"],
        "feature_scope": leakage["checks"]["feature_scope"],
        "provenance_scope": leakage["checks"]["provenance_scope"],
        "truth_isolation": leakage["checks"]["truth_isolation"],
        "truth_dependency_paths": leakage["checks"]["truth_dependency_paths"],
        "unresolved_ancestry_count": leakage["checks"]["unresolved_ancestry_count"],
        "feature_field_leakage": leakage["checks"]["feature_field_leakage"],
        "feature_field_violations": leakage["checks"]["feature_field_violations"],
        "metadata_permutation": leakage["checks"]["metadata_permutation"],
        "row_permutation_invariance": leakage["checks"]["row_permutation_invariance"],
        "note": leakage["note"],
    },
    "limitations": [
        "Read-only adapter did not re-hash feature NPZ files; the QC inspected NPZ key names and a small first-five sample for structural invariance.",
        "This structural feature/ancestry audit does not establish that a trained model cannot exploit other shortcuts.",
        "Factor counters count every metadata occurrence across asset rows and may repeat a factor value across roles/assets; distinct_values is separately reported.",
    ],
}
REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps({
    "report_path": str(REPORT_PATH),
    "audit_time_local": report["audit_time_local"],
    "assets_total": report["counts"]["assets_total"],
    "roles": report["counts"]["roles"],
    "feature_leakage_status": leakage["status"],
    "feature_count": leakage["checks"]["feature_scope"]["selected_and_checked"],
    "truth_path_count": len(leakage["checks"]["truth_dependency_paths"]),
    "field_violation_count": len(leakage["checks"]["feature_field_violations"]),
}, ensure_ascii=False, indent=2))
