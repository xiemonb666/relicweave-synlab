"""Sampler-config interface: mapping specs **and** attribute views must both work.

``synlab.training.api.resume`` rebuilds the training spec from ``recipe.json`` as
``api._SpecView`` (an attribute view) and hands it to ``Trainer``, which passes
``spec.sampling`` into ``build_training_batch(sampler_cfg=...)``.  Before the fix,
``_SamplerCfg.from_spec`` read ``negative_mix`` with ``mix.get(...)``, which on a ``_SpecView``
resolved to ``None`` and raised ``TypeError: 'NoneType' object is not callable`` -- i.e. every
``api.resume()`` of a run written by ``api.train()`` crashed while building its first batch.
"""

from __future__ import annotations

import numpy as np

from _fixtures import build_fixture_pool, make_feature_payloads
from synlab.training.adapter import FeatureBundle
from synlab.training.api import _SpecView
from synlab.training.batch import _SamplerCfg, build_training_batch

SAMPLING = {"queries_per_microbatch": 3, "positive_limit": 1, "legal_negative_limit": 4,
            "negative_mix": {"R1": 0.25, "R0": 0.75}}


def test_sampler_cfg_from_mapping():
    cfg = _SamplerCfg.from_spec(SAMPLING)
    assert (cfg.queries, cfg.positive_limit, cfg.negative_limit) == (3, 1, 4)
    assert cfg.negative_mix == (0.25, 0.75)


def test_sampler_cfg_from_attribute_view():
    """The ``api.resume`` path: ``recipe["spec"]["sampling"]`` wrapped in ``_SpecView``."""
    cfg = _SamplerCfg.from_spec(_SpecView(SAMPLING))
    assert (cfg.queries, cfg.positive_limit, cfg.negative_limit) == (3, 1, 4)
    assert cfg.negative_mix == (0.25, 0.75)


def test_sampler_cfg_defaults_and_explicit_zero_are_not_confused():
    assert _SamplerCfg.from_spec(None).negative_mix == (0.5, 0.5)
    assert _SamplerCfg.from_spec({}).negative_mix == (0.5, 0.5)
    assert _SamplerCfg.from_spec(_SpecView({})).negative_mix == (0.5, 0.5)
    # an explicit 0.0 weight is a real setting, not "missing"
    cfg = _SamplerCfg.from_spec({"negative_mix": {"R1": 0.0, "R0": 1.0}})
    assert cfg.negative_mix == (0.0, 1.0)
    assert _SamplerCfg.from_spec(_SpecView({"negative_mix": {"R1": 0.0, "R0": 1.0}})
                                 ).negative_mix == (0.0, 1.0)


def test_build_training_batch_accepts_the_resume_style_sampling_view():
    pool = build_fixture_pool(lineages={"L1": ["a0", "a1", "a2"]}, r2={"a0": ["a1"]},
                              r1=[("a0", "a2")], with_features=True)
    bundle = FeatureBundle.from_dict(
        {fid: make_feature_payloads([fid], rng=np.random.default_rng(3))[fid]
         for fid in pool.lineup}).check_shapes()
    rows = [{"query": "a0", "positives": ["a1"], "negatives": ["a2"], "excluded": [],
             "sample_key": "row::a0"}]
    built = build_training_batch(bundle, pool=pool, rows=rows,
                                 sampler_cfg=_SpecView(SAMPLING))
    assert built.pos_mask.sum() == 1 and built.neg_mask.sum() == 1
