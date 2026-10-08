"""Probe: does the closed-loop store still carry leaking feature bundles inside a frozen release?"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.roles import FORBIDDEN_FEATURE_FIELDS, ROLE_FEATURE_BUNDLE  # noqa: E402
from synlab.storage.release import ReleaseManager  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

store = AssetStore(ROOT / "data/a12_exports/closed_loop/store")
features = store.list_assets(role=ROLE_FEATURE_BUNDLE, limit=10000)
leaky = [a for a in features
         if set(a.meta or {}) & FORBIDDEN_FEATURE_FIELDS]
print("closed_loop feature_bundle assets:", len(features), "with forbidden keys:", len(leaky))

manager = ReleaseManager(store)
for row in manager.list_releases():
    manifest = json.loads(Path(row["manifest_path"]).read_text(encoding="utf-8"))
    ids = {a["asset_id"] for a in manifest.get("assets", [])}
    inside = sorted(a.asset_id for a in leaky if a.asset_id in ids)
    print("release", row["release_id"], row["manifest_hash"][:30], row["profile"],
          "| assets", len(ids), "| leaky feature assets inside", len(inside))
    for asset_id in inside[:5]:
        print("    ", asset_id)
