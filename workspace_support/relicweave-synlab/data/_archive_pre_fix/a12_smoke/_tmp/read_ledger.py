import json
from pathlib import Path
p = Path("data/a12/reports/next_experiment_batches.json")
d = json.loads(p.read_text(encoding="utf-8"))
print("batches:", len(d.get("batches", [])))
for b in d.get("batches", []):
    print(b.get("lineage_id"), b.get("ok"), b.get("error"), b.get("fragments"), b.get("observations"), b.get("seconds"), (b.get("error_message") or "")[:120])
