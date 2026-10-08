"""Print the worker-mix benchmark: per-view cost of the real 6-pass sequence (scratch helper)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/a12/reports/gpu/worker_mix.json")
d = json.loads(p.read_text(encoding="utf-8"))
print(f"res {d['resolution']} faces {d['faces']} blender {d['blender']} "
      f"views/device {d['views_per_device']}")
print(f"worker mix (samples): {d['worker_mix']}  ->  {d['worker_mix_labels']}")
print()
base = None
for r in d["results"]:
    v = r["view_seconds"]
    print(f"--- {r['device']:6s} enabled={r['device_info'].get('enabled')} "
          f"readback={r['device_info'].get('readback')}")
    print(f"    per-view totals : {[round(x, 3) for x in v]}")
    print(f"    cold view       : {r['cold_view_seconds']:.3f}s")
    print(f"    warm view (best): {r['warm_view_seconds']:.3f}s")
    if base is None:
        base = r["warm_view_seconds"]
        print(f"    warm/cold ratio : {r['warm_view_seconds'] / r['cold_view_seconds']:.3f} "
              f"(init cost = {r['cold_view_seconds'] - r['warm_view_seconds']:.3f}s)")
    else:
        print(f"    warm speedup vs CPU: {base / r['warm_view_seconds']:.2f}x   "
              f"cold speedup vs CPU: "
              f"{d['results'][0]['cold_view_seconds'] / r['cold_view_seconds']:.2f}x")
    first = r["views"][0]["renders"]
    print(f"    cold-view pass times: "
          + ", ".join(f"{x['pass']}={x['seconds']:.3f}" for x in first))
    if len(r["views"]) > 1:
        warm = min(r["views"][1:], key=lambda x: x["view_seconds"])["renders"]
        print(f"    warm-view pass times: "
              + ", ".join(f"{x['pass']}={x['seconds']:.3f}" for x in warm))
    print()
