import numpy as np
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
obs = {}
for r in st.list_assets(role="obs_result", limit=500):
    fid=(r.meta or {}).get("fragment_id")
    if fid: obs.setdefault(fid, r.asset_id)
for a,b in (("LIN0010_V07_M10_PAT08_E01-m","LIN0010_V07_M10_PAT08_E01-p"),
            ("LIN0013_V11_M02_PAT07_E01-m","LIN0013_V11_M02_PAT07_E01-p")):
    A = st.load_arrays(obs[a]); B = st.load_arrays(obs[b])
    P = np.asarray(A["points"], float); Q = np.asarray(B["points"], float)
    print(f"=== {a[-6:]} {P.shape}  vs  {b[-6:]} {Q.shape}")
    print("   bbox A", P.min(0).round(1), P.max(0).round(1))
    print("   bbox B", Q.min(0).round(1), Q.max(0).round(1))
    # nearest distance from a sample of B to A's cloud, and vice versa
    ia = np.linspace(0, P.shape[0]-1, 3000).astype(int); Ps = P[ia]
    ib = np.linspace(0, Q.shape[0]-1, 3000).astype(int); Qs = Q[ib]
    d = np.sqrt(((Qs[:,None,:]-Ps[None,:,:])**2).sum(-1))
    nn = d.min(1)
    print("   B->A nn dist: min %.3f med %.3f p10 %.3f p25 %.3f" % (nn.min(), np.median(nn), np.percentile(nn,10), np.percentile(nn,25)))
    print("   frac of B points within 1mm of A: %.3f   within 3mm: %.3f" % ((nn<1).mean(), (nn<3).mean()))
