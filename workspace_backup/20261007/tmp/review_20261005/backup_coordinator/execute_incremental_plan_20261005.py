from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import re
from typing import Any


ROOT = pathlib.Path(r"C:\Users\xiemo\Desktop\ShardForge")
COORD = ROOT / "tmp" / "review_20261005" / "backup_coordinator"
PLAN = COORD / "next_incremental_backup_plan_20261005_v1.json"
RECEIPT = COORD / "next_incremental_backup_execution_receipt_20261005.json"
EXPECTED_PLAN_SHA256 = "44067acff8d4350c57b62503be557ae13a54fd26443f3701adb03bc26beeb905"
GIT = pathlib.Path(r"C:\Users\xiemo\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe")
BRANCH = "backup/forge-work-20261003"
REPOS = {
    "pgfrag": ROOT / "pgfrag",
    "vesselforge": ROOT / "vesselforge",
}
IDENTITIES = {
    "pgfrag": ("PGFrag Maintainer", "pgfrag@local"),
    "vesselforge": ("A12 SynLab", "synlab@local"),
}
MESSAGES = {
    "pgfrag": "Back up bounded EFGM, run03, and ROI diagnostic evidence",
    "vesselforge": "Back up v2 finite wall probe evidence (global status unknown)",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_git(repo: pathlib.Path, *args: str, allow_failure: bool = False) -> dict[str, Any]:
    argv = [str(GIT), "-c", "core.autocrlf=false", "-C", str(repo), *args]
    completed = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout_text = completed.stdout.decode("utf-8", "replace")
    stderr_text = completed.stderr.decode("utf-8", "replace")
    if "cat-file" in args and "blob" in args:
        stdout_text = f"<blob bytes={len(completed.stdout)} sha256={sha256(completed.stdout)}>"
    stdout_text = re.sub(r"(https?://)[^/@\s]+@", r"\1<redacted>@", stdout_text)
    stderr_text = re.sub(r"(https?://)[^/@\s]+@", r"\1<redacted>@", stderr_text)
    item = {
        "argv": argv,
        "returncode": completed.returncode,
        "stdout": stdout_text,
        "stderr": stderr_text,
    }
    COMMANDS.append(item)
    if completed.returncode != 0 and not allow_failure:
        raise RuntimeError(f"git command failed ({completed.returncode}): {args!r}: {item['stderr']}")
    return {**item, "stdout_bytes": completed.stdout}


def write_receipt() -> None:
    RECEIPT.write_text(json.dumps(RECORD, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def repo_path(repo: pathlib.Path, rel: str) -> pathlib.Path:
    rel_path = pathlib.PurePosixPath(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts or not rel_path.parts:
        raise RuntimeError(f"unsafe repository-relative path: {rel!r}")
    result = repo.joinpath(*rel_path.parts)
    resolved_parent = result.parent.resolve()
    try:
        resolved_parent.relative_to(repo.resolve())
    except ValueError:
        raise RuntimeError(f"destination parent escapes repository: {rel!r}")
    return result


def object_at(repo: pathlib.Path, spec: str) -> tuple[str, bytes]:
    oid_result = run_git(repo, "rev-parse", "--verify", spec)
    oid = oid_result["stdout"].strip()
    data = run_git(repo, "cat-file", "blob", oid)["stdout_bytes"]
    return oid, data


def current_ref(repo: pathlib.Path) -> str:
    return run_git(repo, "rev-parse", "HEAD")["stdout"].strip()


def remote_ref(repo: pathlib.Path) -> str:
    result = run_git(repo, "ls-remote", "origin", f"refs/heads/{BRANCH}")["stdout"].strip()
    parts = result.split()
    if len(parts) != 2 or parts[1] != f"refs/heads/{BRANCH}":
        raise RuntimeError(f"remote branch lookup returned unexpected result: {result!r}")
    return parts[0]


def git_paths(repo: pathlib.Path, *args: str) -> list[str]:
    data = run_git(repo, *args)["stdout_bytes"]
    return [item.decode("utf-8", "strict") for item in data.split(b"\0") if item]


def expected_pin(path: pathlib.Path, expected_bytes: int, expected_sha256: str, label: str) -> bytes:
    data = path.read_bytes()
    if len(data) != expected_bytes or sha256(data) != expected_sha256:
        raise RuntimeError(
            f"pin mismatch for {label}: got {len(data)} bytes sha256={sha256(data)}; "
            f"expected {expected_bytes} bytes sha256={expected_sha256}"
        )
    return data


def main() -> None:
    plan_bytes = PLAN.read_bytes()
    plan_sha = sha256(plan_bytes)
    if plan_sha != EXPECTED_PLAN_SHA256:
        raise RuntimeError(f"approved plan SHA mismatch: found {plan_sha}, expected {EXPECTED_PLAN_SHA256}")
    plan = json.loads(plan_bytes)
    entries = [entry for group in plan["groups"] for entry in group["entries"]]
    if len(entries) != 48 or plan["limits"]["actual_new_bytes"] != 3_621_822:
        raise RuntimeError(f"approved roster shape mismatch: {len(entries)} entries / {plan['limits']!r}")
    if plan["limits"]["max_new_files"] != 60 or plan["limits"]["max_new_bytes"] != 10_485_760:
        raise RuntimeError("roster limits differ from approved scope")
    if {entry["repo"] for entry in entries} != set(REPOS):
        raise RuntimeError("roster repository set differs from approved scope")

    RECORD.update({
        "status": "PREFLIGHT_IN_PROGRESS",
        "plan_path": str(PLAN),
        "plan_sha256": plan_sha,
        "plan_bytes": len(plan_bytes),
        "approved_file_count": len(entries),
        "approved_total_bytes": plan["limits"]["actual_new_bytes"],
        "scope": "exact approved 48-entry PG/VF plan only",
        "repo_records": {},
        "commands": COMMANDS,
    })
    write_receipt()

    entries_by_repo: dict[str, list[dict[str, Any]]] = {name: [] for name in REPOS}
    destinations_seen: set[tuple[str, str]] = set()
    source_pins: dict[tuple[str, str], bytes] = {}
    for entry in entries:
        repo_name = entry["repo"]
        rel = entry["destination_repo_path"]
        key = (repo_name, rel.casefold())
        if key in destinations_seen:
            raise RuntimeError(f"duplicate destination in approved manifest: {key!r}")
        destinations_seen.add(key)
        if entry["operation"] not in {"copy_then_stage", "stage_existing"}:
            raise RuntimeError(f"unapproved operation in roster: {entry['operation']!r}")
        src = pathlib.Path(entry["source_path"])
        data = expected_pin(src, entry["bytes"], entry["sha256"], str(src))
        source_pins[(repo_name, rel)] = data
        target = repo_path(REPOS[repo_name], rel)
        if entry["operation"] == "copy_then_stage":
            if target.exists():
                raise RuntimeError(f"approved copy destination now exists; stopping: {target}")
        else:
            if pathlib.Path(entry["source_repo_path"]).as_posix() != rel:
                raise RuntimeError(f"stage_existing source and destination differ: {entry!r}")
            if not target.is_file():
                raise RuntimeError(f"stage_existing target missing: {target}")
            if target.read_bytes() != data:
                raise RuntimeError(f"stage_existing target differs from pinned source: {target}")
        entries_by_repo[repo_name].append(entry)

    # Read-only preflight for both repositories before any copy.
    preflight: dict[str, dict[str, Any]] = {}
    for repo_name, repo in REPOS.items():
        base = plan["baseline_after_previous_backup"]["repos"][repo_name]
        branch = run_git(repo, "branch", "--show-current")["stdout"].strip()
        head = current_ref(repo)
        remote = remote_ref(repo)
        origin = run_git(repo, "remote", "get-url", "origin")["stdout"].strip()
        staged = run_git(repo, "diff", "--cached", "--quiet", allow_failure=True)
        if staged["returncode"] not in (0, 1):
            raise RuntimeError(f"could not determine index cleanliness in {repo_name}")
        if staged["returncode"] != 0:
            raise RuntimeError(f"index has staged changes in {repo_name}; refusing to mix commits")
        if branch != BRANCH or head != base["head"] or remote != base["remote_head"]:
            raise RuntimeError(
                f"branch/HEAD/remote changed in {repo_name}: branch={branch} head={head} remote={remote}"
            )
        if origin != base["origin"]:
            raise RuntimeError(f"origin URL changed in {repo_name}: {origin!r}")
        all_dest_rel = [e["destination_repo_path"] for e in entries_by_repo[repo_name]]
        attr_args = ["check-attr", "-z", "text", "eol", "filter", "working-tree-encoding", "crlf", "--", *all_dest_rel]
        attr_bytes = run_git(repo, *attr_args)["stdout_bytes"]
        attr_fields = [field.decode("utf-8", "strict") for field in attr_bytes.split(b"\0") if field]
        if len(attr_fields) % 3:
            raise RuntimeError(f"unexpected git check-attr output for {repo_name}")
        attr_rows = [attr_fields[i:i + 3] for i in range(0, len(attr_fields), 3)]
        transforming = [row for row in attr_rows if row[1] in {"text", "eol", "filter", "working-tree-encoding", "crlf"} and row[2] not in {"unspecified", "unset"}]
        if transforming:
            raise RuntimeError(f"Git attributes may transform pinned bytes in {repo_name}: {transforming!r}")
        preflight[repo_name] = {
            "branch": branch,
            "head_before": head,
            "remote_head_before": remote,
            "origin": origin,
            "index_clean": True,
            "attribute_rows": attr_rows,
            "entry_count": len(entries_by_repo[repo_name]),
            "worktree_status_before": run_git(repo, "status", "--porcelain=v1", "--untracked-files=all")["stdout"],
        }
    RECORD["status"] = "PREFLIGHT_PASS_COPYING"
    RECORD["repo_records"] = {name: {"preflight": preflight[name]} for name in REPOS}
    write_receipt()

    # Copy only exact manifest destinations; no overwrites.
    copied: dict[str, list[str]] = {name: [] for name in REPOS}
    for repo_name, group_entries in entries_by_repo.items():
        repo = REPOS[repo_name]
        for entry in group_entries:
            if entry["operation"] != "copy_then_stage":
                continue
            rel = entry["destination_repo_path"]
            dst = repo_path(repo, rel)
            if dst.exists():
                raise RuntimeError(f"copy destination appeared after preflight; stopping: {dst}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            payload = source_pins[(repo_name, rel)]
            with tempfile.NamedTemporaryFile(prefix="backup-copy-", dir=COORD, delete=False) as tmp:
                tmp_path = pathlib.Path(tmp.name)
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
            if tmp_path.stat().st_size != entry["bytes"] or sha256(tmp_path.read_bytes()) != entry["sha256"]:
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError(f"temporary copy failed pin check for {repo_name}:{rel}")
            try:
                os.rename(tmp_path, dst)
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise
            actual = dst.read_bytes()
            if len(actual) != entry["bytes"] or sha256(actual) != entry["sha256"]:
                raise RuntimeError(f"copied file failed pin check for {repo_name}:{rel}")
            copied[repo_name].append(rel)
            RECORD["repo_records"][repo_name]["copied_paths"] = copied[repo_name][:]
            RECORD["status"] = "COPY_IN_PROGRESS"
            write_receipt()

    for repo_name, repo in REPOS.items():
        RECORD["status"] = f"STAGING_{repo_name.upper()}"
        write_receipt()
        rel_paths = [e["destination_repo_path"] for e in entries_by_repo[repo_name]]
        run_git(repo, "add", "--", *rel_paths)
        staged_paths = git_paths(repo, "diff", "--cached", "--name-only", "-z")
        allowed = set(rel_paths)
        if not set(staged_paths).issubset(allowed):
            raise RuntimeError(f"unexpected staged paths in {repo_name}: {sorted(set(staged_paths) - allowed)!r}")
        if not staged_paths:
            raise RuntimeError(f"no staged changes in {repo_name}; refusing empty commit")

        expected_by_rel = {e["destination_repo_path"]: e for e in entries_by_repo[repo_name]}
        blob_checks = []
        for rel, entry in expected_by_rel.items():
            stage_spec = ":" + rel
            try:
                oid, blob = object_at(repo, stage_spec)
            except RuntimeError:
                # If a path is skipped as clean and absent from the index (should be impossible for planned source files), stop.
                raise RuntimeError(f"approved path missing from index after exact add: {repo_name}:{rel}")
            actual_sha = sha256(blob)
            if len(blob) != entry["bytes"] or actual_sha != entry["sha256"]:
                raise RuntimeError(
                    f"staged blob pin mismatch for {repo_name}:{rel}: {len(blob)} bytes sha256={actual_sha}; "
                    f"expected {entry['bytes']} bytes sha256={entry['sha256']}"
                )
            blob_checks.append({"path": rel, "git_blob_oid": oid, "bytes": len(blob), "sha256": actual_sha})
        RECORD["repo_records"][repo_name].update({
            "staged_paths": staged_paths,
            "staged_path_count": len(staged_paths),
            "all_roster_index_blobs_verified": True,
            "index_blob_checks": blob_checks,
        })
        write_receipt()

        parent = current_ref(repo)
        author_name, author_email = IDENTITIES[repo_name]
        commit_args = [
            "-c", f"user.name={author_name}",
            "-c", f"user.email={author_email}",
            "commit", "-m", MESSAGES[repo_name],
        ]
        # run_git adds only core.autocrlf=false globally for this single command.
        run_git(repo, *commit_args)
        commit = current_ref(repo)
        committed_paths = git_paths(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "HEAD")
        if not set(committed_paths).issubset(allowed):
            raise RuntimeError(f"commit includes paths outside approved roster in {repo_name}: {committed_paths!r}")
        committed_blob_checks = []
        for rel, entry in expected_by_rel.items():
            oid, blob = object_at(repo, f"HEAD:{rel}")
            actual_sha = sha256(blob)
            if len(blob) != entry["bytes"] or actual_sha != entry["sha256"]:
                raise RuntimeError(
                    f"committed blob pin mismatch for {repo_name}:{rel}: {len(blob)} bytes sha256={actual_sha}; "
                    f"expected {entry['bytes']} bytes sha256={entry['sha256']}"
                )
            committed_blob_checks.append({"path": rel, "git_blob_oid": oid, "bytes": len(blob), "sha256": actual_sha})
        RECORD["repo_records"][repo_name].update({
            "parent_commit": parent,
            "commit": commit,
            "commit_message": MESSAGES[repo_name],
            "committed_paths": committed_paths,
            "committed_path_count": len(committed_paths),
            "all_approved_HEAD_blobs_verified": True,
            "head_blob_checks": committed_blob_checks,
            "status": "COMMIT_VERIFIED_PUSH_PENDING",
        })
        RECORD["status"] = f"PUSHING_{repo_name.upper()}"
        write_receipt()

        run_git(repo, "push", "origin", BRANCH)
        remote_after = remote_ref(repo)
        if remote_after != commit:
            raise RuntimeError(f"remote head mismatch after push in {repo_name}: {remote_after} != {commit}")
        if current_ref(repo) != commit:
            raise RuntimeError(f"local HEAD changed after push in {repo_name}")
        RECORD["repo_records"][repo_name].update({
            "remote_head_after": remote_after,
            "local_head_after": commit,
            "push_verified": True,
            "status": "PUSH_VERIFIED",
            "worktree_status_after": run_git(repo, "status", "--porcelain=v1", "--untracked-files=all")["stdout"],
        })
        write_receipt()

    RECORD["status"] = "COMPLETE_ALL_REPOS_PUSHED_AND_48_HEAD_BLOBS_VERIFIED"
    RECORD["completed_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_receipt()
    print(json.dumps({
        "status": RECORD["status"],
        "receipt": str(RECEIPT),
        "plan_sha256": plan_sha,
        "repos": {
            name: {
                "commit": RECORD["repo_records"][name]["commit"],
                "remote_head_after": RECORD["repo_records"][name]["remote_head_after"],
                "committed_paths": RECORD["repo_records"][name]["committed_path_count"],
                "head_blobs_verified": len(RECORD["repo_records"][name]["head_blob_checks"]),
            }
            for name in REPOS
        },
    }, ensure_ascii=False, indent=2))


COMMANDS: list[dict[str, Any]] = []
RECORD: dict[str, Any] = {"started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        RECORD["status"] = "STOPPED_WITH_ERROR"
        RECORD["error"] = f"{type(exc).__name__}: {exc}"
        RECORD["commands"] = COMMANDS
        RECORD["stopped_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_receipt()
        print(json.dumps({"status": RECORD["status"], "error": RECORD["error"], "receipt": str(RECEIPT)}, indent=2), file=sys.stderr)
        raise
