"""Probe 4: obs_result meta structure (camera / light / view / noise source) + views sample."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data" / "a12"

conn = sqlite3.connect(f"file:{(STORE / 'metadata.sqlite').as_posix()}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT * FROM assets WHERE role='obs_result' AND lineage_id LIKE 'LIN00%' "
                   "ORDER BY created_at LIMIT 1").fetchone()
meta = json.loads(row["meta_json"])
print("top keys:", sorted(meta.keys()))
for k, v in meta.items():
    if k in ("quality", "views"):
        print(f"\n-- {k}: type={type(v).__name__} "
              f"len={len(v) if hasattr(v,'__len__') else '-'}")
        if k == "views":
            print("   sample view keys:", sorted(v[0].keys()) if v else None)
            print("   view0:", json.dumps(v[0], ensure_ascii=False, default=str)[:2000])
        continue
    print(f"\n-- {k}: {json.dumps(v, ensure_ascii=False, default=str)[:1400]}")
conn.close()
