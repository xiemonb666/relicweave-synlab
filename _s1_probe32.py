import numpy as np
from synlab.storage.store import AssetStore
from synlab.storage.export import load_projection_arrays, _obs_view_count
st = AssetStore(r"data\a12_trainable\store")
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
for side, oaid, fid in (("a","asset_22fadc3fd59d942bacd8","-m"),("b","asset_60a0b55c09cfc4785213","-p")):
    A = load_projection_arrays(st, oaid); nv = _obs_view_count(A)
    P = np.asarray(ct[f"corr_point_{side}"], float)
    H = np.concatenate([P, np.ones((P.shape[0],1))],1)
    allres = []
    for v in range(nv):
        K = np.asarray(A[f"v{v:03d}.K"], float); T = np.asarray(A[f"v{v:03d}.T_WC"], float)
        D = np.asarray(A[f"v{v:03d}.depth_z"], float); IM = np.asarray(A[f"v{v:03d}.id_map"])
        R = np.asarray(A[f"v{v:03d}.roi"], bool) if f"v{v:03d}.roi" in A else None
        cam = (np.linalg.inv(T) @ H.T).T[:, :3]
        pr = (K @ cam.T).T; z = pr[:,2]
        u = np.rint(pr[:,0]/np.where(np.abs(z)<1e-12,np.nan,z)); vv = np.rint(pr[:,1]/np.where(np.abs(z)<1e-12,np.nan,z))
        h,w = D.shape
        ins = (cam[:,2]>0)&np.isfinite(u)&np.isfinite(vv)&(u>=0)&(u<w)&(vv>=0)&(vv<h)
        ui = np.clip(np.where(ins,u,0).astype(int),0,w-1); vi = np.clip(np.where(ins,vv,0).astype(int),0,h-1)
        rd = D[vi,ui]
        res = np.where(ins & np.isfinite(rd), np.abs(rd-cam[:,2]), np.inf)
        allres.append(res)
    S = np.vstack(allres)
    best = S.min(0)
    fin = best[np.isfinite(best)]
    print(f"side {side} ({fid}): inside any view {np.isfinite(best).sum()}/{P.shape[0]}")
    for tol in (1.0, 2.0, 5.0, 20.0, 100.0):
        print(f"    samples within {tol:>5}mm : {int((best<=tol).sum())}")
    if fin.size:
        print("    residual percentiles mm: p05 %.3f p25 %.3f p50 %.3f p75 %.3f p95 %.3f" % tuple(np.percentile(fin,[5,25,50,75,95])))
