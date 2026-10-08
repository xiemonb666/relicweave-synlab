import json
from pathlib import Path

p = Path(__file__).with_name("_div_probe.json")
raw = p.read_bytes()
for enc in ("utf-8", "utf-16", "utf-16-le", "cp1252"):
    try:
        d = json.loads(raw.decode(enc))
        print(f"# decoded as {enc}")
        break
    except Exception:
        continue
else:
    raise SystemExit("cannot decode")

for s in d:
    print("==", s["store"], "assets", s.get("assets_total"), "blobs", s.get("blobs_total"),
          "lineages", s.get("lineages"), s.get("error", ""))
    print("   roles:", s.get("roles"))
