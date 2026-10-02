import sys, json
sys.path.insert(0,".")
from pathlib import Path
from synlab.storage.store import AssetStore
state=json.loads(Path("data/a12_exports/trainable/next_experiment/next_experiment_export_state.json").read_text(encoding="utf-8"))
ids=set((state.get("freeze") or {}).get("unverified_scope_ids") or [])
print("scope ids:", len(ids))
store=AssetStore(Path("data/a12_trainable/store"))
assets=store.list_assets(limit=500000)
fm=[a for a in assets if a.role=="fragment_mesh"]
print("fragment_mesh in store:", len(fm))
print("in scope:", sum(1 for a in fm if a.asset_id in ids))
print("first 3 ids:", [a.asset_id for a in fm[:3]])
a=fm[0]
arr=store.load_arrays(a.asset_id)
print("keys of first mesh:", sorted(arr.keys())[:12], "...n=",len(arr))
print("has origin_kind:", "face__origin_kind" in arr)
import numpy as np
if "face__origin_kind" in arr:
    print("hist:", np.bincount(np.asarray(arr["face__origin_kind"]).reshape(-1).astype(int)))
