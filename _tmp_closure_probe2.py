"""Scratch: which roles have *every* asset resolvable, and what a closed QA_PASS sub-DAG costs?

The distinguishing question: a dangling ancestor is only fatal for ``verify_closure`` when the
asset is inside the frozen scope.  So compute, for each role, how many of its QA_PASS assets would
survive a closed sub-DAG rooted at that role plus the roles below it.
"""

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

assets: dict[str, dict] = {}
for row in con.execute("select asset_id, role, qa_status, lineage_id, ancestry_json, meta_json "
                       "from assets"):
    meta = json.loads(row["meta_json"] or "{}")
    if meta.get("run_id") not in runs:
        continue
    assets[row["asset_id"]] = {
        "role": row["role"], "qa": row["qa_status"], "lineage": row["lineage_id"],
        "ancestry": json.loads(row["ancestry_json"] or "[]"),
    }

def closed(seed_role: str) -> tuple[set[str], int]:
    """All QA_PASS assets of ``seed_role`` closed upwards, then pruned until closed."""
    keep = {aid for aid, a in assets.items() if a["qa"] == "QA_PASS"}
    # walk down from the seed role to collect the needed ancestors
    need: set[str] = {aid for aid, a in assets.items()
                      if a["role"] == seed_role and a["qa"] == "QA_PASS"}
    stack = list(need)
    while stack:
        aid = stack.pop()
        for anc in assets.get(aid, {}).get("ancestry", []):
            if anc in assets and anc not in need:
                need.add(anc)
                stack.append(anc)
    # prune anything whose ancestry leaves the set
    need &= keep
    while True:
        drop = {aid for aid in need if any(anc not in need for anc in assets[aid]["ancestry"])}
        if not drop:
            break
        need -= drop
    return need, len(drop)

for role in ("obs_result", "feature_bundle", "label_bundle", "clean_truth", "mother_mesh"):
    keep, dropped_round = closed(role)
    roles = collections.Counter(assets[a]["role"] for a in keep)
    print(f"\nseed role {role}: closed set = {len(keep)} assets, pruned {dropped_round} in last round")
    for r, n in sorted(roles.items()):
        total = sum(1 for a in assets.values() if a["role"] == r and a["qa"] == "QA_PASS")
        print(f"    {r:22s} {n:4d} / {total} QA_PASS")
