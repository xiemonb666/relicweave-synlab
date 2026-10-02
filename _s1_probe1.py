import json, sys
import pyarrow.parquet as pq
p = r"data\a12_exports\trainable\next_experiment\training_package\research\labels\correspondence.parquet"
t = pq.read_table(p)
print("ROWS", t.num_rows)
print("COLS", t.column_names)
d = t.to_pylist()
for r in d[:3]:
    print(json.dumps({k: (v if not isinstance(v,(bytes,)) else str(v)) for k,v in r.items()}, ensure_ascii=False)[:600])
