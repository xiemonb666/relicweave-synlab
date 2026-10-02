import sys, json, collections; sys.path.insert(0,'.')
from pathlib import Path
import pyarrow.parquet as pq
pkg = Path(r"data\a12_exports\trainable\next_experiment\training_package")
rel = pq.read_table(pkg/"research"/"relations.parquet").to_pylist()
q = pq.read_table(pkg/"deploy"/"queries.parquet").to_pylist()
print("relations rows:", len(rel))
pairs = [(r["query"], r["candidate"]) for r in rel]
rev = set((b, a) for a, b in pairs)
both = sum(1 for p in pairs if p in rev)
print("rows whose reverse also exists:", both, "/", len(pairs))
directed = len(set(pairs)); undirected = len({tuple(sorted(p)) for p in pairs})
print("distinct directed pairs:", directed, "| distinct unordered pairs:", undirected)
print("=> missing direction rows:", undirected - directed if directed == undirected else "asymmetric")
queries = [r["fragment_id"] for r in q]
print("roster fragments:", len(queries))
in_rel = {r["query"] for r in rel} | {r["candidate"] for r in rel}
missing = [f for f in queries if f not in in_rel]
print("roster fragments NOT in relations table:", len(missing), missing[:8])
kinds = collections.Counter(r["kind"] for r in rel)
print("kinds:", dict(kinds))
loss = sum(1 for r in rel if r.get("loss_mask")); elig = sum(1 for r in rel if r.get("eligible_as_negative"))
print("loss_mask true:", loss, "| eligible_as_negative true:", elig, "| valid true:", sum(1 for r in rel if r.get("valid")))
