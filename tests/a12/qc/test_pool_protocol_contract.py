"""The relation-pool protocol contract: four parallel implementations, one battery.

Why this file exists (the defect it prevents)
--------------------------------------------
``docs/a12/relation_negatives.md`` §1 defect (B): ``qc.loader_probe.ExportedRelationPool``
answered ``neighbours()`` with the confirmed **R1/R0** set while ``synlab.training.batch`` reads
``neighbours(q)`` as the **historical R2 mate set**.  Every legal negative then looked like a
mate, the guard refused all of them (``every_legal_negative_is_a_pool_neighbour = true`` for
55/55 queries) and the ``rank`` task **never started** -- while every component reported success
on its own.  ``docs/a12/engineering_policy.md`` §3 row 5 records the structural cause: four
parallel implementations of one protocol, kept in step by convention.

These tests replace the convention with a **contract** (``synlab.qc.pool_contract``,
``relations.pool_protocol.v1``): one row set in, every implementation instantiated from it, one
assertion battery, plus a reproducible failure injection proving the battery can fail.

Nothing here is allowed to be a rubber stamp: expected values come from the row set
(``reference_mates``), never from an implementation under test, and the injection tests assert
that a specific *named* clause fires -- a battery that cannot name what broke is not a contract.
"""

from __future__ import annotations

import pytest

from synlab.qc.pool_contract import (
    ASSERTION_NAMES,
    FAILURE_INJECTIONS,
    IMPLEMENTATIONS,
    POOL_PROTOCOL_VERSION,
    PoolContractError,
    ProtocolContext,
    assert_pool_contract,
    build_implementations,
    canonical_context,
    check_agreement,
    check_pool,
    classify_divergence,
    exported_pool,
    gallery_pool,
    pool_index,
    run_failure_injections,
    training_pool_view,
)
from synlab.relations.legal_negative import MISSING

#: The withdrawn-row fixture's universe: two mate pairs, one withdrawn ``R1`` chain and the legal
#: negative supply they must not be confused with.  Small enough to reason about, complete over its
#: universe so the two reader families can be compared on the same rows.
WITHDRAWN_FRAGMENTS = ("a0-m", "a0-p", "b0-m", "b0-p", "n0", "n1", "x0", "d0")


def eligibility_context() -> ProtocolContext:
    """A context that carries rows the truth layer **withdrew**, in both flag spellings.

    ``docs/a12/relation_negatives.md`` §9.1.1 recorded the real shape: an ``R1`` row between two
    fragments of the *same* fracture event that shares no fracture surface is withdrawn with
    ``valid=False`` / ``loss_mask=False`` / ``reason="no_direct_fracture_surface"`` -- yet three of
    the four readers supplied it as an ordinary negative.  The canonical context has no such row,
    so the eligibility clause needs its own fixture or it would pass vacuously:

    * ``x0-a0-m`` (``R1``): ``valid=False`` **and** ``loss_mask=False`` -- the reported case;
    * ``x0-b0-m`` (``R0``): ``valid=True``, ``loss_mask=False`` -- withdrawn by the mask alone;
    * ``x0-d0`` (``R0``): fully eligible (``valid`` and ``loss_mask`` both true);
    * ``x0-n0`` (``R2``): a mate pair, so the withdrawn candidates are not the only exclusion path;
    * every unnamed pair: an explicit ``R0`` row with both flags true, which keeps the context
      complete so "reader X offers more" cannot be mistaken for "reader X ignores the flags".
    """
    mates = [("a0-m", "a0-p"), ("b0-m", "b0-p"), ("x0", "n0")]
    rows: list[dict] = []
    for a, b in mates:
        rows.append({"query": a, "candidate": b, "kind": "R2", "valid": True, "loss_mask": True,
                     "area_mm2": 12.5, "eligible_as_negative": False,
                     "reason": "shared_cut_surface", "pool_id": "eligibility", "split": "dev"})
    withdrawn = [
        ("x0", "a0-m", "R1", False, False, "no_direct_fracture_surface (same event, mutually "
                                           "exclusive)"),
        ("x0", "b0-m", "R0", True, False, "candidate_mate_present_not_ordinary"),
    ]
    for a, b, kind, valid, loss_mask, reason in withdrawn:
        rows.append({"query": a, "candidate": b, "kind": kind, "valid": valid,
                     "loss_mask": loss_mask, "area_mm2": 0.0,
                     "eligible_as_negative": False, "reason": reason,
                     "pool_id": "eligibility", "split": "dev"})
    named = {tuple(sorted(pair)) for pair in mates}
    named |= {tuple(sorted((a, b))) for a, b, *_ in withdrawn}
    for index, a in enumerate(WITHDRAWN_FRAGMENTS):
        for b in WITHDRAWN_FRAGMENTS[index + 1:]:
            if tuple(sorted((a, b))) in named:
                continue
            rows.append({"query": a, "candidate": b, "kind": "R0", "valid": True,
                         "loss_mask": True, "area_mm2": 0.0, "eligible_as_negative": True,
                         "reason": "", "pool_id": "eligibility", "split": "dev"})
    return ProtocolContext(name="eligibility", lineup=WITHDRAWN_FRAGMENTS, rows=tuple(rows),
                           source="tests/a12/qc/test_pool_protocol_contract.eligibility_context()",
                           notes={"role": "the withdrawn-row fixture of the eligibility clause",
                                  "withdrawn_rows": [["x0", "a0-m"], ["x0", "b0-m"]],
                                  "complete_over_the_universe": True})


@pytest.fixture(scope="module")
def ctx():
    return canonical_context()


@pytest.fixture(scope="module")
def pools(ctx):
    return build_implementations(ctx)


def test_the_canonical_context_covers_every_protocol_clause(ctx) -> None:
    """The fixture must be able to distinguish the clauses, or the suite proves nothing."""
    mates = ctx.mates()
    assert len(ctx.universe()) == 15
    assert ctx.duplicate_pairs() == []
    # mates exist, mate-absent fragments exist, and every kind of the vocabulary is present
    assert mates["a0-m"] == {"a0-p"}
    assert not mates.get("n0")
    kinds = {str(row["kind"]) for row in ctx.rows}
    assert kinds == {"R0", "R1", "R2", "TINY_CONTACT", "UNKNOWN"}
    # the fixture is complete over its universe: every unnamed pair would be a table defect
    named = sum(1 for a in ctx.universe() for b in ctx.universe() if a < b)
    assert len({(min(r["query"], r["candidate"]), max(r["query"], r["candidate"]))
                for r in ctx.rows}) == named


def test_every_registered_implementation_is_instantiated_from_the_same_context(pools) -> None:
    assert len(pools) >= 5                     # four implementations, PoolIndex over two carriers
    seen = set()
    for label, pool in pools.items():
        seen.add(f"{type(pool).__module__}.{type(pool).__name__}")
    assert "synlab.qc.loader_probe.ExportedRelationPool" in seen
    assert "synlab.training.smoke.TrainingPoolView" in seen
    assert "synlab.training.sampler.PoolIndex" in seen
    assert "synlab.relations.gallery.RelationPool" in seen
    for dotted in IMPLEMENTATIONS:
        assert dotted.split(".")[-1] in {name.split(".")[-1] for name in seen}, dotted


@pytest.mark.parametrize("label", [
    "qc.loader_probe.ExportedRelationPool",
    "training.smoke.TrainingPoolView",
    "training.sampler.PoolIndex[exported]",
    "training.sampler.PoolIndex[gallery]",
    "relations.gallery.RelationPool",
])
def test_the_battery_passes_for_every_implementation(pools, ctx, label) -> None:
    report = check_pool(pools[label], ctx, label=label)
    assert report["protocol_version"] == POOL_PROTOCOL_VERSION
    assert [a["name"] for a in report["assertions"]] == list(ASSERTION_NAMES)
    assert report["ok"], report["failures"]


def test_the_four_implementations_agree_on_the_canonical_context(pools, ctx) -> None:
    agreement = check_agreement(pools, ctx)
    assert agreement["ok"], agreement["disagreements"]
    divergence = classify_divergence(pools, ctx)
    assert divergence["conflicts"] == 0, divergence["conflict_examples"]
    assert divergence["conservative_gaps"] == 0
    assert divergence["eligibility_findings"] == 0


def test_assert_pool_contract_names_the_failing_clause(ctx) -> None:
    pool = gallery_pool(ctx)
    assert assert_pool_contract(pool, ctx, label="gallery")["ok"]
    broken = FAILURE_INJECTIONS["neighbours_return_the_negative_set"](pool)
    with pytest.raises(PoolContractError) as info:
        assert_pool_contract(broken, ctx, label="injected")
    assert "neighbours_are_mates" in str(info.value)
    assert info.value.label == "injected"
    assert info.value.failures


def test_failure_injection_is_caught_for_every_clause(ctx) -> None:
    """Each single-clause breakage must be caught by its *named* assertion."""
    report = run_failure_injections(ctx)
    assert report["base"]["ok"] is True
    assert report["total"] == 7
    assert report["caught"] == report["total"], report["injections"]
    for item in report["injections"]:
        assert item["caught"], item
        assert item["expected_assertion"] in item["failed_assertions"], item
    assert report["ok"] is True


def test_the_eligibility_defect_itself_is_caught() -> None:
    """The 9.1.1 defect, injected: eligibility recomputed from the **kind** again.

    ``eligibility_follows_extracted_flags`` is the clause the fix landed for, so it needs the same
    reproducible proof the other clauses have: the injection restores both mechanisms of the
    divergence (``confirmed()`` answering ``relation() in {R0,R1,R2}`` and ``legal_pool()``
    offering every ``R0``/``R1`` the row set withdrew) and the clause must name itself -- with the
    offending pair, the kind and both flags.
    """
    ctx = eligibility_context()
    withdrawn = [(str(row["query"]), str(row["candidate"])) for row in ctx.rows
                 if str(row["kind"]) in ("R0", "R1")
                 and not (bool(row.get("valid", False)) and bool(row.get("loss_mask", False)))]
    assert withdrawn, "the fixture must carry a withdrawn row, or the clause proves nothing"
    good = gallery_pool(ctx)
    assert check_pool(good, ctx, label="gallery")["ok"], "the fixed pool must satisfy the battery"
    broken = FAILURE_INJECTIONS["eligibility_recomputed_from_the_kind"](good)
    report = check_pool(broken, ctx, label="injected::eligibility")
    assert "eligibility_follows_extracted_flags" in report["failed_assertions"], report["failures"]
    query, candidate = sorted(withdrawn)[0]
    assert any(f"({query}, {candidate})" in item for item in report["failures"]), \
        report["failures"]
    # the *un*injected pool refuses the same row, with a machine-readable reason
    resolution = good.negative_eligibility(query, candidate)
    assert resolution.eligible is False and resolution.reason
    assert candidate not in {str(x) for x in good.legal_pool(query)}
    with pytest.raises(Exception):
        good.assert_legal_negative(query, candidate)


def test_the_fixture_is_pinned_to_the_reported_divergence() -> None:
    """The fixture reproduces the shape §9.1.1 recorded: an ``R1`` row withdrawn by ``valid``.

    Without this the eligibility clause could pass vacuously (a context with no withdrawn row
    makes it trivially true), so the fixture itself is asserted, not assumed.
    """
    ctx = eligibility_context()
    rows = {(str(r["query"]), str(r["candidate"])): r for r in ctx.rows}
    assert rows[("x0", "a0-m")]["kind"] == "R1"
    assert rows[("x0", "a0-m")]["valid"] is False
    assert rows[("x0", "a0-m")]["loss_mask"] is False
    assert rows[("x0", "a0-m")]["eligible_as_negative"] is False
    assert "no_direct_fracture_surface" in str(rows[("x0", "a0-m")]["reason"])
    assert rows[("x0", "b0-m")]["loss_mask"] is False
    # and it is complete over its universe, so the readers are compared on real rows
    named = sum(1 for a in ctx.universe() for b in ctx.universe() if a < b)
    assert len({(min(r["query"], r["candidate"]), max(r["query"], r["candidate"]))
                for r in ctx.rows}) == named


@pytest.mark.parametrize("label", [
    "qc.loader_probe.ExportedRelationPool",
    "training.smoke.TrainingPoolView",
    "training.sampler.PoolIndex[exported]",
    "training.sampler.PoolIndex[gallery]",
    "relations.gallery.RelationPool",
])
def test_every_implementation_refuses_a_withdrawn_row(label) -> None:
    """Four implementations x one context carrying ``valid=False`` / ``loss_mask=False`` rows."""
    ctx = eligibility_context()
    pool = build_implementations(ctx)[label]
    report = check_pool(pool, ctx, label=label)
    assert report["ok"], report["failures"]
    for row in ctx.rows:
        if str(row["kind"]) not in ("R0", "R1"):
            continue
        if bool(row.get("valid", False)) and bool(row.get("loss_mask", False)):
            continue
        query, candidate = str(row["query"]), str(row["candidate"])
        assert candidate not in {str(x) for x in pool.legal_pool(query)}, (label, query, candidate)
        assert bool(pool.confirmed(query, candidate)) is False, (label, query, candidate)
        with pytest.raises(Exception):
            pool.assert_legal_negative(query, candidate)


def test_an_input_without_eligibility_evidence_is_refused_not_guessed() -> None:
    """Conservative refusal: an input that cannot confirm the gate supplies nothing.

    The defect was *"derive eligibility from the kind"*.  A carrier that exposes neither
    ``negative_eligibility()`` nor its rows cannot confirm anything, so ``PoolIndex`` must stop
    supplying negatives -- and say why -- instead of falling back to the kind (which is exactly
    what ``relation() in {R0,R1,R2}`` used to do).
    """
    from synlab.training.sampler import PoolIndex

    ctx = eligibility_context()

    class KindOnlyCarrier:
        """The defect's shape: a carrier that can only answer ``relation()``."""

        pool_id = "kind-only"

        def __init__(self) -> None:
            self.lineup = [str(fid) for fid in ctx.universe()]
            self._kinds = {(str(r["query"]), str(r["candidate"])): str(r["kind"]) for r in ctx.rows}

        def relation(self, a: str, b: str) -> str:
            return self._kinds.get((str(a), str(b)), "UNKNOWN")

        def neighbours(self, fragment_id: str) -> set[str]:
            return set()

    carrier = KindOnlyCarrier()
    index = PoolIndex(carrier)
    offered = {fid: index.legal_pool(fid) for fid in [str(f) for f in ctx.universe()]}
    assert all(not values for values in offered.values()), offered
    assert index.confirmed("x0", "a0-m") is False
    reason = index.eligibility_reason("x0", "a0-m")
    assert reason == "carrier_exposes_no_eligibility_evidence", reason
    with pytest.raises(Exception, match="carrier_exposes_no_eligibility_evidence"):
        index.assert_legal_negative("x0", "a0-m")
    # a carrier that *does* expose its rows is resolved from those rows, not from the kind
    class RowsCarrier(KindOnlyCarrier):
        def __init__(self) -> None:
            super().__init__()
            self.rows = {}
            for row in ctx.rows:
                flags = {"kind": str(row["kind"]), "valid": row.get("valid", MISSING),
                         "loss_mask": row.get("loss_mask", MISSING),
                         "eligible_as_negative": row.get("eligible_as_negative", MISSING),
                         "reason": str(row.get("reason", "") or "")}
                self.rows.setdefault((str(row["query"]), str(row["candidate"])), flags)
                self.rows.setdefault((str(row["candidate"]), str(row["query"])), flags)

    rows_index = PoolIndex(RowsCarrier())
    assert rows_index.confirmed("x0", "a0-m") is False
    assert rows_index.eligibility_reason("x0", "a0-m") in ("row_valid_false", "loss_mask_false")
    assert rows_index.confirmed("n0", "n1") is True


def test_the_rank_defect_itself_is_caught_on_every_carrier(ctx) -> None:
    """Defect (B) reproduced verbatim: ``neighbours()`` answers with the legal negative set.

    The injection is applied to each carrier family, because the clause has to hold for the
    gallery pool *and* for the exported reader -- either one drifting is enough to stop ``rank``.
    """
    for inner in (exported_pool(ctx), gallery_pool(ctx), training_pool_view(ctx)):
        broken = FAILURE_INJECTIONS["neighbours_return_the_negative_set"](inner)
        report = check_pool(broken, ctx, label="injected")
        assert "neighbours_are_mates" in report["failed_assertions"], report["failures"]
        # the failure names the fragment and both readings, so it is actionable
        assert any("neighbours(" in item for item in report["failures"]), report["failures"]


def test_mates_is_the_measured_r2_set_for_every_implementation(pools, ctx) -> None:
    expected = ctx.mates()
    for label, pool in pools.items():
        for fid in ctx.universe():
            assert {str(x) for x in pool.mates(fid)} == expected.get(fid, set()), (label, fid)
            assert {str(x) for x in pool.neighbours(fid)} == expected.get(fid, set()), (label, fid)


def test_legal_negatives_are_confirmed_r0_r1_and_never_a_mate(pools, ctx) -> None:
    for label, pool in pools.items():
        for fid in ctx.universe():
            legal = {str(x) for x in pool.legal_pool(fid)}
            assert legal == {str(x) for x in pool.legal_negatives(fid)}, (label, fid)
            for candidate in legal:
                kind = str(pool.relation(fid, candidate))
                assert kind in ("R0", "R1"), (label, fid, candidate, kind)
                assert bool(pool.confirmed(fid, candidate)), (label, fid, candidate)
                assert candidate not in {str(x) for x in pool.mates(fid)}, (label, fid, candidate)
                assert candidate != fid
                pool.assert_legal_negative(fid, candidate)      # the guard accepts it


def test_history_exclusions_contain_the_mates_and_forbid_nothing_legal(pools, ctx) -> None:
    for label, pool in pools.items():
        for fid in ctx.universe():
            history = {str(x) for x in pool.history_exclusions(fid)}
            assert {str(x) for x in pool.mates(fid)} <= history, (label, fid)
            assert not (history & {str(x) for x in pool.legal_pool(fid)}), (label, fid)


def test_the_guard_refuses_what_the_protocol_forbids(ctx) -> None:
    """``assert_legal_negative`` must refuse the query, its mates and every R2/TINY/UNKNOWN."""
    for pool in (exported_pool(ctx), gallery_pool(ctx), pool_index(ctx, carrier="exported")):
        with pytest.raises(Exception):
            pool.assert_legal_negative("a0-m", "a0-m")          # the query itself
        with pytest.raises(Exception):
            pool.assert_legal_negative("a0-m", "a0-p")          # its historical R2 mate
        with pytest.raises(Exception):
            pool.assert_legal_negative("a0-m", "t0")            # TINY_CONTACT
        with pytest.raises(Exception):
            pool.assert_legal_negative("u0", "u0")              # still the query itself


def test_candidate_ids_never_contain_the_query(pools, ctx) -> None:
    for label, pool in pools.items():
        for fid in ctx.universe():
            assert str(fid) not in {str(x) for x in pool.candidate_ids(fid)}, (label, fid)


def test_a_pool_without_a_universe_is_refused(ctx) -> None:
    """The interface clause is behavioural: a pool that names no candidate fails it.

    This is what silently happens when a reader is handed to ``training.sampler.PoolIndex``
    without a ``lineup``/``fragment_ids``: the sampler sees an empty lineage and produces no
    candidate at all.  The clause has to fail loudly instead.
    """

    class NoUniverse:
        def relation(self, a, b):  # noqa: D102
            return "R0"

        def mates(self, fragment_id):  # noqa: D102
            return set()

        def neighbours(self, fragment_id):  # noqa: D102
            return set()

        def legal_pool(self, fragment_id, *, relation=None):  # noqa: D102
            return []

        def legal_negatives(self, fragment_id):  # noqa: D102
            return set()

        def confirmed(self, a, b):  # noqa: D102
            return True

        def history_exclusions(self, fragment_id):  # noqa: D102
            return set()

        def candidate_ids(self, fragment_id):  # noqa: D102
            return []

        def assert_legal_negative(self, query_id, candidate_id):  # noqa: D102
            return None

        def negative_eligibility(self, a, b):  # noqa: D102
            from synlab.relations.legal_negative import NegativeEligibility
            return NegativeEligibility(True, "eligible")

    report = check_pool(NoUniverse(), ctx, label="no-universe")
    assert "interface_present" in report["failed_assertions"], report["failures"]
    assert any("candidate universe" in item for item in report["failures"])


def test_the_adapter_without_a_carrier_lineup_is_refused_too(ctx) -> None:
    """``PoolIndex`` over a carrier that names no fragment must fail the same clause.

    This is the misconfiguration the clause was written for: a table-less carrier produces an
    empty ``PoolIndex.lineage``, so the sampler would draw nothing at all.
    """
    from synlab.training.sampler import PoolIndex

    carrier = exported_pool(ctx)
    carrier.lineup = []
    carrier._kinds = {}
    report = check_pool(PoolIndex(carrier), ctx, label="index-over-empty")
    assert report["failed_assertions"], report
    assert "interface_present" in report["failed_assertions"], report["failures"]
