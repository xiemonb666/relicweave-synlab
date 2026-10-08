"""Print one pioneer lineage per vessel (index, id, material, pattern)."""
import json
from pathlib import Path

rows = json.loads(Path("data/a12_smoke/_tmp/plan.json").read_text(encoding="utf-8"))
first = {}
for r in rows:
    first.setdefault(r["V"], r)
out = []
for k, v in sorted(first.items()):
    out.append(f"{k} idx={v['i']:3d} {v['lid']} {v['M']} {v['P']} {v['L']}")
Path("data/a12_smoke/_tmp/plan_table.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))
print("total lineages:", len(rows))
print("indices:", ",".join(str(v["i"]) for _, v in sorted(first.items())))
