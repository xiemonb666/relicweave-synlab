import json, hashlib
from pathlib import Path
# find the store whose releases/*/manifest hash matches
target = "sha256:6d72889911c457c6e125c71a60d3eec4b6b52542e16c8153d3a46d0a4e28cc27".split(":",1)[1]
n=0
for p in Path("data").rglob("releases/*/*.json"):
    n+=1
print("release json files scanned:", n)
for p in Path("data").rglob("releases/*"):
    if p.is_dir():
        pass
cands = sorted(Path("data").glob("*/store/releases/*"))
for c in cands[:40]:
    print(c)
