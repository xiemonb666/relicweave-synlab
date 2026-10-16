"""Role/QA inventory per store, plus the feature-bundle leakage census.

Read-only: connects to each store's SQLite metadata and prints counts.  No writes.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

FORBIDDEN = ["axis_id", "level", "variant", "split", "parent_id", "object_id", "seed",
             "lineage_id", "mother_id", "fragment_id", "relation", "mate_present", "truth_pose"]

stores = sys.argv[1:] or ["data/a12", "data/a12_exports/closed_loop/store"]
for rel in stores:
    root = ROOT / rel
    db = root / "metadata.sqlite"
    print(f"\n########## {rel}  exists={root.exists()}  db={db.exists()}")
    if not db.exists():
        continue
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT role, qa_status, COUNT(*) AS n FROM assets GROUP BY role, qa_status "
                       "ORDER BY role, qa_status").fetchall()
    total = 0
    for row in rows:
        print(f"  {row['role']:<28} {row['qa_status']:<10} {row['n']}")
        total += row["n"]
    print(f"  TOTAL {total}")
    print("  runs:")
    for row in con.execute("SELECT run_id, profile, scope, status FROM runs ORDER BY rowid").fetchall():
        print(f"    {row['run_id']:<28} profile={row['profile']} scope={row['scope']} status={row['status']}")
    print("  feature_bundle meta keys census:")
    census: dict[str, int] = {}
    exemplars: list[dict] = []
    for row in con.execute("SELECT asset_id, role, qa_status, meta_json FROM assets "
                           "WHERE role='feature_bundle' ORDER BY asset_id").fetchall():
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except ValueError:
            meta = {}
        for key in sorted(meta):
            census[key] = census.get(key, 0) + 1
        if len(exemplars) < 3:
            exemplars.append({"asset_id": row["asset_id"], "qa": row["qa_status"],
                              "meta_keys": sorted(meta)[:24]})
    print("   ", json.dumps(census, sort_keys=True))
    for item in exemplars:
        print("    example:", json.dumps(item, sort_keys=True))
    print("  releases:")
    for row in con.execute("SELECT release_id, profile, scope, frozen_at FROM releases").fetchall():
        print(f"    {row['release_id']:<30} profile={row['profile']} scope={row['scope']}")
    con.close()
