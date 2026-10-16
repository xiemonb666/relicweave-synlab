"""Probe: do the repaired feature bundles still attach to fragments through the real pool code?

The repair removed ``meta["fragment_id"]`` from 8 feature bundles, which is the *primary* key
``relations.gallery.attach_features`` uses to map fragment -> feature payload.  This probe builds a
real ``RelationPool`` from the store's own label/clean_truth records and calls the real
``attach_features``, so the fallback (provenance ancestry) is measured instead of assumed.
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
from synlab.roles import ROLE_FEATURE_BUNDLE  # noqa: E402
from synlab.schemas.runtime import GallerySpec  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

store = AssetStore(ROOT / "data/a12")
fragments = collect_fragments(store)
lineup = sorted(fragments)
gallery = GallerySpec(pool_id="probe_feature_attach", gallery_version="probe",
                      scope="FULL", lineage_ids=sorted({f.lineage_id for f in fragments.values()}),
                      fragment_ids=lineup, size_target=len(lineup), split="train")
pool = RelationPool(gallery=gallery, fragments=fragments, index=RelationsIndex())
report = attach_features(pool, store)

repaired = {}
repair_path = ROOT / "data/a12/reports/feature_leak_repair.json"
if repair_path.exists():
    payload = json.loads(repair_path.read_text(encoding="utf-8"))
    repaired = {e["asset_id"]: e.get("new_asset_id") for e in payload.get("entries") or []}

attached_refs = {fid: pool.fragments[fid].feature_ref for fid in lineup
                 if pool.fragments[fid].feature_ref}
new_ids = set(repaired.values())
print("fragments in lineup:", len(lineup))
print("attach_features:", report)
print("fragments with an attached feature payload:", len(attached_refs))
print("attached via a repaired (new) asset id:", sorted(set(attached_refs.values()) & new_ids))
print("feature assets in store:", len(store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=10000)))
print("detailed mapping:")
for fid in lineup:
    rec = pool.fragments[fid]
    tag = "REPAIRED" if rec.feature_ref in new_ids else ""
    print(f"  {fid} -> feature_ref={rec.feature_ref} payload={'yes' if fid in pool.features else 'no'} {tag}")
