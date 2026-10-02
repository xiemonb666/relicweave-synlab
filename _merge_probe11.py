"""Why the shipped relation table has 3442 rows and the S3 audit reported 3588.

The S3 audit (`tools/a12_relation_direction_audit.py`) builds its scope from **every asset of the
store** whose role is relation_pool / clean_truth / label_bundle; the export builds its table from
the **frozen 328-asset release scope**.  This probe measures both populations with the same
function so the difference is a number, not a story.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from synlab.storage.export import _pool_relations          # noqa: E402
from synlab.storage.store import AssetStore                # noqa: E402

STORE = Path("data/a12_trainable/store")
STATE = Path("data/a12_exports/trainable/next_experiment/next_experiment_export_state.json")

state = json.loads(STATE.read_text(encoding="utf-8"))
scope_ids = set((state.get("freeze") or {}).get("unverified_scope_ids") or [])
store = AssetStore(STORE)

out: dict[str, object] = {}
for label, keep in (("whole_store", None), ("frozen_release_scope", scope_ids)):
    assets = store.list_assets(limit=500000)
    scope: dict[str, object] = {}
    for asset in assets:
        if asset.role not in ("relation_pool", "clean_truth", "label_bundle"):
            continue
        if keep is not None and asset.asset_id not in keep:
            continue
        scope[asset.asset_id] = asset
    rows = _pool_relations(store, scope)
    pairs = {(r["a"], r["b"]) if r["a"] <= r["b"] else (r["b"], r["a"]) for r in rows}
    out[label] = {
        "assets": len(scope),
        "role_counts_sql": {},
        "statement_rows": len(rows),
        "unordered_pairs": len(pairs),
        "complete_rows_if_direction_complete": 2 * len(pairs),
    }
    counts: dict[str, int] = {}
    for asset in scope.values():
        counts[asset.role] = counts.get(asset.role, 0) + 1
    out[label]["role_counts_sql"] = counts
    print(label, json.dumps(out[label], ensure_ascii=False, sort_keys=True))

whole = out["whole_store"]
scope_only = out["frozen_release_scope"]
print("\ndifference in unordered pairs:",
      int(whole["unordered_pairs"]) - int(scope_only["unordered_pairs"]))
print("assets outside the frozen scope:",
      int(whole["assets"]) - int(scope_only["assets"]))

Path("data/a12_reports/_merge_relation_population.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
print("wrote data/a12_reports/_merge_relation_population.json")
