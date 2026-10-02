import sys, glob, json
sys.path.insert(0,'.')
import pandas as pd
paths = [
 "data/a12_exports/closed_loop/training_package_v2/research/relations.parquet",
 "data/a12_exports/negfix/next_experiment/training_package/research/relations.parquet",
 "data/a12_exports/trainable/next_experiment/training_package/research/relations.parquet",
 "data/a12_exports/a12_extras/training_package/research/relations.parquet",
 "data/a12_degrade/exports/rel_degrade_diversity_1790919754/training_package/research/relations.parquet",
 "data/a12_smallfix/s3_proof/training_package/research/relations.parquet",
]
for p in paths:
    try:
        df = pd.read_parquet(p)
        kinds = df["kind"].value_counts().to_dict() if "kind" in df.columns else None
        print(p)
        print("   rows", len(df), "cols", list(df.columns))
        print("   kinds", kinds)
    except Exception as e:
        print(p, "ERR", type(e).__name__, e)
