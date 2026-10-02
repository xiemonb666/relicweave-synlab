import json
import pyarrow.parquet as pq
p = r"data\a12_exports\trainable\next_experiment\training_package\deploy\queries.parquet"
t = pq.read_table(p)
print("ROWS", t.num_rows, "COLS", t.column_names)
d = t.to_pylist()
print(json.dumps(d[0], ensure_ascii=False)[:900])
