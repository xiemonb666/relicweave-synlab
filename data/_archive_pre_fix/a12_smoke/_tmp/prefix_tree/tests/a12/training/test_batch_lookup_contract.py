"""Contract tests for the training-batch neighbour lookup (interface defect fix).

Background -- the defect and its resolution
-------------------------------------------
``synlab/training/batch.py::_build_lookup`` returns three lookups.  Its docstring (and the
pool protocol used across the repository: ``pool.neighbours(fid)`` in
``relations.gallery.RelationPool``, ``training.sampler.PoolIndex``,
``qc.loader_probe.ExportedRelationPool`` and ``build_training_batch``'s own documented
"callable/object with ``relation(a, b)`` plus ``neighbours(fid)``") defines
``neighbours(q) -> set`` as a **callable**.  The implementation returned a bare ``dict`` and
``build_training_batch`` read it with ``neighbours_lookup.get(qid, ())``, so the frozen
integration test ``tests/a12/relations/test_sampler.py::test_rows_feed_training_batch`` -- whose
local wrapper hands the consumer a *function* -- failed with
``AttributeError: 'function' object has no attribute 'get'``.

The callable side is the contract (docstring + repository-wide pool protocol + the consumer
usage pinned by the out-of-scope integration test), so ``_build_lookup`` now returns a callable
:class:`_NeighboursIndex`.  These tests pin:

1. all three lookups are callable and ``neighbours(q)`` equals ``pool.neighbours(q)``;
2. ``build_training_batch`` really *calls* the lookup -- the tests below supply a lookup that
   has no mapping interface at all, so a ``.get()`` consumer fails immediately;
3. the semantics that depend on the lookup (historical-R2 exclusions) still hold.
"""

from __future__ import annotations

import numpy as np
import pytest

from _fixtures import build_fixture_pool, make_feature_payloads
from synlab.errors import ErrorCode, SynLabError
from synlab.training import batch as training_batch
from synlab.training.adapter import EXCLUSION_KNOWN_R2, FeatureBundle


def _pool(**kwargs):
    kwargs.setdefault("lineages", {"L1": ["a0", "a1", "a2"], "L2": ["b0", "b1"]})
    kwargs.setdefault("r2", {"a0": ["a1"]})
    kwargs.setdefault("r1", [("a0", "a2"), ("a1", "a2")])
    return build_fixture_pool(**kwargs)


def _bundle(pool, ids=("a0", "a1", "a2")):
    return FeatureBundle.from_dict(make_feature_payloads(list(ids), rng=np.random.default_rng(5))
                                   ).check_shapes()


def test_build_lookup_returns_callable_neighbours_lookup():
    """The docstring contract: ``(relation(q,c), neighbours(q), confirmed(q,c))`` are callables."""
    pool = _pool()
    ids = list(pool.lineup)
    relation_of, neighbours_of, confirmed_of = training_batch._build_lookup(None, pool, ids)

    assert callable(relation_of) and callable(neighbours_of) and callable(confirmed_of)
    for fid in ids:
        assert neighbours_of(fid) == set(pool.neighbours(fid))
    assert neighbours_of("a0") == {"a1"}
    assert relation_of("a0", "a1") == "R2" and relation_of("a0", "a2") == "R1"
    assert confirmed_of("a0", "a1") is True
    # the returned set is a copy: a caller cannot corrupt the index through it
    neighbours_of("a0").add("b0")
    assert neighbours_of("a0") == {"a1"}


def test_neighbours_index_keeps_mapping_access_for_the_frozen_integration_test():
    """Compatibility affordance: ``tests/a12/relations`` wraps this object and reads ``.get()``.

    Mapping access is *not* the contract (the consumer calls the lookup, see the next test); it
    exists only so that the out-of-scope wrapper keeps working until it is deleted.  Both forms
    must resolve exactly the same adjacency.
    """
    pool = _pool()
    _, neighbours_of, _ = training_batch._build_lookup(None, pool, list(pool.lineup))
    assert isinstance(neighbours_of, dict)
    for fid in pool.lineup:
        assert set(neighbours_of.get(fid, set())) == neighbours_of(fid)
    assert neighbours_of.get("nope", set()) == set()


def test_consumer_calls_the_lookup_even_without_a_mapping_interface():
    """A plain function (no ``.get``) must be enough -- this is the contract the fix restores."""
    pool = _pool()
    bundle = _bundle(pool)
    original = training_batch._build_lookup

    seen: list[str] = []

    def _patched(labels, pool_arg, ids):
        relation_of, neighbours, confirmed_of = original(labels, pool_arg, ids)

        def _neighbours_of(fid):
            seen.append(str(fid))
            return set(neighbours(fid))

        assert not hasattr(_neighbours_of, "get")
        return relation_of, _neighbours_of, confirmed_of

    rows = [{"query": "a0", "positives": ["a1"], "negatives": ["a2"], "excluded": [],
             "sample_key": "row::a0"}]
    training_batch._build_lookup = _patched
    try:
        built = training_batch.build_training_batch(bundle, pool=pool, rows=rows,
                                                    block_r2_contamination=False)
    finally:
        training_batch._build_lookup = original

    assert seen, "the consumer never called the neighbours lookup"
    assert built.pos_mask.sum() == 1 and built.neg_mask.sum() == 1
    assert built.negative_is_r2_history.sum() == 0
    assert training_batch.negative_audit(built)["ok"] is True


def test_historical_neighbour_is_still_rejected_as_an_ordinary_negative():
    """The lookup's only unique job (line 321): a *historical* neighbour is never a negative.

    ``a2`` is a confirmed R1 (legal by relation code alone) and is additionally declared a
    historical neighbour by the pool, so only the neighbour lookup can catch it.
    """
    pool = _pool()
    pool.historical_neighbours["a0"] = ["a1", "a2"]
    bundle = _bundle(pool)
    rows = [{"query": "a0", "positives": ["a1"], "negatives": ["a2"], "excluded": [],
             "sample_key": "row::a0"}]
    with pytest.raises(SynLabError) as excinfo:
        training_batch.build_training_batch(bundle, pool=pool, rows=rows)
    assert excinfo.value.code == ErrorCode.LEAKAGE_DETECTED
    assert "historical R2" in str(excinfo.value)

    # with the contamination guard off the pair is *kept and flagged* by the same lookup, and
    # the module's own final audit still refuses the batch (a flag is not a licence)
    with pytest.raises(SynLabError) as audit_excinfo:
        training_batch.build_training_batch(bundle, pool=pool, rows=rows,
                                            block_r2_contamination=False)
    assert "historical R2 inside neg_mask" in str(audit_excinfo.value)


def test_excluded_historical_neighbour_is_reported_as_known_r2():
    """Line 359 reads the same lookup to explain *why* a candidate was excluded.

    ``C`` is the widest row in the batch, so the excluded candidate gets a column only when
    another row is wider (see ``docs/a12/training_run.md`` §7 for this known limitation).
    """
    pool = _pool()
    pool.historical_neighbours["a0"] = ["a1", "a2"]
    bundle = _bundle(pool, ids=pool.lineup)
    rows = [
        {"query": "b1", "positives": [], "negatives": ["a0", "b0"], "excluded": [],
         "sample_key": "row::b1"},
        {"query": "a0", "positives": ["a1"], "negatives": [], "excluded": ["a2"],
         "sample_key": "row::a0"},
    ]
    built = training_batch.build_training_batch(bundle, pool=pool, rows=rows)
    reasons = np.asarray(built.exclusion_reason)
    assert built.excluded_mask.sum() == 1
    assert EXCLUSION_KNOWN_R2 in reasons[built.excluded_mask].tolist()
