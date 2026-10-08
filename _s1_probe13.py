import numpy as np, json
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
pts_a = np.asarray(ct["corr_point_a"], dtype=np.float64)
pts_b = np.asarray(ct["corr_point_b"], dtype=np.float64)
ia = np.asarray(ct["corr_index_a"]); ib = np.asarray(ct["corr_index_b"])
w = np.asarray(ct["corr_weight"]); v = np.asarray(ct["corr_valid"])
print("n", ia.size, "unique index_a", np.unique(ia)[:10], "unique index_b", np.unique(ib)[:10])
print("unique points_a", np.unique(pts_a, axis=0).shape, "unique points_b", np.unique(pts_b, axis=0).shape)
print("corr_valid true", int(v.sum()), "weight sum", float(w.sum()))
for aid, name in (("asset_22fadc3fd59d942bacd8","obsA"), ("asset_60a0b55c09cfc4785213","obsB")):
    rec = st.get_asset(aid); meta = dict(rec.meta or {})
    arr = st.load_arrays(aid)
    P = np.asarray(arr["points"], dtype=np.float64)
    print("=== ", name, meta.get("fragment_id"), "obs points", P.shape, "point_valid", int(np.asarray(arr["point_valid"]).sum()))
    Q = pts_a if name=="obsA" else pts_b
    # nearest-neighbour distance of each unique corr point to the obs point cloud (subsample obs for speed)
    U = np.unique(Q, axis=0)
    idx = np.linspace(0, P.shape[0]-1, min(60000, P.shape[0])).astype(int)
    Ps = P[idx]
    d = np.sqrt(((U[:,None,:]-Ps[None,:,:])**2).sum(-1)).min(axis=1)
    print("   unique corr pts", U.shape[0], "| nn-dist to obs cloud: min %.4g med %.4g p95 %.4g max %.4g" % (d.min(), np.median(d), np.percentile(d,95), d.max()))
    print("   frac within 0.01mm", float((d<0.01).mean()), " within 0.1mm", float((d<0.1).mean()))
