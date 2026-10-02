"""The pool protocol against a **real** exported package and the **real** asset store.

``tests/a12/qc/test_pool_protocol_contract.py`` proves the battery can distinguish the clauses on
a canonical fixture.  This file runs the same battery on the real inputs the pipeline ships:

* the four implementations instantiated from ``research/relations.parquet`` of the exported
  package (1721 rows, 71 fragments), and
* a real ``relations.gallery.RelationPool`` whose sparse index is loaded from the real asset
  store over exactly those fragments (``collect_fragments`` + ``load_relations_into``).

Two facts are pinned here, both measured, neither averaged:

1. **the safety half holds**: every implementation satisfies all 13 clauses, and no reader
   disagrees with another about the *kind* of a pair a measured row names, or about a mate set;
2. **one divergence is real and is recorded, not smoothed over**: the 24 ``R1`` rows of this
   scope carry ``valid=False`` / ``loss_mask=False`` / ``eligible_as_negative=False``
   ("no_direct_fracture_surface"); ``relations.gallery.RelationPool``, ``PoolIndex[gallery]`` and
   ``PoolIndex[exported]`` offer them as ordinary negatives while
   ``qc.loader_probe.ExportedRelationPool`` and ``training.smoke.TrainingPoolView`` refuse them.
   ``test_the_eligibility_divergence_is_pinned`` fails the moment that changes -- so the fix
   cannot land silently, and this record cannot go stale.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _fixtures import REPO_ROOT
from synlab.qc.pool_contract import (
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


def test_the_eligibility_divergence_is_pinned(real) -> None:
    """**A recorded divergence, not blessed behaviour.**

    24 ``R1`` rows (48 directed pairs) of this scope are marked ``valid=False`` /
    ``loss_mask=False`` / ``eligible_as_negative=False`` with the reason
    ``no_direct_fracture_surface``, i.e. the frozen gate says they may not be ordinary negatives.
    Three readers offer them anyway:

    * ``relations.gallery.RelationPool`` -- ``RelationsIndex.confirmed()`` accepts an explicit
      edge regardless of its ``valid`` flag;
    * ``training.sampler.PoolIndex`` -- ``confirmed()`` recomputes confirmation from
      ``relation()`` alone (``rel in {R0,R1,R2}``) instead of asking the carrier, so it offers the
      rows even over the exported reader that refuses them itself.  This is the **live sampler
      path**.

    The one-line fix is recorded in the finding.  It is *not* applied here: it changes which
    candidates the live sampler draws, i.e. the training data, so it is a Lead decision (the same
    shape as N9's QA tightening).  Until then this test keeps the divergence visible and exact.
    """
    finding = eligibility_finding(real["pools"], real["ctx"])
    assert finding["directed_pairs"] == 48
    assert finding["unordered_pairs"] == 24
    assert finding["kinds"] == ["R1"]
    assert finding["all_rows_valid_false"] is True
    assert finding["all_rows_loss_mask_false"] is True
    assert finding["offered_by_counts"] == {
        "relations.gallery.RelationPool": 48,
        "training.sampler.PoolIndex[exported]": 48,
        "training.sampler.PoolIndex[gallery]": 48,
    }
    example = finding["examples"][0]
    assert example["measured_kind"] == "R1"
    assert example["row_eligible_as_negative"] is False
    assert example["refused_by"] == ["qc.loader_probe.ExportedRelationPool",
                                     "training.smoke.TrainingPoolView"]
    assert finding["frozen_gate"] == \
        "eligible_as_negative == (kind in {R0,R1} and valid and loss_mask)"


def test_the_failure_injection_is_caught_on_the_real_gallery_pool(real) -> None:
    report = run_failure_injections(real["ctx"], base=real["pools"]["relations.gallery.RelationPool"])
    assert report["ok"] is True
    assert report["caught"] == report["total"] == 6


def test_the_store_side_index_is_the_same_relation_reading(real) -> None:
    """The gallery's sparse index must be loaded from the real store, not synthesised here."""
    if not real["fragments"]:
        pytest.skip("real asset store not present")
    assert len(real["fragments"]) == len(real["ctx"].universe())
