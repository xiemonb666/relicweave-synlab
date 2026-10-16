"""Group the before ledger by ``run_id`` (one id = one batch invocation = one loaded code state)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
led = json.loads((ROOT / "data" / "a12" / "reports" /
                  "next_experiment_batches.json").read_text(encoding="utf-8"))
groups: dict[str, list[dict]] = {}
for row in led.get("batches", []):
    groups.setdefault(str(row.get("run_id")), []).append(row)
print(f"{'run_id':26s} {'first':>8s} {'last':>8s} {'n':>3s}  outcomes")
for run_id, rows in groups.items():
    first = datetime.fromtimestamp(rows[0]["at"]).strftime("%H:%M:%S")
    last = datetime.fromtimestamp(rows[-1]["at"]).strftime("%H:%M:%S")
    outcomes = []
    for row in rows:
        state = "OK" if row.get("ok") else str(row.get("error")).replace("ErrorCode.", "")
        outcomes.append(f"{row['lineage_id'].split('_',1)[0]}:{state}")
    print(f"{run_id:26s} {first:>8s} {last:>8s} {len(rows):3d}  {' '.join(outcomes)}")
print("\ncode-fix timestamps (mtime of the edited modules):")
for name in ("synlab/mothers/api.py", "synlab/patterns/glyphs.py", "synlab/patterns/builders.py",
             "synlab/mothers/vessels/group_composite.py", "synlab/pipeline.py"):
    path = ROOT / name
    print(f"  {name:46s} {datetime.fromtimestamp(path.stat().st_mtime):%H:%M:%S}")
