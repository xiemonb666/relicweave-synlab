"""Scratch probe: does the dict-spec -> Trainer path survive api._SpecView?

Reproduces what ``synlab.training.api.resume()`` does (recipe.json's "spec" is a plain dict).
"""
from __future__ import annotations

import json
import sys
import traceback

sys.path.insert(0, r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")

from synlab.training.api import _SpecView  # noqa: E402
from synlab.training.batch import _SamplerCfg  # noqa: E402

SPEC = {
    "run_name": "probe",
    "train_seed": 11,
    "optimization": {"head_lr": 1e-4, "backbone_lr": 1e-5, "weight_decay": 0.01,
                     "warmup_fraction": 0.05, "gradient_clip_norm": 1.0,
                     "accumulation_steps": 1, "max_steps": 3, "precision": "fp32"},
    "sampling": {"queries_per_microbatch": 2, "positive_limit": 2, "legal_negative_limit": 8,
                 "negative_mix": {"R1": 0.5, "R0": 0.5}},
    "curriculum": {"enabled": False},
    "inputs": {"local_token_budget": 256},
}

view = _SpecView(SPEC)
print("type(view):", type(view).__name__)
print("view.sampling:", type(view.sampling).__name__)
print("isinstance(view.sampling, dict):", isinstance(view.sampling, dict))

for name, fn in (
    ("_SamplerCfg.from_spec(_SpecView)", lambda: _SamplerCfg.from_spec(view.sampling)),
    ("_SamplerCfg.from_spec(dict)", lambda: _SamplerCfg.from_spec(SPEC["sampling"])),
):
    try:
        print(f"{name}: OK ->", fn())
    except Exception as exc:  # noqa: BLE001
        print(f"{name}: {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=2)

# what the Trainer itself reads off the spec
for expr, fn in (
    ("Trainer-like head_lr", lambda: float(getattr(getattr(view, "optimization", view), "head_lr", 1e-4))),
    ("Trainer-like max_steps", lambda: int(getattr(getattr(view, "optimization", view), "max_steps", 100))),
    ("curriculum.enabled", lambda: bool(getattr(getattr(view, "curriculum", view), "enabled", True))),
    ("inputs.local_token_budget",
     lambda: int(getattr(getattr(view, "inputs", view), "local_token_budget", 256))),
    ("train_seed", lambda: int(getattr(view, "train_seed", 11))),
):
    try:
        print(f"{expr}: OK ->", fn())
    except Exception as exc:  # noqa: BLE001
        print(f"{expr}: {type(exc).__name__}: {exc}")

print(json.dumps({"note": "probe complete"}, ensure_ascii=False))
