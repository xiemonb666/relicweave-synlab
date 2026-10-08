"""Repair unresolvable ancestry references in the next-experiment batch, then freeze a release.

Why a data-level repair is legitimate here
------------------------------------------
``synlab.physical.api.commit_physical`` writes ``ancestry=[result.clean_ref]``, and
``clean_ref`` is a *semantic* identifier built by ``physical.api.apply_damage`` as
``f"{mother_id}:{event_id}:v{version}"`` -- not an asset id.  Every downstream asset
(``physical_result`` -> ``physical_truth`` / ``obs_result`` -> ``feature_bundle`` /
``visible_labels``) inherits that unresolvable ancestor, so ``ReleaseManager.verify_closure`` can
never be satisfied for any release that contains an observation, and no *observation-bearing*
release can be frozen at all.  Measured consequences are in
``docs/a12/next_experiment_data.md`` §7.

This tool repairs **data**, not code: for each asset in the batch whose ancestry names a
``<mother>:<event>:v<version>`` clean-truth reference, it appends the id of the ``clean_truth``
asset that actually carries that reference (visible in that asset's ``meta["clean_ref"]``) and
keeps the semantic reference in ``meta["ancestry_semantic_refs"]`` for audit.  It never invents an
ancestor and never rewrites payloads, hashes or QA verdicts.

Every change is written to a repair ledger and is reversible from it.

Usage::

    python tools/repair_ancestry_refs.py --dry-run
    python tools/repair_ancestry_refs.py --apply
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LEDGER = ROOT / "data/a12/reports/next_experiment_batches.json"
DB = ROOT / "data/a12/metadata.sqlite"
REPAIR_LEDGER = ROOT / "data/a12/reports/ancestry_repair.json"


def batch_runs() -> set[str]:
    if not LEDGER.exists():
        return set()
    data = json.loads(LEDGER.read_text(encoding="utf-8"))
    return {row["run_id"] for row in data.get("batches", []) if row.get("run_id")}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repair_ancestry_refs")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    parser.add_argument("--ledger", default=str(LEDGER))
    parser.add_argument("--db", default=str(DB))
    args = parser.parse_args(argv)

    runs = batch_runs()
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "select asset_id, role, qa_status, lineage_id, ancestry_json, meta_json from assets")]
    known = {r["asset_id"] for r in rows}
    in_batch = {r["asset_id"] for r in rows
                if json.loads(r["meta_json"] or "{}").get("run_id") in runs}

    # semantic clean-truth reference -> the clean_truth asset id that carries it.
    # The reference map is built from *every* clean_truth asset in the store, not only the ones
    # committed by this batch's runs: a lineage whose first attempt belongs to an earlier run still
    # points at that run's clean truth, and treating such a reference as unresolvable would leave
    # the observation branch closed off.
    ref_to_asset: dict[str, str] = {}
    for row in rows:
        if row["role"] != "clean_truth":
            continue
        meta = json.loads(row["meta_json"] or "{}")
        for key in ("clean_ref", "ref"):
            value = meta.get(key)
            if isinstance(value, str) and value:
                ref_to_asset.setdefault(value, row["asset_id"])
        if meta.get("mother_id") and meta.get("event_id"):
            ref_to_asset.setdefault(
                f'{meta.get("mother_id")}:{meta.get("event_id")}:v{meta.get("version", 0)}',
                row["asset_id"])

    changes: list[dict[str, Any]] = []
    unresolved: collections.Counter = collections.Counter()
    for row in rows:
        if row["asset_id"] not in in_batch:
            continue
        ancestry = json.loads(row["ancestry_json"] or "[]")
        bad = [a for a in ancestry if a not in known]
        if not bad:
            continue
        fixed = list(ancestry)
        semantics: list[str] = []
        for ref in bad:
            target = ref_to_asset.get(ref)
            if target is None:
                unresolved[f'{row["role"]}:{ref.split(":")[0][:32]}'] += 1
                continue
            if target not in fixed:
                fixed.append(target)
            semantics.append(ref)
        if len(fixed) == len(ancestry):
            continue
        meta = json.loads(row["meta_json"] or "{}")
        meta.setdefault("ancestry_semantic_refs", [])
        meta["ancestry_semantic_refs"] = sorted(set(meta["ancestry_semantic_refs"]) | set(semantics))
        meta["ancestry_repair"] = {
            "tool": "tools/repair_ancestry_refs.py",
            "at": time.time(),
            "reason": "clean_ref is a semantic id, not an asset id (physical.api.commit_physical)",
            "added": [a for a in fixed if a not in ancestry],
        }
        changes.append({
            "asset_id": row["asset_id"], "role": row["role"], "lineage_id": row["lineage_id"],
            "before": ancestry, "after": fixed, "meta": meta,
        })

    print(f"batch runs: {len(runs)}  batch assets: {len(in_batch)}  assets to repair: {len(changes)}")
    print("roles repaired:", dict(collections.Counter(c["role"] for c in changes)))
    if unresolved:
        print("STILL UNRESOLVED references (not repairable by this tool):")
        for key, n in unresolved.most_common(20):
            print(f"   {n:4d}  {key}")

    payload = {
        "schema": "synlab.ancestry_repair.v1",
        "at": time.time(),
        "applied": not args.dry_run,
        "runs": sorted(runs),
        "changes": changes,
        "unresolved": dict(unresolved),
    }
    REPAIR_LEDGER.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                             encoding="utf-8")
    print("ledger:", REPAIR_LEDGER, "(applied)" if not args.dry_run else "(dry-run)")
    if args.dry_run or not changes:
        return 0

    with con:
        for change in changes:
            con.execute("UPDATE assets SET ancestry_json = ?, meta_json = ? WHERE asset_id = ?",
                        (json.dumps(change["after"]), json.dumps(change["meta"]),
                         change["asset_id"]))
    print(f"applied {len(changes)} ancestry repairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
