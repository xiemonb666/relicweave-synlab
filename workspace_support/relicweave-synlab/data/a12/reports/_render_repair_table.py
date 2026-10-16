"""Render the 8 old->new mappings as markdown table rows for the repair docs."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
report = json.loads((ROOT / "data/a12/reports/feature_leak_repair.json").read_text(encoding="utf-8"))
for entry in report["entries"]:
    fidelity = entry.get("fidelity") or {}
    repointed = [r["referrer"] for r in (entry.get("ancestry_repointed") or [])]
    print(f"| `{entry['asset_id']}` | `{entry['run_id']}` | {entry['lineage_id']} | "
          f"`{entry.get('new_asset_id')}` | {fidelity.get('n_arrays_new')} | "
          f"{fidelity.get('array_hashes_equal')} | {','.join(repointed)} |")
print()
print("before:", report["before"]["offending_count"], report["before"]["forbidden_entries"])
print("after:", report["after"]["forbidden_entries_total"], report["after"]["n_feature_assets"])
print("external_untouched:", report["external_releases_untouched"],
      len(report["external_release_manifests_before"]))
for run, ctl in report["negative_control_runs"].items():
    print("negctl", run, ctl["status"], ctl["truth_isolation"], ctl["features_checked"])
