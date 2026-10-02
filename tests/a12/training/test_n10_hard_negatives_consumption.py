"""N10 as ``synlab.training`` consumes it: the auxiliary class must not move a denominator.

``relations.hard_negatives_table`` attaches the ``HARD_NEGATIVE_MATE_PRESENT`` class to a row
under its **own** key (``hard_negatives``), never under ``negatives``.  This file pins the two
consequences on real batches built from the canonical relation rows:

* **off** (the default) the batch is the batch: no hard-negative slot, nothing changes;
* **on** the class occupies its own slot block after the pos/neg block, every primary
  denominator (positives, negatives, excluded, ``effective_queries``, the rank denominator) and
  both primary masks are **bit-identical**, and ``neg_mask`` stays disjoint from
  ``hard_neg_mask``.

That is the "does not enter any primary metric denominator" constraint of the Lead ruling,
measured on the tensor that the losses read -- not asserted in prose.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from _fixtures import make_feature_payloads
from synlab.qc.pool_contract import canonical_context, canonical_rows
from synlab.relations.hard_negatives_table import (
    HARD_NEGATIVES_FILE,
    attach_hard_negatives,
    build_records,
    card_payload,
    denominator_snapshot,
    load_hard_negatives,
    write_table,
)
from synlab.training.adapter import FeatureBundle
from synlab.training.batch import build_training_batch, negative_audit
from synlab.training.smoke import TrainingPoolView

QUERY = "a0-m"


@pytest.fixture(scope="module")
def ctx():
    return canonical_context()


@pytest.fixture(scope="module")
def pool(ctx):
    rows = canonical_rows()
    lineup = sorted({str(r["query"]) for r in rows} | {str(r["candidate"]) for r in rows})
    return TrainingPoolView(rows, lineup=lineup, pool_id="canonical")


@pytest.fixture(scope="module")
def bundle(ctx):
    payloads = make_feature_payloads(list(ctx.universe()), n_views=2, image_size=(8, 8),
                                     n_tokens=12, n_points=8, n_regions=2)
    return FeatureBundle.from_dict(payloads, token_budget=12).check_shapes()


@pytest.fixture(scope="module")
def table(tmp_path_factory: pytest.TempPathFactory):
    rows = canonical_rows()
    records, report = build_records(rows, source_relations_hash="sha256:canonical")
    assert records
    root: Path = tmp_path_factory.mktemp("n10")
    written = write_table(records, root / HARD_NEGATIVES_FILE,
                          card=card_payload(rows=len(records), rejected=report["rejected"]))
    return load_hard_negatives(written["path"], enabled=False)


def _row(pool, table, *, limit: int) -> dict:
    hard = table.by_query(QUERY)[:limit]
    positives = sorted(str(x) for x in pool.mates(QUERY))[:1]
    negatives = [c for c in pool.legal_pool(QUERY) if c not in set(hard)][:3]
    assert positives and negatives and hard
    return {"query": QUERY, "positives": positives, "negatives": negatives,
            "sample_key": f"n10::{QUERY}"}


def test_the_switch_off_and_on_leave_every_primary_denominator_identical(pool, bundle, table) -> None:
    base = [_row(pool, table, limit=2)]
    off_rows = attach_hard_negatives(base, table, enabled=False)
    on_rows = attach_hard_negatives(base, table, enabled=True, limit=2)
    assert "hard_negatives" not in off_rows[0]
    assert on_rows[0]["hard_negatives"] and on_rows[0]["negatives"] == base[0]["negatives"]
    off = build_training_batch(bundle, pool=pool, rows=off_rows)
    on = build_training_batch(bundle, pool=pool, rows=on_rows)
    off_snapshot = denominator_snapshot(off)
    on_snapshot = denominator_snapshot(on)
    for key in ("n_queries", "positives", "negatives", "excluded", "effective_queries",
                "rank_denominator"):
        assert off_snapshot[key] == on_snapshot[key], (key, off_snapshot, on_snapshot)
    assert off_snapshot["hard_negatives"] == 0
    assert on_snapshot["hard_negatives"] == 2
    c_off = int(off.n_candidates)
    assert np.array_equal(off.neg_mask, on.neg_mask[:, :c_off])
    assert np.array_equal(off.pos_mask, on.pos_mask[:, :c_off])
    assert np.array_equal(off.labels_relation, on.labels_relation[:, :c_off])
    assert on_snapshot["shape"]["c_hard"] == 2


def test_the_hard_block_is_disjoint_from_the_ordinary_negatives(pool, bundle, table) -> None:
    rows = attach_hard_negatives([_row(pool, table, limit=2)], table, enabled=True, limit=2)
    batch = build_training_batch(bundle, pool=pool, rows=rows)
    assert batch.hard_neg_mask.any()
    assert not (batch.hard_neg_mask & batch.neg_mask).any()
    assert not (batch.hard_neg_mask & batch.pos_mask).any()
    assert not (batch.hard_neg_mask & batch.excluded_mask).any()
    audit = negative_audit(batch)
    assert audit["ok"], audit["problems"]
    assert audit["hard_negatives"] == 2
    assert audit["negatives"] == int(batch.neg_mask.sum())


def test_the_class_is_supervised_only_for_a_mate_present_query(pool, bundle, table) -> None:
    rows = attach_hard_negatives([_row(pool, table, limit=2)], table, enabled=True, limit=2)
    batch = build_training_batch(bundle, pool=pool, rows=rows)
    assert bool(batch.hard_neg_query_mate.all())
    assert int(batch.hard_negative_queries().size) == 1
    assert int(batch.mate_present.sum()) > 0            # the label-side mate flag is filled


def test_attaching_a_class_candidate_that_is_already_a_negative_is_refused(pool, table) -> None:
    row = _row(pool, table, limit=1)
    clash = table.by_query(QUERY)[0]
    row["negatives"] = [clash]
    with pytest.raises(ValueError):
        attach_hard_negatives([row], table, enabled=True, limit=1)
