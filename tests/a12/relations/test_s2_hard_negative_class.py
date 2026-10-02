"""S2: the ``HARD_NEGATIVE_MATE_PRESENT`` class, produced online.

The class and the Lead ruling it implements are documented in
``synlab/relations/mate_absent.py`` and ``docs/a12/smallfixes_report.md`` (S2).  These tests pin
the four conditions of that ruling on **real** inputs -- a hand-built relation table for the
class semantics, and a real ``relations.parquet`` read back by the **real** decision-D10 checker
for the "why it cannot live in the main table" claim:

1. every record carries ``loss_mask=True`` and ``eligible_as_negative=False``;
2. it contributes to no ordinary-negative denominator (it is not an ordinary negative at all);
3. it is auxiliary-only: a separate record set, never merged into ``research/relations.parquet``
   (condition 2 is what forbids the merge: D10 requires ``eligible_as_negative == loss_mask`` on
   every ``R0``/``R1`` row, so a merged class row is a new audit violation -- measured below);
4. every supervised row has a **mate-present query**, and the rejected rows are reported with
   their reason rather than dropped.

And that the class never rewrites a measurement: ``kind`` / ``valid`` / ``area_mm2`` and the
fragment identities of a record are byte-identical to the row it came from.
"""

from __future__ import annotations

import pytest

from synlab.relations.mate_absent import (
    CLASS_EXCLUDED,
    CLASS_HARD_NEGATIVE,
    CLASS_MATE_PRESENT,
    CLASS_ORDINARY_NEGATIVE,
    CLASS_POSITIVE,
    HARD_NEGATIVE_ELIGIBLE_AS_NEGATIVE,
    HARD_NEGATIVE_LOSS_MASK,
    HARD_NEGATIVE_REJECT_QUERY_MATE_ABSENT,
    HARD_NEGATIVE_TASK,
    MATE_PRESENT_REASON,
    apply_rule,
    hard_negative_class_count,
    hard_negative_records,
    row_class,
)
from synlab.relations.sampler import (
    SamplerParams,
    hard_negative_candidates,
    negative_exclusion_reason,
    sample_training_batch,
)

from _fixtures import build_fixture_pool

# --------------------------------------------------------------------------------------
# a small relation table with both populations and every class
# --------------------------------------------------------------------------------------


def _row(query: str, candidate: str, kind: str, *, valid: bool = True, mask: bool = True,
         area: float = 0.0, reason: str = "", eligible: bool | None = None) -> dict:
    return {"query": query, "candidate": candidate, "kind": kind, "valid": bool(valid),
            "loss_mask": bool(mask), "area_mm2": float(area), "reason": reason,
            "eligible_as_negative": (bool(kind in ("R1", "R0") and valid and mask)
                                     if eligible is None else bool(eligible))}


def _table() -> list[dict]:
    """``p0<->p1`` and ``h0<->h1`` are confirmed R2 events; ``z0``/``z1`` have no mate."""
    return [
        _row("p0", "p1", "R2", mask=True, area=12.5, reason="shared_cut_surface"),
        _row("h0", "h1", "R2", mask=True, area=11.5, reason="shared_cut_surface"),
        # the class: candidate has its own mate AND the query has one too
        _row("p0", "h0", "R0", mask=True, area=3.25, reason="different_physical_mother"),
        _row("p0", "h1", "R1", mask=True, area=1.5, reason="same_type_different_object"),
        # the class's candidate, but a MATE-ABSENT query -> must be rejected (condition 4)
        _row("z0", "h0", "R0", mask=True, area=2.0, reason="different_physical_mother"),
        # a legal ordinary negative
        _row("p0", "z0", "R0", mask=True, area=0.0, reason="different_physical_mother"),
        # neither a positive nor a negative (and D10-clean: valid == loss_mask)
        _row("z0", "z1", "UNKNOWN", valid=False, mask=False, reason="unmeasured"),
    ]


def test_the_table_exercises_every_ruling_class():
    rows = _table()
    from synlab.relations.mate_absent import r2_mates

    mates = r2_mates(rows)
    classes = [row_class(row, mates) for row in rows]
    assert classes == [CLASS_POSITIVE, CLASS_POSITIVE, CLASS_MATE_PRESENT, CLASS_MATE_PRESENT,
                       CLASS_MATE_PRESENT, CLASS_ORDINARY_NEGATIVE, CLASS_EXCLUDED]


def test_records_carry_the_two_flags_and_copy_the_measurement_verbatim():
    rows = _table()
    records, report = hard_negative_records(rows)

    assert {r["candidate"] for r in records} == {"h0", "h1"}
    assert {r["query"] for r in records} == {"p0"}
    for record in records:
        assert record["class"] == CLASS_HARD_NEGATIVE
        assert record["loss_mask"] is True and record["loss_mask"] == HARD_NEGATIVE_LOSS_MASK
        assert record["eligible_as_negative"] is False
        assert record["eligible_as_negative"] == HARD_NEGATIVE_ELIGIBLE_AS_NEGATIVE
        assert record["query_mate_present"] is True
        assert record["candidate_mates"] and record["query_mates"]
        assert record["ruling_class"] == CLASS_MATE_PRESENT

    by_pair = {(r["query"], r["candidate"]): r for r in records}
    source = {(r["query"], r["candidate"]): r for r in rows}
    for key, record in by_pair.items():
        origin = source[key]
        assert record["kind"] == origin["kind"]
        assert record["valid"] is origin["valid"]
        assert record["area_mm2"] == origin["area_mm2"]
        assert record["reason"] == origin["reason"]

    assert report["rows_classed_mate_present"] == 3
    assert report["records"] == 2 and report["rejected"] == 1
    assert report["conformance"] == {
        "loss_mask_true_and_eligible_false": True,
        "no_primary_denominator_contribution": True,
        "auxiliary_only": HARD_NEGATIVE_TASK,
        "query_mate_present_for_every_row": True,
    }
    assert report["flags"] == {"loss_mask": True, "eligible_as_negative": False}


def test_a_mate_absent_query_is_rejected_with_its_reason():
    rows = _table()
    records, report = hard_negative_records(rows)
    rejected = report["rejected_rows"]
    assert len(rejected) == 1
    assert (rejected[0]["query"], rejected[0]["candidate"]) == ("z0", "h0")
    assert rejected[0]["reject_reason"] == HARD_NEGATIVE_REJECT_QUERY_MATE_ABSENT
    assert rejected[0]["query_mate_present"] is False
    assert rejected[0]["candidate_mates"] == ["h1"]
    # the rejected row is *not* silently promoted when the guard is switched off either: it is
    # then admitted, and the report says so
    loose, loose_report = hard_negative_records(rows, require_query_mate_present=False)
    assert len(loose) == 3 and loose_report["rejected"] == 0
    assert loose_report["conformance"]["query_mate_present_for_every_row"] is False
    assert {(r["query"], r["candidate"]) for r in records} < {
        (r["query"], r["candidate"]) for r in loose}


def test_the_input_table_is_never_mutated_and_the_ruling_is_stable():
    rows = _table()
    before = [dict(row) for row in rows]
    hard_negative_records(rows)
    assert rows == before

    # the same class is recognised after the mate-absent ruling has cleared loss_mask: the class
    # is a property of the pair, not of when it was read
    ruled, _ = apply_rule(rows)
    assert ruled[2]["loss_mask"] is False and MATE_PRESENT_REASON in ruled[2]["reason"]
    records, report = hard_negative_records(ruled)
    assert {r["candidate"] for r in records} == {"h0", "h1"}
    assert report["rejected"] == 1
    assert all(r["valid"] is True for r in records)


def test_the_class_never_contains_a_positive_or_the_query_own_mate():
    rows = _table()
    records, _ = hard_negative_records(rows)
    for record in records:
        assert record["kind"] in ("R1", "R0")
        assert record["candidate"] not in record["query_mates"]
        assert record["candidate"] != record["query"]


def test_class_count_table_is_a_pure_function_of_the_rows():
    rows = _table()
    table = hard_negative_class_count(rows)
    assert table["class"] == CLASS_HARD_NEGATIVE
    assert table["records"] == 2 and table["rejected"] == 1
    assert table["queries"] == 1 and table["candidates"] == 2
    assert table["records_by_query"] == {"p0": 2}
    assert table["conformance"]["loss_mask_true_and_eligible_false"] is True


# --------------------------------------------------------------------------------------
# condition 2, measured with the real decision-D10 checker
# --------------------------------------------------------------------------------------
def test_merging_the_class_into_relations_parquet_would_add_d10_violations(tmp_path):
    """The class cannot live in the main table -- measured, not asserted.

    ``qc.decision_checks._check_loss_mask_authority`` (decision D10) requires
    ``eligible_as_negative == (kind in {R0,R1} and loss_mask)`` for **every** row of
    ``relations.parquet``.  A class record has ``loss_mask=True`` with
    ``eligible_as_negative=False`` by contract, so appending it is a new violation; keeping it in
    its own record set leaves the main table exactly as the exporter wrote it.
    """
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    from synlab.qc.decision_checks import _check_loss_mask_authority

    rows = _table()
    records, _ = hard_negative_records(rows)

    def _write(name: str, payload: list[dict]) -> None:
        target = tmp_path / name
        target.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({
            "query": pa.array([str(r["query"]) for r in payload]),
            "candidate": pa.array([str(r["candidate"]) for r in payload]),
            "kind": pa.array([str(r["kind"]) for r in payload]),
            "valid": pa.array([bool(r.get("valid", False)) for r in payload]),
            "loss_mask": pa.array([bool(r.get("loss_mask", False)) for r in payload]),
            "eligible_as_negative": pa.array([bool(r.get("eligible_as_negative", False))
                                              for r in payload]),
        }), target / "relations.parquet")

    _write("separate", rows)
    _write("merged", rows + [{"query": r["query"], "candidate": r["candidate"], "kind": r["kind"],
                              "valid": r["valid"], "loss_mask": True,
                              "eligible_as_negative": False} for r in records])

    separate = _check_loss_mask_authority(tmp_path / "separate")
    merged = _check_loss_mask_authority(tmp_path / "merged")
    assert separate.denominator == len(rows) and merged.denominator == len(rows) + len(records)
    assert (merged.denominator - merged.hits) - (separate.denominator - separate.hits) == \
        len(records)
    # every class record is reported as a violation, with the exact flags that caused it
    # (the checker's violation records carry file/index/kind/flags, not the pair itself; the
    # class rows are the ones appended after the main table)
    appended = set(range(len(rows), len(rows) + len(records)))
    examples = [v for v in (merged.evidence or {}).get("violations", [])
                if int(v["index"]) in appended]
    assert len(examples) == len(records)
    assert all(v["loss_mask"] is True and v["eligible_as_negative"] is False for v in examples)
    # the main table's own rows are untouched by the class: the separate package decides exactly
    # as it does today, class present or not
    assert (separate.status, separate.hits) == ("PASS", len(rows)), \
        "the main table is untouched by the class"
    assert merged.hits == separate.hits, (
        "merging adds violations without fixing any: the class cannot be expressed in the "
        "main table's three frozen columns")


# --------------------------------------------------------------------------------------
# the live pool path
# --------------------------------------------------------------------------------------
def _pool(**kwargs):
    kwargs.setdefault("lineages", {"L1": ["p0", "p1"], "L2": ["h0", "h1"], "L3": ["z0", "z1"]})
    kwargs.setdefault("r2", {"p0": ["p1"], "h0": ["h1"]})
    kwargs.setdefault("r1", [])
    return build_fixture_pool(**kwargs)


def test_live_candidates_are_exactly_the_mate_present_non_ordinary_class():
    pool = _pool()
    for candidate in ("h0", "h1"):
        assert negative_exclusion_reason(pool, "p0", candidate) == "candidate_mate_present"
    for candidate in ("z0", "z1"):
        assert negative_exclusion_reason(pool, "p0", candidate) is None

    report = hard_negative_candidates(pool, "p0")
    assert report["ok"] is True and report["query_mate_present"] is True
    assert [r["candidate"] for r in report["candidates"]] == ["h0", "h1"]
    for record in report["candidates"]:
        assert record["class"] == CLASS_HARD_NEGATIVE
        assert record["loss_mask"] is True and record["eligible_as_negative"] is False
        assert record["query_mate_present"] is True
        assert record["candidate_mates"] and record["candidate_mates"] != [record["query"]]
        assert record["exclusion_reason"] == "candidate_mate_present"
    assert report["conformance"]["loss_mask_true_and_eligible_false"] is True
    # an ordinary legal negative is never part of the class
    assert "z0" not in {r["candidate"] for r in report["candidates"]}


def test_a_mate_absent_query_gets_no_class_candidates_at_all():
    pool = _pool()
    report = hard_negative_candidates(pool, "z0")
    assert report["ok"] is False
    assert report["reason"] == HARD_NEGATIVE_REJECT_QUERY_MATE_ABSENT
    assert report["candidates"] == [] and report["records"] == 0
    assert report["query_mate_present"] is False


def test_the_limit_is_applied_and_reported():
    pool = _pool()
    report = hard_negative_candidates(pool, "p0", limit=1)
    assert [r["candidate"] for r in report["candidates"]] == ["h0"]
    assert report["omitted_by_limit"] == 1
    unlimited = hard_negative_candidates(pool, "p0", limit=None)
    assert [r["candidate"] for r in unlimited["candidates"]] == ["h0", "h1"]
    assert unlimited["omitted_by_limit"] == 0


def test_the_sampler_is_off_by_default_and_the_class_never_joins_negatives():
    pool = _pool()
    assert SamplerParams().hard_negative_limit == 0
    assert SamplerParams.from_config({}).hard_negative_limit == 0

    import numpy as np

    from synlab.relations.sampler import new_sampler_state

    def _run(cfg):
        return sample_training_batch(pool, cfg, np.random.default_rng(0),
                                     state=new_sampler_state(), query_ids=["p0"])

    off = _run(None)
    assert "hard_negatives" not in off["rows"][0]
    assert off["exposure"]["hard_negatives"]["disabled_queries"] == 1

    on = _run({"hard_negative_limit": 2})
    row = on["rows"][0]
    assert row["hard_negatives"] == ["h0", "h1"]
    assert row["hard_negative_class"] == CLASS_HARD_NEGATIVE
    assert row["hard_negative_ok"] is True
    # condition 2 at the sampler: the ordinary negative set is byte-identical
    assert row["negatives"] == off["rows"][0]["negatives"]
    assert not set(row["hard_negatives"]) & set(row["negatives"])
    assert on["exposure"]["negatives"] == off["exposure"]["negatives"]
    assert on["exposure"]["hard_negatives"]["candidates"] == 2
    assert on["labels"] == off["labels"]
    assert on["exclusions"] == off["exclusions"]


def test_a_mate_absent_query_is_reported_by_the_sampler_not_silently_empty():
    pool = _pool()
    import numpy as np

    from synlab.relations.sampler import new_sampler_state

    batch = sample_training_batch(pool, {"hard_negative_limit": 3}, np.random.default_rng(1),
                                  state=new_sampler_state(), query_ids=["z0"])
    row = batch["rows"][0]
    assert row["hard_negatives"] == [] and row["hard_negative_ok"] is False
    assert row["hard_negative_reason"] == HARD_NEGATIVE_REJECT_QUERY_MATE_ABSENT
    assert batch["exposure"]["hard_negatives"]["query_mate_absent"] == 1


def test_the_exported_class_semantics_are_the_rule_semantics():
    """The online record and the offline rule agree on the same pair (no second definition)."""
    rows = _table()
    records, _ = hard_negative_records(rows)
    pool = _pool()
    live = hard_negative_candidates(pool, "p0")["candidates"]
    keys_offline = {(r["query"], r["candidate"]) for r in records}
    keys_live = {(r["query"], r["candidate"]) for r in live}
    assert keys_offline == keys_live == {("p0", "h0"), ("p0", "h1")}
    assert all(r["class"] == CLASS_HARD_NEGATIVE for r in live)


def test_the_guards_are_not_relaxed_by_this_class():
    """The class adds a supervision set; it never widens what may be a *negative*.

    Three refusals stay exactly as they were: the query's own confirmed mate is ``known_R2``,
    a candidate carrying its own mate is ``candidate_mate_present`` (the class, not an ordinary
    negative), and self is ``same_fragment``.
    """
    pool = _pool()
    assert negative_exclusion_reason(pool, "p0", "p1") == "known_R2"
    assert negative_exclusion_reason(pool, "p0", "h0") == "candidate_mate_present"
    assert negative_exclusion_reason(pool, "p0", "p0") == "same_fragment"
    assert negative_exclusion_reason(pool, "p0", "z0") is None
    # ... and the raw table keeps its own frozen derivation: a class record is *not* written back
    rows = _table()
    records, _ = hard_negative_records(rows)
    assert all(r["eligible_as_negative"] is False for r in records)
    from synlab.relations.mate_absent import r2_mates

    mates = r2_mates(rows)
    assert [row_class(r, mates) for r in rows][2] == CLASS_MATE_PRESENT
