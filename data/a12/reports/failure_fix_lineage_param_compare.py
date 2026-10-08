"""Compare the parameters the running batch really used for one lineage with the plan snapshot.

``LIN0016_V19_M04_PAT08`` failed in the observation stage under the other writer's process but
replays cleanly with the parameters of my plan snapshot.  The committed ``mother_mesh`` asset of
that lineage records the real dictionary, so the difference is measurable instead of guessed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.storage.store import AssetStore  # noqa: E402

LIN = "LIN0016_V19_M04_PAT08"
PLAN = json.loads((ROOT / "data" / "a12" / "reports" /
                   "failure_class1_param_validation.json").read_text(encoding="utf-8"))
mine = next(r for r in PLAN["rows"] if r["lineage_id"] == LIN)
print(f"plan snapshot: vessel={mine['vessel_id']} material={mine['material_id']} "
      f"pattern={mine['pattern_id']}")
print("plan params:", json.dumps(mine["params"], sort_keys=True))

for root in (ROOT / "data" / "a12", ROOT / "data" / "a12" / "reports" / "failure_fix_store"):
    store = AssetStore(root)
    found = []
    for asset in store.list_assets(limit=500000):
        if getattr(asset, "lineage_id", None) != LIN or asset.role != "mother_mesh":
            continue
        found.append({"asset_id": asset.asset_id, "qa": asset.qa_status,
                      "variant": (asset.meta or {}).get("variant"),
                      "params": (asset.meta or {}).get("params")})
    print(f"\n{root.relative_to(ROOT)}: {len(found)} mother assets")
    for item in found:
        same = dict(item["params"] or {}) == dict(mine["params"])
        print(f"  {item['asset_id']} qa={item['qa']} variant={item['variant']} "
              f"params_identical_to_plan={same}")
        if not same:
            keys = sorted(set(item["params"] or {}) | set(mine["params"]))
            for key in keys:
                a = (item["params"] or {}).get(key)
                b = mine["params"].get(key)
                if a != b:
                    print(f"     {key}: batch={a!r} plan={b!r}")
