"""Read-only: role/QA/run-attribution census of the fresh closed-loop store + its ledger steps."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "data" / "a12_exports" / "cl_fresh" / "store"
con = sqlite3.connect(STORE / "metadata.sqlite")
con.row_factory = sqlite3.Row
rows = con.execute("SELECT role, qa_status, lineage_id, meta_json FROM assets").fetchall()
print(f"{'role':<20}{'qa_status':<12}{'run_id':<26}{'run_id_source':<48}lineage")
for row in rows:
    meta = json.loads(row["meta_json"] or "{}")
    print(f"{row['role']:<20}{row['qa_status']:<12}{str(meta.get('run_id')):<26}"
          f"{str(meta.get('run_id_source')):<48}{row['lineage_id']}")
print("\nqa_status counts:", dict(Counter(r["qa_status"] for r in rows)))

ledger_path = ROOT / "data" / "a12_exports" / "cl_fresh" / "ledger.json"
ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
step = {s["step"]: s for s in ledger["steps"]}["audit"]
print("\naudit step: status", step["status"], "ok", step["ok"])
print("problems:", json.dumps(step["problems"], ensure_ascii=False)[:600])
print("qa_failed:", step["qa_failed"])
print("promotion promoted:", [p["role"] for p in step["promotion"]["promoted"]])
print("promotion failed:", step["promotion"]["failed"])
print("run_id_tagged:", json.dumps(step["run_id_tagged"], ensure_ascii=False)[:900])
