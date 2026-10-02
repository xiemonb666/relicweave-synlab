"""Compact probe: payload encoding + channel inventory of the four extra dimensions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

summary: dict[str, object] = {}


def payload(store: AssetStore, record) -> dict:
    return store.read_payload(record) if hasattr(store, "read_payload") else None


for name, path in (("roi", "data/a12_roi/store"), ("extras", "data/a12_extras/store"),
                   ("context", "data/a12_context/store"), ("degrade", "data/a12_degrade/store")):
    store = AssetStore(Path(path))
    assets = store.list_assets(limit=500000)
    rows = []
    for a in assets:
        bp = store.blob_path(a.blob_hash) if a.blob_hash else None
        rows.append({
            "asset_id": a.asset_id, "role": a.role, "schema": a.schema, "unit": a.unit,
            "frame": a.frame, "lineage": a.lineage_id, "files": list(a.files or []),
            "blob_mb": round(bp.stat().st_size / 1e6, 3) if bp and bp.exists() else None,
            "axis": (a.meta or {}).get("axis_id"), "level": (a.meta or {}).get("level"),
            "identity": (a.meta or {}).get("identity"),
        })
    summary[name] = rows
    print(f"== {name}: {len(rows)} assets, total blob MB "
          f"{round(sum(r['blob_mb'] or 0 for r in rows), 1)}")
    for r in rows:
        if r["role"] in ("obs_result", "context_pack", "degrade_variant", "degrade_source",
                         "feature_bundle", "fragment_mesh"):
            print("   ", json.dumps(r, ensure_ascii=False))

# ---- one ROI obs_result payload, channel inventory --------------------------------
store = AssetStore(Path("data/a12_roi/store"))
for a in store.list_assets(limit=100):
    if a.role != "obs_result":
        continue
    print("\n=== ROI payload:", a.asset_id, "files=", a.files, "blob_mb=",
          round(store.blob_path(a.blob_hash).stat().st_size / 1e6, 2))
    raw = store.read_blob(a.blob_hash)
    print("   first 200 bytes:", raw[:200])
    try:
        import msgpack
        obj = msgpack.unpackb(raw, raw=False, strict_map_key=False)
        print("   msgpack top keys:", list(obj.keys())[:40] if isinstance(obj, dict) else type(obj))
        if isinstance(obj, dict):
            for k, v in list(obj.items())[:6]:
                print(f"     {k}: {type(v).__name__} "
                      f"{list(v.keys())[:20] if isinstance(v, dict) else (len(v) if hasattr(v, '__len__') else v)}")
    except Exception as exc:  # noqa: BLE001
        print("   msgpack failed:", type(exc).__name__, exc)
    break

Path("data/a12_reports/_merge_dimension_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
print("\nwrote data/a12_reports/_merge_dimension_summary.json")
