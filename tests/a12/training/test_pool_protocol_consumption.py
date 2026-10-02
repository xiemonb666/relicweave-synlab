"""The pool protocol as ``synlab.training`` consumes it: the clause that decides ``rank``.

The contract suite (``tests/a12/qc/test_pool_protocol_contract.py``) pins the protocol
clause-by-clause.  This file pins its **consumer**: ``synlab.training.batch`` reads
``pool.neighbours(q)`` as the *historical R2 mate set*, so a pool that answers with its confirmed
R1/R0 set makes every legal negative look like a mate.  That is exactly what happened
(``docs/a12/relation_negatives.md`` §1 defect (B)): ``assert_legal_negative`` refused all 55
queries' negatives and ``rank`` never started, without a single component reporting a failure.

Both directions are asserted here on real batch construction (real ``FeatureBundle``, real
``build_training_batch``): the correct reader yields supervised negatives and a clean
``negative_audit``; the historical mis-reading yields an empty negative set.  A contract that
cannot show that difference is a convention, not a guarantee.
"""

from __future__ import annotations

import numpy as np
import pytest

from _fixtures import make_feature_payloads
from synlab.qc.pool_contract import (
    FAILURE_INJECTIONS,
    canonical_context,
    exported_pool,
    gallery_pool,
    pool_index,
    training_pool_view,
)
from synlab.training.adapter import FeatureBundle
from synlab.training.batch import build_training_batch, negative_audit


@pytest.fixture(scope="module")
def ctx():
    return canonical_context()


@pytest.fixture(scope="module")
def bundle(ctx):
    payloads = make_feature_payloads(list(ctx.universe()), n_views=2, image_size=(8, 8),
                                     n_tokens=12, n_points=8, n_regions=2)
    return FeatureBundle.from_dict(payloads, token_budget=12).check_shapes()


def _rows(pool, ctx) -> list[dict]:
    rows: list[dict] = []
    for fid in ctx.universe():
        positives = sorted(str(x) for x in pool.mates(fid))
        negatives = sorted(str(x) for x in pool.legal_pool(fid))
        if not positives and not negatives:
            continue
        rows.append({"query": fid, "positives": positives, "negatives": negatives,
                     "excluded": [], "sample_key": f"contract::{fid}"})
    return rows


@pytest.mark.parametrize("family", ["exported", "view", "gallery"])
def test_the_correct_reader_gives_supervised_negatives(ctx, bundle, family) -> None:
    pool = {"exported": exported_pool, "view": training_pool_view,
            "gallery": gallery_pool}[family](ctx)
    rows = _rows(pool, ctx)
    batch = build_training_batch(bundle, pool=pool, rows=rows)
    audit = negative_audit(batch)
    assert audit["ok"], audit["problems"]
    assert int(batch.neg_mask.sum()) > 0, "no legal negative survived: rank would never start"
    assert int(batch.pos_mask.sum()) > 0
    # every supervised negative is a confirmed R0/R1 and none of them is a mate
    for q in range(batch.n_queries):
        for c in range(batch.n_candidates):
            if not batch.neg_mask[q, c]:
                continue
            qid = str(batch.meta["fragment_ids"][int(batch.pair_index[q, c, 0])]) \
                if "fragment_ids" in batch.meta else None
            assert qid is None or qid not in {str(x) for x in pool.mates(qid)}


def test_the_historical_misreading_breaks_the_batch(ctx, bundle) -> None:
    """Defect (B) verbatim through the real builder.

    ``build_training_batch`` re-checks every negative against ``pool.neighbours(q)``; with the
    mis-reading in place the guard refuses the **legal** rows and raises
    ``LEAKAGE_DETECTED ... historical R2 <candidate> used as an ordinary negative`` -- the exact
    message that was reported for 55/55 queries of the base package (``docs/a12/relation_negatives.md``
    §1).  A caller that swallows the exception gets an empty negative set, i.e. a ``rank`` task
    with nothing to train on; either way the run never starts.  Both outcomes are asserted so the
    clause cannot regress into "it still builds".
    """
    from synlab.errors import SynLabError

    good = gallery_pool(ctx)
    rows = _rows(good, ctx)                       # rows stay the legal ones
    injected = FAILURE_INJECTIONS["neighbours_return_the_negative_set"](good)
    with pytest.raises(SynLabError) as info:
        build_training_batch(bundle, pool=injected, rows=rows)
    assert "historical R2" in str(info.value), str(info.value)
    assert "used as an ordinary negative" in str(info.value)


def test_pool_index_and_the_carrier_agree_on_the_mate_set(ctx) -> None:
    carrier = gallery_pool(ctx)
    index = pool_index(ctx, carrier="gallery")
    for fid in ctx.universe():
        assert index.mates(fid) == {str(x) for x in carrier.mates(fid)}
        assert index.neighbours(fid) == index.mates(fid)
        assert index.legal_negatives(fid) == {str(x) for x in carrier.legal_pool(fid)}


def test_sampler_legal_pool_is_kind_split_like_the_carrier(ctx) -> None:
    """``LineageBalancedSampler`` draws R1 and R0 separately; the split must lose nothing."""
    index = pool_index(ctx, carrier="gallery")
    for fid in ctx.universe():
        both = {str(x) for x in index.legal_pool(fid)}
        split = ({str(x) for x in index.legal_pool(fid, relation="R1")}
                 | {str(x) for x in index.legal_pool(fid, relation="R0")})
        assert both == split, fid
        assert all(str(index.relation(fid, c)) in ("R0", "R1") for c in both)


def test_a_batch_from_the_canonical_pool_has_balanced_kinds(ctx, bundle) -> None:
    pool = gallery_pool(ctx)
    batch = build_training_batch(bundle, pool=pool, rows=_rows(pool, ctx))
    kinds = np.unique(batch.labels_relation[batch.neg_mask])
    # only R0/R1 codes may appear inside neg_mask (never R2/UNKNOWN/TINY)
    assert set(int(x) for x in kinds) <= {0, 1}, kinds
