"""Scratch: capture the traceback of Trainer.fit() on the real package pool."""
from __future__ import annotations

import sys
import traceback

ROOT = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
sys.path.insert(0, ROOT)

from synlab.training.api import _SpecView, _shape_of_pool  # noqa: E402
from synlab.training.model import build_model  # noqa: E402
from synlab.training.smoke import SMOKE_SPEC, load_real_inputs  # noqa: E402
from synlab.training.trainer import Trainer  # noqa: E402

real = load_real_inputs(ROOT + r"\data\a12_exports\closed_loop\training_package")
pool = real["pool"]
dims = _shape_of_pool(pool)
spec = _SpecView(SMOKE_SPEC)
trainer = Trainer(spec, build_model(seed=11, **dims), pool=pool)
try:
    trainer.fit(steps=1)
    print("fit returned:", trainer.metrics.as_dict())
except Exception:
    traceback.print_exc()
