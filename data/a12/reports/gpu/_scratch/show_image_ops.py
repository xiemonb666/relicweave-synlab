"""Print the image-ops benchmark report (scratch helper)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

p = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    Path("data/a12/reports/gpu/image_ops.json")
d = json.loads(p.read_text(encoding="utf-8"))
print("device  :", d["device"], "| torch", d["torch"], "| res", d["resolution"],
      "| ch", d["channels"])
print("cpu ref :", d["cpu_reference"])
print("gpu impl:", d["gpu_impl"])
eq = d["equivalence"]
print(f"equivalence check: kernel={eq['kernel_shape']} max={eq['max_abs_diff']:.3g} "
      f"bitwise={eq['bitwise_equal']} equivalent={eq['equivalent']}")
print()
print("PIPELINE WORKLOAD (12 views, 1024x768x3, depth-dependent defocus pair):")
for k, v in d["pipeline_workload_12_views"].items():
    print(f"  {k:16s} kernel={str(v['kernel_shape']):>9s} cpu={v['cpu_seconds']:.4f}s "
          f"gpu={v['gpu_seconds']:.4f}s speedup={v['speedup']}x "
          f"maxdiff={v['max_abs_diff']:.3g} within1e-5={v['within_1e-5']}")
t = d["pipeline_workload_total"]
print(f"  TOTAL cpu={t['cpu_seconds']}s gpu={t['gpu_seconds']}s speedup={t['speedup']}x")
print()
print("SWEEP (batch x sigma):")
print(f"  {'batch':>5} {'sigma':>6} {'k':>3} {'cpu_s':>9} {'gpu_s':>9} {'speedup':>8} "
      f"{'maxdiff':>10}  worth")
for r in d["sweep"]:
    print(f"  {r['batch']:>5} {r['sigma_px']:>6} {r['kernel']:>3} {r['cpu_seconds']:>9.4f} "
          f"{r['gpu_seconds']:>9.4f} {str(r['speedup']):>8} {r['max_abs_diff']:>10.3g}  "
          f"{r['gpu_worth_it']}")
