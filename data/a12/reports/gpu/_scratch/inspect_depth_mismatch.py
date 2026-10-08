"""Inspect the single pixel where CPU and GPU disagree about depth (scratch helper)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

cpu = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
gpu = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
a = np.load(cpu["npz"])["depth_z_aa"]
b = np.load(gpu["npz"])["depth_z_aa"]
print("shape", a.shape, a.dtype)
mismatch = np.isnan(a) ^ np.isnan(b)
idx = np.argwhere(mismatch)
print("nan-mismatch pixels:", len(idx))
for v, y, x in idx[:10]:
    print(f"  view={v} y={y} x={x}  cpu={a[v, y, x]!r}  gpu={b[v, y, x]!r}")
# where does the 1e10 come from?
finite_a = a[np.isfinite(a)]
finite_b = b[np.isfinite(b)]
print("cpu finite range :", float(finite_a.min()), float(finite_a.max()))
print("gpu finite range :", float(finite_b.min()), float(finite_b.max()))
print("cpu has 1e10-ish :", int(np.count_nonzero(np.abs(finite_a) > 1e6)))
print("gpu has 1e10-ish :", int(np.count_nonzero(np.abs(finite_b) > 1e6)))
d = np.abs(np.nan_to_num(a.astype(np.float64), nan=0.0)
           - np.nan_to_num(b.astype(np.float64), nan=0.0))
flat = np.argsort(d.ravel())[-5:]
for f in flat[::-1]:
    v, y, x = np.unravel_index(f, d.shape)
    print(f"  worst view={v} y={y} x={x} cpu={a[v,y,x]!r} gpu={b[v,y,x]!r} diff={d[v,y,x]:.6g}")
