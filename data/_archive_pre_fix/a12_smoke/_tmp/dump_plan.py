import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from synlab.config import load_generation_spec
from synlab.pipeline import plan_generation
spec = load_generation_spec("configs/a12/next_experiment.yaml")
plan = plan_generation(spec)
rows = []
for l in plan.lineages:
    rows.append(dict(i=l.mother_index, lid=l.lineage_id, split=l.split, V=l.vessel_id,
                     M=l.material_id, P=l.pattern_id, L=l.layer_combo_id))
Path("data/a12_smoke/_tmp/plan.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
# first index per vessel
first = {}
for r in rows:
    first.setdefault(r["V"], r)
print(json.dumps({k: (v["i"], v["lid"], v["M"], v["P"]) for k, v in sorted(first.items())}, indent=1))
print("total", len(rows))
