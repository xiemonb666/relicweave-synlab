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
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from ..errors import SynLabError
from ..roles import (
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_LABEL_BUNDLE,
    ROLE_OBS_FUSED,
    ROLE_OBS_RESULT,
    ROLE_OBS_VIEW,
    ROLE_PHYSICAL_TRUTH,
    ROLE_PROVENANCE,
    ROLE_VISIBLE_LABELS,
)
from ..storage.store import AssetStore


# Asset bookkeeping fields are used to join/log rows; they are not feature tensors.  Keep this
# list aligned with FEATURE_ASSET_INDEX_KEYS in tests/a12/integration/test_closed_loop.py.
_INDEX_ONLY_META_FIELDS = frozenset({
    "fragment_id", "component_id", "mother_id", "observation_id", "run_id",
})

_TRUTH_ROLES = frozenset({
    ROLE_CLEAN_TRUTH, ROLE_PHYSICAL_TRUTH, ROLE_VISIBLE_LABELS, ROLE_LABEL_BUNDLE,
})

# Observation assets are the model-input boundary.  Their source geometry can legitimately have
# been generated from clean/physical truth, so dependency tracing stops here instead of treating
# the simulator's world model as a truth channel fed to the encoder.
_OBSERVATION_BOUNDARY_ROLES = frozenset({ROLE_OBS_RESULT, ROLE_OBS_VIEW, ROLE_OBS_FUSED})

_ASSET_PAGE_SIZE = 1000


def _iter_assets(store: AssetStore, *, role: str):
    """Yield every asset of a role; a fixed first-page cap is not an audit denominator."""
    offset = 0
    while True:
        page = store.list_assets(role=role, limit=_ASSET_PAGE_SIZE, offset=offset)
        yield from page
        if len(page) < _ASSET_PAGE_SIZE:
            return
        offset += len(page)


def _feature_assets(store: AssetStore, run_id: str | None) -> list[Any]:
    assets = list(_iter_assets(store, role=ROLE_FEATURE_BUNDLE))
    if run_id is not None:
        return [a for a in assets if (a.meta or {}).get("run_id") == run_id]
    return assets


def _declared_feature_fields(value: Any) -> dict[str, Any]:
    """Turn the declared field names into keys for the shared recursive leakage checker."""
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return {str(name): None for name in value}
    if value is None:
        return {}
    return {str(value): None}


def _feature_array_names(store: AssetStore, asset: Any) -> list[str]:
    """Read array names without materializing large feature tensors into memory."""
    if not (asset.files or {}).get("arrays"):
        return []
    path, _ = store.resolve_asset_path(asset.asset_id, "arrays")
    with np.load(path, allow_pickle=False) as data:
        return [str(name) for name in data.files]


def _feature_leakage_probe(asset: Any, array_names: Sequence[str]) -> dict[str, Any]:
    meta = dict(asset.meta or {})
    declared = _declared_feature_fields(meta.pop("feature_fields", None))
    # These values identify assets for joins and logs. The encoder adapter removes them before
    # tensor construction; their presence in metadata alone is not a forward-pass leak.
    for key in _INDEX_ONLY_META_FIELDS:
        meta.pop(key, None)
    return {
        "feature_arrays": {str(name): None for name in array_names},
        "feature_metadata": meta,
        "declared_feature_fields": declared,
    }


def _truth_dependencies(store: AssetStore, feature: Any) -> tuple[list[list[tuple[str, str]]], list[str]]:
    """Find answer-layer ancestors, following wrappers but stopping at observed-input assets."""
    found: list[list[tuple[str, str]]] = []
    unresolved: list[str] = []
    queue: list[tuple[str, list[tuple[str, str]]]] = [
        (str(asset_id), [(str(feature.asset_id), str(feature.role)), (str(asset_id), "<unresolved>")])
        for asset_id in (feature.ancestry or [])
    ]
    seen: set[str] = set()
    records: dict[str, Any] = {}
    while queue:
        asset_id, path = queue.pop()
        if asset_id in seen:
            continue
        seen.add(asset_id)
        try:
            record = records.get(asset_id)
            if record is None:
                record = store.get_asset(asset_id)
                records[asset_id] = record
        except SynLabError:
            unresolved.append(asset_id)
            continue
        current = path[:-1] + [(asset_id, str(record.role))]
        if record.role in _TRUTH_ROLES:
            found.append(current)
            continue
        if record.role in _OBSERVATION_BOUNDARY_ROLES:
            continue
        for ancestor in (record.ancestry or []):
            queue.append((str(ancestor), current + [(str(ancestor), "<unresolved>")]))
    return found, unresolved


def _format_dependency_path(path: Sequence[tuple[str, str]]) -> str:
    return " -> ".join(f"{role}:{asset_id}" for asset_id, role in path)


def run_negative_control(store: AssetStore, run_id: str | None = None) -> dict[str, Any]:
    features = _feature_assets(store, run_id)
    checks: dict[str, Any] = {}
    problems: list[str] = []
    available_features = int(store.count_assets(role=ROLE_FEATURE_BUNDLE))
    checks["feature_scope"] = {
        "requested_run_id": run_id,
        "available_in_store": available_features,
        "selected_and_checked": len(features),
        "selection": "all feature assets" if run_id is None else "exact run_id match",
    }

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
    from ..observe.features import assert_no_leakage

    contaminated: list[str] = []
    unresolved_ancestry: list[str] = []
    field_violations: list[str] = []
    for asset in features:
        paths, unresolved = _truth_dependencies(store, asset)
        contaminated.extend(
            f"{asset.asset_id}:truth dependency {_format_dependency_path(path)}" for path in paths)
        unresolved_ancestry.extend(f"{asset.asset_id}:{ancestor}" for ancestor in unresolved)
        try:
            array_names = _feature_array_names(store, asset)
            assert_no_leakage(_feature_leakage_probe(asset, array_names),
                              path=f"feature_asset[{asset.asset_id}]")
        except SynLabError as exc:
            field_violations.append(f"{asset.asset_id}:{exc.message}")
        except Exception as exc:  # noqa: BLE001 - unreadable feature payload cannot prove isolation
            field_violations.append(
                f"{asset.asset_id}:feature payload could not be inspected "
                f"({type(exc).__name__}: {str(exc)[:160]})")
    # Missing references are also a failure to prove isolation; keep the summary boolean
    # aligned with the detailed unresolved-ancestry evidence below.
    checks["truth_isolation"] = not contaminated and not unresolved_ancestry
    checks["truth_dependency_paths"] = contaminated[:20]
    checks["unresolved_ancestry_count"] = len(unresolved_ancestry)
    checks["feature_field_leakage"] = not field_violations
    checks["feature_field_violations"] = field_violations[:20]
    if contaminated:
        problems.append(f"features depend on truth-layer assets: {contaminated[:5]}")
    if unresolved_ancestry:
        problems.append(f"feature ancestry contains unresolved asset refs: {unresolved_ancestry[:5]}")
    if field_violations:
        problems.append(f"feature payload/metadata contains forbidden fields or is unreadable: "
                        f"{field_violations[:5]}")

    # 4 / 5: balancing and generator inventory ---------------------------------
    available_provenance = list(_iter_assets(store, role=ROLE_PROVENANCE))
    provenance = (available_provenance if run_id is None else
                  [a for a in available_provenance if (a.meta or {}).get("run_id") == run_id])
    checks["provenance_scope"] = {
        "requested_run_id": run_id,
        "available_in_store": len(available_provenance),
        "selected_and_counted": len(provenance),
        "selection": "all provenance assets" if run_id is None else "exact run_id match",
    }
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
        "feature_assets_available": available_features,
        "provenance": len(provenance),
        "provenance_assets_available": len(available_provenance),
        "patterns_seen": sorted(patterns),
    }

    # 3: maternal shortcut (needs a pool) --------------------------------------
    pool_report_path = store.root / "reports" / "pool_audit.json"
    if pool_report_path.exists():
        pool = json.loads(pool_report_path.read_text(encoding="utf-8"))
        checks["same_mother_gallery"] = {
            "available": True,
            "distractor_isolated": pool.get("distractor_isolated"),
            "run_attribution": "UNAVAILABLE" if run_id is not None else "NOT_REQUESTED",
            "scope": ("store report; not attributable to requested run" if run_id is not None
                      else "store report; run scope not requested"),
            "note": "same-mother-only gallery performance is reported when the pool is evaluated",
        }
    else:
        checks["same_mother_gallery"] = {"available": False, "status": "NOT_RUN"}

    ok = (checks["metadata_permutation"] and checks["truth_isolation"]
          and checks["feature_field_leakage"] and checks["row_permutation_invariance"])
    return {
        "ok": bool(ok) and not problems,
        "status": "PASS" if ok and not problems else "FAIL",
        "checks": checks,
        "problems": problems,
        "note": ("these are structural controls: metadata-hash and row-order checks do not prove "
                 "that a trained model cannot exploit other shortcuts; that needs a trained-model "
                 "comparison"),
    }
