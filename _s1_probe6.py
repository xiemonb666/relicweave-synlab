import json, numpy as np
from pathlib import Path
pkg = Path(r"data\a12_exports\trainable\next_experiment\training_package")
man = json.loads((pkg/"export_manifest.json").read_text(encoding="utf-8"))
print("release_id", man.get("release_id"))
print("build", json.dumps(man.get("build"), ensure_ascii=False)[:500])
print("reference_closure", json.dumps(man.get("reference_closure"), ensure_ascii=False)[:900])
