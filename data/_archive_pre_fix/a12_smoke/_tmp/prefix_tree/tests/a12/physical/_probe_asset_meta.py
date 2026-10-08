"""Read-only dump of one asset's meta/qa (keys + selected values)."""
import argparse
import json
import sqlite3
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--root", default="data/a12")
ap.add_argument("--role", default="physical_result")
ap.add_argument("--limit", type=int, default=1)
ap.add_argument("--keys", default="")
args = ap.parse_args()
root = Path(args.root)
con = sqlite3.connect(f"file:{(root / 'metadata.sqlite').as_posix()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
rows = list(con.execute("select asset_id, role, meta_json, qa_json, lineage_id from assets "
                        "where role=? limit ?", (args.role, int(args.limit))))
for row in rows:
    meta = json.loads(row["meta_json"] or "{}")
    qa = json.loads(row["qa_json"] or "{}")
    print("=" * 30, row["role"], row["asset_id"], row["lineage_id"])
    print("meta keys:", sorted(meta))
    print("qa keys:", sorted(qa))
    wanted = [k.strip() for k in args.keys.split(",") if k.strip()]
    for key in wanted:
        print(f"-- {key}:", json.dumps(meta.get(key), indent=1, default=str)[:2500])
    if not wanted:
        print(json.dumps(meta, indent=1, default=str)[:6000])
