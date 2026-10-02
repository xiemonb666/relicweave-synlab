"""Real census of candidate source stores for the merged experiment-ready export.

Read-only.  Every number printed here comes from the store index / asset payloads.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from synlab.storage.store import AssetStore  # noqa: E402

STORES = [
    "data/a12_trainable/store",
    "data/a12_campaign/store",
    "data/a12_roi/store",
    "data/a12_extras/store",
    "data/a12_context/store",
    "data/a12_degrade/store",
    "data/a12_iface/store",
    "data/a12",
    "data/a12_neg/store",
]

report: dict[str, object] = {}
for s in STORES:
    p = Path(s)
    if not (p / "metadata.sqlite").exists():
        report[s] = {"present": False}
        continue
    store = AssetStore(p)
    assets = store.list_assets(limit=500000)
    roles = collections.Counter(a.role for a in assets)
    entry: dict[str, object] = {
        "present": True,
        "assets": len(assets),
        "roles": dict(sorted(roles.items())),
    }
    frags: set[str] = set()
    for a in assets:
        if a.role == "obs_result":
            fid = (a.meta or {}).get("fragment_id")
            if fid:
                frags.add(str(fid))
    entry["obs_fragments"] = len(frags)
    entry["obs_fragment_ids"] = sorted(frags)[:40]
    # view counts for obs_result
    nviews: dict[str, int] = {}
    for a in assets:
        if a.role == "obs_result":
            vs = (a.meta or {}).get("views")
            if isinstance(vs, list):
                nviews[str((a.meta or {}).get("fragment_id"))] = len(vs)
    entry["obs_view_counts"] = dict(sorted(nviews.items())[:40])
    lineages = sorted({a.lineage_id for a in assets if a.lineage_id})
    entry["lineages"] = len(lineages)
    entry["lineage_ids_sample"] = lineages[:25]
    rels = [a for a in assets if a.role == "relation_pool"]
    entry["relation_pool_assets"] = len(rels)
    report[s] = entry
    print("=" * 100)
    print(s)
    print(json.dumps({k: v for k, v in entry.items() if k != "obs_fragment_ids"},
                     ensure_ascii=False, indent=1, default=str))

Path("data/a12_reports/_merge_store_census.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str),
    encoding="utf-8")
print("\nwrote data/a12_reports/_merge_store_census.json")
