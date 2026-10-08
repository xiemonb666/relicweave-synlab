"""Turn survey JSON files into the vessel x result census table used by the report.

Reads one or more ``synthesis_functional_survey*.json`` documents (a "before" and an "after"
run), prints/emits:

* a markdown table ``vessel | lineage | status | error code | stage | frag/obs/r2 | seconds``,
* the honest denominator (surveyed vessels, passed, failed),
* a per-vessel before/after diff (which vessels changed state, and why they may have).

Usage::

    python data/a12/reports/synthesis_functional_census.py \
        --before data/a12/reports/synthesis_functional_survey.before_fix.json \
        --after data/a12/reports/synthesis_functional_survey.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TABLE_HEADER = ("| 器型 | 谱系 | 状态 | 错误码 | 阶段 | 真实 message | frag | obs | r2 | 耗时 s |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")


def load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rows_by_vessel(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in doc.get("lineages", []):
        out.setdefault(row["vessel_id"], row)
    return out


def cell(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).replace("|", "/").replace("\n", " ")
    return text if len(text) <= 120 else text[:117] + "..."


def table(rows: list[dict[str, Any]]) -> str:
    lines = [TABLE_HEADER]
    for row in rows:
        lines.append("| " + " | ".join([
            row["vessel_id"], row["lineage_id"],
            "OK" if row["ok"] else "FAIL",
            cell(row.get("error_code")), cell(row.get("error_stage")),
            cell(row.get("error_message")),
            cell(row.get("fragments")), cell(row.get("observations")), cell(row.get("r2_pairs")),
            cell(row.get("seconds")),
        ]) + " |")
    return "\n".join(lines)


def census(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if r["ok"]]
    failed = [r for r in rows if not r["ok"]]
    by_code: dict[str, int] = {}
    for row in failed:
        code = str(row.get("error_code"))
        by_code[code] = by_code.get(code, 0) + 1
    total_seconds = sum(float(r.get("seconds") or 0.0) for r in rows)
    return {
        "surveyed": len(rows),
        "ok": len(ok),
        "failed": len(failed),
        "failed_vessels": sorted(r["vessel_id"] for r in failed),
        "failed_by_code": dict(sorted(by_code.items())),
        "seconds_total": round(total_seconds, 1),
        "seconds_median": round(sorted(float(r.get("seconds") or 0.0)
                                       for r in rows)[len(rows) // 2], 1) if rows else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="synthesis_functional_census")
    parser.add_argument("--before", default=None)
    parser.add_argument("--after", default="data/a12/reports/synthesis_functional_survey.json")
    parser.add_argument("--out", default="data/a12/reports/synthesis_functional_census.json")
    parser.add_argument("--markdown", default="data/a12/reports/synthesis_functional_table.md")
    args = parser.parse_args()

    after_doc = load(args.after)
    after_rows = sorted(after_doc.get("lineages", []), key=lambda r: r["vessel_id"])
    report: dict[str, Any] = {
        "schema": "synlab.a12.synthesis_functional_census.v1",
        "after_source": args.after,
        "after_census": census(after_rows),
        "after_table_markdown": table(after_rows),
    }
    if args.before:
        before_doc = load(args.before)
        before_map = rows_by_vessel(before_doc)
        after_map = rows_by_vessel(after_doc)
        report["before_source"] = args.before
        report["before_census"] = census(sorted(before_map.values(),
                                                key=lambda r: r["vessel_id"]))
        changes = []
        for vessel in sorted(set(before_map) | set(after_map)):
            before = before_map.get(vessel)
            after = after_map.get(vessel)
            state_before = None if before is None else ("OK" if before["ok"] else "FAIL")
            state_after = None if after is None else ("OK" if after["ok"] else "FAIL")
            if state_before != state_after:
                changes.append({
                    "vessel_id": vessel,
                    "before": {"lineage_id": before["lineage_id"], "state": state_before,
                               "error_code": before.get("error_code"),
                               "error_message": before.get("error_message"),
                               "seconds": before.get("seconds")} if before else None,
                    "after": {"lineage_id": after["lineage_id"], "state": state_after,
                              "error_code": after.get("error_code"),
                              "error_message": after.get("error_message"),
                              "seconds": after.get("seconds")} if after else None,
                })
        report["vessel_state_changes"] = changes
        report["before_table_markdown"] = table(sorted(before_map.values(),
                                                       key=lambda r: r["vessel_id"]))
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                              encoding="utf-8")
    Path(args.markdown).write_text(
        "# 器型 x 结果（synthesis functional survey）\n\n"
        + json.dumps(report["after_census"], ensure_ascii=False, indent=2) + "\n\n"
        + report["after_table_markdown"] + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if not k.endswith("markdown")},
                     ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
