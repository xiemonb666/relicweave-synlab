"""Observation-only feature adapter with a recursive whitelist (plan 4.4, 30.1, 30.2).

``adapt_observed_features(obs, contract) -> dict`` returns **three separate objects**:

``features``
    Only fields a deployment profile can legally obtain, all computed from the damaged
    observation.  Every entry is a legal value payload (array / number / list) so that a
    model forward pass can consume it directly.  No identifier, no answer, no truth.
``labels``
    Research supervision (fragment/event ids, truth geometry, spurious mask, hard-case
    tags, historical relations).  Kept beside the features, never inside them.
``provenance``
    Derivation chain: which observation hash, which estimator versions, which source
    kinds, which view ids.  Also kept beside the features.

The whitelist is enforced **recursively** by :func:`assert_no_leakage`, which is called at
the end of :func:`adapt_observed_features` and is also exported for cache/loader audits.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..roles import (
    FORBIDDEN_FEATURE_FIELDS,
    SOURCE_GT_ORACLE,
    SOURCE_OBS_EST,
)

#: Schema id used for the observation feature bundle (plan 30.1 M00 fallback contract).
FEATURE_SCHEMA = "a12.obs.v1"

#: Feature group keys.  Deliberately opaque: they must not encode lineage, view order or
#: any identifier that could act as a side channel (plan 4.4, 30.12).
FEATURE_GROUPS: tuple[str, ...] = ("g0", "g1", "g2", "g3", "g4")

#: Whitelisted top-level keys of ``features``.
ALLOWED_FEATURE_KEYS: frozenset[str] = frozenset({
    "schema", "version", "groups", "point_cloud", "normal_field", "curvature_field",
    "quality", "view_tokens", "integrity",
})

#: Whitelisted leaf keys inside one feature group.
ALLOWED_GROUP_KEYS: frozenset[str] = frozenset({
    "xyz_mm_or_units", "normal", "curvature_per_mm", "valid", "density_per_mm2",
    "roi_weight", "token_index",
})

#: Additional forbidden names beyond :data:`synlab.roles.FORBIDDEN_FEATURE_FIELDS`.
EXTRA_FORBIDDEN: frozenset[str] = frozenset({
    "spurious", "spurious_vertex_mask", "gt_roi", "oracle_roi", "clean_area",
    "clean_volume", "truth_scale", "scale_truth", "hard_case", "answer", "relation_kind",
    "r2_pair", "candidate_id", "object_id", "bag_id", "generator_family",
    "assembly_pose", "object_pose_T_WO", "T_WS", "T_WC", "T_CW", "T_WF", "T_WO",
    "fragment_index", "view_index", "profile_id", "mother_ref",
})

FORBIDDEN_UNION: frozenset[str] = frozenset(set(FORBIDDEN_FEATURE_FIELDS) | set(EXTRA_FORBIDDEN))


def assert_no_leakage(features: Any, *, path: str = "features") -> None:
    """Recursively verify that no forbidden field name reaches the feature object.

    Raises ``LEAKAGE_DETECTED`` with the offending path.  Non-string leaf keys, dict
    sub-keys and dataclass field names are all checked; the traversal also rejects a
    forbidden name appearing as a *substring* of a longer key (``"gt_normal_p95"``).
    """
    violations: list[str] = []

    def walk(node: Any, where: str, depth: int) -> None:
        if depth > 12:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                key_str = str(key)
                low = key_str.lower()
                if low in FORBIDDEN_UNION:
                    violations.append(f"{where}.{key_str}")
                else:
                    for bad in FORBIDDEN_UNION:
                        if bad in low:
                            violations.append(f"{where}.{key_str} (contains {bad!r})")
                            break
                walk(value, f"{where}.{key_str}", depth + 1)
        elif isinstance(node, (list, tuple)):
            for i, value in enumerate(node):
                walk(value, f"{where}[{i}]", depth + 1)
        elif hasattr(node, "__dataclass_fields__"):
            for key in node.__dataclass_fields__:
                walk(getattr(node, key), f"{where}.{key}", depth + 1)

    walk(features, path, 0)
    if violations:
        raise SynLabError(
            ErrorCode.LEAKAGE_DETECTED,
            f"forbidden fields reached the feature object: {violations[:8]}",
            stage="observe.features.assert_no_leakage",
            evidence_refs=violations[:8],
            measurements={"n_violations": len(violations)},
        )


def _arrays(obs: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    points = np.asarray(getattr(obs, "points", np.zeros((0, 3))), dtype=np.float64)
    normals = np.asarray(getattr(obs, "normals", np.zeros((0, 3))), dtype=np.float64)
    pv = np.asarray(getattr(obs, "point_valid", np.zeros(points.shape[0], dtype=bool)),
                    dtype=bool)
    nv = np.asarray(getattr(obs, "normal_valid", np.zeros(normals.shape[0], dtype=bool)),
                    dtype=bool)
    scale_valid = bool(getattr(obs, "scale_valid", False))
    return points, normals, pv, nv, np.array([scale_valid])


def _curvature_from_normals(points: np.ndarray, normals: np.ndarray,
                            k: int = 12) -> np.ndarray:
    """Per-point mean curvature magnitude from the normal variation (estimation, not truth).

    Uses a KD-tree: no O(N^2) loop over the point cloud.
    """
    n = points.shape[0]
    if n < 3:
        return np.zeros(n, dtype=np.float32)
    try:
        from scipy.spatial import cKDTree

        tree = cKDTree(points)
        kk = int(min(k, n))
        _, idx = tree.query(points, k=kk)
        if idx.ndim == 1:
            idx = idx[:, None]
        nb = normals[idx]                       # (N, k, 3)
        cos = np.clip(np.abs(np.einsum("nk,njk->nj", normals, nb)), 0.0, 1.0)
        ang = np.arccos(cos)
        dist = np.linalg.norm(points[idx] - points[:, None, :], axis=2)
        dist = np.maximum(dist, 1e-9)
        curv = np.where(dist > 1e-9, ang / dist, 0.0)
        return np.nan_to_num(curv[:, 1:].mean(axis=1), nan=0.0, posinf=0.0).astype(np.float32)
    except Exception:  # noqa: BLE001 - reported through validity, never silently faked
        return np.zeros(n, dtype=np.float32)


def _local_density(points: np.ndarray, k: int = 8) -> np.ndarray:
    n = points.shape[0]
    if n < 2:
        return np.zeros(n, dtype=np.float32)
    try:
        from scipy.spatial import cKDTree

        tree = cKDTree(points)
        kk = int(min(k, n))
        dist, _ = tree.query(points, k=kk)
        if dist.ndim == 1:
            dist = dist[:, None]
        r = np.maximum(dist[:, -1], 1e-9)
        return (1.0 / (np.pi * r * r)).astype(np.float32)
    except Exception:  # noqa: BLE001
        return np.zeros(n, dtype=np.float32)


def adapt_observed_features(obs: Any, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the legal feature bundle from one observation.

    ``contract`` may carry ``{"schema": "a12.obs.v1", "token_budget": int,
    "resample_seed": int}``.  Unknown contract keys are rejected: silently accepting an
    unknown option is how a GT field usually sneaks in.
    """
    contract = dict(contract or {})
    allowed_contract = {"schema", "token_budget", "resample_seed", "include_view_tokens"}
    unknown = set(contract) - allowed_contract
    if unknown:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"unknown contract keys {sorted(unknown)}",
                          stage="observe.features.adapt_observed_features")
    if contract.get("schema", FEATURE_SCHEMA) != FEATURE_SCHEMA:
        raise SynLabError(
            ErrorCode.SCHEMA_INVALID,
            f"feature schema {contract.get('schema')!r} is not the a12.obs.v1 contract; a "
            f"main-repo adapter must be verified separately (plan 30.1 M00)",
            stage="observe.features.adapt_observed_features",
        )
    token_budget = int(contract.get("token_budget", 0) or 0)
    seed = int(contract.get("resample_seed", 20261001))

    points, normals, pv, nv, scale_flag = _arrays(obs)
    scale_valid = bool(scale_flag[0])
    n = points.shape[0]
    if n == 0:
        features = {
            "schema": FEATURE_SCHEMA,
            "version": "1.0",
            "groups": list(FEATURE_GROUPS),
            "point_cloud": {"xyz": np.zeros((0, 3), np.float32),
                            "unit": "mm" if scale_valid else "unknown",
                            "scale_valid": scale_valid, "valid": np.zeros(0, dtype=bool),
                            "n_points": 0},
            "normal_field": {"normals": np.zeros((0, 3), np.float32),
                             "valid": np.zeros(0, dtype=bool)},
            "curvature_field": {"curvature_per_mm": np.zeros(0, np.float32),
                                "valid": np.zeros(0, dtype=bool),
                                "estimator": "normal_variation_kdtree.v1"},
            "quality": _quality_features(obs),
            "view_tokens": np.zeros((0, 3), np.float32),
            "integrity": {"features_hash": "", "n_points": 0},
        }
        labels = _labels_object(obs)
        provenance = _provenance_object(obs, contract)
        assert_no_leakage(features)
        return {"features": features, "labels": labels, "provenance": provenance,
                "schema": FEATURE_SCHEMA}

    order = np.lexsort((points[:, 2], points[:, 1], points[:, 0]))
    curvature = _curvature_from_normals(points, normals)
    density = _local_density(points)
    valid = pv & np.isfinite(points).all(axis=1)
    nvalid = nv & np.isfinite(normals).all(axis=1)
    unit = "mm" if scale_valid else "unknown"

    roi_weight = _roi_weight(obs, points)
    token_index = np.full(n, -1, dtype=np.int32)
    if token_budget > 0:
        rng = np.random.Generator(np.random.PCG64(np.uint64(seed)))
        frozen = rng.permutation(n)          # frozen nesting order, sample once
        n_take = int(min(token_budget, n))
        token_index[frozen[:n_take]] = np.arange(n_take, dtype=np.int32)
    view_tokens = _view_tokens(obs)

    features = {
        "schema": FEATURE_SCHEMA,
        "version": "1.0",
        "groups": list(FEATURE_GROUPS),
        "point_cloud": {
            "xyz": np.ascontiguousarray(points[:, [0, 1, 2]][order], dtype=np.float32),
            "unit": unit,
            "scale_valid": scale_valid,
            "valid": valid[order],
            "n_points": int(n),
            "order": "lexsort_xyz",
        },
        "normal_field": {
            "normals": np.ascontiguousarray(normals[order], dtype=np.float32),
            "valid": nvalid[order],
            "estimator": "obs_normal_v1",
        },
        "curvature_field": {
            "curvature_per_mm": np.ascontiguousarray(curvature[order], dtype=np.float32),
            "valid": valid[order],
            "estimator": "normal_variation_kdtree.v1",
        },
        "density_field": {
            "density_per_mm2": np.ascontiguousarray(density[order], dtype=np.float32),
            "valid": valid[order],
            "unit": f"1/{unit}2" if scale_valid else "unknown",
        },
        "roi_weight": np.ascontiguousarray(roi_weight[order], dtype=np.float32),
        "token_index": np.ascontiguousarray(token_index[order], dtype=np.int32),
        "quality": _quality_features(obs),
        "view_tokens": view_tokens,
    }
    integrity = {"features_hash": _features_hash(features), "n_points": int(n),
                 "n_valid_points": int(np.count_nonzero(valid)),
                 "estimator_versions": {"curvature": "normal_variation_kdtree.v1",
                                        "density": "local_kdtree.v1",
                                        "normals": "obs_normal_v1"}}
    features["integrity"] = integrity
    labels = _labels_object(obs)
    provenance = _provenance_object(obs, contract)
    assert_no_leakage(features)
    return {"features": features, "labels": labels, "provenance": provenance,
            "schema": FEATURE_SCHEMA}


def _roi_weight(obs: Any, points: np.ndarray) -> np.ndarray:
    """ROI weight from the *estimated* per-view ROI, back-projected; 0 when unknown."""
    views = list(getattr(obs, "views", []) or [])
    if not views:
        return np.zeros(points.shape[0], dtype=np.float32)
    from ..cameras.projection import project

    weight = np.zeros(points.shape[0], dtype=np.float32)
    for view in views:
        roi = getattr(view, "roi", None)
        if roi is None or not np.asarray(roi).size:
            continue
        frame = view.frame
        uv, z = project(points, np.asarray(frame.K), np.asarray(frame.T_WC),
                        None if frame.dist is None else np.asarray(frame.dist),
                        model=frame.camera_model or "PINHOLE")
        roi_arr = np.asarray(roi, dtype=bool)
        h, w = roi_arr.shape[:2]
        ok = (z > 0) & np.isfinite(uv[:, 0]) & np.isfinite(uv[:, 1])
        u = np.clip(np.rint(np.nan_to_num(uv[:, 0])).astype(np.int64), 0, w - 1)
        v = np.clip(np.rint(np.nan_to_num(uv[:, 1])).astype(np.int64), 0, h - 1)
        inside = roi_arr[v, u] & ok
        weight = np.maximum(weight, inside.astype(np.float32))
    return weight


def _view_tokens(obs: Any, *, grid: int = 4) -> np.ndarray:
    """Per-view appearance tokens: mean linear RGB and the OBS_EST blur of each view.

    Tokens carry **no** view id and no ordering information, so they cannot act as a
    lineage side channel.  Shape ``(n_views, 3)``.
    """
    views = list(getattr(obs, "views", []) or [])
    if not views:
        return np.zeros((0, 3), dtype=np.float32)
    out = np.zeros((len(views), 3), dtype=np.float32)
    for i, view in enumerate(views):
        rgb = np.asarray(getattr(view, "rgb", None), dtype=np.float32)
        if rgb.size == 0:
            continue
        scale = 255.0 if rgb.max() > 2.0 else 1.0
        data = rgb / scale
        # A fixed 4x4 spatial pooling removes the raw resolution/order channel.
        h, w = data.shape[0], data.shape[1]
        hs, ws = max(h // grid, 1), max(w // grid, 1)
        pooled = data[:hs * grid, :ws * grid].reshape(grid, hs, grid, ws, -1).mean(axis=(1, 3))
        out[i, 0] = float(pooled.mean())
        out[i, 1] = float(pooled.std())
        out[i, 2] = float(data[..., :3].mean())
    return out


def _quality_features(obs: Any) -> dict[str, np.ndarray]:
    """OBS_EST values as plain arrays (no source metadata -- that lives in provenance)."""
    from .quality import estimate_quality

    quality = estimate_quality(obs)
    keys = ("blur_laplacian_p95", "blur_laplacian_min", "overexposed_fraction",
            "underexposed_fraction", "mean_level", "point_valid_fraction",
            "view_coverage_mean", "hole_ratio_max", "roi_coverage_mean",
            "nn_spacing_median", "nn_spacing_p95")
    # A missing or malformed entry must degrade to "invalid", never abort the lineage:
    # measured trigger was a KeyError('nn_spacing_p95') that killed whole accepted runs.
    def _entry(key: str):
        row = quality.get(key)
        if isinstance(row, dict):
            raw, ok = row.get("value"), bool(row.get("valid", False))
        else:
            raw, ok = row, False
        try:
            return float(raw), bool(ok)
        except (TypeError, ValueError):
            return 0.0, False

    pairs = [_entry(k) for k in keys]
    values = np.array([v for v, _ in pairs], dtype=np.float32)
    valid = np.array([ok for _, ok in pairs], dtype=bool)
    return {"values": values, "valid": valid, "names": list(keys)}


def _labels_object(obs: Any) -> dict[str, Any]:
    """Research supervision; never merged into ``features``."""
    views = list(getattr(obs, "views", []) or [])
    labels: dict[str, Any] = {
        "role": "research_label_only",
        "observation_id": str(getattr(obs, "observation_id", "")),
        "fragment_id": str(getattr(obs, "fragment_id", "")),
        "component_id": str(getattr(obs, "component_id", "")),
        "mother_id": str(getattr(obs, "mother_id", "")),
        "route": str(getattr(obs, "route", "")),
        "input_profile": str(getattr(obs, "input_profile", "")),
        "source_kind": str(getattr(obs, "source_kind", "")),
        "scale_valid": bool(getattr(obs, "scale_valid", False)),
        "pose_source": "SIMULATOR_REFERENCE_ONLY",
        "view_ids": [str(v.view_id) for v in views],
        "view_poses_T_WC": [np.asarray(v.frame.T_WC, dtype=np.float64).tolist() for v in views],
        "surface_tag_map": [np.asarray(v.surface_tag).copy() for v in views],
        "research_id_map": [np.asarray(v.id_map).copy() for v in views],
        "history": {
            "historical_R2": list(getattr(obs, "meta", {}).get("historical_R2", []) or []),
            "mate_present": bool(getattr(obs, "meta", {}).get("mate_present", False)),
            "association_kind": str(getattr(obs, "meta", {}).get("association_kind", "UNKNOWN_MAPPING")),
        },
    }
    spurious = getattr(obs, "spurious_mask", None)
    if spurious is not None:
        labels["spurious_mask"] = np.asarray(spurious).copy()
    return labels


def _provenance_object(obs: Any, contract: dict[str, Any]) -> dict[str, Any]:
    from .quality import OBS_EST_VERSION

    views = list(getattr(obs, "views", []) or [])
    return {
        "role": "provenance",
        "observation_hash": _observation_hash(obs),
        "obs_est_version": OBS_EST_VERSION,
        "route": str(getattr(obs, "route", "")),
        "input_profile": str(getattr(obs, "input_profile", "")),
        "n_views": len(views),
        "source_kinds": sorted({str(v.source_kind) for v in views}),
        "quality_source_kind": SOURCE_OBS_EST,
        "oracle_fields_used": [],
        "forbidden_source_kinds_present": [],
        "adapter_version": "observe.features.v1",
        "contract": {k: (v if isinstance(v, (int, float, str, bool)) else str(v))
                     for k, v in contract.items()},
        "notes": [
            "features are computed from the damaged observation only",
            f"gt_oracle source_kind is never used here ({SOURCE_GT_ORACLE})",
        ],
    }


def _observation_hash(obs: Any) -> str:
    payload = {
        "points": np.asarray(getattr(obs, "points", np.zeros((0, 3)))),
        "normals": np.asarray(getattr(obs, "normals", np.zeros((0, 3)))),
        "point_valid": np.asarray(getattr(obs, "point_valid", np.zeros(0, dtype=bool))),
        "route": str(getattr(obs, "route", "")),
        "n_views": len(getattr(obs, "views", []) or []),
    }
    return hash_json({k: (v.tolist() if isinstance(v, np.ndarray) else v)
                      for k, v in payload.items()})


def _features_hash(features: dict[str, Any]) -> str:
    """Hash of the numeric payload only, with the hash field excluded."""
    payload: dict[str, Any] = {}
    for key, value in sorted(features.items()):
        if key == "integrity":
            continue
        payload[key] = _canonicalise(value)
    return hash_json(payload)


def _canonicalise(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        if value.dtype == object:
            return [str(v) for v in value.tolist()]
        return {"dtype": str(value.dtype), "shape": list(value.shape),
                "sha256": hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()}
    if isinstance(value, dict):
        return {str(k): _canonicalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalise(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


def feature_vector(features: dict[str, Any]) -> np.ndarray:
    """Flatten the per-point feature matrix ``(N, C)`` for a model forward pass."""
    pc = features["point_cloud"]["xyz"]
    nrm = features["normal_field"]["normals"]
    curv = features["curvature_field"]["curvature_per_mm"][:, None]
    dens = features["density_field"]["density_per_mm2"][:, None]
    roi = np.asarray(features["roi_weight"])[:, None]
    return np.concatenate([pc, nrm, curv, dens, roi], axis=1).astype(np.float32)


__all__ = [
    "FEATURE_SCHEMA", "FEATURE_GROUPS", "ALLOWED_FEATURE_KEYS", "ALLOWED_GROUP_KEYS",
    "EXTRA_FORBIDDEN", "FORBIDDEN_UNION", "assert_no_leakage", "adapt_observed_features",
    "feature_vector",
]
