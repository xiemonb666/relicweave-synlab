"""Scratch: follow one lineage's ancestry chain and show exactly where the closure breaks."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
con = sqlite3.connect(str(ROOT / "data/a12/metadata.sqlite"))
con.row_factory = sqlite3.Row
rows = {r["asset_id"]: dict(r) for r in con.execute(
    "select asset_id, role, qa_status, lineage_id, ancestry_json, meta_json from assets")}

target = None
for aid, row in rows.items():
    if row["role"] == "obs_result" and row["lineage_id"] and row["qa_status"] == "QA_PASS":
        meta = json.loads(row["meta_json"] or "{}")
        if meta.get("run_id"):
            target = aid
print("inspecting", target, rows[target]["lineage_id"] if target else None)

seen: set[str] = set()
queue = [(target, 0)]
while queue:
    aid, depth = queue.pop(0)
    if aid in seen:
        continue
    seen.add(aid)
    row = rows.get(aid)
    pad = "  " * depth
    if row is None:
        print(f"{pad}MISSING {aid}")
        continue
    meta = json.loads(row["meta_json"] or "{}")
    print(f"{pad}{row['role']:20s} {row['qa_status']:11s} {aid}  run={meta.get('run_id')}")
    for anc in json.loads(row["ancestry_json"] or "[]"):
        queue.append((anc, depth + 1))
