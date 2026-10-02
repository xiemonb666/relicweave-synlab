import json, numpy as np
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
# clean truth corr points
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
ca = np.asarray(ct["corr_index_a"]); cb = np.asarray(ct["corr_index_b"])
pa = np.asarray(ct["corr_point_a"]); pb = np.asarray(ct["corr_point_b"])
print("corr n", ca.size, "index_a range", ca.min(), ca.max(), "index_b range", cb.min(), cb.max())
for aid, name in (("asset_22fadc3fd59d942bacd8","obsA"), ("asset_60a0b55c09cfc4785213","obsB")):
    rec = st.get_asset(aid); meta = dict(rec.meta or {})
    print("=== ", name, aid, "fragment_id", meta.get("fragment_id"), "views", len(meta.get("views") or []))
    arr = st.load_arrays(aid)
    ks = sorted(arr)
    print("   n arrays", len(ks), "sample:", ks[:14])
    print("   has points:", "points" in arr, " shape", arr["points"].shape if "points" in arr else None)
    vk = [k for k in ks if k.endswith(".id_map") or k.endswith(".depth_z") or k.endswith(".T_WC") or k.endswith(".K")]
    print("   projection arrays:", vk[:12])
