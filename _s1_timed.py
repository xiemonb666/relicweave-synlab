import time, sys, json
sys.path.insert(0, ".")
from synlab.storage.store import AssetStore
from synlab.storage.export import _correspondence_token_rows, load_projection_arrays
from tools.a12_corr_token_map import relations_with_truth_assets, observation_map
st = AssetStore(r"data\a12_trainable\store")
obs = observation_map(st); rels = relations_with_truth_assets(st)
def lookup(fid):
    a = obs.get(fid)
    return load_projection_arrays(st, a) if a else None
t=time.time(); rows, prov = _correspondence_token_rows(st, rels, lookup)
print("project %.1fs rows=%d mapped=%d" % (time.time()-t, len(rows), prov.get("samples_mapped")), flush=True)
json.dump({"rows": rows, "prov": {k:v for k,v in prov.items()}}, open("_s1_rows.json","w",encoding="utf-8"), ensure_ascii=False)
print("written _s1_rows.json", flush=True)
