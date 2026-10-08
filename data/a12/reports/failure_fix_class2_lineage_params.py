"""Dump, for the failing lineages, the mother assets already committed by the running batch.

Read-only probe: it never writes to the store.  Its purpose is to recover the *real*
parameters the failing mothers were built with, so the pattern-stage failure can be
reproduced from the real inputs instead of a guess.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.storage.store import AssetStore  # noqa: E402

WANTED = [
    "LIN0001_V21_M06_PAT16",
    "LIN0002_V23_M07_PAT12",
    "LIN0003_V23_M11_PAT06",
    "LIN0004_V10_M06_PAT03",
    "LIN0000_V10_M11_PAT15",
]

store = AssetStore(ROOT / "data" / "a12")
found: dict[str, list[dict]] = {lid: [] for lid in WANTED}
assets = store.list_assets(limit=500000)
print(f"assets: {len(assets)}")
for asset in assets:
    lineage = getattr(asset, "lineage_id", None)
    if lineage in found:
        found[lineage].append({
            "asset_id": asset.asset_id,
            "role": asset.role,
            "qa": asset.qa_status,
            "meta": {k: v for k, v in (asset.meta or {}).items()
                     if k in ("vessel_id", "material_id", "mother_id", "params", "variant",
                              "fragment_id", "component_id")},
        })

out = {}
for lineage, items in found.items():
    print(f"--- {lineage}: {len(items)} assets")
    keep = [i for i in items if i["role"] in ("mother_mesh", "pattern_recipe", "pattern_channels")]
    for i in keep:
        print(f"    {i['role']:18s} {i['qa']:10s} {i['asset_id']} {json.dumps(i['meta'], default=str)[:220]}")
    out[lineage] = keep
(ROOT / "data" / "a12" / "reports" / "_f2_lineage_params.json").write_text(
    json.dumps(out, indent=2, default=str), encoding="utf-8")
print("written")

