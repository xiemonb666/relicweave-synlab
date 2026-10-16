"""Quantify the base-outline side effect of the z-advance rule (read-only)."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PRE = REPO / "data/a12/reports/mother_geometry_audit/parts"
POST = REPO / "data/a12/reports/geom_fix/parts_run2"

for vid in ("V01", "V12", "V15", "V17"):
    a = json.loads((PRE / f"{vid}.json").read_text(encoding="utf-8"))
    b = json.loads((POST / f"{vid}.json").read_text(encoding="utf-8"))
    print(vid)
    for tag, d in (("pre ", a), ("post", b)):
        m = d["mesh"]
        print("  %s z=[%.3f,%.3f] bbox=%s vol=%.1f bodies=%s r_max=%s" % (
            tag, m["z_min"], m["z_max"], [round(x, 2) for x in m["bbox_mm"]],
            m["volume_mm3"], m["n_bodies"],
            (d.get("profile_metrics") or {}).get("r_max")))
        sil = d.get("silhouette") or {}
        rows = sil.get("bins") if isinstance(sil, dict) else None
        if rows:
            for r in rows[:4]:
                print("       ", json.dumps(r, ensure_ascii=False))
    print()
