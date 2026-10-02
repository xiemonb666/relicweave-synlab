"""The ``HARD_NEGATIVE_MATE_PRESENT`` auxiliary table (N10): ``research/hard_negatives.parquet``.

Why a separate table (measured, not asserted)
---------------------------------------------
The ``CANDIDATE_MATE_PRESENT_NOT_ORDINARY`` rows of the main relation table -- candidates that
carry their own confirmed ``R2`` mate in the same pool -- may not be ordinary negatives
(``relations.mate_absent``), but the Lead ruling allows them as an **independent auxiliary
supervision class** under four conditions.  Those rows therefore have
``loss_mask = True`` with ``eligible_as_negative = False``, which **contradicts the frozen
single-gate rule of the main table** (decision D10:
``eligible_as_negative == (kind in {R0,R1} and loss_mask)`` on every row).  Measured with the real
checker ``qc.decision_checks._check_loss_mask_authority``: appending the class to
``research/relations.parquet`` took the table from 3 to **883** violations (+880, ``docs/a12``
S2).  The class is therefore emitted as its **own artifact**:

    <package>/research/hard_negatives.parquet

What this module provides
-------------------------
* :data:`COLUMN_SEMANTICS` -- the column dictionary of the auxiliary table (also written into the
  sidecar card, so the data card and the bytes cannot drift apart);
* :func:`build_records` -- the records of the class for one relation table
  (``relations.mate_absent.hard_negative_records``, the single source of truth for the class);
* :func:`write_table` / :func:`read_table` -- the parquet round trip;
* :func:`attach_hard_negatives` -- the **one-key switch**: turn the class on or off for a set of
  batch rows.  Off (the default) the rows are returned untouched, so every primary denominator is
  bit-identical; on, each row gains ``hard_negatives`` (a *separate* key -- never ``negatives``).

The table never enters a primary metric denominator
---------------------------------------------------
The invariant is a property of the rows (``eligible_as_negative = False`` on every one of them)
and is re-measured on a real batch by ``tools/a12_n10_hard_negatives_table.py --step verify``:
with the switch off and on, the rank/pos/neg/`effective_queries` denominators must be identical
and ``neg_mask`` must not move.  A consumer that wants the auxiliary term must therefore opt in
*and* read a different key; nothing can pick these rows up by accident.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

#: Schema/version of the auxiliary table artifact.
HARD_NEGATIVES_TABLE_SCHEMA = "synlab.relations.hard_negatives_table.v1"

#: File name inside a package's ``research/`` layer.
HARD_NEGATIVES_FILE = "hard_negatives.parquet"

#: Sidecar card written next to the table (the column dictionary, machine-readable).
HARD_NEGATIVES_CARD_FILE = "hard_negatives.card.json"

#: Environment switch: ``0``/``false``/``off`` disables the class, anything else enables it.
HARD_NEGATIVES_ENV = "SYNLAB_HARD_NEGATIVES"

#: The column dictionary of the auxiliary table.  ``meaning`` is what the data card quotes.
COLUMN_SEMANTICS: dict[str, dict[str, str]] = {
    "query": {"dtype": "string", "unit": "1", "meaning":
              "query fragment of the pair; mate-present by construction (ruling condition 4)"},
    "candidate": {"dtype": "string", "unit": "1", "meaning":
                  "candidate fragment; it carries its own confirmed R2 mate in the same pool, "
                  "which is exactly why it may not be an ordinary negative"},
    "kind": {"dtype": "string", "unit": "1", "meaning":
             "measured relation kind of the pair (R0/R1) -- copied verbatim, never rewritten"},
    "valid": {"dtype": "bool", "unit": "1", "meaning":
              "the row's measurement is usable -- copied verbatim"},
    "area_mm2": {"dtype": "float", "unit": "mm^2", "meaning":
                 "measured shared cut-face area of the pair -- copied verbatim"},
    "loss_mask": {"dtype": "bool", "unit": "1", "meaning":
                  "always true: the row IS supervised, by the auxiliary hard-negative term"},
    "eligible_as_negative": {"dtype": "bool", "unit": "1", "meaning":
                             "always false: the row is never an ordinary negative and never "
                             "contributes to a primary metric denominator"},
    "class": {"dtype": "string", "unit": "1", "meaning":
              "HARD_NEGATIVE_MATE_PRESENT (the auxiliary supervision class)"},
    "ruling_class": {"dtype": "string", "unit": "1", "meaning":
                     "CANDIDATE_MATE_PRESENT_NOT_ORDINARY (its class in the main table's rule)"},
    "reason": {"dtype": "string", "unit": "1", "meaning":
               "the row's own reason string from the main relation table"},
    "query_mate_present": {"dtype": "bool", "unit": "1", "meaning":
                           "always true (ruling condition 4): a mate-absent query would make the "
                           "candidate's mate-presence a give-away of its negative role"},
    "query_mates": {"dtype": "list<string>", "unit": "1", "meaning":
                    "the measured confirmed R2 mates of the query"},
    "candidate_mates": {"dtype": "list<string>", "unit": "1", "meaning":
                        "the measured confirmed R2 mates of the candidate"},
    "source_relations_hash": {"dtype": "string", "unit": "1", "meaning":
                              "sha256 of the relations.parquet this table was derived from"},
    "table_version": {"dtype": "string", "unit": "1", "meaning":
                      f"artifact version, always {HARD_NEGATIVES_TABLE_SCHEMA}"},
}

#: The columns, in write order.
COLUMNS: tuple[str, ...] = tuple(COLUMN_SEMANTICS)

#: The keys a batch row gains when the switch is on (never ``negatives``).
ROW_KEY = "hard_negatives"


def enabled_from_env(default: bool = False) -> bool:
    """The environment switch (``SYNLAB_HARD_NEGATIVES``); unset keeps the documented default."""
    raw = os.environ.get(HARD_NEGATIVES_ENV)
    if raw is None or raw == "":
        return bool(default)
    return str(raw).strip().lower() not in ("0", "false", "off", "no")


# --------------------------------------------------------------------------------------
# records <-> table
# --------------------------------------------------------------------------------------
def build_records(rows: Sequence[Mapping[str, Any]], *, source_relations_hash: str = "",
                  require_query_mate_present: bool = True
                  ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The auxiliary class records of a relation table, in the table's own column order.

    The classification is done by ``relations.mate_absent.hard_negative_records`` -- the single
    source of truth for the class.  This function only projects the result onto
    :data:`COLUMNS` and stamps the provenance, so the artifact and the rule cannot drift.
    """
    from .mate_absent import (CLASS_HARD_NEGATIVE, HARD_NEGATIVE_ELIGIBLE_AS_NEGATIVE,
                              hard_negative_records)

    records, report = hard_negative_records(
        rows, require_query_mate_present=require_query_mate_present)
    out: list[dict[str, Any]] = []
    for record in records:
        assert bool(record["loss_mask"]) is True
        assert bool(record["eligible_as_negative"]) == bool(HARD_NEGATIVE_ELIGIBLE_AS_NEGATIVE)
        assert str(record["class"]) == CLASS_HARD_NEGATIVE
        out.append({
            "query": str(record["query"]), "candidate": str(record["candidate"]),
            "kind": str(record["kind"]), "valid": bool(record["valid"]),
            "area_mm2": float(record["area_mm2"]),
            "loss_mask": bool(record["loss_mask"]),
            "eligible_as_negative": bool(record["eligible_as_negative"]),
            "class": str(record["class"]), "ruling_class": str(record["ruling_class"]),
            "reason": str(record["reason"]),
            "query_mate_present": bool(record["query_mate_present"]),
            "query_mates": [str(x) for x in record["query_mates"]],
            "candidate_mates": [str(x) for x in record["candidate_mates"]],
            "source_relations_hash": str(source_relations_hash),
            "table_version": HARD_NEGATIVES_TABLE_SCHEMA,
        })
    return out, report


def card_payload(*, source_package: str = "", source_relations_hash: str = "",
                 rows: int = 0, rejected: int = 0,
                 rejected_examples: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """The sidecar card: column dictionary + the *constraint* that keeps the table out of metrics."""
    return {
        "schema": HARD_NEGATIVES_TABLE_SCHEMA,
        "table": HARD_NEGATIVES_FILE,
        "rows": int(rows),
        "columns": {name: dict(COLUMN_SEMANTICS[name]) for name in COLUMNS},
        "class": "HARD_NEGATIVE_MATE_PRESENT",
        "ruling_class": "CANDIDATE_MATE_PRESENT_NOT_ORDINARY",
        "source": {"package": str(source_package),
                   "relations_parquet_hash": str(source_relations_hash)},
        "constraints": {
            "independent_of_the_main_table": (
                "the class is NOT part of research/relations.parquet: its contract "
                "(loss_mask=True with eligible_as_negative=False) violates decision D10's single "
                "gate on every row, measured at +880 violations with the real checker"),
            "no_primary_denominator": (
                "eligible_as_negative is false on every row, so the class contributes to no "
                "primary metric denominator (any@50 / Hit@10 / rank n_valid / n_allowed / the "
                "mate-absent misleading rate); re-measured with the switch off vs on"),
            "auxiliary_only": ("consumed through the SYNLAB_HARD_NEGATIVES switch into the "
                               "separate batch key 'hard_negatives', never into 'negatives'"),
            "query_mate_present": ("every row's query carries its own confirmed R2 mate "
                                   "(ruling condition 4); query-absent candidates are excluded "
                                   "and counted in the sidecar's 'rejected' block"),
        },
        "rejected": {"rows": int(rejected),
                     "reason": "query_mate_absent",
                     "examples": [dict(item) for item in list(rejected_examples)[:5]],
                     "note": ("these candidates are a separate open item: their query has no "
                              "mate, so the candidate's mate-presence would be a give-away of "
                              "its negative role")},
    }


def write_table(records: Sequence[Mapping[str, Any]], path: str | Path, *,
                card: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Write the auxiliary table (parquet) and its sidecar card; returns the written paths."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table({
        "query": pa.array([str(r["query"]) for r in records], type=pa.string()),
        "candidate": pa.array([str(r["candidate"]) for r in records], type=pa.string()),
        "kind": pa.array([str(r["kind"]) for r in records], type=pa.string()),
        "valid": pa.array([bool(r["valid"]) for r in records], type=pa.bool_()),
        "area_mm2": pa.array([float(r["area_mm2"]) for r in records], type=pa.float64()),
        "loss_mask": pa.array([bool(r["loss_mask"]) for r in records], type=pa.bool_()),
        "eligible_as_negative": pa.array([bool(r["eligible_as_negative"]) for r in records],
                                         type=pa.bool_()),
        "class": pa.array([str(r["class"]) for r in records], type=pa.string()),
        "ruling_class": pa.array([str(r["ruling_class"]) for r in records], type=pa.string()),
        "reason": pa.array([str(r["reason"]) for r in records], type=pa.string()),
        "query_mate_present": pa.array([bool(r["query_mate_present"]) for r in records],
                                       type=pa.bool_()),
        "query_mates": pa.array([[str(x) for x in r["query_mates"]] for r in records],
                                type=pa.list_(pa.string())),
        "candidate_mates": pa.array([[str(x) for x in r["candidate_mates"]] for r in records],
                                    type=pa.list_(pa.string())),
        "source_relations_hash": pa.array([str(r.get("source_relations_hash", ""))
                                           for r in records], type=pa.string()),
        "table_version": pa.array([str(r.get("table_version", HARD_NEGATIVES_TABLE_SCHEMA))
                                   for r in records], type=pa.string()),
    })
    pq.write_table(table, target)
    out: dict[str, Any] = {"path": str(target), "rows": int(table.num_rows),
                           "columns": [str(name) for name in table.column_names],
                           "bytes": int(target.stat().st_size)}
    if card is not None:
        card_path = target.with_name(HARD_NEGATIVES_CARD_FILE)
        card_path.write_text(json.dumps(dict(card), ensure_ascii=False, indent=2, sort_keys=True),
                             encoding="utf-8")
        out["card_path"] = str(card_path)
    return out


def read_table(path: str | Path) -> list[dict[str, Any]]:
    """Read the auxiliary table back (parquet first, the JSON fallback next to it otherwise)."""
    target = Path(path)
    if target.is_file():
        import pyarrow.parquet as pq

        return [dict(row) for row in pq.read_table(target).to_pylist()]
    fallback = target.with_suffix(".json")
    if fallback.is_file():
        return [dict(row) for row in json.loads(fallback.read_text(encoding="utf-8"))]
    raise FileNotFoundError(f"hard-negative table not found: {target}")


@dataclass
class HardNegativeTable:
    """A loaded auxiliary table plus the switch state it was loaded with."""

    path: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    enabled: bool = False
    card: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ introspection
    @property
    def n_rows(self) -> int:
        return len(self.rows)

    def columns(self) -> list[str]:
        return list(self.rows[0].keys()) if self.rows else list(COLUMNS)

    def counts(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for row in self.rows:
            kinds[str(row["kind"])] = kinds.get(str(row["kind"]), 0) + 1
        return {"rows": self.n_rows, "kinds": dict(sorted(kinds.items())),
                "queries": len({str(r["query"]) for r in self.rows}),
                "candidates": len({str(r["candidate"]) for r in self.rows}),
                "all_loss_mask_true": all(bool(r["loss_mask"]) for r in self.rows),
                "all_eligible_false": all(not bool(r["eligible_as_negative"]) for r in self.rows),
                "all_query_mate_present": all(bool(r["query_mate_present"]) for r in self.rows),
                "enabled": bool(self.enabled)}

    def by_query(self, query: str) -> list[str]:
        return sorted(str(row["candidate"]) for row in self.rows
                      if str(row["query"]) == str(query))

    def assert_constraints(self) -> dict[str, Any]:
        """The four ruling conditions, re-checked on the loaded bytes (never on trust)."""
        problems: list[str] = []
        for index, row in enumerate(self.rows):
            if not bool(row["loss_mask"]):
                problems.append(f"row {index}: loss_mask is not true")
            if bool(row["eligible_as_negative"]):
                problems.append(f"row {index}: eligible_as_negative is not false")
            if not bool(row["query_mate_present"]):
                problems.append(f"row {index}: query side is not mate-present")
            if str(row["class"]) != "HARD_NEGATIVE_MATE_PRESENT":
                problems.append(f"row {index}: class is {row['class']!r}")
        return {"ok": not problems, "problems": problems[:20], "rows": len(self.rows),
                "columns_declared": list(COLUMNS),
                "columns_present": self.columns(),
                "columns_match": self.columns() == list(COLUMNS) if self.rows else True}


def load_hard_negatives(path: str | Path, *, enabled: bool | None = None,
                        with_card: bool = True) -> HardNegativeTable:
    """Load the auxiliary table; ``enabled=None`` reads the environment switch.

    Loading never changes a batch: the switch is applied by :func:`attach_hard_negatives`, so a
    consumer can load the table for reporting and still keep the class out of the batch.
    """
    target = Path(path)
    rows = read_table(target)
    card: dict[str, Any] = {}
    if with_card:
        card_path = target.with_name(HARD_NEGATIVES_CARD_FILE)
        if card_path.is_file():
            card = json.loads(card_path.read_text(encoding="utf-8"))
    state = enabled_from_env() if enabled is None else bool(enabled)
    return HardNegativeTable(path=str(target), rows=rows, enabled=state, card=card,
                             provenance={"source": card.get("source", {}),
                                         "schema": card.get("schema", ""),
                                         "table_version": (rows[0].get("table_version", "")
                                                           if rows else "")})


def package_table_path(package_dir: str | Path) -> Path:
    """``<package>/research/hard_negatives.parquet`` for a training package directory."""
    return Path(package_dir) / "research" / HARD_NEGATIVES_FILE


def attach_hard_negatives(rows: Sequence[Mapping[str, Any]], table: HardNegativeTable, *,
                          enabled: bool | None = None) -> list[dict[str, Any]]:
    """**One-key switch**: return ``rows`` with or without the auxiliary class attached.

    Off (the default) the rows are copied unchanged -- every primary denominator downstream is
    therefore identical to a run without this table.  On, each row whose query is in the table
    gains :data:`ROW_KEY` (a list of candidate ids) under a key of its **own**; ``negatives`` is
    never touched, so an ordinary-negative reading cannot pick these rows up.
    """
    state = table.enabled if enabled is None else bool(enabled)
    out = [dict(row) for row in rows]
    if not state:
        return out
    for row in out:
        query = str(row.get("query", ""))
        candidates = table.by_query(query)
        if not candidates:
            continue
        existing = [str(x) for x in (row.get("negatives") or [])]
        overlap = sorted(set(candidates) & set(existing))
        if overlap:
            raise ValueError(f"row {query}: hard negatives {overlap} are already ordinary "
                             f"negatives; the class may never be an ordinary negative")
        row[ROW_KEY] = candidates
    return out


def denominator_snapshot(batch: Any) -> dict[str, Any]:
    """The primary denominators of a batch -- the numbers the auxiliary class may not move."""
    return {
        "n_queries": int(getattr(batch, "n_queries", 0)),
        "n_candidates": int(getattr(batch, "n_candidates", 0)),
        "positives": int(batch.pos_mask.sum()),
        "negatives": int(batch.neg_mask.sum()),
        "excluded": int(batch.excluded_mask.sum()),
        "effective_queries": int(batch.effective_query_count()),
        "hard_negatives": int(getattr(batch, "hard_neg_mask", None).sum())
        if getattr(batch, "hard_neg_mask", None) is not None else 0,
        "rank_denominator": int((batch.pos_mask | batch.neg_mask).sum()),
    }


__all__ = [
    "HARD_NEGATIVES_TABLE_SCHEMA", "HARD_NEGATIVES_FILE", "HARD_NEGATIVES_CARD_FILE",
    "HARD_NEGATIVES_ENV", "COLUMN_SEMANTICS", "COLUMNS", "ROW_KEY",
    "enabled_from_env", "build_records", "card_payload", "write_table", "read_table",
    "HardNegativeTable", "load_hard_negatives", "package_table_path", "attach_hard_negatives",
    "denominator_snapshot",
]
