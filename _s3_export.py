import sys, json, time
sys.path.insert(0, ".")
from pathlib import Path
from synlab.storage.store import AssetStore
from synlab.storage.export import export_training_package
import shutil
store = r"data\a12_trainable\store"
rel = "rel_nexp_1790919836"
out = Path(r"data\a12_smallfix\s3_before_after\training_package")
if out.exists(): shutil.rmtree(out)
t0 = time.time()
man = export_training_package(AssetStore(store), rel, out, formats=("parquet",), include_truth=True)
print("export seconds %.1f" % (time.time()-t0))
c = man["counts"]
for k in ("relations","unordered_relation_pairs","relation_rows_reverse_role","relation_pairs_direction_complete","r2_relations","queries","fragments_with_observation"):
    print(f"   {k:34s} = {c.get(k)}")
