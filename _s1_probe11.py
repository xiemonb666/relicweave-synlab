import json, numpy as np
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
import sqlite3
con = sqlite3.connect(str(st.db_path)); con.row_factory = sqlite3.Row
rows = con.execute("select asset_id, role, lineage_id, split, length(meta_json) from assets where role='obs_result' and lineage_id='LIN0009_V04_M01_PAT02'").fetchall()
for r in rows: print(dict(r))
print("---- feature_bundle ----")
rows = con.execute("select asset_id, role, lineage_id from assets where lineage_id='LIN0009_V04_M01_PAT02'").fetchall()
for r in rows: print(dict(r))
