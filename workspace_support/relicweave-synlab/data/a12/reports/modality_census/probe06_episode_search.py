import os,sqlite3,json
ROOT=r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
hits=[]
for dp,dn,fn in os.walk(os.path.join(ROOT,"data")):
    for f in fn:
        if f=="metadata.sqlite":
            p=os.path.join(dp,f)
            con=sqlite3.connect("file:"+p.replace("\\","/")+"?mode=ro&immutable=1",uri=True)
            cur=con.cursor()
            t=[r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            if "assets" in t:
                n=cur.execute("SELECT COUNT(*) FROM assets WHERE role='episode_trace'").fetchone()[0]
                if n: hits.append((os.path.relpath(p,ROOT),n))
                # also look for episode schema
                n2=cur.execute("SELECT COUNT(*) FROM assets WHERE schema LIKE '%episode%'").fetchone()[0]
                if n2: hits.append((os.path.relpath(p,ROOT),"schema-episode",n2))
            if "api_episodes" in t:
                n3=cur.execute("SELECT COUNT(*) FROM api_episodes").fetchone()[0]
                if n3: hits.append((os.path.relpath(p,ROOT),"api_episodes",n3))
            con.close()
print("episode_trace rows found:",len(hits))
for h in hits: print("   ",h)
