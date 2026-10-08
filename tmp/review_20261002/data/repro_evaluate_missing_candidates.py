"""Minimal reproduction: a true neighbor without a feature is removed from eval's denominator."""

from __future__ import annotations

import json

import numpy as np

import synlab.training.api as training_api


class Bundle:
    def __init__(self, fragment_ids: list[str]):
        self.fragment_ids = fragment_ids

    @classmethod
    def from_dict(cls, payloads):
        return cls(list(payloads))

    def check_shapes(self):
        return self

    def to_torch(self):
        return self.fragment_ids


class Encoder:
    def eval(self):
        return None

    def encode_batch(self, fragment_ids):
        vectors = np.tile(np.array([[1.0, 0.0]], dtype=np.float32), (len(fragment_ids), 1))
        return vectors, np.ones(len(fragment_ids), dtype=bool)


class Model:
    encoder = Encoder()

    def index_identity(self):
        return {"index_kind": "dual_tower_encoder", "uses_pair_head": False}


class Pool:
    pool_id = "repro-pool"
    lineup = ["q", "r2-has-feature", "r2-missing-feature"]
    features = {"q": {}, "r2-has-feature": {}}

    def neighbours(self, query_id: str):
        return ["r2-has-feature", "r2-missing-feature"] if query_id == "q" else []


training_api.FeatureBundle = Bundle
report = training_api.evaluate(
    checkpoint_ref=None,
    pool_ref=Pool(),
    top_k=(1,),
    candidate_pool_size=1,
    queries=["q"],
    model=Model(),
)
print(json.dumps(report["per_query"][0], sort_keys=True))
print(json.dumps(report["metrics"]["per_k"]["k=1"], sort_keys=True))
