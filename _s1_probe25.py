import numpy as np, json
from synlab.storage.export import TrainingPackage
pkg = TrainingPackage(r"data\a12_exports\trainable\next_experiment\training_package")
t = pkg.read_tokens("LIN0009_V04_M01_PAT02_E01-m")
print("keys", sorted(t.keys()))
print("tokens", np.asarray(t["tokens"]).shape, "valid", np.asarray(t["token_valid"]).shape, "all valid", bool(np.asarray(t["token_valid"]).all()))
tv = np.asarray(t["token_view"])
print("token_view shape", tv.shape, "unique", np.unique(tv)[:15], "n distinct", np.unique(tv).size)
print("per-view counts", [int((tv==i).sum()) for i in range(12)])
