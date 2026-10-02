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
    assert report["total"] == 6
    assert report["caught"] == report["total"], report["injections"]
    for item in report["injections"]:
        assert item["caught"], item
        assert item["expected_assertion"] in item["failed_assertions"], item
    assert report["ok"] is True


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
