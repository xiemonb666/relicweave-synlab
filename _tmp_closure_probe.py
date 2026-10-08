"""Scratch: where do the dangling ancestors of the batch's QA_PASS assets come from?"""

from __future__ import annotations

import collections
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
con = sqlite3.connect(str(ROOT / "data/a12/metadata.sqlite"))
con.row_factory = sqlite3.Row
led = json.loads((ROOT / "data/a12/reports/next_experiment_batches.json").read_text(encoding="utf-8"))
runs = {row["run_id"] for row in led.get("batches", []) if row.get("run_id")}

assets = {}
for row in con.execute("select asset_id, role, qa_status, lineage_id, ancestry_json, meta_json "
                       "from assets"):
    meta = json.loads(row["meta_json"] or "{}")
    if meta.get("run_id") not in runs:
        continue
    assets[row["asset_id"]] = {
        "role": row["role"], "qa": row["qa_status"], "lineage": row["lineage_id"],
        "ancestry": json.loads(row["ancestry_json"] or "[]"),
    }

print("batch-run assets:", len(assets))
by_role = collections.Counter((a["role"], a["qa"]) for a in assets.values())
for (role, qa), n in sorted(by_role.items()):
    print(f"  {role:22s} {qa:12s} {n}")

print("\nassets with dangling ancestry (ancestor id not an asset id):")
dangling = collections.Counter()
for aid, entry in assets.items():
    for anc in entry["ancestry"]:
        if anc not in assets:
            dangling[(entry["role"], anc.split(":")[0] == anc and "NOT_AN_ID" or "TRUTH_REF")] += 1
print("  total dangling refs:", sum(dangling.values()))
for key, n in dangling.most_common(10):
    print("   ", key, n)

print("\nwhich roles point at the truth refs:")
for aid, entry in list(assets.items()):
    if any(anc not in assets for anc in entry["ancestry"]):
        print(f"  {entry['role']:22s} qa={entry['qa']:10s} lineage={entry['lineage']}")
        break

# count how many of each role would survive a closed QA_PASS-only sub-DAG
keep = {aid for aid, e in assets.items() if e["qa"] == "QA_PASS"}
while True:
    drop = {aid for aid in keep if any(anc not in keep for anc in assets[aid]["ancestry"])}
    if not drop:
        break
    keep -= drop
print("\nclosed QA_PASS-only sub-DAG:", len(keep), "of", len(keep) + len(drop))
print("roles kept:", dict(collections.Counter(assets[a]["role"] for a in keep)))
dropped_roles = collections.Counter(assets[a]["role"] for a in assets if a not in keep)
print("roles dropped:", dict(dropped_roles))
