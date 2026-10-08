import numpy as np
from synlab.storage.store import AssetStore
from synlab.storage.export import load_projection_arrays, _obs_view_count, TOKEN_BLOCK
st = AssetStore(r"data\a12_trainable\store")
obs = {}
for r in st.list_assets(role="obs_result", limit=500):
    fid=(r.meta or {}).get("fragment_id")
    if fid: obs.setdefault(fid, r.asset_id)
pairs = [("LIN0009_V04_M01_PAT02", "asset_bd3812b8c9b5059ac091", "LIN0009_V04_M01_PAT02_E01-m","LIN0009_V04_M01_PAT02_E01-p"),
         ("LIN0010_V07_M10_PAT08", "asset_963121f5e8c793ce8156", "LIN0010_V07_M10_PAT08_E01-m","LIN0010_V07_M10_PAT08_E01-p"),
         ("LIN0012_V03_M02_PAT01", "asset_51098179c1f3daf4b2cf", "LIN0012_V03_M02_PAT01_E01-m","LIN0012_V03_M02_PAT01_E01-p"),
         ("LIN0013_V11_M02_PAT07", "asset_cbb426407ddd6400ac71", "LIN0013_V11_M02_PAT07_E01-m","LIN0013_V11_M02_PAT07_E01-p")]
def locate(fid, P, FC, tol):
    A = load_projection_arrays(st, obs[fid]); nv = _obs_view_count(A)
    H = np.concatenate([P, np.ones((P.shape[0],1))],1)
    n = P.shape[0]
    tokens = np.full(n,-1); views=np.full(n,-1); resid=np.full(n,np.inf)
    for v in range(nv):
        K=np.asarray(A[f"v{v:03d}.K"],float); T=np.asarray(A[f"v{v:03d}.T_WC"],float)
        D=np.asarray(A[f"v{v:03d}.depth_z"],float); IM=np.asarray(A[f"v{v:03d}.id_map"],np.int64)
        R=np.asarray(A[f"v{v:03d}.roi"],bool) if f"v{v:03d}.roi" in A else None
        cam=(np.linalg.inv(T)@H.T).T[:,:3]; pr=(K@cam.T).T; z=pr[:,2]
        u=np.rint(pr[:,0]/np.where(np.abs(z)<1e-12,np.nan,z)); vv=np.rint(pr[:,1]/np.where(np.abs(z)<1e-12,np.nan,z))
        h,w=D.shape
        ins=(cam[:,2]>0)&np.isfinite(u)&np.isfinite(vv)&(u>=0)&(u<w)&(vv>=0)&(vv<h)
        ui=np.clip(np.where(ins,u,0).astype(int),0,w-1); vi=np.clip(np.where(ins,vv,0).astype(int),0,h-1)
        ident = ins & (IM[vi,ui]==FC)
        if R is not None: ident &= R[vi,ui]
        rd=D[vi,ui]; res=np.where(ident&np.isfinite(rd), np.abs(rd-cam[:,2]), np.inf)
        bh=max(h//TOKEN_BLOCK,1); bw=max(w//TOKEN_BLOCK,1)
        grid = ins & (ui<bw*TOKEN_BLOCK) & (vi<bh*TOKEN_BLOCK)
        ok = ident & grid & (res<=tol) & (res<resid)
        if ok.any():
            tokens[ok]=((vi[ok]//bh)*TOKEN_BLOCK+(ui[ok]//bw))*3
            views[ok]=v; resid[ok]=res[ok]
    return tokens, views, resid
for lin, ta, fa, fb in pairs:
    ct = st.load_arrays(ta)
    print("===", lin)
    out={}
    for side, fid in (("a",fa),("b",fb)):
        P=np.asarray(ct[f"corr_point_{side}"],float); FC=np.asarray(ct[f"corr_face_{side}"],np.int64)
        tk,vw,rs = locate(fid,P,FC,5.0)
        idn = locate(fid,P,FC,np.inf)
        out[side]=(tk,vw,rs,idn[0])
        print(f"   side {side}: face-identity+grid samples={int((idn[0]>=0).sum())}/{P.shape[0]}"
              f"  with depth<=5mm: {int((tk>=0).sum())}  median resid of identified: "
              f"{np.median(rs[np.isfinite(rs)]) if np.isfinite(rs).any() else float('nan'):.3f} mm")
    for tol in (5.0, 20.0, 60.0):
        c=0
        for side, fid in (("a",fa),("b",fb)):
            P=np.asarray(ct[f"corr_point_{side}"],float); FC=np.asarray(ct[f"corr_face_{side}"],np.int64)
            tk,_,_ = locate(fid,P,FC,tol); out[side+"_t"]=tk
        both = (out["a_t"]>=0)&(out["b_t"]>=0)
        print(f"   tol={tol:>5}mm -> BOTH sides located: {int(both.sum())}  (a {int((out['a_t']>=0).sum())}, b {int((out['b_t']>=0).sum())})")
