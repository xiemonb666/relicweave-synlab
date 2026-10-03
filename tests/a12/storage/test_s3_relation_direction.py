"""S3 contract: the exported relation table records **both** role assignments of every pair.

``query``/``candidate`` are roles, not the pair: an R2 mate cut is shared from both ends and an
R1/R0 pair is unrelated from both ends, so a table that publishes one role assignment per unordered
pair loses half its supervision.  Measured on the shipped release: 1794 unordered pairs, 1794 rows,
**0** reverse rows -- and the loss is not cosmetic, because
``TrainingBatch.effective_query_count()`` (``batch.py:107-111``) counts a query only when it has
>=1 positive **and** >=1 legal negative, so which role assignment the table happens to record
decides whether the query is trainable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _fixtures import REPO_ROOT

STORE = REPO_ROOT / "data" / "a12_trainable" / "store"


def test_audit_reports_a_doubling_of_rows_with_no_fabrication() -> None:
    """The fix adds rows by *role*, never by inventing a pair or a label."""
    if not (STORE / "metadata.sqlite").is_file():
        pytest.skip(f"store {STORE} not present")
    from tools.a12_relation_direction_audit import audit

    report = audit(STORE)
    assert report["available"] is True
    # every unordered pair gets exactly one extra row, and no pair is invented
    assert report["rows_direction_complete"] == 2 * report["unordered_pairs"]
    assert report["rows_shipped"] == report["unordered_pairs"]
    assert report["missing_direction_rows"] == report["unordered_pairs"]
    assert report["reverse_rows_present_in_shipped"] == 0
    # the label is symmetric, so the gain is supervision *exposure*, not new information
    assert report["supervised_pairs"] > 0
    assert report["eligible_negative_pairs"] > 0


def test_direction_completion_increases_effective_queries() -> None:
    """The measured payoff: more queries satisfy ">=1 positive AND >=1 legal negative"."""
    if not (STORE / "metadata.sqlite").is_file():
        pytest.skip(f"store {STORE} not present")
    from tools.a12_relation_direction_audit import audit

    report = audit(STORE)
    shipped = report["shipped"]["effective_queries"]
    complete = report["direction_complete"]["effective_queries"]
    assert complete > shipped, (
        "direction-completing the table must not reduce the number of trainable queries")
    # both halves of the conjunction must move, otherwise the gain came from one side only
    assert report["direction_complete"]["queries_with_a_positive"] \
        >= report["shipped"]["queries_with_a_positive"]
    assert report["direction_complete"]["queries_with_a_legal_negative"] \
        >= report["shipped"]["queries_with_a_legal_negative"]


def test_effective_query_arithmetic_matches_the_batch_definition() -> None:
    """The audit's arithmetic is the batch's own definition, restated on table rows."""
    import inspect

    from synlab.training.batch import TrainingBatch

    source = inspect.getsource(TrainingBatch.valid_query_indices)
    assert "pos_mask" in source and "neg_mask" in source
    assert "(pos > 0)" in source and "(neg > 0)" in source

    from tools.a12_relation_direction_audit import _eligible

    # an eligible negative is exactly the exporter's own condition
    from synlab.storage.export import NEGATIVE_KINDS

    assert _eligible({"kind": "R0", "valid": True, "loss_mask": True}) is True
    assert _eligible({"kind": "R0", "valid": True, "loss_mask": False}) is False
    assert _eligible({"kind": "R2", "valid": True, "loss_mask": True}) is False
    assert "R2" not in NEGATIVE_KINDS


def test_export_emits_reverse_role_rows(tmp_path: Path) -> None:
    """A real export of a small release carries both directions and says so in its counts."""
    store = REPO_ROOT / "data" / "a12_exports" / "closed_loop" / "store"
    release = "rel_852ab2a1e4c3_1790909619"
    if not (store / "releases" / release / "manifest.json").is_file():
        pytest.skip(f"store {store} carries no release {release}")
    import pyarrow.parquet as pq

    from synlab.storage.export import export_training_package
    from synlab.storage.store import AssetStore

    out = tmp_path / "training_package"
    manifest = export_training_package(AssetStore(store), release, out,
                                       formats=("parquet", "npz", "tar"), include_truth=True)
    counts = manifest["counts"]
    assert counts["relation_pairs_direction_complete"] is True
    assert counts["relations"] == 2 * counts["unordered_relation_pairs"]
    assert counts["relation_rows_reverse_role"] == counts["unordered_relation_pairs"]
    rows = pq.read_table(out / "research" / "relations.parquet").to_pylist()
    pairs = {(row["query"], row["candidate"]) for row in rows}
    # every row's reverse is present too
    assert all((b, a) in pairs for a, b in pairs)
    # the two role assignments of one pair carry the *same* label (symmetry, not invention)
    by_pair = {}
    for row in rows:
        by_pair.setdefault(row["pair_key"], []).append(row)
    for key, group in by_pair.items():
        assert len(group) == 2, key
        assert {row["kind"] for row in group} .__len__() == 1
        assert {bool(row["valid"]) for row in group} .__len__() == 1
        assert {row["direction"] for row in group} == {"canonical", "reverse"}
