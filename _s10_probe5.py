import numpy as np
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
recs = [r for r in st.list_assets(role="obs_result", limit=500)][:3]
for r in recs:
    m = dict(r.meta or {}); fid = m.get("fragment_id")
    arr = st.load_arrays(r.asset_id, keys=[f"v{i:03d}.T_WC" for i in range(12)] + [f"v{i:03d}.K" for i in range(12)])
    print("===", fid, "profile:", m.get("views", [{}])[0].get("profile_id"), "wd:", m.get("views",[{}])[0].get("working_distance_mm"))
    pts = None
    if "points" in (r.files or {}):
        pass
    for i in range(12):
        T = np.asarray(arr.get(f"v{i:03d}.T_WC"), float)
        if T.size == 0: continue
        C = T[:3, 3]
        print(f"   v{i:03d} cam centre = [{C[0]:8.2f}, {C[1]:8.2f}, {C[2]:8.2f}]  |C|={np.linalg.norm(C):7.2f}")
