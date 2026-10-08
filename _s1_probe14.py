import numpy as np, json
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
for aid in ("asset_1beedec77f25cbda2f2f", "asset_b7d01b160094c06eff9b"):
    rec = st.get_asset(aid); meta = dict(rec.meta or {})
    arr = st.load_arrays(aid)
    print("=== fragment_mesh", aid, "fragment_id", meta.get("fragment_id"))
    print("   keys", sorted(arr)[:20])
    for k in sorted(arr):
        if "vert" in k or "point" in k or "face" in k:
            try: print("   ", k, np.asarray(arr[k]).shape)
            except Exception as e: print("   ", k, "ERR", e)
    print("   meta sample", json.dumps({k:v for k,v in meta.items() if k in ("n_points","n_vertices","scale","unit","frame","points_hash")}, ensure_ascii=False)[:300])
