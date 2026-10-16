"""Print the exact LIN0004 component z spans before and after (both gap conventions)."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
pre = json.loads((REPO / "data/a12/reports/mother_geometry_audit/s04_frozen_repro.json")
                 .read_text(encoding="utf-8"))
post = json.loads((REPO / "data/a12/reports/geom_fix/s14_frozen_after.json")
                  .read_text(encoding="utf-8"))

for tag, payload in (("BEFORE", pre), ("AFTER", post)):
    row = payload["LIN0004_V10_M06_PAT03"]
    comps = sorted(row["components"], key=lambda c: c["z_min"])
    print(f"== {tag}  n={len(comps)} max_positive_gap={row.get('max_positive_gap_mm')}")
    for c in comps:
        print(f"   #{c['index']} faces={c['faces']:6d} vol={c['volume_mm3']:14.3f} "
              f"z=[{c['z_min']:.4f}, {c['z_max']:.4f}]")
    for lower, upper in zip(comps, comps[1:]):
        print(f"   gap {lower['index']}->{upper['index']} = "
              f"{upper['z_min'] - lower['z_max']:+.4f} mm")
    if row.get("component_gaps"):
        print("   recorded component_gaps:", json.dumps(row["component_gaps"], default=str)[:400])
