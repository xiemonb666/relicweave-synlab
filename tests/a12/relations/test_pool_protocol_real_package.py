"""The pool protocol against a **real** exported package and the **real** asset store.

``tests/a12/qc/test_pool_protocol_contract.py`` proves the battery can distinguish the clauses on
a canonical fixture.  This file runs the same battery on the real inputs the pipeline ships:

* the four implementations instantiated from ``research/relations.parquet`` of the exported
  package (1721 rows, 71 fragments), and
* a real ``relations.gallery.RelationPool`` whose sparse index is loaded from the real asset
  store over exactly those fragments (``collect_fragments`` + ``load_relations_into``).

Two facts are pinned here, both measured, neither averaged:

1. **the safety half holds**: every implementation satisfies all 14 clauses, and no reader
   disagrees with another about the *kind* of a pair a measured row names, or about a mate set;
2. **the 9.1.1 eligibility divergence is reconciled and stays visible**: the 24 ``R1`` rows of
   this scope carry ``valid=False`` / ``loss_mask=False`` / ``eligible_as_negative=False``
   ("no_direct_fracture_surface") and are now refused by **every** reader -- the same rows that
   ``relations.gallery.RelationPool``, ``PoolIndex[gallery]`` and ``PoolIndex[exported]`` used to
   supply.  ``test_the_eligibility_divergence_is_reconciled_and_pinned`` fails if that regresses,
   *and* fails if the measurement stops being able to see the divergence at all (it re-runs the
   recorded pre-fix behaviour through the same function and requires the exact 48/24/26 counts
   back).  The cost of the tightening is measured in
   ``data/a12_reports/negfix_eligibility.json``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _fixtures import REPO_ROOT
from synlab.qc.pool_contract import (
    FAILURE_INJECTIONS,
    POOL_PROTOCOL_VERSION,
    check_agreement,
    check_pool,
    classify_divergence,
    eligibility_finding,
    exported_pool,
    gallery_pool,
    pool_index,
    run_failure_injections,
    training_pool_view,
)

PACKAGE = REPO_ROOT / "data" / "a12_exports" / "negfix" / "next_experiment" / "training_package"
STORE = REPO_ROOT / "data" / "a12_trainable" / "store"

pytestmark = pytest.mark.skipif(
    not (PACKAGE / "export_manifest.json").exists(),
    reason="real exported training package not present")

LABELS = (
    "qc.loader_probe.ExportedRelationPool",
    "training.smoke.TrainingPoolView",
    "training.sampler.PoolIndex[exported]",
    "training.sampler.PoolIndex[gallery]",
    "relations.gallery.RelationPool",
)


@pytest.fixture(scope="module")
def real():
    from synlab.qc.pool_contract import ProtocolContext
    from synlab.storage.export import TrainingPackage

    package = TrainingPackage(PACKAGE)
    rows = [dict(row) for row in package.relations()]
    endpoints = sorted({str(r.get("query", "")) for r in rows}
                       | {str(r.get("candidate", "")) for r in rows})
    endpoints = [fid for fid in endpoints if fid]
    ctx = ProtocolContext(name="real::test", lineup=tuple(endpoints), rows=tuple(rows),
                          source=str(PACKAGE))
    fragments: dict = {}
    if STORE.exists():
        from synlab.relations.gallery import collect_fragments
        from synlab.storage.store import AssetStore

        records = collect_fragments(AssetStore(STORE), release=None)
        fragments = {fid: rec for fid, rec in records.items() if fid in set(endpoints)}
    pools = {
        "qc.loader_probe.ExportedRelationPool": exported_pool(ctx),
        "training.smoke.TrainingPoolView": training_pool_view(ctx),
        "training.sampler.PoolIndex[exported]": pool_index(ctx, carrier="exported"),
        "training.sampler.PoolIndex[gallery]": pool_index(ctx, carrier="gallery"),
        "relations.gallery.RelationPool": gallery_pool(ctx, fragments=fragments),
    }
    return {"ctx": ctx, "pools": pools, "fragments": fragments, "rows": rows}


def test_the_real_context_is_the_exported_table(real) -> None:
    ctx = real["ctx"]
    assert len(ctx.rows) == 1721
    assert len(ctx.universe()) == 71
    assert ctx.duplicate_pairs() == []      # one row per unordered pair: symmetric by construction
    kinds = {}
    for row in ctx.rows:
        kinds[str(row["kind"])] = kinds.get(str(row["kind"]), 0) + 1
    assert kinds == {"R0": 1560, "UNKNOWN": 106, "R2": 28, "R1": 24, "TINY_CONTACT": 3}
    assert len(ctx.mates()) == 56           # fragments with a confirmed R2 mate in this scope


@pytest.mark.parametrize("label", LABELS)
def test_every_implementation_satisfies_the_battery_on_real_rows(real, label) -> None:
    report = check_pool(real["pools"][label], real["ctx"], label=label)
    assert report["protocol_version"] == POOL_PROTOCOL_VERSION
    assert report["ok"], report["failures"]


def test_mate_sets_agree_across_every_reader_on_real_rows(real) -> None:
    agreement = check_agreement(real["pools"], real["ctx"])
    mate_disagreements = [item for item in agreement["disagreements"]
                          if item["reading"] in ("mates", "neighbours")]
    assert mate_disagreements == []
    divergence = classify_divergence(real["pools"], real["ctx"])
    assert divergence["conflicts"] == 0, divergence["conflict_examples"]


def test_the_gallery_reading_is_a_superset_of_the_exported_one(real) -> None:
    """The exported table is not complete over its universe: that gap is measured, not hidden."""
    divergence = classify_divergence(real["pools"], real["ctx"])
    assert divergence["conservative_gaps"] > 0
    assert "implicit R0" in divergence["note"]
    pools, ctx = real["pools"], real["ctx"]
    exported = pools["qc.loader_probe.ExportedRelationPool"]
    gallery = pools["relations.gallery.RelationPool"]
    offered_export = sum(len(exported.legal_pool(fid)) for fid in ctx.universe())
    offered_gallery = sum(len(gallery.legal_pool(fid)) for fid in ctx.universe())
    assert 0 < offered_export < offered_gallery


def test_the_eligibility_divergence_is_reconciled_and_pinned(real) -> None:
    """**The 9.1.1 divergence, fixed and still pinned** (``docs/a12/relation_negatives.md`` §9.1.2).

    24 ``R1`` rows (48 directed pairs, 26 queries) of this scope are marked ``valid=False`` /
    ``loss_mask=False`` / ``eligible_as_negative=False`` with the reason
    ``no_direct_fracture_surface``.  They used to be offered as ordinary negatives by three of the
    four readers; now every reader refuses them, and this test fails the moment that regresses.

    Three things are asserted, none of them read off the implementation under test:

    1. **the data was not touched to make the fix work**: the 24 withdrawn rows are still in the
       exported table with ``valid=False``, ``loss_mask=False`` and
       ``eligible_as_negative=False`` -- the same population §9.1.1 measured;
    2. **every reader refuses them** -- ``eligibility_finding``'s ``directed_pairs`` is 0 and its
       ``consumers_refusing_withdrawn_rows`` counts all 48 directions for all five instances, so
       "no divergence" is not the same thing as "no such row";
    3. **the finding can still see the divergence**: feeding it the pre-fix readers (the recorded
       failure injection) reproduces exactly 48 directed pairs / 24 unordered / 26 queries, so the
       measurement is not vacuous.
    """
    ctx, pools = real["ctx"], real["pools"]
    rows = {(str(r.get("query")), str(r.get("candidate"))): r for r in ctx.rows}
    withdrawn = [(a, b) for (a, b), row in rows.items()
                 if str(row.get("kind")) == "R1" and row.get("valid") is False]
    assert len(withdrawn) == 24
    assert all(rows[key]["loss_mask"] is False for key in withdrawn)
    assert all(rows[key]["eligible_as_negative"] is False for key in withdrawn)
    assert all("no_direct_fracture_surface" in str(rows[key].get("reason", ""))
               for key in withdrawn)

    finding = eligibility_finding(pools, ctx)
    assert finding["directed_pairs"] == 0, finding["examples"]
    assert finding["withdrawn_rows_directed"] == 48
    assert finding["withdrawn_rows_unordered"] == 24
    assert finding["withdrawn_rows_queries"] == 26
    assert finding["flag_mismatches"] == 0
    assert finding["frozen_gate"] == \
        "eligible_as_negative == (kind in {R0,R1} and valid and loss_mask)"
    assert "FIXED" in finding["mechanism"]
    for label, refused in finding["consumers_refusing_withdrawn_rows"].items():
        assert refused == 48, (label, refused)
    for query, candidate in withdrawn:
        for label, pool in pools.items():
            assert candidate not in {str(x) for x in pool.legal_pool(query)}, (label, query)
            assert bool(pool.confirmed(query, candidate)) is False, (label, query)
            resolution = pool.negative_eligibility(query, candidate)
            assert resolution.eligible is False and resolution.reason, (label, query)
            with pytest.raises(Exception):
                pool.assert_legal_negative(query, candidate)

    # the measurement still sees a divergence when one exists: the pre-fix readers, injected
    injected = {label: FAILURE_INJECTIONS["eligibility_recomputed_from_the_kind"](pool)
                for label, pool in pools.items()}
    regressed = eligibility_finding(injected, ctx)
    assert regressed["directed_pairs"] == 48
    assert regressed["unordered_pairs"] == 24
    assert regressed["kinds"] == ["R1"]
    assert regressed["all_rows_valid_false"] is True
    assert regressed["all_rows_loss_mask_false"] is True
    # every injected reader is back to supplying the withdrawn rows (all five: the injection is
    # "eligibility follows the kind", applied to each implementation in turn)
    assert regressed["offered_by_counts"] == {label: 48 for label in LABELS}
    example = regressed["examples"][0]
    assert example["measured_kind"] == "R1"
    assert example["row_eligible_as_negative"] is False


def test_the_withdrawn_rows_are_the_documented_mate_present_class(real) -> None:
    """Why the refusal is correct and not merely conservative: the candidates are give-aways.

    Every withdrawn direction has a **candidate whose own historical R2 mate is present in this
    scope** -- the class ``docs/a12/relation_negatives.md`` records as
    ``CANDIDATE_MATE_PRESENT_NOT_ORDINARY`` and the ruling withdrew from the ordinary-negative
    supply.  If these candidates were supplied as negatives, "the candidate has a mate" would
    correlate with the negative label inside the ``rank`` task.
    """
    ctx = real["ctx"]
    rows = {(str(r.get("query")), str(r.get("candidate"))): r for r in ctx.rows}
    mates = ctx.mates()
    withdrawn = [(a, b) for (a, b), row in rows.items()
                 if str(row.get("kind")) == "R1" and row.get("valid") is False]
    assert withdrawn
    mate_present = [key for key in withdrawn if mates.get(key[1])]
    assert mate_present == withdrawn, [key for key in withdrawn if key not in mate_present]


def test_the_failure_injection_is_caught_on_the_real_gallery_pool(real) -> None:
    report = run_failure_injections(real["ctx"], base=real["pools"]["relations.gallery.RelationPool"])
    assert report["ok"] is True
    assert report["caught"] == report["total"] == 7
    assert any(item["expected_assertion"] == "eligibility_follows_extracted_flags"
               for item in report["injections"])


def test_the_store_side_index_is_the_same_relation_reading(real) -> None:
    """The gallery's sparse index must be loaded from the real store, not synthesised here."""
    if not real["fragments"]:
        pytest.skip("real asset store not present")
    assert len(real["fragments"]) == len(real["ctx"].universe())
