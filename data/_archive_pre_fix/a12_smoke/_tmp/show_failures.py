"""Print the recorded failures (code/stage/message/traceback) from a survey shard."""

import sys
from pathlib import Path
import json

for name in sys.argv[1:]:
    doc = json.loads(Path(name).read_text(encoding="utf-8"))
    for row in doc.get("lineages", []):
        if row["ok"]:
            continue
        print(f"=== {row['vessel_id']} {row['lineage_id']} "
              f"code={row['error_code']} stage={row['error_stage']} {row['seconds']}s")
        print(f"    message: {row['error_message']}")
        tb = row.get("traceback")
        if tb:
            print("    traceback:")
            for line in str(tb).splitlines():
                print("      " + line)
        print()
