"""Measure whether the repair changed what relations.gallery.attach_features can map.

Pre-repair state = the same store root with the *backup* database (rows of the retired assets),
so the mapping stage runs against the metadata that existed before the repair.  The retired
directories are gone, so a found reference shows up as ``failed`` (unreadable payload) instead of
``attached`` -- which is exactly the signal we need: was a fragment -> feature reference found?

Post-repair state = the live store.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.relations.gallery import (  # noqa: E402
    RelationPool,
    RelationsIndex,
    attach_features,
    collect_fragments,
)
from synlab.roles import ROLE_CLEAN_TRUTH, ROLE_LABEL_BUNDLE, ROLE_PROVENANCE  # noqa: E402
from synlab.schemas.runtime import GallerySpec  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

BACKUP = ROOT / "data/a12/reports/_store_backup_pre_feature_leak_repair.sqlite"


def run(store: AssetStore, label: str) -> dict:
    fragments = collect_fragments(store)
    lineup = sorted(fragments)
    gallery = GallerySpec(pool_id=f"probe_{label}", gallery_version="probe", scope="FULL",
                          lineage_ids=sorted({f.lineage_id for f in fragments.values()}),
                          fragment_ids=lineup, size_target=len(lineup), split="train")
    pool = RelationPool(gallery=gallery, fragments=fragments, index=RelationsIndex())
    report = attach_features(pool, store)
    refs = {fid: pool.fragments[fid].feature_ref for fid in lineup
            if pool.fragments[fid].feature_ref}
    print(f"[{label}] {report} refs_found={len(refs)}")
    for fid, ref in sorted(refs.items()):
        print(f"    {fid} -> {ref}")
    return {"report": report, "refs": refs}


print("=== pre-repair rows (backup DB) ===")
pre = run(AssetStore(ROOT / "data/a12", db_path=BACKUP), "pre_repair")
print()
print("=== post-repair (live store) ===")
post = run(AssetStore(ROOT / "data/a12"), "post_repair")

print()
print("=== retired feature meta that the primary mapping path used ===")
payload = json.loads((ROOT / "data/a12/reports/feature_leak_repair.json").read_text(encoding="utf-8"))
for entry in payload["entries"]:
    meta = entry["tombstone"]["meta"]
    print(f"  {entry['asset_id']}: meta.fragment_id={meta.get('fragment_id')!r} "
          f"component_id={meta.get('component_id')!r} observation_id={meta.get('observation_id')!r}")

print()
print("=== label / clean_truth metadata that the fallback paths read ===")
store = AssetStore(ROOT / "data/a12")
for role in (ROLE_LABEL_BUNDLE, ROLE_CLEAN_TRUTH):
    for asset in store.list_assets(role=role, limit=100):
        meta = asset.meta or {}
        print(f"  {role} {asset.asset_id} fragment_id={meta.get('fragment_id')!r} "
              f"feature_ref={meta.get('feature_ref')!r} observation_id={meta.get('observation_id')!r}")
print()
print("=== provenance ancestry vs label_to_fragment ===")
records = collect_fragments(store)
label_keys = {rec.label_ref for rec in records.values()}
for asset in store.list_assets(role=ROLE_PROVENANCE, limit=100):
    ancestry = list(asset.ancestry or [])
    print(f"  {asset.asset_id} run={(asset.meta or {}).get('run_id')} "
          f"ancestry[1]={ancestry[1] if len(ancestry) > 1 else None} "
          f"in_label_to_fragment={len(ancestry) > 1 and ancestry[1] in label_keys}")
