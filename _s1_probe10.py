import json, numpy as np
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
aid = "asset_bd3812b8c9b5059ac091"
rec = st.get_asset(aid)
print("role", rec.role, "schema", rec.schema, "lineage", rec.lineage_id, "split", rec.split)
meta = dict(rec.meta or {})
print("meta keys", sorted(meta.keys()))
for k in ("fragment_ids","fragment_id","source_kind","pair","kind","a","b"):
    if k in meta: print(" meta", k, "=", json.dumps(meta[k], ensure_ascii=False)[:300])
arr = st.load_arrays(aid)
print("ARRAYS:")
for k in sorted(arr):
    v = arr[k]
    print(f"  {k:28s} shape={getattr(v,'shape',None)} dtype={getattr(v,'dtype',None)}")
