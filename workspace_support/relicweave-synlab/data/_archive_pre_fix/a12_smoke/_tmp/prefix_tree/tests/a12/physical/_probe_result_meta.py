"""Read-only dump of the physical result metadata of one lineage (tolerances for provenance)."""
import argparse
import json
import sqlite3
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--root", default="data/a12")
ap.add_argument("--lineage", default="LIN0000_V01_M01_PAT01")
args = ap.parse_args()
root = Path(args.root)
con = sqlite3.connect(f"file:{(root / 'metadata.sqlite').as_posix()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
for row in con.execute("select asset_id, role, meta_json, qa_json, lineage_id from assets "
                       "where lineage_id=? and role in ('physical_result','physical_component',"
                       "'physical_truth','clean_truth')", (args.lineage,)):
    meta = json.loads(row["meta_json"] or "{}")
    qa = json.loads(row["qa_json"] or "{}")
    print("=" * 30, row["role"], row["asset_id"], "lineage:", row["lineage_id"])
    keep = {k: v for k, v in meta.items()
            if k in ("measurement", "measurement_units", "recipe", "ledger", "damage",
                     "association_counts", "component_id", "ancestor", "axis_id", "level",
                     "variant", "damage_semantics", "iface_id")}
    print(json.dumps(keep, indent=1, default=str)[:3000])
    if row["role"] == "physical_result":
        m = meta.get("measurement") or {}
        print("measurement:", json.dumps(m, indent=1, default=str))
        q = meta.get("qa") or {}
        sp = ((q.get("checks") or {}).get("damaged_subset_clean") or {})
        print("subset instrument keys:", list(sp)[:10])
        print("details:", json.dumps((meta.get("recipe") or {}), indent=1, default=str)[:800])
        print("ledger:", json.dumps(meta.get("ledger") or {}, indent=1, default=str)[:1500])
