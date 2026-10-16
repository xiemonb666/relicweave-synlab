"""Introspect the freshly installed torch to see whether the Python tree is complete."""
from __future__ import annotations

import sys

import torch

print("torch.__file__ :", torch.__file__)
print("torch.__version__:", torch.__version__)
names = sorted(n for n in dir(torch) if not n.startswith("_"))
print("public names   :", len(names))
for probe in ("manual_seed", "randn", "Tensor", "tensor", "zeros", "nn", "cuda", "random",
              "save", "load", "arange", "matmul", "ones", "device"):
    print(f"   has {probe:12s}:", hasattr(torch, probe))
print("sys.modules torch submodules:",
      sorted(m for m in sys.modules if m.startswith("torch") and m.count('.') <= 1)[:25])
import torch.random as tr  # noqa: E402
print("torch.random.manual_seed:", hasattr(tr, "manual_seed"))
print("dir(torch) sample:", names[:40])
