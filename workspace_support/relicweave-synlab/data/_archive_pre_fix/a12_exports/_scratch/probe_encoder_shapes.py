"""Scratch: prove the FragmentEncoder fusion/projection shape mismatch (read-only probe)."""
from __future__ import annotations

import sys

sys.path.insert(0, r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")

import torch  # noqa: E402

from synlab.training.adapter import FeatureBundle  # noqa: E402
from synlab.training.model import FragmentEncoder, build_model  # noqa: E402
from tests.a12._fixtures import make_feature_payloads  # noqa: E402  (fixture payloads only)

payloads = make_feature_payloads(["a0", "a1"], rng=__import__("numpy").random.default_rng(0))
bundle = FeatureBundle.from_dict(payloads).check_shapes()
features = bundle.to_torch()

enc = FragmentEncoder(width=32, out_dim=64, seed=0, quality_input_dim=11, quality_target_dim=8)
print("global_branch out:", enc.global_branch(torch.zeros(2 * 3, 3, 12, 12)).shape)
print("geometry_branch out:", enc.geometry_branch(torch.zeros(2, 6)).shape)
print("token_branch out:", enc.token_branch(torch.zeros(2, 256)).shape)
print("quality_branch out:", enc.quality_branch(torch.zeros(2, enc.quality_input_dim)).shape)
print("gate out:", enc.gate(torch.zeros(2, 32 * 4)).shape)
print("proj in_features:", enc.proj.in_features, "out_features:", enc.proj.out_features)
print("gated-sum fused width:", 32)
try:
    z, valid = enc.encode(features)
    print("encode OK:", z.shape, valid.tolist())
except Exception as exc:  # noqa: BLE001
    print("encode FAILED:", type(exc).__name__, exc)

model = build_model(seed=0, quality_input_dim=11, quality_target_dim=8)
try:
    z, valid = model.encoder.encode(features)
    print("build_model encode OK:", z.shape)
except Exception as exc:  # noqa: BLE001
    print("build_model encode FAILED:", type(exc).__name__, exc)
