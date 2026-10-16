"""Store health + role census after the repair (read-only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.storage.store import health_check  # noqa: E402

for rel in ("data/a12", "data/a12_exports/closed_loop/store"):
    root = ROOT / rel
    health = health_check(str(root))
    print(f"{rel}: ok={health.get('ok')} assets={health.get('assets')} "
          f"files_checked={health.get('files_checked')} blobs={health.get('blobs')} "
          f"problems={json.dumps(health.get('problems'))[:400]}")
    for key in ("missing_files", "hash_mismatches", "orphan_files", "db_integrity"):
        if key in health:
            print(f"   {key}: {json.dumps(health[key])[:200]}")
