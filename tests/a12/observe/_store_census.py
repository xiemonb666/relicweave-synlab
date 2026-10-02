"""Read-only role/asset census of a store (tiny helper for the fracture-surface work)."""
import argparse
import sqlite3
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--root", default="data/a12_iface/store")
ap.add_argument("--roles", default="obs_result,physical_component,physical_truth,visible_labels,"
                                   "clean_truth,provenance,label_bundle,feature_bundle")
args = ap.parse_args()
db = Path(args.root) / "metadata.sqlite"
con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
print("== role counts ==")
for row in con.execute("select role, count(*) as n from assets group by role order by n desc"):
    print(f"  {row['role']:24s} {row['n']}")
roles = tuple(x.strip() for x in args.roles.split(",") if x.strip())
print("== assets of interest ==")
query = ("select lineage_id, role, asset_id, qa_status from assets where role in "
         f"({','.join('?' * len(roles))}) order by lineage_id, role")
for row in con.execute(query, roles):
    print(f"  {row['lineage_id']:28s} {row['role']:20s} {row['asset_id']} {row['qa_status']}")
