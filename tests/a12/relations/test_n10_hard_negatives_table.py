"""N10: the ``HARD_NEGATIVE_MATE_PRESENT`` auxiliary table (``research/hard_negatives.parquet``).

The class may not be an ordinary negative and may not be appended to ``research/relations.parquet``
(decision D10's single gate: ``eligible_as_negative == (kind in {R0,R1} and loss_mask)`` on every
row; measured at **+880 violations** with the real checker).  The Lead approved an independent
auxiliary table instead.  These tests pin the artifact's contract:

* row count and column dictionary (the table is the 880 mate-present records with a mate-present
  query -- the other 240 candidates are rejected, not silently dropped);
* the four ruling conditions, re-read from the written bytes (never from the producer's intent);
* the **one-key switch**: off leaves the rows untouched, on attaches the class under its own key
  and never under ``negatives``;
* the emitted table is *not* in the main relation table, and appending it there would still add
  exactly its own rows as D10 violations (the counter-proof, re-measured).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _fixtures import REPO_ROOT
from synlab.qc.pool_contract import canonical_rows
from synlab.relations.hard_negatives_table import (
    COLUMNS,
    COLUMN_SEMANTICS,
    HARD_NEGATIVES_CARD_FILE,
    HARD_NEGATIVES_ENV,
    HARD_NEGATIVES_FILE,
    HARD_NEGATIVES_TABLE_SCHEMA,
    HardNegativeTable,
    attach_hard_negatives,
    build_records,
    card_payload,
    enabled_from_env,
    load_hard_negatives,
    read_table,
    write_table,
)

PACKAGE = REPO_ROOT / "data" / "a12_exports" / "negfix" / "next_experiment" / "training_package"
TABLE = REPO_ROOT / "data" / "a12_reports" / "n10" / HARD_NEGATIVES_FILE
CARD = TABLE.with_name(HARD_NEGATIVES_CARD_FILE)
needs_table = pytest.mark.skipif(not TABLE.is_file(),
                                 reason="the auxiliary table has not been built in this checkout")


# --------------------------------------------------------------------------------------
# the artifact
# --------------------------------------------------------------------------------------
@needs_table
def test_the_table_has_the_measured_row_count_and_kinds() -> None:
    table = load_hard_negatives(TABLE)
    assert table.n_rows == 880
    counts = table.counts()
    assert counts["kinds"] == {"R0": 880}
    assert counts["all_loss_mask_true"] and counts["all_eligible_false"]
    assert counts["all_query_mate_present"]
    assert counts["queries"] > 0 and counts["candidates"] > 0


@needs_table
def test_the_column_dictionary_is_the_declared_one() -> None:
    table = load_hard_negatives(TABLE)
    constraints = table.assert_constraints()
    assert constraints["ok"], constraints["problems"]
    assert table.columns() == list(COLUMNS)
    assert COLUMNS[0] == "query" and "eligible_as_negative" in COLUMNS
    # every declared column carries a meaning and a unit: this is the data-card column table
    for name, spec in COLUMN_SEMANTICS.items():
        assert spec.get("meaning") and spec.get("dtype") and spec.get("unit"), name
    card = json.loads(CARD.read_text(encoding="utf-8"))
    assert card["schema"] == HARD_NEGATIVES_TABLE_SCHEMA
    assert set(card["columns"]) == set(COLUMNS)
    assert card["rows"] == 880
    assert card["constraints"]["no_primary_denominator"]
    assert card["constraints"]["independent_of_the_main_table"]


@needs_table
def test_the_rejected_rows_are_counted_not_dropped() -> None:
    """240 candidates have a mate-absent query: they are refused and counted, never supervised."""
    card = json.loads(CARD.read_text(encoding="utf-8"))
    assert card["rejected"]["rows"] == 240
    assert card["rejected"]["reason"] == "query_mate_absent"
    assert card["rejected"]["examples"]
    from synlab.relations.mate_absent import HARD_NEGATIVE_REJECT_QUERY_MATE_ABSENT

    assert HARD_NEGATIVE_REJECT_QUERY_MATE_ABSENT == "query_mate_absent"


@needs_table
def test_the_class_is_not_in_the_main_relation_table() -> None:
    """The class names real pairs of the main table, but its *flags* are not in that table.

    Two facts, both measured here:

    * every ``(query, candidate)`` of the auxiliary table **is** a row of
      ``research/relations.parquet`` -- the class is a re-reading of measured rows, not a new
      label (a pair that is not in the table would be an invented relation);
    * the main table carries **no** row with the class's flag pair (``loss_mask=True`` together
      with ``eligible_as_negative=False``) -- that combination is what violates decision D10's
      single gate, and it is why the class lives in its own artifact.
    """
    from synlab.storage.export import TrainingPackage

    if not (PACKAGE / "export_manifest.json").exists():
        pytest.skip("real package not present")
    rows = TrainingPackage(PACKAGE).relations()
    assert rows, "the package carries no relation row"
    class_keys = {(str(r["query"]), str(r["candidate"]))
                  for r in load_hard_negatives(TABLE).rows}
    main_keys = {(str(r["query"]), str(r["candidate"])) for r in rows}
    assert class_keys <= main_keys, sorted(class_keys - main_keys)[:5]
    offenders = [(str(r["query"]), str(r["candidate"])) for r in rows
                 if str(r.get("kind")) in ("R0", "R1") and bool(r.get("loss_mask"))
                 and not bool(r.get("eligible_as_negative"))]
    assert offenders == [], offenders[:5]
    assert all(str(r.get("class", "")) != "HARD_NEGATIVE_MATE_PRESENT" for r in rows)


@needs_table
def test_appending_the_class_to_the_main_table_adds_exactly_its_own_d10_violations() -> None:
    """The counter-proof, re-measured with the real checker on the real rows."""
    from synlab.qc.decision_checks import _check_loss_mask_authority
    from synlab.storage.export import TrainingPackage

    if not (PACKAGE / "export_manifest.json").exists():
        pytest.skip("real package not present")

    import pyarrow as pa
    import pyarrow.parquet as pq

    package = TrainingPackage(PACKAGE)
    main = [dict(row) for row in package.relations()]
    records = load_hard_negatives(TABLE).rows

    def _write(root: Path, name: str, rows) -> None:
        target = root / name
        target.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({
            "query": pa.array([str(r["query"]) for r in rows]),
            "candidate": pa.array([str(r["candidate"]) for r in rows]),
            "kind": pa.array([str(r["kind"]) for r in rows]),
            "valid": pa.array([bool(r.get("valid", False)) for r in rows]),
            "loss_mask": pa.array([bool(r.get("loss_mask", False)) for r in rows]),
            "eligible_as_negative": pa.array([bool(r.get("eligible_as_negative", False))
                                              for r in rows]),
        }), target / "relations.parquet")

    with pytest.MonkeyPatch.context() as patch:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "separate", main)
            _write(root, "merged", main + [dict(r) for r in records])
            separate = _check_loss_mask_authority(root / "separate")
            merged = _check_loss_mask_authority(root / "merged")
            patch.setattr("builtins.print", lambda *a, **k: None)
    added = (merged.denominator - merged.hits) - (separate.denominator - separate.hits)
    assert added == 880, (added, separate.denominator - separate.hits,
                          merged.denominator - merged.hits)


# --------------------------------------------------------------------------------------
# the switch (data-independent: the canonical context)
# --------------------------------------------------------------------------------------
@pytest.fixture()
def synthetic_table(tmp_path: Path) -> HardNegativeTable:
    """A real record set from the canonical relation rows (no packaged data needed)."""
    rows = canonical_rows()
    records, report = build_records(rows, source_relations_hash="sha256:canonical")
    assert records, "the canonical table must contain R0 rows with mate-present sides"
    assert report["rejected"] >= 0
    written = write_table(records, tmp_path / HARD_NEGATIVES_FILE,
                          card=card_payload(rows=len(records), rejected=report["rejected"]))
    loaded = load_hard_negatives(written["path"], enabled=False)
    assert loaded.n_rows == len(records)
    return loaded


def test_the_switch_off_leaves_the_rows_untouched(synthetic_table: HardNegativeTable) -> None:
    rows = [{"query": synthetic_table.rows[0]["query"], "positives": [], "negatives": ["x"]}]
    out = attach_hard_negatives(rows, synthetic_table, enabled=False)
    assert out[0] == rows[0]
    assert "hard_negatives" not in out[0]
    assert rows[0].get("hard_negatives") is None


def test_the_switch_on_attaches_the_class_under_its_own_key(
        synthetic_table: HardNegativeTable) -> None:
    query = str(synthetic_table.rows[0]["query"])
    rows = [{"query": query, "positives": [], "negatives": []}]
    out = attach_hard_negatives(rows, synthetic_table, enabled=True)
    assert out[0]["hard_negatives"] == synthetic_table.by_query(query)
    assert out[0]["negatives"] == []              # never merged into the ordinary negatives
    assert rows[0].get("hard_negatives") is None  # the input is not mutated


def test_the_switch_refuses_a_candidate_that_is_also_an_ordinary_negative(
        synthetic_table: HardNegativeTable) -> None:
    query = str(synthetic_table.rows[0]["query"])
    clash = synthetic_table.by_query(query)[0]
    with pytest.raises(ValueError) as info:
        attach_hard_negatives([{"query": query, "positives": [], "negatives": [clash]}],
                              synthetic_table, enabled=True)
    assert "ordinary" in str(info.value)


def test_the_switch_can_cap_the_class_per_query(synthetic_table: HardNegativeTable) -> None:
    query = str(synthetic_table.rows[0]["query"])
    full = synthetic_table.by_query(query)
    out = attach_hard_negatives([{"query": query, "positives": [], "negatives": []}],
                                synthetic_table, enabled=True, limit=1)
    assert out[0]["hard_negatives"] == full[:1] if full else out[0].get("hard_negatives") is None


def test_the_environment_switch_defaults_to_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HARD_NEGATIVES_ENV, raising=False)
    assert enabled_from_env() is False
    monkeypatch.setenv(HARD_NEGATIVES_ENV, "1")
    assert enabled_from_env() is True
    for value in ("0", "false", "OFF", "no"):
        monkeypatch.setenv(HARD_NEGATIVES_ENV, value)
        assert enabled_from_env() is False, value


def test_the_round_trip_preserves_the_mate_lists(synthetic_table: HardNegativeTable) -> None:
    row = next(item for item in synthetic_table.rows if item["candidate_mates"])
    assert isinstance(row["query_mates"], list) and isinstance(row["candidate_mates"], list)
    reread = read_table(synthetic_table.path)
    assert reread[0]["query_mates"] == synthetic_table.rows[0]["query_mates"]
    assert reread[0]["candidate_mates"] == synthetic_table.rows[0]["candidate_mates"]


def test_every_record_carries_the_class_flags(synthetic_table: HardNegativeTable) -> None:
    for row in synthetic_table.rows:
        assert row["class"] == "HARD_NEGATIVE_MATE_PRESENT"
        assert row["ruling_class"] == "CANDIDATE_MATE_PRESENT_NOT_ORDINARY"
        assert row["loss_mask"] is True
        assert row["eligible_as_negative"] is False
        assert row["query_mate_present"] is True
        assert row["table_version"] == HARD_NEGATIVES_TABLE_SCHEMA
