"""Compare the before/after run_id coverage measurements of §14.1 (read-only, no generation).

Usage::

    & .venv\\Scripts\\python.exe data\\a12\\reports\\runid_coverage_compare.py

Reads ``data/a12_exports/runid_fix/{before,after}.json`` (written by
``runid_coverage_probe.py``), prints the per-role ``meta.run_id`` coverage delta and the gate
verdict transitions, and writes ``data/a12_exports/runid_fix/runid_fix_comparison.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

#: ``<repo>/data/a12/reports/`` -> find the repository root by its own markers.
def _repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "synlab").is_dir():
            return candidate
    raise SystemExit(f"repository root not found above {start}")


ROOT = _repo_root(Path(__file__).resolve().parent)
FIX = ROOT / "data" / "a12_exports" / "runid_fix"

#: The five asset classes named in the defect report (plus the two the same commit path carries).
TARGET_ROLES = ("clean_truth", "obs_result", "physical_truth", "visible_labels", "pattern_channels")


def load(tag: str) -> dict:
    return json.loads((FIX / f"{tag}.json").read_text(encoding="utf-8"))


def main() -> int:
    before, after = load("before"), load("after")
    report: dict = {
        "schema": "synlab.runid_fix_evidence.v1",
        "before": {"run_id": before["run_id"], "store_root": before["store_root"],
                   "code_hashes": before["code_hashes_before"],
                   "generation": before["generation"]},
        "after": {"run_id": after["run_id"], "store_root": after["store_root"],
                  "code_hashes": after["code_hashes_before"],
                  "generation": after["generation"]},
        "run_id_coverage": {},
        "gates": {},
    }
    print(f"before run {before['run_id']} (accepted {before['generation']['accepted']}/"
          f"{before['generation']['attempted']}), after run {after['run_id']} "
          f"(accepted {after['generation']['accepted']}/{after['generation']['attempted']})")
    print(f"{'role':<22}{'before run_id':>14}{'after run_id':>13}  delta")
    for role in sorted(set(before["role_run_id_census"]) | set(after["role_run_id_census"])):
        was = before["role_run_id_census"].get(role, {})
        now = after["role_run_id_census"].get(role, {})
        report["run_id_coverage"][role] = {
            "before_with_run_id": was.get("with_run_id", 0),
            "before_total": was.get("total", 0),
            "after_with_run_id": now.get("with_run_id", 0),
            "after_total": now.get("total", 0),
            "target_class": role in TARGET_ROLES,
        }
        flag = " <-- defect 1" if role in TARGET_ROLES else ""
        print(f"{role:<22}{str(was.get('with_run_id', 0)) + '/' + str(was.get('total', 0)):>14}"
              f"{str(now.get('with_run_id', 0)) + '/' + str(now.get('total', 0)):>13}"
              f"  {now.get('with_run_id', 0) - was.get('with_run_id', 0):+d}{flag}")
    print("\nrequired gates (SANDBOX_CORE):")
    order = list(dict.fromkeys([*before["required_gates"], *after["required_gates"]]))
    transitions: dict[str, str] = {}
    for gate in order:
        was, now = before["gates"].get(gate), after["gates"].get(gate)
        transitions[gate] = f"{was} -> {now}"
        mark = "  <== CHANGED" if was != now else ""
        print(f"    {gate:<28} {was:<8} -> {now}{mark}")
    report["gates"] = transitions
    report["verdict"] = {
        "target_classes_with_run_id_after": sorted(
            role for role in TARGET_ROLES
            if report["run_id_coverage"][role]["after_with_run_id"]
            == report["run_id_coverage"][role]["after_total"]),
        "target_classes_with_run_id_before": sorted(
            role for role in TARGET_ROLES
            if report["run_id_coverage"][role]["before_with_run_id"]
            == report["run_id_coverage"][role]["before_total"]),
        "gates_flipped": sorted(g for g in order
                                if before["gates"].get(g) != after["gates"].get(g)),
    }
    out = FIX / "runid_fix_comparison.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding="utf-8")
    print("\nwrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
