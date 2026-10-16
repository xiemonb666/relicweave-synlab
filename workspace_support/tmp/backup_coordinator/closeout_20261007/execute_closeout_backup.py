from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[3]
GIT_EXE = Path(r"C:\Users\xiemo\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe")
REPO_NAMES = ("pgfrag", "vesselforge", "relicweave-synlab")
BRANCH = "backup/forge-work-20261003"
DEFAULT_RECEIPT = ROOT / "tmp/backup_coordinator/closeout_20261007/execution_receipt.json"
EXPECTED_SCHEMA = "codex_exact_backup_action_manifest_v2"
ALLOWED_OPERATIONS = {
    "copy_then_stage_exact",
    "copy_then_stage_exact_force",
    "stage_existing_exact",
    "stage_existing_exact_force",
    "destination_already_same_bytes_stage_exact",
    "already_recoverable_same_bytes_destination",
}
COPY_OPERATIONS = {"copy_then_stage_exact", "copy_then_stage_exact_force"}
DIRECT_STAGE_OPERATIONS = {
    "stage_existing_exact",
    "stage_existing_exact_force",
    "destination_already_same_bytes_stage_exact",
    "already_recoverable_same_bytes_destination",
}
ALLOWED_CLASSIFICATIONS = {
    "accepted_science98_backup_record_or_tool",
    "authored_documentation",
    "backup_handoff_plan_or_receipt",
    "canonical_handover_convenience_copy",
    "closed_review_documentation",
    "closed_review_figure",
    "closed_review_junit_or_xml_record",
    "closed_review_numeric_evidence",
    "closed_review_raw_execution_record",
    "closed_review_record",
    "closed_review_text_record",
    "exact_raw_worktree_snapshot_for_head_normalization_review",
    "fixture_or_configuration_json",
    "pinned_status_evidence_dependency",
    "prechange_gitattributes_byte_snapshot",
    "preserved_prior_v1_candidate",
    "project_configuration",
    "project_configuration_or_fixture",
    "root_accepted_progress_or_readiness_artifact",
    "root_final_closeout_docx_frozen_pin",
    "root_final_handover_markdown_frozen_pin",
    "root_reference_docx",
    "root_closeout_reference_docx",
    "selected_bounded_replay_data",
    "small_source_test_fixture",
    "source_code_or_original_snapshot",
    "source_config_or_license",
    "source_fixture_jsonl",
    "source_metadata_json",
    "exact_raw_source_snapshot_for_text_or_filter_attribute",
    "text_document_or_dependency",
}
GENERATED_CLASSIFICATIONS = {
    "generated_configlike_output",
    "generated_json_report_or_dataset",
    "generated_jsonl_dataset",
    "generated_metadata_yaml",
    "generated_numeric_dataset",
    "generated_report_document",
    "final_handoff_docx_pending_qa_or_frozen",
    "image_or_unreviewed_figure",
    "not_in_source_scope",
    "renderer_or_other_docx",
    "root_closeout_docx_pending_qa",
    "runtime_text_output",
    "unclassified_json_output",
    "unclassified_text_output",
    "unclassified_yaml_or_config",
}
PATH_SECRET_RE = re.compile(r"(?:^|[._-])(?:credential|credentials|secret|secrets|access[_-]?key|api[_-]?key|private[_-]?key|id_rsa|id_ed25519)(?:$|[._-])", re.I)
SECRET_TEXT_PATTERNS = (
    ("private_key_pem", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github_token", re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("aws_access_key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{24,}\b")),
    ("google_api_key", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("stripe_live_secret", re.compile(rb"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b")),
)
GIT_URL_USERINFO_RE = re.compile(rb"(?i)(https?://)[^\s/@]+@")
GIT_AUTH_HEADER_RE = re.compile(rb"(?i)(authorization\s*:\s*(?:basic|bearer)\s+)[A-Za-z0-9+/=._-]+")
MANDATORY_SUPPLEMENTARY = {
    ("coverage_export", "relicweave-synlab", "docs/handover/20261007/CODE_COVERAGE.md", "tmp/backup_coordinator/closeout_20261007/CODE_COVERAGE.md"),
    ("source_map", "relicweave-synlab", "workspace_backup/20261007/WORKSPACE_SOURCE_MAP.json", "tmp/backup_coordinator/closeout_20261007/WORKSPACE_SOURCE_MAP.json"),
    ("frozen_control_copy", "relicweave-synlab", "docs/backup/20261007/CONTROL_ACTION_MANIFEST.json", "tmp/backup_coordinator/closeout_20261007/explicit_action_manifest.json"),
}
COMMIT_INFO = {
    "pgfrag": (
        "PGFrag Maintainer",
        "pgfrag@local",
        "Archive complete source and review evidence",
        "Preserves project source, fixtures, configuration, and retained diagnostic records. This archival backup does not imply scientific or physical qualification.",
    ),
    "vesselforge": (
        "A12 SynLab",
        "synlab@local",
        "Archive complete source and review evidence",
        "Preserves project source, fixtures, configuration, and retained review records. This archival backup does not imply geometry, CAD, or physical qualification.",
    ),
    "relicweave-synlab": (
        "A12 SynLab",
        "synlab@local",
        "Archive complete source and handover evidence",
        "Preserves project source, fixtures, documentation, and handover evidence. This archival backup does not imply scientific or physical qualification.",
    ),
}
COMMAND_TIMEOUT_SECONDS = 30
COPY_CHUNK_BYTES = 1024 * 1024
ADD_BATCH_PATHS = 96


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def redact_git_bytes(data: bytes) -> tuple[bytes, bool]:
    safe = GIT_URL_USERINFO_RE.sub(rb"\1[REDACTED]@", data)
    safe = GIT_AUTH_HEADER_RE.sub(rb"\1[REDACTED]", safe)
    for _label, pattern in SECRET_TEXT_PATTERNS:
        safe = pattern.sub(b"[REDACTED]", safe)
    return safe, safe != data


def sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(COPY_CHUNK_BYTES)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def git_blob_oid_file(path: Path) -> str:
    size, _ = sha256_file(path)
    digest = hashlib.sha1()
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as stream:
        while True:
            block = stream.read(COPY_CHUNK_BYTES)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def check_source_path_policy(source: Path, dest_rel: str, row: dict[str, Any], size: int) -> dict[str, int]:
    classification = str(row.get("classification", ""))
    if classification not in ALLOWED_CLASSIFICATIONS:
        if classification in GENERATED_CLASSIFICATIONS or classification.startswith("generated_"):
            raise RuntimeError(f"generated/unreviewed classification is not stageable: {classification}")
        raise RuntimeError(f"unknown or unapproved classification: {classification!r}")
    if size > 50 * 1024 * 1024:
        raise RuntimeError("source exceeds the 50 MiB closeout limit")
    if classification == "selected_bounded_replay_data" and size > 20 * 1024 * 1024:
        raise RuntimeError("selected replay data exceeds the 20 MiB bounded-data limit")
    source_parts = [part.lower() for part in source.parts]
    dest_parts = [part.lower() for part in PurePosixPath(dest_rel).parts]
    all_parts = source_parts + dest_parts
    hard_skip = {
        ".git", ".venv", "venv", "env", "node_modules", "__pycache__", "site-packages",
        ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox", "pytest-tmp", "pytest_tmp",
        ".cache", "cache", "build", "dist", "target", ".next", ".nuxt", "coverage", "htmlcov", ".shots",
        ".ssh", ".gnupg", "keyrings", "private_keys", "private-keys", "credential_store", "credential-stores",
        "installer", "installers", "buildcache", "build_cache",
    }
    if any(part in hard_skip for part in all_parts):
        raise RuntimeError(f"runtime/build/cache subtree is not stageable: {source}")
    if any(part == "runtime" or part.endswith("-runtime") or part.endswith("_runtime") or part.startswith("blender-") for part in all_parts):
        raise RuntimeError(f"runtime installation subtree is not stageable: {source}")
    binary_or_key_suffixes = {
        ".exe", ".msi", ".dll", ".so", ".dylib", ".p12", ".pfx", ".pem", ".key",
        ".pyc", ".pyo", ".whl", ".jar", ".class", ".o", ".obj", ".a", ".lib",
    }
    if any(any(part.endswith(suffix) for suffix in binary_or_key_suffixes) for part in all_parts):
        raise RuntimeError("installer, compiled runtime, or private-key path is not stageable")
    basenames = {source.name.lower(), PurePosixPath(dest_rel).name.lower()}
    if any(name == ".env" or (name.startswith(".env.") and name != ".env.example") for name in basenames):
        raise RuntimeError("environment secret path is not stageable")
    if ".env.example" in basenames and classification != "source_config_or_license":
        raise RuntimeError(".env.example is allowed only as explicit source configuration")
    if any(PATH_SECRET_RE.search(part) for part in all_parts):
        raise RuntimeError("credential-like source path is not stageable")
    force_operation = str(row.get("operation", "")).endswith("_force")
    ignore_status = row.get("destination_ignore_status")
    if force_operation and ignore_status != "ignored_exact_path_force_add_required":
        raise RuntimeError(f"force-add is not permitted without an exact ignored-path pin: {dest_rel}")
    if ignore_status == "ignored_exact_path_force_add_required" and not force_operation:
        raise RuntimeError(f"ignored destination is missing its exact force-add operation pin: {dest_rel}")
    if classification in {"selected_bounded_replay_data", "small_source_test_fixture", "source_fixture_jsonl"}:
        if size > 20 * 1024 * 1024:
            raise RuntimeError("source fixture/replay data exceeds 20 MiB")
    binary_classes = {"closed_review_figure", "root_reference_docx", "root_closeout_reference_docx", "selected_bounded_replay_data"}
    if classification in binary_classes or source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".docx", ".npz", ".npy", ".h5", ".hdf5", ".parquet", ".arrow", ".feather", ".mat"}:
        return {"text_files_scanned": 0, "text_bytes_scanned": 0, "binary_files_skipped": 1}
    scanned = 0
    total_bytes = 0
    overlap = 256
    tail = b""
    with source.open("rb") as stream:
        while True:
            block = stream.read(COPY_CHUNK_BYTES)
            if not block:
                break
            total_bytes += len(block)
            data = tail + block
            for label, pattern in SECRET_TEXT_PATTERNS:
                match = pattern.search(data)
                if match:
                    if label == "aws_access_key" and match.group(0) == b"AKIAIOSFODNN7EXAMPLE":
                        continue
                    raise RuntimeError(f"high-confidence credential pattern {label} found in a selected text source (pattern={label})")
            tail = data[-overlap:]
    scanned = 1
    return {"text_files_scanned": scanned, "text_bytes_scanned": total_bytes, "binary_files_skipped": 0}


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.writing")
    with temp.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def path_has_symlink_component(path: Path) -> bool:
    absolute = Path(os.path.abspath(os.fspath(path)))
    parts = absolute.parts
    current = Path(parts[0]) if parts else absolute
    for part in parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def posix_rel(value: str) -> str:
    result = value.replace("\\", "/")
    rel = PurePosixPath(result)
    if (
        not result
        or rel.is_absolute()
        or ":" in result
        or "\x00" in result
        or any(ord(char) < 32 for char in result)
        or any(part in ("", ".", "..") for part in rel.parts)
    ):
        raise RuntimeError(f"unsafe repository-relative path: {value!r}")
    return rel.as_posix()


def safe_origin(value: str) -> str:
    value = value.strip()
    value = redact_git_bytes(value.encode("utf-8", "surrogateescape"))[0].decode("utf-8", "surrogateescape")
    if value.startswith("git@") or value.startswith("ssh://"):
        if value.startswith("git@") and ":" in value:
            host, path = value.split(":", 1)
            return f"ssh://{host.split('@', 1)[1]}/{path.lstrip('/')}"
    parts = urlsplit(value)
    if parts.scheme and parts.hostname:
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme.lower()}://{parts.hostname.lower()}{port}{parts.path}"
    return value.rstrip("/").replace("\\", "/").lower()


def parse_nul_paths(data: bytes) -> set[str]:
    return {os.fsdecode(part).replace("\\", "/") for part in data.split(b"\0") if part}


def tree_map(data: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for record in data.split(b"\0"):
        if not record:
            continue
        meta, path_raw = record.split(b"\t", 1)
        fields = meta.split()
        if len(fields) != 3:
            raise RuntimeError("could not parse Git tree record")
        _mode, obj_type, oid = fields
        if obj_type == b"blob":
            result[os.fsdecode(path_raw).replace("\\", "/")] = oid.decode("ascii")
    return result


def index_map(data: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for record in data.split(b"\0"):
        if not record:
            continue
        meta, path_raw = record.split(b"\t", 1)
        fields = meta.split()
        if len(fields) != 3 or fields[2] != b"0":
            raise RuntimeError("unmerged or malformed Git index entry")
        result[os.fsdecode(path_raw).replace("\\", "/")] = fields[1].decode("ascii")
    return result


class GitRunner:
    def __init__(self, root: Path, log_dir: Path, receipt: dict[str, Any], git_executable: Path) -> None:
        self.root = root
        self.log_dir = log_dir
        self.git_executable = git_executable
        self.receipt = receipt
        self.sequence = 0
        self.persist_logs = False

    def run(
        self,
        repo_name: str,
        args: list[str],
        context: str,
        *,
        timeout: int = COMMAND_TIMEOUT_SECONDS,
        log_streams: bool = True,
        extra_config: tuple[tuple[str, str], ...] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        repo_root = self.root / repo_name
        argv = [str(self.git_executable), "-C", str(repo_root), "-c", "core.autocrlf=false"]
        if extra_config:
            for key, value in extra_config:
                argv.extend(["-c", f"{key}={value}"])
        argv.extend(args)
        self.sequence += 1
        started = utc_now()
        tic = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                argv,
                cwd=self.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
            stdout, stderr, returncode = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            returncode = None
            timed_out = True
        record: dict[str, Any] = {
            "repo": repo_name,
            "context": context,
            "argv": argv,
            "returncode": returncode,
            "timed_out": timed_out,
            "started_utc": started,
            "ended_utc": utc_now(),
            "elapsed_seconds": round(time.monotonic() - tic, 6),
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "stdout_sha256": sha256_bytes(stdout),
            "stderr_sha256": sha256_bytes(stderr),
        }
        if log_streams and self.persist_logs:
            logged_stdout, stdout_redacted = redact_git_bytes(stdout)
            logged_stderr, stderr_redacted = redact_git_bytes(stderr)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{self.sequence:05d}_{os.getpid()}_{time.time_ns()}_{repo_name}_{re.sub(r'[^A-Za-z0-9_.-]+', '_', context)[:48]}"
            stdout_path = self.log_dir / f"{stem}.stdout.bin"
            stderr_path = self.log_dir / f"{stem}.stderr.bin"
            stdout_path.write_bytes(logged_stdout)
            stderr_path.write_bytes(logged_stderr)
            record["stdout_path"] = str(stdout_path)
            record["stderr_path"] = str(stderr_path)
            record["stdout_redacted_for_credentials"] = stdout_redacted
            record["stderr_redacted_for_credentials"] = stderr_redacted
            record["logged_stdout_bytes"] = len(logged_stdout)
            record["logged_stderr_bytes"] = len(logged_stderr)
            record["logged_stdout_sha256"] = sha256_bytes(logged_stdout)
            record["logged_stderr_sha256"] = sha256_bytes(logged_stderr)
        self.receipt["git_commands"].append(record)
        repo_receipt = self.receipt.setdefault("repositories", {}).setdefault(repo_name, {})
        repo_receipt.setdefault("git_commands", []).append(record)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


class CloseoutExecutor:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.root = ROOT.resolve()
        self.git_executable_input = Path(args.git).absolute()
        if path_has_symlink_component(self.git_executable_input):
            raise RuntimeError("Git executable path contains a symlink component")
        self.git_executable = self.git_executable_input.resolve()
        if self.git_executable != GIT_EXE.resolve():
            raise RuntimeError("--git must name the pinned bundled Git executable")
        if not self.git_executable.is_file():
            raise RuntimeError(f"bundled Git executable missing: {self.git_executable}")
        self.manifest_path = Path(args.manifest).resolve()
        self.supplement_path_input = Path(args.supplementary).absolute() if args.supplementary else None
        if self.supplement_path_input is not None and path_has_symlink_component(self.supplement_path_input):
            raise RuntimeError("supplementary manifest path contains a symlink component")
        self.supplement_path = self.supplement_path_input.resolve() if self.supplement_path_input else None
        receipt_arg = args.receipt or str(DEFAULT_RECEIPT)
        self.receipt_path = Path(receipt_arg).resolve()
        if self.receipt_path != DEFAULT_RECEIPT.resolve():
            raise RuntimeError("the execution receipt path is fixed to closeout_20261007/execution_receipt.json")
        self.action_sha = ""
        self.supplement_sha: str | None = None
        self._receipt_was_present = False
        self.manifest: dict[str, Any] = {}
        self.actions: list[dict[str, Any]] = []
        self.repositories: dict[str, dict[str, Any]] = {}
        self.expected_by_repo: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in REPO_NAMES}
        self.expected_git_oid: dict[tuple[str, str], str] = {}
        self.policy_scan = {"actions_checked": 0, "text_files_scanned": 0, "text_bytes_scanned": 0, "binary_files_skipped": 0}
        self.receipt: dict[str, Any] = {
            "schema": "shardforge.closeout_backup_execution.v1",
            "status": "preflight_pending",
            "started_utc": utc_now(),
            "workspace_root": str(self.root),
            "repositories": {},
            "copy_receipts": [],
            "git_commands": [],
            "notes": [
                "Only explicit candidate_actions and the three mandatory reviewed supplementary exports are eligible.",
                "Every target is checked against raw source SHA-256/bytes and the staged/committed Git blob identity.",
                "Per-command core.autocrlf=false is used; repository/global Git configuration is never changed.",
                "Git command stream hashes/byte counts are over actual process output; saved log files redact high-confidence credential material.",
                "Pushes are ordinary non-force fast-forward pushes to the existing backup branch.",
            ],
        }
        self.log_dir = (self.receipt_path.parent / (self.receipt_path.stem + "_gitlogs")) if self.receipt_path else None
        if self.log_dir is None:
            self.log_dir = self.root / "tmp/backup_coordinator/closeout_20261007/execution_gitlogs"
        self.git = GitRunner(self.root, self.log_dir, self.receipt, self.git_executable)

    def verify_git_executable_pin(self) -> tuple[int, str]:
        pin = self.manifest.get("git_executable")
        if not isinstance(pin, dict):
            raise RuntimeError("action manifest has no bundled Git executable pin")
        pinned_path = Path(str(pin.get("path", ""))).resolve()
        if pinned_path != self.git_executable:
            raise RuntimeError("current bundled Git path does not match the action manifest pin")
        current_bytes, current_sha = sha256_file(self.git_executable)
        if current_bytes != pin.get("bytes") or current_sha.lower() != str(pin.get("sha256", "")).lower():
            raise RuntimeError("current bundled Git bytes/SHA-256 do not match the action manifest pin")
        self.git_executable_bytes = current_bytes
        self.git_executable_sha256 = current_sha
        return current_bytes, current_sha

    def load_plan(self) -> None:
        raw = self.manifest_path.read_bytes()
        self.action_sha = sha256_bytes(raw)
        if self.action_sha.lower() != self.args.approved_sha256.lower():
            raise RuntimeError("action manifest SHA-256 does not match --approved-sha256")
        if self.args.execute and self.args.root_go_confirmed.lower() != self.action_sha.lower():
            raise RuntimeError("execution requires --root-go-confirmed equal to the exact action-manifest SHA-256")
        self.manifest = json.loads(raw.decode("utf-8"))
        if self.manifest.get("schema") != EXPECTED_SCHEMA:
            raise RuntimeError("unexpected action manifest schema")
        if not str(self.manifest.get("mode", "")).startswith("PREPARE_ONLY"):
            raise RuntimeError("manifest is not marked as prepare-only")
        if Path(self.manifest.get("workspace_root", "")).resolve() != self.root:
            raise RuntimeError("manifest workspace root does not match this executor workspace")
        inv_path = Path(self.manifest.get("inventory_path", "")).resolve()
        if not within(inv_path, self.root):
            raise RuntimeError("inventory path escapes workspace root")
        inv_bytes, inv_sha = sha256_file(inv_path)
        if inv_sha != self.manifest.get("inventory_sha256"):
            raise RuntimeError("inventory bytes do not match the action manifest's inventory pin")
        self.repositories = self.manifest.get("repositories", {})
        if set(self.repositories) != set(REPO_NAMES):
            raise RuntimeError("action manifest must bind exactly the three approved repositories")
        for repo_name, binding in self.repositories.items():
            if binding.get("head") != binding.get("remote_head") or binding.get("remote_matches_head") is False:
                raise RuntimeError(f"manifest does not pin matching local/remote HEADs for {repo_name}")
        self.actions = list(self.manifest.get("candidate_actions", []))
        if not self.actions:
            raise RuntimeError("action manifest has no candidate actions")
        if self.supplement_path:
            supp_raw = self.supplement_path.read_bytes()
            self.supplement_sha = sha256_bytes(supp_raw)
            if not self.args.supplementary_sha256 or self.args.supplementary_sha256.lower() != self.supplement_sha.lower():
                raise RuntimeError("supplementary manifest SHA-256 is missing or mismatched")
            supplement = json.loads(supp_raw.decode("utf-8"))
            if supplement.get("schema") != "independent_supplementary_exports_v1":
                raise RuntimeError("unexpected supplementary manifest schema")
            if not str(supplement.get("mode", "")).startswith("PREPARE_ONLY"):
                raise RuntimeError("supplementary manifest is not marked prepare-only")
            if supplement.get("source_inventory_sha256") != inv_sha or supplement.get("source_action_manifest_sha256") != self.action_sha:
                raise RuntimeError("supplementary manifest is not bound to the reviewed inventory and action manifest")
            exports = supplement.get("exports", [])
            if len(exports) != len(MANDATORY_SUPPLEMENTARY):
                raise RuntimeError("supplementary manifest must contain exactly three exports")
            actual_supplementary = {
                (
                    row.get("role"),
                    row.get("destination_repo"),
                    posix_rel(str(row.get("destination_repo_relative", ""))),
                    Path(str(row.get("source_workspace_relative", ""))).as_posix(),
                )
                for row in exports
            }
            if actual_supplementary != MANDATORY_SUPPLEMENTARY:
                raise RuntimeError("supplementary manifest does not match the exact three approved role/source/destination tuples")
            for export in exports:
                row = dict(export)
                if row.get("operation") not in {"copy_then_stage_exact", "stage_existing_exact"}:
                    raise RuntimeError("supplementary export has an unapproved operation")
                role_classification = {
                    "coverage_export": "authored_documentation",
                    "source_map": "source_metadata_json",
                    "frozen_control_copy": "backup_handoff_plan_or_receipt",
                }
                role = str(row.get("role", ""))
                if role not in role_classification:
                    raise RuntimeError("supplementary export has an unapproved role")
                row["repo"] = "workspace_root_external"
                row["classification"] = role_classification[role]
                source_workspace_relative = posix_rel(str(row.get("source_workspace_relative", "")))
                row["source_absolute"] = str(self.root / Path(*PurePosixPath(source_workspace_relative).parts))
                row["_supplementary_export"] = True
                self.actions.append(row)
        elif self.args.execute:
            raise RuntimeError("execution requires the separately root-approved mandatory supplementary manifest")
        if self.args.execute:
            if not self.supplement_sha or self.args.supplementary_root_go_confirmed.lower() != self.supplement_sha.lower():
                raise RuntimeError("execution requires --root-go-supplementary-confirmed equal to the exact supplementary-manifest SHA-256")
        self.validate_actions()

    def validate_actions(self) -> None:
        seen: set[tuple[str, str]] = set()
        for row in self.actions:
            repo_name = row.get("destination_repo")
            if repo_name not in REPO_NAMES:
                raise RuntimeError(f"action has unapproved destination repository: {repo_name!r}")
            operation = row.get("operation")
            if operation not in ALLOWED_OPERATIONS:
                raise RuntimeError(f"unsupported action operation: {operation!r}")
            rel = posix_rel(str(row.get("destination_repo_relative", "")))
            key = (repo_name, rel.casefold())
            if key in seen:
                raise RuntimeError(f"duplicate destination: {repo_name}/{rel}")
            seen.add(key)
            repo_root = (self.root / repo_name).resolve()
            dest = repo_root.joinpath(*PurePosixPath(rel).parts)
            if path_has_symlink_component(dest):
                raise RuntimeError("destination path contains a symlink component")
            if not within(dest, repo_root):
                raise RuntimeError(f"destination escapes repository: {repo_name}/{rel}")
            source_input = Path(str(row.get("source_absolute", ""))).absolute()
            if path_has_symlink_component(source_input):
                raise RuntimeError("source path contains a symlink component")
            source = source_input.resolve()
            if not within(source, self.root):
                raise RuntimeError(f"source escapes workspace root: {row.get('source_absolute')!r}")
            if not source.is_file():
                raise RuntimeError("source is missing or not a regular file")
            if source.is_symlink():
                raise RuntimeError("symlink sources are not permitted in the exact-byte backup manifest")
            if row.get("_supplementary_export"):
                source_ws_rel = posix_rel(str(row.get("source_workspace_relative", "")))
                source_ws_input = Path(os.path.abspath(self.root / Path(*PurePosixPath(source_ws_rel).parts)))
                if path_has_symlink_component(source_ws_input):
                    raise RuntimeError("supplementary root-relative source contains a symlink component")
                if os.path.normcase(os.fspath(source_input)) != os.path.normcase(os.fspath(source_ws_input)):
                    raise RuntimeError("supplementary source absolute and workspace-relative paths disagree before resolution")
                source_ws_resolved = source_ws_input.resolve()
                if source.resolve() != source_ws_resolved or not within(source_ws_resolved, self.root):
                    raise RuntimeError("supplementary source does not resolve within the workspace root")
            if operation in DIRECT_STAGE_OPERATIONS and not row.get("_supplementary_export") and source.resolve() != dest.resolve(strict=False):
                if operation not in {"destination_already_same_bytes_stage_exact", "already_recoverable_same_bytes_destination"}:
                    raise RuntimeError(f"direct-stage action source is not the exact target path: {repo_name}/{rel}")
            try:
                source_size = source.stat().st_size
            except OSError as exc:
                raise RuntimeError(f"could not stat approved source: {exc}") from exc
            if source_size != int(row.get("bytes", -1)):
                raise RuntimeError(f"source pin drift: {source}")
            if operation not in COPY_OPERATIONS:
                if not dest.is_file() or dest.is_symlink():
                    raise RuntimeError(f"exact-stage destination is absent or not a regular file: {repo_name}/{rel}")
            policy_counts = check_source_path_policy(source, rel, row, source_size)
            self.policy_scan["actions_checked"] += 1
            for counter, count in policy_counts.items():
                self.policy_scan[counter] += count
            try:
                verified_size, source_sha = sha256_file(source)
            except OSError as exc:
                raise RuntimeError(f"could not read approved source: {exc}") from exc
            if verified_size != source_size or source_sha != row.get("sha256"):
                raise RuntimeError(f"source pin drift: {source}")
            if operation not in COPY_OPERATIONS:
                destination_size, destination_sha = sha256_file(dest)
                if destination_size != source_size or destination_sha != source_sha:
                    raise RuntimeError(f"exact-stage destination does not match its source pin: {repo_name}/{rel}")
            expected_blob_oid = git_blob_oid_file(source)
            self.expected_git_oid[(repo_name, rel)] = expected_blob_oid
            self.expected_by_repo[repo_name][rel] = {
                "path": rel,
                "source": source,
                "source_input": source_input,
                "bytes": source_size,
                "sha256": source_sha,
                "git_blob_oid": expected_blob_oid,
                "operation": operation,
                "force": operation.endswith("_force"),
                "row": row,
                "destination": dest,
            }

    def command_bytes(self, proc: subprocess.CompletedProcess[bytes], label: str) -> bytes:
        if proc.returncode != 0:
            self.command_text(proc, label)
        return proc.stdout

    def command_text(self, proc: subprocess.CompletedProcess[bytes], label: str) -> str:
        if proc.returncode != 0:
            stderr = redact_git_bytes(proc.stderr)[0].decode("utf-8", "replace")[:1000]
            stdout = redact_git_bytes(proc.stdout)[0].decode("utf-8", "replace")[:1000]
            raise RuntimeError(f"{label} failed with rc={proc.returncode}; stdout={stdout!r}; stderr={stderr!r}")
        return redact_git_bytes(proc.stdout)[0].decode("utf-8", "surrogateescape")

    def read_repo_state(self, repo_name: str, context: str) -> dict[str, Any]:
        repo_root = (self.root / repo_name).resolve()
        binding = self.repositories[repo_name]
        if not repo_root.is_dir():
            raise RuntimeError(f"repository root missing: {repo_root}")
        top = self.command_text(self.git.run(repo_name, ["rev-parse", "--show-toplevel"], context + "_toplevel"), "rev-parse toplevel").strip()
        if Path(top).resolve() != repo_root:
            raise RuntimeError(f"Git top-level mismatch for {repo_name}")
        branch = self.command_text(self.git.run(repo_name, ["branch", "--show-current"], context + "_branch"), "branch").strip()
        if branch != BRANCH or branch != binding.get("expected_branch", binding.get("branch")):
            raise RuntimeError(f"branch drift in {repo_name}: {branch!r}")
        head = self.command_text(self.git.run(repo_name, ["rev-parse", "HEAD"], context + "_head"), "HEAD").strip()
        object_format = self.command_text(self.git.run(repo_name, ["rev-parse", "--show-object-format"], context + "_object_format"), "object format").strip()
        if object_format != "sha1":
            raise RuntimeError(f"unsupported Git object format in {repo_name}: {object_format!r}")
        remote_url_proc = self.git.run(repo_name, ["remote", "get-url", "origin"], context + "_origin", log_streams=False)
        remote_url = self.command_text(remote_url_proc, "origin URL").strip()
        sanitized_origin = safe_origin(remote_url)
        expected_origin = safe_origin(str(binding.get("origin_sanitized", "")))
        if sanitized_origin != expected_origin:
            raise RuntimeError(f"sanitized origin mismatch in {repo_name}: {sanitized_origin!r}")
        push_url_proc = self.git.run(repo_name, ["remote", "get-url", "--push", "origin"], context + "_push_origin", log_streams=False)
        push_url = self.command_text(push_url_proc, "push origin URL").strip()
        if safe_origin(push_url) != expected_origin:
            raise RuntimeError(f"sanitized push origin mismatch in {repo_name}")
        remote = self.command_text(
            self.git.run(repo_name, ["ls-remote", "--heads", "origin", f"refs/heads/{BRANCH}"], context + "_ls_remote"),
            "ls-remote",
        ).strip()
        remote_head = remote.split()[0] if remote else None
        if remote_head is None:
            raise RuntimeError(f"remote branch missing in {repo_name}")
        tree_proc = self.git.run(repo_name, ["ls-tree", "-r", "-z", "HEAD"], context + "_head_tree", log_streams=False)
        tree = tree_map(self.command_bytes(tree_proc, "HEAD tree"))
        index_proc = self.git.run(repo_name, ["ls-files", "--stage", "-z"], context + "_index", log_streams=False)
        index = index_map(self.command_bytes(index_proc, "Git index"))
        unstaged_proc = self.git.run(repo_name, ["diff", "--name-only", "-z"], context + "_unstaged", log_streams=False)
        unstaged = parse_nul_paths(self.command_bytes(unstaged_proc, "unstaged diff"))
        staged_proc = self.git.run(repo_name, ["diff", "--cached", "--name-only", "-z"], context + "_staged", log_streams=False)
        staged = parse_nul_paths(self.command_bytes(staged_proc, "staged diff"))
        self.receipt["repositories"].setdefault(repo_name, {}).update(
            {
                "repo_root": str(repo_root),
                "branch": branch,
                "head": head,
                "remote_head": remote_head,
                "baseline_head": binding.get("head"),
                "baseline_remote_head": binding.get("remote_head"),
                "expected_parent": binding.get("head"),
                "origin_sanitized": sanitized_origin,
                "unstaged_tracked_paths": sorted(unstaged),
                "preexisting_staged_paths": sorted(staged),
            }
        )
        return {"head": head, "remote_head": remote_head, "tree": tree, "index": index, "unstaged": unstaged, "staged": staged}

    def validate_status(self, repo_name: str, state: dict[str, Any]) -> None:
        binding = self.repositories[repo_name]
        base_head = str(binding.get("head", ""))
        base_remote = str(binding.get("remote_head", ""))
        head = state["head"]
        remote = state["remote_head"]
        expected = self.expected_by_repo[repo_name]
        target_paths = set(expected)
        if state["staged"]:
            # Resume is allowed only when prior staging is an approved subset with matching raw Git blobs.
            if not state["staged"].issubset(target_paths):
                raise RuntimeError(f"unexpected pre-staged paths in {repo_name}")
            for path in state["staged"]:
                entry = expected[path]
                if state["index"].get(path) != entry["git_blob_oid"]:
                    raise RuntimeError(f"pre-staged blob differs from approved raw bytes: {repo_name}/{path}")
        if not state["unstaged"].issubset(target_paths):
            bad = sorted(state["unstaged"] - target_paths)
            raise RuntimeError(f"unexpected tracked worktree changes in {repo_name}: {bad[:20]!r}")
        if head == base_head:
            if remote not in {base_remote, base_head}:
                raise RuntimeError(f"remote advanced from approved baseline in {repo_name}")
            return
        parent_proc = self.git.run(repo_name, ["rev-parse", "HEAD^"], "resume_parent")
        parent = self.command_text(parent_proc, "resume commit parent").strip()
        if parent != base_head:
            raise RuntimeError(f"local HEAD advanced unexpectedly in {repo_name}")
        parent_tree_proc = self.git.run(repo_name, ["ls-tree", "-r", "-z", parent], "resume_parent_tree", log_streams=False)
        parent_tree = tree_map(self.command_bytes(parent_tree_proc, "resume parent tree"))
        expected_delta = {
            path for path, item in expected.items() if parent_tree.get(path) != item["git_blob_oid"]
        }
        changed_proc = self.git.run(repo_name, ["diff-tree", "--no-commit-id", "--name-only", "-r", "-z", f"{parent}..HEAD"], "resume_commit_paths", log_streams=False)
        changed = parse_nul_paths(self.command_bytes(changed_proc, "resume commit paths"))
        if changed != expected_delta:
            raise RuntimeError(f"existing local commit pathset does not match approved delta in {repo_name}")
        current_tree = state["tree"]
        for path, item in expected.items():
            if current_tree.get(path) != item["git_blob_oid"]:
                raise RuntimeError(f"existing local commit does not contain approved bytes: {repo_name}/{path}")
        if remote not in {base_remote, head}:
            raise RuntimeError(f"remote advanced unexpectedly in {repo_name}")
        self.receipt["repositories"][repo_name]["existing_approved_commit"] = {
            "commit": head,
            "parent": parent,
            "changed_paths": sorted(changed),
        }

    def preflight(self) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for repo_name in REPO_NAMES:
            state = self.read_repo_state(repo_name, "preflight")
            self.validate_status(repo_name, state)
            states[repo_name] = state
        all_destinations = {name: sorted(self.expected_by_repo[name]) for name in REPO_NAMES}
        for name, paths in all_destinations.items():
            self.receipt["repositories"].setdefault(name, {})["approved_action_paths"] = paths
        return states

    def verify_sources_and_targets(self, repo_name: str) -> dict[str, dict[str, Any]]:
        for path, item in self.expected_by_repo[repo_name].items():
            if path_has_symlink_component(item["source_input"]) or item["source_input"].resolve() != item["source"]:
                raise RuntimeError("approved source path changed into or through a symlink after preflight")
            size, digest = sha256_file(item["source"])
            if size != item["bytes"] or digest != item["sha256"]:
                raise RuntimeError(f"source pin drift before copy/stage: {item['source']}")
            dest = item["destination"]
            repo_root = (self.root / repo_name).resolve()
            if path_has_symlink_component(dest):
                raise RuntimeError("destination path changed to include a symlink after preflight")
            if not within(dest, repo_root):
                raise RuntimeError(f"destination escaped repo during recheck: {repo_name}/{path}")
            if dest.exists():
                if not dest.is_file() or dest.is_symlink():
                    raise RuntimeError(f"destination exists but is not a regular file: {dest}")
                dest_size, dest_sha = sha256_file(dest)
                if dest_size != item["bytes"] or dest_sha != item["sha256"]:
                    raise RuntimeError(f"destination collision, refusing overwrite: {dest}")
            elif item["operation"] not in COPY_OPERATIONS:
                raise RuntimeError(f"exact-stage destination disappeared: {repo_name}/{path}")
        return self.expected_by_repo[repo_name]

    def record_copy_receipt(self, repo_name: str, record: dict[str, Any]) -> None:
        self.receipt["copy_receipts"].append({"repo": repo_name, **record})
        self.receipt["repositories"].setdefault(repo_name, {}).setdefault("copy_receipts", []).append(dict(record))
        self.save_checkpoint()

    def copy_missing(self, repo_name: str) -> list[str]:
        copied: list[str] = []
        repo_root = (self.root / repo_name).resolve()
        for path, item in self.expected_by_repo[repo_name].items():
            if item["operation"] not in COPY_OPERATIONS and not (
                item["row"].get("_supplementary_export") and item["operation"] == "stage_existing_exact"
            ):
                continue
            source, dest = item["source"], item["destination"]
            if dest.exists():
                size, digest = sha256_file(dest)
                if size != item["bytes"] or digest != item["sha256"]:
                    raise RuntimeError(f"destination collision, refusing overwrite: {dest}")
                self.record_copy_receipt(
                    repo_name,
                    {
                        "destination": path,
                        "status": "already_present_exact",
                        "bytes": size,
                        "sha256": digest,
                        "supplementary_export": bool(item["row"].get("_supplementary_export")),
                    },
                )
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if path_has_symlink_component(dest):
                raise RuntimeError(f"destination path gained a symlink component: {repo_name}/{path}")
            if not within(dest, repo_root):
                raise RuntimeError(f"destination escaped repo after mkdir: {dest}")
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(prefix=".codex-closeout-copy-", dir=dest.parent, delete=False) as temp:
                    temp_path = Path(temp.name)
                    with source.open("rb") as src:
                        shutil.copyfileobj(src, temp, length=COPY_CHUNK_BYTES)
                    temp.flush()
                    os.fsync(temp.fileno())
                temp_size, temp_sha = sha256_file(temp_path)
                if temp_size != item["bytes"] or temp_sha != item["sha256"]:
                    raise RuntimeError(f"temporary copy hash mismatch for {repo_name}/{path}")
                if dest.exists():
                    raise RuntimeError(f"destination appeared during copy; refusing replace: {dest}")
                if path_has_symlink_component(dest):
                    raise RuntimeError(f"destination path gained a symlink component: {repo_name}/{path}")
                os.rename(temp_path, dest)
                temp_path = None
                copied.append(path)
                self.record_copy_receipt(
                    repo_name,
                    {"destination": path, "status": "copied_exact", "bytes": temp_size, "sha256": temp_sha,
                     "supplementary_export": bool(item["row"].get("_supplementary_export"))},
                )
            finally:
                if temp_path is not None and temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
        return copied

    def save_checkpoint(self) -> None:
        if self.receipt_path is not None:
            atomic_json(self.receipt_path, self.receipt)

    def resume_receipt_if_present(self) -> None:
        if self.receipt_path is None:
            return
        if self.receipt_path.exists():
            self._receipt_was_present = True
            previous = json.loads(self.receipt_path.read_text(encoding="utf-8"))
            if previous.get("schema") != "shardforge.closeout_backup_execution.v1":
                raise RuntimeError("existing receipt has an unexpected schema")
            if previous.get("action_manifest_sha256", "").lower() != self.action_sha.lower():
                raise RuntimeError("existing receipt is pinned to a different action manifest")
            if previous.get("supplementary_manifest_sha256") != self.supplement_sha:
                raise RuntimeError("existing receipt is pinned to a different supplementary manifest")
            if Path(previous.get("receipt_path", "")).resolve() != self.receipt_path:
                raise RuntimeError("existing receipt path identity mismatch")
            if previous.get("root_go_sha256", "").lower() != self.args.root_go_confirmed.lower():
                raise RuntimeError("existing receipt lacks the same explicit root GO pin")
            if previous.get("root_go_supplementary_confirmed_sha256", "").lower() != self.args.root_go_supplementary_confirmed.lower():
                raise RuntimeError("existing receipt lacks the same explicit supplementary root GO pin")
            self.receipt = previous
            self.git.receipt = self.receipt
            self.git.sequence = len(self.receipt.get("git_commands", []))
            if self.log_dir.exists() and not self.log_dir.is_dir():
                raise RuntimeError("existing execution log path is not a directory")
        elif self.log_dir.exists():
            raise RuntimeError("execution log directory exists without its receipt; refusing reuse")

    def target_delta(self, repo_name: str, head_tree: dict[str, str]) -> set[str]:
        return {
            path
            for path, item in self.expected_by_repo[repo_name].items()
            if head_tree.get(path) != item["git_blob_oid"]
        }

    def stage_expected(self, repo_name: str) -> dict[str, Any]:
        state = self.read_repo_state(repo_name, "before_stage")
        self.validate_status(repo_name, state)
        expected = self.expected_by_repo[repo_name]
        delta = self.target_delta(repo_name, state["tree"])
        prior_staged = set(state["staged"])
        for path in prior_staged:
            if path not in delta:
                raise RuntimeError(f"pre-staged path is already exact in HEAD; refusing no-op stage: {repo_name}/{path}")
        request_paths = sorted(delta - prior_staged)
        force_paths = {p for p in request_paths if expected[p]["force"]}
        regular_paths = set(request_paths) - force_paths
        for path in force_paths:
            if expected[path]["row"].get("destination_ignore_status") != "ignored_exact_path_force_add_required":
                raise RuntimeError(f"-f requested for a path not pinned as ignored: {repo_name}/{path}")
        if set(request_paths) & set(prior_staged):
            raise RuntimeError("staged path overlap invariant failed")
        repo_receipt = self.receipt["repositories"].setdefault(repo_name, {})
        previously_requested = set(repo_receipt.get("git_add_requested_paths", []))
        repo_receipt["git_add_requested_paths"] = sorted(previously_requested | set(request_paths) | prior_staged)
        self.receipt["repositories"].setdefault(repo_name, {})["expected_changed_paths"] = sorted(delta)
        self.receipt["repositories"][repo_name]["preexisting_staged_paths"] = sorted(prior_staged)
        self.save_checkpoint()
        for force, paths in ((False, sorted(regular_paths)), (True, sorted(force_paths))):
            for offset in range(0, len(paths), ADD_BATCH_PATHS):
                batch = paths[offset : offset + ADD_BATCH_PATHS]
                if not batch:
                    continue
                pathspecs = [f":(literal){path}" for path in batch]
                args = ["add"]
                if force:
                    args.append("--force")
                args.extend(["--", *pathspecs])
                proc = self.git.run(repo_name, args, "add_force_exact" if force else "add_exact")
                self.save_checkpoint()
                self.command_text(proc, "git add")
        staged_proc = self.git.run(repo_name, ["diff", "--cached", "--name-only", "-z"], "verify_staged_paths", log_streams=False)
        staged = parse_nul_paths(self.command_bytes(staged_proc, "staged paths"))
        unstaged_proc = self.git.run(repo_name, ["diff", "--name-only", "-z"], "verify_unstaged_paths", log_streams=False)
        unstaged = parse_nul_paths(self.command_bytes(unstaged_proc, "unstaged paths"))
        if staged != delta:
            raise RuntimeError(f"staged path set does not equal expected changed subset in {repo_name}")
        if unstaged:
            raise RuntimeError(f"tracked unstaged paths remain after exact stage in {repo_name}: {sorted(unstaged)[:20]!r}")
        index_proc = self.git.run(repo_name, ["ls-files", "--stage", "-z"], "verify_index_blobs", log_streams=False)
        index = index_map(self.command_bytes(index_proc, "Git index blobs"))
        for path, item in expected.items():
            target_oid = index.get(path) if path in delta else state["tree"].get(path)
            if target_oid != item["git_blob_oid"]:
                raise RuntimeError(f"staged/HEAD blob differs from approved raw bytes: {repo_name}/{path}")
        self.receipt["repositories"][repo_name]["staged_paths"] = sorted(staged)
        self.save_checkpoint()
        return {"delta": delta, "staged": staged, "state": state}

    def current_commit(self, repo_name: str, expected_delta: set[str]) -> str:
        repo_state = self.read_repo_state(repo_name, "before_commit")
        self.validate_status(repo_name, repo_state)
        baseline = str(self.repositories[repo_name]["head"])
        if repo_state["head"] != baseline:
            # Validate a commit made by an earlier interrupted invocation; never duplicate it.
            self.validate_status(repo_name, repo_state)
            parent = self.command_text(self.git.run(repo_name, ["rev-parse", "HEAD^"], "verify_existing_commit_parent"), "commit parent").strip()
            parent_tree_proc = self.git.run(repo_name, ["ls-tree", "-r", "-z", parent], "verify_existing_parent_tree", log_streams=False)
            parent_tree = tree_map(self.command_bytes(parent_tree_proc, "existing parent tree"))
            expected_base_delta = self.target_delta(repo_name, parent_tree)
            changed_proc = self.git.run(repo_name, ["diff-tree", "--no-commit-id", "--name-only", "-r", "-z", f"{parent}..HEAD"], "verify_existing_commit_paths", log_streams=False)
            changed = parse_nul_paths(self.command_bytes(changed_proc, "existing commit paths"))
            if parent != baseline or changed != expected_base_delta:
                raise RuntimeError(f"existing commit is not the exact approved closeout delta in {repo_name}")
            self.receipt["repositories"].setdefault(repo_name, {}).update({"head_after_commit": repo_state["head"], "parent": parent, "changed_paths_exact": True})
            self.receipt["repositories"][repo_name]["changed_paths"] = sorted(changed)
            self.receipt["repositories"][repo_name].setdefault("commit_attempted", False)
            self.receipt["repositories"][repo_name].setdefault("commit_returncode", None)
            self.save_checkpoint()
            return repo_state["head"]
        if not expected_delta:
            self.receipt["repositories"].setdefault(repo_name, {}).update({"head_after_commit": baseline, "parent": None, "changed_paths_exact": True, "no_commit_needed": True, "commit_attempted": False, "commit_returncode": None})
            self.receipt["repositories"].setdefault(repo_name, {})["changed_paths"] = []
            self.save_checkpoint()
            return baseline
        if repo_state["staged"] != expected_delta:
            raise RuntimeError(f"cannot commit: staged set is not the exact expected delta in {repo_name}")
        name, email, subject, body = COMMIT_INFO[repo_name]
        message = subject + "\n\n" + body
        proc = self.git.run(
            repo_name,
            ["commit", "-m", message],
            "commit_exact",
            extra_config=(("user.name", name), ("user.email", email)),
        )
        self.receipt["repositories"].setdefault(repo_name, {})["commit_attempted"] = True
        self.receipt["repositories"][repo_name]["commit_returncode"] = proc.returncode
        self.save_checkpoint()
        # Identity is supplied per command and never written to repository/global config.
        # Re-run is never attempted if the commit succeeded but receipt writing later fails.
        if proc.returncode != 0:
            safe_stderr = redact_git_bytes(proc.stderr)[0].decode("utf-8", "replace")[:1000]
            raise RuntimeError(f"git commit failed in {repo_name}: {safe_stderr}")
        new_head = self.command_text(self.git.run(repo_name, ["rev-parse", "HEAD"], "post_commit_head"), "post-commit HEAD").strip()
        parent = self.command_text(self.git.run(repo_name, ["rev-parse", "HEAD^"], "post_commit_parent"), "post-commit parent").strip()
        if parent != baseline:
            raise RuntimeError(f"commit parent drift after commit in {repo_name}")
        changed_proc = self.git.run(repo_name, ["diff-tree", "--no-commit-id", "--name-only", "-r", "-z", f"{parent}..{new_head}"], "post_commit_paths", log_streams=False)
        changed = parse_nul_paths(self.command_bytes(changed_proc, "post-commit paths"))
        if changed != expected_delta:
            raise RuntimeError(f"commit changed path set differs from expected delta in {repo_name}")
        tree_proc = self.git.run(repo_name, ["ls-tree", "-r", "-z", new_head], "post_commit_tree", log_streams=False)
        tree = tree_map(self.command_bytes(tree_proc, "post-commit tree"))
        for path, item in self.expected_by_repo[repo_name].items():
            if tree.get(path) != item["git_blob_oid"]:
                raise RuntimeError(f"committed Git blob differs from approved raw bytes: {repo_name}/{path}")
        self.receipt["repositories"].setdefault(repo_name, {}).update({"head_after_commit": new_head, "parent": parent})
        self.receipt["repositories"][repo_name]["changed_paths_exact"] = True
        self.receipt["repositories"][repo_name]["changed_paths"] = sorted(changed)
        self.save_checkpoint()
        return new_head

    def push_and_verify(self, repo_name: str, local_head: str) -> str:
        branch = self.command_text(self.git.run(repo_name, ["branch", "--show-current"], "pre_push_branch"), "pre-push branch").strip()
        if branch != BRANCH:
            raise RuntimeError(f"branch changed before push in {repo_name}")
        remote_data = self.command_text(
            self.git.run(repo_name, ["ls-remote", "--heads", "origin", f"refs/heads/{BRANCH}"], "pre_push_remote"),
            "pre-push ls-remote",
        ).strip()
        remote_head = remote_data.split()[0] if remote_data else None
        baseline = str(self.repositories[repo_name]["head"])
        if remote_head not in {baseline, local_head}:
            raise RuntimeError(f"remote advanced before push in {repo_name}; refusing non-fast-forward overwrite")
        repo_receipt = self.receipt["repositories"].setdefault(repo_name, {})
        repo_receipt["push_attempted"] = True
        repo_receipt["remote_head_before_push"] = remote_head
        self.save_checkpoint()
        proc = self.git.run(
            repo_name,
            ["push", "--porcelain", "origin", f"refs/heads/{BRANCH}:refs/heads/{BRANCH}"],
            "push_non_force",
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        self.receipt["repositories"][repo_name]["push_returncode"] = proc.returncode
        self.receipt["repositories"][repo_name]["push_exit_code"] = proc.returncode
        self.save_checkpoint()
        if proc.returncode != 0:
            safe_stderr = redact_git_bytes(proc.stderr)[0].decode("utf-8", "replace")[:1200]
            raise RuntimeError(f"non-force push failed in {repo_name}: {safe_stderr}")
        verify_data = self.command_text(
            self.git.run(repo_name, ["ls-remote", "--heads", "origin", f"refs/heads/{BRANCH}"], "post_push_remote"),
            "post-push ls-remote",
        ).strip()
        verified = verify_data.split()[0] if verify_data else None
        if verified != local_head:
            raise RuntimeError(f"remote HEAD did not verify after push in {repo_name}")
        push_status = "already_up_to_date_push_and_verified" if remote_head == local_head else "pushed_and_verified"
        self.receipt["repositories"].setdefault(repo_name, {}).update({"push_status": push_status, "remote_head_after_push": verified})
        self.save_checkpoint()
        return verified

    def verify_final(self, repo_name: str, final_head: str) -> None:
        state = self.read_repo_state(repo_name, "final_verify")
        if state["head"] != final_head or state["remote_head"] != final_head:
            raise RuntimeError(f"final local/remote HEAD mismatch in {repo_name}")
        if state["staged"] or state["unstaged"]:
            raise RuntimeError(f"tracked/index state is not clean after commit in {repo_name}")
        for path, item in self.expected_by_repo[repo_name].items():
            if state["tree"].get(path) != item["git_blob_oid"]:
                raise RuntimeError(f"final approved destination blob mismatch in {repo_name}/{path}")
        self.receipt["repositories"][repo_name].update(
            {
                "final_head": state["head"],
                "final_remote_head": state["remote_head"],
                "tracked_unstaged_paths_after": sorted(state["unstaged"]),
                "staged_paths_after": sorted(state["staged"]),
                "approved_destination_count": len(self.expected_by_repo[repo_name]),
            }
        )
        self.save_checkpoint()

    def run(self) -> dict[str, Any]:
        self.load_plan()
        git_bytes, git_sha = self.verify_git_executable_pin()
        self.receipt.update(
            {
                "action_manifest_path": str(self.manifest_path),
                "action_manifest_sha256": self.action_sha,
                "git_executable": str(self.git_executable),
                "git_executable_bytes": git_bytes,
                "git_executable_sha256": git_sha,
                "source_policy_scan": dict(self.policy_scan),
                "inventory_path": self.manifest.get("inventory_path"),
                "inventory_sha256": self.manifest.get("inventory_sha256"),
                "supplementary_manifest_path": str(self.supplement_path) if self.supplement_path else None,
                "supplementary_manifest_sha256": self.supplement_sha,
                "receipt_path": str(self.receipt_path) if self.receipt_path else None,
                "root_go_sha256": self.args.root_go_confirmed if self.args.execute else None,
                "root_go_supplementary_confirmed_sha256": self.args.supplementary_root_go_confirmed if self.args.execute else None,
                "approved_path_counts": {name: len(self.expected_by_repo[name]) for name in REPO_NAMES},
                "repository_baselines": {
                    name: {
                        "branch": self.repositories[name].get("expected_branch", self.repositories[name].get("branch")),
                        "head": self.repositories[name].get("head"),
                        "parent": self.repositories[name].get("parent"),
                        "remote_head": self.repositories[name].get("remote_head"),
                        "origin_sanitized": self.repositories[name].get("origin_sanitized"),
                    }
                    for name in REPO_NAMES
                },
                "receipt_pointers": {name: f"#/repositories/{name}" for name in REPO_NAMES},
            }
        )
        states = self.preflight()
        if not self.args.execute:
            self.receipt["status"] = "preflight_passed_no_mutations"
            self.receipt["action_manifest_path"] = str(self.manifest_path)
            self.receipt["action_manifest_sha256"] = self.action_sha
            self.receipt["approved_path_counts"] = {name: len(self.expected_by_repo[name]) for name in REPO_NAMES}
            return self.receipt
        if self.receipt_path is None:
            raise RuntimeError("--receipt is required for execution")
        if not within(self.receipt_path, self.root) or any(within(self.receipt_path, self.root / name) for name in REPO_NAMES):
            raise RuntimeError("execution receipt must be in workspace-root metadata outside all repositories")
        if not within(self.log_dir, self.root) or any(within(self.log_dir, self.root / name) for name in REPO_NAMES):
            raise RuntimeError("execution log directory must be in workspace-root metadata outside all repositories")
        self.resume_receipt_if_present()
        if not self._receipt_was_present:
            for repo_name, state in states.items():
                if state["head"] != self.repositories[repo_name].get("head"):
                    raise RuntimeError(f"local HEAD advanced without an execution receipt in {repo_name}")
                if state["remote_head"] != self.repositories[repo_name].get("remote_head"):
                    raise RuntimeError(f"remote HEAD advanced without an execution receipt in {repo_name}")
                if state["staged"]:
                    raise RuntimeError(f"index is staged without an execution receipt in {repo_name}")
        self.receipt.update(
            {
                "action_manifest_path": str(self.manifest_path),
                "action_manifest_sha256": self.action_sha,
                "git_executable": str(self.git_executable),
                "git_executable_bytes": git_bytes,
                "git_executable_sha256": git_sha,
                "inventory_path": self.manifest.get("inventory_path"),
                "inventory_sha256": self.manifest.get("inventory_sha256"),
                "source_policy_scan": dict(self.policy_scan),
                "supplementary_manifest_path": str(self.supplement_path) if self.supplement_path else None,
                "supplementary_manifest_sha256": self.supplement_sha,
                "receipt_path": str(self.receipt_path),
                "root_go_sha256": self.args.root_go_confirmed,
                "approved_path_counts": {name: len(self.expected_by_repo[name]) for name in REPO_NAMES},
                "root_go_supplementary_confirmed_sha256": self.args.supplementary_root_go_confirmed if self.args.execute else None,
            }
        )
        if self.receipt.get("status") == "complete":
            for repo_name in REPO_NAMES:
                final_head = self.receipt.get("repositories", {}).get(repo_name, {}).get("final_head")
                if not final_head:
                    raise RuntimeError(f"completed receipt lacks final HEAD for {repo_name}")
                self.verify_final(repo_name, final_head)
            return self.receipt
        self.git.persist_logs = True
        self.receipt["status"] = "execution_started"
        self.save_checkpoint()
        final_heads: dict[str, str] = {}
        for repo_name in REPO_NAMES:
            self.verify_sources_and_targets(repo_name)
            self.copy_missing(repo_name)
            self.verify_sources_and_targets(repo_name)
            # Refresh branch/HEAD after copies; copying must not alter Git state.
            state = self.read_repo_state(repo_name, "post_copy")
            self.validate_status(repo_name, state)
            staged = self.stage_expected(repo_name)
            final_head = self.current_commit(repo_name, staged["delta"])
            self.receipt["repositories"].setdefault(repo_name, {})["head_after_commit"] = final_head
            self.save_checkpoint()
            self.verify_sources_and_targets(repo_name)
            before_push = self.read_repo_state(repo_name, "pre_push_verify")
            self.validate_status(repo_name, before_push)
            if before_push["head"] != final_head or before_push["staged"] or before_push["unstaged"]:
                raise RuntimeError(f"local state is not clean at approved HEAD before push in {repo_name}")
            for path, item in self.expected_by_repo[repo_name].items():
                if before_push["tree"].get(path) != item["git_blob_oid"]:
                    raise RuntimeError(f"pre-push HEAD blob mismatch: {repo_name}/{path}")
            remote_head = self.push_and_verify(repo_name, final_head)
            final_heads[repo_name] = final_head
            self.verify_final(repo_name, final_head)
            self.receipt["repositories"][repo_name]["remote_head_after_push"] = remote_head
            self.save_checkpoint()
        self.receipt["status"] = "complete"
        self.receipt["completed_utc"] = utc_now()
        self.save_checkpoint()
        return self.receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exact-manifest closeout backup executor; no broad Git staging.")
    parser.add_argument("--manifest", default=str(ROOT / "tmp/backup_coordinator/closeout_20261007/explicit_action_manifest.json"))
    parser.add_argument("--git", default=str(GIT_EXE), help="Pinned bundled Git executable; must match this workspace runtime")
    parser.add_argument("--approved-sha256", required=True, help="Exact reviewed SHA-256 of the action manifest")
    parser.add_argument("--supplementary", help="Exact separately reviewed mandatory supplementary export manifest (required for execution)")
    parser.add_argument("--supplementary-sha256", help="Exact reviewed SHA-256 for --supplementary")
    parser.add_argument("--root-go-supplementary-confirmed", dest="supplementary_root_go_confirmed", default="", help="Must equal the separately reviewed supplementary-manifest SHA after root GO")
    parser.add_argument("--execute", action="store_true", help="Perform exact copies, staging, commits, and non-force pushes")
    parser.add_argument("--root-go-confirmed", default="", help="Must equal the exact action-manifest SHA after root GO")
    parser.add_argument("--receipt", help="Workspace-root aggregate receipt path (default: closeout_20261007/execution_receipt.json)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = CloseoutExecutor(args).run()
    except Exception as exc:
        print(json.dumps({"status": "failed_closed", "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
