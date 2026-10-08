"""Scratch: how do store records identify their fragment?"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from synlab.storage.store import AssetStore

s = AssetStore("data/a12_extras/store")
for r in s.list_assets(limit=2000):
    if r.role in ("physical_component", "physical_result", "obs_result", "fragment_mesh"):
        keep = {k: r.meta.get(k) for k in
                ("fragment_id", "clean_fragment_id", "component_id", "clean_ref",
                 "observation_id", "is_representative", "status")}
        print(r.role, r.asset_id, keep)
        if r.role == "physical_result":
            comps = r.meta.get("components")
            if isinstance(comps, list) and comps:
                print("   components[0]:", {k: comps[0].get(k) for k in
                                            ("component_id", "clean_fragment_id", "status")})
