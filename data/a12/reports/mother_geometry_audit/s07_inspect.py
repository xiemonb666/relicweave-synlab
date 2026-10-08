"""Step 7 (read-only): inspect a few individual part records in full."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PARTS = Path(__file__).resolve().parent / "parts"

for vessel_id in sys.argv[1:]:
    d = json.loads((PARTS / f"{vessel_id}.json").read_text(encoding="utf-8"))
    print(f"===== {vessel_id}  status={d['status']} family={d['family']} params_source={d['params_source']}")
    print("params:", json.dumps(d["params"], sort_keys=True))
    if d["status"] != "OK":
        print("error:", (d.get("error") or "")[:800])
        continue
    print("bbox_mm:", d["mesh"]["bbox_mm"])
    print("declared:", d["declared_z_extent_mm"], "|", d["declared_source"])
    print("profile_metrics:", json.dumps(d["profile_metrics"], sort_keys=True))
    print("body:", json.dumps(d["body"], indent=1, sort_keys=True))
    print("components:", json.dumps(d["components"], indent=1, sort_keys=True))
    print("gaps:", json.dumps(d["component_gaps"], indent=1, sort_keys=True))
    print("silhouette z:", d["silhouette"]["normalised"]["z"])
    print("silhouette r:", d["silhouette"]["normalised"]["r"])
    print("audit:", json.dumps(d["audit"], sort_keys=True)[:800])
    print()
