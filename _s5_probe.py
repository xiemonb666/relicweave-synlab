import sqlite3, json, collections
from pathlib import Path
from synlab.storage.store import AssetStore
for root in (r"data\a12_trainable\store", r"data\a12_exports\closed_loop\store", r"data\a12_campaign\store"):
    p = Path(root)
    if not (p/"metadata.sqlite").exists():
        print(root, "-> no store"); continue
    st = AssetStore(root)
    con = sqlite3.connect(str(st.db_path)); con.row_factory = sqlite3.Row
    cnt = collections.Counter(); found = collections.Counter()
    for r in con.execute("select role, meta_json from assets"):
        m = json.loads(r["meta_json"])
        cnt[r["role"]] += 1
        # look for mask_semantics anywhere in the meta (top level or nested)
        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "mask_semantics": yield v
                    yield from walk(v)
            elif isinstance(o, list):
                for v in o: yield from walk(v)
        vals = list(walk(m))
        if vals: found[(r["role"], tuple(sorted({str(v) for v in vals})))] += 1
    print("===", root, "assets:", sum(cnt.values()))
    print("    roles:", dict(cnt))
    print("    mask_semantics found:", dict(found) if found else "NONE")
