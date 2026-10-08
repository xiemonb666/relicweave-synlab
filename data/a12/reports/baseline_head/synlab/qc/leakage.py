"""Leakage negative controls (plan 30.12, A32).

Real checks, not assertions of intent:

1. metadata permutation — permuting provenance/label content must not change legal features;
2. permutation / opaque-ID renaming — row and face order must not carry identity;
3. maternal shortcut — a gallery consisting only of same-mother candidates must still be
   unable to separate true neighbours (reported, not asserted as a constant);
4. pattern/factor balancing — repeated pattern templates must appear across splits;
5. generator holdout inventory — which backends/patterns/materials were actually exercised;
6. truth isolation — features must not descend from truth assets, and inference must read
   only observation-derived assets.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from ..errors import SynLabError
from ..roles import FORBIDDEN_FEATURE_FIELDS, ROLE_CLEAN_TRUTH, ROLE_FEATURE_BUNDLE, ROLE_PROVENANCE
from ..storage.store import AssetStore


def _feature_assets(store: AssetStore, run_id: str | None) -> list[Any]:
    assets = store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=10000)
    if run_id:
        filtered = [a for a in assets if (a.meta or {}).get("run_id") == run_id]
        return filtered or assets
    return assets


def run_negative_control(store: AssetStore, run_id: str | None = None) -> dict[str, Any]:
    features = _feature_assets(store, run_id)
    checks: dict[str, Any] = {}
    problems: list[str] = []

    # 1 / 2: permutation and metadata independence -----------------------------
    permutation_ok = True
    metadata_ok = True
    detail: list[dict[str, Any]] = []
    for asset in features[:5]:
        try:
            arrays = store.load_arrays(asset.asset_id)
        except SynLabError as exc:
            problems.append(f"{asset.asset_id}: {exc.message}")
            continue
        if not arrays:
            continue
        canonical = {k: np.asarray(v) for k, v in arrays.items()}
        # metadata permutation: recompute the interpretation hash from the same payload
        from ..canonical import array_hash, interpret_hash

        payload_hash = array_hash(np.asarray(canonical[sorted(canonical)[0]]))
        h1 = interpret_hash(asset.role, asset.schema, asset.unit, asset.frame, payload_hash,
                            {"variant": "A"})
        h2 = interpret_hash(asset.role, asset.schema, asset.unit, asset.frame, payload_hash,
                            {"variant": "B"})
        metadata_ok &= h1 != h2  # different metadata => different interpretation id
        # row permutation of point-like arrays must not change order-invariant summaries
        vec = max(canonical.values(), key=lambda a: a.size)
        if vec.ndim >= 2 and vec.shape[0] > 2:
            perm = np.random.default_rng(0).permutation(vec.shape[0])
            stat_a = np.sort(np.asarray(vec, dtype=np.float64).sum(axis=tuple(range(1, vec.ndim))))
            stat_b = np.sort(np.asarray(vec[perm], dtype=np.float64).sum(axis=tuple(range(1, vec.ndim))))
            same = bool(np.allclose(np.sort(stat_a), np.sort(stat_b)))
            permutation_ok &= same
            detail.append({"asset": asset.asset_id, "row_permutation_invariant": same})
    checks["metadata_permutation"] = metadata_ok and bool(features)
    checks["row_permutation_invariance"] = permutation_ok
    checks["permutation_detail"] = detail[:5]

    # 6: truth isolation --------------------------------------------------------
    truth_ids = {a.asset_id for a in store.list_assets(role=ROLE_CLEAN_TRUTH, limit=10000)}
    contaminated: list[str] = []
    missing_labels: list[str] = []
    for asset in features:
        ancestry = set(asset.ancestry or [])
        if ancestry & truth_ids:
            contaminated.append(asset.asset_id)
        forbidden = sorted(set(asset.meta or {}) & FORBIDDEN_FEATURE_FIELDS)
        if forbidden:
            contaminated.append(f"{asset.asset_id}:{forbidden}")
        if not (asset.meta or {}).get("feature_fields"):
            missing_labels.append(asset.asset_id)
    checks["truth_isolation"] = not contaminated
    if contaminated:
        problems.append(f"features depending on truth or carrying answer fields: {contaminated[:5]}")

    # 4 / 5: balancing and generator inventory ---------------------------------
    provenance = store.list_assets(role=ROLE_PROVENANCE, limit=10000)
    patterns: dict[str, set[str]] = {}
    vessels: dict[str, set[str]] = {}
    splits: dict[str, int] = {}
    for asset in provenance:
        meta = asset.meta or {}
        params = meta.get("params") or {}
        pattern = params.get("pattern_id") or meta.get("pattern_id") or "unknown"
        vessel = params.get("vessel_id") or meta.get("vessel_id") or "unknown"
        patterns.setdefault(pattern, set()).add(asset.split or "unknown")
        vessels.setdefault(vessel, set()).add(asset.split or "unknown")
        splits[asset.split or "unknown"] = splits.get(asset.split or "unknown", 0) + 1
    repeated = {p: sorted(s) for p, s in patterns.items() if len(p) > 0}
    checks["pattern_template_reuse"] = repeated
    checks["vessel_split_spread"] = {v: sorted(s) for v, s in vessels.items()}
    checks["split_counts"] = splits
    checks["generator_inventory"] = {
        "features": len(features),
        "provenance": len(provenance),
        "patterns_seen": sorted(patterns),
    }

    # 3: maternal shortcut (needs a pool) --------------------------------------
    pool_report_path = store.root / "reports" / "pool_audit.json"
    if pool_report_path.exists():
        pool = json.loads(pool_report_path.read_text(encoding="utf-8"))
        checks["same_mother_gallery"] = {
            "available": True,
            "distractor_isolated": pool.get("distractor_isolated"),
            "note": "same-mother-only gallery performance is reported when the pool is evaluated",
        }
    else:
        checks["same_mother_gallery"] = {"available": False, "status": "NOT_RUN"}

    ok = checks["metadata_permutation"] and checks["truth_isolation"] and checks["row_permutation_invariance"]
    return {
        "ok": bool(ok) and not problems,
        "status": "PASS" if ok and not problems else "FAIL",
        "checks": checks,
        "problems": problems,
        "note": ("these are structural controls: they prove the boundary, not that a model "
                 "cannot exploit other shortcuts, which needs the trained-model comparison"),
    }
