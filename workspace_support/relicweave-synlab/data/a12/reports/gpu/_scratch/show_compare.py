"""Print the full per-channel diff detail from a compare report (scratch helper)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

r = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
n_px = None
print("speedup_total_wall :", r["speed"]["speedup_total_wall"])
print("speedup_render_pass:", r["speed"]["speedup_render_pass"])
print("views hash-identical:", r["n_views_hash_identical"], "/", r["n_views"])
print()
hdr = f"{'channel':18s} {'bitwise':>7s} {'ndiff':>9s} {'frac':>10s} {'max':>12s} " \
      f"{'p99':>12s} {'median':>8s} {'nan_mismatch':>12s}"
print(hdr)
for name, d in r["channel_diff_cpu_vs_gpu"].items():
    if "max_abs_diff" not in d:
        print(f"{name:18s} {d.get('status')}")
        continue
    print(f"{name:18s} {str(d['identical_bitwise']):>7s} {d['n_differing']:>9d} "
          f"{d['fraction_differing']:>10.3e} {d['max_abs_diff']:>12.6g} "
          f"{d['p99_abs_diff']:>12.6g} {d['median_abs_diff']:>8.3g} "
          f"{d['nan_mismatch_px']:>12d}")
print()
print("total elements per channel:",
      r["channel_diff_cpu_vs_gpu"]["rgb_linear"]["n_compared"])
