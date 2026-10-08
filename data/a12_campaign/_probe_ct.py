import json, sys
sys.path.insert(0, ".")
from synlab.storage.store import AssetStore
s = AssetStore("data/a12_campaign/store")
recs = list(s.list_assets(limit=100000))
ct = [r for r in recs if r.role == "clean_truth" and r.lineage_id == "LIN0000_V10_M11_PAT15"]
print("clean_truth assets:", [(r.asset_id, list(r.files)) for r in ct])
if ct:
    a = s.load_arrays(ct[0].asset_id)
    print("array keys:", list(a)[:20])
    for k in list(a)[:3]:
        print(k, getattr(a[k], "dtype", None), getattr(a[k], "shape", None))
    b = s.load_bytes(ct[0].asset_id, "payload")
    d = json.loads(b.decode("utf-8"))
    print("payload keys:", list(d)[:20])
    rel = d.get("relations")
    print("relations type:", type(rel).__name__, "n=", len(rel) if rel else 0)
    if isinstance(rel, dict):
        k0 = list(rel)[:2]
        for k in k0: print("  ", k, json.dumps(rel[k])[:300])
