from __future__ import annotations

import numpy as np
import pytest

import synlab.training.api as training_api


class _Bundle:
    def __init__(self, fragment_ids: list[str]):
        self.fragment_ids = fragment_ids

    @classmethod
    def from_dict(cls, payloads):
        return cls(list(payloads))

    def check_shapes(self):
        return self

    def to_torch(self):
        return self


class _Encoder:
    def __init__(self, invalid: set[str] | None = None):
        self.invalid = invalid or set()

    def eval(self):
        return None

    def encode_batch(self, bundle: _Bundle):
        vectors = np.tile(np.array([[0.0, 1.0]], dtype=np.float32),
                          (len(bundle.fragment_ids), 1))
        for i, fragment_id in enumerate(bundle.fragment_ids):
            if fragment_id == "q":
                vectors[i] = [1.0, 0.0]
            elif fragment_id.startswith("r2-"):
                vectors[i] = [1.0, 0.0]
        valid = np.asarray([fid not in self.invalid for fid in bundle.fragment_ids], dtype=bool)
        return vectors, valid


class _Model:
    def __init__(self, invalid: set[str] | None = None):
        self.encoder = _Encoder(invalid)

    def index_identity(self):
        return {"index_kind": "dual_tower_encoder", "uses_pair_head": False}


class _Pool:
    pool_id = "evaluation-test-pool"

    def __init__(self, lineup: list[str], features: dict[str, dict],
                 neighbours: dict[str, list[str]]):
        self.lineup = lineup
        self.features = features
        self._neighbours = neighbours

    def neighbours(self, query_id: str) -> list[str]:
        return self._neighbours.get(query_id, [])


@pytest.fixture(autouse=True)
def _fake_feature_bundle(monkeypatch):
    monkeypatch.setattr(training_api, "FeatureBundle", _Bundle)


def _evaluate(pool: _Pool, *, query: str = "q", invalid: set[str] | None = None):
    return training_api.evaluate(
        checkpoint_ref=None,
        pool_ref=pool,
        top_k=(1,),
        candidate_pool_size=1,
        queries=[query],
        model=_Model(invalid),
    )


def test_partial_missing_r2_remains_in_coverage_denominator():
    pool = _Pool(
        lineup=["q", "r2-present", "r2-missing", "negative"],
        features={"q": {}, "r2-present": {}, "negative": {}},
        neighbours={"q": ["q", "r2-present", "r2-missing"]},
    )

    report = _evaluate(pool)
    row = report["per_query"][0]

    assert row["historical_neighbours"] == ["r2-missing", "r2-present"]
    assert row["n_historical_neighbours"] == 2
    assert row["historical_neighbour_availability"] == {
        "r2-missing": "FEATURE_MISSING",
        "r2-present": "ENCODABLE",
    }
    assert row["missing_feature_historical_neighbours"] == ["r2-missing"]
    assert row["cov@1"] == pytest.approx(0.5)
    assert row["pool_cov"] == pytest.approx(0.5)


def test_all_r2_candidates_missing_produces_zero_coverage_not_na():
    pool = _Pool(
        lineup=["q", "r2-missing-a", "r2-missing-b", "negative"],
        features={"q": {}, "negative": {}},
        neighbours={"q": ["r2-missing-a", "r2-missing-b"]},
    )

    row = _evaluate(pool)["per_query"][0]

    assert row["n_historical_neighbours"] == 2
    assert row["missing_feature_historical_neighbours"] == ["r2-missing-a", "r2-missing-b"]
    assert row["hit@1"] == 0.0
    assert row["cov@1"] == 0.0
    assert row["pool_cov"] == 0.0
    assert row["effective_cov@1"] == 0.0


def test_unencodable_r2_candidate_is_reported_without_shrinking_denominator():
    pool = _Pool(
        lineup=["q", "r2-invalid", "r2-present", "negative"],
        features={"q": {}, "r2-invalid": {}, "r2-present": {}, "negative": {}},
        neighbours={"q": ["r2-invalid", "r2-present"]},
    )

    row = _evaluate(pool, invalid={"r2-invalid"})["per_query"][0]

    assert row["n_historical_neighbours"] == 2
    assert row["historical_neighbour_availability"]["r2-invalid"] == \
        "ENCODER_INPUT_UNAVAILABLE"
    assert row["unencodable_historical_neighbours"] == ["r2-invalid"]
    assert row["cov@1"] == pytest.approx(0.5)


def test_missing_query_keeps_full_r2_and_reports_zero_effective_metrics():
    pool = _Pool(
        lineup=["q-missing", "r2-present", "r2-missing", "negative"],
        features={"r2-present": {}, "negative": {}},
        neighbours={"q-missing": ["r2-present", "r2-missing"]},
    )

    report = _evaluate(pool, query="q-missing")
    row = report["per_query"][0]
    aggregate = report["metrics"]["per_k"]["k=1"]

    assert row["status"] == "INPUT_UNAVAILABLE"
    assert row["historical_neighbours"] == ["r2-missing", "r2-present"]
    assert row["n_historical_neighbours"] == 2
    assert row["hit@1"] is None and row["cov@1"] is None
    assert row["effective_hit@1"] == 0.0
    assert row["effective_cov@1"] == 0.0
    assert aggregate["effective_hit_at_k"] == 0.0
    assert aggregate["effective_cov_at_k"] == 0.0


def test_open_set_query_with_zero_r2_preserves_na_metrics():
    pool = _Pool(
        lineup=["q", "negative"],
        features={"q": {}, "negative": {}},
        neighbours={"q": []},
    )

    row = _evaluate(pool)["per_query"][0]

    assert row["status"] == "OK"
    assert row["historical_neighbours"] == []
    assert row["n_historical_neighbours"] == 0
    assert row["hit@1"] is None
    assert row["cov@1"] is None
