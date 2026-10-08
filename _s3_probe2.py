import sys, collections; sys.path.insert(0,'.')
from pathlib import Path
import pyarrow.parquet as pq
pkg = Path(r"data\a12_exports\trainable\next_experiment\training_package")
rel = pq.read_table(pkg/"research"/"relations.parquet").to_pylist()
q = pq.read_table(pkg/"deploy"/"queries.parquet").to_pylist()
print("queries cols:", sorted(q[0].keys()))
roster = [r.get("fragment") for r in q]
print("roster fragments:", len(roster), "nonempty:", sum(1 for x in roster if x))
in_rel = {r["query"] for r in rel} | {r["candidate"] for r in rel}
missing = [f for f in roster if f and f not in in_rel]
print("roster fragments NOT in relations:", len(missing), missing)
print("fragments in relations:", len(in_rel))
# per-query coverage: how many candidates does each query have
byq = collections.Counter(r["query"] for r in rel)
print("queries with relation rows:", len(byq))
print("pair count per query: min", min(byq.values()), "max", max(byq.values()), "median", sorted(byq.values())[len(byq)//2])
print("kinds:", dict(collections.Counter(r["kind"] for r in rel)))
print("loss_mask:", sum(1 for r in rel if r.get("loss_mask")), "valid:", sum(1 for r in rel if r.get("valid")), "eligible_as_negative:", sum(1 for r in rel if r.get("eligible_as_negative")))
# would reverse rows add supervision?
rev = set((r["candidate"], r["query"]) for r in rel) - set((r["query"], r["candidate"]) for r in rel)
print("reverse rows that would be new:", len(rev))
new_supervisable = [p for p in rev if p[0] in in_rel and p[1] in in_rel]
print("of which both endpoints are modelled:", len(new_supervisable))
