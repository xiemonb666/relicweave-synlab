import json
from pathlib import Path
for p in ("data/a12_exports/full/manifest.json",):
    m = json.loads(Path(p).read_text(encoding="utf-8"))
    print(p, "top keys:", sorted(m.keys())[:30])
    for k in ("schema","export_schema","kind","package_schema","release_id","counts","views"):
        if k in m: print("  ", k, "=", json.dumps(m[k], ensure_ascii=False)[:300])
print()
r = Path("data/a12_exports/full/README.md").read_text(encoding="utf-8", errors="replace")
print(r[:1800])
