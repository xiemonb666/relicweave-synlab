#!/usr/bin/env python3
"""One-shot read-only QA aggregation for the layout-final V1.47 candidate.

This helper must only be run after the root explicitly confirms all groups are
ready and has accepted the layout-final content review. It reads page QA reports, actual
rendered PNG bytes, source/review evidence, and the frozen handover artifacts.
It writes only LAYOUT_FINAL_QA_COVERAGE.md and .json beside this script, and
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
MASTER_DOCX = TASK_DIR / "fresh_merge_layout_final_candidate.docx"
BASE_MASTER_DOCX = TASK_DIR / "fresh_merge_final_candidate.docx"
MASTER_RENDER_DIR = TASK_DIR / "fresh_merge_layout_final_render"
LAYOUT_STATIC_PROOF_MD = TASK_DIR / "independent_layout_final.md"
LAYOUT_STATIC_PROOF_JSON = TASK_DIR / "independent_layout_final.json"
SEMANTIC_BASE_PROOF_MD = TASK_DIR / "independent_merged_static.md"
SEMANTIC_BASE_PROOF_JSON = TASK_DIR / "independent_merged_static.json"
OUTPUT_MD = TASK_DIR / "LAYOUT_FINAL_QA_COVERAGE.md"
OUTPUT_JSON = TASK_DIR / "LAYOUT_FINAL_QA_COVERAGE.json"

EXPECTED_MASTER_SHA256 = (
    "883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d"
)
EXPECTED_BASE_SHA256 = "70aa097680aa1920528ba4b6d9646821ac78b367618c0e9b8dbc36439fa38044"
EXPECTED_MASTER_BYTES = 786150
EXPECTED_BASE_BYTES = 786143
EXPECTED_STATIC_MD_SHA256 = "f175c95444430b6cad296bca29c43b5e86807da77a6260866d3eabbc14541b7e"
EXPECTED_STATIC_JSON_SHA256 = "4102d0446b5bb09113334e639e78e347c448c3566dcb58e52c51c4ec8d7013c6"
EXPECTED_SEMANTIC_MD_SHA256 = "636b8b2fc5bccfa673f13fe6032cd1061037f42bea355dd1be49d783bae4c16e"
EXPECTED_SEMANTIC_JSON_SHA256 = "ec8017b65c1f43d11981853aefc4b8ae398c9b4762214adc69ac55fd58814f03"
EXPECTED_MASTER_PAGES = 225
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
    (217, 225),
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
MERGED_REPORT = re.compile(r"^layout_master_(\d{3})_(\d{3})\.json$")


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
        errors.append(f"Missing layout-final candidate DOCX: {relative_or_absolute(master_docx)}")
        actual_master_sha = None
        master_identity = None
    else:
        actual_master_sha = sha256_file(master_docx)
        master_identity = file_identity(master_docx)
        if actual_master_sha.lower() != EXPECTED_MASTER_SHA256:
            errors.append(
                f"Layout-final candidate SHA mismatch: expected {EXPECTED_MASTER_SHA256}, got {actual_master_sha}"
            )
        if master_docx.stat().st_size != EXPECTED_MASTER_BYTES:
            errors.append(f"Layout-final candidate byte size mismatch: expected {EXPECTED_MASTER_BYTES}, got {master_docx.stat().st_size}")

    inventory = page_png_inventory(MASTER_RENDER_DIR, "layout-final candidate render", errors)
    expected_pages = set(range(1, EXPECTED_MASTER_PAGES + 1))
    if set(inventory) != expected_pages:
        errors.append(
            f"Layout-final PNG inventory must be exactly pages 1..{EXPECTED_MASTER_PAGES}; "
            f"missing={sorted(expected_pages - set(inventory))}, "
            f"extra={sorted(set(inventory) - expected_pages)}"
        )

    if not QA_DIR.is_dir():
        errors.append(f"Missing layout-final QA directory: {relative_or_absolute(QA_DIR)}")
        report_paths: list[Path] = []
    else:
        candidates = sorted(QA_DIR.glob("layout_master_*.json"), key=lambda p: p.name)
        report_paths = [path for path in candidates if MERGED_REPORT.fullmatch(path.name)]
        unexpected = [
            path.name for path in candidates
            if not MERGED_REPORT.fullmatch(path.name)
            and path.name != "layout_master_181_198.review_before_root_decision.json"
        ]
        if unexpected:
            errors.append(f"Unexpected layout QA JSON filenames: {unexpected}")

    by_range: dict[tuple[int, int], Path] = {}
    for path in report_paths:
        match = MERGED_REPORT.fullmatch(path.name)
        if not match:
            continue
        page_range = (int(match.group(1)), int(match.group(2)))
        if page_range in by_range:
            errors.append(f"Duplicate layout QA range {page_range}: {path.name}")
        by_range[page_range] = path
    if set(by_range) != expected_groups:
        errors.append(
            "Layout QA group set mismatch; "
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
        report = read_json(json_path, f"layout-final QA JSON {json_path.name}", errors)
        if report is None:
            continue
        if not md_path.is_file():
            errors.append(f"Missing paired layout-final QA Markdown: {relative_or_absolute(md_path)}")
            md_text = ""
        else:
            md_text = md_path.read_text(encoding="utf-8-sig")
        if not report_method_is_individual_original(report, md_text):
            errors.append(f"{json_path.name} lacks individual original-detail inspection evidence")
        bound_hashes = source_hashes(report)
        if EXPECTED_MASTER_SHA256 not in bound_hashes:
            errors.append(f"{json_path.name} does not bind to the layout-final candidate SHA")
        wrong_hashes = sorted(value for value in bound_hashes if value != EXPECTED_MASTER_SHA256)
        if wrong_hashes:
            errors.append(f"{json_path.name} has unexpected source SHA values: {wrong_hashes}")
        declared_issues = top_level_issue_count(report)
        counts = report.get("counts", {})
        if not isinstance(counts, dict):
            errors.append(f"{json_path.name} has no QA counts object")
            counts = {}
        issue_count = counts.get("issues")
        pass_count = counts.get("pass")
        if isinstance(issue_count, int) and not isinstance(issue_count, bool):
            declared_issues = max(declared_issues, issue_count)
        else:
            errors.append(f"{json_path.name} has no integer counts.issues")
        if declared_issues:
            errors.append(f"{json_path.name} declares {declared_issues} top-level issue(s)")
        if pass_count != last - first + 1:
            errors.append(f"{json_path.name} pass count does not equal its page range")
        report_range = report.get("range", {})
        if (
            not isinstance(report_range, dict)
            or report_range.get("start") != first
            or report_range.get("end") != last
            or report.get("source_page_count") != EXPECTED_MASTER_PAGES
        ):
            errors.append(f"{json_path.name} range/source page-count metadata does not match the frozen render")

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
            image_ref = first_value(row, ("png", "png_path", "file", "image"))
            png_name = Path(str(image_ref)).name if image_ref else ""
            image_match = PAGE_PNG.fullmatch(png_name)
            if not image_match or int(image_match.group(1)) != page:
                errors.append(f"{json_path.name} page {page} has an invalid PNG reference: {image_ref!r}")
                continue
            image_path = inventory.get(page)
            if image_path is None:
                errors.append(f"Missing layout-final page {page} PNG")
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
                errors.append(f"Layout-final page {page} dimensions are {image_meta['dimensions_px']}")
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
            f"Layout-final page rows do not cover pages 1..{EXPECTED_MASTER_PAGES} exactly once; "
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


def inspect_layout_static_proof(errors: list[str]) -> dict[str, Any]:
    proof_md = LAYOUT_STATIC_PROOF_MD
    proof_json = LAYOUT_STATIC_PROOF_JSON
    md_text = ""
    if not proof_md.is_file():
        errors.append(f"Missing independent layout static-proof Markdown: {relative_or_absolute(proof_md)}")
    else:
        md_text = proof_md.read_text(encoding="utf-8-sig")
        if sha256_file(proof_md).lower() != EXPECTED_STATIC_MD_SHA256:
            errors.append("Independent layout static-proof Markdown SHA mismatch")
    proof = read_json(proof_json, "independent layout static-proof JSON", errors) or {}
    if proof_json.is_file() and sha256_file(proof_json).lower() != EXPECTED_STATIC_JSON_SHA256:
        errors.append("Independent layout static-proof JSON SHA mismatch")

    base = proof.get("base", {})
    final = proof.get("final", {})
    if not isinstance(base, dict) or not isinstance(final, dict):
        errors.append("Independent layout static proof has malformed base/final identity records")
        base = base if isinstance(base, dict) else {}
        final = final if isinstance(final, dict) else {}
    if proof.get("status") != "LAYOUT_STATIC_PASS":
        errors.append("Independent layout static proof does not report LAYOUT_STATIC_PASS")
    if base.get("sha256", "").lower() != EXPECTED_BASE_SHA256 or base.get("bytes") != EXPECTED_BASE_BYTES:
        errors.append("Independent layout static proof does not bind the accepted 70aa base identity")
    if str(base.get("path", "")).casefold() != str(BASE_MASTER_DOCX).casefold():
        errors.append("Independent layout static proof base path does not name the pinned 70aa source DOCX")
    if not BASE_MASTER_DOCX.is_file():
        errors.append(f"Missing accepted 70aa base DOCX: {relative_or_absolute(BASE_MASTER_DOCX)}")
    elif (
        sha256_file(BASE_MASTER_DOCX).lower() != EXPECTED_BASE_SHA256
        or BASE_MASTER_DOCX.stat().st_size != EXPECTED_BASE_BYTES
    ):
        errors.append("Accepted 70aa base DOCX bytes do not match the static-proof identity")
    if final.get("sha256", "").lower() != EXPECTED_MASTER_SHA256 or final.get("bytes") != EXPECTED_MASTER_BYTES:
        errors.append("Independent layout static proof does not bind the frozen layout-final identity")
    if str(final.get("path", "")).casefold() != str(MASTER_DOCX).casefold():
        errors.append("Independent layout static proof final path does not name the pinned layout-final DOCX")
    if (
        "LAYOUT_STATIC_PASS" not in md_text
        or EXPECTED_MASTER_SHA256 not in md_text.lower()
        or EXPECTED_BASE_SHA256 not in md_text.lower()
    ):
        errors.append("Independent layout static-proof Markdown does not cite both pinned source SHAs")

    checks = proof.get("checks", {})
    if not isinstance(checks, dict):
        checks = {}
    required_checks = (
        "base_70aa_sha_matches_pin",
        "final_sha_matches_pin",
        "same_23_part_set_and_all_22_non_document_parts_exact",
        "all_relationship_parts_byte_identical",
        "all_18217_wt_tokens_exact_in_order",
        "all_8_status_paragraphs_exact",
        "all_553_bookmarks_and_113_internal_links_exact",
        "194_tables_and_only_target_row_5_to_4",
        "three_row_paragraphs_cloned_after_target_table",
        "cloned_paragraph_xml_exact_except_keep_flags",
        "keepNext_label_and_first_explanation_keepLines_all_three",
        "five_B13_reference_spacing_after_changes_100_to_20",
        "paragraph_C14N_diffs_are_only_five_refs_plus_three_relocated_clones",
        "all_other_body_C14N_identical",
    )
    failed_checks = [name for name in required_checks if checks.get(name) is not True]
    if failed_checks:
        errors.append(f"Independent layout static proof has failed/missing checks: {failed_checks}")

    integrity = proof.get("integrity", {})
    package = proof.get("package", {})
    delta = proof.get("layout_delta", {})
    if (
        integrity.get("base_wt_count") != 18217
        or integrity.get("final_wt_count") != 18217
        or integrity.get("base_concatenated_wt_sha256") != integrity.get("final_concatenated_wt_sha256")
    ):
        errors.append("Static-proof ordered-token counts/digests do not establish exact token preservation")
    status_rows = integrity.get("status_paragraphs", [])
    if len(status_rows) != 8 or not all(
        isinstance(row, dict)
        and row.get("exact") is True
        and row.get("base_count") == 1
        and row.get("final_count") == 1
        for row in status_rows
    ):
        errors.append("Static-proof status-paragraph evidence is incomplete or mismatched")
    if (
        integrity.get("base_bookmarks") != 553
        or integrity.get("final_bookmarks") != 553
        or integrity.get("base_internal_links") != 113
        or integrity.get("final_internal_links") != 113
        or integrity.get("duplicate_bookmark_names") is not False
        or integrity.get("dangling_anchors") != []
    ):
        errors.append("Static-proof bookmark/internal-link integrity evidence is incomplete or mismatched")
    if (
        package.get("base_parts") != 23
        or package.get("final_parts") != 23
        or package.get("changed_non_document_parts") != []
        or not isinstance(package.get("relationship_parts"), list)
        or len(package.get("relationship_parts", [])) != 3
    ):
        errors.append("Static-proof package/relationship evidence is incomplete or mismatched")
    reference_spacing = delta.get("B13_reference_spacing_after", {}).get("paragraphs", [])
    expected_diff_indices = [2402, 2403, 2404, 2405, 2406, 7287, 7288, 7289]
    changed_rows = delta.get("changed_table_row_counts", [])
    if (
        delta.get("table_index") != 185
        or delta.get("base_row_count") != 5
        or delta.get("final_row_count") != 4
        or delta.get("source_last_row_index") != 5
        or changed_rows != [{"table": 185, "base": 5, "final": 4}]
        or delta.get("paragraph_C14N_diff_indices") != expected_diff_indices
        or delta.get("expected_diff_indices") != expected_diff_indices
        or len(reference_spacing) != 5
        or [row.get("paragraph_index") for row in reference_spacing if isinstance(row, dict)] != [2402, 2403, 2404, 2405, 2406]
        or not all(
            isinstance(row, dict) and row.get("base_after") == "100" and row.get("final_after") == "20"
            for row in reference_spacing
        )
        or delta.get("body_C14N_equal_after_reversing_declared_layout_changes") is not True
    ):
        errors.append("Static-proof layout delta does not match the declared single-table and five-reference changes")

    return {
        "markdown": file_identity(proof_md) if proof_md.is_file() else None,
        "json": file_identity(proof_json) if proof_json.is_file() else None,
        "status": proof.get("status"),
        "base": base,
        "base_docx_actual": file_identity(BASE_MASTER_DOCX) if BASE_MASTER_DOCX.is_file() else None,
        "final": final,
        "required_checks_passed": len(required_checks) - len(failed_checks),
        "required_checks_expected": len(required_checks),
        "ordered_wt_tokens_base_and_final": [integrity.get("base_wt_count"), integrity.get("final_wt_count")],
        "status_paragraph_count": len(status_rows),
        "parts_base_and_final": [package.get("base_parts"), package.get("final_parts")],
        "layout_delta": {
            "table_index": delta.get("table_index"),
            "rows_base_to_final": [delta.get("base_row_count"), delta.get("final_row_count")],
            "reference_spacing_changes": len(reference_spacing),
            "body_c14n_equal_after_reversing_declared_layout_changes": delta.get("body_C14N_equal_after_reversing_declared_layout_changes"),
        },
    }


def inspect_accepted_semantic_base_proof(errors: list[str]) -> dict[str, Any]:
    md_path = SEMANTIC_BASE_PROOF_MD
    json_path = SEMANTIC_BASE_PROOF_JSON
    md_text = ""
    if not md_path.is_file():
        errors.append(f"Missing accepted semantic-base Markdown proof: {relative_or_absolute(md_path)}")
    else:
        md_text = md_path.read_text(encoding="utf-8-sig")
        if sha256_file(md_path).lower() != EXPECTED_SEMANTIC_MD_SHA256:
            errors.append("Accepted semantic-base Markdown proof SHA mismatch")
    proof = read_json(json_path, "accepted semantic-base static proof JSON", errors) or {}
    if json_path.is_file() and sha256_file(json_path).lower() != EXPECTED_SEMANTIC_JSON_SHA256:
        errors.append("Accepted semantic-base static proof JSON SHA mismatch")
    if proof.get("status") != "STATIC_PASS_WITH_REVIEWED_SCOPE_EXCEPTIONS":
        errors.append("Semantic base proof does not retain its reviewed-scope static PASS")
    source = proof.get("source_hashes_and_bytes", {}).get("candidate", {})
    if (
        source.get("sha256", "").lower() != EXPECTED_BASE_SHA256
        or source.get("bytes") != EXPECTED_BASE_BYTES
        or proof.get("hash_pins", {}).get("candidate_matches_final_proof") is not True
    ):
        errors.append("Semantic base proof does not bind the accepted 70aa candidate")
    checks = proof.get("checks", {})
    if not isinstance(checks, dict) or not checks or any(value is not True for value in checks.values()):
        errors.append("Semantic base proof has missing or non-PASS static checks")
    if "70aa097680aa1920528ba4b6d9646821ac78b367618c0e9b8dbc36439fa38044" not in md_text.lower():
        errors.append("Semantic base Markdown does not cite the accepted 70aa source SHA")
    package = proof.get("package", {})
    if package.get("parts") != 23 or package.get("changed_non_document_parts") != []:
        errors.append("Semantic base proof does not preserve its accepted package identity")

    return {
        "markdown": file_identity(md_path) if md_path.is_file() else None,
        "json": file_identity(json_path) if json_path.is_file() else None,
        "status": proof.get("status"),
        "accepted_candidate": source,
        "static_check_count": len(checks) if isinstance(checks, dict) else 0,
        "all_static_checks_pass": isinstance(checks, dict) and bool(checks) and all(value is True for value in checks.values()),
        "reviewed_scope_exceptions_retained": True,
        "root_acceptance": "inherited from explicit root content-review acceptance gate for the 70aa semantic base",
    }


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
    parser.add_argument("--final-qa-all-groups-ready", action="store_true", help="Required explicit confirmation that all 13 layout-final visual QA groups are ready.")
    parser.add_argument("--root-content-review-accepted", action="store_true", help="Required explicit root acceptance of the final candidate content review.")
    parser.add_argument("--root-layout-final-qa-go", action="store_true", help="Required separate explicit root GO to run the final layout QA aggregation.")
    args = parser.parse_args()

    if not args.final_qa_all_groups_ready:
        parser.error("wait for root's layout-final allgroupsready instruction before running this helper")
    if not args.root_content_review_accepted:
        parser.error("a final PASS requires root to explicitly accept the layout-final content review")
    if not args.root_layout_final_qa_go:
        parser.error("wait for root's separate layout-final QA GO before running this helper")
    if OUTPUT_MD.exists() or OUTPUT_JSON.exists():
        parser.error("coverage outputs already exist; preserve the frozen files and do not overwrite them")

    errors: list[str] = []

    master = inspect_master_groups(MASTER_DOCX, errors)
    layout_static_proof = inspect_layout_static_proof(errors)
    semantic_base_proof = inspect_accepted_semantic_base_proof(errors)
    decision_snapshot = {
        "markdown": QA_DIR / "layout_master_181_198.review_before_root_decision.md",
        "json": QA_DIR / "layout_master_181_198.review_before_root_decision.json",
    }
    for label, path in decision_snapshot.items():
        if not path.is_file():
            errors.append(f"Missing preserved pre-root-decision snapshot ({label}): {relative_or_absolute(path)}")
    root_content_review = {
        "accepted_by_root": True,
        "acceptance_basis": "Root's explicit root-content-review-accepted GO; accepted semantic qualification is inherited from the reviewed 70aa source proof.",
        "accepted_semantic_base_proof": semantic_base_proof,
        "root_independently_reviewed_pages": [68, 69, 219, 220, 183, 184, 191, 192],
        "continuation_decision": "The root accepted the complete natural continuation path in the 181-198 group after reviewing the retained pre-decision snapshot and final report.",
        "pre_root_decision_snapshot": {
            label: file_identity(path) if path.is_file() else None
            for label, path in decision_snapshot.items()
        },
    }
    handover = inspect_handover(errors)
    history = inspect_history(errors)
    combined_rendered_pages = master["render_png_count"] + handover["page_png_count"]
    page_coverage_ok = (
        master["render_png_count"] == EXPECTED_MASTER_PAGES
        and master["page_row_count"] == EXPECTED_MASTER_PAGES
        and master["unique_page_count"] == EXPECTED_MASTER_PAGES
        and master["png_sha256_matches"] == EXPECTED_MASTER_PAGES
        and master["clean_pass_pages"] == EXPECTED_MASTER_PAGES
        and handover["page_png_count"] == 13
        and handover["pages_covered"] == 13
        and handover["unique_pages"] == 13
        and handover["png_sha256_matches"] == 13
        and combined_rendered_pages == 238
    )
    if not page_coverage_ok:
        errors.append("Combined layout-final plus handover PNG/page coverage must be exactly 225 + 13 = 238")

    status = "PASS" if not errors else "BLOCKED_MISMATCHES"
    coverage: dict[str, Any] = {
        "schema": "v147_layout_final_qa_coverage.v1",
        "status": status,
        "layout_final_qa_pass": not errors,
        "aggregation_gates": {
            "root_confirmed_final_qa_all_groups_ready": True,
            "root_content_review_accepted": True,
            "root_separate_layout_final_qa_go": True,
            "oldbase_qa_used_for_new_master_acceptance": False,
        },
        "layout_final_candidate": master,
        "layout_static_proof": layout_static_proof,
        "root_content_review": root_content_review,
        "handover_qa_reused_without_rerender": handover,
        "combined_rendered_page_count": combined_rendered_pages,
        "combined_render_coverage": {
            "layout_final_pages": [1, EXPECTED_MASTER_PAGES],
            "handover_pages": [1, 13],
            "expected_total_png_pages": 238,
            "actual_total_png_pages": combined_rendered_pages,
            "no_missing_or_duplicate_pages_within_each_document": page_coverage_ok,
        },
        "preserved_history": history,
        "integrity_findings": errors,
        "scope_note": "One-shot read/hash aggregation only. No rendering, source edits, numerical work, CAD, tests, or Git writes.",
    }
    md_lines = [
        "# Layout-final visual QA coverage",
        "",
        f"**Status: `{status}`.** This report covers the frozen layout-final candidate only after all 13 visual QA groups were ready, root accepted the content review, and root gave the separate QA GO.",
        "",
        f"Layout-final candidate SHA-256: `{EXPECTED_MASTER_SHA256}`. Rendered pages: {master['page_row_count']}/{EXPECTED_MASTER_PAGES}; page PNG SHA matches: {master['png_sha256_matches']}; clean pass pages: {master['clean_pass_pages']}.",
        "",
        "Each page group was inspected individually and bound to the layout-final source SHA. Every page PNG hash was checked against the actual render file. See the JSON companion for per-page hashes and report identities.",
        "",
        "Semantic qualification is inherited from the reviewed 70aa base. The frozen independent layout static proof binds both source DOCX files and verifies all 18,217 ordered text tokens, eight status paragraphs, bookmarks/internal links, the 23-part package, and exactly the declared layout deltas. The proof and root content review identities are recorded in the JSON companion.",
        "",
        "The frozen handover DOCX/Markdown and 13 page PNGs were checked against their existing two reports and page 5 correction addendum. No handover rerender was performed.",
        "",
        "The previous baseline 086-102 QA report overwrite remains unrecoverable; its addendum is retained as written and the lost report is not reconstructed. Two known temporary-helper loss/overwrite records are retained by count only; missing helper contents are not fabricated.",
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
