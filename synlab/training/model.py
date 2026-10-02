"""Dual-tower first stage, local refinement head, and classical shallow baselines.

Frozen interface (plan 30.10):

* :meth:`FragmentEncoder.encode_fragment` -> L2-normalised ``z[D]`` -- the **only** vector
  that may be put into a whole-gallery index;
* :meth:`PairRefineHead.score_pair` -> a per-pair ``refine_logit`` -- because every pair owns
  its own vector, pair-head outputs are explicitly **not cacheable** and must never be
  searched with FAISS / an independent-vector index.  This is enforced in code by
  :meth:`PairRefineHead.cacheable_vector` raising, and by :func:`assert_cacheable_index_ok`.

Missing observations are handled with validity masks and gates: a branch with no valid entry
contributes exactly 0 with gate 0, and a fragment with no legal modality at all is reported
``valid=False`` instead of being turned into an all-padding embedding or a "valid" zero vector.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from .adapter import FEATURE_SCHEMA, TOKEN_DIM, TorchFeatureBundle

MODEL_VERSION = "a12.dual_tower.v1"
PAIR_HEAD_VERSION = "a12.pair_refine.v1"
CLASSICAL_VERSION = "a12.classical.v1"

#: token-policy identity: which tokens are selected and how multiple tokens from one capture
#: are grouped.  Any change invalidates cached features (plan 18.1).
TOKEN_POLICY = {
    "schema": "token_policy.v1",
    "budget_default": 256,
    "budget_choices": [128, 256, 512],
    "stratify": ["view", "capture_source", "spatial_bin"],
    "order_within_stratum": "obs_est_quality_desc_then_index",
    "min_roi_quota": 8,
    "over_quota": "keep_retrieval_index",
    "source_grouping": "shared_capture_source_not_reweighted",
}


def _torch():
    import torch

    return torch


# --------------------------------------------------------------------------------------
# Token grouping helper (plan 30.11): duplicate tokens from one capture share a group
# --------------------------------------------------------------------------------------
def source_group_weights(token_source, token_valid, *, renormalise: bool = True):
    """Weight per token so that one capture source contributes at most 1 unit of evidence."""
    torch = _torch()
    src = token_source.clone()
    src[~token_valid] = -1
    weights = torch.zeros_like(src, dtype=torch.float32)
    valid_src = src >= 0
    if valid_src.any():
        index = src.masked_fill(~valid_src, 0).reshape(-1)
        counts = torch.zeros(int(src.max().item()) + 1 if valid_src.any() else 1,
                             device=src.device, dtype=torch.float32)
        counts = counts.index_add(0, index.reshape(-1), valid_src.reshape(-1).float())
        gathered = counts[index].reshape(src.shape)
        weights = torch.where(valid_src, 1.0 / gathered.clamp(min=1.0), torch.zeros_like(gathered))
    if renormalise:
        denom = weights.sum(dim=1, keepdim=True).clamp(min=1e-8)
        weights = weights / denom
    return weights


def masked_mean(values, valid, weights=None):
    """Masked mean over the token axis.

    ``values`` is ``[N, L, D]`` with ``valid``/``weights`` of shape ``[N, L]`` -> ``[N, D]``; a
    row with no valid entry is an exact zero vector.  A 2-D ``values`` of shape ``[N, L]`` is
    also accepted and returns ``[N]``.
    """
    torch = _torch()
    if values.dim() == 2:
        return masked_mean_row(values, valid, weights)
    w = valid.float() if weights is None else (weights * valid.float())
    denom = w.sum(dim=-1, keepdim=True)
    pooled = (values * w.unsqueeze(-1)).sum(dim=-2)
    return pooled / denom.clamp(min=1e-8)


def masked_mean_row(values, valid, weights=None):
    """Masked mean over the last axis of a 2-D ``[N, L]`` tensor -> ``[N]``."""
    torch = _torch()
    w = valid.float() if weights is None else (weights * valid.float())
    denom = w.sum(dim=-1)
    pooled = (values * w).sum(dim=-1)
    return pooled / denom.clamp(min=1e-8)


def masked_fill_mean(values, valid):
    """Keep per-channel identity: invalid entries take the row mean of the valid entries.

    ``values``/``valid`` are ``[N, D]``; the output is ``[N, D]`` (a row with no valid channel
    becomes an exact zero row, which the caller must treat as *absent*, not as a measurement).
    """
    torch = _torch()
    v = valid.to(values.dtype)
    mean = masked_mean_row(values, valid).unsqueeze(-1)
    filled = torch.where(valid, values, mean.expand_as(values))
    return torch.where(v.sum(dim=-1, keepdim=True) > 0, filled, torch.zeros_like(filled))


# --------------------------------------------------------------------------------------
# Fragment encoder (first stage, cacheable)
# --------------------------------------------------------------------------------------
class FragmentEncoder:
    """Dual-tower fragment encoder producing L2-normalised ``z[D]`` from observed features.

    Sub-modules:

    * ``global_branch``: RGB conv stack with ``global_valid`` masked pooling over views;
    * ``geometry_branch``: point/normal encoder gated by ``point_valid`` / ``normal_valid``
      and hard-gated by ``scale_valid`` (untrusted scale never enters the 3D tower);
    * ``quality_branch``: ``OBS_EST`` quality / presence MLP (never an oracle target);
    * ``proj``: projection head to the retrieval dimension.
    """

    def __init__(self, *, token_dim: int = TOKEN_DIM, out_dim: int = 64, width: int = 32,
                 quality_channels: int = 4, presence_channels: int = 3, seed: int = 0,
                 normalize: bool = True, temperature: float = 0.07,
                 quality_target_dim: int | None = None,
                 quality_input_dim: int | None = None) -> None:
        torch = _torch()
        nn = torch.nn
        g = torch.Generator().manual_seed(int(seed))
        self.out_dim = int(out_dim)
        self.normalize = bool(normalize)
        self.temperature = float(temperature)
        self.token_dim = int(token_dim)
        self.index_kind = "fragment_encoder"
        self.quality_input_dim = int(quality_input_dim or (quality_channels + presence_channels))

        #: view-embedding branch: ends at ``width`` so every branch contributes equally to fusion
        self.global_branch = nn.Sequential(
            nn.Conv2d(3, width, 3, stride=2, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(width, width * 2, 3, stride=2, padding=1), nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d(1), nn.Flatten(),
            nn.Linear(width * 2, width * 2), nn.ReLU(inplace=True),
            nn.Linear(width * 2, width), nn.ReLU(inplace=True),
        )
        self.geometry_branch = nn.Sequential(nn.Linear(6, width), nn.ReLU(inplace=True),
                                            nn.Linear(width, width), nn.ReLU(inplace=True))
        self.token_branch = nn.Sequential(nn.Linear(token_dim, width), nn.ReLU(inplace=True),
                                         nn.Linear(width, width), nn.ReLU(inplace=True))
        self.quality_branch = nn.Sequential(
            nn.Linear(self.quality_input_dim, width), nn.ReLU(inplace=True),
            nn.Linear(width, width), nn.ReLU(inplace=True))
        # D-task head: predicts OBS_EST quality channels from observation-only inputs.
        # ``quality_channels`` here is the *flattened* (region x channel) dimension, so the
        # head can regress every (region, channel) target independently.
        self.quality_head = nn.Linear(width, max(int(quality_target_dim or quality_channels), 1))
        self.quality_out_features = max(int(quality_target_dim or quality_channels), 1)
        self.gate = nn.Sequential(nn.Linear(width * 4, width * 2), nn.ReLU(inplace=True),
                                 nn.Linear(width * 2, 3))
        self.proj = nn.Linear(width * 2, out_dim)
        # deterministic initialisation so two runs from the same seed agree
        for module in self.modules():
            if isinstance(module, nn.Linear):
                with torch.no_grad():
                    module.weight.copy_(torch.randn(module.weight.shape, generator=g) * 0.05)
                    if module.bias is not None:
                        module.bias.zero_()
            elif isinstance(module, nn.Conv2d):
                with torch.no_grad():
                    module.weight.copy_(torch.randn(module.weight.shape, generator=g) * 0.05)
                    if module.bias is not None:
                        module.bias.zero_()

    # -- parameters -------------------------------------------------------------------
    #: sub-modules in a fixed order, so state_dict round-trips are stable
    SUB_MODULES = ("global_branch", "geometry_branch", "token_branch", "quality_branch",
                   "quality_head", "gate", "proj")

    def parameters(self):
        for sub in self.SUB_MODULES:
            yield from getattr(self, sub).parameters()

    def named_parameters(self, prefix: str = ""):
        for sub in self.SUB_MODULES:
            for name, p in getattr(self, sub).named_parameters(prefix=f"{prefix}{sub}."):
                yield name, p

    def train(self, mode: bool = True):
        for sub in self.SUB_MODULES:
            getattr(self, sub).train(mode)
        return self

    def eval(self):
        return self.train(False)

    def modules(self):
        for sub in self.SUB_MODULES:
            yield getattr(self, sub)

    def state_dict(self):
        out = {}
        for sub in self.SUB_MODULES:
            for k, v in getattr(self, sub).state_dict().items():
                out[f"{sub}.{k}"] = v
        return out

    def load_state_dict(self, state):
        for sub in self.SUB_MODULES:
            prefix = f"{sub}."
            sub_state = {k[len(prefix):]: v for k, v in state.items() if k.startswith(prefix)}
            if sub_state:
                getattr(self, sub).load_state_dict(sub_state)
        return self

    def to(self, device):
        for module in self.modules():
            module.to(device)
        return self

    def zero_grad(self):
        for module in self.modules():
            module.zero_grad(set_to_none=True)

    # -- forward ----------------------------------------------------------------------
    def _quality_input(self, features):
        """Observation-only quality/presence vector ``[F, Cq*R + Cm]`` (never an oracle target).

        Each channel keeps its identity; an unavailable channel is replaced by the row mean of
        the available channels (masked imputation, recorded in ``diagnostics``).
        """
        torch = _torch()
        f = features.global_rgb.shape[0]
        q = masked_fill_mean(features.quality.reshape(f, -1),
                            features.quality_valid.reshape(f, -1))
        p = masked_fill_mean(features.presence, features.presence_valid)
        return torch.cat([q, p], dim=-1)

    def encode(self, features: TorchFeatureBundle, return_parts: bool = False):
        """Return ``(z[F,D], valid[F] bool, parts)``; ``z`` is zero for invalid fragments."""
        torch = _torch()
        rgb = features.global_rgb                       # [F,V,3,H,W]
        f, v = rgb.shape[0], rgb.shape[1]
        flat = rgb.reshape(f * v, 3, rgb.shape[-2], rgb.shape[-1])
        emb = self.global_branch(flat).reshape(f, v, -1)
        view_valid = features.global_valid
        rgb_vec = masked_mean(emb, view_valid)
        rgb_gate = view_valid.any(dim=1).float()

        # geometry: [points, normals] mean over valid points, hard-gated by scale_valid
        pts = features.points
        nrm = features.normals
        pv = features.point_valid
        nv = features.normal_valid
        both = pv & nv
        scale_ok = features.scale_valid & (pv.any(dim=1) | nv.any(dim=1))
        geo_in = torch.cat([pts, nrm], dim=-1)          # [F,N,6]
        w = (pv | nv) & features.scale_valid[:, None]
        geo_vec = masked_mean(geo_in, w)
        geo_gate = (w.any(dim=1)).float()

        tok_vec = masked_mean(features.local_tokens, features.token_valid)
        tok_gate = features.token_valid.any(dim=1).float()

        q = features.quality
        qv = features.quality_valid
        qp = self._quality_input(features)
        qual_vec = self.quality_branch(qp.to(self._dtype()))

        geo_vec = self.geometry_branch(geo_vec.to(self._dtype()))
        tok_vec = self.token_branch(tok_vec.to(self._dtype()))
        rgb_vec = rgb_vec.to(self._dtype())

        gate_logits = self.gate(torch.cat([rgb_vec, geo_vec, tok_vec, qual_vec], dim=-1))
        gates = torch.sigmoid(gate_logits)
        gates = gates * torch.stack([rgb_gate, geo_gate, tok_gate], dim=-1).to(gates.dtype)
        mass = gates.sum(dim=-1)
        fused = (torch.stack([rgb_vec, geo_vec, tok_vec], dim=1) * gates.unsqueeze(-1)).sum(dim=1)
        fused = fused / mass.clamp(min=1e-6).unsqueeze(-1)

        z = self.proj(fused)
        valid = (rgb_gate + geo_gate + tok_gate) > 0
        z = torch.where(valid.unsqueeze(-1), z, torch.zeros_like(z))
        if self.normalize:
            z = torch.nn.functional.normalize(z, dim=-1)
        parts = {"gates": gates, "gate_mass": mass, "rgb_gate": rgb_gate,
                 "geometry_gate": geo_gate, "token_gate": tok_gate,
                 "scale_gated_out": (~features.scale_valid).float()}
        if return_parts:
            return z, valid, parts
        return z, valid

    def _dtype(self):
        return self.proj.weight.dtype

    def encode_quality(self, features: TorchFeatureBundle):
        """Observation-only quality estimate ``[F, quality_out_features]`` (task D input).

        The input is ``OBS_EST`` quality/presence; oracle targets never enter this path.
        """
        torch = _torch()
        hidden = self.quality_branch(self._quality_input(features).to(self._dtype()))
        return self.quality_head(hidden)

    def encode_fragment(self, features: TorchFeatureBundle):
        """Frozen façade: ``encode_fragment(features) -> (z[F,D], valid[F])``."""
        return self.encode(features)

    def encode_batch(self, features: TorchFeatureBundle) -> tuple[np.ndarray, np.ndarray]:
        """Numpy view used by retrieval / diagnostics (no grad)."""
        torch = _torch()
        was_training = self.proj.training
        self.eval()
        with torch.no_grad():
            z, valid = self.encode(features)
        if was_training:
            self.train(True)
        return z.detach().cpu().numpy(), valid.detach().cpu().numpy()

    # -- identity ---------------------------------------------------------------------
    def index_identity(self, *, input_hash: str = "", cache_version: str = "") -> dict:
        return {
            "index_kind": self.index_kind,
            "model_version": MODEL_VERSION,
            "encoder_version": f"{MODEL_VERSION}:dim{self.out_dim}",
            "input_schema": FEATURE_SCHEMA,
            "input_hash": input_hash,
            "token_policy_hash": hash_json(TOKEN_POLICY),
            "cache_version": cache_version,
            "normalized": self.normalize,
            "distance": "inner_product_on_l2_normalized",
        }


# --------------------------------------------------------------------------------------
# Local refinement head (per pair, NOT cacheable)
# --------------------------------------------------------------------------------------
class PairRefineHead:
    """``score_pair(query_tokens, candidate_tokens) -> refine_logit``.

    The head is attention/pooling based, so there is no per-fragment vector to index.  The
    class deliberately exposes no cacheable embedding: :meth:`cacheable_vector` raises
    :class:`SynLabError` so that no caller can accidentally build a FAISS index of pair-head
    outputs (plan 30.10).
    """

    def __init__(self, *, token_dim: int = TOKEN_DIM, width: int = 32, seed: int = 0,
                 temperature: float = 0.07) -> None:
        torch = _torch()
        nn = torch.nn
        g = torch.Generator().manual_seed(int(seed) + 977)
        self.token_dim = int(token_dim)
        self.temperature = float(temperature)
        self.pair_head_version = PAIR_HEAD_VERSION
        self.q_proj = nn.Linear(token_dim, width)
        self.c_proj = nn.Linear(token_dim, width)
        self.mlp = nn.Sequential(nn.Linear(width * 4, width * 2), nn.ReLU(inplace=True),
                                 nn.Linear(width * 2, 1))
        self.logit_scale = nn.Parameter(torch.tensor(1.0 / max(float(temperature), 1e-6)))
        for module in (self.q_proj, self.c_proj, *[m for m in self.mlp if isinstance(m, nn.Linear)]):
            with torch.no_grad():
                module.weight.copy_(torch.randn(module.weight.shape, generator=g) * 0.05)
                if module.bias is not None:
                    module.bias.zero_()

    # -- parameters -------------------------------------------------------------------
    def parameters(self):
        yield self.logit_scale
        for module in (self.q_proj, self.c_proj, self.mlp):
            yield from module.parameters()

    def named_parameters(self, prefix: str = ""):
        yield f"{prefix}logit_scale", self.logit_scale
        for sub in ("q_proj", "c_proj", "mlp"):
            for name, p in getattr(self, sub).named_parameters(prefix=f"{prefix}{sub}."):
                yield name, p

    def modules(self):
        yield self.q_proj
        yield self.c_proj
        yield self.mlp

    def to(self, device):
        for module in self.modules():
            module.to(device)
        return self

    def train(self, mode: bool = True):
        for module in self.modules():
            module.train(mode)
        return self

    def eval(self):
        return self.train(False)

    def zero_grad(self):
        for module in self.modules():
            module.zero_grad(set_to_none=True)

    def state_dict(self):
        out = {"logit_scale": self.logit_scale.detach().clone()}
        for sub in ("q_proj", "c_proj", "mlp"):
            for k, v in getattr(self, sub).state_dict().items():
                out[f"{sub}.{k}"] = v
        return out

    def load_state_dict(self, state):
        if "logit_scale" in state:
            with _torch().no_grad():
                self.logit_scale.copy_(state["logit_scale"])
        for sub in ("q_proj", "c_proj", "mlp"):
            prefix = f"{sub}."
            sub_state = {k[len(prefix):]: v for k, v in state.items() if k.startswith(prefix)}
            if sub_state:
                getattr(self, sub).load_state_dict(sub_state)
        return self

    # -- forward ----------------------------------------------------------------------
    def score_pair(self, query_tokens, candidate_tokens, *, query_valid=None, cand_valid=None):
        """Return ``refine_logit`` of shape ``[Q, C]``.

        ``query_tokens``/``candidate_tokens`` may be ``[Q,L,D]`` / ``[C,L,D]`` or already
        broadcast ``[Q,C,L,D]``.  Validities mask padded tokens; a pair with no overlapping
        valid token mass gets a large negative logit instead of a NaN.
        """
        torch = _torch()
        q = query_tokens
        c = candidate_tokens
        if q.dim() == 3 and c.dim() == 3:
            q = q.unsqueeze(1)
            c = c.unsqueeze(0)
        if q.dim() != 4 or c.dim() != 4:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"score_pair expects [Q,L,D]/[C,L,D] or [Q,C,L,D], got "
                              f"{tuple(query_tokens.shape)}/{tuple(candidate_tokens.shape)}",
                              stage="training.model.PairRefineHead.score_pair")
        qh = self.q_proj(q.to(self._dtype()))
        ch = self.c_proj(c.to(self._dtype()))
        qv = (torch.ones_like(qh[..., 0], dtype=torch.bool) if query_valid is None
              else _expand_valid(query_valid, qh))
        cv = (torch.ones_like(ch[..., 0], dtype=torch.bool) if cand_valid is None
              else _expand_valid(cand_valid, ch))
        sim = torch.einsum("qcid,qcjd->qcij", qh, ch) / max(float(qh.shape[-1]) ** 0.5, 1.0)
        neg_inf = torch.finfo(sim.dtype).min / 8
        keep = qv.unsqueeze(-1) & cv.unsqueeze(-2)
        sim = torch.where(keep, sim, torch.full_like(sim, neg_inf))
        max_q = sim.max(dim=-1).values.clamp(min=neg_inf / 2)   # [Q,C,I] best candidate per q token
        max_c = sim.max(dim=-2).values.clamp(min=neg_inf / 2)   # [Q,C,J]
        any_keep = keep.any(dim=-1)                             # [Q,C,I]
        any_keep_c = keep.any(dim=-2)                           # [Q,C,J]
        pooled_q = _masked_mean_dim(max_q, any_keep, dim=-1)
        pooled_c = _masked_mean_dim(max_c, any_keep_c, dim=-1)
        overlap = (any_keep.any(dim=-1) & any_keep_c.any(dim=-1)).to(qh.dtype)
        sim_mean = _masked_mean_2d(sim, keep)
        feats = torch.cat([pooled_q, pooled_c, sim_mean, overlap.unsqueeze(-1)], dim=-1)
        logit = self.mlp(feats).squeeze(-1) * self.logit_scale
        logit = torch.where(overlap > 0, logit, torch.full_like(logit, -20.0))
        return logit

    def _dtype(self):
        return self.q_proj.weight.dtype

    def cacheable_vector(self, *args, **kwargs):
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            "PairRefineHead has no cacheable per-fragment vector: a refine logit is defined "
            "per pair, so pair-head outputs must never be indexed for whole-gallery FAISS "
            "retrieval (plan 30.10). Use FragmentEncoder.encode_fragment for the index.",
            stage="training.model.PairRefineHead.cacheable_vector",
        )


def _expand_valid(valid, target):
    torch = _torch()
    v = valid
    if v.dim() == 2:      # [N,L]
        v = v.unsqueeze(1)
    if v.shape[0] == 1 and target.shape[0] != 1:
        v = v.expand(target.shape[0], *v.shape[1:])
    if v.shape[1] == 1 and target.shape[1] != 1:
        v = v.expand(v.shape[0], target.shape[1], *v.shape[2:])
    if v.shape[-1] != target.shape[-2]:
        pad = v.new_zeros(*v.shape[:-1], target.shape[-2])
        pad[..., : v.shape[-1]] = v
        v = pad
    return v


def _masked_mean_dim(values, mask, dim: int):
    torch = _torch()
    w = mask.to(values.dtype)
    denom = w.sum(dim=dim, keepdim=True)
    out = (values * w).sum(dim=dim) / denom.clamp(min=1e-8)
    return torch.where(denom.squeeze(dim) > 0, out, torch.zeros_like(out))


def _masked_mean_2d(values, mask):
    torch = _torch()
    w = mask.to(values.dtype)
    denom = w.sum(dim=(-1, -2), keepdim=False)
    out = (values * w).sum(dim=(-1, -2)) / denom.clamp(min=1e-8)
    return torch.where(denom > 0, out, torch.zeros_like(out))


# --------------------------------------------------------------------------------------
# Classical shallow baselines (numpy + faiss, no torch)
# --------------------------------------------------------------------------------------
def _l2_normalize(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(norms, 1e-12)


class ClassicalRetriever:
    """Exact-cosine shallow baseline.

    ``IndexFlatIP`` over L2-normalised vectors is an exact inner-product index; the numpy
    path is kept alongside so a test can verify the two agree (they are the same arithmetic,
    only the accumulation order differs).
    """

    version = CLASSICAL_VERSION

    def __init__(self, *, name: str, use_faiss: bool = True) -> None:
        self.name = name
        self.use_faiss = bool(use_faiss)
        self._ids: list[str] = []
        self._vecs: np.ndarray | None = None
        self._index = None

    def fit(self, ids: Sequence[str], vectors: np.ndarray) -> "ClassicalRetriever":
        vecs = _l2_normalize(np.asarray(vectors, dtype=np.float32))
        if vecs.ndim != 2:
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"vectors must be [N,D], got {vecs.shape}",
                              stage="training.model.ClassicalRetriever.fit")
        if len(ids) != vecs.shape[0]:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{len(ids)} ids for {vecs.shape[0]} vectors",
                              stage="training.model.ClassicalRetriever.fit")
        self._ids = [str(i) for i in ids]
        self._vecs = vecs
        self._index = None
        if self.use_faiss and vecs.shape[0]:
            import faiss

            index = faiss.IndexFlatIP(int(vecs.shape[1]))
            index.add(np.ascontiguousarray(vecs))
            self._index = index
        return self

    def search(self, queries: np.ndarray, k: int) -> list[list[tuple[str, float]]]:
        q = _l2_normalize(np.asarray(queries, dtype=np.float32))
        if q.ndim == 1:
            q = q[None, :]
        if self._vecs is None:
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, "retriever not fitted",
                              stage="training.model.ClassicalRetriever.search")
        k = int(min(k, len(self._ids)))
        if k <= 0:
            return [[] for _ in range(q.shape[0])]
        if self._index is not None:
            scores, idx = self._index.search(np.ascontiguousarray(q), k)
        else:
            scores, idx = self._numpy_search(q, k)
        out = []
        for row_scores, row_idx in zip(scores, idx):
            pairs = [(self._ids[int(j)], float(s)) for s, j in zip(row_scores, row_idx) if int(j) >= 0]
            out.append(pairs)
        return out

    def _numpy_search(self, q: np.ndarray, k: int):
        sims = q @ self._vecs.T
        order = np.argsort(-sims, axis=1, kind="stable")[:, :k]
        scores = np.take_along_axis(sims, order, axis=1)
        return scores, order

    def exact_topk(self, queries: np.ndarray, k: int) -> list[list[tuple[str, float]]]:
        """Pure-numpy exact top-k (used to validate the FAISS path)."""
        q = _l2_normalize(np.asarray(queries, dtype=np.float32))
        if q.ndim == 1:
            q = q[None, :]
        k = int(min(k, len(self._ids)))
        if k <= 0:
            return [[] for _ in range(q.shape[0])]
        scores, idx = self._numpy_search(q, k)
        return [[(self._ids[int(j)], float(s)) for s, j in zip(rs, ri)]
                for rs, ri in zip(scores, idx)]

    @property
    def dim(self) -> int:
        return 0 if self._vecs is None else int(self._vecs.shape[1])


class ObservationVectorBaseline:
    """Shared plumbing for the three shallow observation baselines.

    ``mode`` selects the observation vector: ``"2d"`` (global RGB statistics), ``"3d"``
    (points/normals statistics, requires ``scale_valid``), ``"shallow_fusion"`` (2D + 3D +
    quality/presence, each component gate-masked when missing).
    """

    def __init__(self, *, mode: str, use_faiss: bool = True, name: str | None = None) -> None:
        if mode not in ("2d", "3d", "shallow_fusion"):
            raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown baseline mode {mode!r}",
                              stage="training.model.ObservationVectorBaseline")
        self.mode = mode
        self.name = name or f"classical_{mode}"
        self.retriever = ClassicalRetriever(name=self.name, use_faiss=use_faiss)
        self.n_geometry_unavailable = 0

    def vector(self, payload: dict) -> np.ndarray:
        parts: list[np.ndarray] = []
        rgb = np.asarray(payload["global_rgb"], dtype=np.float32)
        gv = np.asarray(payload["global_valid"], dtype=bool)
        if rgb.ndim == 4:
            rgb = rgb[None, ...]
            gv = gv[None, ...]
        per_view = rgb.reshape(rgb.shape[0] * rgb.shape[1], -1)
        view_valid = gv.reshape(-1)
        if self.mode in ("2d", "shallow_fusion"):
            if view_valid.any():
                sel = per_view[view_valid]
                stats2d = np.concatenate([sel.mean(axis=0), sel.std(axis=0)])
            else:
                stats2d = np.zeros(per_view.shape[1] * 2, dtype=np.float32)
            parts.append(stats2d)
        if self.mode in ("3d", "shallow_fusion"):
            pts = np.asarray(payload["points"], dtype=np.float32).reshape(-1, 3)
            nrm = np.asarray(payload["normals"], dtype=np.float32).reshape(-1, 3)
            pv = np.asarray(payload["point_valid"], dtype=bool).reshape(-1)
            nv = np.asarray(payload["normal_valid"], dtype=bool).reshape(-1)
            scale_ok = bool(payload.get("scale_valid", False))
            if not scale_ok or not (pv.any() or nv.any()):
                self.n_geometry_unavailable += 1
                stats3d = np.zeros(12, dtype=np.float32)
            else:
                sel_p = pts[pv]
                sel_n = nrm[nv]
                stats3d = np.concatenate([
                    sel_p.mean(axis=0) if sel_p.size else np.zeros(3, dtype=np.float32),
                    sel_p.std(axis=0) if sel_p.size else np.zeros(3, dtype=np.float32),
                    sel_n.mean(axis=0) if sel_n.size else np.zeros(3, dtype=np.float32),
                    sel_n.std(axis=0) if sel_n.size else np.zeros(3, dtype=np.float32),
                ]).astype(np.float32)
            parts.append(stats3d)
        if self.mode == "shallow_fusion":
            q = np.asarray(payload["quality"], dtype=np.float32)
            qv = np.asarray(payload["quality_valid"], dtype=bool)
            q_masked = np.where(qv, q, 0.0)
            pr = np.asarray(payload["presence"], dtype=np.float32) * np.asarray(
                payload["presence_valid"], dtype=bool)
            parts.append(np.concatenate([q_masked.mean(axis=0), pr]).astype(np.float32))
        return np.concatenate(parts).astype(np.float32)

    def fit(self, payloads: dict[str, dict], *, available: dict[str, bool] | None = None):
        ids, vecs = [], []
        for fid, payload in payloads.items():
            if available is not None and not available.get(fid, True):
                continue
            ids.append(fid)
            vecs.append(self.vector(payload))
        if not ids:
            self.retriever.fit([], np.zeros((0, 1), dtype=np.float32))
            return self
        self.retriever.fit(ids, np.stack(vecs))
        return self

    def search(self, payload: dict, k: int):
        return self.retriever.search(self.vector(payload)[None, :], k)[0]

    def exact_topk(self, payload: dict, k: int):
        return self.retriever.exact_topk(self.vector(payload)[None, :], k)[0]

    def identity(self) -> dict:
        return {"index_kind": "classical_observation_vector", "mode": self.mode,
                "version": CLASSICAL_VERSION, "distance": "cosine_exact",
                "uses_pair_head": False}


def classical_2d(**kwargs) -> ObservationVectorBaseline:
    return ObservationVectorBaseline(mode="2d", **kwargs)


def classical_3d(**kwargs) -> ObservationVectorBaseline:
    return ObservationVectorBaseline(mode="3d", **kwargs)


def shallow_fusion(**kwargs) -> ObservationVectorBaseline:
    return ObservationVectorBaseline(mode="shallow_fusion", **kwargs)


CLASSICAL_BASELINES = {"2d": classical_2d, "3d": classical_3d, "shallow_fusion": shallow_fusion}


# --------------------------------------------------------------------------------------
# Composite model
# --------------------------------------------------------------------------------------
@dataclass
class DualTowerModel:
    """Encoder (indexable) + pair head (not indexable) + optional classical baseline."""

    encoder: FragmentEncoder
    pair_head: PairRefineHead | None = None
    classical: ObservationVectorBaseline | None = None

    def parameter_groups(self, *, head_lr: float, backbone_lr: float) -> list[dict]:
        """Head = projection + refine head; backbone = shared observation towers."""
        backbone, head = [], []
        for name, p in self.encoder.named_parameters():
            top = name.split(".", 1)[0]
            (head if top in ("proj", "index_proj") else backbone).append(p)
        if self.pair_head is not None:
            head.extend(list(self.pair_head.parameters()))
        groups = []
        if head:
            groups.append({"params": head, "lr": float(head_lr), "name": "head"})
        if backbone:
            groups.append({"params": backbone, "lr": float(backbone_lr), "name": "backbone"})
        return groups

    def index_identity(self, **kwargs) -> dict:
        identity = self.encoder.index_identity(**kwargs)
        identity["pair_head_version"] = (PAIR_HEAD_VERSION if self.pair_head is not None else None)
        identity["classical"] = self.classical.identity() if self.classical is not None else None
        return identity

    def encode_fragment(self, features: TorchFeatureBundle):
        return self.encoder.encode(features)

    def score_pair(self, query_tokens, candidate_tokens, **kwargs):
        if self.pair_head is None:
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                              "no pair refinement head configured",
                              stage="training.model.DualTowerModel.score_pair")
        return self.pair_head.score_pair(query_tokens, candidate_tokens, **kwargs)


def assert_cacheable_index_ok(identity: dict) -> None:
    """Reject an index identity that was built from a per-pair (non-cacheable) embedder."""
    if str(identity.get("index_kind", "")).strip() in ("", "pair_head", "per_pair"):
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"index identity {identity!r} is not a cacheable per-fragment encoder; "
            "pair-head outputs are per pair and cannot be indexed (plan 30.10)",
            stage="training.model.assert_cacheable_index_ok",
        )
    if identity.get("uses_pair_head"):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "an index may not be built from pair-head outputs (plan 30.10)",
                          stage="training.model.assert_cacheable_index_ok")


def build_model(*, out_dim: int = 64, width: int = 32, token_dim: int = TOKEN_DIM,
                with_pair_head: bool = True, classical_mode: str | None = None,
                seed: int = 0, quality_target_dim: int | None = None,
                quality_input_dim: int | None = None) -> DualTowerModel:
    encoder = FragmentEncoder(token_dim=token_dim, out_dim=out_dim, width=width, seed=seed,
                              quality_target_dim=quality_target_dim,
                              quality_input_dim=quality_input_dim)
    head = PairRefineHead(token_dim=token_dim, width=width, seed=seed) if with_pair_head else None
    base = CLASSICAL_BASELINES[classical_mode]() if classical_mode else None
    return DualTowerModel(encoder=encoder, pair_head=head, classical=base)


__all__ = [
    "MODEL_VERSION", "PAIR_HEAD_VERSION", "CLASSICAL_VERSION", "TOKEN_POLICY",
    "FragmentEncoder", "PairRefineHead", "DualTowerModel", "ClassicalRetriever",
    "ObservationVectorBaseline", "classical_2d", "classical_3d", "shallow_fusion",
    "CLASSICAL_BASELINES", "source_group_weights", "masked_mean",
    "assert_cacheable_index_ok", "build_model",
]
