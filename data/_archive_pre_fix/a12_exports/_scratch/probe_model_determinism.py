"""Scratch: is build_model(seed=...) deterministic across processes / within a process?"""
from __future__ import annotations

import hashlib
import sys

sys.path.insert(0, r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")

import numpy as np  # noqa: E402
import torch  # noqa: E402

from synlab.training.model import build_model  # noqa: E402


def digest(model) -> str:
    h = hashlib.sha256()
    for name, p in model.encoder.named_parameters():
        h.update(name.encode())
        h.update(np.ascontiguousarray(p.detach().numpy()).tobytes())
    for name, p in model.pair_head.named_parameters(prefix="pair_head."):
        h.update(name.encode())
        h.update(np.ascontiguousarray(p.detach().numpy()).tobytes())
    return "sha256:" + h.hexdigest()[:32]


m1 = build_model(seed=11, quality_input_dim=2, quality_target_dim=1)
m2 = build_model(seed=11, quality_input_dim=2, quality_target_dim=1)
print("torch threads:", torch.get_num_threads())
print("in-process model1:", digest(m1))
print("in-process model2:", digest(m2))
print("equal in-process:", digest(m1) == digest(m2))
print("proj.weight[0,:4] :", m1.encoder.proj.weight.detach()[0, :4].tolist())
print("global_branch.0.weight[0,0,0,:3]:",
      m1.encoder.global_branch[0].weight.detach()[0, 0, 0, :3].tolist())
print("pair_head.q_proj.weight[0,:3]:", m1.pair_head.q_proj.weight.detach()[0, :3].tolist())
