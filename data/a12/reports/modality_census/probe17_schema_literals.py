import os,re,collections
ROOT=r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
pat=re.compile(r'["\']((?:synlab|a12)\.[a-z0-9_.]+\.v\d+)["\']')
hits=collections.Counter(); n=0
for dp,dn,fn in os.walk(ROOT):
    if any(s in dp for s in (".git","node_modules",".venv","__pycache__",".pytest_cache")): continue
    for f in fn:
        if not f.endswith((".py",".json")): continue
        p=os.path.join(dp,f)
        try: txt=open(p,encoding="utf-8",errors="ignore").read()
        except Exception: continue
        for m in pat.finditer(txt):
            hits[m.group(1)]+=1; n+=1
roles=set()
for line in open(os.path.join(ROOT,"synlab","roles.py"),encoding="utf-8"):
    m=re.match(r'^SCHEMA_\w+\s*=\s*"([^"]+)"',line)
    if m: roles.add(m.group(1))
print("versioned schema-like literals in .py/.json (excl .git/.venv/node_modules): %d occurrences, %d distinct"%(n,len(hits)))
print("declared in roles.py: %d"%len(roles))
litonly=sorted(set(hits)-roles)
print("distinct literals NOT in roles.py: %d"%len(litonly))
