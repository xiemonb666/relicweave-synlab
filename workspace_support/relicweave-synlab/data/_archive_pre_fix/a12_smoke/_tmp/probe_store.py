import json, sqlite3, sys
from pathlib import Path
con = sqlite3.connect("data/a12_smoke/metadata.sqlite")
con.row_factory = sqlite3.Row
cur = con.cursor()
tables = [r[0] for r in cur.execute("select name from sqlite_master where type='table'")]
print("tables:", tables)
for t in ("assets", "runs"):
    if t in tables:
        cols = [c[1] for c in cur.execute(f"pragma table_info({t})")]
        print(t, cols)
        if t == "assets":
            for row in cur.execute("select lineage_id, role, qa_status, count(*) c from assets group by lineage_id, role, qa_status order by lineage_id"):
                print(dict(row))
        else:
            for row in cur.execute(f"select * from {t}"):
                d = dict(row)
                print({k: (str(v)[:60] if v is not None else None) for k, v in d.items()})
