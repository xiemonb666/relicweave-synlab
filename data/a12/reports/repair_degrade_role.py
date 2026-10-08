"""Repair the misfiled degradation bundles of one store (A01 / leakage boundary).

Why this exists
---------------
``synlab.degrade.api._apply_impl`` used to commit every axis/level result under the
``feature_bundle`` role while its metadata carried ``axis_id``/``level``/``variant`` — the exact
keys ``synlab.roles.FORBIDDEN_FEATURE_FIELDS`` forbids inside a feature bundle.  The code is
fixed (``COMMIT_ROLES['X']`` now commits a ``degrade_measurement``), but the rows already written
by the operator audit stay in the store and keep `A01` and
``synlab.qc.leakage.run_negative_control`` at FAIL.

What it does (per misfiled asset, in this order)
------------------------------------------------
1. reads the committed bundle back with the module's own inverse function
   (``synlab.degrade.sources.load_source``);
2. re-commits those exact bytes under ``role=degrade_measurement`` / ``schema=synlab.measurement.v1``,
   so the identity of the payload survives under a role that may legally carry the factor label;
3. verifies the re-commit is byte-faithful (same array keys, shapes, dtypes and per-array hashes);
4. only then removes the misfiled row: the SQLite row and the ``assets/<id>`` directory, after the
   absolute path has been resolved and checked against the asset id;
5. records a tombstone (role, schema, unit, frame, qa, meta, file hashes) plus the old->new id
   mapping in a JSON report, so the removal is auditable and nothing is silently dropped.

It refuses to touch an asset that anything else references (another asset's ancestry, a release
manifest, a pool/roster asset) and it never rewrites an existing row in place: ``asset_id`` is
derived from ``interpret_hash(role, ...)``, so editing ``role`` in the database would break the
store's identity contract.

Usage::

    python data/a12/reports/repair_degrade_role.py --store data/a12            # dry run
    python data/a12/reports/repair_degrade_role.py --store data/a12 --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synlab.canonical import array_hash, hash_file  # noqa: E402
from synlab.degrade.sources import commit_source, load_source  # noqa: E402
from synlab.roles import (  # noqa: E402
    FORBIDDEN_FEATURE_FIELDS,
    ROLE_DEGRADE_MEASUREMENT,
    ROLE_FEATURE_BUNDLE,
    SCHEMA_MEASUREMENT,
)
from synlab.storage.store import AssetStore  # noqa: E402

#: Keys ``commit_source`` regenerates on every commit; they must not be forced from the old meta.
REGENERATED_META_KEYS = ("source_kind", "payload_meta", "dropped_non_storable_keys", "content_hash")


def misfiled_assets(store: AssetStore) -> list[Any]:
    """feature_bundle assets whose metadata carries the factor label (and no feature contract)."""
    out = []
    for asset in store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=100000):
        meta = asset.meta or {}
        if set(meta) & FORBIDDEN_FEATURE_FIELDS and not meta.get("feature_fields"):
            out.append(asset)
    return out


def references_to(store: AssetStore, asset_id: str) -> dict[str, list[str]]:
    """Every place outside the asset row itself that mentions ``asset_id``."""
    hits: dict[str, list[str]] = {"ancestry": [], "meta": [], "releases": [], "rows": []}
    with store.connect() as conn:
        for row in conn.execute("SELECT asset_id, ancestry_json, meta_json FROM assets").fetchall():
            if asset_id in (row["ancestry_json"] or ""):
                hits["ancestry"].append(row["asset_id"])
            if asset_id in (row["meta_json"] or ""):
                hits["meta"].append(row["asset_id"])
        for table in ("jobs", "runs", "events", "releases"):
            try:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            except Exception:  # noqa: BLE001 - table may not exist in an older store
                continue
            for row in rows:
                blob = " ".join(str(value) for value in tuple(row))
                if asset_id in blob:
                    hits["rows"].append(f"{table}:{tuple(row)[0]}")
    releases_dir = store.root / "releases"
    if releases_dir.exists():
        for manifest in releases_dir.rglob("manifest.json"):
            if asset_id in manifest.read_text(encoding="utf-8"):
                hits["releases"].append(str(manifest))
    return hits


def array_census(store: AssetStore, asset_id: str) -> dict[str, dict[str, Any]]:
    arrays = store.load_arrays(asset_id)
    return {key: {"shape": list(value.shape), "dtype": str(value.dtype),
                  "hash": array_hash(value)} for key, value in sorted(arrays.items())}


def plan_entry(store: AssetStore, asset: Any) -> dict[str, Any]:
    refs = references_to(store, asset.asset_id)
    blocking = {k: v for k, v in refs.items() if k in ("ancestry", "releases") and v}
    return {
        "asset_id": asset.asset_id,
        "role": asset.role, "schema": asset.schema, "unit": asset.unit, "frame": asset.frame,
        "qa_status": asset.qa_status, "lineage_id": asset.lineage_id, "split": asset.split,
        "forbidden_meta_keys": sorted(set(asset.meta or {}) & FORBIDDEN_FEATURE_FIELDS),
        "meta_keys": sorted(asset.meta or {}),
        "files": dict(asset.files or {}),
        "file_hashes": dict(store.file_hashes(asset.asset_id)),
        "arrays": array_census(store, asset.asset_id),
        "references": refs,
        "blocking_references": blocking,
        "action": "REFUSED_REFERENCED" if blocking else "RECOMMIT_AND_REMOVE",
    }


def repair_one(store: AssetStore, entry: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    asset_id = entry["asset_id"]
    if entry["blocking_references"]:
        return {**entry, "performed": False,
                "reason": f"asset is referenced by {entry['blocking_references']}"}
    if not apply:
        return {**entry, "performed": False, "reason": "dry run"}

    record = store.get_asset(asset_id)
    bundle = load_source(store, asset_id)
    meta = {k: v for k, v in dict(record.meta or {}).items() if k not in REGENERATED_META_KEYS}
    new_record = commit_source(
        store, bundle, role=ROLE_DEGRADE_MEASUREMENT, schema=SCHEMA_MEASUREMENT,
        lineage_id=record.lineage_id, split=record.split, qa=dict(record.qa or {}), meta=meta)

    old_arrays = entry["arrays"]
    new_arrays = array_census(store, new_record.asset_id)
    same_keys = sorted(old_arrays) == sorted(new_arrays)
    identical = same_keys and all(old_arrays[k]["hash"] == new_arrays[k]["hash"]
                                  and old_arrays[k]["shape"] == new_arrays[k]["shape"]
                                  and old_arrays[k]["dtype"] == new_arrays[k]["dtype"]
                                  for k in old_arrays)
    fidelity = {
        "array_keys_equal": same_keys,
        "array_hashes_equal": identical,
        "n_arrays_old": len(old_arrays), "n_arrays_new": len(new_arrays),
        "differences": sorted(k for k in set(old_arrays) | set(new_arrays)
                              if old_arrays.get(k, {}).get("hash") != new_arrays.get(k, {}).get("hash")),
    }
    if not identical:
        # The payload did not survive the role change: keep the misfiled row and report it.
        return {**entry, "performed": False, "new_asset_id": new_record.asset_id,
                "fidelity": fidelity,
                "reason": "re-commit is not byte-faithful; the misfiled row was left in place"}

    meta_new = {k: v for k, v in dict(new_record.meta or {}).items() if k not in REGENERATED_META_KEYS}
    meta_diff = {"only_old": sorted(set(meta) - set(meta_new)),
                 "only_new": sorted(set(meta_new) - set(meta)),
                 "changed": sorted(k for k in set(meta) & set(meta_new) if meta[k] != meta_new[k])}

    # ---------------- remove the misfiled row -------------------------------------------
    asset_dir = (store.root / "assets" / asset_id).resolve()
    expected_parent = (store.root / "assets").resolve()
    if asset_dir.parent != expected_parent or asset_dir.name != asset_id:
        return {**entry, "performed": False, "new_asset_id": new_record.asset_id,
                "fidelity": fidelity, "meta_diff": meta_diff,
                "reason": f"refusing to remove unexpected path {asset_dir}"}
    existed = asset_dir.exists()
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))
            conn.execute(
                "INSERT INTO events(run_id, job_id, type, state, revision, message, payload_json, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (None, None, "asset.role_repaired", "REMOVED", 1, asset_id,
                 json.dumps({"from_role": ROLE_FEATURE_BUNDLE, "to_role": ROLE_DEGRADE_MEASUREMENT,
                             "new_asset_id": new_record.asset_id,
                             "reason": "misfiled: degradation measurement carried the factor label "
                                       "under the feature_bundle role (A01 / leakage boundary)"}),
                 time.time()))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    if existed:
        shutil.rmtree(asset_dir)
    return {**entry, "performed": True, "new_asset_id": new_record.asset_id,
            "new_role": new_record.role, "new_schema": new_record.schema,
            "new_qa_status": new_record.qa_status,
            "fidelity": fidelity, "meta_diff": meta_diff, "asset_dir_removed": bool(existed)}


def role_counts(store: AssetStore) -> dict[str, int]:
    counts: dict[str, int] = {}
    for asset in store.list_assets(limit=1000000):
        counts[asset.role] = counts.get(asset.role, 0) + 1
    return dict(sorted(counts.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repair_degrade_role")
    parser.add_argument("--store", default="data/a12")
    parser.add_argument("--apply", action="store_true", help="really re-commit and remove")
    parser.add_argument("--report", default="data/a12/reports/degrade_role_repair.json")
    args = parser.parse_args(argv)

    store = AssetStore(ROOT / args.store if not Path(args.store).is_absolute() else args.store)
    assets = misfiled_assets(store)
    entries = [plan_entry(store, asset) for asset in assets]
    before = role_counts(store)
    results = [repair_one(store, entry, apply=args.apply) for entry in entries]
    after = role_counts(store)

    report = {
        "schema": "synlab.degrade_role_repair.v1",
        "generated_at": time.time(),
        "store": str(store.root),
        "applied": bool(args.apply),
        "candidate_count": len(entries),
        "misfiled_rule": ("role == feature_bundle AND meta intersects FORBIDDEN_FEATURE_FIELDS "
                          "AND meta has no feature_fields"),
        "new_role": ROLE_DEGRADE_MEASUREMENT,
        "new_schema": SCHEMA_MEASUREMENT,
        "before_role_counts": before,
        "after_role_counts": after,
        "repaired": [r for r in results if r.get("performed")],
        "refused": [r for r in results if not r.get("performed")],
        "entries": results,
        "note": ("asset_id is derived from interpret_hash(role, ...), so the role of an existing "
                 "row is never edited in place: the payload is re-committed under the correct role "
                 "and only then is the misfiled row removed, with its tombstone recorded here."),
    }
    path = Path(args.report)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                    encoding="utf-8")
    print(f"[repair] applied={args.apply} candidates={len(entries)} "
          f"repaired={len(report['repaired'])} refused={len(report['refused'])} report={path}")
    for entry in report["repaired"]:
        print(f"  {entry['asset_id']} -> {entry['new_asset_id']} "
              f"({entry.get('new_role')}) arrays={entry['fidelity']['n_arrays_new']} "
              f"faithful={entry['fidelity']['array_hashes_equal']}")
    for entry in report["refused"]:
        print(f"  REFUSED {entry['asset_id']}: {entry.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
