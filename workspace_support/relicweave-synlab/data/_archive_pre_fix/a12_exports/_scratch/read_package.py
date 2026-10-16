"""Scratch: dump the real exported training package structure (read-only)."""
from __future__ import annotations

import json
import sys

sys.path.insert(0, r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")

from synlab.storage.export import TrainingPackage  # noqa: E402

PKG = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\data\a12_exports\closed_loop\training_package"

pkg = TrainingPackage(PKG)
print("manifest keys:", sorted(pkg.manifest.keys()))
print("files in manifest:", len(pkg.manifest.get("files", [])))
print("verify:", json.dumps(pkg.verify_files(), ensure_ascii=False)[:400])

rel = pkg.relations()
print("\n== relations", len(rel), "rows ==")
for r in rel:
    print("  ", json.dumps({k: (str(v)[:40]) for k, v in r.items()}, ensure_ascii=False))

q = pkg.queries()
print("\n== queries", len(q), "rows ==")
for r in q:
    print("  ", json.dumps({k: (str(v)[:60]) for k, v in r.items()}, ensure_ascii=False))

for layer in ("clean", "visible", "physical"):
    rows = pkg.labels(layer)
    print(f"\n== labels[{layer}] {len(rows)} rows ==")
    for r in rows:
        print("  ", json.dumps({k: (str(v)[:60]) for k, v in r.items()}, ensure_ascii=False))

idx = pkg.observation_index()
print("\n== obs index rows:", len(idx.get("rows", {})), "keys:", sorted(idx.keys()))
for fid, entry in list(idx.get("rows", {}).items())[:20]:
    print("  ", fid, json.dumps({k: str(v)[:40] for k, v in entry.items()}))

for rel_path, root in (("geometry/index.json", pkg.deploy), ("tokens/index.json", pkg.deploy)):
    data = json.loads((root / rel_path).read_text(encoding="utf-8"))
    print(f"\n== {rel_path}: rows={len(data.get('rows', {}))} keys={sorted(data.keys())}")
    for fid, entry in list(data.get("rows", {}).items()):
        print("  ", fid, json.dumps({k: str(v)[:60] for k, v in entry.items()}))
