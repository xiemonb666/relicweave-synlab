"""Check whether pre/post parts used the same parameters (read-only)."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PRE = REPO / "data/a12/reports/mother_geometry_audit/parts"
POST = REPO / "data/a12/reports/geom_fix/parts"

for i in range(1, 25):
    vid = f"V{i:02d}"
    pre = json.loads((PRE / f"{vid}.json").read_text(encoding="utf-8"))
    post = json.loads((POST / f"{vid}.json").read_text(encoding="utf-8"))
    pp, qp = pre.get("params") or {}, post.get("params") or {}
    if pp == qp:
        continue
    keys = sorted(set(pp) | set(qp))
    diffs = {k: (pp.get(k), qp.get(k)) for k in keys if pp.get(k) != qp.get(k)}
    print(f"{vid}: params DIFFER  pre_src={pre.get('params_source')} post_src={post.get('params_source')}")
    for k, (a, b) in diffs.items():
        print(f"     {k}: {a} -> {b}")
print("done")
