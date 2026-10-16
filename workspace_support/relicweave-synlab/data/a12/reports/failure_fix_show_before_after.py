"""Print the before/after rows of ``failure_mode_before_after.json`` as a table."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
data = json.loads((ROOT / "data" / "a12" / "reports" /
                   "failure_mode_before_after.json").read_text(encoding="utf-8"))
for key in ("before_current_plan_attempts", "after_fixed_code_attempts"):
    block = data[key]
    print(f"== {key}: attempted={block['attempted']} accepted={block['accepted']} "
          f"rate={block['acceptance_rate']}")
    for row in block["outcomes"]:
        print(f"  {row['at']} {row['lineage_id']:26s} {str(row['vessel_id']):4s} "
              f"{str(row['material_id']):4s} {str(row['pattern_id']):6s} "
              f"{row['class'][:30]:32s} {str(row['seconds']):>8s} "
              f"{(row['error_message'] or '')[:64]}")
    counts = Counter((row["lineage_id"], row["class"]) for row in block["outcomes"])
    print("  distinct lineage/class pairs:")
    for key2, value in sorted(counts.items()):
        print(f"     {value:3d}  {key2}")
    print()
