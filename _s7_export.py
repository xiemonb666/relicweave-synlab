import sys, json, time
sys.path.insert(0, ".")
from pathlib import Path
from synlab.storage.store import AssetStore
from synlab.storage.export import export_training_package
store = r"data\a12_exports\closed_loop\store"
st = AssetStore(store)
rel = "rel_852ab2a1e4c3_1790909619"
out = Path(r"data\a12_smallfix\s7_proof\training_package")
t0 = time.time()
man = export_training_package(st, rel, out, formats=("parquet", "npz"), include_truth=True)
print("export seconds %.1f" % (time.time()-t0))
idx = json.loads((out/"deploy"/"obs"/"index.json").read_text(encoding="utf-8"))
qr = idx.get("quality_research") or {}
print("quality_research present:", bool(qr))
print("  channels:", qr.get("channels"))
print("  estimator_version:", qr.get("estimator_version"))
print("  fragments_with_quality:", qr.get("fragments_with_quality"), "/", qr.get("n_fragments_reported"))
rows = qr.get("rows") or {}
for fid, row in list(rows.items())[:2]:
    print(f"  {fid}: n_channels={row['n_channels']} first3={[round(v,4) for v in row['values'][:3]]}")
