import sys; sys.path.insert(0,'.')
from pathlib import Path
n=0
for p in Path("data").rglob("manifest.json"):
    if "releases" in str(p):
        n+=1
        if n<=6: print(p)
print("total release manifests:", n)
