import json, sqlite3
uri = "file:" + "data/a12/metadata.sqlite".replace("\\","/") + "?mode=ro&immutable=1"
con = sqlite3.connect(uri, uri=True); con.row_factory = sqlite3.Row
cur = con.cursor()
print("== all qa_report rows ==")
for r in cur.execute("SELECT * FROM assets WHERE role='qa_report' ORDER BY created_at"):
    d = dict(r)
    d["qa_json"] = (d["qa_json"] or "")[:300]
    d["files_json"] = (d["files_json"] or "")[:300]
    d["lineage_id"] = repr(d["lineage_id"]); d["split"] = repr(d["split"])
    print(json.dumps(d, indent=2, default=str))
print("== roles present, again ==")
print([ (r["role"], r["n"]) for r in cur.execute("SELECT role, COUNT(*) n FROM assets GROUP BY 1 ORDER BY 2 DESC")])
print("== NULL lineage_id / split per role ==")
for r in cur.execute("SELECT role, SUM(lineage_id IS NULL) nl, SUM(split IS NULL) ns, COUNT(*) n FROM assets GROUP BY 1 ORDER BY 1"):
    if r["nl"] or r["ns"]:
        print(f"  {r['role']:<22} lineage_id_null={r['nl']} split_null={r['ns']} of {r['n']}")
print("== distinct split incl empty ==")
for r in cur.execute("SELECT role, split, COUNT(*) n FROM assets GROUP BY 1,2 ORDER BY 1,2"):
    print(f"  {r['role']:<22} split={r['split']!r:<12} n={r['n']}")
