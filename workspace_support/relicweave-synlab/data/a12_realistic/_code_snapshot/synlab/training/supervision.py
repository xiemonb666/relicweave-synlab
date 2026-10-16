"""Per-task supervision accounting: ``n_valid`` / ``n_allowed`` / *which condition* rejected it.

The five task losses already report ``n_valid`` (what the loss really consumed) and a skip
reason, but that is not enough to answer "does this package have supervision for task X?":

* a task can be skipped because the **labels do not exist** (nobody produced them) or because the
  labels exist and are **masked away** (the pair cannot be encoded) -- two different facts with
  two different fixes;
* the mask that removes them is a conjunction, so "0 allowed" hides *which* conjunct was False.

This module decomposes the masks the trainer really applies and records, per task,

``n_valid``
    label rows that exist and are valid *before* encodability is considered;
``n_allowed``
    rows that survive every mask the loss applies (that is what the loss's own ``n_valid`` is);
``blocked_by``
    the measured conditions that removed the difference, most-binding first;
``structural``
    ``{"applicable": False, "reason", "evidence", "unlock_condition"}`` when the *plan and the
    package* cannot produce that label at all -- the honest marker that lets a reader (and
    ``tests/a12/training``) tell "structurally not applicable yet" from "silently zero".

Everything here is numpy and read-only: it never changes a mask the loss uses, it only measures
the same masks.  Plan 30.12 invariants are re-checked in :func:`plan_30_12_evidence`.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from .adapter import (
    CONTRADICTION_MISSING,
    RELATION_R1_CODE,
    RELATION_R2_CODE,
    RELATION_UNKNOWN_CODE,
)

#: same order the multi-task combiner reports in
TASK_ORDER = ("rank", "view", "correspondence", "quality", "contradiction")


def _b(value: Any) -> np.ndarray:
    return np.asarray(value, dtype=bool)


def pair_mask_conjuncts(batch: Any, z_valid: np.ndarray) -> dict[str, Any]:
    """Decompose ``allowed = z_valid[q] & z_valid[c] & pair_valid`` into measured counts.

    This is the exact mask ``Trainer.compute_losses`` builds
    (``synlab/training/trainer.py``: ``allowed = z_valid[q_idx] & z_valid[c_idx] & pair_valid``);
    the decomposition exists so a report can name the conjunct that rejected a pair instead of
    printing a bare zero.
    """
    pair = np.asarray(batch.pair_index, dtype=np.int64)
    pair_valid = _b(batch.pair_valid)
    z = _b(z_valid)
    q_idx, c_idx = pair[:, :, 0], pair[:, :, 1]
    q_ok = z[q_idx]
    c_ok = z[c_idx]
    allowed = q_ok & c_ok & pair_valid
    ids = list(batch.features.fragment_ids)
    return {
        "pair_valid": int(pair_valid.sum()),
        "z_valid_queries": int(q_ok.sum()),
        "z_valid_candidates": int(c_ok.sum()),
        "allowed": int(allowed.sum()),
        "rejected_by": {
            "pair_valid==False": int((~pair_valid).sum()),
            "z_valid[query]==False": int((~q_ok & pair_valid).sum()),
            "z_valid[candidate]==False": int((~c_ok & pair_valid).sum()),
        },
        "allowed_mask": allowed,
        "unencodable_pairs": [
            {"query": ids[int(q_idx[i, j])], "candidate": ids[int(c_idx[i, j])],
             "z_valid_query": bool(q_ok[i, j]), "z_valid_candidate": bool(c_ok[i, j]),
             "pair_valid": bool(pair_valid[i, j])}
            for i in range(pair.shape[0]) for j in range(pair.shape[1])
            if pair_valid[i, j] and not allowed[i, j]
        ],
    }


def _structural(reason: str, evidence: Mapping[str, Any],
                unlock: Sequence[str]) -> dict[str, Any]:
    return {"applicable": False, "reason": reason, "evidence": dict(evidence),
            "unlock_condition": list(unlock)}


def supervision_accounting(batch: Any, *, z_valid: np.ndarray,
                           label_report: Mapping[str, Any] | None = None
                           ) -> dict[str, Any]:
    """Per-task ``n_valid`` / ``n_allowed`` / ``blocked_by`` / ``structural`` on a real batch."""
    labels = dict(label_report or {})
    quality_labels = dict(labels.get("quality") or {})
    corr_labels = dict(labels.get("correspondence") or {})
    pair = pair_mask_conjuncts(batch, z_valid)
    allowed = pair["allowed_mask"]

    pos = _b(batch.pos_mask)
    neg = _b(batch.neg_mask)
    label_valid = _b(batch.label_pair_valid)
    relation = np.asarray(batch.labels_relation, dtype=np.int64)
    cont = np.asarray(batch.contradiction, dtype=np.int64)
    cont_valid = _b(batch.contradiction_valid)
    q_valid = _b(batch.quality_target_valid)
    global_valid = _b(batch.features.global_valid)
    token_valid = _b(batch.features.token_valid)
    corr_w = np.asarray(batch.corr_weight, dtype=np.float64)

    tasks: dict[str, Any] = {}

    # ---- view (per fragment x view, no pair mask) -------------------------------------
    views_per_fragment = global_valid.sum(axis=1)
    view_anchors = int(sum(int(k) for k in views_per_fragment.tolist() if int(k) >= 2))
    tasks["view"] = {
        "n_valid": int(global_valid.sum()),
        "n_allowed": view_anchors,
        "blocked_by": [] if view_anchors else ["fewer_than_two_valid_views_for_every_fragment"],
        "structural": None,
        "evidence": {"views_per_fragment": views_per_fragment.tolist(),
                     "fragments_with_two_or_more_views": int((views_per_fragment >= 2).sum())},
    }

    # ---- rank (positives + legal negatives, both masked by `allowed`) -------------------
    n_pos, n_neg = int(pos.sum()), int(neg.sum())
    pos_allowed, neg_allowed = int((pos & allowed).sum()), int((neg & allowed).sum())
    rank_blocked: list[str] = []
    rank_structural = None
    if n_neg == 0:
        rank_blocked.append("no_legal_negative_in_the_exported_relation_table")
    elif neg_allowed == 0:
        rank_blocked.append("every_legal_negative_pair_is_unencodable")
    if n_pos and pos_allowed == 0:
        rank_blocked.append("every_positive_pair_is_unencodable")
    if n_pos == 0:
        rank_blocked.append("no_confirmed_R2_positive_in_the_batch")
    if pos_allowed == 0 or neg_allowed == 0:
        rank_structural = _structural(
            rank_blocked[0] if rank_blocked else "no_rank_supervision",
            {"positives_label_valid": n_pos, "positives_allowed": pos_allowed,
             "negatives_label_valid": n_neg, "negatives_allowed": neg_allowed,
             "relation_kinds": {str(int(k)): int(v) for k, v in
                                zip(*np.unique(relation[_b(batch.pair_valid)],
                                               return_counts=True))},
             "positives_rejected_by": {k: int(np.count_nonzero(pos & ~allowed))
                                       for k in ("z_valid[candidate]==False",)},
             "evidence": "synlab/training/trainer.py allowed = z_valid[q] & z_valid[c] & pair_valid"},
            ["produce confirmed R1/R0 rows with valid=true and loss_mask=true between two "
             "fragments that both carry an observation (>=1 valid token or >=1 valid view)",
             "observe both sides of an R2 pair so a positive pair can be encoded"],
        )
    tasks["rank"] = {
        "n_valid": n_pos + n_neg,
        "n_allowed": pos_allowed + neg_allowed,
        "n_valid_positives": n_pos, "n_valid_negatives": n_neg,
        "n_allowed_positives": pos_allowed, "n_allowed_negatives": neg_allowed,
        "blocked_by": rank_blocked,
        "structural": rank_structural,
        "evidence": {"effective_queries": int(batch.effective_query_count())},
    }

    # ---- correspondence (label rows -> token-space W, then the same `allowed` mask) -----
    corr_entries = int(np.count_nonzero(corr_w > 0))
    corr_allowed = int(np.count_nonzero((corr_w > 0) & allowed[..., None]))
    corr_blocked = list(corr_labels.get("blocked_by") or [])
    corr_structural = None
    if corr_allowed == 0:
        if corr_labels.get("n_label_samples_in_package", 0) == 0 and not corr_blocked:
            corr_blocked = ["no_correspondence_label_in_the_batch"]
        corr_structural = _structural(
            corr_blocked[0] if corr_blocked else "no_correspondence_supervision",
            {"batch_weight_entries": corr_entries,
             "label_samples_in_package": int(corr_labels.get("n_label_samples_in_package", 0)),
             "pairs_in_batch_with_labels": int(corr_labels.get("pairs_in_batch_with_labels", 0)),
             "pairs_with_both_sides_observable": int(
                 corr_labels.get("pairs_with_both_sides_observable", 0)),
             "pairs_with_one_side_observable": int(
                 corr_labels.get("pairs_with_one_side_observable", 0)),
             "token_mapping_available": bool(corr_labels.get("token_mapping_available", False)),
             "unobserved_fragments": list(
                 (corr_labels.get("reference_geometry_mm") or {}).get("unobserved_fragments", []))},
            list(corr_labels.get("unlock_condition") or
                 ["export the release's correspondence labels into the package"]),
        )
    tasks["correspondence"] = {
        "n_valid": int(corr_labels.get("n_label_samples_in_package", corr_entries)),
        "n_allowed": corr_allowed,
        "blocked_by": corr_blocked,
        "structural": corr_structural,
        "evidence": {"batch_weight_entries": corr_entries,
                     "batch_row_weight_sum": float(corr_w.sum()),
                     "rows_with_valid_token_evidence": int(
                         (token_valid.sum(axis=1) > 0).sum())},
    }

    # ---- quality (per fragment; no pair mask) ------------------------------------------
    quality_blocked: list[str] = []
    quality_structural = None
    if int(q_valid.sum()) == 0:
        quality_blocked.append("no_valid_quality_target")
        quality_structural = _structural(
            "no_label_side_quality_measurement_in_the_package",
            {"quality_target_valid_sum": 0,
             "per_fragment": quality_labels.get("per_fragment", {}),
             "measured_fragments_in_package": int(
                 quality_labels.get("n_measured_fragments_in_package", 0))},
            ["export a label-side observability/quality measurement for at least one fragment "
             "(the release's visible layer carries one per fragment x view)",
             "attach the GT_ORACLE comparison block "
             "(synlab.observe.quality.attach_oracle_comparison) if the target should be a "
             "same-channel oracle instead of the observability anchor"],
        )
    tasks["quality"] = {
        "n_valid": int(q_valid.sum()),
        "n_allowed": int(q_valid.sum()),
        "blocked_by": quality_blocked,
        "structural": quality_structural,
        "evidence": {"channel": str(quality_labels.get("channel", "")),
                     "n_fragments": int(q_valid.shape[0]) if q_valid.ndim else 0,
                     "source_kind": str(quality_labels.get("source_kind", "")),
                     "missing_is_not_a_zero_label": True},
    }

    # ---- contradiction (labels exist per pair; masked by the same `allowed`) ------------
    cont_allowed = int((cont_valid & allowed).sum())
    cont_blocked: list[str] = []
    cont_structural = None
    if int(cont_valid.sum()) == 0:
        cont_blocked.append("no_contradiction_label")
    elif cont_allowed == 0:
        cont_blocked.append("no_encodable_contradiction_pair")
    labels_present = cont[cont_valid]
    if cont_allowed == 0:
        cont_structural = _structural(
            cont_blocked[0] if cont_blocked else "no_contradiction_supervision",
            {"labels_valid": int(cont_valid.sum()), "labels_allowed": cont_allowed,
             "label_histogram": {str(int(k)): int(v) for k, v in
                                 zip(*np.unique(labels_present, return_counts=True))}
             if labels_present.size else {},
             "classes_present": int(np.unique(labels_present).size) if labels_present.size else 0,
             "missing_label_code": int(CONTRADICTION_MISSING)},
            ["observe both fragments of a labelled pair so its pair score can be computed "
             "(contradiction is supervised on the pair logits, which needs both embeddings)",
             "produce a pair whose relation evidence contradicts (the exported labels are all "
             "class 1 'compatible' today: R1/R2 are compatible by definition)"],
        )
    tasks["contradiction"] = {
        "n_valid": int(cont_valid.sum()),
        "n_allowed": cont_allowed,
        "blocked_by": cont_blocked,
        "structural": cont_structural,
        "evidence": {"label_histogram": {str(int(k)): int(v) for k, v in
                                        zip(*np.unique(labels_present, return_counts=True))}
                     if labels_present.size else {},
                     "classes_present": int(np.unique(labels_present).size)
                     if labels_present.size else 0},
    }

    # ``n_valid`` here means "label rows that exist and are valid" (the number the *task report*
    # calls ``n_valid_labels``); ``n_allowed`` is what the loss can consume.  Both names are
    # exposed so a reader never has to guess which of the two a number is.
    for entry in tasks.values():
        entry["n_valid_labels"] = int(entry["n_valid"])

    return {
        "tasks": tasks,
        "pair_mask": {k: v for k, v in pair.items() if k != "allowed_mask"},
        "tasks_with_supervision": sorted(t for t, v in tasks.items() if v["n_allowed"] > 0),
        "tasks_structurally_blocked": sorted(t for t, v in tasks.items()
                                             if v["n_allowed"] == 0 and v["structural"]),
        "tasks_without_explanation": sorted(t for t, v in tasks.items()
                                            if v["n_allowed"] == 0 and not v["structural"]),
        "plan_30_12": plan_30_12_evidence(batch),
    }


def plan_30_12_evidence(batch: Any) -> dict[str, Any]:
    """Re-measure the plan 30.12 invariants on the batch that is about to be trained.

    ``UNKNOWN`` must never be supervised, a label that is not confirmed must never be supervised,
    and a slot whose validity mask is False must not carry a value that could be mistaken for a
    label.  Each entry is a count that must be 0; they are measured here so a report states them
    instead of assuming them.
    """
    relation = np.asarray(batch.labels_relation, dtype=np.int64)
    supervised = _b(batch.pos_mask) | _b(batch.neg_mask)
    cont = np.asarray(batch.contradiction, dtype=np.int64)
    cont_valid = _b(batch.contradiction_valid)
    q_target = np.asarray(batch.quality_target, dtype=np.float64)
    q_valid = _b(batch.quality_target_valid)
    return {
        "unknown_rows_inside_supervision": int(
            (supervised & (relation == RELATION_UNKNOWN_CODE)).sum()),
        "unconfirmed_rows_inside_supervision": int((supervised & ~_b(batch.label_pair_valid)).sum()),
        "non_r2_relation_inside_pos_mask": int(
            (_b(batch.pos_mask) & (relation != RELATION_R2_CODE)).sum()),
        "r2_rows_inside_neg_mask": int((_b(batch.neg_mask) & (relation == RELATION_R2_CODE)).sum()),
        "unknown_rows_with_a_contradiction_label": int(
            (cont_valid & (relation == RELATION_UNKNOWN_CODE)).sum()),
        "missing_contradiction_rows_marked_valid": int(
            (cont_valid & (cont == CONTRADICTION_MISSING)).sum()),
        "invalid_quality_slots_with_a_nonzero_value": int(
            ((~q_valid) & (q_target != 0.0)).sum()),
        "r1_fallback_rows": int(_b(batch.r1_fallback_used).sum()),
        "r1_code_present": bool((relation == RELATION_R1_CODE).any()),
        "relation_codes_supervised": sorted({int(c) for c in relation[supervised].tolist()}),
    }


__all__ = ["TASK_ORDER", "pair_mask_conjuncts", "supervision_accounting",
           "plan_30_12_evidence"]
