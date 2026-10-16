"""Collect every number the final documents need, from the real artifacts (read-only)."""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "data" / "a12_exports" / "closed_loop" / "closed_loop_report.json"
A12 = ROOT / "data" / "a12" / "reports"


def load(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


print("### ledger steps")
ledger = load(LEDGER)
print("run_id:", ledger["run_id"], "ok:", ledger["ok"], "mothers:", ledger["mothers"])
for entry in ledger["steps"]:
    name = entry["step"]
    print(f"\n-- {name}: status={entry['status']} seconds={entry.get('seconds')}")
    if name == "release_freeze":
        print("   release_id:", entry.get("release_id"), "profile:", entry.get("release_profile"))
        print("   assets:", entry.get("assets"), "scope_pending:", entry.get("scope_pending"))
        print("   gate_overrides:", entry.get("gate_overrides"),
              "refused:", entry.get("refused_gate_overrides"))
        print("   gates_required:", {g: entry["gates"].get(g) for g in entry.get("required_gates", [])})
        print("   manifest_hash:", entry.get("manifest_hash"))
        print("   assets_by_role:", json.dumps(entry.get("assets_by_role"), sort_keys=True))
    if name == "export_training_package":
        print("   files_total:", entry.get("files_total"), "bytes_total:", entry.get("bytes_total"))
        print("   manifest_hash:", entry.get("manifest_hash"))
        print("   counts:", json.dumps(entry.get("counts"), sort_keys=True))
        print("   views:", json.dumps(entry.get("views"), sort_keys=True))
        print("   separation:", json.dumps(entry.get("separation"), sort_keys=True))
        print("   labels:", json.dumps([{k: v for k, v in lab.items() if k != 'assets'}
                                        for lab in (entry.get("labels") or [])], sort_keys=True))
        print("   token_cache:", json.dumps(entry.get("token_cache"), sort_keys=True))
        print("   legacy_export:", json.dumps(entry.get("legacy_export"), sort_keys=True))
        print("   reference_closure:", json.dumps(entry.get("reference_closure"), sort_keys=True))
    if name == "loader_probe":
        print("   ok:", entry.get("ok"), "counts:", json.dumps(entry.get("counts"), sort_keys=True))
        print("   batch:", json.dumps(entry.get("batch"), sort_keys=True))
        print("   feature_shapes:", json.dumps(entry.get("feature_shapes"), sort_keys=True))
        print("   real_denominator:", json.dumps(entry.get("real_denominator"), sort_keys=True))
        print("   negative_audit:", json.dumps(entry.get("negative_audit"), sort_keys=True))
        print("   degenerate:", json.dumps(entry.get("degenerate"), sort_keys=True))
        print("   blocking_attempt:", entry.get("blocking_attempt"), "error:", entry.get("error"))
    if name == "build_pool":
        print("   pool_status:", entry.get("pool_status"), "candidates:", entry.get("candidates"),
              "queries:", entry.get("queries"), "r2:", entry.get("r2_edges"),
              "unknown:", entry.get("unknown_edges"), "mothers:", entry.get("mothers"))
    if name == "audit":
        print("   ok:", entry.get("ok"), "problems:", json.dumps(entry.get("problems"))[:300])
        print("   qa_failed:", entry.get("qa_failed"))
        print("   coordinate_contract:", json.dumps(entry.get("coordinate_contract"))[:200])

print("\n### data/a12/reports/loader_probe.json")
probe = load(A12 / "loader_probe.json")
print("ok:", probe.get("ok"), "status:", probe.get("status"), "files_ok:", probe.get("files_ok"))
print("counts:", json.dumps(probe.get("counts"), sort_keys=True))
print("real_denominator:", json.dumps(probe.get("real_denominator"), sort_keys=True))
print("relation_pool:", json.dumps(probe.get("relation_pool"), sort_keys=True))
print("feature_shapes:", json.dumps(probe.get("feature_shapes"), sort_keys=True))

print("\n### acceptance snapshots")
before = load(A12 / "acceptance_summary.before.json")
after = load(A12 / "acceptance_summary.json")
print("before counts:", json.dumps(before["counts"], sort_keys=True),
      "generated_at:", before["generated_at"])
print("after  counts:", json.dumps(after["counts"], sort_keys=True),
      "generated_at:", after["generated_at"], "hash:", after["summary_hash"])
print("before fails:", [k for k, v in before["items"].items() if v["status"] == "FAIL"])
print("after  fails:", [k for k, v in after["items"].items() if v["status"] == "FAIL"])
print("A01 before entries:",
      len(before["items"]["A01"]["metrics"]["forbidden_fields_in_committed_features"]),
      sorted(set(before["items"]["A01"]["metrics"]["forbidden_fields_in_committed_features"])))
print("A01 after  entries:",
      len(after["items"]["A01"]["metrics"]["forbidden_fields_in_committed_features"]),
      sorted(set(after["items"]["A01"]["metrics"]["forbidden_fields_in_committed_features"])))
moved = {k: (before["items"][k]["status"], after["items"][k]["status"])
         for k in sorted(after["items"]) if before["items"][k]["status"] != after["items"][k]["status"]}
print("status migrations:", json.dumps(moved, sort_keys=True))

print("\n### status matrix")
with (ROOT / "docs" / "a12" / "status_matrix.csv").open("r", encoding="utf-8", newline="") as fh:
    rows = list(csv.DictReader(fh))
print("rows:", len(rows), "areas:", dict(Counter(r["area"] for r in rows)))
print("status histogram:", dict(Counter(r["status"] for r in rows).most_common()))
print("acceptance rows:", dict(Counter(r["status"] for r in rows if r["area"] == "acceptance")))

print("\n### leakage report")
leak = load(A12 / "leakage_negative_control.json")
print("canonical: ok:", leak["ok"], "status:", leak["status"], "run_id:", leak.get("run_id"))
print("truth_isolation:", leak["checks"]["truth_isolation"], "problems:", leak["problems"])
print("scope:", json.dumps(leak["scope"], sort_keys=True))
print("store_wide ok:", leak["store_wide"]["ok"],
      "truth_isolation:", leak["store_wide"]["checks"]["truth_isolation"])
print("store_wide problems:", leak["store_wide"]["problems"])
print("clean_run_scoped:", json.dumps(leak["clean_run_scoped"], sort_keys=True))
print("census:", json.dumps({k: v for k, v in leak["degrade_role_census"].items() if k != "rows"},
                            sort_keys=True))
print("residual:", json.dumps(leak["residual"], sort_keys=True)[:900])

print("\n### repair report")
rep = load(A12 / "degrade_role_repair.json")
print("applied:", rep["applied"], "candidates:", rep["candidate_count"],
      "repaired:", len(rep["repaired"]), "refused:", len(rep["refused"]))
print("before:", json.dumps(rep["before_role_counts"], sort_keys=True))
print("after :", json.dumps(rep["after_role_counts"], sort_keys=True))
print("faithful:", all(r["fidelity"]["array_hashes_equal"] for r in rep["repaired"]))
