import json, numpy as np
from synlab.storage.export import TrainingPackage
pkg = r"data\a12_exports\trainable\next_experiment\training_package"
tp = TrainingPackage(pkg)
man = tp.manifest
views = man.get("views")
print("VIEWS type", type(views))
print(json.dumps(views, ensure_ascii=False, indent=1)[:2500])
