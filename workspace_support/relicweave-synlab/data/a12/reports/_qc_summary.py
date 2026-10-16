"""Summarise every data_quality_<store>.json report into a compact table (read-only)."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REPORTS = REPO / "data" / "a12" / "reports"


def main() -> None:
    paths = sorted(REPORTS.glob("data_quality_*.json"))
    print(f"{len(paths)} report(s)\n")
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        target = report["target"]
        print("=" * 100)
        print(f"{target['path']}  [{target['kind']}]  verdict={report['verdict']} "
              f"trainable={report['trainable']}  report={path.name}")
        counts = report.get("counts") or {}
        print(f"  counts: total={counts.get('total')} PASS={counts.get('QA_PASS')} "
              f"PENDING={counts.get('QA_PENDING')} FAIL={counts.get('QA_FAIL')} "
              f"relation_rows={report.get('relation_rows')}")
        first = report.get("first_cause")
        if first:
            print(f"  first: [{first['status']}] {first['check_id']} -- {first['detail'][:220]}")
        for check in report["checks"]:
            if check["status"] in ("PASS", "NOT_APPLICABLE") and "geometry" not in check["id"] \
                    and "semantics" not in check["id"] and "training" not in check["id"]:
                continue
            denom = "" if check["denominator"] is None else f" ({check['hits']}/{check['denominator']})"
            print(f"    {check['status']:<15} {check['id']}{denom}")
            print(f"        {check['detail'][:260]}")
        problems = (report.get("unreadable") or [])
        if problems:
            print(f"  unreadable: {len(problems)}")
            for item in problems[:6]:
                print(f"    - {item[:180]}")
        extra = report.get("package")
        if extra:
            print(f"  package: {json.dumps(extra, ensure_ascii=False)[:400]}")


if __name__ == "__main__":
    main()
