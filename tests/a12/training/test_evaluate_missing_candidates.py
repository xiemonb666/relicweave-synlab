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
            if fragment_id.startswith("q"):
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


def _evaluate(pool: _Pool, *, query: str = "q", invalid: set[str] | None = None,
              candidate_pool_size: int = 1, all_queries: bool = False):
    return training_api.evaluate(
        checkpoint_ref=None,
        pool_ref=pool,
        top_k=(1,),
        candidate_pool_size=candidate_pool_size,
        queries=None if all_queries else [query],
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
    assert row["conditional_cov@1"] == 1.0  # one in-pool R2 and Top1 retrieves it
    assert row["pool_miss"] is False


def test_all_r2_candidates_missing_produces_zero_coverage_not_na():
    pool = _Pool(
        lineup=["q", "r2-missing-a", "r2-missing-b", "negative"],
        features={"q": {}, "negative": {}},
        neighbours={"q": ["r2-missing-a", "r2-missing-b"]},
    )

    report = _evaluate(pool)
    row = report["per_query"][0]

    assert row["n_historical_neighbours"] == 2
    assert row["missing_feature_historical_neighbours"] == ["r2-missing-a", "r2-missing-b"]
    assert row["hit@1"] == 0.0
    assert row["cov@1"] == 0.0
    assert row["pool_cov"] == 0.0
    assert row["effective_cov@1"] == 0.0
    assert row["conditional_cov@1"] is None
    assert row["pool_miss"] is True
    assert report["metrics"]["pool_miss_count"] == 1


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


def test_training_evaluate_conditional_cov_is_topk_coverage_within_candidate_pool():
    pool = _Pool(
        lineup=["q", "r2-a", "r2-b", "negative"],
        features={"q": {}, "r2-a": {}, "r2-b": {}, "negative": {}},
        neighbours={"q": ["r2-a", "r2-b"]},
    )

    report = _evaluate(pool, candidate_pool_size=3)
    row = report["per_query"][0]

    assert row["first_stage"] == ["r2-a", "r2-b", "negative"]
    assert row["conditional_cov@1"] == pytest.approx(0.5)
    assert row["conditional_cov@1"] == report["metrics"]["per_k"]["k=1"][
        "conditional_cov_at_k"]
    assert row["conditional_cov"] == pytest.approx(0.5)
    assert row["conditional_cov_legacy_pool_census"] == 1.0
    assert report["metrics"]["conditional_cov_legacy_status"] == \
        "LEGACY_POOL_CENSUS_UNVALIDATED_FOR_RETRIEVAL"
    assert report["evaluation_semantics"]["version"] == "historical_R2_denominator_v2"


def test_entire_lineup_without_features_is_reported_as_input_failures():
    pool = _Pool(
        lineup=["q", "r2-missing", "negative"],
        features={},
        neighbours={"q": ["r2-missing"]},
    )

    report = _evaluate(pool, all_queries=True)

    assert report["metrics"]["gallery_size"] == 3
    assert report["metrics"]["feature_available_gallery_size"] == 0
    assert report["metrics"]["encoded_gallery_size"] == 0
    assert report["metrics"]["feature_missing_gallery_ids"] == ["negative", "q", "r2-missing"]
    assert [r["status"] for r in report["per_query"]] == [
        "INPUT_UNAVAILABLE", "INPUT_UNAVAILABLE", "INPUT_UNAVAILABLE"]
    assert report["metrics"]["per_k"]["k=1"]["effective_cov_at_k"] == 0.0


def test_missing_absent_query_does_not_dilute_present_effective_denominator():
    pool = _Pool(
        lineup=["q-present-ok", "r2-present", "q-present-missing", "r2-missing",
                "q-absent-missing", "negative"],
        features={"q-present-ok": {}, "r2-present": {}, "negative": {}},
        neighbours={
            "q-present-ok": ["r2-present"],
            "q-present-missing": ["r2-missing"],
            "q-absent-missing": [],
        },
    )

    report = training_api.evaluate(
        checkpoint_ref=None,
        pool_ref=pool,
        top_k=(1,),
        candidate_pool_size=1,
        queries=["q-present-ok", "q-present-missing", "q-absent-missing"],
        model=_Model(),
    )
    rows = {row["query_id"]: row for row in report["per_query"]}
    metrics = report["metrics"]
    at_one = metrics["per_k"]["k=1"]

    assert rows["q-present-ok"]["effective_cov@1"] == 1.0
    assert rows["q-present-missing"]["effective_cov@1"] == 0.0
    assert rows["q-absent-missing"]["effective_cov@1"] is None
    assert at_one["effective_cov_at_k"] == pytest.approx(0.5)
    assert at_one["effective_cov_at_k_denominator"] == 2
    assert metrics["risk"]["possible_absent"] == 1
    assert metrics["risk"]["possible_present"] == 2
