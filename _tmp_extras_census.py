"""Scratch: census the new extras store before exporting."""
from __future__ import annotations

import collections
import sys

sys.stdout.reconfigure(encoding="utf-8")

from synlab.storage.store import AssetStore

s = AssetStore("data/a12_extras/store")
rows = s.list_assets(limit=2000)
print("assets:", len(rows))
print("roles:", dict(collections.Counter(r.role for r in rows)))
for r in rows:
    print(f"{r.role:<22} {r.asset_id} lin={r.lineage_id} "
          f"frag={r.meta.get('fragment_id')} keys={sorted(r.meta.keys())[:10]}")
print("runs:", [run for run in (s.get_run(x) for x in ("run_0c53c8b981927272",)) ])
