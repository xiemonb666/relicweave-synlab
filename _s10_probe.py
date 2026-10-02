import json
from pathlib import Path
p = Path(r"data\a12_exports\trainable\next_experiment\training_package\deploy\obs\index.json")
d = json.loads(p.read_text(encoding="utf-8"))
vp = d["view_pos"]["measured"]
print("view_pos.measured:", json.dumps(vp, ensure_ascii=False, indent=2))
# per-fragment view_pos from the tars would be heavier; the index records the source
print("definition:", d["view_pos"]["definition"][:200])
