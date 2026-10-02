import json, numpy as np
from pathlib import Path
pkg = Path(r"data\a12_exports\trainable\next_experiment\training_package")
idx = list((pkg/"deploy"/"obs").rglob("index.json"))
print("obs index files:", len(idx))
for p in idx[:3]: print(p)
if idx:
    d = json.loads(idx[0].read_text(encoding="utf-8"))
    print("SCHEMA", d.get("schema"))
    print("TOPKEYS", sorted(d.keys()))
    rows = d.get("rows")
    print("rows type", type(rows), len(rows) if hasattr(rows,'__len__') else '')
    if isinstance(rows, dict):
        k0 = sorted(rows)[0]
        print("sample row key", k0)
        print(json.dumps(rows[k0], ensure_ascii=False, indent=1)[:3000])
