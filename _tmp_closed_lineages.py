"""Scratch: which lineages have a *fully closed, all-QA_PASS* ancestry (mother -> observation)?

Only those can enter a frozen release that still carries observations.  Reports the blocking
ancestor for every lineage that cannot.
"""

from __future__ import annotations

import collections
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
con = sqlite3.connect(str(ROOT / "data/a12/metadata.sqlite"))
con.row_factory = sqlite3.Row
rows = {r["asset_id"]: dict(r) for r in con.execute(
    "select asset_id, role, qa_status, lineage_id, ancestry_json, meta_json from assets")}
led = json.loads((ROOT / "data/a12/reports/next_experiment_batches.json").read_text(encoding="utf-8"))
runs = {row["run_id"] for row in led.get("batches", []) if row.get("run_id")}

accepted = sorted({r["lineage_id"] for r in rows.values()
                   if r["role"] == "label_bundle" and r["qa_status"] == "QA_PASS"
                   and r["lineage_id"] and json.loads(r["meta_json"] or "{}").get("run_id") in runs})
print("accepted lineages in this batch's runs:", len(accepted))

fully: list[str] = []
for lin in accepted:
    # walk the whole ancestry of every asset of this lineage
    root_ids = [aid for aid, r in rows.items()
                if r["lineage_id"] == lin and r["qa_status"] == "QA_PASS"
                and json.loads(r["meta_json"] or "{}").get("run_id") in runs]
    seen: set[str] = set()
    queue = list(root_ids)
    blockers: list[str] = []
    while queue:
        aid = queue.pop()
        if aid in seen:
            continue
        seen.add(aid)
        row = rows.get(aid)
        if row is None:
            blockers.append(f"MISSING:{aid}")
            continue
        if row["qa_status"] != "QA_PASS":
            blockers.append(f'{row["role"]}/{row["qa_status"]}:{aid}')
        queue.extend(json.loads(row["ancestry_json"] or "[]"))
    ok = not blockers
    print(f'  {lin:26s} roles={len(seen):3d} closed={ok}'
          + ("" if ok else f'  blockers={blockers[:2]}'))
    if ok:
        fully.append(lin)

print("\nfully closed + QA_PASS lineages:", len(fully))
for lin in fully:
    print("   ", lin)
