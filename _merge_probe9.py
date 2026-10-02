"""Probe the ROI obs meta, view meta and the context_pack meta (the real payloads)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from synlab.storage.store import AssetStore  # noqa: E402


def show(obj, depth=0, maxdepth=2, prefix=""):
    pad = "  " * depth
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and depth < maxdepth:
                print(f"{pad}{k}: {type(v).__name__}[{len(v)}]")
                show(v, depth + 1, maxdepth, prefix)
            else:
                s = json.dumps(v, ensure_ascii=False, default=str)
                print(f"{pad}{k}: {s[:220]}")
    elif isinstance(obj, list) and obj:
        show(obj[0], depth, maxdepth, prefix)


roi = AssetStore(Path("data/a12_roi/store"))
assets = roi.list_assets(limit=10)
a = assets[0]
print("=== ROI obs meta (asset", a.asset_id, ")")
show(a.meta, 0, 1)
views = (a.meta or {}).get("views")
if isinstance(views, list):
    print("\n--- n views:", len(views))
    for v in views[:2] + views[-2:]:
        print("  view:", json.dumps({k: vv for k, vv in v.items() if k != "meta"},
                                    ensure_ascii=False, default=str)[:400])
        print("  meta:", json.dumps(v.get("meta"), ensure_ascii=False, default=str)[:900])

ctx = AssetStore(Path("data/a12_context/store"))
for asset in ctx.list_assets(limit=100):
    if asset.role == "context_pack":
        print("\n=== context_pack meta:", asset.asset_id)
        print(json.dumps(asset.meta, ensure_ascii=False, indent=1, default=str)[:3000])

ex = AssetStore(Path("data/a12_extras/store"))
for asset in ex.list_assets(limit=100):
    if asset.role == "context_pack":
        print("\n=== extras context_pack meta:", asset.asset_id)
        print(json.dumps(asset.meta, ensure_ascii=False, indent=1, default=str)[:2000])
