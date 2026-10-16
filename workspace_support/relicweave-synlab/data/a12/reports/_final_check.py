"""Final deliverable check: every repair artefact parses and carries the expected fields."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "data/a12/reports"

for name in ("feature_leak_assets_before.json", "feature_leak_repair.json",
             "release_freeze_after_feature_leak_repair.json", "leakage_negative_control.json",
             "acceptance_summary.json", "acceptance_summary.before_feature_leak_repair.json",
             "audit_run_2fad0ac4d3b67098.json", "audit_run_404bbe3c80f2c04e.json"):
    path = REPORTS / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    print(f"{name}  {os.path.getsize(path)} B  schema={payload.get('schema', '-')}  "
          f"keys={len(payload)}")

before = json.loads((REPORTS / "feature_leak_assets_before.json").read_text(encoding="utf-8"))
print("before: offending", before["offending_count"], "entries", before["forbidden_entries"],
      "assets listed", len(before["assets"]))
repair = json.loads((REPORTS / "feature_leak_repair.json").read_text(encoding="utf-8"))
print("repair: repaired", len(repair["repaired"]), "refused", len(repair["refused"]),
      "mapping", len(repair["entries"]),
      "external_untouched", repair["external_releases_untouched"])
print("after survey:", repair["after"]["n_feature_assets"], "features; forbidden",
      repair["after"]["forbidden_entries_total"])
print("negctl store:", repair["after"]["negative_control_store"])
print("negctl runs:", {k: (v["status"], v["truth_isolation"]) for k, v in
                       repair["negative_control_runs"].items()})
freeze = json.loads((REPORTS / "release_freeze_after_feature_leak_repair.json")
                    .read_text(encoding="utf-8"))
for entry in freeze["runs"]:
    print("freeze", entry["run_id"], "frozen", entry["frozen"], "scope_kind", entry["scope_kind"],
          "required_pending", entry["scope_pending"],
          "excluded", len(entry.get("excluded_assets") or []),
          "closure_full_ok", entry["closure_full"]["ok"])
summary = json.loads((REPORTS / "acceptance_summary.json").read_text(encoding="utf-8"))
print("acceptance counts:", summary["counts"], "A01:",
      summary["items"]["A01"]["status"],
      len(summary["items"]["A01"]["metrics"]["forbidden_fields_in_committed_features"]))
