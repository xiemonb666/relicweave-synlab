import numpy as np
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
C = {"a": np.asarray(ct["corr_point_a"], np.float64), "b": np.asarray(ct["corr_point_b"], np.float64)}
OBS = {"a": "asset_22fadc3fd59d942bacd8", "b": "asset_60a0b55c09cfc4785213"}
TOL = 5.0
def best_views(points, arr, nv=12):
    hom = np.concatenate([points, np.ones((points.shape[0],1))],1)
    best = np.full(points.shape[0], -1); bestr = np.full(points.shape[0], np.inf)
    inside_any = np.zeros(points.shape[0], bool)
    for i in range(nv):
        K = arr.get(f"v{i:03d}.K"); T = arr.get(f"v{i:03d}.T_WC"); D = arr.get(f"v{i:03d}.depth_z")
        if K is None or T is None or D is None: continue
        K = np.asarray(K,float); T = np.asarray(T,float); D = np.asarray(D,float)
        cam = (np.linalg.inv(T) @ hom.T).T[:, :3]
        pr = (K @ cam.T).T; z = pr[:,2]
        u = np.rint(pr[:,0]/np.where(np.abs(z)<1e-12, np.nan, z)).astype(int)
        v = np.rint(pr[:,1]/np.where(np.abs(z)<1e-12, np.nan, z)).astype(int)
        h,w = D.shape
        okin = (cam[:,2]>0)&(u>=0)&(u<w)&(v>=0)&(v<h)
        inside_any |= okin
        r = np.full(points.shape[0], np.inf)
        r[okin] = np.abs(D[v[okin],u[okin]] - cam[okin,2])
        better = r < bestr
        best[better] = i; bestr[better] = r[better]
    matched = bestr <= TOL
    return best, bestr, matched, inside_any
for side, aid in OBS.items():
    arr = st.load_arrays(aid)
    for tag, pts in (("matched", C[side]), ("swapped", C["b" if side=="a" else "a"])):
        best, bestr, matched, inside_any = best_views(pts, arr)
        print(f"{side} <- corr_{tag}: inside_any {inside_any.mean():.3f}  matched(<=5mm) {matched.sum()}/{pts.shape[0]} "
              f"({matched.mean():.3f})  median resid {np.median(np.where(np.isfinite(bestr), bestr, np.nan)):.4g}")
