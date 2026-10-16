"""Which fragment did the pipeline really damage in the isolated run? (from the store record)

``physical_result`` stores the survivor map with one ``ancestor`` per component, i.e. the
fragment id the declared recipe was applied to.  For ``LIN0004_V10_M06_PAT03`` that used to be
the untouched lid (``…_E01-m``); after the fix it must be a fragment that carries the interface.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.storage.store import AssetStore  # noqa: E402

STORE = ROOT / "data" / "a12" / "reports" / "failure_fix_store"
OUT = ROOT / "data" / "a12" / "reports" / "failure_class3_pipeline_target.json"

store = AssetStore(STORE)
rows = []
for asset in store.list_assets(limit=500000):
    if asset.role != "physical_result":
        continue
    qa = dict(asset.qa or {})
    components = qa.get("components") or []
    ancestors = sorted({str(c.get("ancestor")) for c in components if isinstance(c, dict)})
    representatives = [str(c.get("ancestor")) for c in components
                       if isinstance(c, dict) and c.get("is_representative")]
    rows.append({
        "lineage_id": getattr(asset, "lineage_id", None),
        "axis_id": qa.get("axis_id"), "status": qa.get("status"),
        "failure_codes": qa.get("failure_codes"),
        "ancestors": ancestors,
        "damaged_fragment": representatives[0] if representatives else None,
        "n_components": len(components),
        "lost_volume_ratio": (qa.get("measured") or {}).get("lost_volume_ratio")
        if isinstance(qa.get("measured"), dict) else None,
    })
for row in sorted(rows, key=lambda r: str(r["lineage_id"])):
    print(f"{row['lineage_id']:26s} {row['axis_id']} {str(row['status']):5s} "
          f"damaged={row['damaged_fragment']} ancestors={row['ancestors']} "
          f"codes={row['failure_codes']}")
OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(f"\nwritten {OUT.relative_to(ROOT)}")
