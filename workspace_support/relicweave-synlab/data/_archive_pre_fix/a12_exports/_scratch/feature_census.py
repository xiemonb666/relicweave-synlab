"""Exact forbidden-field census over the feature_bundle role of one store."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np  # noqa: F401  (import kept close to the project's own stack)

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from synlab.roles import FORBIDDEN_FEATURE_FIELDS  # noqa: E402

rel = sys.argv[1] if len(sys.argv) > 1 else "data/a12"
db = ROOT / rel / "metadata.sqlite"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
rows = con.execute("SELECT asset_id, role, schema, unit, frame, qa_status, meta_json, ancestry_json, "
                   "lineage_id, split, created_at FROM assets WHERE role='feature_bundle' "
                   "ORDER BY qa_status, asset_id").fetchall()
print(f"feature_bundle rows: {len(rows)}")
for row in rows:
    meta = json.loads(row["meta_json"] or "{}")
    forbidden = sorted(set(meta) & FORBIDDEN_FEATURE_FIELDS)
    print(json.dumps({
        "asset_id": row["asset_id"], "qa": row["qa_status"], "schema": row["schema"],
        "unit": row["unit"], "frame": row["frame"], "run_id": meta.get("run_id"),
        "has_feature_fields": bool(meta.get("feature_fields")),
        "n_feature_fields": len(meta.get("feature_fields") or []),
        "forbidden": forbidden, "lineage_id": row["lineage_id"], "split": row["split"],
        "ancestry": json.loads(row["ancestry_json"] or "[]"),
        "axis_key": bool("axis_id" in meta),
    }, sort_keys=True))
con.close()
