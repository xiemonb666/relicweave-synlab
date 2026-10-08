import sys, json, collections
sys.path.insert(0, ".")
from pathlib import Path
import numpy as np
pkg_dir = Path(r"data\a12_exports\trainable\next_experiment\training_package")
from tools.load_package import Package, build_batch
built = build_batch(pkg_dir, token_budget=256)
sup = built["supervision"]["tasks"]
for t in ("rank","contradiction","correspondence","quality","view"):
    e = sup[t]
    print(f"{t:14s} n_valid={e['n_valid']:6d} n_allowed={e['n_allowed']:6d} blocked={e['blocked_by']}")
print()
print("contradiction evidence:", json.dumps(sup["contradiction"]["evidence"], ensure_ascii=False)[:300])
print("pair_mask:", json.dumps(built["supervision"]["pair_mask"], ensure_ascii=False)[:500])
