"""Read-only inspection of a store's sqlite schema (no AssetStore, no writes)."""
import json
import sqlite3
import sys

con = sqlite3.connect("file:data/a12/metadata.sqlite?mode=ro", uri=True)
con.row_factory = sqlite3.Row
tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
print("tables:", tables)
cur = con.execute("select * from assets limit 1")
print("assets cols:", [d[0] for d in cur.description])
row = dict(cur.fetchone())
print(json.dumps({k: (str(v)[:200]) for k, v in row.items()}, indent=1))
print("role counts:", [tuple(r) for r in con.execute(
    "select role, count(*) from assets group by role order by 2 desc")])
