"""The five core task losses (plan 18.2) with per-task effective denominators.

Every loss returns a :class:`LossResult`-shaped dict::

    {"loss": Tensor | None, "n_valid": int, "skipped": bool, "reason": str | None,
     "diagnostics": {...}}

Rules that the implementation must never bend:

* no valid supervision -> ``skipped=True`` and a counted reason; **never** divide by zero and
  **never** treat padding as a label;
* the batch denominator is the number of *valid* queries/correspondences, not a padded
  dimension;
* numerics go through ``torch.logsumexp`` / ``F.log_softmax`` so large logits cannot overflow;
* the rank term is per positive: each positive faces its own positive logit plus the legal
  negatives, so multiple positives never compete with each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError

DEFAULT_WEIGHTS: dict[str, float] = {
    "rank": 1.0, "view": 0.1, "correspondence": 0.1, "quality": 0.05, "contradiction": 0.1,
}

TASK_ORDER = ("rank", "view", "correspondence", "quality", "contradiction")

#: non-finite guard threshold for reported values
_MAX_ABS_LOGIT = 1e6


def _torch():
    import torch

    return torch


def _skip(reason: str, **diagnostics: Any) -> dict[str, Any]:
    return {"loss": None, "n_valid": 0, "skipped": True, "reason": reason,
            "diagnostics": diagnostics}


def _result(loss, n_valid: int, **diagnostics: Any) -> dict[str, Any]:
    return {"loss": loss, "n_valid": int(n_valid), "skipped": False, "reason": None,
            "diagnostics": diagnostics}


def _masked_rows(scores, mask):
    """Rows of ``scores`` that contain at least one True in ``mask``."""
    torch = _torch()
    keep = mask.any(dim=-1)
    return keep


# --------------------------------------------------------------------------------------
# A. same-fragment multi-view InfoNCE
# --------------------------------------------------------------------------------------
def view_infonce(view_embeddings, *, fragment_index, view_valid=None, exclude_matrix=None,
                 temperature: float = 0.1) -> dict[str, Any]:
    """InfoNCE over views of the same fragment.

    Positive pairs are two views of the *same* fragment that share actual visible area.
    ``exclude_matrix[i, j]`` (bool, ``[F,F]``) marks fragments that may not serve as ordinary
    negatives for fragment ``i`` -- known R2 neighbours and grey-zone fragments are excluded
    so a true mate is never pushed away (plan 18.2 A).
    """
    torch = _torch()
    z = view_embeddings                       # [N_view_tokens, D]
    fid = fragment_index                      # [N] fragment index per view
    if z.dim() != 2 or fid.dim() != 1 or z.shape[0] != fid.shape[0]:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"view_infonce shapes {tuple(z.shape)} / {tuple(fid.shape)}",
                          stage="training.losses.view_infonce")
    n = int(z.shape[0])
    if n < 2:
        return _skip("fewer_than_two_views")
    valid = torch.ones(n, dtype=torch.bool, device=z.device) if view_valid is None \
        else view_valid.to(z.device).bool().reshape(-1)
    if int(valid.sum()) < 2:
        return _skip("no_valid_views")

    sim = (z @ z.t()) / max(float(temperature), 1e-8)
    same = fid[:, None] == fid[None, :]
    eye = torch.eye(n, dtype=torch.bool, device=z.device)
    positive = same & ~eye

    allowed = valid[:, None] & valid[None, :] & ~eye
    if exclude_matrix is not None:
        ex = exclude_matrix.to(z.device).bool()
        excluded = ex[fid][:, fid]
        allowed = allowed & ~excluded
    # a candidate that is a positive for this anchor stays allowed
    allowed = allowed | positive

    losses = []
    n_pairs = 0
    for i in range(n):
        if not bool(valid[i]):
            continue
        pos = positive[i] & allowed[i]
        if not bool(pos.any()):
            continue
        cand = allowed[i]
        logits = sim[i][cand]
        if logits.numel() < 2:
            continue
        pos_in_cand = pos[cand]
        log_denom = torch.logsumexp(logits, dim=0)
        # mean over this anchor's positives of (logsumexp - logit_positive)
        anchor_loss = (log_denom - logits[pos_in_cand]).mean()
        losses.append(anchor_loss)
        n_pairs += int(pos_in_cand.sum())
    if not losses:
        return _skip("no_positive_view_pair", n_views=n)
    loss = torch.stack(losses).mean()
    return _result(loss, len(losses), n_views=n, n_positive_pairs=n_pairs,
                   n_excluded=int(exclude_matrix.sum()) if exclude_matrix is not None else 0)


# --------------------------------------------------------------------------------------
# B. neighbour ranking (per positive logsumexp)
# --------------------------------------------------------------------------------------
def rank_loss(scores_pos, scores_neg, *, temperature: float = 0.1,
              pos_valid=None, neg_valid=None) -> dict[str, Any]:
    """Plan 18.2 B, per positive ``p``:

    ``L(q,p) = logsumexp([s(q,p)/tau, {s(q,n)/tau for n in legal}] ) - s(q,p)/tau``

    ``scores_pos``/``scores_neg`` are per-query lists (or ``[Q,P]`` / ``[Q,C]`` arrays).
    Multiple positives never compete: each gets its own row with only its own logit.
    """
    torch = _torch()
    valid_n = _valid_count(scores_neg, neg_valid)
    if valid_n == 0:
        return _skip("no_legal_negative")
    pos_list = _as_rows(scores_pos)
    neg_list = _as_rows(scores_neg)
    if not pos_list:
        return _skip("no_positive")
    pv_list = _as_rows(pos_valid, dtype=torch.bool) if pos_valid is not None else None
    nv_list = _as_rows(neg_valid, dtype=torch.bool) if neg_valid is not None else None

    per_query = []
    skipped_queries: list[str] = []
    n_positives = 0
    for qi, pos in enumerate(pos_list):
        if pos.numel() == 0:
            skipped_queries.append("empty_positive_row")
            continue
        neg = neg_list[qi] if qi < len(neg_list) else pos.new_zeros(0)
        if nv_list is not None and qi < len(nv_list):
            neg = neg[nv_list[qi]]
        if neg.numel() == 0:
            skipped_queries.append("no_legal_negative")
            continue
        pmask = (pv_list[qi] if pv_list is not None and qi < len(pv_list)
                 else torch.ones_like(pos, dtype=torch.bool))
        sel = pos[pmask]
        if sel.numel() == 0:
            skipped_queries.append("no_valid_positive")
            continue
        rows = []
        for p in sel:
            logits = torch.cat([p.reshape(1), neg.reshape(-1)]) / max(float(temperature), 1e-8)
            rows.append(torch.logsumexp(logits, dim=0) - logits[0])
        per_query.append(torch.stack(rows).mean())
        n_positives += int(sel.numel())
    if not per_query:
        return _skip("no_query_with_positive_and_negative",
                     skipped_queries=skipped_queries[:8])
    loss = torch.stack(per_query).mean()
    return _result(loss, len(per_query), n_positives=n_positives,
                   n_negative_logits=valid_n, skipped_queries=skipped_queries[:8],
                   temperature=float(temperature))


def rank_loss_pair_head(sim_qc, overlap, *, pos_mask, neg_mask, max_q=None, max_c=None,
                        temperature: float = 0.1) -> dict[str, Any]:
    """Rank loss driven by the local pair head.

    ``sim_qc[q,c]`` is the token-similarity evidence of pair ``(q,c)`` (reduced over tokens);
    each positive forms its own competition row against the legal negatives of that query.
    """
    torch = _torch()
    q, c = sim_qc.shape
    pos_mask = pos_mask.to(torch.bool)
    neg_mask = neg_mask.to(torch.bool) & ~pos_mask
    overlap = overlap.to(torch.bool)
    per_query = []
    n_pos = 0
    for i in range(q):
        neg_idx = torch.nonzero(neg_mask[i], as_tuple=False).reshape(-1)
        if neg_idx.numel() == 0:
            continue
        neg_scores = sim_qc[i][neg_idx] / max(float(temperature), 1e-8)
        pos_idx = torch.nonzero(pos_mask[i], as_tuple=False).reshape(-1)
        rows = []
        for j in pos_idx.tolist():
            logits = torch.cat([sim_qc[i, j].reshape(1) / max(float(temperature), 1e-8), neg_scores])
            rows.append(torch.logsumexp(logits, dim=0) - logits[0])
        if rows:
            per_query.append(torch.stack(rows).mean())
            n_pos += len(rows)
    if not per_query:
        return _skip("no_query_with_pair_positive_and_negative")
    loss = torch.stack(per_query).mean()
    return _result(loss, len(per_query), n_positives=n_pos,
                   n_negative_pairs=int(neg_mask.sum()))


def _valid_count(scores, valid) -> int:
    if valid is None:
        rows = _as_rows(scores)
        return int(sum(int(r.numel()) for r in rows))
    rows = _as_rows(valid, dtype=_torch().bool)
    return int(sum(int(r.sum()) for r in rows))


def _as_rows(values, dtype=None):
    torch = _torch()
    if values is None:
        return []
    if isinstance(values, (list, tuple)):
        out = []
        for v in values:
            t = v if torch.is_tensor(v) else torch.as_tensor(np.asarray(v))
            out.append(t.reshape(-1).to(dtype) if dtype is not None else t.reshape(-1))
        return out
    t = values if torch.is_tensor(values) else torch.as_tensor(np.asarray(values))
    if t.dim() == 1:
        return [t]
    out = []
    for i in range(t.shape[0]):
        row = t[i].reshape(-1)
        out.append(row.to(dtype) if dtype is not None else row)
    return out


# --------------------------------------------------------------------------------------
# C. local correspondence with dustbin (masked soft-target CE) / optional Sinkhorn
# --------------------------------------------------------------------------------------
def correspondence_loss(sim_matrix, weight, *, row_valid=None, col_valid=None,
                        mode: str = "masked_ce", temperature: float = 0.1,
                        dustbin_logit: float = -2.0, sinkhorn_cfg: Mapping[str, Any] | None = None,
                        source_group: Any = None, row_weight: Any = None) -> dict[str, Any]:
    """Many-to-many correspondence supervision (plan 30.11).

    ``weight[q,c,i,j]`` is the non-negative edge weight ``W`` of the physical patch groups;
    a row is normalised into a multi-candidate target distribution, and unknown rows are
    masked entirely.  ``dustbin_logit`` is available as an explicit "no target" option: an
    empty ``W`` row means *no target*, a masked row means *unknown* -- the two are never mixed.

    ``source_group[q,c,i]`` (optional) marks the capture source of a query token; duplicate
    tokens that come from the same capture share a group and are aggregated before weighting,
    so one capture cannot contribute multiple independent physical evidences.
    """
    torch = _torch()
    sim = sim_matrix
    if sim.dim() != 4:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"correspondence_loss expects [Q,C,I,J] similarity, got {tuple(sim.shape)}",
                          stage="training.losses.correspondence_loss")
    q, c, i_dim, j_dim = sim.shape
    w = weight.to(sim.dtype)
    if tuple(w.shape) != tuple(sim.shape):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"weight shape {tuple(w.shape)} != similarity shape {tuple(sim.shape)}",
                          stage="training.losses.correspondence_loss")
    rv = (torch.ones((q, c, i_dim), dtype=torch.bool, device=sim.device) if row_valid is None
          else row_valid.to(sim.device).bool())
    cv = (torch.ones((q, c, j_dim), dtype=torch.bool, device=sim.device) if col_valid is None
          else col_valid.to(sim.device).bool())
    if tuple(rv.shape) != (q, c, i_dim) or tuple(cv.shape) != (q, c, j_dim):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "correspondence validity shapes mismatch",
                          stage="training.losses.correspondence_loss")

    w = torch.where(cv.unsqueeze(-2), w, torch.zeros_like(w))
    row_sum = w.sum(dim=-1)
    unknown_rows = (~rv) | (row_sum <= 0)
    # explicit "no target": a *valid* row whose W is all zero -> dustbin
    dustbin_rows = rv & (row_sum <= 0)
    supervised_rows = rv & (row_sum > 0)
    n_valid = int(supervised_rows.sum())
    if n_valid == 0:
        return _skip("no_supervised_correspondence_row",
                     unknown_rows=int(unknown_rows.sum()),
                     explicit_dustbin_rows=int(dustbin_rows.sum()))

    target = w / row_sum.clamp(min=1e-12).unsqueeze(-1)
    # a collinear warp plus the dustbin column
    scored = sim / max(float(temperature), 1e-8)
    scored = torch.where(cv.unsqueeze(-2), scored, torch.full_like(scored, -1e4))
    dust = torch.full((q, c, i_dim, 1), float(dustbin_logit) / max(float(temperature), 1e-8),
                      device=sim.device, dtype=sim.dtype)
    logits = torch.cat([scored, dust], dim=-1)
    target_full = torch.cat([target, torch.zeros_like(dust)], dim=-1)

    if mode == "masked_ce":
        logp = torch.log_softmax(logits, dim=-1)
        per_row = -(target_full * logp).sum(dim=-1)      # [Q,C,I]
        row_mass = row_sum
        if source_group is not None:
            row_mass = _group_aggregate(row_mass, source_group.to(sim.device))
        denom = row_mass.masked_fill(~supervised_rows, 0.0).sum().clamp(min=1e-8)
        loss = (per_row * row_mass).masked_fill(~supervised_rows, 0.0).sum() / denom
        aux = {"mode": "masked_ce", "n_supervised_rows": n_valid,
               "n_explicit_dustbin_rows": int(dustbin_rows.sum()),
               "aggregated_mass": float(denom.detach())}
    elif mode == "sinkhorn":
        cfg = dict(sinkhorn_cfg or {})
        plan, aux = _sinkhorn_plan(logits, weight, cv, rv, dustbin_logit=dustbin_logit,
                                   n_iters=int(cfg.get("n_iters", 20)),
                                   epsilon=float(cfg.get("epsilon", 1.0)),
                                   row_mass=cfg.get("row_mass"), col_mass=cfg.get("col_mass"),
                                   unmatched_mass=float(cfg.get("unmatched_mass", 1.0)))
        total = weight.sum(dim=-1)
        denom = total.masked_fill(~supervised_rows, 0.0).sum()
        matched = (plan * weight).sum(dim=(-1, -2)).masked_fill(~supervised_rows, 0.0)
        loss = 1.0 - matched.sum() / denom.clamp(min=1e-8)
        aux.update({"mode": "sinkhorn", "n_supervised_rows": n_valid,
                    "mean_transport_mass": float(plan.sum().detach())})
    else:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown correspondence mode {mode!r}",
                          stage="training.losses.correspondence_loss")
    return _result(loss, n_valid, **aux)


def _group_aggregate(values, source_group):
    """Aggregate per-token values across tokens sharing one capture-source group."""
    torch = _torch()
    if source_group.dim() == 2:
        source_group = source_group.unsqueeze(1).expand(-1, values.shape[1], -1)
    if tuple(source_group.shape) != tuple(values.shape):
        return values
    out = torch.zeros_like(values)
    flat_key = source_group.reshape(values.shape[0], values.shape[1], values.shape[2])
    for q in range(values.shape[0]):
        for c in range(values.shape[1]):
            keys = flat_key[q, c]
            uniq = torch.unique(keys)
            for k in uniq.tolist():
                m = keys == k
                out[q, c, m] = values[q, c, m].mean()
    return out


def _sinkhorn_plan(logits, weight, col_valid, row_valid, *, dustbin_logit, n_iters, epsilon,
                   row_mass, col_mass, unmatched_mass):
    """Differentiable partial-assignment Sinkhorn with declared capacity marginals.

    Capacities: row (query token) capacity from its valid footprint mass, column (candidate
    token) capacity from its valid footprint mass, plus an explicit unmatched mass.  There is
    **no** unit-capacity one-to-one assumption (plan 30.11): a row may legitimately spread over
    several columns and vice versa.
    """
    torch = _torch()
    q, c, i_dim, j_dim = logits.shape
    if row_mass is None:
        r = torch.ones((q, c, i_dim), dtype=logits.dtype, device=logits.device)
    else:
        r = torch.as_tensor(row_mass, dtype=logits.dtype, device=logits.device) \
            .expand(q, c, i_dim).clone()
    r = r * row_valid.to(logits.dtype)
    if col_mass is None:
        col = torch.ones((q, c, j_dim), dtype=logits.dtype, device=logits.device)
    else:
        col = torch.as_tensor(col_mass, dtype=logits.dtype, device=logits.device) \
            .expand(q, c, j_dim).clone()
    col = col * col_valid.to(logits.dtype)

    # target marginal on the candidate side: the physical W column sums (normalised), so
    # column capacity follows actual surface footprint rather than a uniform assumption.
    col_target = weight.sum(dim=-2)
    col_target = col_target * col_valid.to(logits.dtype)
    norm = col_target.sum(dim=-1, keepdim=True).clamp(min=1e-8)
    col_target = col_target / norm * unmatched_mass

    logK = logits / max(float(epsilon), 1e-6)
    logK = logK - logK.amax(dim=(-1, -2), keepdim=True).detach()
    K = torch.exp(logK)
    K = K * (col_valid.unsqueeze(-2).to(logits.dtype) * row_valid.unsqueeze(-1).to(logits.dtype))
    u = torch.ones_like(r)
    v = torch.ones_like(col_target)
    for _ in range(int(n_iters)):
        Kv = torch.einsum("qcij,qcj->qci", K, v).clamp(min=1e-12)
        u = r / Kv
        Ktu = torch.einsum("qcij,qci->qcj", K, u).clamp(min=1e-12)
        v = col_target / Ktu
    plan = u.unsqueeze(-1) * K * v.unsqueeze(-2)
    aux = {"epsilon": float(epsilon), "n_iters": int(n_iters),
           "declared_row_capacity": float(r.sum().detach()),
           "declared_col_capacity": float(col_target.sum().detach()),
           "unmatched_mass": float(unmatched_mass)}
    return plan, aux


# --------------------------------------------------------------------------------------
# D. quality estimation
# --------------------------------------------------------------------------------------
def quality_loss(prediction, target, valid, *, kind: str = "huber", delta: float = 1.0,
                 buckets: int | None = None, bucket_edges: Sequence[float] | None = None) -> dict[str, Any]:
    """Huber regression or bucketed CE on ``OBS_EST`` quality channels.

    ``valid`` is per channel and per target source, so an unavailable channel never becomes a
    zero label.  ``prediction`` is the model's observation-only estimate; ``target`` comes from
    the label side (``GT_ORACLE`` allowed) and is never copied into the input features.
    """
    torch = _torch()
    p = prediction
    t = target.to(p.dtype)
    v = valid.to(p.device).bool()
    if tuple(v.shape) != tuple(p.shape):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"quality valid shape {tuple(v.shape)} != prediction {tuple(p.shape)}",
                          stage="training.losses.quality_loss")
    n_valid = int(v.sum())
    if n_valid == 0:
        return _skip("no_valid_quality_target")

    if kind == "huber":
        per = torch.nn.functional.huber_loss(p, t, reduction="none", delta=float(delta))
        loss = (per * v.to(p.dtype)).sum() / v.to(p.dtype).sum().clamp(min=1e-8)
        aux = {"kind": "huber", "delta": float(delta),
               "mae": float(((p - t).abs() * v).sum().detach() / max(n_valid, 1))}
    elif kind == "bucket_ce":
        n_buckets = int(buckets or 0)
        if n_buckets <= 1:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "bucket_ce needs buckets >= 2",
                              stage="training.losses.quality_loss")
        labels = _to_bucket_labels(t, n_buckets, bucket_edges)
        if p.shape[-1] == n_buckets:
            logits = p
        elif p.shape[-1] == 1:
            logits = p.expand(*p.shape[:-1], n_buckets)
        elif p.shape[-1] == t.shape[-1] * n_buckets:
            logits = p.reshape(*p.shape[:-1], t.shape[-1], n_buckets)
        else:
            raise SynLabError(
                ErrorCode.SCHEMA_INVALID,
                f"bucket_ce prediction last dim {p.shape[-1]} cannot map to {n_buckets} buckets",
                stage="training.losses.quality_loss")
        per = torch.nn.functional.cross_entropy(
            logits.reshape(-1, n_buckets), labels.reshape(-1).to(logits.device), reduction="none")
        per = per.reshape(v.shape)
        loss = (per * v.to(p.dtype)).sum() / v.to(p.dtype).sum().clamp(min=1e-8)
        aux = {"kind": "bucket_ce", "buckets": n_buckets}
    else:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown quality loss kind {kind!r}",
                          stage="training.losses.quality_loss")
    return _result(loss, n_valid, **aux)


def _to_bucket_labels(target, n_buckets: int, edges: Sequence[float] | None):
    torch = _torch()
    if edges is not None:
        e = torch.as_tensor(list(edges), dtype=target.dtype, device=target.device)
        labels = torch.bucketize(target, e)
        return labels.clamp(0, n_buckets - 1).to(torch.long)
    t = target
    looks_integer = bool(torch.all(t == t.round()).item()) if t.numel() else False
    if looks_integer and float(t.min()) >= 0.0 and float(t.max()) <= n_buckets - 1:
        return t.round().to(torch.long)
    scaled = (t - t.min()) / (t.max() - t.min()).clamp(min=1e-8)
    return (scaled * (n_buckets - 1)).round().to(torch.long)


# --------------------------------------------------------------------------------------
# E. contradiction / compatibility
# --------------------------------------------------------------------------------------
def contradiction_loss(logits, labels, valid, *, class_weights=None) -> dict[str, Any]:
    """R1 / contradicting-negative supervision; ``missing`` is masked separately.

    Label codes: ``0=missing 1=compatible 2=contradicting``.  ``valid`` excludes the
    ``missing`` rows (and rows whose construct is not trustworthy) from the denominator.
    """
    torch = _torch()
    v = valid.to(logits.device).bool()
    if tuple(v.shape) != tuple(labels.shape):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"contradiction valid shape {tuple(v.shape)} != labels {tuple(labels.shape)}",
                          stage="training.losses.contradiction_loss")
    n_valid = int(v.sum())
    if n_valid == 0:
        return _skip("no_valid_contradiction_label",
                     missing=int((labels == 0).sum()))
    target = labels.to(logits.device).long().reshape(-1)
    if logits.shape[-1] != 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"contradiction logits last dim {logits.shape[-1]} != 3",
                          stage="training.losses.contradiction_loss")
    flat_logits = logits.reshape(-1, 3)
    flat_valid = v.reshape(-1)
    weight = None
    if class_weights is not None:
        weight = torch.as_tensor(list(class_weights), dtype=logits.dtype, device=logits.device)
    per = torch.nn.functional.cross_entropy(flat_logits, target, reduction="none", weight=weight)
    loss = (per * flat_valid.to(per.dtype)).sum() / flat_valid.to(per.dtype).sum().clamp(min=1e-8)
    return _result(loss, n_valid, missing=int((labels == 0).sum()),
                   compatible=int((labels == 1).sum()), contradicting=int((labels == 2).sum()))


# --------------------------------------------------------------------------------------
# Multi-task combination
# --------------------------------------------------------------------------------------
def _weight_of(loss_weights: Any, name: str) -> float:
    if loss_weights is None:
        return DEFAULT_WEIGHTS[name]
    if isinstance(loss_weights, Mapping):
        return float(loss_weights.get(name, 0.0))
    return float(getattr(loss_weights, name, 0.0))


@dataclass
class MultiTaskLoss:
    """Weighted combination of the five task losses (defaults ``1/.1/.1/.05/.1``)."""

    loss_weights: Any = None
    n_present: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    skipped_reasons: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.reset_counters()

    def reset_counters(self) -> None:
        self.n_present = {t: 0 for t in TASK_ORDER}
        self.skipped = {t: 0 for t in TASK_ORDER}
        self.skipped_reasons = {}

    def combine(self, results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        """Combine task results, counting skipped tasks explicitly.

        Every entry carries three supervision numbers, which are *not* the same thing:

        ``n_valid``
            rows the loss really consumed (its denominator); 0 for a skipped task;
        ``n_allowed``
            rows that survived every mask the task applies (equals ``n_valid`` when present);
        ``n_valid_labels``
            label rows that exist and are valid *before* encodability is considered.  A task with
            ``n_valid_labels > 0`` and ``n_valid == 0`` is *blocked*, not unlabelled -- the
            distinction a supervision report needs (see ``synlab.training.supervision``).
        """
        torch = _torch()
        total = None
        report: dict[str, Any] = {}
        for name, res in results.items():
            present = res is not None and res.get("loss") is not None and not res.get("skipped", False)
            self.n_present[name] = self.n_present.get(name, 0) + (1 if present else 0)
            weight = _weight_of(self.loss_weights, name)
            if not present:
                n_labels = int((res or {}).get("n_valid_labels", 0) or 0)
                self.skipped[name] = self.skipped.get(name, 0) + 1
                self.skipped_reasons[name] = (res or {}).get("reason") or "no_valid_supervision"
                report[name] = {"skipped": True,
                                "reason": self.skipped_reasons[name],
                                "weight": weight, "loss": None, "n_valid": 0,
                                "n_allowed": 0, "n_valid_labels": n_labels,
                                "effective_supervision_ratio": 0.0,
                                "diagnostics": (res or {}).get("diagnostics", {})}
                continue
            loss = res["loss"]
            contribution = loss * weight
            total = contribution if total is None else total + contribution
            report[name] = {"skipped": False, "reason": None, "weight": weight,
                            "loss": float(loss.detach()),
                            "weighted": float(contribution.detach()),
                            "n_valid": int(res.get("n_valid", 0)),
                            "n_allowed": int(res.get("n_valid", 0)),
                            "n_valid_labels": int(res.get("n_valid_labels",
                                                          res.get("n_valid", 0)) or 0),
                            "effective_supervision_ratio": _supervision_ratio(res),
                            "diagnostics": res.get("diagnostics", {})}
        if total is None:
            return {"loss": None, "report": report, "all_skipped": True,
                    "skipped_tasks": sorted(self.skipped_reasons)}
        return {"loss": total, "report": report, "all_skipped": False,
                "skipped_tasks": sorted(self.skipped_reasons)}

    def task_report(self) -> dict[str, Any]:
        return {"n_present": dict(self.n_present), "skipped": dict(self.skipped),
                "skipped_reasons": dict(self.skipped_reasons),
                "weights": {t: _weight_of(self.loss_weights, t) for t in TASK_ORDER}}


def _supervision_ratio(res: Mapping[str, Any]) -> float:
    diag = res.get("diagnostics") or {}
    for key in ("n_present", "n_candidates", "n_rows"):
        if key in diag and diag[key]:
            return float(res.get("n_valid", 0)) / float(diag[key])
    if "n_visible_tokens" in diag and diag["n_visible_tokens"]:
        return float(res.get("n_valid", 0)) / float(diag["n_visible_tokens"])
    n_valid = int(res.get("n_valid", 0))
    return 1.0 if n_valid > 0 else 0.0


def task_gradient_norms(loss_tensors: Mapping[str, Any], parameters: Sequence[Any], *,
                        retain_graph: bool = False) -> dict[str, float | None]:
    """Per-task gradient norms on the shared parameters (plan 18.3).

    A task whose gradient is not finite is reported as ``None`` with the reason, never as 0.
    """
    torch = _torch()
    out: dict[str, float | None] = {}
    for name, tensor in loss_tensors.items():
        if tensor is None or not torch.is_tensor(tensor) or not tensor.requires_grad:
            out[name] = None
            continue
        grads = torch.autograd.grad(tensor, list(parameters), retain_graph=retain_graph,
                                    allow_unused=True)
        total = 0.0
        for g in grads:
            if g is None:
                continue
            total += float(g.detach().pow(2).sum())
        value = total ** 0.5
        out[name] = value if np.isfinite(value) else None
    return out


__all__ = [
    "DEFAULT_WEIGHTS", "TASK_ORDER", "MultiTaskLoss",
    "view_infonce", "rank_loss", "rank_loss_pair_head", "correspondence_loss",
    "quality_loss", "contradiction_loss", "task_gradient_norms",
]
