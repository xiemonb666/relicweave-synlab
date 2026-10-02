import sqlite3, json, collections
from pathlib import Path
for pkg, store in ((r"data\a12_exports\closed_loop\training_package_v2","data/a12_exports/closed_loop/store"),
                   (r"data\a12_exports\a12_extras\training_package","data/a12_extras/store")):
    p = Path(pkg)/"deploy"/"obs"/"index.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    print(pkg, "obs fragments:", len(d.get("rows") or {}), "| has quality_research:", "quality_research" in d)
