import sqlite3, collections
from pathlib import Path
from synlab.storage.store import AssetStore
for root in (r"data\a12_verify\store", r"data\a12_extras\store", r"data\a12_demo\store"):
    st = AssetStore(root)
    con = sqlite3.connect(str(st.db_path)); con.row_factory = sqlite3.Row
    roles = collections.Counter(r["role"] for r in con.execute("select role from assets"))
    rels = list((Path(root)/"releases").glob("*")) if (Path(root)/"releases").is_dir() else []
    print(root, "roles:", dict(roles))
    print("    releases:", [p.name for p in rels][:5])
