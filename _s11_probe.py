import json
from pathlib import Path
for name in ("a09_p03_geometry.json","a09_acceptance_final.json"):
    p = Path("data/a12/reports")/name
    if not p.exists(): continue
    d = json.loads(p.read_text(encoding="utf-8"))
    print("===", name, "top keys:", sorted(d.keys())[:18])
    s = json.dumps(d, ensure_ascii=False)
    import re
    for kw in ("roi_external_drift","lost_volume","spacing","grid","halo","marching"):
        for m in re.finditer(r'"([^"]*%s[^"]*)"\s*:\s*([^,}]{1,60})' % kw, s):
            print(f"   {m.group(1)} = {m.group(2)[:60]}")
        break
