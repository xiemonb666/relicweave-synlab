import numpy as np, hashlib
from synlab.storage.store import AssetStore
from synlab.storage.export import load_projection_arrays
from synlab.storage.export import _locate_samples_in_token_grid
st = AssetStore(r"data\a12_trainable\store")
obs = {}
for r in st.list_assets(role="obs_result", limit=500):
    fid=(r.meta or {}).get("fragment_id")
    if fid: obs.setdefault(fid, r.asset_id)
seen=set(); results=[]
for role in ("clean_truth","physical_truth"):
    for r in st.list_assets(role=role, limit=500):
        ct = st.load_arrays(r.asset_id)
        if "corr_face_a" not in ct: continue
        fids = [str(x) for x in np.asarray(ct.get("corr_fragment_ids", [])).tolist()]
        if len(fids)!=2: continue
        key=(r.lineage_id, fids[0], fids[1], np.asarray(ct["corr_point_a"]).shape[0])
        if key in seen: continue
        seen.add(key)
        a,b=fids
        pa=np.asarray(ct["corr_point_a"],float); pb=np.asarray(ct["corr_point_b"],float)
        fa=np.asarray(ct["corr_face_a"],np.int64); fb=np.asarray(ct["corr_face_b"],np.int64)
        ra = _locate_samples_in_token_grid(load_projection_arrays(st, obs[a]), pa, fa) if a in obs else None
        rb = _locate_samples_in_token_grid(load_projection_arrays(st, obs[b]), pb, fb) if b in obs else None
        oa = int(ra["ok"].sum()) if ra else 0
        ob = int(rb["ok"].sum()) if rb else 0
        both = int((ra["ok"] & rb["ok"]).sum()) if (ra and rb) else 0
        results.append((r.lineage_id, a[-6:], b[-6:], len(pa), oa, ob, both))
        print(f"{r.lineage_id[-14:]:16s} n={len(pa):5d}  -m located={oa:5d}  -p located={ob:5d}  BOTH={both:5d}")
print()
print("pairs with BOTH sides located:", sum(1 for x in results if x[6]>0), "/", len(results))
print("total samples located on both sides:", sum(x[6] for x in results))
