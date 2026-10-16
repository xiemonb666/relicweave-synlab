"""Print a compact digest of a closed-loop ledger (the full file is ~74 MB)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open("r", encoding="utf-8") as handle:
    data = json.load(handle)

print("keys:", sorted(data))
print("run_id:", data.get("run_id"), "ok:", data.get("ok"))
print("step_status:", json.dumps(data.get("step_status"), sort_keys=True))
print("degraded:", json.dumps(data.get("degraded_steps"), sort_keys=True))
print("failed:", json.dumps(data.get("failed_steps"), sort_keys=True))
for entry in data.get("steps", []):
    name = entry.get("step")
    keep = {k: v for k, v in entry.items()
            if k in ("status", "seconds", "run_id", "accepted", "attempted", "release_id",
                     "release_profile", "assets", "scope_pending", "scope_completed",
                     "gates", "required_gates", "bytes_total", "files_total", "counts",
                     "ok", "error", "pool_status", "candidates", "queries", "r2_edges",
                     "manifest_hash", "views", "separation", "relation_kinds", "labels",
                     "token_cache", "reference_closure")}
    text = json.dumps(keep, sort_keys=True, default=str)
    print(f"\n=== {name} ===")
    print(text[:4000])
