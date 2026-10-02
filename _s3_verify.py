import sys, json, collections, shutil
sys.path.insert(0, ".")
from pathlib import Path
import pyarrow.parquet as pq
from synlab.storage.store import AssetStore
from synlab.storage.export import export_training_package
store = r"data\a12_exports\closed_loop\store"
rel = "rel_852ab2a1e4c3_1790909619"
out = Path(r"data\a12_smallfix\s3_proof\training_package")
if out.exists(): shutil.rmtree(out)
man = export_training_package(AssetStore(store), rel, out, formats=("parquet", "npz"), include_truth=True)
c = man["counts"]
print("AFTER export counts:")
for k in ("relations","unordered_relation_pairs","relation_rows_reverse_role","relation_pairs_direction_complete","r2_relations","queries"):
    print(f"   {k:34s} = {c.get(k)}")
rows = pq.read_table(out/"research"/"relations.parquet").to_pylist()
print("parquet rows:", len(rows))
byq = collections.Counter(r["query"] for r in rows)
print("queries with rows:", len(byq))
pos = collections.Counter(r["query"] for r in rows if r["kind"]=="R2")
neg = collections.Counter(r["query"] for r in rows if r["kind"] in ("R0","R1") and r.get("eligible_as_negative"))
eff = sum(1 for q in byq if pos.get(q,0)>0 and neg.get(q,0)>0)
print("effective_queries (pos>0 & neg>0, table level):", eff)
print("queries with a positive:", len(pos), "| with a legal negative:", len(neg))
print("directions:", collections.Counter(r["direction"] for r in rows))
# direction completeness
pk = collections.Counter(r["pair_key"] for r in rows)
print("pair_keys with exactly 2 rows:", sum(1 for v in pk.values() if v==2), "of", len(pk))
