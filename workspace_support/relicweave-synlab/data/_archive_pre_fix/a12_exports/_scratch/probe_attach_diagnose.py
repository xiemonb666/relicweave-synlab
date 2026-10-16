"""Diagnose why relations.gallery.attach_features attaches 0 payloads in the a12 store."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.relations.gallery import collect_fragments  # noqa: E402
from synlab.roles import ROLE_FEATURE_BUNDLE, ROLE_PROVENANCE  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

store = AssetStore(ROOT / "data/a12")
records = collect_fragments(store)
print("fragment records:", len(records))
for fid, rec in sorted(records.items()):
    print(f"  {fid}: label_ref={rec.label_ref} obs_ref={rec.obs_ref} feature_ref={rec.feature_ref}")
label_refs = {rec.label_ref for rec in records.values()}
print("label_to_fragment keys:", sorted(label_refs))

print("\nprovenance assets:")
for asset in store.list_assets(role=ROLE_PROVENANCE, limit=100):
    ancestry = list(asset.ancestry or [])
    print(f"  {asset.asset_id} run={ (asset.meta or {}).get('run_id')} ancestry={ancestry} "
          f"ancestry[1]_is_label_ref={len(ancestry) > 1 and ancestry[1] in label_refs}")

print("\nfeature assets (meta fragment_id / component_id / observation_id):")
for asset in store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=100):
    meta = asset.meta or {}
    print(f"  {asset.asset_id} run={meta.get('run_id')} fragment_id={meta.get('fragment_id')!r} "
          f"component_id={meta.get('component_id')!r} observation_id={meta.get('observation_id')!r} "
          f"ancestry={list(asset.ancestry or [])} schema={meta.get('schema')}")
