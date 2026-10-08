#!/usr/bin/env python3
"""One-shot read-only QA aggregation for the merged V1.47 master.

This helper must only be run after the root explicitly confirms all groups are
ready and has reviewed the merged content. It reads page QA reports, actual
rendered PNG bytes, source/review evidence, and the frozen handover artifacts.
It writes only MERGED_FINAL_QA_COVERAGE.md and .json beside this script, and
refuses to overwrite either output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "tmp" / "v147_user_merge_20261007"
QA_DIR = TASK_DIR / "qa"
MASTER_RENDER_DIR = TASK_DIR / "fresh_merge_final_render"
OUTPUT_MD = TASK_DIR / "MERGED_FINAL_QA_COVERAGE.md"
OUTPUT_JSON = TASK_DIR / "MERGED_FINAL_QA_COVERAGE.json"

EXPECTED_MASTER_SHA256 = (
    "70aa097680aa1920528ba4b6d9646821ac78b367618c0e9b8dbc36439fa38044"
)
EXPECTED_MASTER_PAGES = 226
EXPECTED_GROUPS = [
    (1, 18),
    (19, 36),
    (37, 54),
    (55, 72),
    (73, 90),
    (91, 108),
    (109, 126),
    (127, 144),
    (145, 162),
    (163, 180),
    (181, 198),
    (199, 216),
    (217, 226),
]

HANDOVER_DOCX_REL = (
    "docs/handover/20261007/"
    "RelicWeave_A12_VesselForge_PGFrag_Handover_20261007.docx"
)
HANDOVER_DOCX_SHA256 = (
    "c8b4e57340c7c9d485aeb5c6aa298ba90ac166870c9d8d0a7d414d35051f7fd2"
)
HANDOVER_MD_REL = "docs/handover/20261007/HANDOVER.md"
HANDOVER_MD_SHA256 = (
    "f226a153f8aed2da04e07298f1277cd74071370d52cf74a4967702c2792f7a53"
)
HANDOVER_RENDER_DIR = ROOT / "tmp" / "closeout_documents_20261007" / "handover_render"
HANDOVER_QA_DIR = ROOT / "tmp" / "closeout_documents_20261007" / "qa"
OLD_BASE_COVERAGE_JSON = (
    ROOT / "tmp" / "closeout_documents_20261007" / "FINAL_QA_COVERAGE.json"
)
BASELINE_OVERWRITE_ADDENDUM_JSON = (
    HANDOVER_QA_DIR / "final_master_086_102.baseline_overwrite_addendum.json"
)
BASELINE_OVERWRITE_ADDENDUM_MD = (
    HANDOVER_QA_DIR / "final_master_086_102.baseline_overwrite_addendum.md"
)
PAGE5_ADDENDUM_JSON = HANDOVER_QA_DIR / "final_handover_001_007.addendum.json"
PAGE5_ADDENDUM_MD = HANDOVER_QA_DIR / "final_handover_001_007.addendum.md"

HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
PAGE_PNG = re.compile(r"^page-(\d+)\.png$")
MERGED_REPORT = re.compile(r"^merged_master_(\d{3})_(\d{3})\.json$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    return {
        "path": relative_or_absolute(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def relative_or_absolute(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def resolve_arg_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def read_json(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append(f"Missing {label}: {relative_or_absolute(path)}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # Preserve a useful diagnostic in the coverage record.
        errors.append(f"Cannot parse {label} {relative_or_absolute(path)}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object: {relative_or_absolute(path)}")
        return None
    return value


def walk_hashes(value: Any, prefix: str = "", *, skip_pages: bool = True) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if skip_pages and key == "pages":
                continue
            key_path = f"{prefix}{key}"
            if "sha" in key.lower() and isinstance(child, str) and HEX64.fullmatch(child):
                found.append((key_path, child.lower()))
            found.extend(walk_hashes(child, key_path + ".", skip_pages=skip_pages))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(walk_hashes(child, f"{prefix}[{index}].", skip_pages=skip_pages))
    return found


def source_hashes(report: dict[str, Any]) -> set[str]:
    """Collect SHA fields explicitly bound to source/document/master inputs."""
    terms = ("source", "document", "master", "docx", "input_document")
    return {
        digest
        for key_path, digest in walk_hashes(report)
        if any(term in key_path.lower() for term in terms)
    }


def png_identity(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"Not a PNG with a valid IHDR: {relative_or_absolute(path)}")
    width, height = struct.unpack(">II", header[16:24])
    return {
        "path": relative_or_absolute(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "dimensions_px": [width, height],
    }


def page_png_inventory(folder: Path, label: str, errors: list[str]) -> dict[int, Path]:
    if not folder.is_dir():
        errors.append(f"Missing {label} directory: {relative_or_absolute(folder)}")
        return {}
    found: dict[int, Path] = {}
    duplicates: list[int] = []
    for path in folder.iterdir():
        match = PAGE_PNG.fullmatch(path.name)
        if not match or not path.is_file():
            continue
        page = int(match.group(1))
        if page in found:
            duplicates.append(page)
        found[page] = path
    if duplicates:
        errors.append(f"Duplicate numeric page PNG names in {label}: {sorted(set(duplicates))}")
    return found


def first_value(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in obj:
            return obj[key]
    return None


def report_method_is_individual_original(json_obj: dict[str, Any], md_text: str) -> bool:
    blob = (json.dumps(json_obj, ensure_ascii=False) + "\n" + md_text).lower()
    individual = any(token in blob for token in ("individually", "each page", "each png", "every page"))
    original_detail = any(
        token in blob
        for token in ("view_image", "detail=original", "original detail", "original resolution")
    )
    return individual and original_detail


def top_level_issue_count(report: dict[str, Any]) -> int:
    total = 0

    def visit(value: Any, in_pages: bool = False) -> None:
        nonlocal total
        if isinstance(value, dict):
            for key, child in value.items():
                child_in_pages = in_pages or key == "pages"
                lowered = key.lower().replace("_", "")
                if not in_pages and lowered in ("issuecount", "totalissues", "totalissuecount"):
                    if isinstance(child, int) and not isinstance(child, bool):
                        total += max(child, 0)
                if key == "issues" and not in_pages and isinstance(child, list):
                    total += len(child)
                visit(child, child_in_pages)
        elif isinstance(value, list):
            for child in value:
                visit(child, in_pages)

    visit(report)
    return total


def status_is_pass(row: dict[str, Any]) -> bool:
    pass_flag = row.get("pass")
    if pass_flag is False:
        return False
    status = first_value(row, ("result", "verdict", "status"))
    if status is not None:
        return str(status).strip().lower() in {"pass", "passed", "ok", "accepted"}
    return pass_flag is True


def inspect_master_groups(master_docx: Path, errors: list[str]) -> dict[str, Any]:
    expected_groups = set(EXPECTED_GROUPS)
    if not master_docx.is_file():
        errors.append(f"Missing merged master DOCX: {relative_or_absolute(master_docx)}")
        actual_master_sha = None
        master_identity = None
    else:
        actual_master_sha = sha256_file(master_docx)
        master_identity = file_identity(master_docx)
        if actual_master_sha.lower() != EXPECTED_MASTER_SHA256:
            errors.append(
                f"Merged master SHA mismatch: expected {EXPECTED_MASTER_SHA256}, got {actual_master_sha}"
            )

    inventory = page_png_inventory(MASTER_RENDER_DIR, "merged master render", errors)
    expected_pages = set(range(1, EXPECTED_MASTER_PAGES + 1))
    if set(inventory) != expected_pages:
        errors.append(
            "Merged master PNG inventory must be exactly pages 1..226; "
            f"missing={sorted(expected_pages - set(inventory))}, "
            f"extra={sorted(set(inventory) - expected_pages)}"
        )

    if not QA_DIR.is_dir():
        errors.append(f"Missing merged master QA directory: {relative_or_absolute(QA_DIR)}")
        report_paths: list[Path] = []
    else:
        report_paths = sorted(QA_DIR.glob("merged_master_*.json"), key=lambda p: p.name)

    by_range: dict[tuple[int, int], Path] = {}
    unexpected: list[str] = []
    for path in report_paths:
        match = MERGED_REPORT.fullmatch(path.name)
        if not match:
            unexpected.append(path.name)
            continue
        page_range = (int(match.group(1)), int(match.group(2)))
        if page_range in by_range:
            errors.append(f"Duplicate merged QA range {page_range}: {path.name}")
        by_range[page_range] = path
    if unexpected:
        errors.append(f"Unexpected merged QA JSON filenames: {unexpected}")
    if set(by_range) != expected_groups:
        errors.append(
            "Merged QA group set mismatch; "
            f"missing={sorted(expected_groups - set(by_range))}, "
            f"extra={sorted(set(by_range) - expected_groups)}"
        )

    page_records: list[dict[str, Any]] = []
    group_records: list[dict[str, Any]] = []
    for first, last in EXPECTED_GROUPS:
        page_range = (first, last)
        json_path = by_range.get(page_range)
        if json_path is None:
            continue
        md_path = json_path.with_suffix(".md")
        report = read_json(json_path, f"merged master QA JSON {json_path.name}", errors)
        if report is None:
            continue
        if not md_path.is_file():
            errors.append(f"Missing paired merged master QA Markdown: {relative_or_absolute(md_path)}")
            md_text = ""
        else:
            md_text = md_path.read_text(encoding="utf-8-sig")
        if not report_method_is_individual_original(report, md_text):
            errors.append(f"{json_path.name} lacks individual original-detail inspection evidence")
        bound_hashes = source_hashes(report)
        if EXPECTED_MASTER_SHA256 not in bound_hashes:
            errors.append(f"{json_path.name} does not bind to the merged master SHA")
        wrong_hashes = sorted(value for value in bound_hashes if value != EXPECTED_MASTER_SHA256)
        if wrong_hashes:
            errors.append(f"{json_path.name} has unexpected source SHA values: {wrong_hashes}")
        declared_issues = top_level_issue_count(report)
        if declared_issues:
            errors.append(f"{json_path.name} declares {declared_issues} top-level issue(s)")

        report_pages = report.get("pages")
        if not isinstance(report_pages, list):
            errors.append(f"{json_path.name} has no page list")
            report_pages = []
        numbers: list[int] = []
        group_png_matches = 0
        group_inspected = 0
        group_pass = 0
        for row in report_pages:
            if not isinstance(row, dict):
                errors.append(f"{json_path.name} has a non-object page row")
                continue
            try:
                page = int(row.get("page"))
            except (TypeError, ValueError):
                errors.append(f"{json_path.name} has a page row without an integer page")
                continue
            numbers.append(page)
            image_ref = first_value(row, ("png", "file", "image"))
            png_name = Path(str(image_ref)).name if image_ref else ""
            image_match = PAGE_PNG.fullmatch(png_name)
            if not image_match or int(image_match.group(1)) != page:
                errors.append(f"{json_path.name} page {page} has an invalid PNG reference: {image_ref!r}")
                continue
            image_path = inventory.get(page)
            if image_path is None:
                errors.append(f"Missing merged master page {page} PNG")
                continue
            try:
                image_meta = png_identity(image_path)
            except Exception as exc:
                errors.append(str(exc))
                continue
            declared_png_sha = first_value(row, ("sha256", "pngSha256", "png_sha256"))
            if not isinstance(declared_png_sha, str) or not HEX64.fullmatch(declared_png_sha):
                errors.append(f"{json_path.name} page {page} has no full PNG SHA-256")
            elif declared_png_sha.lower() != image_meta["sha256"]:
                errors.append(f"{json_path.name} page {page} PNG SHA mismatch")
            else:
                group_png_matches += 1
            if image_meta["dimensions_px"] != [1547, 2002]:
                errors.append(f"Merged master page {page} dimensions are {image_meta['dimensions_px']}")
            inspected = row.get("inspected") is True
            if inspected:
                group_inspected += 1
            else:
                errors.append(f"{json_path.name} page {page} lacks inspected=true")
            page_pass = status_is_pass(row)
            issues = row.get("issues", [])
            if issues not in (None, []):
                errors.append(f"{json_path.name} page {page} has issue entries")
            if page_pass and issues in (None, []):
                group_pass += 1
            else:
                errors.append(f"{json_path.name} page {page} is not a clean PASS")
            page_records.append(
                {
                    "page": page,
                    "png": image_meta["path"],
                    "png_bytes": image_meta["bytes"],
                    "png_sha256": image_meta["sha256"],
                    "dimensions_px": image_meta["dimensions_px"],
                    "inspected": inspected,
                    "status": "pass" if page_pass and issues in (None, []) else str(first_value(row, ("result", "verdict", "status"))),
                    "issue_count": len(issues) if isinstance(issues, list) else (0 if issues is None else 1),
                }
            )
        expected_group_pages = set(range(first, last + 1))
        if set(numbers) != expected_group_pages or len(numbers) != len(set(numbers)):
            errors.append(
                f"{json_path.name} page rows do not exactly cover {first}..{last}; "
                f"missing={sorted(expected_group_pages - set(numbers))}, "
                f"extra={sorted(set(numbers) - expected_group_pages)}"
            )
        group_records.append(
            {
                "range": [first, last],
                "json": file_identity(json_path),
                "markdown": file_identity(md_path) if md_path.is_file() else None,
                "source_sha256_binding": sorted(bound_hashes),
                "pages_expected": last - first + 1,
                "pages_inspected_true": group_inspected,
                "png_sha256_matches": group_png_matches,
                "clean_pass_pages": group_pass,
                "declared_top_level_issues": declared_issues,
                "inspection_method_individually_at_original_detail": report_method_is_individual_original(report, md_text),
            }
        )

    all_numbers = [row["page"] for row in page_records]
    if set(all_numbers) != expected_pages or len(all_numbers) != len(set(all_numbers)):
        errors.append(
            "Merged page rows do not cover pages 1..226 exactly once; "
            f"missing={sorted(expected_pages - set(all_numbers))}, "
            f"extra={sorted(set(all_numbers) - expected_pages)}"
        )
    return {
        "source_docx": master_identity,
        "render_directory": relative_or_absolute(MASTER_RENDER_DIR),
        "render_png_count": len(inventory),
        "expected_page_range": [1, EXPECTED_MASTER_PAGES],
        "qa_group_count": len(group_records),
        "qa_groups": group_records,
        "page_row_count": len(page_records),
        "unique_page_count": len(set(all_numbers)),
        "pages_inspected_true": sum(1 for page in page_records if page["inspected"]),
        "png_sha256_matches": sum(group["png_sha256_matches"] for group in group_records),
        "clean_pass_pages": sum(group["clean_pass_pages"] for group in group_records),
        "page_png_sha256": page_records,
    }


def inspect_source_review_inputs(
    source_proof_md: Path,
    source_proof_json: Path,
    root_review_md: Path,
    root_review_json: Path,
    errors: list[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, md_path, json_path in (
        ("independent_merged_static_final_sourceproof", source_proof_md, source_proof_json),
        ("root_content_review", root_review_md, root_review_json),
    ):
        md_text = ""
        json_obj: dict[str, Any] | None = None
        if not md_path.is_file():
            errors.append(f"Missing {label} Markdown: {relative_or_absolute(md_path)}")
        else:
            md_text = md_path.read_text(encoding="utf-8-sig")
        json_obj = read_json(json_path, f"{label} JSON", errors)
        combined = md_text + "\n" + (json.dumps(json_obj, ensure_ascii=False) if json_obj else "")
        bound = EXPECTED_MASTER_SHA256 in combined.lower()
        if not bound:
            errors.append(f"{label} does not cite the merged master SHA")
        result[label] = {
            "markdown": file_identity(md_path) if md_path.is_file() else None,
            "json": file_identity(json_path) if json_path.is_file() else None,
            "cites_merged_master_sha256": bound,
            "json_status": first_value(json_obj or {}, ("status", "result", "verdict", "overall_status", "overallStatus")),
        }
    return result


def inspect_handover(errors: list[str]) -> dict[str, Any]:
    handover_error_start = len(errors)
    handover_docx = ROOT / Path(HANDOVER_DOCX_REL)
    handover_md = ROOT / Path(HANDOVER_MD_REL)
    for label, path, expected in (
        ("handover DOCX", handover_docx, HANDOVER_DOCX_SHA256),
        ("handover Markdown", handover_md, HANDOVER_MD_SHA256),
    ):
        if not path.is_file():
            errors.append(f"Missing {label}: {relative_or_absolute(path)}")
        elif sha256_file(path).lower() != expected:
            errors.append(f"{label} SHA mismatch: {relative_or_absolute(path)}")

    json_1_7_path = HANDOVER_QA_DIR / "final_handover_001_007.json"
    json_8_13_path = HANDOVER_QA_DIR / "final_handover_008_013.json"
    addendum_path = PAGE5_ADDENDUM_JSON
    report_1_7 = read_json(json_1_7_path, "handover pages 1-7 QA JSON", errors) or {}
    report_8_13 = read_json(json_8_13_path, "handover pages 8-13 QA JSON", errors) or {}
    addendum = read_json(addendum_path, "handover page 5 correction addendum JSON", errors) or {}
    rows: list[dict[str, Any]] = []
    png_hash_matches = 0
    inventory = page_png_inventory(HANDOVER_RENDER_DIR, "handover render", errors)
    if set(inventory) != set(range(1, 14)):
        errors.append("Handover page PNG inventory must be exactly pages 1..13")

    for report_path, report in ((json_1_7_path, report_1_7), (json_8_13_path, report_8_13)):
        pages = report.get("pages", [])
        if not isinstance(pages, list):
            errors.append(f"{report_path.name} has no page list")
            continue
        for row in pages:
            if not isinstance(row, dict):
                errors.append(f"{report_path.name} contains a non-object page row")
                continue
            try:
                page = int(row.get("page"))
            except (TypeError, ValueError):
                errors.append(f"{report_path.name} has a page row without an integer page")
                continue
            png_path = inventory.get(page)
            if png_path is None:
                errors.append(f"Missing handover page {page} PNG")
                continue
            try:
                meta = png_identity(png_path)
            except Exception as exc:
                errors.append(str(exc))
                continue
            declared = first_value(row, ("pngSha256", "sha256", "png_sha256"))
            if not isinstance(declared, str) or not HEX64.fullmatch(declared) or declared.lower() != meta["sha256"]:
                errors.append(f"Handover page {page} PNG hash does not match {report_path.name}")
            else:
                png_hash_matches += 1
            if row.get("inspected") is not True:
                errors.append(f"{report_path.name} page {page} lacks inspected=true")
            if meta["dimensions_px"] != [1547, 2002]:
                errors.append(f"Handover page {page} dimensions are {meta['dimensions_px']}")
            rows.append(
                {
                    "page": page,
                    "png": meta["path"],
                    "bytes": meta["bytes"],
                    "sha256": meta["sha256"],
                    "inspected": row.get("inspected") is True,
                }
            )
    handover_nums = [row["page"] for row in rows]
    if set(handover_nums) != set(range(1, 14)) or len(handover_nums) != len(set(handover_nums)):
        errors.append("Handover QA JSONs do not cover pages 1..13 exactly once")

    addendum = addendum or {}
    correction = addendum.get("correction", {})
    page5_path = HANDOVER_RENDER_DIR / "page-5.png"
    if not page5_path.is_file():
        errors.append("Missing handover page 5 PNG")
        page5_meta = None
    else:
        page5_meta = png_identity(page5_path)
    if page5_meta:
        if (
            correction.get("page") != 5
            or correction.get("reopenedOriginalPngIndividuallyAtOriginalDetail") is not True
            or correction.get("pngSha256", "").lower() != page5_meta["sha256"]
            or correction.get("pngBytes") != page5_meta["bytes"]
        ):
            errors.append("Handover page 5 correction addendum does not match the actual page PNG")
    final_visual_qa = addendum.get("finalVisualQa", {})
    if (
        final_visual_qa.get("status") != "PASS"
        or final_visual_qa.get("totalIssues") != 0
        or addendum.get("originalReportsOverwritten") is not False
    ):
        errors.append("Handover page 5 correction addendum lacks final PASS/0-issue/preserved-report evidence")

    # Verify that the page-5 addendum amends, but does not replace, the old page 1-7 reports.
    amended_md = HANDOVER_QA_DIR / "final_handover_001_007.md"
    if not amended_md.is_file():
        errors.append("Missing original handover pages 1-7 Markdown paired with correction addendum")
    amends = addendum.get("amends", {})
    if amended_md.is_file() and sha256_file(amended_md).lower() != str(amends.get("markdown", {}).get("sha256", "")).lower():
        errors.append("Page 5 addendum Markdown identity does not match the original report")
    if json_1_7_path.is_file() and sha256_file(json_1_7_path).lower() != str(amends.get("json", {}).get("sha256", "")).lower():
        errors.append("Page 5 addendum JSON identity does not match the original report")
    addendum_md = PAGE5_ADDENDUM_MD
    if not addendum_md.is_file():
        errors.append("Missing handover page 5 correction addendum Markdown")

    # Both old handover QA groups must bind to the preserved handover DOCX and Markdown.
    src1 = report_1_7.get("sources", {})
    docx1 = src1.get("docx", {})
    md1 = src1.get("markdown", {})
    bindings = [
        (docx1.get("path"), docx1.get("sha256"), docx1.get("matchesSuppliedSha256")),
        (md1.get("path"), md1.get("sha256"), md1.get("matchesSuppliedSha256")),
        (
            report_8_13.get("source_file"),
            report_8_13.get("source_sha256"),
            report_8_13.get("source_sha256_matches_expected"),
        ),
        (
            report_8_13.get("source_markdown"),
            report_8_13.get("source_markdown_sha256"),
            report_8_13.get("source_markdown_sha256_matches_expected"),
        ),
    ]
    expected_by_path = {
        HANDOVER_DOCX_REL: HANDOVER_DOCX_SHA256,
        HANDOVER_MD_REL: HANDOVER_MD_SHA256,
    }
    for path_text, digest, declared_match in bindings:
        if path_text not in expected_by_path or str(digest).lower() != expected_by_path.get(path_text):
            errors.append(f"Handover source binding is unexpected or mismatched: {path_text!r}")
        if declared_match is not True:
            errors.append(f"Handover source binding lacks a true match flag for {path_text!r}")

    return {
        "source_docx": file_identity(handover_docx) if handover_docx.is_file() else None,
        "source_docx_expected_sha256": HANDOVER_DOCX_SHA256,
        "source_markdown": file_identity(handover_md) if handover_md.is_file() else None,
        "source_markdown_expected_sha256": HANDOVER_MD_SHA256,
        "render_directory": relative_or_absolute(HANDOVER_RENDER_DIR),
        "page_png_count": len(inventory),
        "pages_covered": len(rows),
        "unique_pages": len(set(handover_nums)),
        "png_sha256_matches": png_hash_matches,
        "page5_correction": {
            "addendum_json": file_identity(addendum_path) if addendum_path.is_file() else None,
            "addendum_markdown": file_identity(addendum_md) if addendum_md.is_file() else None,
            "actual_png": page5_meta,
            "final_status": final_visual_qa.get("status"),
            "final_issue_count": final_visual_qa.get("totalIssues"),
            "original_reports_overwritten": addendum.get("originalReportsOverwritten"),
            "amended_reports_match": bool(
                amended_md.is_file()
                and json_1_7_path.is_file()
                and sha256_file(amended_md).lower() == str(amends.get("markdown", {}).get("sha256", "")).lower()
                and sha256_file(json_1_7_path).lower() == str(amends.get("json", {}).get("sha256", "")).lower()
            ),
        },
        "effective_status_after_page5_addendum": "PASS" if len(errors) == handover_error_start else "BLOCKED",
        "page_png_sha256": sorted(rows, key=lambda row: row["page"]),
        "qa_json_inputs": [
            file_identity(json_1_7_path) if json_1_7_path.is_file() else None,
            file_identity(json_8_13_path) if json_8_13_path.is_file() else None,
        ],
    }


def inspect_history(errors: list[str]) -> dict[str, Any]:
    addendum = read_json(BASELINE_OVERWRITE_ADDENDUM_JSON, "baseline overwrite addendum JSON", errors) or {}
    md_text = ""
    if not BASELINE_OVERWRITE_ADDENDUM_MD.is_file():
        errors.append(f"Missing baseline overwrite addendum Markdown: {relative_or_absolute(BASELINE_OVERWRITE_ADDENDUM_MD)}")
    else:
        md_text = BASELINE_OVERWRITE_ADDENDUM_MD.read_text(encoding="utf-8-sig")
    overwritten = addendum.get("overwritten_baseline_report", {})
    if overwritten.get("exact_original_report_recoverable") is not False:
        errors.append("Baseline overwrite addendum does not preserve the unrecoverable status")
    if overwritten.get("exact_report_backup_created_before_overwrite") is not False:
        errors.append("Baseline overwrite addendum does not record the missing exact pre-overwrite backup")
    if "does not reconstruct" not in md_text.lower() and "not reconstruct" not in md_text.lower():
        errors.append("Baseline overwrite addendum does not explicitly rule out reconstruction")

    oldbase: dict[str, Any] | None = None
    if OLD_BASE_COVERAGE_JSON.is_file():
        oldbase = read_json(OLD_BASE_COVERAGE_JSON, "frozen oldbase QA coverage JSON", errors)
    if oldbase and oldbase.get("status") != "base_review_complete_pending_v4":
        errors.append("Frozen oldbase QA coverage status changed unexpectedly")
    if oldbase and oldbase.get("record_scope") == "oldbase_only":
        # It is cited only as prior history and never contributes to merged page PASS.
        oldbase_ref = file_identity(OLD_BASE_COVERAGE_JSON)
    else:
        oldbase_ref = None
        errors.append("Oldbase QA coverage is missing its oldbase-only/pending-v4 identity")

    current_json_copy_equal = False
    current_markdown_copy_equal = False
    for suffix in ("md", "json"):
        old_path = HANDOVER_QA_DIR / f"master_086_102.{suffix}"
        final_path = HANDOVER_QA_DIR / f"final_master_086_102.{suffix}"
        if not old_path.is_file() or not final_path.is_file():
            errors.append(f"Missing preserved current 086-102 report copy ({suffix})")
            continue
        if old_path.read_bytes() != final_path.read_bytes():
            errors.append(f"Current final_master_086_102.{suffix} is not byte-identical to current master_086_102.{suffix}")
        elif suffix == "json":
            current_json_copy_equal = True
        else:
            current_markdown_copy_equal = True

    return {
        "baseline_overwrite_addendum_json": file_identity(BASELINE_OVERWRITE_ADDENDUM_JSON) if BASELINE_OVERWRITE_ADDENDUM_JSON.is_file() else None,
        "baseline_overwrite_addendum_markdown": file_identity(BASELINE_OVERWRITE_ADDENDUM_MD) if BASELINE_OVERWRITE_ADDENDUM_MD.is_file() else None,
        "baseline_original_report_recoverable": overwritten.get("exact_original_report_recoverable"),
        "baseline_original_report_reconstructed": False,
        "baseline_docx_sha256_recorded": overwritten.get("baseline_docx_sha256"),
        "baseline_203_page_render_retained_as_recorded": addendum.get("retained_baseline_artifacts", {}).get("baseline_docx_and_203_page_png_render_retained"),
        "current_086_102_final_json_copy_identical_to_overwritten_path": current_json_copy_equal,
        "current_086_102_final_markdown_copy_identical_to_overwritten_path": current_markdown_copy_equal,
        "current_086_102_copies_both_identical": current_json_copy_equal and current_markdown_copy_equal,
        "oldbase_qa_reference_only": oldbase_ref,
        "oldbase_used_to_grant_merged_master_pass": False,
        "known_tmp_helper_loss_or_overwrite_records": {
            "count_from_root_instruction": 2,
            "provenance": "recorded from the root instruction; item details are not reconstructed",
            "artifacts_reconstructed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-docx", required=True, help="Exact merged V1.47 DOCX whose SHA must be the frozen 70aa... digest.")
    parser.add_argument("--source-proof-md", required=True, help="Final independent_merged_static source proof Markdown.")
    parser.add_argument("--source-proof-json", required=True, help="Final independent_merged_static source proof JSON.")
    parser.add_argument("--root-content-review-md", required=True, help="Root content review Markdown for the merged master.")
    parser.add_argument("--root-content-review-json", required=True, help="Root content review JSON for the merged master.")
    parser.add_argument("--final-qa-allgroupsready", action="store_true", help="Required explicit gate from root before aggregation.")
    parser.add_argument("--root-content-review-accepted", action="store_true", help="Required explicit root acceptance gate before a final PASS can be recorded.")
    args = parser.parse_args()

    if not args.final_qa_allgroupsready:
        parser.error("wait for root's finalQA allgroupsready instruction before running this helper")
    if not args.root_content_review_accepted:
        parser.error("a final PASS requires root to explicitly accept the merged content review")
    if OUTPUT_MD.exists() or OUTPUT_JSON.exists():
        parser.error("coverage outputs already exist; preserve the frozen files and do not overwrite them")

    errors: list[str] = []
    master_docx = resolve_arg_path(args.master_docx)
    source_proof_md = resolve_arg_path(args.source_proof_md)
    source_proof_json = resolve_arg_path(args.source_proof_json)
    root_review_md = resolve_arg_path(args.root_content_review_md)
    root_review_json = resolve_arg_path(args.root_content_review_json)

    master = inspect_master_groups(master_docx, errors)
    reviews = inspect_source_review_inputs(
        source_proof_md, source_proof_json, root_review_md, root_review_json, errors
    )
    handover = inspect_handover(errors)
    history = inspect_history(errors)

    status = "PASS" if not errors else "BLOCKED_MISMATCHES"
    coverage: dict[str, Any] = {
        "schema": "v147_merged_final_qa_coverage.v1",
        "status": status,
        "final_master_pass": not errors,
        "aggregation_gates": {
            "root_confirmed_final_qa_all_groups_ready": True,
            "root_content_review_accepted": True,
            "oldbase_qa_used_for_new_master_acceptance": False,
        },
        "merged_master": master,
        "source_and_content_reviews": reviews,
        "handover_qa_reused_without_rerender": handover,
        "preserved_history": history,
        "root_visual_observations": [
            {"page": 110, "note": "E05 heading is followed by two lines of body text; root review does not classify it as an isolated heading."},
            {"page": 38, "note": "RESEARCH_CANDIDATE wraps across lines but remains readable; root review does not classify the wrap as a defect."},
            {"page": 136, "note": "Continuation template has no repeated table header; if readable, retain this as a note rather than an issue."},
        ],
        "integrity_findings": errors,
        "scope_note": "One-shot read/hash aggregation only. No rendering, source edits, numerical work, CAD, tests, or Git writes.",
    }
    md_lines = [
        "# Merged final QA coverage",
        "",
        f"**Status: `{status}`.** This report covers the merged candidate only after root marked all QA groups ready and accepted the content review.",
        "",
        f"Merged master SHA-256: `{EXPECTED_MASTER_SHA256}`. Rendered pages: {master['page_row_count']}/{EXPECTED_MASTER_PAGES}; page PNG SHA matches: {master['png_sha256_matches']}; clean pass pages: {master['clean_pass_pages']}.",
        "",
        "The page groups were inspected individually and bound to the candidate source SHA. Each PNG hash was checked against the actual render file. See the JSON companion for per-page hashes and report identities.",
        "",
        "Source proof and root content review are identified by path and SHA in the JSON companion. The previous oldbase QA is retained as historical context only and does not grant this candidate a PASS.",
        "",
        "The preserved handover DOCX/Markdown and 13 page PNGs were checked against their existing two reports and page 5 correction addendum. No handover rerender was performed.",
        "",
        "The previous baseline 086-102 QA report overwrite remains unrecoverable; the addendum was read as written and the lost report was not reconstructed. Two known temporary-helper loss/overwrite records are retained as a count from the root instruction; missing helper contents are not fabricated.",
        "",
        "Root visual notes retained: page 110 E05 is followed by two body lines; page 38 RESEARCH_CANDIDATE wraps readably; page 136 continuation-template header omission is informational when the text remains readable.",
    ]
    if errors:
        md_lines.extend(["", "Integrity findings:", ""])
        md_lines.extend(f"- {item}" for item in errors)
    md_text = "\n".join(md_lines) + "\n"

    OUTPUT_JSON.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_MD.write_text(md_text, encoding="utf-8")
    print(json.dumps({"status": status, "pages": master["page_row_count"], "png_hash_matches": master["png_sha256_matches"], "findings": len(errors), "outputs": [relative_or_absolute(OUTPUT_MD), relative_or_absolute(OUTPUT_JSON)]}, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
