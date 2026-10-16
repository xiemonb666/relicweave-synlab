"""How many pixels differ *meaningfully* between the CPU and CUDA renders?

``max_abs_diff`` alone is misleading: a single silhouette pixel can dominate it while 99.99%
of the frame agrees to float round-off.  This reports the distribution against thresholds
that matter for the delivered data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

cpu = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
gpu = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
A = np.load(cpu["npz"])
B = np.load(gpu["npz"])

for name, thresholds in (("depth_z", (1e-3, 1e-2, 0.1, 1.0, 10.0)),
                         ("rgb_linear", (1e-6, 1e-4, 1e-3, 1e-2))):
    x = A[name].astype(np.float64)
    y = B[name].astype(np.float64)
    both_nan = np.isnan(x) & np.isnan(y)
    d = np.abs(np.nan_to_num(x, nan=0.0) - np.nan_to_num(y, nan=0.0))
    valid = ~both_nan
    tot = int(valid.sum())
    print(f"--- {name}: {tot} comparable elements")
    for t in thresholds:
        n = int(np.count_nonzero((d > t) & valid))
        print(f"      > {t:<8g}: {n:>9d}  ({n / tot:.3e})")
    print(f"      max     : {float(d[valid].max()):.6g}")
