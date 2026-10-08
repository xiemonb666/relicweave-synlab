"""Read the A01/A02/A32 entries out of an acceptance summary (keeps console output small)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
wanted = sys.argv[2].split(",") if len(sys.argv) > 2 else ["A01", "A02", "A32"]
data = json.loads(path.read_text(encoding="utf-8"))
print("counts:", json.dumps(data.get("counts"), sort_keys=True))
print("profile:", data.get("profile"), "generated_at:", data.get("generated_at"))
for key in wanted:
    entry = (data.get("items") or {}).get(key)
    print(f"\n=== {key} ===")
    print(json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True, default=str)[:3000])
