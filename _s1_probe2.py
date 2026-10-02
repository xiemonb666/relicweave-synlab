import json, glob, os
import numpy as np
from synlab.storage.export import TrainingPackage
pkg = r"data\a12_exports\trainable\next_experiment\training_package"
tp = TrainingPackage(pkg)
print("TYPE", type(tp))
print("MANIFEST KEYS", sorted(tp.manifest.keys())[:40] if hasattr(tp,"manifest") else "no manifest")
man = tp.manifest
print(json.dumps({k: man[k] for k in man if k in ("counts","supervision_labels")}, ensure_ascii=False, indent=1)[:3000])
