import numpy as np, json
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
print("obsA cloud bbox:")
oa = st.load_arrays("asset_22fadc3fd59d942bacd8")
P = np.asarray(oa["points"], np.float64)
print("  ", P.min(0).round(2), P.max(0).round(2))
print("obsB cloud bbox:")
ob = st.load_arrays("asset_60a0b55c09cfc4785213")
Q = np.asarray(ob["points"], np.float64)
print("  ", Q.min(0).round(2), Q.max(0).round(2))
print("corr_point_a bbox:", np.asarray(ct["corr_point_a"]).min(0).round(2), np.asarray(ct["corr_point_a"]).max(0).round(2))
print("corr_point_b bbox:", np.asarray(ct["corr_point_b"]).min(0).round(2), np.asarray(ct["corr_point_b"]).max(0).round(2))
for aid, name in (("asset_1beedec77f25cbda2f2f","meshA"),("asset_b7d01b160094c06eff9b","meshB")):
    m = st.load_arrays(aid); V = np.asarray(m["mesh.vertices"], np.float64)
    print(name, "verts bbox:", V.min(0).round(2), V.max(0).round(2))
# Project obs points through view 0 and compare with depth
for aid, name, cloud in (("asset_22fadc3fd59d942bacd8","obsA",P), ("asset_60a0b55c09cfc4785213","obsB",Q)):
    arr = st.load_arrays(aid)
    K = np.asarray(arr["v000.K"], np.float64); T = np.asarray(arr["v000.T_WC"], np.float64)
    depth = np.asarray(arr["v000.depth_z"], np.float64); idm = np.asarray(arr["v000.id_map"])
    print("===", name, "K", K.round(2).tolist(), "T[0:3,3]", T[:3,3].round(2).tolist())
    print("   depth finite frac %.3f  range [%.2f, %.2f]  id_map>=0 frac %.3f" % (
        np.isfinite(depth).mean(), np.nanmin(depth), np.nanmax(depth), (idm>=0).mean()))
    idx = np.linspace(0, cloud.shape[0]-1, 5000).astype(int)
    W = cloud[idx]
    hom = np.concatenate([W, np.ones((W.shape[0],1))],1)
    cam = (np.linalg.inv(T) @ hom.T).T[:, :3]
    pr = (K @ cam.T).T
    z = pr[:,2]; u = np.rint(pr[:,0]/z).astype(int); v = np.rint(pr[:,1]/z).astype(int)
    h,w = depth.shape
    ok = (cam[:,2]>0)&(u>=0)&(u<w)&(v>=0)&(v<h)
    r = np.full(W.shape[0], np.nan)
    r[ok] = np.abs(depth[v[ok],u[ok]] - cam[ok,2])
    fin = r[np.isfinite(r)]
    print("   inside %.3f  median |depth-camz| = %.4g mm  frac<5mm %.3f" % (ok.mean(), np.median(fin) if fin.size else np.nan, float((fin<5).mean()) if fin.size else 0))
