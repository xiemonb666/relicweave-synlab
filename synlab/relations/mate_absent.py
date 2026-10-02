"""Mate-absent rule for ordinary relation negatives (the fix for the `rank` task).

The problem this module rules on
-------------------------------
A relation row ``(q, c, kind)`` with ``kind in {R1, R0}``, ``valid`` and ``loss_mask`` is an
*ordinary negative* of the query ``q``.  Nothing in that rule looks at the **candidate's own
adjacency**: a candidate ``c`` that has its own confirmed ``R2`` mate ``d`` inside the very same
pool was still offered as an ordinary negative of unrelated queries.  Measured on
``data/a12_exports/trainable/next_experiment/training_package``: ``LIN0101_V16_M12_PAT12_E01-m``
was used as an ordinary negative of ``LIN0100_V17_M02_PAT08_E01-m`` while its own mate
``LIN0101_V16_M12_PAT12_E01-p`` sat in the same gallery -- i.e. the training signal said "this
sherd is not the same body as that one" about a sherd whose true partner *is* in the pool.  A
model can exploit exactly that: "a fragment that has a matching partner somewhere in the
gallery" becomes a fragment-level cue for being a positive, a transductive shortcut that has
nothing to do with the observed surface.

The rule
--------
``mate_absent(c)`` -- the candidate has **no** confirmed ``R2`` mate in the pool -- is a
precondition for the *ordinary negative* class.  This is the pool semantics the plan already
uses for retrieval queries: a fragment whose mate is not in the gallery cannot be a retrieval
target (Hit / CovRecall are ``N/A`` for it, ``synlab.diagnostics.metrics``) and its only role is
to act as a distractor/negative.  This module applies the same reading to the candidate side of a
negative pair.

Classes (exactly one per row, recorded in the report and, for the affected rows, in the
exported ``reason`` column):

``POSITIVE_R2``
    ``kind == R2 and valid`` -- the row is a positive, not a negative.  Untouched.
``ORDINARY_NEGATIVE_MATE_ABSENT``
    ``kind in {R1, R0} and valid and loss_mask and mate_absent(candidate)`` -- a legal ordinary
    negative, unchanged.
``CANDIDATE_MATE_PRESENT_NOT_ORDINARY``
    ``kind in {R1, R0} and valid and loss_mask`` but the **candidate has its own R2 mate** in the
    pool.  This is a *separate class*, not an ordinary negative: the row is kept in the table
    with its measured ``kind``/``valid``/``area_mm2`` (the measurement is not rewritten), its
    ``loss_mask`` is cleared and its ``reason`` records why.
``EXCLUDED``
    everything else (invalid, already unmasked, ``TINY_CONTACT``, ``UNKNOWN``, ...).

Is the separate class allowed to enter a loss?
---------------------------------------------
``synlab.training.batch.assert_legal_negative`` would *accept* such a candidate (it only refuses
the query itself, the query's own historical ``R2``, ``UNKNOWN``/``TINY_CONTACT`` and unconfirmed
labels), so nothing here is a *guard* violation.  It is refused by the plan's mate-absent
semantics, which is stricter.  Mechanism and counts are documented in
``docs/a12/relation_negatives.md``; the guard itself is untouched and never relaxed.

What this module never does
---------------------------
* it never changes ``kind``, ``valid``, ``area_mm2`` or the query/candidate identities -- only
  the *supervision eligibility* of a row (``loss_mask``) and its recorded ``reason``;
* it never invents a negative, a mate or a class value;
* it never turns an ``UNKNOWN`` row into anything (an ``UNKNOWN`` pair is not a negative and not
  a positive).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..schemas.runtime import RELATION_R0, RELATION_R1, RELATION_R2

MATE_ABSENT_RULE_VERSION = "relations.mate_absent.v1"

#: ``reason`` marker appended to a row whose candidate carries its own R2 mate.
MATE_PRESENT_REASON = "ordinary_negative_forbidden:mate_present_candidate"

#: the same ruling in the sampler's exclusion vocabulary
#: (``synlab.relations.sampler.negative_exclusion_reason``).
MATE_PRESENT_EXCLUSION_REASON = "candidate_mate_present"

#: the four row classes (exactly one per row)
CLASS_POSITIVE = "POSITIVE_R2"
CLASS_ORDINARY_NEGATIVE = "ORDINARY_NEGATIVE_MATE_ABSENT"
CLASS_MATE_PRESENT = "CANDIDATE_MATE_PRESENT_NOT_ORDINARY"
CLASS_EXCLUDED = "EXCLUDED"
ROW_CLASSES: tuple[str, ...] = (CLASS_POSITIVE, CLASS_ORDINARY_NEGATIVE,
                                CLASS_MATE_PRESENT, CLASS_EXCLUDED)

NEGATIVE_KINDS: frozenset[str] = frozenset({RELATION_R1, RELATION_R0})

_QUERY_KEYS: tuple[str, ...] = ("query", "a", "fragment_a")
_CANDIDATE_KEYS: tuple[str, ...] = ("candidate", "b", "fragment_b")


# --------------------------------------------------------------------------------------
# reading a relation row
# --------------------------------------------------------------------------------------
def _endpoints(row: Mapping[str, Any]) -> tuple[str, str]:
    """``(query, candidate)`` of a directed relation row, whatever spelling it uses."""
    query = next((str(row[k]) for k in _QUERY_KEYS if row.get(k)), "")
    candidate = next((str(row[k]) for k in _CANDIDATE_KEYS if row.get(k)), "")
    return query, candidate


def r2_mates(rows: Iterable[Mapping[str, Any]], *,
             valid_only: bool = True) -> dict[str, set[str]]:
    """``{fragment: {mates}}`` from every ``R2`` row of the table (both directions).

    ``valid_only=True`` (the default) reads a mate only from a row whose measurement is usable,
    which is exactly the set ``synlab.training.batch`` treats as the historical-R2 adjacency.
    """
    mates: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if str(row.get("kind")) != RELATION_R2:
            continue
        if valid_only and not bool(row.get("valid", False)):
            continue
        query, candidate = _endpoints(row)
        if not query or not candidate or query == candidate:
            continue
        mates[query].add(candidate)
        mates[candidate].add(query)
    return {fid: set(values) for fid, values in mates.items()}


def mate_absent_fragments(rows: Iterable[Mapping[str, Any]], **kwargs: Any) -> set[str]:
    """Every fragment named by the table that has **no** confirmed ``R2`` mate in it."""
    rows = list(rows)
    mates = r2_mates(rows, **kwargs)
    fragments: set[str] = set()
    for row in rows:
        query, candidate = _endpoints(row)
        for fid in (query, candidate):
            if fid:
                fragments.add(fid)
    return {fid for fid in fragments if not mates.get(fid)}


def row_class(row: Mapping[str, Any], mates: Mapping[str, set[str]]) -> str:
    """The class of one row under the rule (see the module docstring).

    Recognises both states of a :data:`CLASS_MATE_PRESENT` row: *before* the rule is applied
    (``kind in {R1,R0} and valid and loss_mask`` and the candidate has a mate) and *after* it
    (the same row with ``loss_mask`` cleared and :data:`MATE_PRESENT_REASON` in ``reason``), so
    the class is a property of the pair and not of when it was read.
    """
    query, candidate = _endpoints(row)
    kind = str(row.get("kind", ""))
    valid = bool(row.get("valid", False))
    masked = bool(row.get("loss_mask", False))
    if kind == RELATION_R2 and valid:
        return CLASS_POSITIVE
    if kind in NEGATIVE_KINDS and valid and masked:
        return (CLASS_MATE_PRESENT if mates.get(candidate)
                else CLASS_ORDINARY_NEGATIVE)
    if (kind in NEGATIVE_KINDS and valid and not masked
            and MATE_PRESENT_REASON in str(row.get("reason", "") or "")):
        return CLASS_MATE_PRESENT
    if not query or not candidate:
        return CLASS_EXCLUDED
    return CLASS_EXCLUDED


# --------------------------------------------------------------------------------------
# applying the rule
# --------------------------------------------------------------------------------------
def apply_rule(rows: Sequence[Mapping[str, Any]], *,
               valid_only_mates: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return ``(ruled_rows, report)`` with the mate-absent rule applied to every row.

    The returned rows are copies; the input is never mutated.  Only the *eligibility* of a
    ``CANDIDATE_MATE_PRESENT_NOT_ORDINARY`` row changes: ``loss_mask`` becomes ``False`` (so
    every consumer that derives ``eligible_as_negative := kind in {R1,R0} and valid and
    loss_mask`` -- the frozen rule -- excludes it instead of using it) and ``reason`` gets the
    machine-readable marker :data:`MATE_PRESENT_REASON` appended.  ``kind``, ``valid``,
    ``area_mm2`` and the identities stay exactly as measured.
    """
    rows = [dict(row) for row in rows]
    mates = r2_mates(rows, valid_only=valid_only_mates)
    classes = [row_class(row, mates) for row in rows]
    ordinary_before = sum(1 for row, klass in zip(rows, classes)
                          if klass in (CLASS_ORDINARY_NEGATIVE, CLASS_MATE_PRESENT))

    changed: list[dict[str, Any]] = []
    for row, klass in zip(rows, classes):
        if klass != CLASS_MATE_PRESENT:
            continue
        query, candidate = _endpoints(row)
        before = {"query": query, "candidate": candidate, "kind": str(row.get("kind")),
                  "valid": bool(row.get("valid", False)),
                  "loss_mask": bool(row.get("loss_mask", False)),
                  "reason": str(row.get("reason", "") or "")}
        reason = str(row.get("reason", "") or "")
        if not before["loss_mask"] and MATE_PRESENT_REASON in reason:
            # already ruled by an earlier call: the function is idempotent and this row is not
            # counted as a change again
            continue
        row["loss_mask"] = False
        if MATE_PRESENT_REASON not in reason:
            row["reason"] = (f"{reason} | {MATE_PRESENT_REASON}" if reason
                             else MATE_PRESENT_REASON)
        if "eligible_as_negative" in row:
            # the frozen derivation of the export writer, recomputed from the ruled inputs
            row["eligible_as_negative"] = bool(
                str(row.get("kind")) in NEGATIVE_KINDS
                and row.get("valid", False) and row["loss_mask"])
        changed.append({**before, "after": {"loss_mask": False, "reason": row["reason"]},
                        "class": klass, "candidate_mates": sorted(mates.get(candidate, set()))})

    counts: dict[str, int] = {name: 0 for name in ROW_CLASSES}
    for klass in classes:
        counts[klass] += 1
    ordinary_by_query: dict[str, int] = defaultdict(int)
    blocked_by_query: dict[str, int] = defaultdict(int)
    for row, klass in zip(rows, classes):
        query, _candidate = _endpoints(row)
        if klass == CLASS_ORDINARY_NEGATIVE:
            ordinary_by_query[query] += 1
        elif klass == CLASS_MATE_PRESENT:
            blocked_by_query[query] += 1
    report: dict[str, Any] = {
        "schema": "synlab.relations.mate_absent.v1",
        "version": MATE_ABSENT_RULE_VERSION,
        "rule": ("a candidate may be an ordinary negative only when it has no confirmed R2 mate "
                 "in the pool (mate_absent(candidate)); a candidate that has one is a separate "
                 "class and never enters the ordinary negative set"),
        "rows": len(rows),
        "classes": counts,
        "fragments": len({fid for row in rows for fid in _endpoints(row) if fid}),
        "mate_absent_fragments": sorted(mate_absent_fragments(rows, valid_only=valid_only_mates)),
        "rows_reruled": len(changed),
        "rows_reruled_detail": changed,
        "ordinary_negatives_before": int(ordinary_before),
        "mate_present_candidates_before": int(ordinary_before - counts[CLASS_ORDINARY_NEGATIVE]),
    }
    report["ordinary_negatives_after"] = int(counts[CLASS_ORDINARY_NEGATIVE])
    report["queries_with_ordinary_negative"] = len(ordinary_by_query)
    report["queries_with_blocked_candidate"] = len(blocked_by_query)
    report["ordinary_negatives_by_query"] = dict(sorted(ordinary_by_query.items()))
    report["blocked_candidates_by_query"] = dict(sorted(blocked_by_query.items()))
    return rows, report


# --------------------------------------------------------------------------------------
# the minimal trainable set (query + encodable R2 positive + >= 2 legal negatives)
# --------------------------------------------------------------------------------------
def minimal_trainable_set(rows: Sequence[Mapping[str, Any]], *,
                          encodable: Mapping[str, bool] | None = None,
                          minimum_negatives: int = 2) -> dict[str, Any]:
    """Pick the smallest real (query, positive, negatives) set the rule leaves trainable.

    ``encodable`` is an explicit ``{fragment: bool}`` map (the caller measures it -- e.g.
    ``tools.load_package.encoder_valid`` on the packaged shards); when it is ``None`` every
    fragment counts as encodable and the report says so instead of pretending to have measured
    it.  A positive must be a confirmed ``R2`` row whose **both** endpoints are encodable (the
    rank loss needs query and candidate in the same forward pass), and the negatives are the
    query's ordinary-negative rows whose candidate is encodable.
    """
    rows = list(rows)
    mates = r2_mates(rows)
    measured = encodable is not None
    ok = (lambda fid: bool(encodable.get(fid, False))) if measured else (lambda fid: True)

    positives: dict[str, list[str]] = defaultdict(list)
    negatives: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        query, candidate = _endpoints(row)
        if not query or not candidate or query == candidate:
            continue
        klass = row_class(row, mates)
        if klass == CLASS_POSITIVE and ok(query) and ok(candidate):
            positives[query].append(candidate)
        elif klass == CLASS_ORDINARY_NEGATIVE and ok(candidate) and ok(query):
            negatives[query].append(candidate)

    candidates = sorted(q for q in positives if len(negatives.get(q, [])) >= minimum_negatives)
    chosen = candidates[0] if candidates else None
    payload: dict[str, Any] = {
        "schema": "synlab.relations.minimal_trainable_set.v1",
        "rule_version": MATE_ABSENT_RULE_VERSION,
        "encodability_measured": measured,
        "minimum_negatives": int(minimum_negatives),
        "queries_with_encodable_positive": sorted(positives),
        "queries_with_ordinary_negative": sorted(q for q in negatives if negatives[q]),
        "queries_trainable": candidates,
        "ok": chosen is not None,
    }
    if chosen is None:
        payload["reason"] = (
            "no query carries both an encodable confirmed R2 positive and >= "
            f"{minimum_negatives} ordinary negatives (mate-absent candidate, encodable both "
            "sides); the measured counts above say which half is missing")
        payload["query"] = None
        payload["positives"] = []
        payload["negatives"] = []
        return payload
    negatives_sorted = sorted(negatives[chosen])
    payload["query"] = chosen
    payload["positives"] = sorted(positives[chosen])
    payload["negatives"] = negatives_sorted
    payload["positive_used"] = payload["positives"][0]
    payload["negatives_used"] = negatives_sorted[: int(minimum_negatives)]
    payload["all_three_observed"] = bool(
        measured and ok(chosen) and all(ok(f) for f in payload["positives"])
        and all(ok(f) for f in payload["negatives_used"]))
    return payload


def class_count_table(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Class counts + the mate table, for a report (no rows returned)."""
    rows = list(rows)
    mates = r2_mates(rows)
    counts: dict[str, int] = {name: 0 for name in ROW_CLASSES}
    per_kind: dict[str, dict[str, int]] = {}
    for row in rows:
        klass = row_class(row, mates)
        counts[klass] += 1
        kind = str(row.get("kind", ""))
        per_kind.setdefault(kind, {})
        per_kind[kind][klass] = per_kind[kind].get(klass, 0) + 1
    return {
        "schema": "synlab.relations.negative_class_table.v1",
        "rule_version": MATE_ABSENT_RULE_VERSION,
        "rows": len(rows), "classes": counts, "classes_by_kind": per_kind,
        "r2_edges": int(sum(len(v) for v in mates.values()) // 2),
        "fragments_with_mate": sum(1 for v in mates.values() if v),
        "fragments_mate_absent": len(mate_absent_fragments(rows)),
        "mate_absent_fragments": sorted(mate_absent_fragments(rows)),
        "mates": {fid: sorted(values) for fid, values in sorted(mates.items())},
    }


def ordinary_negative_pairs(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """Every ``(query, candidate)`` the rule leaves in the ordinary negative class."""
    rows = list(rows)
    mates = r2_mates(rows)
    out: list[tuple[str, str]] = []
    for row in rows:
        if row_class(row, mates) != CLASS_ORDINARY_NEGATIVE:
            continue
        query, candidate = _endpoints(row)
        out.append((query, candidate))
    return out


def is_mate_absent(fragment_id: str, rows: Sequence[Mapping[str, Any]]) -> bool:
    """``True`` when the fragment has no confirmed ``R2`` mate in ``rows``."""
    return not r2_mates(rows).get(str(fragment_id))


def observed_fragments_from_payloads(payloads: Mapping[str, Mapping[str, Any]]) -> dict[str, bool]:
    """Encodability of every fragment from packaged/loader payloads (real arrays only).

    Mirrors ``tools.load_package.encoder_valid`` (the encoder's own ``z_valid``): the fragment
    can enter a forward pass when it has any valid global view, or valid scaled geometry, or any
    valid token.  A fragment with no observation at all is ``False`` -- never a zero-filled
    stand-in.
    """
    out: dict[str, bool] = {}
    for fid, payload in payloads.items():
        global_valid = np.asarray(payload["global_valid"]).astype(bool)
        token_valid = np.asarray(payload["token_valid"]).astype(bool)
        point_valid = np.asarray(payload["point_valid"]).astype(bool)
        normal_valid = np.asarray(payload["normal_valid"]).astype(bool)
        tokens_total = int(np.asarray(payload.get("tokens_total", 0)).reshape(-1)[0]
                           if np.asarray(payload.get("tokens_total", 0)).size else 0)
        scale_valid = bool(np.asarray(payload.get("scale_valid", False)).any())
        rgb_gate = bool(global_valid.any())
        geo_gate = bool(((point_valid | normal_valid) & scale_valid).any())
        tok_gate = bool(token_valid.any()) and tokens_total > 0
        out[str(fid)] = bool(rgb_gate or geo_gate or tok_gate)
    return out


__all__ = [
    "MATE_ABSENT_RULE_VERSION", "MATE_PRESENT_REASON", "MATE_PRESENT_EXCLUSION_REASON",
    "ROW_CLASSES", "NEGATIVE_KINDS",
    "CLASS_POSITIVE", "CLASS_ORDINARY_NEGATIVE", "CLASS_MATE_PRESENT", "CLASS_EXCLUDED",
    "r2_mates", "mate_absent_fragments", "row_class", "apply_rule", "class_count_table",
    "minimal_trainable_set", "ordinary_negative_pairs", "is_mate_absent",
    "observed_fragments_from_payloads",
]
