"""Inspect the committed feature_bundle / label_bundle / clean_truth payloads."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from synlab.storage.store import AssetStore  # noqa: E402


def _describe(value, depth=0):
    if isinstance(value, np.ndarray):
        return {"ndarray": list(value.shape), "dtype": str(value.dtype)}
    if isinstance(value, dict):
        if depth > 2:
            return {k: type(v).__name__ for k, v in list(value.items())[:20]}
        return {str(k): _describe(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, (list, tuple)):
        return [f"list[{len(value)}]"] if depth < 2 else f"list[{len(value)}]"
    return f"{type(value).__name__}={str(value)[:60]}"


def main() -> None:
    store = AssetStore(sys.argv[1])
    out = {}
    for role in ("feature_bundle", "label_bundle", "clean_truth", "physical_truth", "obs_result"):
        assets = store.list_assets(role=role, limit=1)
        if not assets:
            out[role] = None
            continue
        asset = assets[0]
        arrays = store.load_arrays(asset.asset_id)
        out[role] = {
            "asset_id": asset.asset_id,
            "qa_status": asset.qa_status,
            "array_keys": {k: list(v.shape) for k, v in sorted(arrays.items())},
            "meta": _describe({k: v for k, v in (asset.meta or {}).items()
                               if k not in ("relations",)}),
        }
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str)[:12000])


if __name__ == "__main__":
    main()
