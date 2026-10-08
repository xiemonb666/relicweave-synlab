import numpy as np, json
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
rec = st.get_asset("asset_bd3812b8c9b5059ac091")
npz = st.root / rec.files["arrays"]
print("npz", npz, npz.stat().st_size)
with np.load(npz, allow_pickle=False) as d:
    print("files ok, n", len(d.files))
    try:
        v = d["corr_fragment_ids"]; print("loaded corr_fragment_ids", v, v.dtype)
    except Exception as e:
        print("LOAD FAILED:", type(e).__name__, e)
