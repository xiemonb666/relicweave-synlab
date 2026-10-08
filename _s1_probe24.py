import numpy as np
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
C = np.asarray(ct["corr_point_a"], np.float64)
IDX = {"a": np.asarray(ct["corr_index_a"]), "b": np.asarray(ct["corr_index_b"])}
obs = {"m": ("asset_22fadc3fd59d942bacd8", "asset_1beedec77f25cbda2f2f"),
       "p": ("asset_60a0b55c09cfc4785213", "asset_b7d01b160094c06eff9b")}
# map point index -> position in cloud via exact coordinate equality on mesh vertices
for frag, (oaid, maid) in obs.items():
    A = st.load_arrays(oaid); M = st.load_arrays(maid)
    P = np.asarray(A["points"], np.float64); V = np.asarray(M["mesh.vertices"], np.float64)
    # exact match of mesh vertices inside the cloud
    keyP = {tuple(np.round(p, 9)): i for i, p in enumerate(P)}
    hit = np.array([keyP.get(tuple(np.round(v, 9)), -1) for v in V])
    print(f"fragment {frag}: mesh verts {V.shape[0]} cloud {P.shape[0]} | verts found in cloud: {int((hit>=0).sum())}")
    # now project corr points and test id_map equality
    hom = np.concatenate([C, np.ones((C.shape[0],1))],1)
    ok_tot = 0; eq_tot = 0
    for v in range(12):
        K = np.asarray(A[f"v{v:03d}.K"], float); T = np.asarray(A[f"v{v:03d}.T_WC"], float)
        D = np.asarray(A[f"v{v:03d}.depth_z"], float); IM = np.asarray(A[f"v{v:03d}.id_map"])
        cam = (np.linalg.inv(T) @ hom.T).T[:, :3]
        pr = (K @ cam.T).T; z = pr[:,2]
        u = np.rint(pr[:,0]/np.where(np.abs(z)<1e-12,np.nan,z)).astype(int)
        vv = np.rint(pr[:,1]/np.where(np.abs(z)<1e-12,np.nan,z)).astype(int)
        h,w = IM.shape
        ins = (cam[:,2]>0)&(u>=0)&(u<w)&(vv>=0)&(vv<h)
        ok = ins & (IM[np.clip(vv,0,h-1), np.clip(u,0,w-1)] >= 0)
        if v == 0:
            ok_tot = ok.copy()
        else:
            ok_tot |= ok
    print(f"   corr pts projecting into a valid id_map pixel (any view): {int(ok_tot.sum())}/{C.shape[0]}")
