"""Probe 2: dump one full meta_json per interesting role, to locate every diversity signal."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data" / "a12"
ROLES = ("cutter_mesh", "fragment_mesh", "mother_mesh", "obs_result", "feature_bundle",
         "clean_truth", "physical_component", "pattern_recipe", "material_profile",
         "degrade_measurement", "obs_view", "obs_fused_geometry", "label_bundle")

conn = sqlite3.connect(f"file:{(STORE / 'metadata.sqlite').as_posix()}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
for role in ROLES:
    row = conn.execute("SELECT * FROM assets WHERE role=? ORDER BY created_at LIMIT 1",
                       (role,)).fetchone()
    if row is None:
        print(f"### {role}: (none)")
        continue
    meta = json.loads(row["meta_json"] or "{}")
    qa = json.loads(row["qa_json"] or "{}")
    print(f"### {role}  lineage={row['lineage_id']}  files={row['files_json']}")
    print("  meta:", json.dumps(meta, ensure_ascii=False, default=str)[:3000])
    print("  qa  :", json.dumps(qa, ensure_ascii=False, default=str)[:1500])
    print()
conn.close()
