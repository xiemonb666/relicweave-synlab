import time, numpy as np
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
import pyarrow.parquet as pq
t=pq.read_table(r"data\a12_exports\trainable\next_experiment\training_package\research\labels\correspondence.parquet")
pairs = sorted({(r["fragment_a"], r["fragment_b"]) for r in t.to_pylist()})
print("pairs with correspondence:", len(pairs))
for p in pairs: print("   ", p)
# how many obs assets total and their size
recs = st.list_assets(role="obs_result", limit=500)
print("obs_result assets:", len(recs))
tot = sum((st.root / r.files["arrays"]).stat().st_size for r in recs)
print("total obs npz bytes: %.1f GB" % (tot/1e9))
