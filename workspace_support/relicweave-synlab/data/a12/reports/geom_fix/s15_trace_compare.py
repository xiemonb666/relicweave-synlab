"""Pre-fix vs post-fix helper trace: radius span and dropped control points (read-only)."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PRE = REPO / "data/a12/reports/mother_geometry_audit/s05_trace.json"
POST = REPO / "data/a12/reports/geom_fix/trace_parts"

pre = json.loads(PRE.read_text(encoding="utf-8"))
print(f"{'vid':4} {'pre_span':>10} {'post_span':>10} {'pre_drop':>8} {'post_drop':>9}")
rows = []
for i in range(1, 25):
    vid = f"V{i:02d}"
    p = pre.get(vid) or {}
    calls = p.get("calls") or p.get("trace") or []
    pspan = None
    pdrop = 0
    for c in calls:
        if c.get("helper") == "wall_points":
            s = c.get("out_r_span")
            pspan = s if pspan is None else max(pspan, s)
        elif "monotone" in str(c.get("helper", "")):
            pdrop += int(c.get("n_in", 0) - c.get("n_out", 0))
    post_file = POST / f"{vid}.json"
    post = json.loads(post_file.read_text(encoding="utf-8")) if post_file.exists() else {}
    rows.append({"vessel_id": vid, "pre_span": pspan, "post_span": post.get("wall_points_r_span_max"),
                 "pre_dropped": pdrop, "post_dropped": post.get("filter_dropped_total")})
    print(f"{vid:4} {str(round(pspan,4) if isinstance(pspan,(int,float)) else pspan):>10} "
          f"{str(round(post.get('wall_points_r_span_max'),4) if isinstance(post.get('wall_points_r_span_max'),(int,float)) else post.get('wall_points_r_span_max')):>10} "
          f"{pdrop:8d} {str(post.get('filter_dropped_total')):>9}")

out = REPO / "data/a12/reports/geom_fix/s15_trace_compare.json"
out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", out)
