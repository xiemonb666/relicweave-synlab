"""Print one line per recorded survey row (per shard)."""

import json
import sys
from pathlib import Path

names = sys.argv[1:] or ["survey_finalA", "survey_finalB", "survey_repro3", "survey_v23_before",
                         "frozenA", "frozenB"]
for name in names:
    path = Path(name)
    if not path.exists():
        path = Path("data/a12_smoke/_tmp") / (name if name.endswith(".json") else name + ".json")
    if not path.exists():
        print(f"--- {name}: MISSING")
        continue
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get("lineages", [])
    print(f"--- {path.name}: {len(rows)} rows")
    for r in rows:
        print("   ", r["vessel_id"], r["lineage_id"], "OK" if r["ok"] else "FAIL",
              r.get("error_code"), f"frag={r.get('fragments')}", f"obs={r.get('observations')}",
              f"r2={r.get('r2_pairs')}", f"{r.get('seconds')}s")
