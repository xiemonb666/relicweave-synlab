"""Scratch: which payload keys does each candidate target role actually carry?"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from synlab.storage.store import AssetStore

s = AssetStore("data/a12_extras/store")
for r in s.list_assets(limit=2000):
    if r.role in ("physical_component", "fragment_mesh", "obs_result"):
        arrays = s.load_arrays(r.asset_id)
        print(r.role, r.asset_id, "files:", sorted(r.files))
        print("   arrays:", sorted(arrays)[:14], "... n=", len(arrays))
