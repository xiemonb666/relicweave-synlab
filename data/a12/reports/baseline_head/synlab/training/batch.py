"""Label-side training batch: relations, masks, correspondences, quality, contradiction.

Everything in this module is **label side**.  A :class:`TrainingBatch` holds a
:class:`~synlab.training.adapter.FeatureBundle` but never the other way round, and the
frozen exclusion rules of plan 18.2 are enforced at construction time:

* a *sampled* query's positives are its confirmed R2 relations and they never compete with
  each other;
* ordinary negatives may only be confirmed R1/R0 candidates -- never the query itself, never
  another candidate's known R2, never a grey-zone edge, never ``UNKNOWN``, never ``TINY``,
  never a candidate whose relation label is unconfirmed;
* when a query has no confirmed R1, the sampler may fall back to R0 and must record it in
  ``r1_fallback_used``;
* every candidate carries an :data:`~synlab.training.adapter.EXCLUSION_*` reason so a report
  can show *why* something was removed instead of silently shrinking a denominator.

Integration point: ``synlab.relations.api.sample_training_batch(pool, sampler_cfg, rng)`` is
**not present in this checkout** (parallel development).  :func:`build_training_batch` accepts
either that function's documented ``{"pool_id", "rows": [{"query", "positives", "negatives"}]}``
output (via ``rows=``) or the test fixture :class:`~tests.a12._fixtures.FixturePool`
(via ``pool=``); both go through the same rule checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from .adapter import (
    CONTRADICTION_COMPATIBLE,
    CONTRADICTION_MISSING,
    EXCLUSION_GRAY_ZONE,
    EXCLUSION_KNOWN_R2,
    EXCLUSION_LABEL_INVALID,
    EXCLUSION_NONE,
    EXCLUSION_REASON_NAMES,
    EXCLUSION_SAME_FRAGMENT,
    EXCLUSION_TINY,
    EXCLUSION_UNKNOWN,
    FeatureBundle,
    RELATION_CODES,
    RELATION_NAMES,
    RELATION_R1_CODE,
    RELATION_R2_CODE,
    RELATION_TINY_CODE,
    RELATION_UNKNOWN_CODE,
)

#: quality tiers Q0..Q5 (plan 18.5); Q2 is used as an uncalibrated *stress* tier
QUALITY_TIERS = ("Q0", "Q1", "Q2", "Q3", "Q4", "Q5")
UNCALIBRATED_TIERS = frozenset({"Q2"})

_CLEAN_TIERS = frozenset({0, 1})
_STRESS_TIERS = frozenset({2})
_HARD_TIERS = frozenset({3, 4, 5})


def relation_code(name: str) -> int:
    return RELATION_CODES.get(str(name), RELATION_UNKNOWN_CODE)


def relation_name(code: int) -> str:
    return RELATION_NAMES.get(int(code), "UNKNOWN")


@dataclass
class TrainingBatch:
    """One constructed training batch: features + labels + masks (both kept separate)."""

    features: FeatureBundle
    pair_index: np.ndarray                 # [Q,C,2] int64 (query index, candidate index)
    pair_valid: np.ndarray                 # [Q,C] bool
    labels_relation: np.ndarray            # [Q,C] int8
    label_pair_valid: np.ndarray           # [Q,C] bool
    pos_mask: np.ndarray                   # [Q,C] bool
    neg_mask: np.ndarray                   # [Q,C] bool
    excluded_mask: np.ndarray              # [Q,C] bool
    exclusion_reason: np.ndarray           # [Q,C] int8
    quality_target: np.ndarray             # [F,R,Cq] float32
    quality_target_valid: np.ndarray       # [F,R,Cq] bool
    corr_weight: np.ndarray                # [Q,C,K] float32 (many-to-many edge weight W)
    corr_row_valid: np.ndarray             # [Q,C,K] bool
    corr_col_valid: np.ndarray             # [Q,C,K] bool
    corr_kind: np.ndarray                  # [F,L] int8, query and candidate token kinds
    contradiction: np.ndarray              # [Q,C] int8
    contradiction_valid: np.ndarray        # [Q,C] bool
    quality_tier: np.ndarray               # [F] int8
    lineage_cluster: np.ndarray            # [F] int64 (resolved to stable cluster ids)
    negative_is_r2_history: np.ndarray     # [Q,C] bool -- must be all False
    r1_fallback_used: np.ndarray           # [Q,C] bool
    sample_keys: np.ndarray                # [Q] <U64 deterministic sample keys
    pool_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ accounting
    @property
    def n_queries(self) -> int:
        return int(self.pair_index.shape[0])

    @property
    def n_candidates(self) -> int:
        return int(self.pair_index.shape[1])

    def valid_query_indices(self) -> np.ndarray:
        """Queries with >=1 valid positive AND >=1 legal negative (rank loss eligibility)."""
        pos = self.pos_mask.sum(axis=1)
        neg = self.neg_mask.sum(axis=1)
        return np.nonzero((pos > 0) & (neg > 0))[0]

    def positive_counts(self) -> np.ndarray:
        return self.pos_mask.sum(axis=1).astype(np.int64)

    def negative_counts(self) -> np.ndarray:
        return self.neg_mask.sum(axis=1).astype(np.int64)

    def effective_query_count(self) -> int:
        return int(self.valid_query_indices().size)

    def quality_tier_histogram(self) -> dict[str, int]:
        vals, counts = np.unique(self.quality_tier, return_counts=True)
        return {QUALITY_TIERS[int(v)] if 0 <= int(v) < len(QUALITY_TIERS) else f"T{int(v)}": int(c)
                for v, c in zip(vals.tolist(), counts.tolist())}

    def clean_fraction(self) -> float:
        if self.features.n_fragments == 0:
            return 0.0
        clean = np.isin(self.quality_tier, list(_CLEAN_TIERS)).sum()
        return float(clean / self.features.n_fragments)

    def exposure(self) -> dict[str, Any]:
        """Real exposure accounting (plan 18.4): mothers, R2 edges, labels, tokens."""
        return {
            "fragments": self.features.n_fragments,
            "queries": self.n_queries,
            "effective_queries": self.effective_query_count(),
            "r2_edges_exposed": int(self.pos_mask.sum()),
            "legal_negatives": int(self.neg_mask.sum()),
            "excluded_candidates": int(self.excluded_mask.sum()),
            "unconfirmed_candidates": int((~self.label_pair_valid).sum()),
            "correspondence_edges": int((self.corr_weight > 0).sum()),
            "contradiction_labels": int(self.contradiction_valid.sum()),
            "quality_targets": int(self.quality_target_valid.sum()),
            "tokens": int(self.features.real_token_counts().sum()),
            "points": int(self.features.real_point_counts().sum()),
            "clean_fraction": self.clean_fraction(),
            "tier_histogram": self.quality_tier_histogram(),
            "exclusion_histogram": exclusion_histogram(self),
        }

    def as_label_dict(self) -> dict[str, np.ndarray]:
        """Label tensors only -- what a loss function is allowed to see."""
        return {
            "pair_index": self.pair_index, "pair_valid": self.pair_valid,
            "labels_relation": self.labels_relation, "label_pair_valid": self.label_pair_valid,
            "pos_mask": self.pos_mask, "neg_mask": self.neg_mask,
            "excluded_mask": self.excluded_mask, "exclusion_reason": self.exclusion_reason,
            "quality_target": self.quality_target,
            "quality_target_valid": self.quality_target_valid,
            "corr_weight": self.corr_weight, "corr_row_valid": self.corr_row_valid,
            "corr_col_valid": self.corr_col_valid, "corr_kind": self.corr_kind,
            "contradiction": self.contradiction,
            "contradiction_valid": self.contradiction_valid,
        }


def exclusion_histogram(batch: TrainingBatch) -> dict[str, int]:
    vals, counts = np.unique(batch.exclusion_reason, return_counts=True)
    out = {name: 0 for name in EXCLUSION_REASON_NAMES.values()}
    for v, c in zip(vals.tolist(), counts.tolist()):
        out[EXCLUSION_REASON_NAMES.get(int(v), str(int(v)))] = int(c)
    return out


# --------------------------------------------------------------------------------------
# Rule checks
# --------------------------------------------------------------------------------------
def assert_legal_negative(relation: str | int, *, query_id: str, candidate_id: str,
                          is_history_r2: bool = False, confirmed: bool = True) -> None:
    """Raise when a candidate may not serve as an ordinary negative (plan 18.2)."""
    code = relation_code(relation) if isinstance(relation, str) else int(relation)
    if query_id == candidate_id:
        raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                          f"{candidate_id} is the query itself and cannot be a negative",
                          stage="training.batch.assert_legal_negative")
    if is_history_r2 or code == RELATION_R2_CODE:
        raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                          f"historical R2 {candidate_id} used as an ordinary negative of {query_id}",
                          stage="training.batch.assert_legal_negative")
    if code in (RELATION_UNKNOWN_CODE, RELATION_TINY_CODE):
        raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                          f"{relation_name(code)} candidate {candidate_id} used as a negative of {query_id}",
                          stage="training.batch.assert_legal_negative")
    if not confirmed:
        raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                          f"unconfirmed candidate {candidate_id} used as a negative of {query_id}",
                          stage="training.batch.assert_legal_negative")


def negative_audit(batch: TrainingBatch) -> dict[str, Any]:
    """Independently re-verify that no illegal candidate sits in ``neg_mask``."""
    problems: list[str] = []
    q_idx, c_idx = batch.pair_index[:, :, 0], batch.pair_index[:, :, 1]
    if np.any(batch.neg_mask & (q_idx == c_idx)):
        problems.append("self candidate inside neg_mask")
    if np.any(batch.neg_mask & batch.negative_is_r2_history):
        problems.append("historical R2 inside neg_mask")
    bad_kinds = np.isin(batch.labels_relation,
                        [RELATION_R2_CODE, RELATION_UNKNOWN_CODE, RELATION_TINY_CODE])
    if np.any(batch.neg_mask & bad_kinds):
        problems.append("R2/UNKNOWN/TINY relation code inside neg_mask")
    if np.any(batch.neg_mask & ~batch.label_pair_valid):
        problems.append("unconfirmed label inside neg_mask")
    if np.any(batch.neg_mask & batch.excluded_mask):
        problems.append("excluded candidate inside neg_mask")
    if np.any(batch.pos_mask & ~batch.label_pair_valid):
        problems.append("unconfirmed label inside pos_mask")
    return {
        "ok": not problems,
        "problems": problems,
        "negatives": int(batch.neg_mask.sum()),
        "positives": int(batch.pos_mask.sum()),
        "r1_fallback_used": int(batch.r1_fallback_used.sum()),
    }


# --------------------------------------------------------------------------------------
# Batch construction
# --------------------------------------------------------------------------------------
def _cluster_ids(fragment_ids: Sequence[str], clusters: Mapping[str, str]) -> np.ndarray:
    """Stable local renumbering of lineage clusters (opaque ids never reach a model)."""
    mapping: dict[str, int] = {}
    out = np.zeros(len(fragment_ids), dtype=np.int64)
    for i, fid in enumerate(fragment_ids):
        key = str(clusters.get(fid, "UNKNOWN"))
        if key not in mapping:
            mapping[key] = len(mapping)
        out[i] = mapping[key]
    return out


def _contradiction_label(relation: int, *, label_valid: bool, has_contradiction: bool,
                         has_evidence: bool) -> tuple[int, bool]:
    if not label_valid or not has_evidence:
        return CONTRADICTION_MISSING, False
    if relation in (RELATION_R1_CODE, RELATION_R2_CODE):
        return CONTRADICTION_COMPATIBLE, True
    return (2 if has_contradiction else CONTRADICTION_COMPATIBLE), True


def build_training_batch(
    features: FeatureBundle,
    *,
    labels: Mapping[str, Mapping[str, Any]] | None = None,
    pool: Any | None = None,
    rows: Sequence[Mapping[str, Any]] | None = None,
    sampler_cfg: Any | None = None,
    rng: np.random.Generator | None = None,
    block_r2_contamination: bool = True,
    correspondence: Mapping[tuple[str, str], Any] | None = None,
    quality_target: np.ndarray | None = None,
    quality_target_valid: np.ndarray | None = None,
    quality_tier: Mapping[str, int] | None = None,
    contradiction_source: Any | None = None,
) -> TrainingBatch:
    """Assemble a :class:`TrainingBatch` from a pool/fixture or pre-sampled rows.

    ``labels`` supplies the relations used for supervision.  Accepted forms:

    * ``{"R2": {fid: [mates]}, "R1": {fid: [..]}, "R0": {fid: [..]}, "UNKNOWN": {fid: [..]},
      "TINY_CONTACT": {fid: [..]}, "confirmed": {(a,b): bool}}`` (fixture style), or
    * a callable/object with ``relation(a, b) -> str`` plus ``neighbours(fid)``.
    """
    cfg = _SamplerCfg.from_spec(sampler_cfg)
    rng = rng or np.random.default_rng(0)
    f = features.n_fragments
    ids = list(features.fragment_ids)

    relation_lookup, neighbours_lookup, confirmed_lookup = _build_lookup(labels, pool, ids)

    if rows is None:
        rows = _sample_rows(ids, neighbours_lookup, relation_lookup, confirmed_lookup, cfg, rng)
    else:
        rows = [dict(r) for r in rows]

    q = len(rows)
    c = max(1, max((len(r.get("positives", [])) + len(r.get("negatives", [])) for r in rows),
                   default=1))

    pair_index = np.zeros((q, c, 2), dtype=np.int64)
    pair_valid = np.zeros((q, c), dtype=bool)
    labels_relation = np.full((q, c), RELATION_UNKNOWN_CODE, dtype=np.int8)
    label_pair_valid = np.zeros((q, c), dtype=bool)
    pos_mask = np.zeros((q, c), dtype=bool)
    neg_mask = np.zeros((q, c), dtype=bool)
    excluded_mask = np.zeros((q, c), dtype=bool)
    exclusion_reason = np.full((q, c), EXCLUSION_NONE, dtype=np.int8)
    negative_is_r2_history = np.zeros((q, c), dtype=bool)
    r1_fallback_used = np.zeros((q, c), dtype=bool)
    sample_keys = np.array([str(r.get("sample_key", f"q{i:04d}")) for i, r in enumerate(rows)],
                           dtype="U64")

    index_of = {fid: i for i, fid in enumerate(ids)}
    for i, row in enumerate(rows):
        qid = str(row["query"])
        q_ix = index_of[qid]
        positives = [p for p in row.get("positives", []) if p in index_of and p != qid]
        negatives = [n for n in row.get("negatives", []) if n in index_of and n != qid]
        # de-duplicate while preserving order, and never let a positive repeat as a negative
        positives = list(dict.fromkeys(positives))
        negatives = [n for n in dict.fromkeys(negatives) if n not in positives]

        slot = 0
        for cid in positives + negatives:
            is_pos = cid in positives
            c_ix = index_of[cid]
            rel = relation_code(relation_lookup(qid, cid))
            confirmed = bool(confirmed_lookup(qid, cid))
            history_r2 = cid in neighbours_lookup.get(qid, ())
            pair_index[i, slot] = (q_ix, c_ix)
            pair_valid[i, slot] = True
            labels_relation[i, slot] = rel
            label_pair_valid[i, slot] = confirmed
            if is_pos:
                pos_mask[i, slot] = True
                if not confirmed or rel != RELATION_R2_CODE:
                    raise SynLabError(
                        ErrorCode.SCHEMA_INVALID,
                        f"positive {cid} of {qid} is {relation_name(rel)} (confirmed={confirmed}); "
                        "positives must be confirmed R2",
                        stage="training.batch.build_training_batch",
                    )
            else:
                if not block_r2_contamination:
                    neg_mask[i, slot] = True
                    negative_is_r2_history[i, slot] = bool(history_r2 or rel == RELATION_R2_CODE)
                    r1_fallback_used[i, slot] = bool(row.get("r1_fallback", False))
                    slot += 1
                    continue
                assert_legal_negative(rel, query_id=qid, candidate_id=cid,
                                      is_history_r2=history_r2, confirmed=confirmed)
                neg_mask[i, slot] = True
                negative_is_r2_history[i, slot] = False
                r1_fallback_used[i, slot] = bool(row.get("r1_fallback", False))
            slot += 1

        for cid in row.get("excluded", []):
            if cid not in index_of or cid == qid or slot >= c:
                continue
            c_ix = index_of[cid]
            rel = relation_code(relation_lookup(qid, cid))
            pair_index[i, slot] = (q_ix, c_ix)
            pair_valid[i, slot] = False
            excluded_mask[i, slot] = True
            labels_relation[i, slot] = rel
            label_pair_valid[i, slot] = bool(confirmed_lookup(qid, cid))
            if cid in neighbours_lookup.get(qid, ()) or rel == RELATION_R2_CODE:
                exclusion_reason[i, slot] = EXCLUSION_KNOWN_R2
            elif rel == RELATION_UNKNOWN_CODE:
                exclusion_reason[i, slot] = EXCLUSION_UNKNOWN
            elif rel == RELATION_TINY_CODE:
                exclusion_reason[i, slot] = EXCLUSION_TINY
            elif not confirmed_lookup(qid, cid):
                exclusion_reason[i, slot] = EXCLUSION_LABEL_INVALID
            else:
                exclusion_reason[i, slot] = EXCLUSION_GRAY_ZONE
            slot += 1

    corr_weight, corr_row_valid, corr_col_valid = _corr_tensors(
        correspondence, rows, index_of, features.token_budget)

    quality_tier_arr = np.zeros(f, dtype=np.int8)
    for i, fid in enumerate(ids):
        tier = 0
        if quality_tier and fid in quality_tier:
            tier = int(quality_tier[fid])
        elif pool is not None and hasattr(pool, "quality_tier"):
            tier = int(getattr(pool, "quality_tier").get(fid, 0))
        quality_tier_arr[i] = tier

    clusters = {}
    if pool is not None and hasattr(pool, "lineage_cluster_of"):
        clusters = dict(getattr(pool, "lineage_cluster_of"))
    elif labels and "lineage_cluster" in labels:
        clusters = dict(labels["lineage_cluster"])

    corr_kind = np.full((f, features.token_budget), 0, dtype=np.int8)
    if labels and "corr_kind" in labels:
        ck = np.asarray(labels["corr_kind"], dtype=np.int8)
        corr_kind[:, : ck.shape[1]] = ck[:, : features.token_budget]

    cont = np.full((q, c), CONTRADICTION_MISSING, dtype=np.int8)
    cont_valid = np.zeros((q, c), dtype=bool)
    for i, row in enumerate(rows):
        flags = row.get("contradiction") or {}
        for slot in range(c):
            if not pair_valid[i, slot]:
                continue
            cid = ids[int(pair_index[i, slot, 1])]
            qid = ids[int(pair_index[i, slot, 0])]
            info = flags.get(cid, False)
            has_contradiction = bool(info.get("contradiction", False)) if isinstance(info, Mapping) else bool(info)
            has_evidence = bool(info.get("evidence", True)) if isinstance(info, Mapping) else True
            cont[i, slot], cont_valid[i, slot] = _contradiction_label(
                int(labels_relation[i, slot]), label_valid=bool(label_pair_valid[i, slot]),
                has_contradiction=has_contradiction, has_evidence=has_evidence)

    if quality_target is None:
        quality_target = features.quality.copy()
        quality_target_valid = (features.quality_valid.copy() if quality_target_valid is None
                                else np.asarray(quality_target_valid, dtype=bool))
    elif quality_target_valid is None:
        quality_target_valid = np.ones_like(np.asarray(quality_target), dtype=bool)

    batch = TrainingBatch(
        features=features,
        pair_index=pair_index, pair_valid=pair_valid,
        labels_relation=labels_relation, label_pair_valid=label_pair_valid,
        pos_mask=pos_mask, neg_mask=neg_mask,
        excluded_mask=excluded_mask, exclusion_reason=exclusion_reason,
        quality_target=np.asarray(quality_target, dtype=np.float32),
        quality_target_valid=np.asarray(quality_target_valid, dtype=bool),
        corr_weight=corr_weight, corr_row_valid=corr_row_valid, corr_col_valid=corr_col_valid,
        corr_kind=corr_kind, contradiction=cont, contradiction_valid=cont_valid,
        quality_tier=quality_tier_arr, lineage_cluster=_cluster_ids(ids, clusters),
        negative_is_r2_history=negative_is_r2_history, r1_fallback_used=r1_fallback_used,
        sample_keys=sample_keys,
        pool_id=str(getattr(pool, "pool_id", "") or (labels or {}).get("pool_id", "")),
        meta={"exclusion_reason_names": EXCLUSION_REASON_NAMES,
              "relation_names": RELATION_NAMES},
    )
    audit = negative_audit(batch)
    if not audit["ok"]:
        raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
                          f"illegal negatives in batch: {audit['problems']}",
                          stage="training.batch.build_training_batch",
                          evidence_refs=audit["problems"])
    return batch


# --------------------------------------------------------------------------------------
# internals
# --------------------------------------------------------------------------------------
@dataclass
class _SamplerCfg:
    queries: int = 2
    positive_limit: int = 2
    negative_limit: int = 8
    negative_mix: tuple[float, float] = (0.5, 0.5)  # (R1 weight, R0 weight)

    @classmethod
    def from_spec(cls, spec: Any | None) -> "_SamplerCfg":
        if spec is None:
            return cls()
        if isinstance(spec, _SamplerCfg):
            return spec
        if isinstance(spec, Mapping):
            mix = spec.get("negative_mix", {"R1": 0.5, "R0": 0.5})
            return cls(queries=int(spec.get("queries_per_microbatch", 2)),
                       positive_limit=int(spec.get("positive_limit", 2)),
                       negative_limit=int(spec.get("legal_negative_limit", 8)),
                       negative_mix=(float(mix.get("R1", 0.5)), float(mix.get("R0", 0.5))))
        mix = getattr(spec, "negative_mix", {"R1": 0.5, "R0": 0.5})
        return cls(
            queries=int(getattr(spec, "queries_per_microbatch", 2)),
            positive_limit=int(getattr(spec, "positive_limit", 2)),
            negative_limit=int(getattr(spec, "legal_negative_limit", 8)),
            negative_mix=(float(mix.get("R1", 0.5)), float(mix.get("R0", 0.5))),
        )


def _build_lookup(labels, pool, ids):
    """Return ``(relation(q,c)->name, neighbours(q)->set, confirmed(q,c)->bool)``."""
    rel_table: dict[tuple[str, str], str] = {}
    neighbours: dict[str, set[str]] = {fid: set() for fid in ids}
    confirmed: dict[tuple[str, str], bool] = {}

    if pool is not None and hasattr(pool, "relation"):
        for a in ids:
            for b in ids:
                if a == b:
                    continue
                rel_table[(a, b)] = str(pool.relation(a, b))
            neighbours[a] = set(pool.neighbours(a)) if hasattr(pool, "neighbours") else set()
    elif labels is not None and "R2" in labels and isinstance(labels["R2"], Mapping):
        for a, mates in labels["R2"].items():
            for b in mates:
                rel_table[(a, b)] = "R2"
                rel_table[(b, a)] = "R2"
                neighbours.setdefault(a, set()).add(b)
                neighbours.setdefault(b, set()).add(a)
        for key, name in (("R1", "R1"), ("R0", "R0"),
                          ("UNKNOWN", "UNKNOWN"), ("TINY_CONTACT", "TINY_CONTACT")):
            for a, mates in (labels.get(key) or {}).items():
                for b in mates:
                    rel_table.setdefault((a, b), name)
                    rel_table.setdefault((b, a), name)
    elif labels is not None and hasattr(labels, "relation"):
        for a in ids:
            for b in ids:
                if a != b:
                    rel_table[(a, b)] = str(labels.relation(a, b))
            neighbours[a] = set(labels.neighbours(a))

    if labels is not None and "confirmed" in labels:
        for key, value in labels["confirmed"].items():
            if isinstance(key, tuple) and len(key) == 2:
                a, b = key
                confirmed[(str(a), str(b))] = bool(value)
                confirmed[(str(b), str(a))] = bool(value)

    def relation_of(a: str, b: str) -> str:
        return rel_table.get((a, b), "UNKNOWN")

    def confirmed_of(a: str, b: str) -> bool:
        # explicit table wins; otherwise a relation present in the table is confirmed and a
        # node with no table entry at all stays unconfirmed (never silently treated as R0)
        if (a, b) in confirmed:
            return confirmed[(a, b)]
        if (a, b) in rel_table:
            return True
        return False

    return relation_of, neighbours, confirmed_of


def _sample_rows(ids, neighbours, relation_of, confirmed_of, cfg: _SamplerCfg,
                 rng: np.random.Generator) -> list[dict]:
    with_mates = [fid for fid in ids if neighbours.get(fid)]
    candidates = with_mates or list(ids)
    n = min(cfg.queries, len(candidates))
    chosen = list(rng.choice(candidates, size=n, replace=False)) if n else []
    rows = []
    for qid in chosen:
        pos = sorted(neighbours.get(qid, set()))
        pos = pos[: cfg.positive_limit]
        r1, r0 = [], []
        for cid in ids:
            if cid == qid or cid in neighbours.get(qid, set()):
                continue
            if not confirmed_of(qid, cid):
                continue
            rel = relation_of(qid, cid)
            if rel == "R1":
                r1.append(cid)
            elif rel == "R0":
                r0.append(cid)
        fallback = False
        if not r1:
            fallback = True  # no confirmed R1 available -> recorded R0 fallback
        budget = cfg.negative_limit
        w1, w0 = cfg.negative_mix
        n1 = int(round(budget * w1 / max(w1 + w0, 1e-9))) if r1 else 0
        picked = list(rng.permutation(r1)[:n1]) if r1 else []
        picked += list(rng.permutation(r0)[: max(0, budget - len(picked))])
        excluded = sorted({c for c in ids
                           if c != qid and (c in neighbours.get(qid, set())
                                            or relation_of(qid, c) in ("UNKNOWN", "TINY_CONTACT")
                                            or not confirmed_of(qid, c))})
        rows.append({"query": qid, "positives": pos, "negatives": picked,
                     "excluded": excluded, "r1_fallback": fallback,
                     "sample_key": f"row::{qid}"})
    return rows


def _corr_tensors(correspondence, rows, index_of, token_budget: int):
    q = len(rows)
    c = max(1, max((len(r.get("positives", [])) + len(r.get("negatives", [])) for r in rows),
                   default=1))
    k = max(int(token_budget), 1)
    weight = np.zeros((q, c, k), dtype=np.float32)
    row_valid = np.zeros((q, c, k), dtype=bool)
    col_valid = np.zeros((q, c, k), dtype=bool)
    if correspondence:
        for i, row in enumerate(rows):
            qid = str(row["query"])
            entries = list(row.get("positives", [])) + list(row.get("negatives", []))
            for slot, cid in enumerate(entries[:c]):
                spec = correspondence.get((qid, cid)) or correspondence.get((cid, qid))
                if spec is None:
                    continue
                r = np.asarray(spec.get("rows", []), dtype=np.int64)
                cc = np.asarray(spec.get("cols", []), dtype=np.int64)
                w = np.asarray(spec.get("weights", np.ones(r.size)), dtype=np.float32)
                rv = np.asarray(spec.get("row_valid", np.ones(r.size)), dtype=bool)
                cv = np.asarray(spec.get("col_valid", np.ones(cc.size)), dtype=bool)
                for a, b, ww in zip(r.tolist(), cc.tolist(), w.tolist()):
                    if 0 <= a < k and 0 <= b < k:
                        weight[i, slot, a] += float(ww)
                row_valid[i, slot, : min(k, rv.size)] = rv[:k]
                col_valid[i, slot, : min(k, cv.size)] = cv[:k]
    return weight, row_valid, col_valid


__all__ = [
    "QUALITY_TIERS", "UNCALIBRATED_TIERS", "TrainingBatch", "build_training_batch",
    "negative_audit", "assert_legal_negative", "exclusion_histogram",
    "relation_code", "relation_name",
]
