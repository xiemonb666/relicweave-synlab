import json, numpy as np
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
seen = {}
for r in st.list_assets(role="obs_result", limit=500):
    m = dict(r.meta or {}); fid = m.get("fragment_id")
    for v in (m.get("views") or []):
        prof = v.get("profile_id"); u = v.get("u_position_mm"); wd = v.get("working_distance_mm")
        seen.setdefault(prof, []).append((u, wd))
for prof, vals in sorted(seen.items(), key=lambda kv: str(kv[0])):
    u = np.asarray([x[0] for x in vals], float); w = np.asarray([x[1] for x in vals], float)
    print(f"{str(prof):32s} n={len(vals):4d} u range [{np.nanmin(u):.2f}, {np.nanmax(u):.2f}] unique_u={np.unique(u).size} wd range [{np.nanmin(w):.1f}, {np.nanmax(w):.1f}]")
print()
import collections
print("T_WC[0,3] per profile (from obs arrays) would be authoritative; u_position_mm field above is the metadata copy")
