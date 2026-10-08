"""Model/trainer contracts that the real-package smoke run depends on.

These pin the defects found while running a real forward/backward for the first time
(``docs/a12/training_run.md``): the encoder could not run at all, two builds from the same seed
disagreed, ``named_parameters`` names did not match ``state_dict`` keys, and
``Trainer.save_checkpoint`` could not hash its own payload.
"""

from __future__ import annotations

import hashlib

import numpy as np

from _fixtures import build_fixture_pool, make_feature_payloads
from synlab.training.adapter import FeatureBundle
from synlab.training.api import _SpecView
from synlab.training.model import build_model
from synlab.training.smoke import SMOKE_SPEC
from synlab.training.trainer import Trainer


def _payloads(n: int = 3):
    return make_feature_payloads([f"a{i}" for i in range(n)], rng=np.random.default_rng(2))


def _bundle(n: int = 3) -> FeatureBundle:
    return FeatureBundle.from_dict(_payloads(n)).check_shapes()


def _model():
    return build_model(seed=11, quality_input_dim=11, quality_target_dim=8)


def _digest(model) -> str:
    h = hashlib.sha256()
    for name, p in model.encoder.named_parameters():
        h.update(name.encode())
        h.update(np.ascontiguousarray(p.detach().numpy()).tobytes())
    for name, p in model.pair_head.named_parameters(prefix="pair_head."):
        h.update(name.encode())
        h.update(np.ascontiguousarray(p.detach().numpy()).tobytes())
    return h.hexdigest()


def test_named_parameters_names_are_the_state_dict_keys():
    model = _model()
    assert list(dict(model.encoder.named_parameters())) == list(model.encoder.state_dict())
    assert list(dict(model.pair_head.named_parameters())) == list(model.pair_head.state_dict())
    # a prefixed call inserts exactly one separator dot (PyTorch treats the prefix as a module path)
    prefixed = dict(model.encoder.named_parameters(prefix="enc."))
    assert "enc.global_branch.0.weight" in prefixed
    assert not any(".." in name for name in prefixed)
    head_prefixed = dict(model.pair_head.named_parameters(prefix="pair_head."))
    assert "pair_head.q_proj.weight" in head_prefixed
    assert not any(".." in name for name in head_prefixed)


def test_build_model_is_reproducible_for_a_seed():
    assert _digest(_model()) == _digest(_model())
    assert _digest(build_model(seed=12, quality_input_dim=11, quality_target_dim=8)) \
        != _digest(_model())


def test_encoder_forward_runs_and_masks_unobserved_fragments():
    bundle = _bundle(3)
    model = _model()
    features = bundle.to_torch()
    z, valid = model.encoder.encode(features)
    assert z.shape == (3, 64) and valid.all()
    norms = z.detach().norm(dim=-1)
    assert np.allclose(norms.numpy(), 1.0, atol=1e-5)
    # an observation-less fragment (every validity mask False) is reported invalid, not faked
    payloads = _payloads(2)
    empty = dict(payloads["a0"])
    empty["global_valid"] = np.zeros_like(np.asarray(payloads["a0"]["global_valid"]))
    empty["token_valid"] = np.zeros_like(np.asarray(payloads["a0"]["token_valid"]))
    empty["point_valid"] = np.zeros_like(np.asarray(payloads["a0"]["point_valid"]))
    empty["normal_valid"] = np.zeros_like(np.asarray(payloads["a0"]["normal_valid"]))
    empty["quality_valid"] = np.zeros_like(np.asarray(payloads["a0"]["quality_valid"]))
    empty["presence_valid"] = np.zeros_like(np.asarray(payloads["a0"]["presence_valid"]))
    bundle2 = FeatureBundle.from_dict({"a0": empty, "a1": payloads["a1"]}).check_shapes()
    z2, valid2 = model.encoder.encode(bundle2.to_torch())
    assert bool(valid2[0]) is False and float(z2[0].norm()) == 0.0
    assert bool(valid2[1]) is True


def test_parameter_groups_cover_head_and_backbone():
    model = _model()
    groups = model.parameter_groups(head_lr=1e-4, backbone_lr=1e-5)
    by_name = {g["name"]: int(sum(p.numel() for p in g["params"])) for g in groups}
    assert set(by_name) == {"head", "backbone"}
    total = sum(int(p.numel()) for _, p in model.encoder.named_parameters()) + int(
        sum(p.numel() for _, p in model.pair_head.named_parameters()))
    assert by_name["head"] + by_name["backbone"] == total


def test_checkpoint_payload_hash_survives_tensor_state_dicts():
    """``payload_hash`` must be computable (the raw payload holds torch tensors)."""
    pool = build_fixture_pool(lineages={"L1": ["a0", "a1", "a2"]}, r2={"a0": ["a1"]},
                              r1=[("a0", "a2")], with_features=True)
    trainer = Trainer(_SpecView(SMOKE_SPEC), _model(), pool=pool)
    payload = trainer.checkpoint_payload()
    assert payload["payload_hash"].startswith("sha256:")
    again = trainer.checkpoint_payload()
    assert again["payload_hash"] == payload["payload_hash"]
    # a changed weight must change the payload hash (it is a content hash, not a formality)
    with __import__("torch").no_grad():
        next(trainer.model.encoder.proj.parameters()).add_(1.0)
    assert trainer.checkpoint_payload()["payload_hash"] != payload["payload_hash"]
    assert set(payload) >= {"model", "pair_head", "optimizer", "scheduler", "step",
                            "sampler_cursor", "rng_state", "torch_rng_state", "metrics"}
