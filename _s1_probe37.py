import sqlite3, collections, json
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
con = sqlite3.connect(str(st.db_path)); con.row_factory = sqlite3.Row
obs = collections.defaultdict(set)
for r in con.execute("select asset_id, meta_json from assets where role='obs_result'"):
    m = json.loads(r["meta_json"]); fid=m.get("fragment_id")
    if fid: obs[fid[:fid.rfind("_E01")+4]].add(fid)
print("lineages with any observation:", len(obs))
full=0; part=0
for k, v in sorted(obs.items()):
    ms = sorted(x for x in v if x.endswith("-m")); ps = sorted(x for x in v if x.endswith("-p"))
    tag = "BOTH" if (ms and ps) else "one-side"
    if ms and ps: full+=1
    else: part+=1
print("lineages with BOTH -m and -p observed:", full, " one-side only:", part)
for k,v in sorted(obs.items()):
    ms=[x for x in v if x.endswith("-m")]; ps=[x for x in v if x.endswith("-p")]
    if ms and ps: print("   BOTH:", sorted(v))
