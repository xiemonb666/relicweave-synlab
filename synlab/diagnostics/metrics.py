"""Frozen retrieval metrics and the failure/NA denominators (plan 19.1, 30.14).

Definitions (q = query, G = frozen gallery excluding q, ``N_G(q)`` = all in-gallery
historical true neighbours, ``C_M`` = first-stage pool, ``T_K`` = refined TopK)::

    Hit@K         = 1[T_K n N_G(q) != empty]
    CovRecall@K   = |T_K n N_G(q)| / |N_G(q)|
    any@M         = 1[C_M n N_G(q) != empty]
    PoolCov@M     = |C_M n N_G(q)| / |N_G(q)|
    ConditionalCov@K = |T_K n C_M n N_G(q)| / |C_M n N_G(q)|
    EffectiveCov@K= |A(q) n N_G(q)| / |N_G(q)|, A(q) = accepted set
    EffectiveHit@K= 1[that intersection is non-empty]

Honesty rules implemented here
------------------------------
* a query with **no** in-gallery neighbour has ``Hit/Cov = NA`` (``None``, never ``0``) but
  stays in the risk denominator;
* a frozen query *with* neighbours that fails, times out or has no legal input keeps
  ``EffectiveHit = EffectiveCov = 0`` and **remains in the primary denominator** -- it may
  never drop out by being written as NA;
* rejection is reported with the original ranking, the acceptance rate and the post-rejection
  effective metrics; a present query that was rejected has an effective recall of 0;
* duplicate candidate identities collapse to one candidate; the query itself is never a
  candidate;
* ``ConditionalCov@K`` has the in-pool positive count as denominator: zero in-pool positives is
  NA and is counted as ``pool_miss``. The old two-argument ``conditional_cov`` remains a legacy
  pool-presence census and must not be used to assess retrieval success.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

import numpy as np

#: Query statuses of the frozen roster (plan 30.14).
STATUS_OK = "OK"
STATUS_REJECTED = "REJECTED"
STATUS_INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_RECONSTRUCTION_FAILED = "RECONSTRUCTION_FAILED"
STATUS_NO_CANDIDATE = "NO_CANDIDATE"
STATUS_NA_NOT_APPLICABLE = "NA_NOT_APPLICABLE"

FAILURE_STATUSES = (STATUS_INPUT_UNAVAILABLE, STATUS_TIMEOUT, STATUS_RECONSTRUCTION_FAILED,
                    STATUS_NO_CANDIDATE)

DEFAULT_TOP_K: tuple[int, ...] = (1, 5, 10, 20)


# --------------------------------------------------------------------------------------
# candidate hygiene
# --------------------------------------------------------------------------------------
def _as_ids(values: Iterable[Any] | None) -> list[str]:
    return [str(v) for v in (values or [])]


def dedupe_candidates(candidates: Iterable[Any], *, query_id: str | None = None
                      ) -> tuple[list[str], dict[str, Any]]:
    """One identity per candidate; the query itself is never a candidate (plan 30.10)."""
    seen: set[str] = set()
    unique: list[str] = []
    duplicates: list[str] = []
    self_seen = 0
    for value in candidates:
        cid = str(value)
        if query_id is not None and cid == str(query_id):
            self_seen += 1
            continue
        if cid in seen:
            duplicates.append(cid)
            continue
        seen.add(cid)
        unique.append(cid)
    return unique, {"duplicates_removed": len(duplicates), "duplicate_ids": sorted(set(duplicates)),
                    "self_candidates_removed": self_seen}


def intersect(ranked: Iterable[Any], neighbours: Iterable[Any]) -> list[str]:
    """``ranked n neighbours`` preserving the ranked order (ranked is authoritative)."""
    neighbours_set = {str(n) for n in neighbours}
    out: list[str] = []
    seen: set[str] = set()
    for value in ranked:
        cid = str(value)
        if cid in neighbours_set and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def _na_if_absent(neighbours: Sequence[str]) -> bool:
    return len(neighbours) == 0


# --------------------------------------------------------------------------------------
# per-K metrics
# --------------------------------------------------------------------------------------
def hit_at_k(ranked: Iterable[Any], neighbours: Iterable[Any]) -> float | None:
    """``1[T_K n N_G != empty]``; ``None`` (NA) when the query has no in-gallery neighbour."""
    neighbour_list = _as_ids(neighbours)
    if _na_if_absent(neighbour_list):
        return None
    return 1.0 if intersect(ranked, neighbour_list) else 0.0


def cov_recall_at_k(ranked: Iterable[Any], neighbours: Iterable[Any]) -> float | None:
    """``|T_K n N_G| / |N_G|``; ``None`` (NA) when ``|N_G| == 0``."""
    neighbour_list = _as_ids(neighbours)
    if _na_if_absent(neighbour_list):
        return None
    return len(intersect(ranked, neighbour_list)) / float(len(neighbour_list))


def any_at_m(first_stage: Iterable[Any], neighbours: Iterable[Any]) -> float | None:
    neighbour_list = _as_ids(neighbours)
    if _na_if_absent(neighbour_list):
        return None
    return 1.0 if intersect(first_stage, neighbour_list) else 0.0


def pool_cov_at_m(first_stage: Iterable[Any], neighbours: Iterable[Any]) -> float | None:
    neighbour_list = _as_ids(neighbours)
    if _na_if_absent(neighbour_list):
        return None
    return len(intersect(first_stage, neighbour_list)) / float(len(neighbour_list))


def conditional_cov(first_stage: Iterable[Any], neighbours: Iterable[Any]) -> float | None:
    """Legacy pool-presence census; use :func:`conditional_cov_at_k` for retrieval quality.

    The historical two-argument interface cannot distinguish the first-stage pool from its
    refined TopK. It therefore returns 1.0 whenever the pool contains any positive and None
    otherwise. Kept only for compatibility with old diagnostics; this value is not a retrieval
    success metric.
    """
    neighbour_list = _as_ids(neighbours)
    in_pool = intersect(first_stage, neighbour_list)
    if not in_pool:
        return None
    return len(in_pool) / float(len(in_pool))


def conditional_cov_at_k(top_k: Iterable[Any], first_stage: Iterable[Any],
                         neighbours: Iterable[Any]) -> float | None:
    """Refined coverage of the true positives admitted by the first-stage pool.

    ``C_M`` is ``first_stage``, ``T_K`` is ``top_k``, and ``N_G`` is the full historical R2
    set. The denominator is ``|C_M ∩ N_G|``; the numerator is
    ``|T_K ∩ C_M ∩ N_G|``. A zero denominator is NA and should be paired with ``pool_miss``.
    Candidate IDs are deduplicated by identity through :func:`intersect`.
    """
    in_pool = intersect(first_stage, _as_ids(neighbours))
    if not in_pool:
        return None
    return len(intersect(top_k, in_pool)) / float(len(in_pool))


def pool_miss(first_stage: Iterable[Any], neighbours: Iterable[Any]) -> bool:
    """True when the query has neighbours but the first-stage pool found none of them."""
    neighbour_list = _as_ids(neighbours)
    return bool(neighbour_list) and not intersect(first_stage, neighbour_list)


# --------------------------------------------------------------------------------------
# acceptance set and effective metrics
# --------------------------------------------------------------------------------------
def accept_set(candidates: Iterable[Any], scores: Mapping[str, float], *,
               threshold: float | None = None,
               observed_valid: Mapping[str, bool] | None = None,
               keep_top: int | None = None) -> list[str]:
    """``A(q) = {c in TopK : calibrated_score >= threshold and observed_valid(c)}``.

    ``observed_valid`` may only be produced by legal observation checks (never by a GT
    label).  Multiple positives may be accepted simultaneously: the set is not forced to be
    mutually exclusive (plan 30.13).
    """
    ordered, _ = dedupe_candidates(candidates)
    accepted: list[str] = []
    for cid in ordered:
        if threshold is not None and float(scores.get(cid, float("-inf"))) < float(threshold):
            continue
        if observed_valid is not None and not bool(observed_valid.get(cid, False)):
            continue
        accepted.append(cid)
        if keep_top is not None and len(accepted) >= int(keep_top):
            break
    return accepted


def effective_hit_at_k(accepted: Iterable[Any], neighbours: Iterable[Any]) -> float | None:
    """``1[A n N_G != empty]``; NA for a query without in-gallery neighbours."""
    neighbour_list = _as_ids(neighbours)
    if _na_if_absent(neighbour_list):
        return None
    return 1.0 if intersect(accepted, neighbour_list) else 0.0


def effective_cov_at_k(accepted: Iterable[Any], neighbours: Iterable[Any]) -> float | None:
    """``|A n N_G| / |N_G|``; the denominator is the *full* historical neighbour set."""
    neighbour_list = _as_ids(neighbours)
    if _na_if_absent(neighbour_list):
        return None
    return len(intersect(accepted, neighbour_list)) / float(len(neighbour_list))


def risk_events(neighbours: Iterable[Any], accepted: Iterable[Any]) -> dict[str, Any]:
    """The two frozen risk events of plan 30.14.

    ``absent_false_accept = 1[|N_G| == 0 and |A| > 0]``;
    ``present_wrong_accept = 1[|N_G| > 0 and A \\ N_G != empty]`` (a query that also found its
    true mate but additionally proposed an R1/R0 candidate still counts).
    """
    neighbour_list = _as_ids(neighbours)
    accepted_list, hygiene = dedupe_candidates(accepted)
    wrong = [c for c in accepted_list if c not in set(neighbour_list)]
    absent = len(neighbour_list) == 0
    return {
        "absent_false_accept": int(absent and len(accepted_list) > 0),
        "present_wrong_accept": int((not absent) and bool(wrong)),
        "n_neighbours": len(neighbour_list),
        "n_accepted": len(accepted_list),
        "n_wrong_accepted": len(wrong),
        "wrong_accepted": wrong,
        "absent_denominator": int(absent),
        "present_denominator": int(not absent),
        "duplicates_removed": hygiene["duplicates_removed"],
    }


# --------------------------------------------------------------------------------------
# one roster row
# --------------------------------------------------------------------------------------
def query_metrics(*, query_id: str, neighbours: Sequence[str], gallery_ids: Sequence[str] = (),
                  first_stage: Sequence[str] | None = None,
                  ranked: Sequence[str] | None = None, top_k: Sequence[int] = DEFAULT_TOP_K,
                  accepted: Sequence[str] | None = None, status: str = STATUS_OK,
                  lineage_cluster: str = "", failure_code: str | None = None,
                  seconds: float | None = None, cost: float | None = None,
                  observed_valid: Mapping[str, bool] | None = None,
                  unencodable_candidates: Sequence[str] = (),
                  input_hash: str = "", gallery_hash: str = "") -> dict[str, Any]:
    """One frozen-roster row: raw ranking, pool, NA flags, effective metrics and risk."""
    top_k = tuple(sorted({int(k) for k in top_k}))
    neighbour_list = _as_ids(neighbours)
    query = str(query_id)
    candidate_source = ranked if ranked is not None else first_stage
    ordered, hygiene = dedupe_candidates(candidate_source or [], query_id=query)
    stage, stage_hygiene = dedupe_candidates(first_stage if first_stage is not None else ordered,
                                             query_id=query)
    mate_present = bool(neighbour_list)
    failed = status in FAILURE_STATUSES
    rejected = status == STATUS_REJECTED
    in_present_denominator = mate_present                     # frozen: failures stay inside
    in_absent_denominator = not mate_present
    # A query whose original ranking was never produced (timeout / no input / NA) reports
    # Hit/Cov = NA, not 0 (plan 30.14); a produced but empty ranking is a real 0.
    rank_produced = bool(ordered) or status in (STATUS_OK, STATUS_REJECTED,
                                                STATUS_NO_CANDIDATE)

    row: dict[str, Any] = {
        "query_id": query,
        "lineage_cluster": str(lineage_cluster),
        "status": status,
        "failure_code": failure_code,
        "mate_present": mate_present,
        "rank_produced": rank_produced,
        "n_historical_neighbours": len(neighbour_list),
        "historical_neighbours": list(neighbour_list),
        "gallery_size": len(gallery_ids),
        "input_hash": input_hash,
        "gallery_hash": gallery_hash,
        "rank_order": ordered,
        "first_stage": stage,
        "duplicates_removed": hygiene["duplicates_removed"] + stage_hygiene["duplicates_removed"],
        "self_candidates_removed": (hygiene["self_candidates_removed"]
                                    + stage_hygiene["self_candidates_removed"]),
        "unencodable_candidates": sorted({str(c) for c in unencodable_candidates}),
        "seconds": seconds,
        "cost": cost,
        "in_present_denominator": in_present_denominator,
        "in_absent_denominator": in_absent_denominator,
        "in_frozen_denominator": True,
        "primary_end_to_end_failed": bool(mate_present and (failed or rejected)),
        "hit_na": not mate_present,
        "pool_cov_na": not mate_present,
        "conditional_cov_na": pool_miss(stage, neighbour_list),
        "conditional_cov_semantics_version": "conditional_cov_at_k_v2",
    }
    row["pool_cov"] = pool_cov_at_m(stage, neighbour_list)
    row["any_at_m"] = any_at_m(stage, neighbour_list)
    row["conditional_cov_legacy_pool_census"] = conditional_cov(stage, neighbour_list)
    row["pool_miss"] = bool(pool_miss(stage, neighbour_list))
    row["in_pool_positives"] = len(intersect(stage, neighbour_list))

    for k in sorted({int(k) for k in top_k}):
        top = ordered[:k]
        if mate_present and not rank_produced:
            hit, cov = None, None
        else:
            hit = hit_at_k(top, neighbour_list)
            cov = cov_recall_at_k(top, neighbour_list)
        row[f"hit@{k}"] = hit
        row[f"cov@{k}"] = cov
        row[f"topk_na@{k}"] = hit is None
        row[f"conditional_cov@{k}"] = conditional_cov_at_k(top, stage, neighbour_list)
    max_k = max((int(k) for k in top_k), default=0)
    row["conditional_cov"] = (row.get(f"conditional_cov@{max_k}") if max_k
                              else None)
    max_k = max((int(k) for k in top_k), default=0)
    top_ids = ordered[:max_k] if max_k else ordered
    if accepted is None:
        accepted_ids = list(top_ids) if (status == STATUS_OK and not failed) else []
    else:
        accepted_ids, accept_hygiene = dedupe_candidates(accepted, query_id=query)
        row["duplicates_removed"] += accept_hygiene["duplicates_removed"]
    row["accepted"] = list(accepted_ids)
    row["acceptance_rate"] = (len(accepted_ids) / float(len(top_ids))) if top_ids else 0.0
    row["accepted_any"] = bool(accepted_ids)
    row["all_rejected"] = (bool(top_ids) and not accepted_ids and not failed)

    for k in sorted({int(k) for k in top_k}):
        k_accepted = [c for c in accepted_ids if c in set(ordered[:k])]
        if mate_present and (failed or rejected):
            eff_hit, eff_cov = 0.0, 0.0            # frozen: failures keep 0, never NA
        else:
            eff_hit = effective_hit_at_k(k_accepted, neighbour_list)
            eff_cov = effective_cov_at_k(k_accepted, neighbour_list)
        row[f"effective_hit@{k}"] = eff_hit
        row[f"effective_cov@{k}"] = eff_cov
    events = risk_events(neighbour_list, accepted_ids)
    row["risk"] = events
    row["absent_false_accept"] = events["absent_false_accept"]
    row["present_wrong_accept"] = events["present_wrong_accept"]
    row["observed_valid_rejections"] = int(
        sum(1 for c in top_ids if observed_valid is not None and not observed_valid.get(c, False)))
    return row


# --------------------------------------------------------------------------------------
# aggregates
# --------------------------------------------------------------------------------------
def _mean(values: Sequence[Any]) -> float | None:
    finite = [float(v) for v in values if v is not None and np.isfinite(float(v))]
    if not finite:
        return None
    return float(np.mean(finite))


def _count_na(values: Sequence[Any]) -> int:
    return int(sum(1 for v in values if v is None
                   or (isinstance(v, float) and not np.isfinite(v))))


def aggregate_metrics(rows: Sequence[Mapping[str, Any]],
                      top_k: Sequence[int] = DEFAULT_TOP_K) -> dict[str, Any]:
    """Aggregate roster rows with the **frozen** denominators of plan 30.14."""
    rows = list(rows)
    top_k = tuple(sorted({int(k) for k in top_k}))
    present = [r for r in rows if r.get("mate_present")]
    absent = [r for r in rows if not r.get("mate_present")]
    failures = [r for r in rows if r.get("status") in FAILURE_STATUSES]
    rejected = [r for r in rows if r.get("status") == STATUS_REJECTED]
    completed_present = [r for r in present
                         if r.get("status") == STATUS_OK and r not in failures]

    summary: dict[str, Any] = {
        "queries_total": len(rows),
        "frozen_denominator": len(rows),
        "present_denominator": len(present),
        "absent_denominator": len(absent),
        "completed_present": len(completed_present),
        "failures": len(failures),
        "rejections": len(rejected),
        "failure_counts": _failure_counts(rows),
        "mate_absent_queries": len(absent),
        "acceptance_rate": _mean([r.get("acceptance_rate", 0.0) for r in present]),
        "all_rejected_present": int(sum(1 for r in present if r.get("all_rejected"))),
        "pool_miss": int(sum(1 for r in rows if r.get("pool_miss"))),
        "duplicates_removed": int(sum(int(r.get("duplicates_removed", 0)) for r in rows)),
        "self_candidates_removed": int(sum(int(r.get("self_candidates_removed", 0)) for r in rows)),
        "seconds_total": float(sum(float(r.get("seconds") or 0.0) for r in rows)),
        "cost_total": float(sum(float(r.get("cost") or 0.0) for r in rows)),
    }
    for k in sorted({int(k) for k in top_k}):
        hit_values = [r.get(f"hit@{k}") for r in rows]
        cov_values = [r.get(f"cov@{k}") for r in rows]
        eff_hit_present = [r.get(f"effective_hit@{k}") for r in present]
        eff_cov_present = [r.get(f"effective_cov@{k}") for r in present]
        eff_hit_completed = [r.get(f"effective_hit@{k}") for r in completed_present]
        eff_cov_completed = [r.get(f"effective_cov@{k}") for r in completed_present]
        summary[f"k={k}"] = {
            "hit_at_k": _mean(hit_values),
            "hit_at_k_na_count": _count_na(hit_values),
            "cov_recall_at_k": _mean(cov_values),
            "cov_recall_at_k_na_count": _count_na(cov_values),
            "conditional_cov_at_k": _mean([r.get(f"conditional_cov@{k}") for r in rows]),
            "conditional_cov_at_k_na_count": _count_na(
                [r.get(f"conditional_cov@{k}") for r in rows]),
            "effective_hit_at_k": _mean(eff_hit_present),
            "effective_hit_at_k_denominator": len(present),
            "effective_cov_at_k": _mean(eff_cov_present),
            "effective_cov_at_k_denominator": len(present),
            "effective_hit_at_k_completed_only": _mean(eff_hit_completed),
            "effective_cov_at_k_completed_only": _mean(eff_cov_completed),
            "effective_hit_at_k_completed_denominator": len(completed_present),
        }
    pool_covs = [r.get("pool_cov") for r in rows]
    anys = [r.get("any_at_m") for r in rows]
    conditionals = [r.get("conditional_cov") for r in rows]
    summary["pool_cov_at_m"] = _mean(pool_covs)
    summary["pool_cov_at_m_na_count"] = _count_na(pool_covs)
    summary["any_at_m"] = _mean(anys)
    summary["any_at_m_na_count"] = _count_na(anys)
    summary["conditional_cov"] = _mean(conditionals)
    summary["conditional_cov_na_count"] = _count_na(conditionals)
    summary["conditional_cov_legacy_pool_census"] = _mean(
        [r.get("conditional_cov_legacy_pool_census") for r in rows])
    summary["conditional_cov_semantics"] = "max configured K; conditional_cov_at_k_v2"
    summary["conditional_cov_semantics_version"] = "conditional_cov_at_k_v2"
    summary["conditional_cov_legacy_semantics"] = (
        "conditional_cov_legacy_pool_census is compatibility-only and is not retrieval success"
    )
    summary["risk"] = {
        "absent_false_accept_events": int(sum(int(r.get("absent_false_accept", 0)) for r in rows)),
        "absent_denominator": len(absent),
        "absent_false_accept_rate": (_safe_rate(sum(int(r.get("absent_false_accept", 0))
                                                   for r in absent), len(absent))),
        "present_wrong_accept_events": int(sum(int(r.get("present_wrong_accept", 0)) for r in rows)),
        "present_denominator": len(present),
        "present_wrong_accept_rate": (_safe_rate(sum(int(r.get("present_wrong_accept", 0))
                                                     for r in present), len(present))),
    }
    summary["na_counts"] = {
        "hit": summary.get("k=%d" % max((int(k) for k in top_k), default=1), {}).get(
            "hit_at_k_na_count", 0),
        "pool_cov": summary["pool_cov_at_m_na_count"],
        "conditional_cov": summary["conditional_cov_na_count"],
    }
    summary["frozen_denominator_note"] = (
        "failed / timed-out / rejected queries with neighbours keep EffectiveHit=EffectiveCov=0 "
        "inside the frozen denominator; mate-absent queries stay in the risk denominator"
    )
    return summary


def _safe_rate(events: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return events / float(denominator)


def _failure_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        code = row.get("failure_code") or (None if row.get("status") == STATUS_OK
                                           else str(row.get("status")))
        if not code:
            continue
        counts[str(code)] = counts.get(str(code), 0) + 1
    return counts


def per_query_table(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Flatten roster rows into a parquet-friendly table (lists become JSON strings)."""
    import json

    out: list[dict[str, Any]] = []
    for row in rows:
        flat: dict[str, Any] = {}
        for key, value in row.items():
            if key == "risk":
                for sub, sub_value in (value or {}).items():
                    flat[f"risk_{sub}"] = json.dumps(sub_value) if isinstance(sub_value, list) \
                        else sub_value
            elif isinstance(value, (list, tuple, dict)):
                flat[key] = json.dumps(value, ensure_ascii=False, default=str)
            else:
                flat[key] = value
        out.append(flat)
    return out


__all__ = [
    "STATUS_OK", "STATUS_REJECTED", "STATUS_INPUT_UNAVAILABLE", "STATUS_TIMEOUT",
    "STATUS_RECONSTRUCTION_FAILED", "STATUS_NO_CANDIDATE", "STATUS_NA_NOT_APPLICABLE",
    "FAILURE_STATUSES", "DEFAULT_TOP_K", "dedupe_candidates", "intersect", "hit_at_k",
    "cov_recall_at_k", "any_at_m", "pool_cov_at_m", "conditional_cov",
    "conditional_cov_at_k", "pool_miss",
    "accept_set", "effective_hit_at_k", "effective_cov_at_k", "risk_events", "query_metrics",
    "aggregate_metrics", "per_query_table",
]
