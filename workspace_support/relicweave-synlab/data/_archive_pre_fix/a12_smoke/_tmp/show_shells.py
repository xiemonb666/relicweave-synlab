"""Print the multi-shell rows of the shell census (which vessels the per-shell cut touches)."""

import json
from pathlib import Path

rows = json.loads(Path("data/a12_smoke/_tmp/shell_census.json").read_text(encoding="utf-8"))
for row in rows:
    if row["shells"] > 1:
        print(f"{row['vessel_id']} {row['lineage_id']}: shells={row['shells']} "
              f"faces={row['shell_faces']} volumes={row['shell_volumes_mm3']} "
              f"pairwise_overlap={row['pairwise_overlap_mm3']}")
print()
for row in rows:
    if row["shells"] == 1:
        print(f"{row['vessel_id']}: 1 shell, {row['mother_faces']} faces, "
              f"{row['shell_volumes_mm3'][0]:.1f} mm^3")
