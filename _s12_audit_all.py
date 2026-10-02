"""S12: dump the frozen 31-axis / 155-level audit contract (baseline must not regress)."""

import json
import time

from synlab.degrade.api import audit_all_axes

t0 = time.perf_counter()
rep = audit_all_axes(store=None, levels=[0, 1, 2, 3, 4])
print("seconds", round(time.perf_counter() - t0, 2))
print("keys:", list(rep.keys()))
for k in ("ok", "identity_ok", "all_axes_pass", "failing_axes", "contract", "limits"):
    print(" ", k, "=", json.dumps(rep.get(k), default=str)[:1200])
den = rep.get("denominators")
if isinstance(den, dict):
    for k, v in den.items():
        print("  denom.", k, "=", v)
axes = rep.get("axes")
print("axes container:", type(axes).__name__)
bad = []
if isinstance(axes, dict):
    for aid, entry in axes.items():
        levels = (entry or {}).get("levels") if isinstance(entry, dict) else entry
        if isinstance(levels, dict):
            items = levels.items()
        elif isinstance(levels, list):
            items = [(str((v or {}).get("level", i)), v) for i, v in enumerate(levels)]
        else:
            items = []
        for lv, val in items:
            st = (val or {}).get("status") if isinstance(val, dict) else val
            if str(st) != "PASS":
                bad.append((aid, lv, st))
elif isinstance(axes, list):
    for entry in axes:
        aid = (entry or {}).get("axis_id") if isinstance(entry, dict) else str(entry)
        for val in (entry or {}).get("levels", []) if isinstance(entry, dict) else []:
            st = (val or {}).get("status") if isinstance(val, dict) else val
            if str(st) != "PASS":
                bad.append((aid, (val or {}).get("level"), st))
print("non-PASS levels:", len(bad))
for row in bad[:30]:
    print("   ", row)
with open("data/a12_reports/s12_audit_all_axes.json", "w", encoding="utf-8") as handle:
    json.dump(rep, handle, default=str, indent=1, sort_keys=True)
