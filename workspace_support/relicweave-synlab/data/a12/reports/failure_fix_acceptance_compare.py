"""Before/after acceptance comparison for the three failure classes (recomputable).

Real denominator, no fabrication.  The *before* rows come from
``data/a12/reports/next_experiment_batches.json`` (written by ``tools/batch_generate.py``, never
modified here); the *after* rows come from

* the same tool run by the other writer after the fixes landed (``run_e031b5651fb7f7ff``), and
* an isolated post-fix run of this work:
  ``--root data/a12/reports/failure_fix_store --ledger data/a12/reports/failure_fix_batches.json
  --batch 6 --only 1,2,3,4,9,10`` (the four failing lineages plus two pending controls).

Runs are split by ``run_id`` because one ``run_id`` = one batch invocation = one loaded code
state (``failure_fix_runs.py`` prints the grouping).  ``run_id`` itself is derived from the git
dirty-diff hash, so it *cannot* tell which single edit a process loaded; the split below uses the
measured ordering of the edits (see ``docs/a12/failure_mode_fixes.md`` section 4).

Usage::

    python data/a12/reports/failure_fix_acceptance_compare.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BEFORE = ROOT / "data" / "a12" / "reports" / "next_experiment_batches.json"
AFTER = ROOT / "data" / "a12" / "reports" / "failure_fix_batches.json"
PLAN = ROOT / "data" / "a12" / "reports" / "failure_class1_param_validation.json"
OUT = ROOT / "data" / "a12" / "reports" / "failure_mode_before_after.json"

#: runs of the *old* plan (before the "picked vessel sequence" consistency fix); they carry the
#: four cross-vessel MOTHER_INVALID rows of failure class 1
PRE_FIX_PLAN_RUNS = ("run_e69efa4cbcab8b94", "run_c8e819f2f7599078")
#: runs of the current plan *before* the three defect fixes of this work
BEFORE_RUNS = ("run_1f0eb1ef0c60a503", "run_bdc7b25bd6c6f835", "run_92f4b8e5e36c5687")

CLASS_1 = "class1_cross_vessel_params (MOTHER_INVALID, extra_forbidden)"
CLASS_2 = "class2_pattern_stage (UNEXPECTED)"
CLASS_3 = "class3_interface_roi_not_applicable (NA_NOT_APPLICABLE)"
OTHER = "other"
NOTES = {
    "ErrorCode.MOTHER_INVALID": CLASS_1,
    "UNEXPECTED": CLASS_2,
    "ErrorCode.NA_NOT_APPLICABLE": CLASS_3,
}


def classify(row: dict) -> str:
    if row.get("ok"):
        return "accepted"
    return NOTES.get(str(row.get("error")), OTHER)


def rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for row in data.get("batches", []):
        item = dict(row)
        item["at_hhmmss"] = datetime.fromtimestamp(row.get("at", 0)).strftime("%H:%M:%S")
        out.append(item)
    return out


def summarize(items: list[dict], *, label: str) -> dict:
    counts = Counter(classify(row) for row in items)
    attempted = len(items)
    accepted = counts.get("accepted", 0)
    return {
        "label": label,
        "attempted": attempted,
        "accepted": accepted,
        "acceptance_rate": round(accepted / attempted, 4) if attempted else None,
        "per_class": {key: counts.get(key, 0) for key in
                      ("accepted", CLASS_1, CLASS_2, CLASS_3, OTHER)},
        "distinct_lineages": sorted({row["lineage_id"] for row in items}),
        "distinct_accepted": sorted({row["lineage_id"] for row in items if row.get("ok")}),
        "distinct_failed_per_class": {
            key: sorted({row["lineage_id"] for row in items if classify(row) == key})
            for key in (CLASS_1, CLASS_2, CLASS_3, OTHER)},
        "runs": sorted({str(row.get("run_id")) for row in items}),
        "outcomes": [{"at": row["at_hhmmss"], "run_id": row.get("run_id"),
                      "lineage_id": row["lineage_id"], "vessel_id": row.get("vessel_id"),
                      "material_id": row.get("material_id"),
                      "pattern_id": row.get("pattern_id"), "class": classify(row),
                      "error": row.get("error"), "seconds": row.get("seconds"),
                      "error_message": (row.get("error_message") or "")[:160]}
                     for row in items],
    }


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    current = {row["lineage_id"]: (row["vessel_id"], row["material_id"], row["pattern_id"])
               for row in plan["rows"]}
    before_all = rows(BEFORE)
    after_isolated = rows(AFTER)

    pre_fix_plan = [r for r in before_all if str(r.get("run_id")) in PRE_FIX_PLAN_RUNS]
    before = [r for r in before_all if str(r.get("run_id")) in BEFORE_RUNS]
    teammate_after = [r for r in before_all
                      if str(r.get("run_id")) not in PRE_FIX_PLAN_RUNS
                      and str(r.get("run_id")) not in BEFORE_RUNS]

    def is_current(row: dict) -> bool:
        key = current.get(row["lineage_id"])
        return key is not None and key == (row.get("vessel_id"), row.get("material_id"),
                                           row.get("pattern_id"))

    report = {
        "before_ledger": str(BEFORE.relative_to(ROOT)).replace("\\", "/"),
        "after_ledger": str(AFTER.relative_to(ROOT)).replace("\\", "/"),
        "plan_reference": str(PLAN.relative_to(ROOT)).replace("\\", "/"),
        "before_all_attempts": summarize(before_all, label="every ledger row at snapshot time"),
        "before_failure_class_1_old_plan": summarize(
            pre_fix_plan, label="old plan (cross-vessel mapping), pre-fix code"),
        "before_current_plan_before_fixes": summarize(
            before, label="current plan, code before the three defect fixes"),
        "after_current_plan_other_writer_run": summarize(
            teammate_after, label="current plan, other writer's post-fix run"),
        "after_isolated_post_fix_run": summarize(
            after_isolated, label="current plan, isolated post-fix run of this work"),
        "plan_stability_check": {
            "ledger_rows_matching_the_current_plan": sum(1 for r in before_all if is_current(r)),
            "ledger_rows_with_a_different_vessel_mapping": sum(
                1 for r in before_all if not is_current(r)),
            "note": ("the pre-fix plan rows are the ones whose (vessel, material, pattern) triple "
                     "the current planner does not reproduce; the current-plan rows match 1:1"),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for name, block in report.items():
        if not isinstance(block, dict) or "attempted" not in block:
            continue
        print(f"\n== {name}: {block['label']}")
        print(f"   attempted={block['attempted']} accepted={block['accepted']} "
              f"rate={block['acceptance_rate']} runs={block['runs']}")
        for key, value in block["per_class"].items():
            lineages = block["distinct_failed_per_class"].get(key) if key != "accepted" else None
            extra = f"  distinct={lineages}" if lineages else ""
            print(f"     {value:3d}  {key}{extra}")
    print("\n== plan stability check")
    for key, value in report["plan_stability_check"].items():
        print(f"   {key}: {value}")
    print(f"\nwritten {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
