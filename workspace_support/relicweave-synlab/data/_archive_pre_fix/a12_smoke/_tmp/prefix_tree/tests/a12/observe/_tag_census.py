"""Quick per-view surface_tag histogram of a store's obs_result assets (read-only)."""
import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--root", default="data/a12_iface/store")
ap.add_argument("--role", default="obs_result")
args = ap.parse_args()
root = Path(args.root)
con = sqlite3.connect(f"file:{(root / 'metadata.sqlite').as_posix()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
for row in con.execute("select asset_id, role, files_json, meta_json, lineage_id from assets "
                       "where role=?", (args.role,)):
    files = json.loads(row["files_json"] or "{}")
    meta = json.loads(row["meta_json"] or "{}")
    inner = dict(meta.get("meta") or {})
    npz = root / files["arrays"]
    with np.load(npz, allow_pickle=False) as data:
        keys = [k for k in data.files if k.endswith("surface_tag")]
        total = 0
        rim = 0
        hist: dict[str, int] = {}
        per_view = {}
        for key in sorted(keys):
            tag = np.asarray(data[key])
            values, counts = np.unique(tag, return_counts=True)
            view_hist = {str(int(k)): int(v) for k, v in zip(values, counts)}
            for k, v in view_hist.items():
                hist[k] = hist.get(k, 0) + v
            total += int(tag.size)
            rim += int(view_hist.get("2", 0))
            per_view[key.split(".")[0]] = {"pixels": int(tag.size), "rim": int(view_hist.get("2", 0)),
                                           "histogram": view_hist}
    print(f"{row['asset_id']} {row['lineage_id']} views={len(per_view)} pixels={total} rim={rim} "
          f"({(rim / total if total else 0):.6f}) hist={hist}")
    print("   meta.surface_tag_pixels:", json.dumps(inner.get("surface_tag_pixels"))[:400])
    print("   meta.surface_tag_source:", inner.get("surface_tag_source"),
          "| target_meta.source:", (inner.get("target_meta") or {}).get("surface_tag_source"))
    for view, entry in per_view.items():
        print(f"   {view}: pixels={entry['pixels']} rim={entry['rim']} hist={entry['histogram']}")
