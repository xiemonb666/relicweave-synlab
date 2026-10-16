"""Diff the pre-fix and post-fix ``_carve_holes`` characterisation reports.

Both JSON files are produced by ``observe_carve_holes_bounds.py`` on the same constructed inputs.
This script separates the cases that must be *unchanged* (everything the historical code could
already answer: identical carved pixel sets, identical values) from the cases that must *change*
(the requests that used to raise ``IndexError`` and now carve their in-raster part).

Usage::

    .venv\\Scripts\\python.exe data\\a12\\reports\\observe_carve_holes_compare.py \
        --before data/a12/reports/observe_carve_holes_bounds_before.json \
        --after data/a12/reports/observe_carve_holes_bounds_after.json \
        --out data/a12/reports/observe_carve_holes_bounds_compare.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default="data/a12/reports/observe_carve_holes_bounds_before.json")
    ap.add_argument("--after", default="data/a12/reports/observe_carve_holes_bounds_after.json")
    ap.add_argument("--out", default="data/a12/reports/observe_carve_holes_bounds_compare.json")
    args = ap.parse_args()
    before = json.loads((ROOT / args.before).read_text(encoding="utf-8"))
    after = json.loads((ROOT / args.after).read_text(encoding="utf-8"))

    summary: dict = {"fixed": {}, "unchanged_ok": {}, "still_broken": {}, "semantics": {}}

    for name, case in before["cases"].items():
        now = after["cases"].get(name)
        if now is None:
            summary["still_broken"][name] = {"reason": "case missing in the after report"}
            continue
        if case["ok"] and now["ok"]:
            if "carved_yx" in case and "carved_yx" in now:
                same_pixels: bool | None = case["carved_yx"] == now["carved_yx"]
                entry = {"carved_pixels_before": case["carved_pixels"],
                         "carved_pixels_after": now["carved_pixels"],
                         "identical_carved_pixel_set": same_pixels}
            else:
                # e.g. the hole_count=0 identity case: compare the whole record
                entry = {"identical_record": case == now, "record": case}
            summary["unchanged_ok"][name] = entry
        elif not case["ok"] and now["ok"]:
            summary["fixed"][name] = {
                "error_before": case["error"],
                "carved_pixels_after": now["carved_pixels"],
                "clip_report_after": now["clip_report"],
            }
        elif not now["ok"]:
            summary["still_broken"][name] = {"error_before": case["error"],
                                            "error_after": now["error"]}

    # -- boundary sweep: which (size, radius) requests changed verdict
    for size, rows in before["sweep"].items():
        for row_before, row_after in zip(rows, after["sweep"][size]):
            assert row_before["radius_px"] == row_after["radius_px"]
            for axis in ("x", "y"):
                key = f"{size}_r{row_before['radius_px']}_{axis}"
                was = row_before[f"{axis}_first_oob_ok"]
                now = row_after[f"{axis}_first_oob_ok"]
                if was != now:
                    summary["fixed"][f"sweep_{key}"] = {
                        "centre": row_before[f"{axis}_first_oob"],
                        "ok_before": was, "ok_after": now,
                        "error_before": (row_before.get(f"{axis}_first_oob_error")
                                         or f"IndexError (raised; the x-axis record keeps the "
                                            f"message, the y-axis probe only stored the verdict)")}
                else:
                    summary["unchanged_ok"][f"sweep_{key}"] = {"ok": was}

    summary["monte_carlo"] = {"before": before["monte_carlo"], "after": after["monte_carlo"]}
    for key, entry in before["semantics"].items():
        now = after["semantics"].get(key)
        summary["semantics"][key] = {
            "before": entry, "after": now,
            "identical": entry == now,
        }
    summary["verdict"] = {
        "cases_unchanged_ok": len(summary["unchanged_ok"]),
        "cases_fixed": len(summary["fixed"]),
        "cases_still_broken": len(summary["still_broken"]),
        "semantics_entries_identical": all(v["identical"] for v in summary["semantics"].values()),
        "non_crashing_cases_pixel_identical": all(
            v["identical_carved_pixel_set"] for v in summary["unchanged_ok"].values()
            if "identical_carved_pixel_set" in v),
        "non_crashing_cases_record_identical": all(
            v["identical_record"] for v in summary["unchanged_ok"].values()
            if "identical_record" in v),
    }
    out = ROOT / args.out
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["verdict"], ensure_ascii=False, indent=2))
    print("fixed:", json.dumps({k: {"error_before": v.get("error_before")}
                                for k, v in list(summary["fixed"].items())[:6]},
                               ensure_ascii=False, indent=2))
    print(f"written {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
