import json
from pathlib import Path
pkg = Path(r"data\a12_exports\trainable\next_experiment\training_package")
man = json.loads((pkg/"export_manifest.json").read_text(encoding="utf-8"))
rc = man.get("reference_closure")
print("rc keys", sorted(rc.keys()) if isinstance(rc,dict) else type(rc))
print(json.dumps({k:v for k,v in rc.items() if k!="problems"}, ensure_ascii=False, indent=1)[:1500])
print("release_manifest_hash", man.get("release_manifest_hash"))
print("release_profile", json.dumps(man.get("release_profile"), ensure_ascii=False)[:600])
