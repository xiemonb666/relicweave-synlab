#!/usr/bin/env python3
"""Plan or explicitly stage handover files in the three ShardForge repositories.

The default invocation is read-only.  Pass ``--stage`` only after reviewing the
plan to stage all tracked changes with ``git add -u`` and the selected
non-ignored new files by literal NUL-delimited pathspecs.  This utility never
commits, pushes, force-adds ignored paths, or removes local data.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPOSITORIES = ("vesselforge", "pgfrag", "relicweave-synlab")
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024
LARGE_TRACKED_WARNING_BYTES = 95 * 1024 * 1024

# These are exact suffix checks.  Binary/runtime exclusions below are separate
# and take precedence, so a same-named file in an excluded dependency payload
# is never treated as project source.
SOURCE_CODE_CONFIG_SUFFIXES = frozenset(
    {
        ".py",
        ".jl",
        ".ps1",
        ".sh",
        ".bat",
        ".cmd",
        ".toml",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".conf",
        ".json",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".html",
        ".htm",
        ".css",
        ".xml",
        ".sql",
        ".ipynb",
    }
)
SOURCE_DOCUMENT_SUFFIXES = frozenset({".md", ".rst", ".txt"})
SOURCE_SUFFIXES = SOURCE_CODE_CONFIG_SUFFIXES | SOURCE_DOCUMENT_SUFFIXES
REQUIRED_SOURCE_SUFFIXES = (".py", ".jl", ".ps1", ".sh", ".toml", ".yaml", ".yml", ".json")

RAW_ARRAY_SUFFIXES = frozenset({".npy", ".f64le", ".i32le"})
DEPENDENCY_BINARY_SUFFIXES = frozenset({".dll", ".exe", ".whl", ".pyd", ".so"})
RUNTIME_DIRECTORY_NAMES = frozenset(
    {
        "_temp_matplotlib",
        ".mplconfig",
        ".venv",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        "sdk",
        "depot",
        "extract",
    }
)
EVIDENCE_DIRECTORY_NAMES = frozenset(
    {
        "data",
        "output",
        "outputs",
        "run",
        "runs",
        "report",
        "reports",
        "log",
        "logs",
        "receipt",
        "receipts",
        "capture",
        "captures",
        "validation",
        "previews",
        "evidence",
        "native_raw",
        "mesh_arrays",
    }
)
CONFIG_DIRECTORY_NAMES = frozenset(
    {"config", "configs", "settings", "schema", "schemas", "profiles", "presets"}
)
CONFIG_JSON_NAMES = frozenset({"package.json", "tsconfig.json", "jsconfig.json"})


class PlanError(RuntimeError):
    """A repository could not be inspected safely."""


def git(repo: Path, *args: str, check: bool = True) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode:
        detail = os.fsdecode(completed.stderr).strip()
        raise PlanError(f"git {' '.join(args)} failed in {repo}: {detail}")
    return completed.stdout


def nul_paths(data: bytes) -> list[str]:
    return [os.fsdecode(item) for item in data.split(b"\0") if item]


def file_size(repo: Path, relative_path: str) -> int:
    path = repo / Path(relative_path)
    try:
        return path.lstat().st_size
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise PlanError(f"cannot read file size for {relative_path!r} in {repo}: {exc}") from exc


def excluded_runtime_directory(relative_path: str) -> str | None:
    # The final component is a file name.  In particular, a project script
    # named ``extract_*.py`` must not be mistaken for an extraction directory.
    parts = [part.casefold() for part in Path(relative_path).parts[:-1]]
    for part in parts:
        if part in RUNTIME_DIRECTORY_NAMES:
            return part
        if part.startswith("extract_") or part.endswith("_extract") or part.endswith("_extracts"):
            return part
    return None


def is_config_json(relative_path: str) -> bool:
    path = Path(relative_path)
    if path.name.casefold() in CONFIG_JSON_NAMES:
        return True
    return any(part.casefold() in CONFIG_DIRECTORY_NAMES for part in path.parts[:-1])


def is_generated_evidence_path(relative_path: str) -> bool:
    parts = [part.casefold() for part in Path(relative_path).parts[:-1]]
    if any(part in EVIDENCE_DIRECTORY_NAMES for part in parts):
        return True
    return any(
        part.startswith(("run", "output", "capture", "receipt", "report", "log"))
        for part in parts
    )


def classify_new_file(relative_path: str, size_bytes: int) -> dict[str, Any]:
    suffix = Path(relative_path).suffix.casefold()
    source = suffix in SOURCE_SUFFIXES

    runtime_dir = excluded_runtime_directory(relative_path)
    if runtime_dir:
        return {
            "selected": False,
            "reason": f"runtime_or_dependency_directory:{runtime_dir}",
            "source": source,
        }
    if suffix in RAW_ARRAY_SUFFIXES:
        return {"selected": False, "reason": f"raw_array_format:{suffix}", "source": False}
    if suffix in DEPENDENCY_BINARY_SUFFIXES:
        return {"selected": False, "reason": f"executable_dependency:{suffix}", "source": False}

    if size_bytes > MAX_EVIDENCE_BYTES:
        if suffix == ".json" and not is_config_json(relative_path):
            return {"selected": False, "reason": "generated_json_evidence_over_10_mib", "source": True}
        if is_generated_evidence_path(relative_path) and suffix == ".txt":
            return {
                "selected": False,
                "reason": "generated_text_evidence_over_10_mib",
                "source": True,
            }
        if suffix in SOURCE_CODE_CONFIG_SUFFIXES or suffix in SOURCE_DOCUMENT_SUFFIXES:
            return {
                "selected": True,
                "reason": "source_text_over_10_mib_review_required",
                "source": True,
                "error": "source_text_over_10_mib",
            }
        return {"selected": False, "reason": "generated_evidence_over_10_mib", "source": False}

    return {"selected": True, "reason": "non_ignored_project_file_under_10_mib", "source": source}


def verify_repo(repo: Path, workspace: Path) -> tuple[str, str]:
    if not repo.is_dir():
        raise PlanError(f"required repository directory is missing: {repo}")
    root = Path(os.fsdecode(git(repo, "rev-parse", "--show-toplevel")).strip()).resolve()
    if root != repo.resolve():
        raise PlanError(f"expected {repo} to be a standalone Git repository; Git root is {root}")
    branch = os.fsdecode(git(repo, "branch", "--show-current")).strip() or "(detached HEAD)"
    head = os.fsdecode(git(repo, "rev-parse", "--short", "HEAD")).strip()
    try:
        root.relative_to(workspace)
    except ValueError as exc:
        raise PlanError(f"repository root escapes the workspace: {root}") from exc
    return branch, head


def plan_repo(repo: Path, workspace: Path) -> dict[str, Any]:
    branch, head = verify_repo(repo, workspace)
    tracked_paths = sorted(set(nul_paths(git(repo, "diff", "--name-only", "--no-renames", "-z", "HEAD", "--"))))
    untracked_paths = sorted(set(nul_paths(git(repo, "ls-files", "--others", "--exclude-standard", "-z"))))
    unmerged_records = git(repo, "ls-files", "-u", "-z").split(b"\0")
    conflicts = sorted(
        {
            os.fsdecode(record.partition(b"\t")[2])
            for record in unmerged_records
            if record and b"\t" in record
        }
    )

    tracked_changes: list[dict[str, Any]] = []
    tracked_source_count = 0
    large_tracked: list[dict[str, Any]] = []
    for relative_path in tracked_paths:
        size_bytes = file_size(repo, relative_path)
        suffix = Path(relative_path).suffix.casefold()
        is_source = suffix in SOURCE_SUFFIXES
        tracked_source_count += int(is_source)
        row = {
            "path": relative_path,
            "size_bytes": size_bytes,
            "source": is_source,
            "reason": "tracked_change_always_staged_by_git_add_u",
        }
        tracked_changes.append(row)
        if size_bytes > LARGE_TRACKED_WARNING_BYTES:
            large_tracked.append(row.copy())

    selected_new: list[dict[str, Any]] = []
    excluded_new: list[dict[str, Any]] = []
    source_suffix_counts: dict[str, Counter[str]] = defaultdict(Counter)
    errors: list[dict[str, Any]] = []
    for relative_path in untracked_paths:
        size_bytes = file_size(repo, relative_path)
        classification = classify_new_file(relative_path, size_bytes)
        row: dict[str, Any] = {
            "path": relative_path,
            "size_bytes": size_bytes,
            "reason": classification["reason"],
            "source": bool(classification["source"]),
        }
        suffix = Path(relative_path).suffix.casefold() or "(none)"
        if row["source"]:
            counts = source_suffix_counts[suffix]
            counts["seen"] += 1
            counts["bytes_seen"] += size_bytes
            counts["selected" if classification["selected"] else "excluded"] += 1
            counts["bytes_selected" if classification["selected"] else "bytes_excluded"] += size_bytes
        if classification["selected"]:
            selected_new.append(row)
        else:
            excluded_new.append(row)
        if classification.get("error"):
            errors.append(
                {
                    "code": classification["error"],
                    "path": relative_path,
                    "size_bytes": size_bytes,
                    "message": "Source text is retained regardless of size; review before --stage.",
                }
            )

    excluded_by_reason: dict[str, dict[str, int]] = {}
    for row in excluded_new:
        item = excluded_by_reason.setdefault(row["reason"], {"count": 0, "bytes": 0})
        item["count"] += 1
        item["bytes"] += row["size_bytes"]

    source_coverage: dict[str, Any] = {
        "required_suffixes": list(REQUIRED_SOURCE_SUFFIXES),
        "tracked_source_changes_always_staged": tracked_source_count,
        "untracked_source_candidate_count": sum(counts["seen"] for counts in source_suffix_counts.values()),
        "untracked_source_selected_count": sum(counts["selected"] for counts in source_suffix_counts.values()),
        "untracked_source_excluded_count": sum(counts["excluded"] for counts in source_suffix_counts.values()),
        "uncovered_untracked_source_count": 0,
        "uncovered_untracked_source_files": [],
        "by_suffix": {suffix: dict(counts) for suffix, counts in sorted(source_suffix_counts.items())},
        "coverage_rule": "Every non-ignored untracked path with a source suffix is listed as selected or with an explicit exclusion reason. git ls-files --exclude-standard deliberately omits ignored paths; they are never force-added.",
    }
    return {
        "repository": repo.name,
        "root": str(repo.resolve()),
        "branch": branch,
        "head": head,
        "scan_command": "git ls-files --others --exclude-standard -z",
        "tracked_change_count": len(tracked_changes),
        "tracked_change_bytes_present": sum(row["size_bytes"] for row in tracked_changes),
        "tracked_changes": tracked_changes,
        "untracked_candidate_count": len(untracked_paths),
        "selected_new_count": len(selected_new),
        "selected_new_bytes": sum(row["size_bytes"] for row in selected_new),
        "selected_new_files": selected_new,
        "excluded_new_count": len(excluded_new),
        "excluded_new_bytes": sum(row["size_bytes"] for row in excluded_new),
        "excluded_new_by_reason": excluded_by_reason,
        "excluded_new_files": excluded_new,
        "planned_path_count": len(tracked_changes) + len(selected_new),
        "planned_present_bytes": sum(row["size_bytes"] for row in tracked_changes + selected_new),
        "large_tracked_over_95_mib": large_tracked,
        "unmerged_index_entries": conflicts,
        "source_coverage": source_coverage,
        "errors": errors,
        "stage_mode": {
            "tracked_operation": "git add -u -- .",
            "new_file_operation": "git add --pathspec-from-file=<NUL-delimited-file> --pathspec-file-nul using :(literal) pathspecs",
            "ignored_files": "never force-added",
            "commits_or_pushes": "never",
        },
    }


def apply_stage(repo: Path, repo_plan: dict[str, Any]) -> dict[str, Any]:
    git(repo, "add", "-u", "--", ".")
    selected = [os.fsencode(row["path"]) for row in repo_plan["selected_new_files"]]
    if selected:
        with tempfile.NamedTemporaryFile(prefix="shardforge-pathspec-", suffix=".nul", delete=False) as handle:
            pathspec_file = Path(handle.name)
            for relative_path in selected:
                normalized = relative_path.replace(b"\\", b"/")
                handle.write(b":(literal)" + normalized + b"\0")
        try:
            git(repo, "add", f"--pathspec-from-file={pathspec_file}", "--pathspec-file-nul")
        finally:
            pathspec_file.unlink(missing_ok=True)

    staged = set(nul_paths(git(repo, "diff", "--cached", "--name-only", "--no-renames", "-z", "HEAD", "--")))
    expected = {row["path"] for row in repo_plan["tracked_changes"]}
    expected.update(row["path"] for row in repo_plan["selected_new_files"])
    missing = sorted(expected - staged)
    if missing:
        raise PlanError(f"stage verification failed in {repo}: expected paths not staged: {missing[:20]}")
    return {
        "repository": repo.name,
        "tracked_changes_staged": len(repo_plan["tracked_changes"]),
        "selected_new_files_staged": len(repo_plan["selected_new_files"]),
        "verified_expected_paths": len(expected),
        "verification": "all planned tracked changes and selected new files appear in the index",
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=True, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="ShardForge workspace containing vesselforge, pgfrag, and relicweave-synlab",
    )
    parser.add_argument(
        "--stage",
        action="store_true",
        help="stage the reviewed plan (tracked changes via git add -u plus selected new files); no commit or push",
    )
    parser.add_argument("--output-json", type=Path, help="also write the complete plan/report to this JSON file")
    args = parser.parse_args(argv)

    workspace = args.workspace.resolve()
    try:
        output_path = args.output_json.resolve() if args.output_json else None
        if args.stage and output_path is not None:
            for name in REPOSITORIES:
                try:
                    output_path.relative_to((workspace / name).resolve())
                except ValueError:
                    continue
                raise PlanError(
                    "--output-json cannot target a repository during --stage because writing the final report after staging would leave that report unstaged; run a dry-plan with --output-json, then use --stage without --output-json"
                )
        plans = [plan_repo(workspace / name, workspace) for name in REPOSITORIES]
        report: dict[str, Any] = {
            "format_version": 1,
            "created_by": "tools/handover/prepare_delivery_stage.py",
            "snapshot_status": "pre_release_dry_plan",
            "snapshot_note": "Point-in-time inventory; refresh after repository or workspace_support archive changes and before explicit staging.",
            "workspace": str(workspace),
            "mode": "stage_requested" if args.stage else "dry_plan",
            "policy": {
                "untracked_discovery": "git ls-files --others --exclude-standard -z",
                "tracked_changes": "always stage with git add -u when --stage is used",
                "generated_evidence_limit_bytes": MAX_EVIDENCE_BYTES,
                "tracked_large_file_warning_bytes": LARGE_TRACKED_WARNING_BYTES,
                "raw_array_suffixes_excluded": sorted(RAW_ARRAY_SUFFIXES),
                "dependency_binary_suffixes_excluded": sorted(DEPENDENCY_BINARY_SUFFIXES),
                "runtime_directories_excluded": sorted(RUNTIME_DIRECTORY_NAMES),
                "source_suffix_allowlist": sorted(SOURCE_SUFFIXES),
            },
            "repositories": plans,
            "stage_results": [],
            "errors": [
                {"repository": plan["repository"], **error}
                for plan in plans
                for error in plan["errors"]
            ],
            "warnings": [
                {
                    "repository": plan["repository"],
                    "code": "tracked_file_over_95_mib",
                    **row,
                    "message": "Tracked changes are still staged by --stage; review this large-file warning.",
                }
                for plan in plans
                for row in plan["large_tracked_over_95_mib"]
            ],
        }

        if args.stage:
            conflicts = [
                {"repository": plan["repository"], "entries": plan["unmerged_index_entries"]}
                for plan in plans
                if plan["unmerged_index_entries"]
            ]
            if report["errors"] or conflicts:
                report["stage_blocked"] = True
                report["blocking_conflicts"] = conflicts
                report["stage_results"] = []
                print(json.dumps(report, ensure_ascii=True, indent=2))
                if args.output_json:
                    write_json(args.output_json, report)
                return 2
            report["stage_results"] = [
                apply_stage(workspace / plan["repository"], plan) for plan in plans
            ]

        rendered = json.dumps(report, ensure_ascii=True, indent=2)
        print(rendered)
        if args.output_json:
            write_json(args.output_json, report)
        return 0
    except PlanError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
