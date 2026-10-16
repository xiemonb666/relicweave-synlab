"""Measure the pool feature-attachment path before/after the leak repair, with the mapping stage
separated from the payload stage.

``attach_features`` has three mapping sources (feature ``meta["fragment_id"]``, feature ancestry,
provenance ancestry) and then rebuilds the payload with ``_feature_payload``.  This probe reports
each stage separately, plus ``_feature_payload`` on a *never repaired* feature asset, so a change
caused by the repair can be told apart from the store's pre-existing behaviour.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.relations.gallery import (  # noqa: E402
    _feature_payload,
    collect_fragments,
)
from synlab.roles import ROLE_FEATURE_BUNDLE, ROLE_PROVENANCE  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

BACKUP = ROOT / "data/a12/reports/_store_backup_pre_feature_leak_repair.sqlite"


def mapping(store: AssetStore) -> dict[str, str]:
    """Verbatim copy of attach_features' mapping stage (gallery.py lines 606-622)."""
    records = collect_fragments(store)
    label_to_fragment = {rec.label_ref: fid for fid, rec in records.items() if rec.label_ref}
    feature_assets: dict[str, str] = {}
    for asset in store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=10000):
        meta = dict(asset.meta or {})
        fid = str(meta.get("fragment_id") or "")
        if fid:
            feature_assets[fid] = asset.asset_id
        for ancestor in asset.ancestry or []:
            if ancestor in label_to_fragment:
                feature_assets.setdefault(label_to_fragment[ancestor], asset.asset_id)
    for asset in store.list_assets(role=ROLE_PROVENANCE, limit=10000):
        ancestry = list(asset.ancestry or [])
        if len(ancestry) >= 2 and ancestry[1] in label_to_fragment:
            feature_assets.setdefault(label_to_fragment[ancestry[1]], ancestry[0])
    return feature_assets


def stage(store: AssetStore, label: str) -> dict:
    refs = mapping(store)
    readable, payloads = {}, {}
    for fid, ref in refs.items():
        if ref in {a.asset_id for a in store.list_assets(limit=100000)}:
            try:
                arrays = store.load_arrays(ref)
            except Exception as exc:  # noqa: BLE001 - the pre-repair dirs are gone by design
                readable[fid] = f"UNREADABLE: {type(exc).__name__}"
                continue
            payload = _feature_payload(store, ref, arrays)
            payloads[fid] = bool(payload)
    print(f"[{label}] mapped fragments={len(refs)} refs={sorted(refs.items())}")
    print(f"[{label}] payload built: {payloads}")
    if readable:
        print(f"[{label}] unreadable refs: {readable}")
    return refs


print("=== mapping stage, pre-repair rows (backup DB) ===")
stage(AssetStore(ROOT / "data/a12", db_path=BACKUP), "pre_repair")
print()
print("=== mapping stage, post-repair (live store) ===")
stage(AssetStore(ROOT / "data/a12"), "post_repair")
print()
print("=== _feature_payload on a never-repaired (clean run) feature asset ===")
store = AssetStore(ROOT / "data/a12")
for asset in store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=10000):
    meta = asset.meta or {}
    if meta.get("run_id") != "run_23664ddb26eada4b":
        continue
    arrays = store.load_arrays(asset.asset_id)
    payload = _feature_payload(store, asset.asset_id, arrays)
    print(f"  {asset.asset_id}: arrays={sorted(arrays)}")
    print(f"    has 'points'={('points' in arrays)} has 'global_rgb'={('global_rgb' in arrays)} "
          f"payload_empty={not payload}")
    break
print()
print("=== repaired feature meta (what the primary mapping key would have been) ===")
report = json.loads((ROOT / "data/a12/reports/feature_leak_repair.json").read_text(encoding="utf-8"))
for entry in report["entries"][:2]:
    print(" ", entry["asset_id"], "->", entry["new_asset_id"],
          "dropped", entry["meta_diff"]["dropped_keys"],
          "kept_observation_fields", entry["new_meta"].get("leak_repair", {}).get("kept_observation_fields"))
