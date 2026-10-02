import numpy as np
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
for aid in ("asset_22fadc3fd59d942bacd8","asset_60a0b55c09cfc4785213"):
    rec = st.get_asset(aid)
    p = st.root / rec.files["arrays"]
    print(aid, "npz MB", round(p.stat().st_size/1e6,1))
    with np.load(p, allow_pickle=False) as d:
        tot = sum(d[k].nbytes for k in d.files)
        print("   uncompressed MB", round(tot/1e6,1), "n arrays", len(d.files))
        big = sorted(((d[k].nbytes, k) for k in d.files), reverse=True)[:6]
        print("   biggest:", [(k, round(n/1e6,1)) for n,k in big])
