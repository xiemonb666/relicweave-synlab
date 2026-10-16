"""Step 6 (read-only): compact summary of the 24 per-vessel part records."""
from __future__ import annotations

import json
from pathlib import Path

PARTS = Path(__file__).resolve().parent / "parts"

for path in sorted(PARTS.glob("*.json")):
    d = json.loads(path.read_text(encoding="utf-8"))
    if d["status"] != "OK":
        print(f"== {d['vessel_id']} {d['status']}")
        print((d.get("error") or "")[:1200])
        print()
        continue
    b, m = d["body"], d["mesh"]
    taper = (d.get("body_wall_taper") or {}).get("taper")
    print(f"{d['vessel_id']} decl={d['declared_z_extent_mm']:8.3f} "
          f"bodyz=[{b['z_min']:7.2f},{b['z_max']:8.3f}] ext={b['z_extent_mm']:8.3f} "
          f"probshort={b['profile_shortfall_mm']!s:>9.9} "
          f"extshort={b['extent_shortfall_mm']!s:>9.9} bodies={m['n_bodies']} "
          f"gap={d['max_positive_gap_mm']:7.3f} taper={taper!s:>6.6} "
          f"topR={b['top_over_max_radius_ratio']!s:>6.6} vol={m['volume_mm3']:12.1f} "
          f"wt={m['watertight']} audit={d['audit']['ok']} "
          f"fail={[f.get('check') for f in d['audit']['failures']]}")
