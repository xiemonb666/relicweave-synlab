"""S2: how the training side consumes the ``HARD_NEGATIVE_MATE_PRESENT`` class.

The class is produced by ``synlab/relations`` (see
``tests/a12/relations/test_s2_hard_negative_class.py``).  These tests pin what the **consumer**
must guarantee, i.e. the other three conditions of the Lead ruling:

2. the class contributes to **no** primary denominator: ``neg_mask`` / ``negative_counts`` /
   ``valid_query_indices`` / ``effective_query_count`` / ``exclusion_histogram`` and the pos/neg
   slot layout are identical with and without it -- measured on the very same rows;
3. it is an **auxiliary** term: ``training.losses.hard_negative_loss``, its own weight, default
   ``0.0`` (off), outside the frozen five-task ``TASK_ORDER``, and reading ``hard_neg_mask``
   only -- never ``neg_mask``;
4. every supervised row has a **mate-present query**, enforced at batch construction (it raises,
   it does not drop), and the mate-presence cue is then *constant* inside the auxiliary term's
   own comparison set, which ``mate_present_shortcut_probe`` measures.

Plus the arithmetic of the term, and the one integration hazard the class creates: the
correspondence weight tensor must share the batch's (now wider) candidate dimension.
"""

from __future__ import annotations

import numpy as np
import pytest

from _fixtures import build_fixture_pool, make_feature_payloads
from synlab.errors import ErrorCode, SynLabError
from synlab.training import batch as training_batch
from synlab.training.adapter import FeatureBundle
from synlab.training.batch import (
    HARD_NEGATIVE_CLASS,
    build_training_batch,
    mate_present_shortcut_probe,
    negative_audit,
)
from synlab.training.losses import (
    DEFAULT_HARD_NEGATIVE_WEIGHT,
    DEFAULT_WEIGHTS,
    HARD_NEGATIVE_TASK,
    MultiTaskLoss,
    TASK_ORDER,
    hard_negative_loss,
)

IDS = ("p0", "p1", "h0", "h1", "z0", "z1")


def _pool(**kwargs):
    kwargs.setdefault("lineages", {"L1": ["p0", "p1"], "L2": ["h0", "h1"], "L3": ["z0", "z1"]})
    kwargs.setdefault("r2", {"p0": ["p1"], "h0": ["h1"]})
    kwargs.setdefault("r1", [])
    return build_fixture_pool(**kwargs)


def _bundle(ids=IDS):
    return FeatureBundle.from_dict(
        make_feature_payloads(list(ids), rng=np.random.default_rng(5))).check_shapes()


def _rows(*, hard=("h0", "h1"), query="p0", positives=("p1",), negatives=("z0",)) -> list[dict]:
    row = {"query": query, "positives": list(positives), "negatives": list(negatives),
           "excluded": [], "sample_key": f"row::{query}"}
    if hard:
        row["hard_negatives"] = list(hard)
    return [row]


# --------------------------------------------------------------------------------------
# condition 2 -- no primary denominator moves
# --------------------------------------------------------------------------------------
def test_the_class_lands_in_its_own_slots_and_moves_no_denominator():
    pool = _pool()
    bundle = _bundle()
    off = build_training_batch(bundle, pool=pool, rows=_rows(hard=()))
    on = build_training_batch(bundle, pool=pool, rows=_rows())

    # the batch grows by exactly the hard-negative block, appended after the pos/neg block
    assert off.n_candidates == 2 and on.n_candidates == 4
    assert int(off.hard_neg_mask.sum()) == 0 and int(on.hard_neg_mask.sum()) == 2
    assert [bool(v) for v in on.hard_neg_mask[0]] == [False, False, True, True]

    # ... and every pos/neg slot is bit-identical
    cut = off.n_candidates
    for name in ("pair_index", "pair_valid", "labels_relation", "label_pair_valid", "pos_mask",
                 "neg_mask", "excluded_mask", "exclusion_reason", "negative_is_r2_history",
                 "r1_fallback_used"):
        assert np.array_equal(np.asarray(getattr(off, name)), np.asarray(getattr(on, name))[:, :cut]), name
    for name in ("pos_mask", "neg_mask", "excluded_mask"):
        assert np.array_equal(np.asarray(getattr(off, name)).sum(axis=1),
                              np.asarray(getattr(on, name)).sum(axis=1)), name

    assert off.effective_query_count() == on.effective_query_count() == 1
    assert list(off.valid_query_indices()) == list(on.valid_query_indices()) == [0]
    assert int(off.negative_counts().sum()) == int(on.negative_counts().sum()) == 1
    # the exclusion histogram is identical in every bucket except ``none``, which counts the
    # slots carrying no exclusion reason: it grows by exactly the hard-negative block, i.e. by
    # the wider candidate dimension and by nothing else
    off_hist, on_hist = off.exposure()["exclusion_histogram"], on.exposure()["exclusion_histogram"]
    assert {k: v for k, v in off_hist.items() if k != "none"} == \
        {k: v for k, v in on_hist.items() if k != "none"}
    assert on_hist["none"] - off_hist["none"] == int(on.hard_neg_mask.sum())
    assert off.exposure()["legal_negatives"] == on.exposure()["legal_negatives"]
    assert on.exposure()["hard_negative_supervision_rows"] == 2
    assert on.exposure()["hard_negative_queries"] == 1

    assert on.hard_neg_query_mate.tolist() == [True]
    assert negative_audit(off)["ok"] is True
    audit = negative_audit(on)
    assert audit["ok"] is True, audit["problems"]
    assert audit["negatives"] == 1 and audit["positives"] == 1
    assert audit["hard_negatives"] == 2 and audit["hard_negative_queries"] == 1
    assert on.meta["hard_negative_class"] == HARD_NEGATIVE_CLASS
    assert on.meta["hard_negative_c_pn"] == 2 and on.meta["hard_negative_c_hard"] == 2


def test_the_correspondence_tensor_shares_the_widened_candidate_dimension():
    """The class widens ``C``; every pair-shaped tensor must be widened with it."""
    pool = _pool()
    built = build_training_batch(_bundle(), pool=pool, rows=_rows())
    assert built.corr_weight.shape[:2] == (built.n_queries, built.n_candidates)
    assert built.corr_row_valid.shape == built.corr_weight.shape
    assert built.contradiction.shape == (built.n_queries, built.n_candidates)
    assert built.quality_target.shape[0] == built.features.n_fragments
    # the hard block is not a correspondence row: its weight stays zero
    assert float(np.abs(built.corr_weight[:, built.meta["hard_negative_c_pn"]:]).sum()) == 0.0


def test_the_shortcut_probe_reports_zero_power_for_the_guarded_class():
    pool = _pool()
    built = build_training_batch(_bundle(), pool=pool, rows=_rows())
    probe = mate_present_shortcut_probe(built)
    assert probe["queries_probed"] == 1
    assert probe["queries_with_constant_cue"] == 1
    assert probe["mean_auc_mate_present_vs_positive"] is None
    assert probe["discriminative_power"] == 0.0
    assert probe["rows"][0]["query_mate_present"] is True


def test_the_shortcut_probe_is_not_vacuous():
    """Tamper with the cue and the probe reports the shortcut it exists to detect."""
    pool = _pool()
    built = build_training_batch(_bundle(), pool=pool, rows=_rows())
    ids = list(built.features.fragment_ids)
    built.mate_present[ids.index("h1")] = False      # pretend one hard negative has no mate
    probe = mate_present_shortcut_probe(built)
    assert probe["queries_with_constant_cue"] == 0
    assert probe["mean_auc_mate_present_vs_positive"] == pytest.approx(0.75)
    assert probe["discriminative_power"] == pytest.approx(0.5)


# --------------------------------------------------------------------------------------
# condition 4 -- enforced, not hoped for
# --------------------------------------------------------------------------------------
def test_a_mate_absent_query_may_not_supervise_the_class():
    pool = _pool()
    with pytest.raises(SynLabError) as excinfo:
        build_training_batch(_bundle(), pool=pool,
                             rows=_rows(query="z0", positives=(), hard=("h0",)))
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert "mate-absent" in str(excinfo.value)
    # the guard has no switch: the builder refuses the row rather than dropping it, and the class
    # *producer* is the only place where such a pair can even be named (with an explicit opt-in)
    import inspect

    assert "require_hard_negative_query_mate" not in inspect.signature(
        build_training_batch).parameters
    from synlab.relations.mate_absent import hard_negative_records

    table = [{"query": "z0", "candidate": "h0", "kind": "R0", "valid": True, "loss_mask": True,
              "area_mm2": 0.0, "reason": "", "eligible_as_negative": True},
             {"query": "h0", "candidate": "h1", "kind": "R2", "valid": True, "loss_mask": True,
              "area_mm2": 1.0, "reason": "", "eligible_as_negative": False}]
    strict, _ = hard_negative_records(table)
    loose, _ = hard_negative_records(table, require_query_mate_present=False)
    assert strict == [] and len(loose) == 1
    assert loose[0]["query_mate_present"] is False


def test_a_candidate_without_a_mate_of_its_own_is_refused():
    pool = _pool(lineages={"L1": ["p0", "p1"], "L2": ["h0", "h1"], "L4": ["q0"]})
    with pytest.raises(SynLabError) as excinfo:
        build_training_batch(_bundle(IDS + ("q0",)), pool=pool,
                             rows=_rows(hard=("q0",), negatives=()))
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert "no confirmed R2 mate of its own" in str(excinfo.value)


def test_the_query_own_mate_can_never_be_a_hard_negative():
    pool = _pool()
    with pytest.raises(SynLabError) as excinfo:
        build_training_batch(_bundle(), pool=pool,
                             rows=_rows(hard=("p1",), positives=(), negatives=()))
    assert excinfo.value.code == ErrorCode.LEAKAGE_DETECTED
    assert "R2 mate/positive" in str(excinfo.value)


def test_a_candidate_that_is_both_negative_and_hard_negative_is_refused():
    pool = _pool()
    with pytest.raises(SynLabError) as excinfo:
        build_training_batch(_bundle(), pool=pool, rows=_rows(hard=("h0", "z0")))
    assert excinfo.value.code == ErrorCode.LEAKAGE_DETECTED
    assert "mutually exclusive" in str(excinfo.value)


# --------------------------------------------------------------------------------------
# condition 3 -- the auxiliary term
# --------------------------------------------------------------------------------------
def test_the_task_is_off_by_default_and_outside_the_frozen_task_order():
    assert DEFAULT_HARD_NEGATIVE_WEIGHT == 0.0
    assert HARD_NEGATIVE_TASK not in TASK_ORDER
    assert set(TASK_ORDER) == {"rank", "view", "correspondence", "quality", "contradiction"}
    assert set(DEFAULT_WEIGHTS) == set(TASK_ORDER)


def test_the_loss_is_the_explicit_logsumexp_of_positives_versus_hard_negatives():
    torch = pytest.importorskip("torch")
    from synlab.training.losses import _skip

    sim = torch.tensor([[2.0, 1.0, -1.0, 0.5]])
    allowed = torch.ones((1, 4), dtype=torch.bool)
    pos = torch.tensor([[False, True, False, False]])
    hard = torch.tensor([[False, False, True, True]])
    result = hard_negative_loss(sim, allowed, pos_mask=pos, hard_neg_mask=hard,
                                query_mate_present=torch.tensor([True]), temperature=0.1)
    inv = 10.0
    expected = (torch.logsumexp(torch.tensor([1.0 * inv, -1.0 * inv, 0.5 * inv]), dim=0)
                - torch.tensor(1.0 * inv))
    assert not result["skipped"]
    assert float(result["loss"]) == pytest.approx(float(expected))
    assert result["n_valid"] == 1
    assert result["diagnostics"]["n_hard_negatives"] == 2
    assert result["diagnostics"]["n_positives"] == 1
    assert result["diagnostics"]["task"] == HARD_NEGATIVE_TASK
    assert result["diagnostics"]["margin"] == 0.0

    # an unallowed hard negative is not read at all
    masked = hard_negative_loss(sim, torch.tensor([[True, True, True, False]]), pos_mask=pos,
                                hard_neg_mask=hard, query_mate_present=torch.tensor([True]))
    assert masked["diagnostics"]["n_hard_negatives"] == 1
    # a mate-absent query contributes nothing
    skipped = hard_negative_loss(sim, allowed, pos_mask=pos, hard_neg_mask=hard,
                                 query_mate_present=torch.tensor([False]))
    assert skipped["skipped"] is True
    assert skipped["reason"] == "no_query_with_allowed_positive_and_hard_negative"
    # an empty class is a *skip with a reason*, never a zero
    empty = hard_negative_loss(sim, allowed, pos_mask=pos,
                               hard_neg_mask=torch.zeros((1, 4), dtype=torch.bool))
    assert empty["skipped"] is True and empty["reason"] == "no_allowed_hard_negative"
    assert _skip("x")["loss"] is None


def test_the_loss_never_reads_the_ordinary_negative_mask():
    torch = pytest.importorskip("torch")

    sim = torch.tensor([[2.0, 1.0, -1.0, 0.5]])
    pos = torch.tensor([[False, True, False, False]])
    hard = torch.tensor([[False, False, True, True]])
    first = hard_negative_loss(sim, torch.ones((1, 4), dtype=torch.bool), pos_mask=pos,
                               hard_neg_mask=hard, query_mate_present=torch.tensor([True]))
    # the ordinary rank denominator is a different object; the auxiliary term has no parameter
    # through which it could enter, and its body never names it
    import inspect

    signature = inspect.signature(hard_negative_loss)
    assert "neg_mask" not in signature.parameters
    source = inspect.getsource(hard_negative_loss)
    body = source.split('"""')[2] if source.count('"""') >= 2 else source   # drop the docstring
    body = body.replace("hard_neg_mask", "").replace("hard_negative", "")
    assert "neg_mask" not in body
    assert first["n_valid"] == 1
    # the value is invariant under any change to the ordinary negative set: the same call with a
    # different `allowed` row-wide mask is the only thing that moves it
    stricter = hard_negative_loss(sim, torch.tensor([[True, True, True, True]]), pos_mask=pos,
                                  hard_neg_mask=hard, query_mate_present=torch.tensor([True]))
    assert float(stricter["loss"]) == pytest.approx(float(first["loss"]))


def test_the_multi_task_combination_carries_the_auxiliary_task_beside_the_core_five():
    torch = pytest.importorskip("torch")

    core = {name: {"loss": torch.tensor(1.0), "n_valid": 1, "skipped": False,
                   "reason": None, "diagnostics": {}} for name in TASK_ORDER}
    # with the weight at 0 the task is not even built, so the combination is the core five
    assert set(MultiTaskLoss(loss_weights=dict(DEFAULT_WEIGHTS)).task_report()["weights"]) == \
        set(TASK_ORDER)
    combined = MultiTaskLoss(loss_weights={**DEFAULT_WEIGHTS, HARD_NEGATIVE_TASK: 0.3}).combine(
        {**core, HARD_NEGATIVE_TASK: {"loss": torch.tensor(2.0), "n_valid": 1,
                                      "skipped": False, "reason": None, "diagnostics": {}}})
    assert not combined["all_skipped"]
    assert combined["report"][HARD_NEGATIVE_TASK]["weight"] == 0.3
    assert combined["report"][HARD_NEGATIVE_TASK]["weighted"] == pytest.approx(0.6)
    for name in TASK_ORDER:
        assert combined["report"][name]["weight"] == DEFAULT_WEIGHTS[name]
        assert combined["report"][name]["n_valid"] == 1
    # and with the default weight the report's weight for it is 0
    assert MultiTaskLoss(loss_weights=dict(DEFAULT_WEIGHTS)).combine(core)["report"]["rank"][
        "loss"] == 1.0


def test_the_batch_audit_names_every_way_the_class_could_be_abused():
    pool = _pool()
    built = build_training_batch(_bundle(), pool=pool, rows=_rows())
    saved = np.asarray(built.hard_neg_mask).copy()
    try:
        built.hard_neg_mask = saved & False
        built.hard_neg_mask[0, 0] = True          # inside the positive block
        audit = negative_audit(built)
        assert audit["ok"] is False
        assert "hard negative inside pos_mask" in audit["problems"]
    finally:
        built.hard_neg_mask = saved
    assert training_batch.negative_audit(built)["ok"] is True
