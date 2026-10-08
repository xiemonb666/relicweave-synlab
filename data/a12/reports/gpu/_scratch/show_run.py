"""Print a one-run benchmark report compactly (scratch helper)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

for arg in sys.argv[1:]:
    p = Path(arg)
    if not p.is_file():
        print(f"--- {arg}: MISSING")
        continue
    r = json.loads(p.read_text(encoding="utf-8"))
    sel = r.get("resolved_device_selection") or {}
    print(f"--- {p.name}")
    print(f"    device_requested={r.get('device_requested')} "
          f"resolved={sel.get('resolved_device')}/{sel.get('resolved_compute_device_type')} "
          f"require_gpu={r.get('gpu_require')} fallback={sel.get('fallback')}")
    print(f"    views={r.get('views')} total_wall={r.get('total_wall_seconds_incl_process_start')}s "
          f"per_view={r.get('seconds_per_view_incl_process_start')}s")
    print(f"    sum_worker_wall={r.get('sum_worker_wall_seconds')}s "
          f"sum_inproc={r.get('sum_worker_inprocess_elapsed_seconds')}s "
          f"sum_render_pass={r.get('sum_render_pass_seconds')}s "
          f"proc_overhead={r.get('process_start_overhead_seconds')}s")
    vram = r.get("vram")
    if vram:
        print(f"    vram peak={vram.get('peak_used_mb')}MB delta={vram.get('peak_delta_mb')}MB "
              f"total={vram.get('total_mb')}MB")
    load = r.get("system_cpu_load_during_run") or {}
    print(f"    cpu_load mean={load.get('mean_percent')}% max={load.get('max_percent')}%")
    views = r.get("per_view") or []
    if views:
        rs = [v.get("render_seconds") or {} for v in views]
        for tag in ("rgb", "geometry_exact", "geometry_aa", "geometry_targetonly"):
            vals = [float(x.get(tag, 0.0)) for x in rs]
            if vals:
                print(f"      {tag:20s} sum={sum(vals):8.2f}s  per_view_avg={sum(vals)/len(vals):7.3f}s")
        ww = [float(v.get("worker_wall_seconds") or 0.0) for v in views]
        ie = [float(v.get("worker_elapsed_seconds") or 0.0) for v in views]
        print(f"      worker_wall per view avg={sum(ww)/len(ww):.3f}s  "
              f"inproc per view avg={sum(ie)/len(ie):.3f}s")
        st = [v.get("raycast_status") for v in views]
        print(f"      raycast statuses: {sorted(set(st))}")
