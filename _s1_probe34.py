import numpy as np, collections
from synlab.storage.store import AssetStore
from synlab.storage.export import load_projection_arrays, _obs_view_count
st = AssetStore(r"data\a12_trainable\store")
obs = {}
for r in st.list_assets(role="obs_result", limit=500):
    fid=(r.meta or {}).get("fragment_id")
    if fid: obs.setdefault(fid, r.asset_id)
cache={}
def idmap_labels(fid):
    if fid in cache: return cache[fid]
    o = obs.get(fid); s=set()
    if o:
        A = load_projection_arrays(st, o)
        for v in range(_obs_view_count(A)):
            s |= set(np.unique(np.asarray(A[f"v{v:03d}.id_map"])).tolist())
        s.discard(-1)
    cache[fid]=s; return s
for role in ("clean_truth","physical_truth"):
    print("=========", role)
    for r in st.list_assets(role=role, limit=500):
        ct = st.load_arrays(r.asset_id)
        if "corr_face_a" not in ct: continue
        fids = [str(x) for x in np.asarray(ct.get("corr_fragment_ids", [])).tolist()]
        if len(fids) != 2: continue
        a,b = fids
        FCa = set(np.asarray(ct["corr_face_a"]).tolist()); FCb = set(np.asarray(ct["corr_face_b"]).tolist())
        La, Lb = idmap_labels(a), idmap_labels(b)
        ca = len(FCa & La)/max(len(FCa),1); cb = len(FCb & Lb)/max(len(FCb),1)
        both = (ca>0.5) and (cb>0.5)
        flag = "  <== BOTH SIDES MATCH" if both else ""
        print(f"  {r.lineage_id[-14:]:16s} {a[-6:]} cov={ca:.3f} ({len(La)} labels)  {b[-6:]} cov={cb:.3f} ({len(Lb)} labels){flag}")
