import sqlite3, json
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_exports\closed_loop\store")
con = sqlite3.connect(str(st.db_path)); con.row_factory = sqlite3.Row
n = 0
for r in con.execute("select asset_id, meta_json from assets where role='obs_result' limit 3"):
    m = json.loads(r["meta_json"])
    q = m.get("quality") or {}
    est = {k: v for k, v in q.items() if isinstance(v, dict) and v.get("source_kind") == "OBS_EST"}
    print(r["asset_id"], m.get("fragment_id"), "quality entries:", len(q), "OBS_EST:", len(est))
    n += 1
print("obs_result assets:", con.execute("select count(*) from assets where role='obs_result'").fetchone()[0])
