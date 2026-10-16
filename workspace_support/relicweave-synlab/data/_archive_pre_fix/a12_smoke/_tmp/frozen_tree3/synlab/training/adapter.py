"""Training-time contracts: ``a12.obs.v1`` payloads -> masked tensors and separate labels.

Design rules enforced here (plan 18.1, 18.3, 30.11, 30.12):

* features and labels are **separate objects**; a feature container has no relation,
  lineage, mother, interface or split field and cannot be built with one
  (:func:`assert_no_forbidden_features`);
* ragged token/point counts keep their **real** length (``token_valid`` / ``point_valid``);
  padding exists only to make a rectangular tensor and is never a label;
* missing geometry is handled by masked pooling / gating (a branch with no valid entry
  contributes exactly 0 with gate 0 and is recorded), never by NaN and never by inserting a
  "valid" zero vector;
* the active local-token budget is stratified (view x capture-source x spatial bin), then
  ordered by ``OBS_EST`` quality / valid area inside each stratum, with a minimum quota for
  small ROIs.  Every dropped token keeps a retrieval index back into the full upstream
  token table (:mod:`token_retrieval`), so the over-quota evidence is retrievable, not lost.

Integration point: ``synlab.observe.api.adapt_observed_features(obs, contract) -> dict``
is **not present in this checkout** (parallel development).  This module consumes its
documented output through :meth:`FeatureBundle.from_dict` and never imports it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..roles import FORBIDDEN_FEATURE_FIELDS

FEATURE_SCHEMA = "a12.obs.v1"
TOKEN_DIM = 256

#: relation label codes (labels side only -- never a feature)
RELATION_CODES: dict[str, int] = {"R0": 0, "R1": 1, "R2": 2, "TINY_CONTACT": 3, "UNKNOWN": 4}
RELATION_NAMES: dict[int, str] = {v: k for k, v in RELATION_CODES.items()}
RELATION_R2_CODE = RELATION_CODES["R2"]
RELATION_R1_CODE = RELATION_CODES["R1"]
RELATION_TINY_CODE = RELATION_CODES["TINY_CONTACT"]
RELATION_UNKNOWN_CODE = RELATION_CODES["UNKNOWN"]

#: candidate exclusion reasons (plan 18.2: other fragments' known R2 / grey zone, UNKNOWN and
#: TINY contacts never enter ordinary negatives)
EXCLUSION_NONE = 0
EXCLUSION_SAME_FRAGMENT = 1
EXCLUSION_KNOWN_R2 = 2
EXCLUSION_GRAY_ZONE = 3
EXCLUSION_UNKNOWN = 4
EXCLUSION_TINY = 5
EXCLUSION_LABEL_INVALID = 6
EXCLUSION_REASON_NAMES: dict[int, str] = {
    EXCLUSION_NONE: "none",
    EXCLUSION_SAME_FRAGMENT: "same_fragment",
    EXCLUSION_KNOWN_R2: "known_R2",
    EXCLUSION_GRAY_ZONE: "gray_zone",
    EXCLUSION_UNKNOWN: "unknown",
    EXCLUSION_TINY: "TINY",
    EXCLUSION_LABEL_INVALID: "label_invalid",
}

MODALITY_RGB = 0
MODALITY_DEPTH = 1
MODALITY_NORMAL = 2
MODALITY_POINT = 3

CORR_KIND_UNKNOWN = 0
CORR_KIND_EXACT_SURVIVOR = 1
CORR_KIND_VERIFIED_RECESSION = 2

CONTRADICTION_MISSING = 0
CONTRADICTION_COMPATIBLE = 1
CONTRADICTION_CONTRADICTING = 2

#: fields that may never appear inside a feature container (plan 30.12 / roles.py)
FEATURE_FORBIDDEN_FIELDS = frozenset(FORBIDDEN_FEATURE_FIELDS) | {
    "relation", "labels_relation", "R2", "historical_R2", "neg_mask", "pos_mask",
    "quality_target", "corr_weight", "reward", "done_success",
}

#: payload keys that are *bookkeeping only*: they name the row so the batch can be indexed and
#: logged, are consumed into ``FeatureBundle.fragment_ids`` and are **removed** before any
#: tensor is produced.  They must never be exposed to a model forward pass (plan 30.12: ids may
#: only be used for indexing/logging, and the batch renumbers them locally).
INDEX_ONLY_PAYLOAD_KEYS = frozenset({"fragment_id", "row_id", "sample_id"})


def _f32(value: Any) -> np.ndarray:
    return np.ascontiguousarray(np.asarray(value, dtype=np.float32))


def select_token_quota(tokens: np.ndarray, token_valid: np.ndarray, *, budget: int,
                       min_roi_quota: int = 8, token_view: np.ndarray | None = None,
                       token_pixel: np.ndarray | None = None,
                       token_source: np.ndarray | None = None,
                       token_quality: np.ndarray | None = None,
                       spatial_bins: int = 4) -> dict:
    """Stratified quota selection over one fragment's active local tokens.

    Priority (plan 18.1): stratum = ``(view, capture source, spatial bin)``; inside a stratum
    tokens are ordered by ``OBS_EST`` quality (descending), then by original index (stable,
    deterministic, no RNG).  Every stratum smaller than or equal to ``min_roi_quota`` keeps all
    of its tokens ("small ROI minimum quota").  Returns integer indices into ``tokens``
    (ascending) plus per-stratum accounting.
    """
    tokens = np.asarray(tokens)
    valid = np.asarray(token_valid, dtype=bool)
    n_total = int(tokens.shape[0])
    active_idx = np.nonzero(valid[:n_total])[0]
    n_active = int(active_idx.size)
    budget = max(int(budget), 1)

    if n_active <= budget:
        return {
            "indices": active_idx.astype(np.int64), "kept": n_active, "total": n_total,
            "active": n_active, "strata": {}, "over_quota": 0, "min_roi_reserved": 0,
            "budget": budget,
        }

    def _col(arr, default):
        if arr is None:
            return np.full(n_total, default)
        out = np.asarray(arr)
        return out[:n_total]

    view = _col(token_view, 0).astype(np.int64)
    src = _col(token_source, 0).astype(np.int64)
    pix = np.zeros((n_total, 2), dtype=np.int64) if token_pixel is None else np.asarray(token_pixel)[:n_total]
    if token_quality is None:
        q = np.zeros(n_total, dtype=np.float64)
        if np.size(token_pixel) and token_pixel is not None:
            q = np.full(n_total, float(np.size(token_pixel)))
    else:
        q = np.asarray(token_quality, dtype=np.float64).reshape(-1)[:n_total]

    ys = pix[:, 0] if pix.ndim == 2 else np.zeros(n_total, dtype=np.int64)
    if np.all(ys < 0):
        bins = np.zeros(n_total, dtype=np.int64)
    else:
        bins = ys % max(int(spatial_bins), 1)

    stride_src = max(int(src.max()) + 1, 1)
    stratum = ((view * stride_src) + src) * max(int(spatial_bins), 1) + bins
    stratum_a = stratum[active_idx]

    order = np.lexsort((np.arange(n_total, dtype=np.int64), -q))  # quality desc, index asc
    rank = np.empty(n_total, dtype=np.int64)
    rank[order] = np.arange(n_total, dtype=np.int64)

    uniq, inverse, counts = np.unique(stratum_a, return_inverse=True, return_counts=True)
    counts = counts.astype(np.int64)
    n_strata = int(uniq.size)

    quota = np.maximum((budget * counts) // n_active, 1)
    if int(quota.sum()) > budget:
        for s in np.argsort(-quota):
            if int(quota.sum()) <= budget:
                break
            over = int(quota.sum()) - budget
            reducible = int(quota[s]) - 1
            cut = int(min(max(reducible, 0), over))
            quota[s] -= cut
    if int(quota.sum()) < budget:
        fractions = (budget * counts) / n_active - np.floor((budget * counts) / n_active)
        for s in np.argsort(-fractions):
            if int(quota.sum()) >= budget:
                break
            quota[s] += 1

    keep: list[int] = []
    reserved_small = 0
    for s in range(n_strata):
        members = active_idx[inverse == s]
        ranked = members[np.argsort(rank[members], kind="stable")]
        take = int(min(quota[s], ranked.size))
        if ranked.size <= int(min_roi_quota):
            take = int(ranked.size)
            reserved_small += take
        keep.extend(int(i) for i in ranked[:take])

    keep_arr = np.unique(np.asarray(keep, dtype=np.int64))
    if keep_arr.size > budget:
        keep_arr = np.sort(keep_arr[np.argsort(rank[keep_arr], kind="stable")[:budget]])
    return {
        "indices": keep_arr.astype(np.int64),
        "kept": int(keep_arr.size),
        "total": n_total,
        "active": n_active,
        "strata": {int(u): int(c) for u, c in zip(uniq.tolist(), counts.tolist())},
        "over_quota": int(n_active - keep_arr.size),
        "min_roi_reserved": int(reserved_small),
        "budget": budget,
    }


def _prepare_tokens(payload: Mapping[str, Any], fragment_id: str,
                    budget: int, min_roi_quota: int) -> dict:
    """Slice one payload's tokens down to the quota and build the per-fragment token block."""
    tokens_all = np.asarray(payload["local_tokens"])
    if tokens_all.ndim != 2 or tokens_all.shape[1] != TOKEN_DIM:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"payload {fragment_id}: local_tokens must be [L,{TOKEN_DIM}], got {tokens_all.shape}",
            stage="training.adapter.FeatureBundle.from_dict",
        )
    n = int(tokens_all.shape[0])

    def _rowarr(key, dtype, default, width=None):
        value = payload.get(key)
        if value is None:
            base = np.full((n, width), default, dtype=dtype) if width else np.full(n, default, dtype=dtype)
            return base
        arr = np.asarray(value)
        if arr.ndim == 2 and width:
            out = np.full((n, width), default, dtype=dtype)
            out[: arr.shape[0], : arr.shape[1]] = arr.astype(dtype)
            return out
        out = np.full(n, default, dtype=dtype)
        out[: min(n, arr.shape[0])] = np.asarray(arr, dtype=dtype).reshape(-1)[:n]
        return out

    valid_full = _rowarr("token_valid", np.bool_, False)
    view = _rowarr("token_view", np.int32, -1)
    pixel = _rowarr("token_pixel", np.int32, -1, width=2)
    modality = _rowarr("token_modality", np.int32, MODALITY_RGB)
    source = _rowarr("token_source", np.int32, 0)
    upstream_index = _rowarr("token_retrieval", np.int32, -1)

    quality = payload.get("quality")
    token_quality = None
    if quality is not None and np.size(quality):
        qarr = np.asarray(quality, dtype=np.float64)
        token_quality = np.full(n, float(np.mean(qarr)))

    report = select_token_quota(
        tokens_all, valid_full, budget=budget, min_roi_quota=min_roi_quota,
        token_view=view, token_pixel=pixel, token_source=source, token_quality=token_quality,
    )
    keep = report["indices"]

    # retrieval index back into the full upstream token table: for a dropped token this is
    # its upstream index (or its own payload-provided retrieval index if it had one).
    retrieval = np.full(keep.size, -1, dtype=np.int32)
    dropped = np.setdiff1d(np.arange(n, dtype=np.int64), keep, assume_unique=False)
    if dropped.size:
        upstream = np.where(upstream_index[dropped] >= 0,
                            upstream_index[dropped], dropped.astype(np.int32))
        # ``keep`` may legitimately be empty: a fragment whose every validity mask is False is
        # *unobserved* (the loader meets these in the real exported package), and then
        # ``select_token_quota`` keeps nothing while every token counts as dropped.  Clamp to
        # the receiving length instead of broadcasting a full-length array into an empty one.
        retrieval[: min(retrieval.size, upstream.size)] = upstream[: retrieval.size].astype(np.int32)

    report = {k: v for k, v in report.items() if k != "indices"}
    report["dropped_upstream_indices"] = dropped.astype(np.int64)
    report["selected_retrieval_slots"] = int(np.count_nonzero(retrieval >= 0))
    return {
        "tokens": _f32(tokens_all[keep]),
        "valid": valid_full[keep],
        "view": view[keep].astype(np.int32),
        "pixel": pixel[keep].astype(np.int32),
        "modality": modality[keep].astype(np.int32),
        "source": source[keep].astype(np.int32),
        "retrieval": retrieval,
        "total": np.int32(payload.get("tokens_total", n)),
        "report": report,
    }


@dataclass
class FeatureBundle:
    """Batched, masked observation features.  **No labels live here.**"""

    fragment_ids: list[str]
    global_rgb: np.ndarray          # [F,V,3,H,W] float32
    global_valid: np.ndarray        # [F,V] bool
    pixel_valid: np.ndarray         # [F,V,H,W] bool
    local_tokens: np.ndarray        # [F,L,256] float32
    token_valid: np.ndarray         # [F,L] bool
    token_view: np.ndarray          # [F,L] int32
    token_pixel: np.ndarray         # [F,L,2] int32
    token_modality: np.ndarray      # [F,L] int32
    token_source: np.ndarray        # [F,L] int32
    token_retrieval: np.ndarray     # [F,L] int32
    tokens_total: np.ndarray        # [F] int32
    points: np.ndarray              # [F,N,3] float32
    point_valid: np.ndarray         # [F,N] bool
    normals: np.ndarray             # [F,N,3] float32
    normal_valid: np.ndarray        # [F,N] bool
    quality: np.ndarray             # [F,R,Cq] float32
    quality_valid: np.ndarray       # [F,R,Cq] bool
    presence: np.ndarray            # [F,Cm] float32
    presence_valid: np.ndarray      # [F,Cm] bool
    scale_valid: np.ndarray         # [F] bool
    obs_version: np.ndarray         # [F] int32
    meta: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ shape helpers
    @property
    def n_fragments(self) -> int:
        return len(self.fragment_ids)

    @property
    def n_views(self) -> int:
        return int(self.global_rgb.shape[1])

    @property
    def token_budget(self) -> int:
        return int(self.local_tokens.shape[1])

    @property
    def n_points(self) -> int:
        return int(self.points.shape[1])

    @property
    def n_regions(self) -> int:
        return int(self.quality.shape[1])

    @property
    def c_quality(self) -> int:
        return int(self.quality.shape[2])

    @property
    def c_presence(self) -> int:
        return int(self.presence.shape[1])

    @property
    def scale_valid_fraction(self) -> float:
        return float(np.mean(self.scale_valid)) if self.n_fragments else 0.0

    def index_of(self, fragment_id: str) -> int:
        try:
            return self.fragment_ids.index(fragment_id)
        except ValueError as exc:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"fragment {fragment_id!r} not in bundle",
                              stage="training.adapter.FeatureBundle.index_of") from exc

    def token_retention(self) -> np.ndarray:
        """kept / active tokens per fragment (acceptance for 128/256/512 budgets)."""
        active = self.real_token_counts().astype(np.float64)
        total = self.tokens_total.astype(np.float64)
        return np.clip(active / np.maximum(total, 1.0), 0.0, 1.0)

    def real_token_counts(self) -> np.ndarray:
        return self.token_valid.sum(axis=1).astype(np.int64)

    def real_point_counts(self) -> np.ndarray:
        return self.point_valid.sum(axis=1).astype(np.int64)

    def dropped_token_indices(self, fragment_index: int) -> np.ndarray:
        """Upstream indices of the tokens removed by the quota for one fragment."""
        fid = self.fragment_ids[fragment_index]
        return np.asarray(self.meta.get("token_quota", {}).get(fid, {}).get(
            "dropped_upstream_indices", np.zeros(0, dtype=np.int64)), dtype=np.int64)

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_dict(cls, payloads: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]],
                  *, contract: Any | None = None, token_budget: int | None = None,
                  min_roi_quota: int = 8) -> "FeatureBundle":
        """Build a batch from ``adapt_observed_features`` output.

        ``payloads`` is either one payload, a sequence of payloads, or a mapping
        ``fragment_id -> payload``.  ``contract`` is accepted for signature compatibility
        with the upstream adapter and recorded in ``meta``; it never relaxes shape checks.
        """
        if isinstance(payloads, Mapping):
            items = [(str(k), dict(v)) for k, v in payloads.items()]
        else:
            items = [(str(p.get("fragment_id", f"frag{i}")), dict(p)) for i, p in enumerate(payloads)]
        if not items:
            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, "empty feature batch",
                              stage="training.adapter.FeatureBundle.from_dict")

        ids = [fid for fid, _ in items]
        raw = [p for _, p in items]
        for fid, payload in zip(ids, raw):
            assert_no_forbidden_features(payload, where=f"payload[{fid}]")
            schema = payload.get("schema", FEATURE_SCHEMA)
            if schema != FEATURE_SCHEMA:
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  f"payload {fid} schema {schema!r} != {FEATURE_SCHEMA!r}",
                                  stage="training.adapter.FeatureBundle.from_dict")

        blocks = []
        quota_report: dict[str, dict] = {}
        for fid, payload in zip(ids, raw):
            n_tok = int(np.asarray(payload["local_tokens"]).shape[0])
            budget = int(token_budget or payload.get("token_budget") or n_tok)
            block = _prepare_tokens(payload, fid, budget, int(min_roi_quota))
            blocks.append(block)
            quota_report[fid] = block["report"]

        n_views = max(int(np.asarray(p["global_rgb"]).shape[0]) for p in raw)
        height = max(int(np.asarray(p["global_rgb"]).shape[-2]) for p in raw)
        width = max(int(np.asarray(p["global_rgb"]).shape[-1]) for p in raw)
        max_tokens = max(int(b["tokens"].shape[0]) for b in blocks)
        max_points = max(int(np.asarray(p["points"]).shape[0]) for p in raw)
        n_regions = max(int(np.asarray(p["quality"]).shape[0]) for p in raw)
        c_quality = max(int(np.asarray(p["quality"]).shape[1]) for p in raw)
        c_presence = max(int(np.asarray(p["presence"]).shape[0]) for p in raw)
        f = len(ids)

        bundle = cls(
            fragment_ids=ids,
            global_rgb=np.zeros((f, n_views, 3, height, width), dtype=np.float32),
            global_valid=np.zeros((f, n_views), dtype=bool),
            pixel_valid=np.zeros((f, n_views, height, width), dtype=bool),
            local_tokens=np.zeros((f, max_tokens, TOKEN_DIM), dtype=np.float32),
            token_valid=np.zeros((f, max_tokens), dtype=bool),
            token_view=np.full((f, max_tokens), -1, dtype=np.int32),
            token_pixel=np.full((f, max_tokens, 2), -1, dtype=np.int32),
            token_modality=np.full((f, max_tokens), -1, dtype=np.int32),
            token_source=np.full((f, max_tokens), -1, dtype=np.int32),
            token_retrieval=np.full((f, max_tokens), -1, dtype=np.int32),
            tokens_total=np.zeros((f,), dtype=np.int32),
            points=np.zeros((f, max_points, 3), dtype=np.float32),
            point_valid=np.zeros((f, max_points), dtype=bool),
            normals=np.zeros((f, max_points, 3), dtype=np.float32),
            normal_valid=np.zeros((f, max_points), dtype=bool),
            quality=np.zeros((f, n_regions, c_quality), dtype=np.float32),
            quality_valid=np.zeros((f, n_regions, c_quality), dtype=bool),
            presence=np.zeros((f, c_presence), dtype=np.float32),
            presence_valid=np.zeros((f, c_presence), dtype=bool),
            scale_valid=np.zeros((f,), dtype=bool),
            obs_version=np.zeros((f,), dtype=np.int32),
            meta={"schema": FEATURE_SCHEMA, "token_quota": quota_report,
                  "contract": repr(contract) if contract is not None else None},
        )

        for i, payload in enumerate(raw):
            rgb = _f32(payload["global_rgb"])
            v, _, h, w = rgb.shape
            bundle.global_rgb[i, :v, :, :h, :w] = rgb
            bundle.global_valid[i, :v] = np.asarray(payload["global_valid"], dtype=bool)
            bundle.pixel_valid[i, :v, :h, :w] = np.asarray(payload["pixel_valid"], dtype=bool)

            block = blocks[i]
            k = int(block["tokens"].shape[0])
            bundle.local_tokens[i, :k] = block["tokens"]
            bundle.token_valid[i, :k] = block["valid"]
            bundle.token_view[i, :k] = block["view"]
            bundle.token_pixel[i, :k] = block["pixel"]
            bundle.token_modality[i, :k] = block["modality"]
            bundle.token_source[i, :k] = block["source"]
            bundle.token_retrieval[i, :k] = block["retrieval"]
            bundle.tokens_total[i] = int(block["total"])

            pts = _f32(payload["points"])
            npnt = int(pts.shape[0])
            if npnt:
                bundle.points[i, :npnt] = pts
                bundle.point_valid[i, :npnt] = np.asarray(payload["point_valid"], dtype=bool)
                bundle.normals[i, :npnt] = _f32(payload["normals"])
                bundle.normal_valid[i, :npnt] = np.asarray(payload["normal_valid"], dtype=bool)

            q = _f32(payload["quality"])
            bundle.quality[i, : q.shape[0], : q.shape[1]] = q
            bundle.quality_valid[i, : q.shape[0], : q.shape[1]] = np.asarray(
                payload["quality_valid"], dtype=bool)
            pr = _f32(payload["presence"])
            bundle.presence[i, : pr.shape[0]] = pr
            bundle.presence_valid[i, : pr.shape[0]] = np.asarray(payload["presence_valid"], dtype=bool)
            bundle.scale_valid[i] = bool(payload.get("scale_valid", False))
            bundle.obs_version[i] = int(payload.get("obs_version", 0))

        bundle.token_view[~bundle.token_valid] = -1
        bundle.token_pixel[~bundle.token_valid] = -1
        return bundle

    # ------------------------------------------------------------------ checks
    def check_shapes(self) -> "FeatureBundle":
        f = self.n_fragments
        expected = {
            "global_rgb": (f, self.n_views, 3),
            "global_valid": (f, self.n_views),
            "pixel_valid": (f, self.n_views, self.global_rgb.shape[3], self.global_rgb.shape[4]),
            "local_tokens": (f, self.token_budget, TOKEN_DIM),
            "token_valid": (f, self.token_budget),
            "token_view": (f, self.token_budget),
            "token_pixel": (f, self.token_budget, 2),
            "token_modality": (f, self.token_budget),
            "token_source": (f, self.token_budget),
            "token_retrieval": (f, self.token_budget),
            "tokens_total": (f,),
            "points": (f, self.n_points, 3),
            "point_valid": (f, self.n_points),
            "normals": (f, self.n_points, 3),
            "normal_valid": (f, self.n_points),
            "quality": (f, self.n_regions, self.c_quality),
            "quality_valid": (f, self.n_regions, self.c_quality),
            "presence": (f, self.c_presence),
            "presence_valid": (f, self.c_presence),
            "scale_valid": (f,),
            "obs_version": (f,),
        }
        for name, prefix in expected.items():
            arr = np.asarray(getattr(self, name))
            if tuple(arr.shape[: len(prefix)]) != tuple(prefix):
                raise SynLabError(ErrorCode.SCHEMA_INVALID,
                                  f"{name} shape {arr.shape} does not match the expected prefix "
                                  f"{tuple(prefix)}",
                                  stage="training.adapter.check_shapes")
        for name in ("global_valid", "pixel_valid", "token_valid", "point_valid",
                     "normal_valid", "quality_valid", "presence_valid", "scale_valid"):
            if np.asarray(getattr(self, name)).dtype != np.bool_:
                raise SynLabError(ErrorCode.SCHEMA_INVALID, f"{name} must be bool",
                                  stage="training.adapter.check_shapes")
        if not np.isfinite(self.global_rgb).all() or not np.isfinite(self.local_tokens).all():
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "non-finite feature values",
                              stage="training.adapter.check_shapes")
        if not np.isfinite(self.points).all() or not np.isfinite(self.quality).all():
            raise SynLabError(ErrorCode.SCHEMA_INVALID, "non-finite geometry/quality values",
                              stage="training.adapter.check_shapes")
        return self

    def to_torch(self, *, device: str = "cpu") -> "TorchFeatureBundle":
        import torch

        self.check_shapes()
        dtypes = {
            "global_rgb": torch.float32, "global_valid": torch.bool, "pixel_valid": torch.bool,
            "local_tokens": torch.float32, "token_valid": torch.bool, "token_view": torch.int64,
            "token_pixel": torch.int64, "token_modality": torch.int64, "token_source": torch.int64,
            "token_retrieval": torch.int64, "tokens_total": torch.int64, "points": torch.float32,
            "point_valid": torch.bool, "normals": torch.float32, "normal_valid": torch.bool,
            "quality": torch.float32, "quality_valid": torch.bool, "presence": torch.float32,
            "presence_valid": torch.bool, "scale_valid": torch.bool, "obs_version": torch.int64,
        }
        kwargs: dict[str, Any] = {}
        for name, dtype in dtypes.items():
            tensor = torch.from_numpy(np.ascontiguousarray(getattr(self, name)))
            if tensor.dtype != dtype:
                tensor = tensor.to(dtype)
            kwargs[name] = tensor.to(device)
        return TorchFeatureBundle(
            fragment_ids=list(self.fragment_ids),
            meta={"schema": FEATURE_SCHEMA, "token_quota": self.meta.get("token_quota", {})},
            **kwargs,
        )


@dataclass
class TorchFeatureBundle:
    """Torch mirror of :class:`FeatureBundle` (same field names, same validity masks)."""

    fragment_ids: list[str]
    global_rgb: Any = None
    global_valid: Any = None
    pixel_valid: Any = None
    local_tokens: Any = None
    token_valid: Any = None
    token_view: Any = None
    token_pixel: Any = None
    token_modality: Any = None
    token_source: Any = None
    token_retrieval: Any = None
    tokens_total: Any = None
    points: Any = None
    point_valid: Any = None
    normals: Any = None
    normal_valid: Any = None
    quality: Any = None
    quality_valid: Any = None
    presence: Any = None
    presence_valid: Any = None
    scale_valid: Any = None
    obs_version: Any = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_fragments(self) -> int:
        return len(self.fragment_ids)

    def select(self, indices: Sequence[int]) -> "TorchFeatureBundle":
        """Subset selection used by per-query losses (keeps validity masks consistent)."""
        import torch

        idx = torch.as_tensor([int(i) for i in indices], dtype=torch.long,
                              device=self.global_rgb.device)
        kwargs: dict[str, Any] = {}
        for f in fields(self):
            if f.name in ("fragment_ids", "meta"):
                continue
            kwargs[f.name] = getattr(self, f.name).index_select(0, idx)
        return TorchFeatureBundle(fragment_ids=[self.fragment_ids[int(i)] for i in indices],
                                  meta=dict(self.meta), **kwargs)


def masked_pool(tokens: np.ndarray, token_valid: np.ndarray,
                weights: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Mean over **valid** tokens only.

    Returns ``(pooled [F,256], counts [F])``.  A row with ``counts == 0`` is *absent*: its
    pooled vector is all-zero and the caller must not treat it as a valid observation.
    """
    tok = np.asarray(tokens, dtype=np.float64)
    valid = np.asarray(token_valid, dtype=bool)
    if tok.ndim != 3 or valid.shape != tok.shape[:2]:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"masked_pool shapes {tok.shape} / {valid.shape}",
                          stage="training.adapter.masked_pool")
    w = valid.astype(np.float64) if weights is None else (np.asarray(weights, dtype=np.float64) * valid)
    denom = w.sum(axis=1)
    out = np.zeros((tok.shape[0], tok.shape[2]), dtype=np.float64)
    numer = (tok * w[:, :, None]).sum(axis=1)
    np.divide(numer, np.maximum(denom, 1e-12)[:, None], out=out)
    out[denom <= 0] = 0.0
    return out.astype(np.float32), denom.astype(np.int64)


def gated_fuse(branches: Mapping[str, np.ndarray], gates: Mapping[str, np.ndarray],
               valid: Mapping[str, np.ndarray] | None = None) -> dict:
    """Gate-fuse branches whose inputs may be missing.

    A branch whose ``valid`` mask is all-False contributes exactly 0 and its gate is forced to
    0; the fusion is renormalised over the surviving gates.  If every branch is missing,
    ``available`` is False and the fused vector is all-zero -- callers must then treat that
    fragment as having no legal modality instead of using the zero vector as a measurement.
    """
    valid = valid or {}
    if not branches:
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE, "gated_fuse called with no branches",
                          stage="training.adapter.gated_fuse")
    total: np.ndarray | None = None
    denom: np.ndarray | None = None
    for name, value in branches.items():
        arr = np.asarray(value, dtype=np.float64)
        v = np.asarray(valid.get(name, np.ones(arr.shape[0], dtype=bool)), dtype=bool)
        g = np.asarray(gates.get(name, np.ones(arr.shape[0], dtype=np.float64)), dtype=np.float64) * v
        contrib = arr * g[:, None]
        total = contrib if total is None else total + contrib
        denom = g if denom is None else denom + g
    assert total is not None and denom is not None
    out = np.divide(total, np.maximum(denom, 1e-12)[:, None])
    available = denom > 0
    out[~available] = 0.0
    return {"fused": out.astype(np.float32), "available": available,
            "gate_mass": denom.astype(np.float32), "branches": list(branches)}


def assert_no_forbidden_features(payload: Mapping[str, Any], *, where: str = "payload",
                                 allow_index_keys: bool = True) -> None:
    """Reject a feature dict carrying label / provenance fields (plan 30.12).

    ``fragment_id`` (and the other :data:`INDEX_ONLY_PAYLOAD_KEYS`) is accepted because the
    batch uses it purely for indexing/logging; it is dropped before any tensor is built and is
    never handed to the encoder.
    """
    forbidden = FEATURE_FORBIDDEN_FIELDS
    if allow_index_keys:
        forbidden = forbidden - INDEX_ONLY_PAYLOAD_KEYS
    leaked = sorted(forbidden.intersection(payload.keys()))
    if leaked:
        raise SynLabError(
            ErrorCode.LEAKAGE_DETECTED,
            f"{where} carries forbidden feature fields: {leaked}",
            stage="training.adapter.assert_no_forbidden_features",
            evidence_refs=leaked,
        )

__all__ = [
    "FEATURE_SCHEMA", "TOKEN_DIM", "FEATURE_FORBIDDEN_FIELDS", "INDEX_ONLY_PAYLOAD_KEYS",
    "RELATION_CODES", "RELATION_NAMES", "RELATION_R2_CODE", "RELATION_R1_CODE",
    "RELATION_TINY_CODE", "RELATION_UNKNOWN_CODE",
    "EXCLUSION_NONE", "EXCLUSION_SAME_FRAGMENT", "EXCLUSION_KNOWN_R2", "EXCLUSION_GRAY_ZONE",
    "EXCLUSION_UNKNOWN", "EXCLUSION_TINY", "EXCLUSION_LABEL_INVALID", "EXCLUSION_REASON_NAMES",
    "MODALITY_RGB", "MODALITY_DEPTH", "MODALITY_NORMAL", "MODALITY_POINT",
    "CORR_KIND_UNKNOWN", "CORR_KIND_EXACT_SURVIVOR", "CORR_KIND_VERIFIED_RECESSION",
    "CONTRADICTION_MISSING", "CONTRADICTION_COMPATIBLE", "CONTRADICTION_CONTRADICTING",
    "FeatureBundle", "TorchFeatureBundle", "select_token_quota",
    "masked_pool", "gated_fuse", "assert_no_forbidden_features",
]
