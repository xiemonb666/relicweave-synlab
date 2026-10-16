"""Dump QA/meta of interesting assets in a store (diagnostic)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from synlab.storage.store import AssetStore  # noqa: E402


def main() -> None:
    store = AssetStore(sys.argv[1])
    roles = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    for asset in store.list_assets(limit=10000):
        if roles and asset.role not in roles:
            continue
        print("=" * 90)
        print(f"{asset.role} {asset.asset_id} qa_status={asset.qa_status} split={asset.split}")
        print("QA:", json.dumps(asset.qa, ensure_ascii=False, indent=1, default=str)[:2500])
        meta = {k: v for k, v in (asset.meta or {}).items()
                if k not in ("feature_fields", "relations", "relations_json")}
        print("META:", json.dumps(meta, ensure_ascii=False, indent=1, default=str)[:4000])
        if "relations" in (asset.meta or {}):
            rows = asset.meta["relations"]
            from collections import Counter

            print("RELATIONS:", len(rows), Counter(r.get("kind") for r in rows))
            for r in rows[:8]:
                print("   ", json.dumps(r, ensure_ascii=False, default=str)[:400])
        print("FILES:", list((asset.files or {}).keys()))


if __name__ == "__main__":
    main()
