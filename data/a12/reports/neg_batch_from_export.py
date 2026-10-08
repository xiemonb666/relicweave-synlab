"""Build a real training batch from the existing exported package (item 3, step 1)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from synlab.relations.negatives import build_training_batch_for_package  # noqa: E402

PACKAGE = REPO / "data" / "a12_exports" / "closed_loop" / "training_package"
OUT = REPO / "data" / "a12" / "reports" / "relation_negatives_batch_from_export.json"

result = build_training_batch_for_package(PACKAGE)
result.pop("batch_object", None)
result.pop("pool_object", None)
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

print(json.dumps({k: v for k, v in result.items()
                  if k not in ("rows", "exposure", "batch", "pool_mates_used_for_R2",
                               "negative_audit")}, ensure_ascii=False, indent=2, default=str))
print("batch:", json.dumps(result["batch"], ensure_ascii=False))
print("negative_audit:", json.dumps(result["negative_audit"], ensure_ascii=False)[:800])
print("frozen_probe_pool_route:", json.dumps(result["frozen_probe_pool_route"], ensure_ascii=False)[:600])
print("rows:", json.dumps(result["rows"], ensure_ascii=False))
