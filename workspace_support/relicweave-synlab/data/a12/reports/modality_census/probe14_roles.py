import os,sqlite3,re,collections
ROOT=r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
roles_c=set()
for line in open(os.path.join(ROOT,"synlab","roles.py"),encoding="utf-8"):
    m=re.match(r'^ROLE_\w+\s*=\s*"([^"]+)"',line)
    if m: roles_c.add(m.group(1))
DATA=os.path.join(ROOT,"data")
use=collections.Counter(); stores=collections.defaultdict(set); n_store=0; n_asset=0
for dp,dn,fn in os.walk(DATA):
    for f in fn:
        if f!="metadata.sqlite": continue
        p=os.path.join(dp,f); n_store+=1
        con=sqlite3.connect("file:"+p.replace("\\","/")+"?mode=ro&immutable=1",uri=True)
        cur=con.cursor()
        t=[r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "assets" in t:
            for r in cur.execute("SELECT role,COUNT(*) FROM assets GROUP BY role"):
                use[r[0]]+=r[1]; stores[r[0]].add(os.path.relpath(p,ROOT)); n_asset+=r[1]
        con.close()
print("stores=%d assets=%d distinct roles=%d"%(n_store,n_asset,len(use)))
print("\nROLES ON ASSETS NOT DECLARED IN roles.py:")
un=[r for r in use if r not in roles_c]
if not un: print("   無")
for r in sorted(un):
    print("   %-22s n=%-5d stores=%s"%(r,use[r],sorted(stores[r])[:3]))
print("\nDECLARED ROLES WITH ZERO ASSETS IN ANY STORE:")
z=sorted(roles_c-set(use))
if not z: print("   無")
for r in z: print("   ",r)
