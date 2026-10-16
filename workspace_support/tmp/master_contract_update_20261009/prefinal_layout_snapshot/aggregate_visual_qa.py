#!/usr/bin/env python
"""Aggregate page-by-page visual review reports against render_manifest.json.

Use the bundled Python runtime with -B. Without --final-qa-go this is a
preflight-only operation: it prints WAITING/FAIL/PASS and never writes final
coverage artifacts. Use --final-qa-go only after Root explicitly sends
FINAL_QA_GO.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "render_manifest.json"
DEFAULT_QA_DIR = ROOT / "qa"
OUTPUT_JSON = ROOT / "final_visual_coverage.json"
OUTPUT_MD = ROOT / "final_visual_coverage.md"
CHUNK_SIZE = 15


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def expected_groups(page_count: int) -> list[tuple[int, int]]:
    return [
        (start, min(start + CHUNK_SIZE - 1, page_count))
        for start in range(1, page_count + 1, CHUNK_SIZE)
    ]


def add_issue(
    issues: list[dict[str, Any]],
    source: str,
    message: str,
    *,
    page: int | None = None,
    severity: str = "error",
) -> None:
    issue: dict[str, Any] = {
        "severity": severity,
        "source": source,
        "message": message,
    }
    if page is not None:
        issue["page"] = page
    issues.append(issue)


def markdown_report(coverage: dict[str, Any]) -> str:
    docx = coverage["final_artifacts"]["docx"]
    pdf = coverage["final_artifacts"]["pdf"]
    page_coverage = coverage["page_coverage"]
    lines = [
        "# Final visual QA coverage",
        "",
        f"Status: **{coverage['status']}**",
        "",
        f"Final DOCX SHA-256: {docx['sha256']}",
        f"Final PDF SHA-256: {pdf['sha256']}",
        f"Expected pages: {page_coverage['expected_page_count']}",
        f"Pages reviewed exactly once: {page_coverage['reviewed_exactly_once']}",
        f"Pages passed: {page_coverage['passed_pages']}",
        f"Pages with issues: {page_coverage['pages_with_issues']}",
        f"Missing pages: {page_coverage['missing_pages']}",
        f"Duplicate page records: {page_coverage['duplicate_pages']}",
        "",
        "| QA report | Range | Report SHA-256 | Pages | Pass | Issues |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for report in coverage["reports"]:
        start = report.get("start")
        end = report.get("end")
        range_text = (
            f"{start:03d}–{end:03d}"
            if isinstance(start, int) and isinstance(end, int)
            else "invalid"
        )
        lines.append(
            f"| {report['path']} | {range_text} | {report.get('sha256', 'unavailable')} "
            f"| {report.get('covered_page_count', 0)} | {report.get('passed_page_count', 0)} "
            f"| {report.get('issue_count', 0)} |"
        )
    lines.extend(["", "## Issues", ""])
    if coverage["issues"]:
        for issue in coverage["issues"]:
            page_text = f" page {issue['page']}" if "page" in issue else ""
            lines.append(
                f"- [{issue['severity']}] {issue['source']}{page_text}: {issue['message']}"
            )
    else:
        lines.append("No issues recorded.")
    lines.extend(
        [
            "",
            "## Page bindings",
            "",
            "The JSON file contains one row per final page, binding the final DOCX SHA-256, "
            "same-run PDF SHA-256, actual PNG SHA-256, review result, and source QA report.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--qa-dir", type=Path, default=DEFAULT_QA_DIR)
    parser.add_argument(
        "--final-qa-go",
        action="store_true",
        help="Write final_visual_coverage.json/md only after Root sends FINAL_QA_GO.",
    )
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    qa_dir = args.qa_dir.resolve()
    if not manifest_path.is_file():
        print(json.dumps({"status": "FAIL", "error": f"Manifest missing: {manifest_path}"}))
        return 1
    try:
        manifest = load_json(manifest_path)
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": f"Cannot read manifest: {exc}"}))
        return 1

    global_issues: list[dict[str, Any]] = []
    if manifest.get("schema") != "final_render_manifest.v1":
        add_issue(global_issues, str(manifest_path), "Unexpected render manifest schema.")
    if manifest.get("status") != "PASS":
        add_issue(global_issues, str(manifest_path), "Render manifest status is not PASS.")

    docx_data = manifest.get("docx") or {}
    pdf_data = manifest.get("pdf") or {}
    page_rows = manifest.get("pages")
    if not isinstance(page_rows, list):
        add_issue(global_issues, str(manifest_path), "Manifest pages field is not a list.")
        page_rows = []
    docx_path = Path(str(docx_data.get("path", ""))).resolve()
    pdf_path = Path(str(pdf_data.get("path", ""))).resolve()
    docx_sha = str(docx_data.get("sha256", "")).lower()
    pdf_sha = str(pdf_data.get("sha256", "")).lower()
    page_count = pdf_data.get("page_count")
    if type(page_count) is not int or page_count <= 0:
        add_issue(global_issues, str(manifest_path), "PDF page count is missing or invalid.")
        page_count = 0

    actual_docx_sha: str | None = None
    actual_pdf_sha: str | None = None
    actual_pdf_pages: int | None = None
    if not docx_path.is_file():
        add_issue(global_issues, str(docx_path), "Final DOCX is missing.")
    else:
        actual_docx_sha = sha256_file(docx_path)
        if actual_docx_sha != docx_sha:
            add_issue(global_issues, str(docx_path), "Final DOCX SHA-256 no longer matches the manifest.")
    if not pdf_path.is_file():
        add_issue(global_issues, str(pdf_path), "Final PDF is missing.")
    else:
        actual_pdf_sha = sha256_file(pdf_path)
        if actual_pdf_sha != pdf_sha:
            add_issue(global_issues, str(pdf_path), "Final PDF SHA-256 no longer matches the manifest.")
        try:
            from pypdf import PdfReader

            actual_pdf_pages = len(PdfReader(str(pdf_path)).pages)
            if actual_pdf_pages != page_count:
                add_issue(global_issues, str(pdf_path), "Final PDF page count no longer matches the manifest.")
        except Exception as exc:
            add_issue(global_issues, str(pdf_path), f"Cannot read final PDF page count: {exc}")

    expected_page_numbers = set(range(1, page_count + 1))
    png_by_page: dict[int, dict[str, Any]] = {}
    for row in page_rows:
        if not isinstance(row, dict) or type(row.get("page")) is not int:
            add_issue(global_issues, str(manifest_path), "Manifest contains a malformed page row.")
            continue
        page = row["page"]
        if page in png_by_page:
            add_issue(global_issues, str(manifest_path), "Duplicate page number in render manifest.", page=page)
            continue
        png_path = Path(str(row.get("path", ""))).resolve()
        declared_sha = str(row.get("sha256", "")).lower()
        actual_png_sha: str | None = None
        if not png_path.is_file():
            add_issue(global_issues, str(png_path), "Rendered page PNG is missing.", page=page)
        else:
            actual_png_sha = sha256_file(png_path)
            if actual_png_sha != declared_sha:
                add_issue(global_issues, str(png_path), "Actual PNG SHA-256 no longer matches the manifest.", page=page)
        png_by_page[page] = {
            "path": str(png_path),
            "manifest_sha256": declared_sha,
            "actual_sha256": actual_png_sha,
            "bytes": row.get("bytes"),
            "dimensions_px": row.get("dimensions_px"),
        }

    missing_manifest_pages = sorted(expected_page_numbers - set(png_by_page))
    extra_manifest_pages = sorted(set(png_by_page) - expected_page_numbers)
    if missing_manifest_pages:
        add_issue(global_issues, str(manifest_path), f"Manifest is missing PNG pages: {missing_manifest_pages[:20]}")
    if extra_manifest_pages:
        add_issue(global_issues, str(manifest_path), f"Manifest has out-of-range PNG pages: {extra_manifest_pages[:20]}")

    groups = expected_groups(page_count)
    expected_range_set = set(groups)
    report_paths = sorted(qa_dir.glob("visual_*.json")) if qa_dir.is_dir() else []
    reports: list[dict[str, Any]] = []
    all_page_reviews: list[dict[str, Any]] = []
    reviews_by_page: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    report_range_counts: collections.Counter[tuple[int, int]] = collections.Counter()
    review_issues: list[dict[str, Any]] = []
    filename_pattern = re.compile(r"^visual_(\d+)_(\d+)\.json$", re.IGNORECASE)

    for report_path in report_paths:
        report_sha = sha256_file(report_path)
        report_record: dict[str, Any] = {
            "path": str(report_path.resolve()),
            "sha256": report_sha,
            "start": None,
            "end": None,
            "reviewer": None,
            "covered_page_count": 0,
            "passed_page_count": 0,
            "issue_count": 0,
            "issues": [],
            "unique_pages": [],
        }
        try:
            report = load_json(report_path)
        except Exception as exc:
            add_issue(report_record["issues"], str(report_path), f"Cannot parse report JSON: {exc}")
            report_record["issue_count"] = len(report_record["issues"])
            reports.append(report_record)
            review_issues.extend(report_record["issues"])
            continue

        start = report.get("start") if type(report.get("start")) is int else None
        end = report.get("end") if type(report.get("end")) is int else None
        reviewer = report.get("reviewer")
        report_record.update(
            {
                "start": start,
                "end": end,
                "reviewer": reviewer,
                "declared_docx_sha256": report.get("docx_sha256"),
                "declared_pdf_sha256": report.get("pdf_sha256"),
            }
        )
        match = filename_pattern.fullmatch(report_path.name)
        if start is None or end is None or start < 1 or end < start or end > page_count:
            add_issue(report_record["issues"], str(report_path), "Top-level start/end range is missing or invalid.")
        else:
            report_range_counts[(start, end)] += 1
            if (start, end) not in expected_range_set:
                add_issue(report_record["issues"], str(report_path), "Range does not match the 15-page review plan.")
        if not match or (start is not None and end is not None and (int(match.group(1)), int(match.group(2))) != (start, end)):
            add_issue(report_record["issues"], str(report_path), "Filename must match visual_<start>_<end>.json and top-level range.")
        if not isinstance(report.get("docx_sha256"), str) or report["docx_sha256"].lower() != docx_sha:
            add_issue(report_record["issues"], str(report_path), "Top-level DOCX SHA does not match the final manifest.")
        if not isinstance(report.get("pdf_sha256"), str) or report["pdf_sha256"].lower() != pdf_sha:
            add_issue(report_record["issues"], str(report_path), "Top-level PDF SHA does not match the final manifest.")
        if not isinstance(reviewer, str) or not reviewer.strip():
            add_issue(report_record["issues"], str(report_path), "Top-level reviewer is missing.")

        page_items = report.get("pages")
        if not isinstance(page_items, list):
            add_issue(report_record["issues"], str(report_path), "Pages field is not a list.")
            page_items = []
        report_record["covered_page_count"] = len(page_items)
        seen_in_report: set[int] = set()
        for page_item in page_items:
            if not isinstance(page_item, dict) or type(page_item.get("page")) is not int:
                add_issue(report_record["issues"], str(report_path), "Page row is malformed.")
                continue
            page = page_item["page"]
            page_issues = page_item.get("issues")
            render = png_by_page.get(page, {})
            actual_png_sha = render.get("actual_sha256")
            declared_png_sha = page_item.get("png_sha256")
            page_review = {
                "page": page,
                "final_docx_sha256": docx_sha,
                "render_pdf_sha256": pdf_sha,
                "png_path": render.get("path"),
                "png_sha256": actual_png_sha,
                "declared_png_sha256": declared_png_sha,
                "review_report_path": str(report_path.resolve()),
                "review_report_sha256": report_sha,
                "reviewer": reviewer,
                "inspected_original": page_item.get("inspected_original"),
                "status": page_item.get("status"),
                "issues": page_issues,
            }
            if page in seen_in_report:
                add_issue(report_record["issues"], str(report_path), "Page is duplicated within the report.", page=page)
            seen_in_report.add(page)
            if start is not None and end is not None and not start <= page <= end:
                add_issue(report_record["issues"], str(report_path), "Page is outside the declared range.", page=page)
            if page not in expected_page_numbers:
                add_issue(report_record["issues"], str(report_path), "Page is outside the final PDF page range.", page=page)
            if not isinstance(declared_png_sha, str) or not actual_png_sha or declared_png_sha.lower() != actual_png_sha:
                add_issue(report_record["issues"], str(report_path), "PNG SHA does not match the actual rendered PNG.", page=page)
            if page_item.get("inspected_original") is not True:
                add_issue(report_record["issues"], str(report_path), "Original-detail visual inspection is not confirmed.", page=page)
            status_value = page_item.get("status")
            if not isinstance(status_value, str) or status_value.lower() != "pass":
                add_issue(report_record["issues"], str(report_path), "Page status is not pass.", page=page)
            if not isinstance(page_issues, list):
                add_issue(report_record["issues"], str(report_path), "Page issues field must be a list.", page=page)
            elif page_issues:
                for item in page_issues:
                    add_issue(
                        report_record["issues"],
                        str(report_path),
                        f"Reviewer reported an issue: {json.dumps(item, ensure_ascii=False)}",
                        page=page,
                    )
            reviews_by_page[page].append(page_review)
            all_page_reviews.append(page_review)
            if (
                page_item.get("inspected_original") is True
                and isinstance(status_value, str)
                and status_value.lower() == "pass"
                and isinstance(page_issues, list)
                and not page_issues
                and isinstance(declared_png_sha, str)
                and actual_png_sha
                and declared_png_sha.lower() == actual_png_sha
                and page in expected_page_numbers
                and start is not None
                and end is not None
                and start <= page <= end
            ):
                report_record["passed_page_count"] += 1
        report_record["unique_pages"] = sorted(seen_in_report)
        report_record["issue_count"] = len(report_record["issues"])
        reports.append(report_record)
        review_issues.extend(report_record["issues"])

    for page_range, count in sorted(report_range_counts.items()):
        if count > 1:
            add_issue(review_issues, str(qa_dir), f"Duplicate reports for range {page_range[0]}-{page_range[1]}.")
    missing_groups = [list(group) for group in groups if report_range_counts[group] == 0]
    unexpected_ranges = [list(group) for group in sorted(set(report_range_counts) - expected_range_set)]
    duplicate_pages = sorted(page for page, rows in reviews_by_page.items() if len(rows) > 1)
    missing_review_pages = sorted(expected_page_numbers - set(reviews_by_page))
    extra_review_pages = sorted(set(reviews_by_page) - expected_page_numbers)
    if duplicate_pages:
        add_issue(review_issues, str(qa_dir), f"Duplicate page coverage: {duplicate_pages[:20]}")
    if extra_review_pages:
        add_issue(review_issues, str(qa_dir), f"Out-of-range page coverage: {extra_review_pages[:20]}")

    ranges_complete = (
        all(report_range_counts[group] == 1 for group in groups)
        and set(report_range_counts) == expected_range_set
    )
    pages_exactly_once = not missing_review_pages and not duplicate_pages and not extra_review_pages
    if ranges_complete and pages_exactly_once and not global_issues and not review_issues:
        status = "PASS"
    elif global_issues or review_issues:
        status = "FAIL"
    else:
        status = "WAITING"

    all_issues = global_issues + review_issues
    passed_page_count = sum(
        1
        for page, rows in reviews_by_page.items()
        if len(rows) == 1
        and rows[0].get("inspected_original") is True
        and isinstance(rows[0].get("status"), str)
        and rows[0]["status"].lower() == "pass"
        and rows[0].get("issues") == []
        and rows[0].get("png_sha256") == rows[0].get("declared_png_sha256")
    )
    page_bindings = []
    for page in sorted(expected_page_numbers):
        render = png_by_page.get(page, {})
        review_rows = reviews_by_page.get(page, [])
        page_bindings.append(
            {
                "page": page,
                "final_docx_sha256": docx_sha,
                "render_pdf_sha256": pdf_sha,
                "png_path": render.get("path"),
                "png_sha256": render.get("actual_sha256"),
                "review_count": len(review_rows),
                "reviews": review_rows,
            }
        )

    coverage: dict[str, Any] = {
        "schema": "final_visual_coverage.v1",
        "status": status,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "render_manifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
            "status": manifest.get("status"),
        },
        "final_artifacts": {
            "docx": {
                "path": str(docx_path),
                "bytes": docx_path.stat().st_size if docx_path.is_file() else None,
                "sha256": actual_docx_sha,
            },
            "pdf": {
                "path": str(pdf_path),
                "bytes": pdf_path.stat().st_size if pdf_path.is_file() else None,
                "sha256": actual_pdf_sha,
                "page_count": actual_pdf_pages,
            },
        },
        "page_coverage": {
            "expected_page_count": page_count,
            "expected_group_size": CHUNK_SIZE,
            "expected_groups": [list(group) for group in groups],
            "reports_found": len(reports),
            "expected_reports": len(groups),
            "ranges_complete": ranges_complete,
            "missing_groups": missing_groups,
            "unexpected_ranges": unexpected_ranges,
            "reviewed_page_rows": len(all_page_reviews),
            "reviewed_exactly_once": sum(1 for page in expected_page_numbers if len(reviews_by_page.get(page, [])) == 1),
            "passed_pages": passed_page_count,
            "pages_with_issues": len({issue["page"] for issue in all_issues if type(issue.get("page")) is int}),
            "missing_pages": missing_review_pages,
            "duplicate_pages": duplicate_pages,
            "extra_pages": extra_review_pages,
            "render_png_rows": len(png_by_page),
            "render_pngs_cover_pdf_exactly": not missing_manifest_pages and not extra_manifest_pages,
        },
        "reports": reports,
        "issues": all_issues,
        "pages": page_bindings,
    }

    summary = {
        "status": status,
        "reports_found": len(reports),
        "expected_reports": len(groups),
        "pages_reviewed_exactly_once": coverage["page_coverage"]["reviewed_exactly_once"],
        "expected_pages": page_count,
        "missing_groups": missing_groups,
        "missing_pages": missing_review_pages,
        "duplicate_pages": duplicate_pages,
        "issue_count": len(all_issues),
        "outputs_written": False,
    }
    if args.final_qa_go:
        OUTPUT_JSON.write_text(
            json.dumps(coverage, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        OUTPUT_MD.write_text(markdown_report(coverage) + "\n", encoding="utf-8")
        summary["outputs_written"] = True
        summary["json_output"] = str(OUTPUT_JSON)
        summary["markdown_output"] = str(OUTPUT_MD)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if status == "FAIL":
        return 1
    if status == "WAITING":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
