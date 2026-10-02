import json, numpy as np
from synlab.storage.export import TrainingPackage
pkg = r"data\a12_exports\trainable\next_experiment\training_package"
tp = TrainingPackage(pkg)
man = tp.manifest
assets = man.get("assets")
print("ASSETS type", type(assets), len(assets) if hasattr(assets,'__len__') else '')
if isinstance(assets, dict):
    ks = sorted(assets.keys()); print("KEYS", ks[:20])
    print(json.dumps(assets[ks[0]], ensure_ascii=False, indent=1)[:2000])
else:
    print(json.dumps(assets[:3], ensure_ascii=False, indent=1)[:2000])
print("=== labels ===")
print(json.dumps(man.get("labels"), ensure_ascii=False, indent=1)[:1500])
print("=== token_cache ===")
print(json.dumps(man.get("token_cache"), ensure_ascii=False, indent=1)[:1200])
