import numpy as np, json
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
rec = st.get_asset("asset_22fadc3fd59d942bacd8")
meta = dict(rec.meta or {})
def walk(o, pre="", depth=0):
    if depth>2: return
    if isinstance(o, dict):
        for k,v in o.items():
            if isinstance(v,(dict,list)) and depth<2: walk(v, pre+"/"+str(k), depth+1)
            else: print(f"{pre}/{k} = {json.dumps(v, ensure_ascii=False)[:160]}")
    elif isinstance(o, list) and o and isinstance(o[0], dict):
        walk(o[0], pre+"[0]", depth+1)
print("TOP", sorted(meta.keys()))
for k in sorted(meta):
    v = meta[k]
    if k == "views":
        print("views: n=", len(v)); print("  view[0] keys:", sorted(v[0].keys()))
        print("  view[0]:", json.dumps({kk:vv for kk,vv in v[0].items() if kk not in ("K","T_WC","dist")}, ensure_ascii=False)[:900])
        print("  view[0].K:", json.dumps(np.asarray(v[0].get("K")).tolist() if v[0].get("K") is not None else None))
        continue
    print(f"{k} = {json.dumps(v, ensure_ascii=False)[:260]}")
