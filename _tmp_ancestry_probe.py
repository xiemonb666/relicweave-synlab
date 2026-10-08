"""Scratch: show the exact ancestry strings that do not resolve to asset ids."""

from __future__ import annotations

import collections
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
con = sqlite3.connect(str(ROOT / "data/a12/metadata.sqlite"))
con.row_factory = sqlite3.Row
ids = {r["asset_id"] for r in con.execute("select asset_id from assets")}

bad = collections.Counter()
examples: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
for row in con.execute("select asset_id, role, qa_status, lineage_id, ancestry_json from assets "
                       "where lineage_id like 'LIN%'"):
    for anc in json.loads(row["ancestry_json"] or "[]"):
        if anc in ids:
            continue
        key = f'{row["role"]} -> {anc.split(":")[0][:40]}'
        bad[key] += 1
        if len(examples[row["role"]]) < 3:
            examples[row["role"]].append((row["asset_id"], anc))

for key, n in bad.most_common(20):
    print(f"{n:4d}  {key}")
print()
for role, items in examples.items():
    print("==", role)
    for aid, anc in items:
        print("   ", aid, "->", anc)
