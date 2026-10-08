"""Summarise the Cycles device sweep into a printable table (scratch helper)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]  # <root>/data/a12/reports/gpu/_scratch/this.py
path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    ROOT / "data" / "a12" / "reports" / "gpu" / "device_sweep.json"
d = json.loads(path.read_text(encoding="utf-8"))
print("resolution", d["resolution"], "faces", d["faces"], "blender", d["blender"],
      "repeat", d["repeat"])
rows: dict[int, dict[str, float]] = {}
info: dict[str, dict] = {}
for r in d["results"]:
    rows.setdefault(r["samples"], {})[r["device"]] = r["best_seconds"]
    info[r["device"]] = r["device_info"]
print()
print(f"{'spp':>5} {'CPU_s':>9} {'CUDA_s':>9} {'OPTIX_s':>9} {'CUDA_x':>8} {'OPTIX_x':>8}")
for s in sorted(rows):
    c = rows[s].get("CPU")
    cu = rows[s].get("CUDA")
    op = rows[s].get("OPTIX")

    def ratio(v):
        return f"{c / v:8.2f}" if (c and v) else "     n/a"
    print(f"{s:>5} {c:>9.3f} {cu:>9.3f} {op:>9.3f} {ratio(cu)} {ratio(op)}")
print()
for dev in ("CPU", "CUDA", "OPTIX"):
    print(dev, json.dumps({k: v for k, v in info.get(dev, {}).items()
                           if k in ("readback", "enabled", "cycles_device", "set_error")},
                          ensure_ascii=False))
