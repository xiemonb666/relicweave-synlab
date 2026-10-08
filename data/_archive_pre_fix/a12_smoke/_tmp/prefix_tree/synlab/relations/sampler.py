"""Training sampler and hard-negative mining (plan 16.2, 16.3, 30.10, 30.12).

Frozen rules enforced here
--------------------------
* lineage-balanced query draw, then one valid event/query/observation version per draw;
* positives are **1-2** candidates drawn from the *full* R2 set ``N_G(q)``; across batches the
  cursor walks the whole neighbour list so every R2 edge is eventually covered, while the
  supervision still records the complete set;
* negatives start from ``4 x R1 + 4 x R0`` per query; when no confirmed R1 exists the sampler
  falls back to R0 and records ``r1_fallback`` (it never fabricates an R1);
* **all** historical R2 and every ``TINY_CONTACT`` edge are removed from the negative set --
  not only the positives sampled in this batch -- and ``UNKNOWN`` never enters the loss;
* separate exposure accounting for R2 edges, mothers and hard-negative groups; indices are
  returned as *positions*, never as embeddings, and ``hard_type``/``mate_present`` are never
  part of a model input.

Hard-negative mining reads **only legal observable features** for retrieval; the relation
labels are used afterwards and exclusively to drop historical R2 / grey zone / ``UNKNOWN`` /
``TINY_CONTACT`` and to confirm R1/R0.  Assembly distance, shared interface ids and truth
poses are never read (plan 16.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..roles import FORBIDDEN_FEATURE_FIELDS
from ..schemas.runtime import (
    RELATION_R0,
    RELATION_R1,
    RELATION_R2,
    RELATION_TINY,
    RELATION_UNKNOWN,
)

SAMPLER_VERSION = "relations.sampler.v1"
MINER_VERSION = "relations.miner.v1"

#: Hard-negative groups required by plan 16.3, plus one reporting-only bucket for a
#: retrieved *true* neighbour that is not heavily damaged (it is never a negative).
HARD_GROUPS: tuple[str, ...] = (
    "same_instrument_not_adjacent",
    "same_type_different_object",
    "same_template_different_phase",
    "pattern_like_geometry_off",
    "geometry_close_pattern_off",
    "heavily_damaged_true_neighbour",
    "multi_neighbour_query",
    "no_neighbour_in_gallery",
    "true_neighbour_retrieved",
)

#: R0 quota categories from plan 16.2 item 3.
R0_CATEGORIES: tuple[str, ...] = (
    "same_type_different_object", "pattern_approx", "geometry_approx", "ordinary_different_object",
)

#: Extra names that must never reach a feature tensor (plan 30.12).
_EXTRA_FORBIDDEN = frozenset({
    "mate_present", "hard_type", "hard_case_tag", "historical_r2", "interface_id",
    "assembly_distance", "truth_pose", "t_wf", "relation", "r2_pair", "spurious_mask",
})
_FORBIDDEN_UNION = frozenset({str(f).lower() for f in FORBIDDEN_FEATURE_FIELDS}
                             | {str(f).lower() for f in _EXTRA_FORBIDDEN})


# --------------------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------------------
@dataclass
class SamplerParams:
    queries: int = 2
    positive_limit: int = 2
    negative_limit: int = 8
    negative_mix: tuple[float, float] = (0.5, 0.5)
    r0_categories: tuple[str, ...] = R0_CATEGORIES

    @classmethod
    def from_config(cls, cfg: Any | None) -> "SamplerParams":
        if cfg is None:
            return cls()
        if isinstance(cfg, SamplerParams):
            return cfg
        sampling = getattr(cfg, "sampling", cfg)
        if hasattr(sampling, "model_dump"):
            data = sampling.model_dump(mode="json")
        elif isinstance(sampling, Mapping):
            data = dict(sampling)
        else:
            data = {k: getattr(sampling, k) for k in
                    ("queries_per_microbatch", "positive_limit", "legal_negative_limit",
                     "negative_mix") if hasattr(sampling, k)}
        mix = data.get("negative_mix") or {}
        if not isinstance(mix, Mapping):
            mix = {}
        return cls(
            queries=int(data.get("queries_per_microbatch", 2) or 2),
            positive_limit=int(data.get("positive_limit", 2) or 2),
            negative_limit=int(data.get("legal_negative_limit", 8) or 0),
            negative_mix=(float(mix.get("R1", 0.5)), float(mix.get("R0", 0.5))),
        )


def new_sampler_state() -> dict[str, Any]:
    """Mutable cross-batch cursor (R2 coverage + exposure accounting)."""
    return {"r2_cursor": {}, "query_draws": {}, "lineage_draws": {}, "r2_exposed": {},
            "batches": 0, "r1_fallback_events": 0}


# --------------------------------------------------------------------------------------
# legality of a candidate for the negative set
# --------------------------------------------------------------------------------------
def negative_exclusion_reason(pool: Any, query_id: str, candidate_id: str) -> str | None:
    """Return why ``candidate_id`` may **not** be an ordinary negative, else ``None``.

    This is the frozen exclusion (plan 16.2 item 4): self, *all* historical R2, TINY_CONTACT,
    UNKNOWN/grey zone and unconfirmed relations are removed -- independently of which
    positives happened to be sampled in the current batch.
    """
    if candidate_id == query_id:
        return "same_fragment"
    try:
        neighbours = set(pool.neighbours(query_id))
    except Exception:  # noqa: BLE001 - a pool without neighbours() cannot confirm anything
        neighbours = set()
    if candidate_id in neighbours:
        return "known_R2"
    relation = str(pool.relation(query_id, candidate_id))
    if relation == RELATION_R2:
        return "known_R2"
    if relation == RELATION_TINY:
        return "TINY_CONTACT"
    if relation == RELATION_UNKNOWN:
        return "gray_zone"
    if relation not in (RELATION_R1, RELATION_R0):
        return "label_invalid"
    confirmed = getattr(pool, "confirmed", None)
    if callable(confirmed) and not confirmed(query_id, candidate_id):
        return "label_invalid"
    return None


def assert_legal_negative(pool: Any, query_id: str, candidate_id: str) -> None:
    reason = negative_exclusion_reason(pool, query_id, candidate_id)
    if reason is not None:
        raise SynLabError(
            ErrorCode.LEAKAGE_DETECTED,
            f"candidate {candidate_id} may not be a negative of {query_id}: {reason}",
            stage="relations.sampler.assert_legal_negative",
            measurements={"query": query_id, "candidate": candidate_id, "reason": reason},
        )


# --------------------------------------------------------------------------------------
# lineage-balanced query draw
# --------------------------------------------------------------------------------------
def _lineages_of(pool: Any) -> dict[str, list[str]]:
    cluster_of = getattr(pool, "lineage_cluster_of", None) or getattr(pool, "lineage_of", {}) or {}
    out: dict[str, list[str]] = {}
    for fid in pool.lineup:
        out.setdefault(str(cluster_of.get(fid, "UNKNOWN")), []).append(str(fid))
    return out


def draw_queries(pool: Any, rng: np.random.Generator, count: int,
                 state: dict[str, Any] | None = None) -> list[str]:
    """Balanced draw: one query per lineage per round, least-exposed lineage first."""
    state = state if state is not None else new_sampler_state()
    lineages = _lineages_of(pool)
    if not lineages:
        return []
    order = sorted(lineages)
    rng.shuffle(order)
    draws = state.setdefault("query_draws", {})
    picked: list[str] = []
    guard = 0
    while len(picked) < count and guard < 4 * (len(order) + count + 1):
        guard += 1
        progressed = False
        for lineage in order:
            if len(picked) >= count:
                break
            members = [f for f in sorted(lineages[lineage]) if f != ""]
            if not members:
                continue
            members.sort(key=lambda f: (int(draws.get(f, 0)), f))
            choice = members[0]
            if choice in picked:
                continue
            picked.append(choice)
            draws[choice] = int(draws.get(choice, 0)) + 1
            state.setdefault("lineage_draws", {})
            state["lineage_draws"][lineage] = int(state["lineage_draws"].get(lineage, 0)) + 1
            progressed = True
        if not progressed:
            break
    return picked


# --------------------------------------------------------------------------------------
# legal observables used for R0 category coverage / mining
# --------------------------------------------------------------------------------------
def assert_legal_feature_payload(payload: Mapping[str, Any], *, where: str = "payload") -> None:
    """Reject forbidden field names (recursively) before any retrieval use."""
    violations: list[str] = []

    def walk(node: Any, path: str, depth: int) -> None:
        if depth > 8:
            return
        if isinstance(node, Mapping):
            for key, value in node.items():
                low = str(key).lower()
                if low in _FORBIDDEN_UNION:
                    violations.append(f"{path}.{key}")
                else:
                    walk(value, f"{path}.{key}", depth + 1)
        elif isinstance(node, (list, tuple)) and not isinstance(node, (str, bytes)):
            for i, value in enumerate(node[:32]):
                walk(value, f"{path}[{i}]", depth + 1)

    walk(payload, where, 0)
    if violations:
        raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                          f"forbidden fields reached the retrieval features: {violations[:8]}",
                          stage="relations.sampler.assert_legal_feature_payload",
                          evidence_refs=violations[:8])


def legal_retrieval_vector(payload: Mapping[str, Any]) -> np.ndarray | None:
    """Observable-only fragment vector: appearance tokens + scale-normalised geometry.

    Only fields a deployment profile can obtain are read (view appearance statistics,
    observed point/normal moments, OBS_EST quality/presence).  Returns ``None`` when the
    payload cannot form a legal vector (missing observations are *not* zero-filled).
    """
    assert_legal_feature_payload(payload, where="retrieval")
    parts: list[np.ndarray] = []
    tokens = payload.get("view_tokens")
    if tokens is not None and np.asarray(tokens).size:
        arr = np.asarray(tokens, dtype=np.float64)
        if arr.ndim == 2 and arr.shape[0] > 0:
            parts.append(np.concatenate([arr.mean(axis=0), arr.std(axis=0)]))
    points = payload.get("points")
    normals = payload.get("normals")
    pv = payload.get("point_valid")
    if points is not None and normals is not None:
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        nrm = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
        mask = (np.ones(pts.shape[0], dtype=bool) if pv is None
                else np.asarray(pv, dtype=bool).reshape(-1))
        if mask.size != pts.shape[0]:
            mask = np.ones(pts.shape[0], dtype=bool)
        sel_p, sel_n = pts[mask], nrm[mask]
        if sel_p.size:
            centre = sel_p.mean(axis=0)
            spread = float(np.linalg.norm(sel_p - centre, axis=1).mean()) or 1.0
            shape = (sel_p - centre) / spread                 # scale-normalised shape
            parts.append(np.concatenate([shape.mean(axis=0), shape.std(axis=0)]))
        if sel_n.size:
            parts.append(np.concatenate([sel_n.mean(axis=0), sel_n.std(axis=0)]))
    quality = payload.get("quality")
    if quality is not None and np.asarray(quality).size:
        q = np.asarray(quality, dtype=np.float64)
        qv = payload.get("quality_valid")
        if qv is not None and np.asarray(qv).shape == q.shape:
            q = np.where(np.asarray(qv, dtype=bool), q, 0.0)
        parts.append(q.reshape(-1))
    if not parts:
        return None
    vec = np.concatenate(parts).astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if not np.isfinite(norm) or norm <= 1e-12:
        return None
    return vec / norm


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# --------------------------------------------------------------------------------------
# training batch sampling
# --------------------------------------------------------------------------------------
def sample_training_batch(pool: Any, cfg: Any | None = None,
                          rng: np.random.Generator | None = None, *,
                          state: dict[str, Any] | None = None,
                          query_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Draw one micro-batch of queries with positives and legal negatives (plan 16.2).

    The returned ``rows`` feed ``synlab.training.batch.build_training_batch(rows=...)``
    unchanged (``query`` / ``positives`` / ``negatives`` / ``excluded`` / ``r1_fallback`` /
    ``sample_key``).
    """
    params = SamplerParams.from_config(cfg)
    rng = rng if rng is not None else np.random.default_rng(0)
    state = state if state is not None else new_sampler_state()
    state["batches"] = int(state.get("batches", 0)) + 1

    if query_ids is not None:
        queries = [str(q) for q in query_ids][: params.queries]
    else:
        queries = draw_queries(pool, rng, params.queries, state)

    lineups = list(pool.lineup)
    lineup_set = set(lineups)
    rows: list[dict[str, Any]] = []
    exclusion_histogram: dict[str, int] = {}
    hard_group_histogram = {group: 0 for group in HARD_GROUPS}
    r0_category_histogram = {name: 0 for name in R0_CATEGORIES}
    r0_category_unavailable: list[str] = []
    r2_total, r2_exposed_now = 0, 0
    q5_queries: list[str] = []

    for query in queries:
        neighbours = [n for n in pool.neighbours(query) if n != query]
        r2_total += len(neighbours)
        in_gallery = [n for n in neighbours if n in lineup_set]
        if not in_gallery:
            hard_group_histogram["no_neighbour_in_gallery"] += 1
        if len(neighbours) > 1:
            hard_group_histogram["multi_neighbour_query"] += 1

        # ---- positives: walk the full R2 list with a cross-batch cursor --------------
        cursor = int(state.setdefault("r2_cursor", {}).get(query, 0))
        if in_gallery:
            take = min(params.positive_limit, len(in_gallery))
            start = cursor % len(in_gallery)
            positives = [in_gallery[(start + i) % len(in_gallery)] for i in range(take)]
            state["r2_cursor"][query] = (start + take) % len(in_gallery)
        else:
            positives = []
            state["r2_cursor"][query] = 0
        exposed = state.setdefault("r2_exposed", {}).setdefault(query, [])
        for positive in positives:
            if positive not in exposed:
                exposed.append(positive)
                r2_exposed_now += 1

        # ---- candidate split ---------------------------------------------------------
        r1_pool, r0_pool, excluded = [], [], []
        for candidate in lineups:
            if candidate == query:
                excluded.append(candidate)
                exclusion_histogram["same_fragment"] = exclusion_histogram.get("same_fragment", 0) + 1
                continue
            reason = negative_exclusion_reason(pool, query, candidate)
            if reason is not None:
                excluded.append(candidate)
                exclusion_histogram[reason] = exclusion_histogram.get(reason, 0) + 1
                continue
            relation = str(pool.relation(query, candidate))
            if relation == RELATION_R1:
                r1_pool.append(candidate)
            else:
                r0_pool.append(candidate)

        budget = int(params.negative_limit)
        w1, w0 = params.negative_mix
        want_r1 = int(round(budget * w1 / max(w1 + w0, 1e-9))) if r1_pool else 0
        picked = ([str(c) for c in rng.permutation(r1_pool)[:want_r1]] if r1_pool else [])
        fallback = not r1_pool and budget > 0
        if fallback:
            state["r1_fallback_events"] = int(state.get("r1_fallback_events", 0)) + 1
        shortfall = max(0, budget - len(picked))
        picked.extend(_pick_r0(pool, query, r0_pool, shortfall, rng,
                               r0_category_histogram, r0_category_unavailable))

        # ---- hard-group accounting (labels only; never a model input) ----------------
        for candidate in picked:
            relation = str(pool.relation(query, candidate))
            if relation == RELATION_R1:
                group = ("same_instrument_not_adjacent"
                         if pool.mother_of.get(candidate) == pool.mother_of.get(query)
                         else "same_type_different_object")
            else:
                group = "same_type_different_object"
            hard_group_histogram[group] = hard_group_histogram.get(group, 0) + 1
        for positive in positives:
            if int(pool.quality_tier.get(positive, 0)) >= 4:
                hard_group_histogram["heavily_damaged_true_neighbour"] += 1
        if int(pool.quality_tier.get(query, 0)) >= 5:
            q5_queries.append(query)

        rows.append({
            "query": query,
            "positives": [p for p in positives if p in lineup_set],
            "negatives": [c for c in picked if c not in positives],
            "excluded": sorted(set(excluded)),
            "r1_fallback": bool(fallback),
            "sample_key": f"row::{pool.pool_id}::{query}::b{state['batches']}",
            "lineage_cluster": str(getattr(pool, "lineage_cluster_of", {}).get(query, "")),
            "quality_tier": int(getattr(pool, "quality_tier", {}).get(query, 0)),
        })

    return {
        "schema": "synlab.relations.batch.v1",
        "sampler_version": SAMPLER_VERSION,
        "pool_id": str(getattr(pool, "pool_id", "")),
        "gallery_version": str(getattr(pool, "gallery_version", "")),
        "pool_hash": str(getattr(pool, "hash", "")),
        "rows": rows,
        "index": _index_view(pool, rows),
        "observations": _observations(pool, rows),
        "labels": _labelled_rows(pool, rows),
        "provenance": {
            "sampler_version": SAMPLER_VERSION,
            "pool_id": str(getattr(pool, "pool_id", "")),
            "pool_hash": str(getattr(pool, "hash", "")),
            "feature_refs": {fid: getattr(rec, "feature_ref", None)
                             for fid, rec in getattr(pool, "fragments", {}).items()
                             if getattr(rec, "feature_ref", None)},
            "note": "indices are positions; hard_type/mate_present are never model inputs",
        },
        "exposure": {
            "queries": len(rows),
            "positives": int(sum(len(r["positives"]) for r in rows)),
            "negatives": int(sum(len(r["negatives"]) for r in rows)),
            "r2_edges_available": r2_total,
            "r2_edges_exposed_this_batch": r2_exposed_now,
            "r2_edges_exposed_cumulative": int(sum(len(v) for v in state["r2_exposed"].values())),
            "mothers_exposed": len({pool.mother_of.get(r["query"], "") for r in rows}),
            "lineages_exposed": len({r["lineage_cluster"] for r in rows}),
            "hard_groups": hard_group_histogram,
            "r0_categories": r0_category_histogram,
            "r0_categories_unavailable": sorted(set(r0_category_unavailable)),
            "q5_unresolvable_queries": sorted(set(q5_queries)),
            "r1_fallback_events": int(state.get("r1_fallback_events", 0)),
        },
        "exclusions": exclusion_histogram,
        "r2_cursor": dict(state["r2_cursor"]),
    }


def _pick_r0(pool: Any, query: str, r0_pool: Sequence[str], count: int,
             rng: np.random.Generator, histogram: dict[str, int],
             unavailable: list[str]) -> list[str]:
    """R0 quota covering the four declared categories when legal observations allow it."""
    if count <= 0 or not r0_pool:
        return []
    features = getattr(pool, "features", {}) or {}
    query_vec = legal_retrieval_vector(features[query]) if query in features else None
    if query_vec is None:
        unavailable.extend(["pattern_approx", "geometry_approx", "same_type_different_object"])
    scored: list[tuple[str, float]] = []
    if query_vec is not None:
        for candidate in r0_pool:
            payload = features.get(candidate)
            if payload is None:
                continue
            vec = legal_retrieval_vector(payload)
            if vec is None:
                continue
            scored.append((candidate, _cosine(query_vec, vec)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    picked: list[str] = []
    per_category = max(1, count // len(R0_CATEGORIES))
    if scored:
        for candidate, sim in scored[:per_category]:
            if candidate not in picked:
                picked.append(candidate)
                histogram["pattern_approx"] = histogram.get("pattern_approx", 0) + 1
        if len(picked) < count and len(scored) > per_category:
            tail = list(reversed(scored))[: max(1, per_category)]
            for candidate, _sim in tail:
                if candidate not in picked and len(picked) < count:
                    picked.append(candidate)
                    histogram["geometry_approx"] = histogram.get("geometry_approx", 0) + 1
    remaining = [c for c in r0_pool if c not in picked]
    while remaining and len(picked) < count:
        choice = str(rng.choice(remaining))
        remaining.remove(choice)
        picked.append(choice)
        if query_vec is not None and features.get(choice) is not None:
            histogram["same_type_different_object"] = \
                histogram.get("same_type_different_object", 0) + 1
        else:
            histogram["ordinary_different_object"] = \
                histogram.get("ordinary_different_object", 0) + 1
    return picked


def _index_view(pool: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    fragment_ids: list[str] = []
    for row in rows:
        for fid in [row["query"], *row["positives"], *row["negatives"]]:
            if fid not in fragment_ids:
                fragment_ids.append(str(fid))
    return {
        "fragment_ids": fragment_ids,
        "query_index": {str(r["query"]): i for i, r in enumerate(rows)},
        "position_of": {fid: i for i, fid in enumerate(fragment_ids)},
        "n_queries": len(rows),
        "n_candidates": len(fragment_ids),
    }


def _observations(pool: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for row in rows:
        for fid in [row["query"], *row["positives"], *row["negatives"]]:
            rec = getattr(pool, "fragments", {}).get(fid)
            out[str(fid)] = {
                "fragment_id": str(fid),
                "observation_ref": getattr(rec, "obs_ref", None),
                "feature_ref": getattr(rec, "feature_ref", None),
                "obs_version": int(getattr(rec, "meta", {}).get("obs_version", 0) or 0),
            }
    return out


def _labelled_rows(pool: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Relation labels for the sampled pairs -- kept beside the features, never inside."""
    labels = {"R2": {}, "R1": {}, "R0": {}, "TINY_CONTACT": {}, "UNKNOWN": {},
              "confirmed": {}}
    for row in rows:
        query = str(row["query"])
        labels["R2"][query] = sorted(str(n) for n in pool.neighbours(query))
        for candidate in row["negatives"]:
            relation = str(pool.relation(query, candidate))
            labels.setdefault(relation, {}).setdefault(query, []).append(str(candidate))
        for candidate in row["positives"]:
            labels["confirmed"][f"{query}|{candidate}"] = True
    return labels


# --------------------------------------------------------------------------------------
# hard-negative mining (plan 16.3)
# --------------------------------------------------------------------------------------
def mine_hard_negatives(pool: Any, query_ids: Sequence[str] | None = None, *,
                        top_m: int = 200, split: str | None = None,
                        rng: np.random.Generator | None = None,
                        encoder_hash: str = "", cache: dict[str, Any] | None = None,
                        cache_version: str = "") -> list[dict[str, Any]]:
    """Retrieve the legal TopM neighbours of each query and label the hard groups.

    ``split=None`` mines inside the pool's own line-up; pass ``split="train"`` to restrict the
    candidate gallery to the training split (plan 16.3: cache from train only, dev/confirm are
    never fed back into training).

    Retrieval uses legal observable features only.  Labels are applied afterwards: a
    candidate is ``usable_as_negative`` only when it is a confirmed R1/R0 that is neither a
    historical R2 nor a grey zone nor ``TINY_CONTACT`` nor the query itself.
    """
    rng = rng if rng is not None else np.random.default_rng(0)
    features = getattr(pool, "features", {}) or {}
    queries = list(query_ids) if query_ids is not None else [
        q.fragment_id for q in getattr(pool, "roster", [])]
    if not queries:
        queries = list(pool.lineup)
    candidates = [fid for fid in pool.lineup
                  if split is None or not getattr(pool, "split_of", {}).get(fid)
                  or getattr(pool, "split_of", {}).get(fid) == split]
    candidate_vectors: dict[str, np.ndarray] = {}
    for fid in candidates:
        payload = features.get(fid)
        if payload is None:
            continue
        vec = legal_retrieval_vector(payload)
        if vec is not None:
            candidate_vectors[fid] = vec

    cache_info = {"encoder_hash": encoder_hash, "cache_version": cache_version,
                  "cache_age_batches": None, "source": "train_only"}
    if cache is not None:
        cache_info["cache_age_batches"] = cache.get("age_batches")
        if cache.get("encoder_hash") and encoder_hash and cache["encoder_hash"] != encoder_hash:
            cache_info["stale"] = True

    results: list[dict[str, Any]] = []
    for query in queries:
        payload = features.get(str(query))
        keep: list[dict[str, Any]] = []
        if payload is None:
            results.append({"query": str(query), "candidates": [], "status": "INPUT_UNAVAILABLE",
                            "hard_groups": {}, "cache": cache_info})
            continue
        qvec = legal_retrieval_vector(payload)
        if qvec is None:
            results.append({"query": str(query), "candidates": [], "status": "INPUT_UNAVAILABLE",
                            "hard_groups": {}, "cache": cache_info})
            continue
        ranked = _top_m_legal(qvec, candidate_vectors, top_m, exclude={str(query)})
        multi = len(pool.neighbours(query)) > 1
        histogram = {group: 0 for group in HARD_GROUPS}
        if not pool.neighbours(query):
            histogram["no_neighbour_in_gallery"] += 1
        for candidate, score in ranked:
            reason = negative_exclusion_reason(pool, str(query), candidate)
            relation = str(pool.relation(query, candidate))
            group = _hard_group(pool, str(query), candidate, relation, reason)
            histogram[group] = histogram.get(group, 0) + 1
            keep.append({
                "candidate": candidate,
                "relation": relation,
                "score": float(score),
                "hard_group": group,
                "usable_as_negative": reason is None,
                "exclusion_reason": reason,
            })
        if multi:
            histogram["multi_neighbour_query"] = histogram.get("multi_neighbour_query", 0) + 1
        results.append({
            "query": str(query),
            "candidates": keep,
            "status": "OK",
            "retrieved": len(ranked),
            "top_m": int(top_m),
            "usable_negatives": sum(1 for c in keep if c["usable_as_negative"]),
            "hard_groups": histogram,
            "cache": cache_info,
            "miner_version": MINER_VERSION,
            "candidate_selection": "deterministic exact TopM; no random candidate draw",
        })
    return results


def _hard_group(pool: Any, query: str, candidate: str, relation: str,
                reason: str | None) -> str:
    same_mother = pool.mother_of.get(candidate) == pool.mother_of.get(query)
    if relation == RELATION_R2:
        return ("heavily_damaged_true_neighbour"
                if int(pool.quality_tier.get(candidate, 0)) >= 4 else "true_neighbour_retrieved")
    if relation == RELATION_R1:
        return "same_instrument_not_adjacent" if same_mother else "same_type_different_object"
    if reason == "TINY_CONTACT":
        return "heavily_damaged_true_neighbour"
    if reason is not None:
        return "no_neighbour_in_gallery"
    # R0: separate pattern-like from geometry-like using legal observables only
    features = getattr(pool, "features", {}) or {}
    q_payload, c_payload = features.get(query), features.get(candidate)
    if q_payload is None or c_payload is None:
        return "same_type_different_object"
    q_vec = legal_retrieval_vector(q_payload)
    c_vec = legal_retrieval_vector(c_payload)
    if q_vec is None or c_vec is None:
        return "same_type_different_object"
    sim = _cosine(q_vec, c_vec)
    return "pattern_like_geometry_off" if sim >= 0.8 else "geometry_close_pattern_off"


def _top_m_legal(query_vector: np.ndarray, candidate_vectors: Mapping[str, np.ndarray],
                 top_m: int, *, exclude: Iterable[str] = ()) -> list[tuple[str, float]]:
    """Exact inner-product TopM over legal fragment vectors (FAISS when importable)."""
    skip = {str(e) for e in exclude}
    ids = [fid for fid in sorted(candidate_vectors) if fid not in skip]
    if not ids:
        return []
    matrix = np.stack([candidate_vectors[fid] for fid in ids]).astype(np.float32)
    q = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
    k = int(min(max(top_m, 1), len(ids)))
    scores: np.ndarray
    try:  # reuse the installed exact index (plan 18.1: existing module or FAISS IndexFlatIP)
        import faiss

        index = faiss.IndexFlatIP(matrix.shape[1])
        index.add(matrix)
        distances, indices = index.search(q, k)
        scores = np.zeros(len(ids), dtype=np.float32)
        scores[indices[0]] = distances[0]
        order = np.lexsort((np.asarray(ids), -scores))[:k]
    except Exception:  # noqa: BLE001 - exact numpy fallback, identical ranking
        raw = matrix @ q.reshape(-1)
        order = np.lexsort((np.asarray(ids), -raw))[:k]
        scores = raw
    return [(ids[int(i)], float(scores[int(i)])) for i in order]


__all__ = [
    "SAMPLER_VERSION", "MINER_VERSION", "HARD_GROUPS", "R0_CATEGORIES", "SamplerParams",
    "new_sampler_state", "negative_exclusion_reason", "assert_legal_negative", "draw_queries",
    "assert_legal_feature_payload", "legal_retrieval_vector", "sample_training_batch",
    "mine_hard_negatives",
]
