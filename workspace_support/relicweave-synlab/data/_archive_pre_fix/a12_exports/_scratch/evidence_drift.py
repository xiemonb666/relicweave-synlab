"""Compare the frozen manifest's recorded evidence hashes with the files on disk now."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.canonical import hash_file  # noqa: E402

manifest_path = Path(sys.argv[1])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
evidence = (manifest.get("extra") or {}).get("evidence_reports") or {}
print("release:", manifest["release_id"], "frozen_at:", manifest["frozen_at"])
print("recorded evidence files:", len(evidence))
drift = []
for name, entry in sorted(evidence.items()):
    path = Path(entry.get("path") or "")
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        drift.append({"name": name, "path": str(path), "state": "MISSING"})
        continue
    current = hash_file(path)
    if current != entry.get("hash"):
        drift.append({"name": name, "path": str(path), "recorded": entry.get("hash"),
                      "current": current})
print("drifted after the freeze:", len(drift))
for item in drift:
    print("  ", json.dumps(item, sort_keys=True))
