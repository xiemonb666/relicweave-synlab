"""Which physical_component assets carry no face__origin_kind array, and what do they carry?"""
import json
import sqlite3
from pathlib import Path

import numpy as np

root = Path("data/a12")
con = sqlite3.connect(f"file:{(root / 'metadata.sqlite').as_posix()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
missing = 0
shown = 0
for row in con.execute("select asset_id, role, files_json, meta_json from assets "
                       "where role='physical_component'"):
    files = json.loads(row["files_json"] or "{}")
    if "arrays" not in files:
        print(row["asset_id"], "NO ARRAYS")
        continue
    with np.load(root / files["arrays"], allow_pickle=False) as data:
        keys = list(data.files)
        has = [k for k in keys if "origin_kind" in k]
        if not has:
            missing += 1
            if shown < 3:
                meta = json.loads(row["meta_json"] or "{}")
                print(row["asset_id"], "keys:", keys[:12], "meta:", json.dumps(meta)[:200])
                shown += 1
        else:
            with np.load(root / files["arrays"], allow_pickle=False) as data2:
                arr = np.asarray(data2[has[0]])
            unique, counts = np.unique(arr, return_counts=True)
            print(row["asset_id"], has[0], dict(zip(unique.tolist(), counts.tolist())))
print("components without any origin_kind array:", missing)
