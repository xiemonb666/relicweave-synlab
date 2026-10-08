"""Probe 3: clean_truth arrays + cutter basis, and the camera registry."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data" / "a12"

conn = sqlite3.connect(f"file:{(STORE / 'metadata.sqlite').as_posix()}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

row = conn.execute("SELECT * FROM assets WHERE role='clean_truth' AND lineage_id LIKE 'LIN00%' "
                   "ORDER BY created_at LIMIT 1").fetchone()
files = json.loads(row["files_json"])
arr_path = STORE / files["arrays"]
print("clean_truth arrays:", arr_path)
with np.load(arr_path, allow_pickle=False) as d:
    for k in d.files:
        print(f"   {k:34s} {str(d[k].shape):16s} {d[k].dtype}")

meta = json.loads(row["meta_json"])
print("\nclean_truth meta keys:", sorted(meta.keys()))
for k in ("interfaces", "event_tree", "patch_evidence"):
    v = meta.get(k)
    print(f"\n-- {k}: {json.dumps(v, ensure_ascii=False, default=str)[:1200]}")

print("\n=== camera registry ===")
prof = conn.execute("SELECT meta_json, lineage_id, asset_id FROM assets WHERE "
                    "role='material_profile' LIMIT 1").fetchone()
conn.close()

import sys
sys.path.insert(0, str(ROOT))
from synlab.cameras.api import camera_profiles  # noqa: E402

for p in camera_profiles():
    print(json.dumps({k: v for k, v in p.__dict__.items()
                      if k in ("profile_id", "tier", "working_distance_mm", "focal_px_1024",
                               "image_long_edge_px", "f_number", "focus_distance_mm",
                               "fov_mm", "depth_of_field_mm", "u_position_mm")},
                     default=str))
