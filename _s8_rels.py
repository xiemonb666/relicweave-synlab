import pyarrow.parquet as pq
from pathlib import Path
for p in ("data/a12_exports/trainable/next_experiment/training_package/research/relations.parquet",
          "data/a12_exports/negfix/next_experiment/training_package/research/relations.parquet"):
    t = pq.read_table(p)
    print(p.split("/")[-3], "rows", t.num_rows, "cols", t.column_names)
