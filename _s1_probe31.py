import numpy as np, json
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
import sqlite3
con = sqlite3.connect(str(st.db_path)); con.row_factory = sqlite3.Row
for frag in ("LIN0009_V04_M01_PAT02_E01-m", "LIN0010_V07_M10_PAT08_E01-m", "LIN0013_V11_M02_PAT07_E01-p"):
    rows = con.execute("select asset_id, role, schema from assets where lineage_id=? and role in ('fragment_mesh','obs_result','feature_bundle','mother_mesh')", (frag.rsplit("_E01",1)[0],)).fetchall()
    print("===", frag)
    for r in rows:
        aid = r["asset_id"]
        try:
            rec = st.get_asset(aid); meta = dict(rec.meta or {})
            fid = meta.get("fragment_id")
            if r["role"] != "obs_result" and fid != frag and r["role"]=="fragment_mesh": continue
            extra = ""
            if r["role"]=="fragment_mesh":
                A = st.load_arrays(aid); extra = " faces=%d verts=%d" % (np.asarray(A["mesh.faces"]).shape[0], np.asarray(A["mesh.vertices"]).shape[0])
            if r["role"]=="obs_result":
                extra = " n_points=%s" % meta.get("n_points")
            print(f"   {r['role']:15s} {aid} {r['schema']}{extra}")
        except Exception as e:
            print("   ", aid, "ERR", e)
