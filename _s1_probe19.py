import numpy as np, json
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
for aid in ("asset_1beedec77f25cbda2f2f","asset_b7d01b160094c06eff9b"):
    rec = st.get_asset(aid); m = dict(rec.meta or {})
    arr = st.load_arrays(aid)
    print(aid, "->", json.dumps({k:m.get(k) for k in ("fragment_id","component_id","role","schema","side","fragment","event_id")}, ensure_ascii=False))
    print("    meta keys:", sorted(m.keys())[:20])
print()
print("=== normal matching (subset; fragment meshes vs corr normals) ===")
for aid, nm in (("asset_22fadc3fd59d942bacd8","obsA"),("asset_60a0b55c09cfc4785213","obsB")):
    arr = st.load_arrays(aid)
    N = np.asarray(arr["normals"], np.float64)
    idx = np.linspace(0, N.shape[0]-1, 4000).astype(int)
    Ns = N[idx]; Ns /= np.maximum(np.linalg.norm(Ns,axis=1,keepdims=True),1e-12)
    for side in ("a","b"):
        Cn = np.asarray(ct[f"corr_normal_{side}"], np.float64)
        Cn = Cn/np.maximum(np.linalg.norm(Cn,axis=1,keepdims=True),1e-12)
        # for each corr normal, best |dot| among obs normals
        dots = np.abs(Cn @ Ns.T).max(1)
        print(f"  {nm} vs corr_normal_{side}: mean|dot| {dots.mean():.3f}  frac>0.95 {float((dots>0.95).mean()):.3f}  frac>0.8 {float((dots>0.8).mean()):.3f}")
