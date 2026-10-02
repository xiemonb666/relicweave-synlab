"""Probe the real payloads of the four 'not yet packaged' dimensions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from synlab.storage.store import AssetStore  # noqa: E402

out: dict[str, object] = {}


def blob_path(store: AssetStore, record) -> Path | None:
    if not record.blob_hash:
        return None
    return store.blob_path(record.blob_hash)


for name, path in (("roi", "data/a12_roi/store"), ("extras", "data/a12_extras/store"),
                   ("context", "data/a12_context/store"), ("degrade", "data/a12_degrade/store")):
    store = AssetStore(Path(path))
    assets = store.list_assets(limit=500000)
    entries = []
    for a in assets:
        meta = a.meta or {}
        bp = blob_path(store, a)
        entry = {
            "asset_id": a.asset_id, "role": a.role, "schema": a.schema, "unit": a.unit,
            "frame": a.frame, "lineage_id": a.lineage_id, "split": str(a.split),
            "qa_status": a.qa_status, "files": list(a.files or []),
            "blob_bytes": bp.stat().st_size if bp and bp.exists() else None,
            "meta_keys": sorted(meta.keys()),
        }
        if a.role in ("obs_result", "context_pack", "degrade_variant", "degrade_source",
                      "feature_bundle", "fragment_mesh"):
            small = {}
            for k, v in meta.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    small[k] = v
                elif isinstance(v, list):
                    small[k] = f"list[{len(v)}]"
                elif isinstance(v, dict):
                    small[k] = {kk: (vv if isinstance(vv, (str, int, float, bool)) or vv is None
                                     else (f"list[{len(vv)}]" if isinstance(vv, list)
                                           else type(vv).__name__))
                                 for kk, vv in list(v.items())[:25]}
            entry["meta"] = small
        entries.append(entry)
    out[name] = {"store": path, "assets": len(assets), "entries": entries}
    print("=" * 100)
    print(f"{name}: {path}  assets={len(assets)}")
    for e in entries:
        if e["role"] in ("obs_result", "context_pack", "degrade_variant", "degrade_source"):
            print(json.dumps({k: v for k, v in e.items() if k != "meta"}, ensure_ascii=False)[:600])
            print("   meta:", json.dumps(e.get("meta"), ensure_ascii=False)[:1400])

Path("data/a12_reports/_merge_dimension_probe.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
print("\nwrote data/a12_reports/_merge_dimension_probe.json")
