"""Report first-vs-best repeat timing from the device sweep (scratch helper).

The real pipeline spawns ONE Blender process per view, so a one-time per-process GPU
initialisation cost is paid 12 times.  ``best of N`` hides it; this prints every repeat.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    ROOT / "data" / "a12" / "reports" / "gpu" / "device_sweep.json"
d = json.loads(path.read_text(encoding="utf-8"))
print(f"{'dev':>6} {'spp':>5}  repeats (s)")
for r in d["results"]:
    times = ", ".join(f"{t:.3f}" for t in r["seconds"])
    first, best = r["seconds"][0], min(r["seconds"])
    print(f"{r['device']:>6} {r['samples']:>5}  [{times}]  first={first:.3f} best={best:.3f} "
          f"init_gap={first - best:+.3f}")
