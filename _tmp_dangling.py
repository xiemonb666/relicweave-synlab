"""Scratch: current dangling-ancestry census for the batch (after the applied repair)."""

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

dangling = collections.Counter()
examples: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
for aid, row in rows.items():
    meta = json.loads(row["meta_json"] or "{}")
    if meta.get("run_id") not in runs:
        continue
    for anc in json.loads(row["ancestry_json"] or "[]"):
        if anc in rows:
            continue
        key = row["role"]
        dangling[key] += 1
        if len(examples[key]) < 2:
            examples[key].append((aid, anc))

print("dangling ancestors by role:")
for role, n in dangling.most_common():
    print(f"  {role:22s} {n}")
print()
for role, items in examples.items():
    for aid, anc in items:
        print(f"  {role:20s} {aid} -> {anc}")

# how many QA_FAIL / QA_PENDING ancestors block the observation branch
print("\nQA status of ancestors of batch obs_result assets:")
bad = collections.Counter()
for aid, row in rows.items():
    meta = json.loads(row["meta_json"] or "{}")
    if row["role"] != "obs_result" or meta.get("run_id") not in runs:
        continue
    for anc in json.loads(row["ancestry_json"] or "[]"):
        target = rows.get(anc)
        if target is None:
            bad["MISSING"] += 1
        elif target["qa_status"] != "QA_PASS":
            bad[f'{target["role"]}/{target["qa_status"]}'] += 1
print(dict(bad))
