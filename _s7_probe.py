import numpy as np, json
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
r = st.list_assets(role="obs_result", limit=1)[0]
m = dict(r.meta or {})
q = m.get("quality") or {}
print("obs quality channels:", len(q))
rows = []
for k, v in sorted(q.items()):
    if not isinstance(v, dict): continue
    rows.append((k, v.get("source_kind"), v.get("unit"), v.get("valid"), v.get("value"), v.get("estimator_version")))
for row in rows[:12]:
    print("   %-34s src=%-9s unit=%-4s valid=%-5s value=%s est=%s" % tuple(str(x) for x in row))
print("total channels:", len(rows), " valid:", sum(1 for x in rows if x[3]))
