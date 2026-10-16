import os,sqlite3,json,collections
ROOT=r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
DATA=os.path.join(ROOT,"data")
types=collections.defaultdict(collections.Counter); vals=collections.defaultdict(collections.Counter)
for dp,dn,fn in os.walk(DATA):
    for f in fn:
        if f!="metadata.sqlite": continue
        p=os.path.join(dp,f)
        con=sqlite3.connect("file:"+p.replace("\\","/")+"?mode=ro&immutable=1",uri=True); cur=con.cursor()
        t=[r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "assets" in t:
            for r in cur.execute("SELECT role,meta_json FROM assets"):
                mj=json.loads(r["meta_json"]); m=mj.get("meta",mj)
                if isinstance(m,dict) and "component_id" in m:
                    v=m["component_id"]
                    types[r["role"]][type(v).__name__]+=1
                    vals[r["role"]][json.dumps(v)[:40]]+=1
        con.close()
for role in sorted(types):
    print("%-22s types=%s"%(role,dict(types[role])))
    print("      sample values: %s"%list(vals[role])[:6])
