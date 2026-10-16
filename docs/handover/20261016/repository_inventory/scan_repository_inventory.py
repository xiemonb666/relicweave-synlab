#!/usr/bin/env python3
"""Build a read-only handover inventory for the three ShardForge repositories.

The script reads Git path lists and file contents, then writes its three reports
beside itself. It never stages files or changes repository files. Hashing is
streamed and limited to two workers by default.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_WORKSPACE = SCRIPT_DIR.parents[3]
REPOSITORIES = ("vesselforge", "pgfrag", "relicweave-synlab")
REPORT_NAMES = {
    "candidates": "PROJECT_CODE_CANDIDATES.json",
    "local": "LOCAL_ONLY_ARTIFACTS.json",
    "summary": "SUMMARY.md",
}

SOURCE_SUFFIXES = {
    ".py", ".pyi", ".jl", ".c", ".h", ".cc", ".cpp", ".hpp", ".cxx",
    ".rs", ".go", ".java", ".kt", ".cs", ".fs", ".js", ".jsx", ".mjs",
    ".cjs", ".ts", ".tsx", ".vue", ".php", ".rb", ".sh", ".bash",
    ".ps1", ".psm1", ".bat", ".cmd", ".sql", ".r", ".m", ".f", ".f90",
}
CONFIG_SUFFIXES = {
    ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".properties",
    ".env", ".json", ".xml", ".lock", ".gradle", ".tf", ".tfvars",
}
DOC_EVIDENCE_SUFFIXES = {
    ".md", ".rst", ".txt", ".log", ".csv", ".tsv", ".xml", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".junit",
}
FROZEN_DATA_SUFFIXES = {".py", ".jl", ".toml", ".dat", ".msh"}
RAW_NUMERIC_SUFFIXES = {".npy", ".f64le"}
MEDIA_AND_MODEL_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff",
    ".heic", ".obj", ".ply", ".stl", ".step", ".stp", ".3mf", ".glb",
    ".gltf", ".iges", ".igs", ".brep", ".svg",
}
DEPENDENCY_RELEASE_SUFFIXES = {".dll", ".exe", ".whl"}
LARGE_GENERATED_SUFFIXES = {".json", ".npz", ".csv"}
RUNTIME_OR_VENDOR_PARTS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", ".nox", ".cache", ".mplconfig",
    ".matplotlib", "_temp_matplotlib", "site-packages", "dist-packages",
    "node_modules", "vendor", "vendors", "third_party", "third-party",
    "uv-cache", "build", "dist",
}

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("openai_or_generic_secret_token", re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("url_embedded_password", re.compile(r"[A-Za-z][A-Za-z0-9+.-]{0,31}://[^\s/:@]+:[^\s/@]+@")),
    (
        "credential_assignment_quoted",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|auth(?:orization)?|client[_-]?secret|"
            r"password|passwd|private[_-]?key|secret|token)\b\s*[:=]\s*"
            r"(?:Bearer\s+)?(?P<quote>[\"'])(?P<secret>[^\"'\r\n]{16,}?)(?P=quote)"
        ),
    ),
    (
        "credential_assignment_unquoted_config",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|auth(?:orization)?|client[_-]?secret|"
            r"password|passwd|private[_-]?key|secret|token)\b\s*[:=]\s*"
            r"(?:Bearer\s+)?(?P<secret>[A-Za-z0-9_./+=-]{24,})(?=\s*(?:[,;#}]|$))"
        ),
    ),
)
PLACEHOLDER_VALUES = {
    "your_api_key", "your_token", "your_password", "changeme", "change_me",
    "replace_me", "replace-with-your-token", "example", "dummy", "placeholder",
    "none", "null", "false", "true", "undefined", "redacted",
}
MAX_SECRET_FILE_BYTES = 2 * 1024 * 1024
MAX_SECRET_LINE_BYTES = 64 * 1024
MAX_SECRET_SCAN_TOTAL_BYTES = 128 * 1024 * 1024


def run_git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed in {repo.name}: {detail}")
    return result.stdout


def nul_paths(raw: bytes) -> set[str]:
    return {os.fsdecode(item) for item in raw.split(b"\0") if item}


def normalized_relative(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def is_inside_inventory(rel: str) -> bool:
    normalized = normalized_relative(rel).strip("/").lower()
    return normalized == "docs/handover/20261016/repository_inventory" or normalized.startswith(
        "docs/handover/20261016/repository_inventory/"
    )


def path_parts(rel: str) -> tuple[str, ...]:
    return tuple(part.lower() for part in normalized_relative(rel).split("/") if part)


def is_runtime_or_vendor(rel: str) -> bool:
    return any(part in RUNTIME_OR_VENDOR_PARTS for part in path_parts(rel))


def is_data_path(rel: str) -> bool:
    return "data" in path_parts(rel)


def file_suffix(rel: str) -> str:
    return Path(rel).suffix.lower()


def classify(repo: str, rel: str, size: int, threshold: int) -> dict[str, str]:
    """Return recommendation and reason; extension and location rules are explicit."""
    suffix = file_suffix(rel)
    parts = path_parts(rel)
    if is_runtime_or_vendor(rel):
        return {
            "recommendation": "local_only",
            "category": "runtime_cache_or_vendor_dependency",
            "reason": "Runtime cache, environment, generated build output, or third-party/vendor path.",
        }
    if suffix in DEPENDENCY_RELEASE_SUFFIXES:
        return {
            "recommendation": "local_only",
            "category": "dependency_release_artifact",
            "reason": "DLL, EXE, and wheel files are dependency release artifacts, not project source.",
        }
    if suffix in RAW_NUMERIC_SUFFIXES:
        return {
            "recommendation": "local_only",
            "category": "raw_numeric_or_trajectory_data",
            "reason": "Raw NumPy or f64le data is a generated/local dataset and should stay local.",
        }
    if suffix == ".npz":
        if size > threshold:
            return {
                "recommendation": "local_only",
                "category": "large_generated_dataset",
                "reason": "NPZ archive exceeds the 10 MiB review threshold; retain locally.",
            }
        return {
            "recommendation": "review_required",
            "category": "small_fixture_or_dataset",
            "reason": "Small NPZ may be a required fixture; root must decide whether to retain or upload it.",
        }
    if is_data_path(rel) and suffix in FROZEN_DATA_SUFFIXES:
        reason = "Preserve frozen project inputs and scripts under data/, including .py, .jl, .toml, .dat, and .msh."
        if suffix == ".msh":
            reason += " Root should verify provenance/license if this mesh came from an external source."
        return {
            "recommendation": "candidate",
            "category": "frozen_project_input_or_script",
            "reason": reason,
        }
    if any(part in {"fixture", "fixtures"} for part in parts) and size <= threshold and suffix not in SOURCE_SUFFIXES | CONFIG_SUFFIXES:
        return {
            "recommendation": "review_required",
            "category": "small_fixture",
            "reason": "Small fixture may be required by tests; root should decide whether to upload it.",
        }
    generated_area = any(part in {"data", "experiments", "results", "runs", "outputs", "artifacts", "rawlogs", "tmp"} for part in parts)
    if suffix in LARGE_GENERATED_SUFFIXES and size > threshold and generated_area:
        return {
            "recommendation": "local_only",
            "category": "large_generated_text_or_dataset",
            "reason": f"Generated {suffix[1:].upper()} exceeds the 10 MiB review threshold; retain locally.",
        }
    if suffix in LARGE_GENERATED_SUFFIXES and size > threshold:
        return {
            "recommendation": "review_required",
            "category": "large_text_or_dataset",
            "reason": f"Large {suffix[1:].upper()} is outside a known generated-data path; root should review before upload.",
        }
    if suffix in MEDIA_AND_MODEL_SUFFIXES:
        return {
            "recommendation": "review_required",
            "category": "model_photo_or_visual_resource",
            "reason": "Root should decide whether this model/photo/visual asset is required and verify its license or provenance.",
        }
    if suffix in SOURCE_SUFFIXES:
        return {
            "recommendation": "candidate",
            "category": "project_source_code",
            "reason": "Source code or script; preserve for the code handover.",
        }
    if suffix in CONFIG_SUFFIXES:
        return {
            "recommendation": "candidate",
            "category": "project_configuration",
            "reason": "Project configuration or lock file; preserve for the code handover.",
        }
    if suffix in DOC_EVIDENCE_SUFFIXES and size <= threshold:
        return {
            "recommendation": "candidate",
            "category": "documentation_or_small_evidence",
            "reason": "Documentation or small text evidence under the 10 MiB threshold.",
        }
    return {
        "recommendation": "local_only",
        "category": "other_generated_or_binary_artifact",
        "reason": "Not recognized as project code, configuration, documentation, or small evidence; root may reclassify if required.",
    }


def file_digest(record: dict[str, Any]) -> tuple[str, str | None, str | None]:
    path = Path(record["absolute_path"])
    try:
        if path.is_symlink():
            raw = os.fsencode(os.readlink(path))
            return record["key"], hashlib.sha256(raw).hexdigest(), None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        return record["key"], digest.hexdigest(), None
    except OSError as exc:
        return record["key"], None, type(exc).__name__


def is_source_or_config_for_secret_scan(rel: str) -> bool:
    suffix = file_suffix(rel)
    basename = Path(rel).name.lower()
    return suffix in SOURCE_SUFFIXES | CONFIG_SUFFIXES or basename in {"dockerfile", "makefile"}


def is_placeholder(value: str) -> bool:
    cleaned = value.strip().strip("\"'`;,.)]").strip().lower()
    if cleaned in PLACEHOLDER_VALUES:
        return True
    if any(marker in cleaned for marker in ("${", "<", ">", "****", "...", "your-", "example-")):
        return True
    return False


def scan_credentials(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return path/rule/line only; never serialize matched source text."""
    found: set[tuple[str, str, int]] = set()
    stats = {
        "eligible_files": 0,
        "scanned_files": 0,
        "bytes_scanned": 0,
        "skipped_file_size_limit": 0,
        "skipped_total_budget": 0,
        "skipped_long_lines": 0,
        "skipped_binary_files": 0,
        "read_errors": 0,
    }
    for record in records:
        rel = record["path"]
        if is_runtime_or_vendor(rel) or not is_source_or_config_for_secret_scan(rel):
            continue
        stats["eligible_files"] += 1
        if record["size_bytes"] is not None and record["size_bytes"] > MAX_SECRET_FILE_BYTES:
            stats["skipped_file_size_limit"] += 1
            continue
        remaining_budget = MAX_SECRET_SCAN_TOTAL_BYTES - stats["bytes_scanned"]
        if remaining_budget <= 0:
            stats["skipped_total_budget"] += 1
            continue
        file_budget = min(MAX_SECRET_FILE_BYTES, remaining_budget)
        try:
            stream = Path(record["absolute_path"]).open("rb")
        except OSError:
            stats["read_errors"] += 1
            continue
        stats["scanned_files"] += 1
        line_number = 0
        bytes_read = 0
        try:
            with stream:
                while True:
                    remaining = file_budget - bytes_read
                    if remaining <= 0:
                        break
                    raw_line = stream.readline(min(MAX_SECRET_LINE_BYTES + 1, remaining + 1))
                    if not raw_line:
                        break
                    bytes_read += len(raw_line)
                    stats["bytes_scanned"] += len(raw_line)
                    if b"\0" in raw_line:
                        stats["skipped_binary_files"] += 1
                        break
                    if len(raw_line) > MAX_SECRET_LINE_BYTES or (
                        len(raw_line) == MAX_SECRET_LINE_BYTES and not raw_line.endswith(b"\n")
                    ):
                        stats["skipped_long_lines"] += 1
                        # Consume the rest of this line in bounded chunks. The file
                        # size cap above bounds total work and memory stays bounded.
                        while raw_line and not raw_line.endswith(b"\n"):
                            remaining = file_budget - bytes_read
                            if remaining <= 0:
                                break
                            raw_line = stream.readline(min(MAX_SECRET_LINE_BYTES + 1, remaining + 1))
                            bytes_read += len(raw_line)
                            stats["bytes_scanned"] += len(raw_line)
                        line_number += 1
                        if bytes_read >= file_budget:
                            break
                        continue
                    line_number += 1
                    line = raw_line.decode("utf-8", errors="replace")
                    for rule, pattern in SECRET_PATTERNS:
                        if rule == "credential_assignment_unquoted_config" and file_suffix(rel) not in CONFIG_SUFFIXES:
                            continue
                        for match in pattern.finditer(line):
                            if rule.startswith("credential_assignment_"):
                                value = match.group("secret")
                                if is_placeholder(value):
                                    continue
                                # Avoid reporting common variable references and test sentinels.
                                if re.fullmatch(r"(?i)(?:os\.environ(?:\.get)?|process\.env|env)\([^)]*\)", value):
                                    continue
                            found.add((f"{record['repo']}/{record['path']}", rule, line_number))
        except OSError:
            stats["read_errors"] += 1
    return (
        [{"path": path, "rule": rule, "line": line} for path, rule, line in sorted(found)],
        stats,
    )


def add_walked_files(repo_root: Path, rel_root: str, paths: set[str]) -> int:
    walk_root = repo_root / Path(rel_root)
    if not walk_root.is_dir():
        return 0
    before = len(paths)
    for current, dirs, files in os.walk(walk_root, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d.lower() != ".git")
        for name in files:
            absolute = Path(current) / name
            rel = normalized_relative(absolute.relative_to(repo_root))
            if not is_inside_inventory(rel):
                paths.add(rel)
    return len(paths) - before


def inventory_repo(repo_root: Path, repo: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tracked = nul_paths(run_git(repo_root, "ls-files", "-z"))
    modified = nul_paths(run_git(repo_root, "ls-files", "--modified", "-z"))
    staged = nul_paths(run_git(repo_root, "diff", "--cached", "--name-only", "-z"))
    untracked = nul_paths(run_git(repo_root, "ls-files", "--others", "--exclude-standard", "-z"))
    paths = set(tracked) | set(untracked)
    explicitly_walked: set[str] = set()

    # Git ignore rules commonly hide the PG fragment histories; include the full
    # data tree and the named third-party matplotlib runtime cache for review.
    extra_walks: list[str] = []
    if repo == "pgfrag":
        extra_walks.extend(("data", "experiments/bowl_independent_audit_20261015/_temp_matplotlib"))
    for rel_root in extra_walks:
        before = set(paths)
        add_walked_files(repo_root, rel_root, paths)
        explicitly_walked.update(paths - before)

    records: list[dict[str, Any]] = []
    path_sources: dict[str, str] = {}
    for rel in paths:
        if is_inside_inventory(rel):
            continue
        if rel in tracked:
            source = "tracked_modified" if rel in modified or rel in staged else "tracked"
        elif rel in untracked:
            source = "git_untracked"
        else:
            source = "explicit_walk_ignored_or_unlisted"
        path_sources[rel] = source
        absolute = repo_root / Path(rel)
        try:
            stat = absolute.lstat()
            size = stat.st_size
            is_link = absolute.is_symlink()
        except OSError as exc:
            size = None
            is_link = False
            stat_error = type(exc).__name__
        else:
            stat_error = None
        if size is None:
            classification = {
                "recommendation": "local_only",
                "category": "unreadable_path_metadata",
                "reason": f"Path metadata could not be read ({stat_error}); inspect manually.",
            }
        else:
            classification = classify(repo, rel, size, 10 * 1024 * 1024)
        record = {
            "repo": repo,
            "path": normalized_relative(rel),
            "git_state": source,
            "tracked_modified": rel in modified or rel in staged,
            "size_bytes": size,
            "is_symlink": is_link,
            "sha256": None,
            "hash_error": None,
            "hash_status": "pending",
            "classification": classification,
            "absolute_path": str(absolute),
            "key": f"{repo}\0{rel}",
        }
        records.append(record)

    records.sort(key=lambda item: (item["path"].casefold(), item["path"]))
    metadata = {
        "repo": repo,
        "root": str(repo_root),
        "head": run_git(repo_root, "rev-parse", "HEAD").decode("ascii", errors="replace").strip(),
        "branch": run_git(repo_root, "branch", "--show-current").decode("utf-8", errors="replace").strip(),
        "tracked_count": len(tracked),
        "tracked_modified_count": len(modified),
        "staged_count": len(staged),
        "untracked_visible_count": len(untracked),
        "explicit_walk_count": len(explicitly_walked),
        "files_in_inventory": len(records),
        "walk_roots": extra_walks,
    }
    return records, metadata


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "repo": record["repo"],
        "path": record["path"],
        "git_state": record["git_state"],
        "tracked_modified": record["tracked_modified"],
        "size_bytes": record["size_bytes"],
        "sha256": record["sha256"],
        "hash_status": record["hash_status"],
        "hash_error": record["hash_error"],
        "category": record["classification"]["category"],
        "reason": record["classification"]["reason"],
        "recommendation": record["classification"]["recommendation"],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def markdown_summary(
    workspace: Path,
    repo_metadata: list[dict[str, Any]],
    records: list[dict[str, Any]],
    credential_findings: list[dict[str, Any]],
    credential_scan_stats: dict[str, int],
    hash_failures: list[dict[str, str]],
    threshold: int,
    workers: int,
) -> str:
    recommendations = Counter(r["classification"]["recommendation"] for r in records)
    categories_by_repo: dict[str, Counter[str]] = defaultdict(Counter)
    bytes_by_repo: Counter[str] = Counter()
    candidate_bytes = 0
    local_bytes = 0
    review_bytes = 0
    for record in records:
        rec = record["classification"]["recommendation"]
        categories_by_repo[record["repo"]][rec] += 1
        size = record["size_bytes"] or 0
        bytes_by_repo[record["repo"]] += size
        if rec == "candidate":
            candidate_bytes += size
        elif rec == "local_only":
            local_bytes += size
        else:
            review_bytes += size

    lines = [
        "# Repository Inventory Summary",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Workspace: `{workspace}`",
        "",
        "This is a read-only inventory for `vesselforge`, `pgfrag`, and `relicweave-synlab`. The script used `git ls-files -z`, `git ls-files --modified -z`, and `git ls-files --others --exclude-standard -z`; it also walked all of `pgfrag/data/` and `pgfrag/experiments/bowl_independent_audit_20261015/_temp_matplotlib/` so ignored histories and runtime cache files are represented. It does not stage, commit, push, or edit repository files.",
        "",
        f"It hashed {sum(1 for record in records if record['hash_status'] == 'hashed'):,} of {len(records):,} inventoried files using SHA-256 with at most {workers} workers and 8 MiB read blocks. The classification threshold is {threshold // (1024 * 1024)} MiB. All tracked files marked modified/staged and visible untracked files were hashed; every file in PG `data/` and every excluded file over the threshold was hashed. The named `_temp_matplotlib/` tree was inventoried as a runtime cache. Unchanged tracked files outside those rules show `sha256: null` with `hash_status: unchanged_tracked_not_hashed`.",
        "",
        "## Repository state",
        "",
        "| Repository | Branch | HEAD | Tracked | Modified tracked | Staged | Visible untracked | Extra walked | Inventoried | Candidate | Local only | Review required | Total bytes |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for meta in repo_metadata:
        c = categories_by_repo[meta["repo"]]
        lines.append(
            f"| {meta['repo']} | `{meta['branch'] or '(detached)'}` | `{meta['head']}` | "
            f"{meta['tracked_count']:,} | {meta['tracked_modified_count']:,} | {meta['staged_count']:,} | "
            f"{meta['untracked_visible_count']:,} | {meta['explicit_walk_count']:,} | "
            f"{meta['files_in_inventory']:,} | {c['candidate']:,} | {c['local_only']:,} | "
            f"{c['review_required']:,} | {bytes_by_repo[meta['repo']]:,} |"
        )
    lines.extend([
        "",
        f"Across all repositories: {recommendations['candidate']:,} candidate files ({candidate_bytes:,} bytes), {recommendations['local_only']:,} local-only files ({local_bytes:,} bytes), and {recommendations['review_required']:,} review-required files ({review_bytes:,} bytes).",
        "",
        "## Classification guidance",
        "",
        "- Candidate files include project code, configuration, documentation, and small textual evidence. Project-owned frozen inputs under `data/` with suffixes `.py`, `.jl`, `.toml`, `.dat`, or `.msh` are explicitly preserved as candidates; third-party `vendor/` and runtime/cache trees remain local-only.",
        "- Raw `.npy` and `.f64le` histories, NPZ archives over 10 MiB, and generated JSON/CSV/NPZ over 10 MiB under data/experiment/result paths are recommended local-only. Hashes are streamed, so the large PG datasets do not need to be loaded into memory.",
        "- `.dll`, `.exe`, and `.whl` are classified as dependency release artifacts. Runtime caches, virtual environments, `__pycache__`, `site-packages`, vendor trees, build output, and `_temp_matplotlib` are excluded from project code candidates.",
        "- Photo, image, and geometry resources plus small NPZ fixtures are marked `review_required`; root must decide whether each is needed and verify any license/provenance before upload.",
        "- Paths under repository roots were inventoried from tracked and visible untracked Git paths, with the two PG-specific full walks listed above. Other ignored paths outside those walks are not enumerated.",
        "- This report is only a recommendation manifest. It does not stage files; final staging remains with the root agent.",
        "",
        "## Suggested local-only patterns",
        "",
        "Review/apply only after checking project-specific inputs: `**/__pycache__/`, `**/.venv/`, `**/venv/`, `**/site-packages/`, `**/node_modules/`, `**/vendor/`, `**/third_party/`, `**/_temp_matplotlib/`, `**/.pytest_cache/`, `**/.mypy_cache/`, `**/.ruff_cache/`, `**/.mplconfig/`, `**/build/`, `**/dist/`, `**/*.npy`, `**/*.f64le`, generated `**/*.npz`, generated `**/*.json` over 10 MiB, generated `**/*.csv` over 10 MiB, `**/*.dll`, `**/*.exe`, and `**/*.whl`. Keep the data-directory `.py`/`.jl`/`.toml`/`.dat`/`.msh` frozen inputs visible for root review.",
        "",
        "## Credential scan",
        "",
        f"The source/config scan reports only file path, detector rule, and line number. It never writes matched content to either manifest or the console. It checked {credential_scan_stats['scanned_files']:,} of {credential_scan_stats['eligible_files']:,} eligible files and read {credential_scan_stats['bytes_scanned']:,} bytes; it skipped {credential_scan_stats['skipped_file_size_limit']:,} files over 2 MiB, {credential_scan_stats['skipped_total_budget']:,} files after the 128 MiB total scan budget, {credential_scan_stats['skipped_long_lines']:,} lines over 64 KiB, {credential_scan_stats['skipped_binary_files']:,} binary files, and {credential_scan_stats['read_errors']:,} files with read errors. Runtime/vendor paths are excluded.",
        "",
    ])
    if credential_findings:
        lines.append("| Path | Rule | Line |")
        lines.append("|---|---|---:|")
        for item in credential_findings:
            lines.append(f"| `{item['path']}` | `{item['rule']}` | {item['line']} |")
    else:
        lines.append("No likely credential patterns were found in the scanned source/config files.")
    lines.extend(["", "## Hash errors", ""])
    if hash_failures:
        lines.append("Some paths could not be hashed; only the path and exception type are shown.")
        lines.append("")
        lines.append("| Path | Error |")
        lines.append("|---|---|")
        for item in hash_failures:
            lines.append(f"| `{item['path']}` | `{item['error']}` |")
    else:
        lines.append("No hashing errors.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-root", type=Path, default=DEFAULT_WORKSPACE,
        help="Workspace containing the three repositories (default: inferred from this script).",
    )
    parser.add_argument("--workers", type=int, default=2, help="Maximum parallel SHA-256 workers (default: 2).")
    parser.add_argument("--threshold-mib", type=int, default=10, help="Large generated file threshold in MiB (default: 10).")
    args = parser.parse_args()
    if not 1 <= args.workers <= 2:
        parser.error("--workers must be 1 or 2")
    if args.threshold_mib <= 0:
        parser.error("--threshold-mib must be positive")

    workspace = args.workspace_root.resolve()
    threshold = args.threshold_mib * 1024 * 1024
    all_records: list[dict[str, Any]] = []
    repo_metadata: list[dict[str, Any]] = []
    for repo in REPOSITORIES:
        repo_root = workspace / repo
        if not repo_root.is_dir():
            raise SystemExit(f"Repository directory missing: {repo_root}")
        records, metadata = inventory_repo(repo_root, repo)
        all_records.extend(records)
        repo_metadata.append(metadata)

    # Hash each inventoried file in a bounded worker pool, streaming 8 MiB blocks.
    records_by_key = {record["key"]: record for record in all_records}
    hash_targets: list[dict[str, Any]] = []
    for record in all_records:
        recommendation = record["classification"]["recommendation"]
        needs_hash = (
            record["git_state"] != "tracked"
            or record["tracked_modified"]
            or (record["repo"] == "pgfrag" and is_data_path(record["path"]))
            or (
                record["size_bytes"] is not None
                and record["size_bytes"] > threshold
                and recommendation != "candidate"
            )
        )
        if needs_hash:
            hash_targets.append(record)
        else:
            record["hash_status"] = "unchanged_tracked_not_hashed"

    completed_hashes = 0
    progress_interval = max(100, len(hash_targets) // 20 or 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(file_digest, record) for record in hash_targets]
        for future in concurrent.futures.as_completed(futures):
            key, digest, error = future.result()
            record = records_by_key[key]
            record["sha256"] = digest
            record["hash_error"] = error
            record["hash_status"] = "hash_failed" if error else "hashed"
            completed_hashes += 1
            if completed_hashes % progress_interval == 0 or completed_hashes == len(hash_targets):
                print(f"Hashed {completed_hashes:,}/{len(hash_targets):,} selected files.", file=sys.stderr, flush=True)

    # Exclude the report directory itself above, including the script and reports,
    # so no manifest contains its own digest or grows on repeated runs.
    credential_findings, credential_scan_stats = scan_credentials(all_records)
    candidates = [public_record(r) for r in all_records if r["classification"]["recommendation"] == "candidate"]
    local = [public_record(r) for r in all_records if r["classification"]["recommendation"] != "candidate"]
    hash_failures = [
        {"path": f"{r['repo']}/{r['path']}", "error": r["hash_error"] or "unknown"}
        for r in all_records if r["hash_status"] == "hash_failed"
    ]

    SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(SCRIPT_DIR / REPORT_NAMES["candidates"], {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workspace_root": str(workspace),
        "classification": "candidate",
        "files": candidates,
    })
    write_json(SCRIPT_DIR / REPORT_NAMES["local"], {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workspace_root": str(workspace),
        "classification": "local_only_or_review_required",
        "files": local,
    })
    summary = markdown_summary(
        workspace, repo_metadata, all_records, credential_findings,
        credential_scan_stats, hash_failures, threshold, args.workers,
    )
    (SCRIPT_DIR / REPORT_NAMES["summary"]).write_text(summary, encoding="utf-8")

    # Console output is deliberately aggregate-only; it cannot expose secret text.
    print(
        f"Inventory complete: {len(candidates)} candidates, {len(local)} local/review files, "
        f"{completed_hashes} hashes, {len(credential_findings)} credential-rule hits, {len(hash_failures)} hash errors."
    )
    print(f"Reports: {SCRIPT_DIR}")
    return 0 if not hash_failures else 2


if __name__ == "__main__":
    sys.exit(main())
