#!/usr/bin/env python3
"""Independent read-only closeout verifier and path-only credential scanner.

Postverify mode is intentionally inert unless the caller supplies the explicit
root-GO marker. It reads a frozen inventory, explicit action manifest, and
execution receipt; it never stages, copies, commits, pushes, runs project code,
or reads file contents into its report. Credential-scan mode reports only
source paths, rule names, and counts; matched values and lines are discarded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO


REPO_IDS = ("pgfrag", "vesselforge", "relicweave-synlab")
TEXT_SUFFIXES = {
    ".py", ".pyi", ".pyw", ".ps1", ".psm1", ".psd1", ".js", ".jsx",
    ".ts", ".tsx", ".mjs", ".cjs", ".sh", ".bash", ".zsh", ".bat",
    ".cmd", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hxx", ".cs", ".java",
    ".kt", ".go", ".rs", ".rb", ".php", ".swift", ".sql", ".html",
    ".css", ".scss", ".json", ".jsonc", ".jsonl", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".xml", ".md", ".rst", ".adoc",
    ".txt", ".csv", ".properties", ".lock", ".json5", ".ipynb", ".svg",
    ".patch", ".diff", ".mk", ".cmake", ".example", ".sample", ".template",
}
TEXT_BASENAMES = {
    "dockerfile", "makefile", "justfile", "procfile", "gemfile", "rakefile",
    "readme", "license", "copying", "notice", "authors", "contributors",
    ".editorconfig", ".gitattributes", ".gitignore", ".dockerignore",
    ".npmrc", ".nvmrc", ".pre-commit-config.yaml", "security.md",
    "code_of_conduct.md", "contributing.md", "citation.cff",
}
SOURCE_SUFFIX_RE = re.compile(
    r"\.(?:pyi?|pyw|pyx|pxd|jl|r|rmd|ps1|psm1|psd1|js|jsx|ts|tsx|mjs|cjs|sh|bash|zsh|bat|cmd|"
    r"c|h|cc|cpp|cxx|hpp|hxx|cs|java|kt|kts|go|rs|rb|php|swift|scala|sql|lua|pl|yaml|yml|toml|ini|cfg|conf|json|json5|md|rst|adoc|ipynb|svg|patch|diff|mk|cmake)\.",
    re.I,
)
SOURCE_CLASSES = {
    "source_code_or_original_snapshot", "source_config_or_license",
    "authored_documentation", "source_metadata_json", "project_configuration",
    "project_configuration_or_fixture", "fixture_or_configuration_json",
    "small_source_test_fixture", "text_document_or_dependency",
    "pinned_status_evidence_dependency", "closed_review_record",
    "accepted_science98_backup_record_or_tool", "backup_handoff_plan_or_receipt",
    "root_accepted_progress_or_readiness_artifact",
}
DENIED_PARTS = {
    ".git", ".venv", "venv", "site-packages", "node_modules",
    "installer", "installers", "buildcache", "build_cache", "credentials",
    "credential_store", "credential-stores", "keyrings", "private_keys",
    "private-keys",
}
SENSITIVE_NAMES = {
    ".env", ".netrc", ".pypirc", "credentials.json", "service-account.json",
    "id_rsa", "id_ed25519",
}
SECRET_PATH_RE = re.compile(
    r"(?:^|[/\\])(?:\.env(?:\.(?!example$|sample$|template$)[^/\\]+)?|"
    r"credentials?(?:\.[^/\\]+)?|secrets?(?:\.[^/\\]+)?|"
    r"[^/\\]+\.(?:pem|p12|pfx|key|keystore))(?:$|[/\\])", re.I
)
PATTERNS: dict[str, re.Pattern[str]] = {
    "private_key_pem_header": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"
    ),
    "github_token_format": re.compile(
        r"\b(?:github_pat_[A-Za-z0-9_]{40,}|gh[pousr]_[A-Za-z0-9]{30,})\b"
    ),
    "aws_access_key_id_format": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "google_api_key_format": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "slack_token_format": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{25,}\b"),
    "stripe_secret_key_format": re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b"),
}
ASSIGNMENT_RE = re.compile(
    r"(?im)\b(api[_-]?key|secret(?:[_-]?key)?|client[_-]?secret|"
    r"access[_-]?token|auth[_-]?token|password)\b\s*[:=]\s*"
    r"['\"]([^'\"\r\n]{24,})['\"]"
)
TEMPLATE_RE = re.compile(
    r"(?i)(?:os\.environ|os\.getenv|process\.env|env\(|\$\{[^}]+\}|"
    r"<[^>]+>|\b(?:changeme|redacted|example|placeholder|dummy|sample|"
    r"your[-_ ]|replace[-_ ]?me|insert[-_ ]|not[-_ ]a[-_ ]secret)\b|x{4,})"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def read_json(path: Path) -> tuple[dict[str, Any], str, int]:
    size, digest = sha256_file(path)
    with path.open("r", encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value, digest, size


def new_output_path(path_text: str) -> Path:
    path = Path(path_text).resolve()
    path.relative_to(Path(__file__).resolve().parent)
    if not path.name.startswith("independent_"):
        raise ValueError("Output basename must start with independent_")
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_json_new(path: Path, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(encoded)


def write_text_new(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def safe_source_path(entry: dict[str, Any]) -> Path | None:
    text = entry.get("source_absolute")
    if not isinstance(text, str) or not text:
        return None
    candidate = Path(text)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    lowered_parts = {part.casefold() for part in resolved.parts}
    if lowered_parts & DENIED_PARTS or SECRET_PATH_RE.search(str(resolved)):
        return None
    if resolved.name.casefold() in SENSITIVE_NAMES:
        return None
    return resolved


def entropy_bits(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def credential_scan(args: argparse.Namespace) -> int:
    started = time.monotonic()
    inventory_path = Path(args.inventory).resolve(strict=True)
    inventory, inventory_sha, inventory_bytes = read_json(inventory_path)
    entries = inventory.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Inventory has no entries array")
    workspace = Path(str(inventory.get("workspace_root", ""))).resolve()
    candidates: dict[str, tuple[Path, dict[str, Any]]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("classification") not in SOURCE_CLASSES:
            continue
        path = safe_source_path(entry)
        if path is None or not path.is_file() or (
            path.suffix.casefold() not in TEXT_SUFFIXES
            and path.name.casefold() not in TEXT_BASENAMES
            and not SOURCE_SUFFIX_RE.search(path.name)
        ):
            continue
        try:
            path.relative_to(workspace)
        except ValueError:
            continue
        candidates[str(path).casefold()] = (path, entry)

    hits: list[dict[str, Any]] = []
    total_bytes = 0
    unreadable = 0
    for path, entry in candidates.values():
        try:
            raw = path.read_bytes()
        except OSError:
            unreadable += 1
            continue
        total_bytes += len(raw)
        if b"\x00" in raw:
            continue
        text = raw.decode("utf-8-sig", errors="replace")
        found: dict[str, int] = {}
        for rule, pattern in PATTERNS.items():
            count = sum(1 for _ in pattern.finditer(text))
            if count:
                found[rule] = count
        assignment_count = 0
        for match in ASSIGNMENT_RE.finditer(text):
            literal = match.group(2).strip()
            if TEMPLATE_RE.search(literal) or entropy_bits(literal) < 3.45:
                continue
            assignment_count += 1
        if assignment_count:
            found["high_entropy_credential_assignment"] = assignment_count
        if found:
            try:
                rel = path.relative_to(workspace).as_posix()
            except ValueError:
                rel = path.name
            hits.append({"path": rel, "rules": found, "match_count": sum(found.values())})

    result = {
        "schema": "independent_embedded_credential_scan_v1",
        "mode": "path_rule_count_only",
        "created_unix_seconds": int(time.time()),
        "inventory_path": str(inventory_path),
        "inventory_bytes": inventory_bytes,
        "inventory_sha256": inventory_sha,
        "scanned_file_count": len(candidates) - unreadable,
        "scanned_bytes": total_bytes,
        "unreadable_file_count": unreadable,
        "hit_file_count": len(hits),
        "hits": sorted(hits, key=lambda row: row["path"].casefold()),
        "limitations": [
            "High-confidence literal patterns only; no secret values or source lines are retained.",
            "Environment lookups and obvious templates/placeholders are not treated as credentials.",
            "Only selected inventory source/config/documentation text is scanned; credential stores, .git, and runtimes are excluded.",
        ],
    }
    out = new_output_path(args.out)
    write_json_new(out, result)
    print(json.dumps({
        "status": "SCAN_COMPLETE",
        "inventory_sha256": inventory_sha,
        "scanned_file_count": result["scanned_file_count"],
        "scanned_bytes": total_bytes,
        "hit_file_count": len(hits),
        "output": str(out),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }, ensure_ascii=False))
    return 0


def run_git(git: str, root: Path, argv: list[str], timeout: float = 30.0) -> bytes:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "0"
    completed = subprocess.run(
        [git, *argv], cwd=str(root), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git command failed rc={completed.returncode}: {argv[0]}")
    return completed.stdout


def norm_rel(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Missing repository-relative path")
    path = value.replace("\\", "/")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise ValueError(f"Expected relative path: {path}")
    parts = [part for part in path.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError(f"Parent traversal is not allowed: {path}")
    return "/".join(parts)


def pathset_digest(paths: set[str]) -> str:
    data = b"".join(path.encode("utf-8", errors="surrogateescape") + b"\0" for path in sorted(paths))
    return sha256_bytes(data)


def parse_tree(raw: bytes) -> dict[str, dict[str, str]]:
    tree: dict[str, dict[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        header, tab, path_raw = record.partition(b"\t")
        if not tab:
            raise ValueError("Malformed git ls-tree record")
        mode, obj_type, oid = header.decode("ascii").split(" ", 2)
        path = path_raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        tree[path] = {"mode": mode, "type": obj_type, "oid": oid}
    return tree


def read_exact(stream: BinaryIO, count: int, digest: Any) -> None:
    remaining = count
    while remaining:
        block = stream.read(min(1024 * 1024, remaining))
        if not block:
            raise EOFError("Short read from git cat-file --batch")
        digest.update(block)
        remaining -= len(block)


def cat_file_hashes(git: str, root: Path, oids: set[str]) -> dict[str, dict[str, Any]]:
    if not oids:
        return {}
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc = subprocess.Popen(
        [git, "cat-file", "--batch"], cwd=str(root), env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    write_errors: list[BaseException] = []

    def feed_oids() -> None:
        try:
            assert proc.stdin is not None
            for requested_oid in sorted(oids):
                proc.stdin.write(requested_oid.encode("ascii") + b"\n")
            proc.stdin.close()
        except BaseException as exc:
            write_errors.append(exc)

    writer = threading.Thread(target=feed_oids, name="git-cat-file-input", daemon=True)
    writer.start()
    found: dict[str, dict[str, Any]] = {}
    for _ in range(len(oids)):
        header = proc.stdout.readline()
        parts = header.rstrip(b"\n").split(b" ")
        if len(parts) != 3 or parts[1] == b"missing":
            raise ValueError("Git object missing or malformed in cat-file batch")
        oid = parts[0].decode("ascii")
        obj_type = parts[1].decode("ascii")
        size = int(parts[2])
        digest = hashlib.sha256()
        read_exact(proc.stdout, size, digest)
        if proc.stdout.read(1) != b"\n":
            raise ValueError("Malformed cat-file batch delimiter")
        found[oid] = {"type": obj_type, "bytes": size, "sha256": digest.hexdigest()}
    proc.stdout.close()
    writer.join(timeout=30)
    if writer.is_alive() or write_errors:
        proc.kill()
        raise RuntimeError("cat-file input stream did not complete")
    stderr = proc.stderr.read()
    proc.stderr.close()
    rc = proc.wait(timeout=30)
    if rc != 0:
        raise RuntimeError(f"git cat-file --batch failed rc={rc}")
    if stderr.strip():
        raise RuntimeError("git cat-file --batch emitted stderr")
    return found


def mapping_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    actions = manifest.get("candidate_actions")
    if not isinstance(actions, list):
        raise ValueError("Manifest has no candidate_actions array")
    return [row for row in actions if isinstance(row, dict)]


def supplementary_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    if data.get("schema") != "independent_supplementary_exports_v1":
        raise ValueError("Supplementary metadata manifest has an unexpected schema")
    rows = data.get("exports")
    if not isinstance(rows, list) or not rows or len(rows) > 32:
        raise ValueError("Supplementary metadata exports must contain 1..32 rows")
    parsed = [row for row in rows if isinstance(row, dict)]
    destinations = {
        (str(row.get("destination_repo", "")), norm_rel(row.get("destination_repo_relative")))
        for row in parsed
    }
    required = {
        ("relicweave-synlab", "docs/handover/20261007/CODE_COVERAGE.md"),
        ("relicweave-synlab", "workspace_backup/20261007/WORKSPACE_SOURCE_MAP.json"),
    }
    if not required.issubset(destinations):
        raise ValueError("Supplementary export map omits a required source-recovery document")
    for row in parsed:
        repo = str(row.get("destination_repo", ""))
        rel = norm_rel(row.get("destination_repo_relative"))
        if (repo, rel) not in required:
            base = rel.rsplit("/", 1)[-1]
            permitted_control = (
                rel.startswith("workspace_backup/20261007/")
                or (rel.startswith("docs/backup/20261007/") and base.startswith("CONTROL_") and base.lower().endswith(".json"))
            )
            if row.get("role") != "frozen_control_copy" or repo != "relicweave-synlab" or not permitted_control:
                raise ValueError("Only explicitly labeled frozen control copies may supplement the two required exports")
    return parsed


def repo_record_map(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    source = receipt.get("repositories")
    if isinstance(source, dict):
        for key, value in source.items():
            if isinstance(value, dict):
                result[str(key)] = dict(value)
    elif isinstance(source, list):
        for value in source:
            if isinstance(value, dict) and value.get("repo"):
                result[str(value["repo"])] = dict(value)
    for field in ("commit_records", "git_mutations", "repositories_committed"):
        rows = receipt.get(field)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("repo"):
                    key = str(row["repo"])
                    result.setdefault(key, {}).update(row)
    return result


def record_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def normalize_paths(value: Any) -> set[str] | None:
    if not isinstance(value, list):
        return None
    normalized = [norm_rel(item) for item in value]
    if len(normalized) != len(set(normalized)):
        return None
    return set(normalized)


def check_forbidden_path(repo_rel: str) -> bool:
    parts = {part.casefold() for part in repo_rel.split("/")}
    base = repo_rel.rsplit("/", 1)[-1].casefold()
    return bool(parts & DENIED_PARTS) or base in SENSITIVE_NAMES or bool(SECRET_PATH_RE.search("/" + repo_rel))


def is_raw_snapshot_entry(entry: dict[str, Any]) -> bool:
    classification = str(entry.get("classification", ""))
    destination = str(entry.get("destination_repo_relative", "")).replace("\\", "/")
    return classification.startswith("exact_raw_") or destination.startswith("docs/backup/20261007/raw_source/")


def git_blob_oid_for_file(path: Path, object_format: str) -> str:
    if object_format not in {"sha1", "sha256"}:
        raise ValueError(f"Unsupported Git object format: {object_format}")
    digest = hashlib.new(object_format)
    size = path.stat().st_size
    digest.update(f"blob {size}\0".encode("ascii"))
    read_size = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            read_size += len(block)
            digest.update(block)
    if read_size != size:
        raise RuntimeError(f"File changed while deriving its Git blob OID: {path}")
    return digest.hexdigest()


def postverify(args: argparse.Namespace) -> int:
    if args.root_go_confirmed != "ROOT_GO_AFTER_PUSH":
        raise PermissionError("Postverify requires the exact root GO marker after commit and push")
    started = time.monotonic()
    inv_path = Path(args.inventory).resolve(strict=True)
    man_path = Path(args.manifest).resolve(strict=True)
    receipt_path = Path(args.receipt).resolve(strict=True)
    inventory, inv_sha, inv_bytes = read_json(inv_path)
    manifest, man_sha, man_bytes = read_json(man_path)
    receipt, receipt_sha, receipt_bytes = read_json(receipt_path)
    supplement = None
    supplement_sha = None
    supplement_bytes = 0
    if args.supplementary:
        supplement, supplement_sha, supplement_bytes = read_json(Path(args.supplementary).resolve(strict=True))
    if manifest.get("inventory_sha256") != inv_sha:
        raise ValueError("Manifest does not pin the supplied final inventory SHA-256")
    if receipt.get("plan_sha256") and args.plan:
        plan, plan_sha, plan_bytes = read_json(Path(args.plan).resolve(strict=True))
        if receipt.get("plan_sha256") != plan_sha:
            raise ValueError("Execution receipt does not pin the supplied plan SHA-256")
        plan_inv_sha = plan.get("inventory_sha256") or plan.get("inventory_sha")
        plan_man_sha = plan.get("manifest_sha256") or plan.get("action_manifest_sha256")
        if plan_inv_sha != inv_sha or plan_man_sha != man_sha:
            raise ValueError("Plan does not pin the supplied final inventory and manifest")
    elif args.plan:
        raise ValueError("Receipt lacks plan_sha256; cannot verify the supplied plan")
    elif not args.allow_receipt_without_plan:
        raise ValueError("Supply the execution plan, or root must explicitly allow receipt-only binding")

    workspace = Path(str(inventory.get("workspace_root", ""))).resolve(strict=True)
    manifest_repos = manifest.get("repositories")
    if not isinstance(manifest_repos, dict):
        raise ValueError("Manifest repositories must be an object")
    repo_roots: dict[str, Path] = {}
    for repo_id in REPO_IDS:
        rec = manifest_repos.get(repo_id)
        if not isinstance(rec, dict):
            raise ValueError(f"Missing repository definition: {repo_id}")
        root_text = rec.get("repo_root")
        if not root_text:
            raise ValueError(f"Missing repo_root for {repo_id}")
        root = Path(str(root_text)).resolve(strict=True)
        root.relative_to(workspace)
        repo_roots[repo_id] = root

    actions = mapping_rows(manifest)
    main_action_count = len(actions)
    supplemental = supplementary_rows(supplement) if supplement is not None else []
    expected_by_repo: dict[str, set[str]] = {repo: set() for repo in REPO_IDS}
    action_by_source: dict[tuple[str, str], list[dict[str, Any]]] = {}
    path_owner: dict[tuple[str, str], dict[str, Any]] = {}
    action_rows: list[dict[str, Any]] = []
    target_blob_oids: dict[tuple[str, str], str] = {}
    git = args.git
    object_formats: dict[str, str] = {}
    for repo, root in repo_roots.items():
        object_format = run_git(git, root, ["rev-parse", "--show-object-format"]).decode("ascii").strip()
        if object_format not in {"sha1", "sha256"}:
            raise ValueError(f"Unsupported Git object format for {repo}: {object_format}")
        object_formats[repo] = object_format
    for row in [*actions, *supplemental]:
        repo = str(row.get("destination_repo", ""))
        if repo not in repo_roots:
            raise ValueError(f"Action points outside the three approved repositories: {repo}")
        rel = norm_rel(row.get("destination_repo_relative"))
        if check_forbidden_path(rel):
            raise ValueError(f"Forbidden destination path is selected: {repo}/{rel}")
        classification = str(row.get("classification", ""))
        if classification.startswith("generated_") or classification in {
            "renderer_or_other_docx", "source_over_50MiB_requires_review",
            "internal_backup_record_over_1MiB_or_dynamic",
        }:
            raise ValueError(f"An excluded/generated classification was selected: {classification}")
        key = (repo, rel)
        if key in path_owner:
            raise ValueError(f"Duplicate destination: {repo}/{rel}")
        path_owner[key] = row
        expected_by_repo[repo].add(rel)
        source_text = row.get("source_absolute") or row.get("source_path")
        if not source_text:
            raise ValueError(f"Action lacks a source path: {repo}/{rel}")
        source = Path(str(source_text)).resolve(strict=True)
        source.relative_to(workspace)
        if check_forbidden_path(source.relative_to(workspace).as_posix()):
            raise ValueError(f"Action source is outside the approved code scope: {repo}/{rel}")
        action_by_source.setdefault((str(source).casefold(), repo), []).append(row)
        action_rows.append(row)

    entries = inventory.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Inventory has no entries array")
    evidence = manifest.get("status_evidence_dependency_closure")
    if not isinstance(evidence, list) or len(evidence) != 100:
        raise ValueError("Final manifest must contain exactly 100 status evidence dependencies")
    evidence_paths = [str(row.get("source_path", "")) for row in evidence if isinstance(row, dict)]
    if len(evidence_paths) != 100 or len(set(evidence_paths)) != 100:
        raise ValueError("Status evidence dependency paths are missing or duplicated")
    for item in evidence:
        if not item.get("current_inventory_match") or not item.get("recovery_mapping_complete"):
            raise ValueError("A status evidence dependency is not hash-pinned or recoverable")
        if item.get("expected_bytes") != item.get("current_bytes") or item.get("expected_sha256") != item.get("current_sha256"):
            raise ValueError("A status evidence dependency changed after pinning")

    inventory_by_workspace_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("operation") == "exclude":
            continue
        repo = str(entry.get("repo", ""))
        if repo == "workspace_root_external":
            path_key = str(entry.get("source_workspace_relative") or "").replace("\\", "/")
        else:
            rel = str(entry.get("source_repo_relative") or "").replace("\\", "/")
            path_key = f"{repo}/{rel}" if rel else ""
        if path_key:
            inventory_by_workspace_path[path_key] = entry
    for item in evidence:
        source_row = inventory_by_workspace_path.get(str(item.get("source_path", "")).replace("\\", "/"))
        if not source_row or (int(source_row.get("bytes", -1)), str(source_row.get("sha256", ""))) != (int(item.get("expected_bytes", -1)), str(item.get("expected_sha256", ""))):
            raise ValueError("A status evidence source does not resolve to its exact inventory row")

    # Validate every selected source and collect all required HEAD object IDs.
    source_checks: dict[str, dict[str, Any]] = {}
    expected_tree_oids: dict[str, dict[str, str]] = {repo: {} for repo in REPO_IDS}
    needs: dict[str, set[str]] = {repo: set() for repo in REPO_IDS}
    excluded_inventory_count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("operation") == "exclude":
            excluded_inventory_count += 1
            if entry.get("destination_repo") or entry.get("destination_repo_relative"):
                raise ValueError("Excluded inventory row unexpectedly has a destination")
            continue
        if str(entry.get("operation", "")).startswith("blocked"):
            raise ValueError("Inventory contains a blocked destination mapping")
        source = safe_source_path(entry)
        if source is None:
            if entry.get("source_absolute"):
                raise ValueError("An inventory source path is outside the allowed readable scope")
            continue
        try:
            source.relative_to(workspace)
        except ValueError as exc:
            raise ValueError("Inventory source path is outside workspace") from exc
        if not source.is_file():
            raise FileNotFoundError(f"Inventory source missing: {source}")
        size, digest = sha256_file(source)
        if size != int(entry.get("bytes", -1)) or digest != str(entry.get("sha256", "")):
            raise ValueError(f"Inventory source pin changed: {source}")
        source_checks[str(source).casefold()] = {"bytes": size, "sha256": digest}
        repo = entry.get("repo")
        if repo in repo_roots and entry.get("git_status") in {"tracked", "tracked_modified"}:
            rel = norm_rel(entry.get("source_repo_relative"))
            oid = str(entry.get("git_head_blob_oid") or "")
            if not oid:
                raise ValueError(f"Tracked source lacks its original HEAD blob pin: {repo}/{rel}")
            previous = expected_tree_oids[repo].get(rel)
            if previous and previous != oid:
                raise ValueError(f"Conflicting HEAD blob pins: {repo}/{rel}")
            expected_tree_oids[repo][rel] = oid
            needs[repo].add(oid)
    tracked_count = sum(len(rows) for rows in expected_tree_oids.values())

    # Verify source -> destination file bytes for every action.
    destination_checks: dict[tuple[str, str], dict[str, Any]] = {}
    for row in action_rows:
        repo = str(row["destination_repo"])
        rel = norm_rel(row["destination_repo_relative"])
        source_text = row.get("source_absolute") or row.get("source_path")
        source = Path(str(source_text)).resolve(strict=True)
        source_size, source_sha = sha256_file(source)
        if source_size != int(row.get("bytes", -1)) or source_sha != str(row.get("sha256", "")):
            raise ValueError(f"Action source pin changed: {source}")
        dest = (repo_roots[repo] / Path(rel)).resolve(strict=True)
        dest.relative_to(repo_roots[repo])
        dest_size, dest_sha = sha256_file(dest)
        if (dest_size, dest_sha) != (source_size, source_sha):
            raise ValueError(f"Source and destination bytes differ: {repo}/{rel}")
        destination_checks[(repo, rel)] = {"bytes": dest_size, "sha256": dest_sha}
        target_blob_oids[(repo, rel)] = git_blob_oid_for_file(dest, object_formats[repo])

    # Validate alias mappings without assuming an alias is a stage action.
    alias_rows = manifest.get("source_aliases_to_existing_byte_identical_destinations", [])
    if not isinstance(alias_rows, list):
        raise ValueError("source_aliases_to_existing_byte_identical_destinations must be an array")
    alias_count = 0
    for alias in alias_rows:
        if not isinstance(alias, dict):
            raise ValueError("Malformed source alias mapping")
        source_text = alias.get("source_absolute")
        if not source_text:
            source_text = alias.get("source")
        dest_repo = alias.get("destination_repo") or alias.get("repo")
        dest_rel_text = alias.get("destination_repo_relative") or alias.get("destination")
        if dest_repo not in repo_roots:
            raise ValueError("Source alias points outside approved repositories")
        src = Path(str(source_text)).resolve(strict=True)
        src.relative_to(workspace)
        if check_forbidden_path(src.relative_to(workspace).as_posix()):
            raise ValueError("Source alias reads an excluded scope path")
        dst_rel = norm_rel(dest_rel_text)
        if check_forbidden_path(dst_rel):
            raise ValueError("Source alias destination is forbidden")
        ss, sh = sha256_file(src)
        dest = (repo_roots[str(dest_repo)] / Path(dst_rel)).resolve(strict=True)
        dest.relative_to(repo_roots[str(dest_repo)])
        ds, dh = sha256_file(dest)
        exp_bytes = alias.get("bytes", ss)
        exp_sha = alias.get("sha256", sh)
        if (ss, sh, ds, dh) != (exp_bytes, exp_sha, exp_bytes, exp_sha):
            raise ValueError(f"Original-source alias byte mapping differs: {dst_rel}")
        destination_checks[(str(dest_repo), dst_rel)] = {"bytes": ds, "sha256": dh}
        alias_count += 1

    # Verify every raw worktree snapshot mapping against its source pin, its
    # original HEAD object, and the separately archived destination action.
    raw_maps = manifest.get("tracked_raw_source_snapshot_map", [])
    if not isinstance(raw_maps, list):
        raise ValueError("tracked_raw_source_snapshot_map must be an array")
    entry_by_original: dict[tuple[str, str], dict[str, Any]] = {}
    canonical_pin_by_original: dict[tuple[str, str], tuple[Any, ...]] = {}
    for entry in entries:
        if isinstance(entry, dict) and entry.get("operation") != "exclude" and entry.get("repo") in repo_roots and entry.get("source_repo_relative"):
            key = (str(entry["repo"]), norm_rel(entry["source_repo_relative"]))
            pin = (
                entry.get("bytes"), entry.get("sha256"), entry.get("git_head_blob_oid"),
                entry.get("worktree_head_relation"),
            )
            current = entry_by_original.get(key)
            if current is None or (is_raw_snapshot_entry(current) and not is_raw_snapshot_entry(entry)):
                entry_by_original[key] = entry
                canonical_pin_by_original[key] = pin
            elif not is_raw_snapshot_entry(current) and not is_raw_snapshot_entry(entry):
                if canonical_pin_by_original[key] != pin:
                    raise ValueError(f"Conflicting canonical tracked-source rows: {key[0]}/{key[1]}")
    raw_relations: dict[str, int] = {}
    raw_verified = 0
    for raw in raw_maps:
        if not isinstance(raw, dict):
            raise ValueError("Malformed tracked raw-snapshot map row")
        source_repo = str(raw.get("source_repo", ""))
        dest_repo = str(raw.get("destination_repo", ""))
        source_rel = norm_rel(raw.get("source_path"))
        dest_rel = norm_rel(raw.get("destination_path"))
        if source_repo not in repo_roots or dest_repo not in repo_roots:
            raise ValueError("Raw-snapshot map points outside approved repositories")
        entry = entry_by_original.get((source_repo, source_rel))
        if not entry or (int(entry.get("bytes", -1)), str(entry.get("sha256", ""))) != (int(raw.get("bytes", -1)), str(raw.get("sha256", ""))):
            raise ValueError(f"Raw-snapshot source pin differs: {source_repo}/{source_rel}")
        if str(entry.get("git_head_blob_oid", "")) != str(raw.get("head_blob_oid", "")):
            raise ValueError(f"Raw-snapshot original HEAD OID differs: {source_repo}/{source_rel}")
        if entry.get("worktree_head_relation") != raw.get("relation"):
            raise ValueError(f"Raw-snapshot relation differs: {source_repo}/{source_rel}")
        archived = next((row for row in action_rows if row.get("destination_repo") == dest_repo and norm_rel(row.get("destination_repo_relative")) == dest_rel), None)
        if not archived or (int(archived.get("bytes", -1)), str(archived.get("sha256", ""))) != (int(raw.get("bytes", -1)), str(raw.get("sha256", ""))):
            raise ValueError(f"Raw-snapshot has no exact approved archive action: {dest_repo}/{dest_rel}")
        relation = str(raw.get("relation", "unknown"))
        raw_relations[relation] = raw_relations.get(relation, 0) + 1
        raw_verified += 1

    raw_source_keys = {(str(row.get("source_repo")), norm_rel(row.get("source_path"))) for row in raw_maps if isinstance(row, dict)}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("operation") == "exclude" or entry.get("repo") not in repo_roots or entry.get("git_status") not in {"tracked", "tracked_modified"}:
            continue
        relation = entry.get("worktree_head_relation")
        key = (str(entry["repo"]), norm_rel(entry.get("source_repo_relative")))
        if relation == "raw_worktree_matches_head_blob":
            continue
        if relation not in {"crlf_lf_normalization_only", "other_filter_or_content_relation_unresolved"} or key not in raw_source_keys:
            raise ValueError(f"Tracked source differs from HEAD without a raw archive: {key[0]}/{key[1]}")

    # Ensure each evidence mapping resolves through the same independent tree check.
    for item in evidence:
        mapping = item.get("backup_recovery_mapping", {})
        if not isinstance(mapping, dict):
            raise ValueError("Malformed evidence recovery mapping")
        repo = str(mapping.get("repo", ""))
        rel = norm_rel(mapping.get("path"))
        if repo not in repo_roots:
            raise ValueError("Evidence recovery mapping points outside approved repositories")
        key = (repo, rel)
        if mapping.get("kind") == "same_original_path_already_in_head_byte_identical":
            expected = {"bytes": int(item["expected_bytes"]), "sha256": str(item["expected_sha256"])}
            if key in destination_checks and destination_checks[key] != expected:
                raise ValueError("Evidence original-path mapping conflicts with another pinned byte tuple")
            destination_checks[key] = expected
        elif key not in path_owner:
            existing = entry_by_original.get(key)
            if not existing or (int(existing.get("bytes", -1)), str(existing.get("sha256", ""))) != (int(item["expected_bytes"]), str(item["expected_sha256"])):
                raise ValueError("Evidence recovery path has neither a frozen action nor an identical existing row")
            destination_checks[key] = {"bytes": int(item["expected_bytes"]), "sha256": str(item["expected_sha256"])}

    repo_results: dict[str, dict[str, Any]] = {}
    repo_trees: dict[str, dict[str, dict[str, str]]] = {}
    repo_blobs: dict[str, dict[str, dict[str, Any]]] = {}
    for repo in REPO_IDS:
        root = repo_roots[repo]
        head = run_git(git, root, ["rev-parse", "HEAD"]).decode("ascii").strip()
        parent = run_git(git, root, ["rev-parse", "HEAD^"]).decode("ascii").strip()
        base_record = manifest_repos[repo]
        base_head = str(base_record.get("head", ""))
        if not base_head or parent != base_head:
            raise ValueError(f"Committed parent differs from the frozen baseline: {repo}")
        base_tree = parse_tree(run_git(git, root, ["ls-tree", "-r", "-z", "--full-tree", "HEAD^"]))
        tree = parse_tree(run_git(git, root, ["ls-tree", "-r", "-z", "--full-tree", "HEAD"]))
        repo_trees[repo] = tree
        for rel, expected_oid in expected_tree_oids[repo].items():
            actual = base_tree.get(rel)
            if not actual or actual["type"] != "blob" or actual["oid"] != expected_oid:
                raise ValueError(f"Original tracked source does not match the committed parent blob: {repo}/{rel}")
            if (repo, rel) not in path_owner:
                current_head = tree.get(rel)
                if not current_head or current_head["type"] != "blob" or current_head["oid"] != expected_oid:
                    raise ValueError(f"An unchanged tracked source changed in the backup commit: {repo}/{rel}")
        for (dest_repo, rel), _check in destination_checks.items():
            if dest_repo != repo:
                continue
            actual = tree.get(rel)
            if not actual or actual["type"] != "blob":
                raise ValueError(f"Approved destination is absent from HEAD tree: {repo}/{rel}")
            needs[repo].add(actual["oid"])
        for item in evidence:
            mapping = item.get("backup_recovery_mapping", {})
            if mapping.get("repo") == repo:
                rel = norm_rel(mapping.get("path"))
                actual = tree.get(rel)
                if actual and actual["type"] == "blob":
                    needs[repo].add(actual["oid"])
        blob_meta = cat_file_hashes(git, root, needs[repo])
        repo_blobs[repo] = blob_meta
        for rel, expected_oid in expected_tree_oids[repo].items():
            meta = blob_meta.get(expected_oid)
            if not meta or meta["type"] != "blob":
                raise ValueError(f"Tracked parent blob is not a readable blob: {repo}/{rel}")
            entry = entry_by_original.get((repo, rel))
            if entry and entry.get("git_head_blob_bytes") is not None and meta["bytes"] != int(entry["git_head_blob_bytes"]):
                raise ValueError(f"Tracked HEAD blob byte count differs from inventory: {repo}/{rel}")
            if entry and entry.get("worktree_head_relation") == "raw_worktree_matches_head_blob":
                source = Path(str(entry["source_absolute"])).resolve(strict=True)
                current = source_checks.get(str(source).casefold())
                if not current or (meta["bytes"], meta["sha256"]) != (current["bytes"], current["sha256"]):
                    raise ValueError(f"Tracked source differs from its raw HEAD blob: {repo}/{rel}")
        for (dest_repo, rel), check in destination_checks.items():
            if dest_repo != repo:
                continue
            oid = tree[rel]["oid"]
            meta = blob_meta.get(oid)
            if not meta or meta["type"] != "blob" or (meta["bytes"], meta["sha256"]) != (check["bytes"], check["sha256"]):
                raise ValueError(f"Destination file does not match its raw HEAD blob: {repo}/{rel}")

        branch = run_git(git, root, ["branch", "--show-current"]).decode("utf-8", "replace").strip()
        dirty = run_git(git, root, ["status", "--porcelain=v1", "--untracked-files=no"])
        staged = run_git(git, root, ["diff", "--cached", "--name-only", "-z"])
        changed_raw = run_git(git, root, ["diff-tree", "--no-commit-id", "--name-only", "-r", "--no-renames", "-z", "HEAD^", "HEAD"])
        changed = {path.decode("utf-8", "surrogateescape").replace("\\", "/") for path in changed_raw.split(b"\0") if path}
        expected_paths = expected_by_repo[repo]
        expected_changed_paths: set[str] = set()
        for rel in expected_paths:
            target_oid = target_blob_oids.get((repo, rel))
            if not target_oid:
                raise ValueError(f"Approved action lacks a raw target blob OID: {repo}/{rel}")
            base_blob = base_tree.get(rel)
            if not base_blob or base_blob["type"] != "blob" or base_blob["oid"] != target_oid:
                expected_changed_paths.add(rel)
        if changed != expected_changed_paths:
            raise ValueError(
                f"Committed changed-path set differs from raw target changes for {repo}: "
                f"expected={len(expected_changed_paths)} actual={len(changed)}"
            )
        rec_map = repo_record_map(receipt)
        record = rec_map.get(repo, {})
        recorded_commit = record_value(record, "commit", "new_head", "head")
        recorded_parent = record_value(record, "parent", "pre_head", "base_head")
        recorded_branch = record_value(record, "branch", "expected_branch")
        if not recorded_commit or str(recorded_commit) != head:
            raise ValueError(f"Execution receipt commit does not match current HEAD: {repo}")
        if not recorded_parent or str(recorded_parent) != parent or (base_head and parent != base_head):
            raise ValueError(f"Execution receipt parent does not match actual/base HEAD: {repo}")
        if recorded_branch and str(recorded_branch) != branch:
            raise ValueError(f"Execution receipt branch does not match worktree: {repo}")
        approved_paths = normalize_paths(record.get("approved_action_paths"))
        if approved_paths is None or approved_paths != expected_paths:
            raise ValueError(f"Execution receipt approved-action pathset is absent or differs: {repo}")
        add_requested_paths = normalize_paths(record.get("git_add_requested_paths"))
        if (
            add_requested_paths is None
            or not add_requested_paths.issubset(approved_paths)
            or not expected_changed_paths.issubset(add_requested_paths)
        ):
            raise ValueError(f"Execution receipt git-add request paths are absent or do not cover approved changes: {repo}")
        staged_paths = normalize_paths(record_value(record, "staged_paths"))
        if staged_paths is None or staged_paths != expected_changed_paths:
            raise ValueError(f"Execution receipt staged pathset is absent or differs from changed files: {repo}")
        committed_paths = normalize_paths(record.get("changed_paths"))
        if committed_paths is None or committed_paths != expected_changed_paths:
            raise ValueError(f"Execution receipt actual changed pathset is absent or differs: {repo}")
        if record.get("changed_paths_exact") is not True:
            raise ValueError(f"Execution receipt does not assert an exact pathset: {repo}")
        push_rc = record_value(record, "push_exit_code", "push_rc")
        push_command = record.get("push_command")
        if push_rc is None and isinstance(push_command, dict):
            push_rc = push_command.get("rc")
        if push_rc is None or int(push_rc) != 0:
            raise ValueError(f"Execution receipt lacks successful push rc: {repo}")
        remote_line = run_git(git, root, ["ls-remote", "--heads", "origin", f"refs/heads/{branch}"]).decode("ascii", "replace").strip()
        remote_parts = remote_line.split()
        remote_head = remote_parts[0] if len(remote_parts) >= 2 and remote_parts[1] == f"refs/heads/{branch}" else ""
        if remote_head != head:
            raise ValueError(f"Remote branch does not point to verified commit: {repo}")
        if dirty.strip() or staged.strip():
            raise ValueError(f"Tracked worktree or index is not clean after backup commit: {repo}")
        repo_results[repo] = {
            "head": head, "parent": parent, "branch": branch, "remote_head": remote_head,
            "approved_action_path_count": len(expected_paths),
            "approved_action_pathset_sha256": pathset_digest(expected_paths),
            "git_add_requested_path_count": len(add_requested_paths),
            "staged_path_count": len(staged_paths),
            "changed_path_count": len(changed), "changed_pathset_sha256": pathset_digest(changed),
            "tracked_source_path_count": len(expected_tree_oids[repo]),
            "verified_head_blob_count": len(blob_meta), "tracked_worktree_status_count": 0,
        }

    closure_rows = manifest.get("status_evidence_dependency_closure", [])
    evidence_verified = 0
    action_keys = {(str(row.get("destination_repo")), norm_rel(row.get("destination_repo_relative")), int(row.get("bytes", -1)), str(row.get("sha256", ""))) for row in action_rows}
    for item in closure_rows:
        mapping = item.get("backup_recovery_mapping", {})
        kind = str(mapping.get("kind", ""))
        repo = mapping.get("repo")
        rel = norm_rel(mapping.get("path"))
        key = (str(repo), rel, int(item["expected_bytes"]), str(item["expected_sha256"]))
        if kind == "same_original_path_already_in_head_byte_identical":
            if repo not in repo_roots:
                raise ValueError("Evidence original-path mapping points outside repos")
            oid = repo_trees[str(repo)].get(rel, {}).get("oid")
            meta = repo_blobs[str(repo)].get(oid, {}) if oid else {}
            if not oid or (meta.get("bytes"), meta.get("sha256")) != (key[2], key[3]):
                raise ValueError(f"Evidence original HEAD mapping differs: {item.get('source_path')}")
        elif key not in action_keys:
            # Same-path clean candidates may be already tracked and represented by an inventory row.
            matching = next((e for e in entries if isinstance(e, dict) and e.get("repo") == repo and e.get("source_repo_relative") == rel and e.get("bytes") == key[2] and e.get("sha256") == key[3]), None)
            if not matching:
                raise ValueError(f"Evidence recovery path has no frozen action or existing row: {item.get('source_path')}")
        evidence_verified += 1

    result = {
        "schema": "independent_all_code_backup_postverify_v1",
        "status": "PASS",
        "root_go_marker": "ROOT_GO_AFTER_PUSH",
        "created_unix_seconds": int(time.time()),
        "inputs": {
            "inventory": {"path": str(inv_path), "bytes": inv_bytes, "sha256": inv_sha},
            "manifest": {"path": str(man_path), "bytes": man_bytes, "sha256": man_sha},
            "execution_receipt": {"path": str(receipt_path), "bytes": receipt_bytes, "sha256": receipt_sha},
            "supplementary_exports": ({"path": str(Path(args.supplementary).resolve()), "bytes": supplement_bytes, "sha256": supplement_sha} if args.supplementary else None),
        },
        "summary": {
            "approved_action_count": main_action_count,
            "approved_action_bytes": sum(int(row.get("bytes", 0)) for row in actions),
            "supplementary_export_bytes": sum(int(row.get("bytes", 0)) for row in supplemental),
            "supplementary_export_count": len(supplemental),
            "verified_source_count": len(source_checks),
            "excluded_inventory_rows_not_hashed_or_backed_up": excluded_inventory_count,
            "verified_destination_count": len(destination_checks),
            "tracked_source_path_count": tracked_count,
            "status_evidence_refs_verified": evidence_verified,
            "original_source_aliases_verified": alias_count,
            "tracked_raw_snapshots_verified": raw_verified,
            "tracked_raw_snapshot_relations": raw_relations,
            "all_source_destination_head_blobs_match_raw_sha256": True,
            "all_explicit_pathsets_parent_branch_remote_and_cleanliness_checks_pass": True,
        },
        "repositories": repo_results,
        "scope_exclusions": {
            "forbidden_paths_in_approved_actions": 0,
            "git_index_not_used_as_head_evidence": True,
            "head_blobs_read_via_ls_tree_and_cat_file_batch": True,
            "no_tests_or_project_code_run": True,
        },
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    out = new_output_path(args.out)
    write_json_new(out, result)
    print(json.dumps({"status": "PASS", "output": str(out), "action_count": len(action_rows), "elapsed_seconds": result["elapsed_seconds"]}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    cred = sub.add_parser("credential-scan", help="high-confidence, path/category/count-only scan")
    cred.add_argument("--inventory", required=True)
    cred.add_argument("--out", required=True)
    cred.set_defaults(func=credential_scan)
    audit = sub.add_parser("postverify", help="read-only final verification after root GO and push")
    audit.add_argument("--inventory", required=True)
    audit.add_argument("--manifest", required=True)
    audit.add_argument("--receipt", required=True)
    audit.add_argument("--supplementary", help="frozen tuple manifest for post-inventory metadata exports")
    audit.add_argument("--plan", help="required when the execution receipt pins a plan")
    audit.add_argument("--allow-receipt-without-plan", action="store_true", help="explicit root-approved exception only")
    audit.add_argument("--git", default="git")
    audit.add_argument("--root-go-confirmed", required=True, help="must equal ROOT_GO_AFTER_PUSH after explicit root GO")
    audit.add_argument("--out", required=True)
    audit.set_defaults(func=postverify)
    return parser


if __name__ == "__main__":
    try:
        parsed = build_parser().parse_args()
        sys.exit(parsed.func(parsed))
    except Exception as exc:
        # Keep failures value-free: no exception text from file parsing or git output is echoed.
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__}, ensure_ascii=False))
        sys.exit(2)
