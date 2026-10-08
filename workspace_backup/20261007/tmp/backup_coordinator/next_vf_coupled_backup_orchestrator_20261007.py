from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge")
PLAN_PATH = ROOT / "tmp" / "backup_coordinator" / "next_vf_coupled_backup_plan_20261007.json"
RECEIPT_PATH = ROOT / "tmp" / "backup_coordinator" / "next_vf_coupled_backup_execution_20261007.json"
STAGE_SNAPSHOT = ROOT / "tmp" / "backup_coordinator" / "next_vf_coupled_backup_execution_20261007_stage.json"
LOG_DIR = ROOT / "tmp" / "backup_coordinator" / "next_vf_coupled_backup_gitlogs_20261007"
PLAN_SHA256 = "d0564be84a6a51887db11a3aa2410fb9f3154935adc066e1c1d5487b8fb989e7"
BRANCH = "backup/forge-work-20261003"
REMOTE_REF = "refs/heads/backup/forge-work-20261003"


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json_atomic(path: Path, obj: Any) -> None:
    tmp = path.with_name(path.name + ".writing")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")[:64] or "command"


class BackupRun:
    def __init__(self) -> None:
        self.plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        self.plan_sha = sha256_file(PLAN_PATH)
        if self.plan_sha != PLAN_SHA256:
            raise RuntimeError(f"plan SHA mismatch: {self.plan_sha}")
        if not RECEIPT_PATH.exists():
            raise RuntimeError("copy/stage execution receipt is missing")
        self.receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
        if self.receipt.get("plan_sha256") != PLAN_SHA256:
            raise RuntimeError("execution receipt is pinned to another plan")
        expected_stage_status = "copy_and_exact_stage_complete_index_blobs_verified_commit_pending"
        if self.receipt.get("execution_status") != expected_stage_status:
            # Preserve and resume only the known read-only false-alarm preflight failure.
            # The frozen stage receipt is the checkpoint; never recopy or restage here.
            if self.receipt.get("execution_status") != "commit_or_push_failed":
                raise RuntimeError(f"unexpected stage status: {self.receipt.get('execution_status')}")
            if not STAGE_SNAPSHOT.is_file():
                raise RuntimeError("failed receipt cannot resume without the frozen stage checkpoint")
            stage_receipt = json.loads(STAGE_SNAPSHOT.read_text(encoding="utf-8"))
            if (
                stage_receipt.get("plan_sha256") != PLAN_SHA256
                or stage_receipt.get("execution_status") != expected_stage_status
            ):
                raise RuntimeError("frozen stage checkpoint is not the approved pending plan")
            for repo_state in self.receipt.get("repositories", {}).values():
                if repo_state.get("commit_attempt") or repo_state.get("push_attempt") or repo_state.get("commit"):
                    raise RuntimeError("failed receipt contains a commit or push attempt; inspect state manually")
            old_error = self.receipt.get("error_message", "")
            history = self.receipt.setdefault("attempt_history", [])
            attempt_number = 1 + max((int(item.get("attempt", 0)) for item in history), default=0)
            failure_snapshot_sha = sha256_file(RECEIPT_PATH.with_name(
                "next_vf_coupled_backup_execution_20261007_pre_resume_failed_attempt.json"
            )) if RECEIPT_PATH.with_name(
                "next_vf_coupled_backup_execution_20261007_pre_resume_failed_attempt.json"
            ).is_file() else None
            history.append({
                "attempt": attempt_number,
                "status": "read_only_precommit_guard_false_alarm",
                "error": old_error,
                "repository_mutation": "none; approved files were already copied and staged in the prior checkpoint",
                "cause": "git status --short included the plan's expected staged additions; the corrected guard checks unstaged diff and exact cached paths",
                "preserved_failure_receipt_sha256": failure_snapshot_sha,
                "resumed_from_stage_snapshot_sha256": sha256_file(STAGE_SNAPSHOT),
            })
            self.receipt["execution_status"] = expected_stage_status
            self.receipt.pop("error_message", None)
            self.receipt.pop("failed_utc", None)
            self.receipt.setdefault("notes", []).append(
                "Resumed the exact approved staged checkpoint after preserving a read-only precommit false-alarm receipt; no files were recopied or restaged."
            )
        self.receipt.setdefault("git_command_receipts", [])
        self.receipt.setdefault("commit_blob_checks", [])
        self.receipt.setdefault("repositories", {})
        self.receipt.setdefault("notes", [])
        self.seq = 1 + len(self.receipt["git_command_receipts"])
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        write_json_atomic(RECEIPT_PATH, self.receipt)

    def run_git(self, repo: str, args: list[str], timeout: int = 30) -> dict[str, Any]:
        repo_path = ROOT / repo
        argv = ["git", "-C", str(repo_path), "-c", "core.autocrlf=false", *args]
        started = now_utc()
        t0 = time.monotonic()
        timed_out = False
        exception_text = None
        try:
            import subprocess

            proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
            stdout = proc.stdout
            stderr = proc.stderr
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            returncode = None
            exception_text = f"TimeoutExpired after {timeout}s"
        elapsed_ms = round((time.monotonic() - t0) * 1000, 3)
        ended = now_utc()
        label = safe_name("_".join(args[:4]))
        stem = f"{self.seq:04d}_{repo}_{label}"
        self.seq += 1
        record = {
            "argv": argv,
            "returncode": returncode,
            "timed_out": timed_out,
            "exception": exception_text,
            "started_utc": started,
            "ended_utc": ended,
            "elapsed_ms": elapsed_ms,
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "stdout_base64": base64.b64encode(stdout).decode("ascii"),
            "stderr_base64": base64.b64encode(stderr).decode("ascii"),
            "stdout_text": stdout.decode("utf-8", errors="replace"),
            "stderr_text": stderr.decode("utf-8", errors="replace"),
        }
        log_record = {
            "argv": argv,
            "returncode": returncode,
            "timed_out": timed_out,
            "exception": exception_text,
            "started_utc": started,
            "ended_utc": ended,
            "elapsed_ms": elapsed_ms,
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "stdout_base64": record["stdout_base64"],
            "stderr_base64": record["stderr_base64"],
        }
        (LOG_DIR / f"{stem}.json").write_text(json.dumps(log_record, indent=2) + "\n", encoding="utf-8")
        if args and args[0] in {"commit", "push"}:
            (LOG_DIR / f"{stem}.stdout.bin").write_bytes(stdout)
            (LOG_DIR / f"{stem}.stderr.bin").write_bytes(stderr)
        self.receipt["git_command_receipts"].append(record)
        self.save()
        return record

    def check_rc(self, record: dict[str, Any], context: str) -> None:
        if record["returncode"] != 0:
            raise RuntimeError(
                f"{context} failed rc={record['returncode']} timeout={record['timed_out']}: "
                f"{record['stderr_text']}"
            )

    def git_text(self, repo: str, args: list[str], context: str, timeout: int = 30) -> str:
        record = self.run_git(repo, args, timeout=timeout)
        self.check_rc(record, context)
        return record["stdout_text"].strip()

    def verify_source_and_destinations(self, repo: str) -> list[dict[str, Any]]:
        repo_root = (ROOT / repo).resolve(strict=True)
        entries = [entry for entry in self.plan["files"] if entry["repo"] == repo]
        seen: set[str] = set()
        for entry in entries:
            key = entry["destination_repo_relative"].casefold()
            if key in seen:
                raise RuntimeError(f"duplicate destination in {repo}: {key}")
            seen.add(key)
            source = Path(entry["source_absolute"]).resolve(strict=True)
            source.relative_to(repo_root)
            source_rel = source.relative_to(repo_root).as_posix()
            if source_rel != entry["source_repo_relative"]:
                raise RuntimeError(f"source relative mismatch: {source_rel}")
            if source.stat().st_size != entry["bytes"] or sha256_file(source) != entry["sha256"]:
                raise RuntimeError(f"source pin mismatch: {repo}:{source_rel}")
            dest = (repo_root / Path(entry["destination_repo_relative"])).resolve(strict=False)
            dest.relative_to(repo_root)
            if entry["operation"] == "stage_existing_exact":
                if dest != source:
                    raise RuntimeError(f"direct-stage path mismatch: {repo}:{entry['destination_repo_relative']}")
            elif entry["operation"] == "copy_then_stage_exact":
                if not dest.is_file():
                    raise RuntimeError(f"planned copied destination is missing: {dest}")
            else:
                raise RuntimeError(f"unapproved operation: {entry['operation']}")
            if dest.stat().st_size != entry["bytes"] or sha256_file(dest) != entry["sha256"]:
                raise RuntimeError(f"destination pin mismatch: {repo}:{entry['destination_repo_relative']}")
        return entries

    def verify_precommit(self, repo: str) -> tuple[list[dict[str, Any]], list[str], dict[str, str]]:
        expected_meta = self.plan["repositories"][repo]
        top = Path(self.git_text(repo, ["rev-parse", "--show-toplevel"], f"{repo} top-level")).resolve()
        if top != (ROOT / repo).resolve():
            raise RuntimeError(f"unexpected repository root for {repo}: {top}")
        branch = self.git_text(repo, ["branch", "--show-current"], f"{repo} branch")
        head = self.git_text(repo, ["rev-parse", "HEAD"], f"{repo} HEAD")
        parent = self.git_text(repo, ["rev-parse", "HEAD^"], f"{repo} parent")
        remote_output = self.git_text(
            repo, ["ls-remote", "origin", REMOTE_REF], f"{repo} ls-remote", timeout=30
        )
        remote_head = remote_output.split()[0] if remote_output else ""
        staged_text = self.git_text(repo, ["diff", "--cached", "--name-only"], f"{repo} staged paths")
        tracked_status = self.git_text(
            repo, ["status", "--short", "--untracked-files=no"], f"{repo} tracked status"
        )
        unstaged = self.run_git(repo, ["diff", "--quiet"])
        if unstaged["returncode"] not in (0, 1):
            raise RuntimeError(f"{repo} unstaged diff query failed rc={unstaged['returncode']}")
        expected_paths = sorted(entry["destination_repo_relative"] for entry in self.plan["files"] if entry["repo"] == repo)
        staged_paths = sorted(line for line in staged_text.splitlines() if line)
        if branch != BRANCH:
            raise RuntimeError(f"{repo} branch drift: {branch}")
        if unstaged["returncode"] != 0:
            raise RuntimeError(f"{repo} has tracked unstaged changes: {tracked_status}")
        if head == expected_meta["head"]:
            if parent != expected_meta["parent"]:
                raise RuntimeError(f"{repo} parent drift: {parent}")
            if remote_head != expected_meta["remote_head"]:
                raise RuntimeError(f"{repo} remote drift before commit: {remote_head}")
            if staged_paths != expected_paths:
                raise RuntimeError(f"{repo} staged path set mismatch ({len(staged_paths)} vs {len(expected_paths)})")
        else:
            # A prior command may have created the exact commit before a receipt write failed.
            # Recognize only that one-parent commit with the approved path set; never recommit it.
            if parent != expected_meta["head"]:
                raise RuntimeError(f"{repo} HEAD advanced unexpectedly: {head} parent={parent}")
            if staged_paths:
                raise RuntimeError(f"{repo} has staged paths after a possible commit")
            changed_text = self.git_text(
                repo, ["diff-tree", "--no-commit-id", "--name-only", "-r", head], f"{repo} possible existing commit paths"
            )
            changed_paths = sorted(line for line in changed_text.splitlines() if line)
            if changed_paths != expected_paths:
                raise RuntimeError(f"{repo} possible existing commit path set differs")
            if remote_head not in {expected_meta["remote_head"], head}:
                raise RuntimeError(f"{repo} remote advanced unexpectedly: {remote_head}")
        entries = self.verify_source_and_destinations(repo)
        index_checks = []
        for entry in entries:
            path = entry["destination_repo_relative"]
            index_record = self.run_git(repo, ["ls-files", "-s", "--", path])
            self.check_rc(index_record, f"{repo} index entry {path}")
            line = next((line for line in index_record["stdout_text"].splitlines() if line), "")
            match = re.match(r"^[0-9]+\s+([0-9a-f]+)\s+0\t", line)
            if not match:
                raise RuntimeError(f"cannot parse index blob OID for {repo}:{path}: {line!r}")
            oid = match.group(1)
            blob_record = self.run_git(repo, ["cat-file", "blob", oid])
            self.check_rc(blob_record, f"{repo} index blob {path}")
            blob = base64.b64decode(blob_record["stdout_base64"])
            digest = sha256_bytes(blob)
            passed = len(blob) == entry["bytes"] and digest == entry["sha256"]
            check = {
                "repo": repo,
                "path": path,
                "git_oid": oid,
                "bytes": len(blob),
                "sha256": digest,
                "expected_bytes": entry["bytes"],
                "expected_sha256": entry["sha256"],
                "passed": passed,
            }
            index_checks.append(check)
            self.receipt["index_blob_checks"].append(check)
            self.save()
            if not passed:
                raise RuntimeError(f"index blob mismatch {repo}:{path}")
        return entries, expected_paths, {
            "branch": branch,
            "head": expected_meta["head"],
            "actual_head": head,
            "parent": parent,
            "remote_head": remote_head,
            "index_blob_count": str(len(index_checks)),
            "status_short_contains_approved_stage": tracked_status,
            "unstaged_worktree_clean": unstaged["returncode"] == 0,
        }

    def committed_blob_checks(self, repo: str, commit: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        checks = []
        for entry in entries:
            path = entry["destination_repo_relative"]
            tree_record = self.run_git(repo, ["ls-tree", "-r", commit, "--", path])
            self.check_rc(tree_record, f"{repo} ls-tree {path}")
            line = next((line for line in tree_record["stdout_text"].splitlines() if line), "")
            match = re.match(r"^[0-9]+\s+blob\s+([0-9a-f]+)\t", line)
            if not match:
                raise RuntimeError(f"cannot parse tree blob OID for {repo}:{path}: {line!r}")
            oid = match.group(1)
            blob_record = self.run_git(repo, ["cat-file", "blob", oid])
            self.check_rc(blob_record, f"{repo} commit blob {path}")
            blob = base64.b64decode(blob_record["stdout_base64"])
            digest = sha256_bytes(blob)
            passed = len(blob) == entry["bytes"] and digest == entry["sha256"]
            check = {
                "repo": repo,
                "path": path,
                "git_oid": oid,
                "bytes": len(blob),
                "sha256": digest,
                "expected_bytes": entry["bytes"],
                "expected_sha256": entry["sha256"],
                "passed": passed,
            }
            checks.append(check)
            self.receipt["commit_blob_checks"].append(check)
            self.save()
            if not passed:
                raise RuntimeError(f"committed blob mismatch {repo}:{path}")
        return checks

    def verify_existing_commit_if_any(self, repo: str, entries: list[dict[str, Any]], expected_paths: list[str]) -> str | None:
        planned_head = self.plan["repositories"][repo]["head"]
        head = self.git_text(repo, ["rev-parse", "HEAD"], f"{repo} resume HEAD")
        if head == planned_head:
            return None
        parent = self.git_text(repo, ["rev-parse", f"{head}^"], f"{repo} resume parent")
        if parent != planned_head:
            raise RuntimeError(f"{repo} HEAD advanced unexpectedly: {head} parent={parent}")
        paths_text = self.git_text(repo, ["diff-tree", "--no-commit-id", "--name-only", "-r", head], f"{repo} existing commit paths")
        paths = sorted(line for line in paths_text.splitlines() if line)
        if paths != expected_paths:
            raise RuntimeError(f"{repo} already-created commit path set differs")
        return head

    def execute_repo(self, repo: str, title: str, body: str, user_name: str, user_email: str) -> None:
        repo_path = ROOT / repo
        entries, expected_paths, preflight = self.verify_precommit(repo)
        rr = self.receipt["repositories"].setdefault(repo, {})
        rr["precommit_verified"] = preflight
        rr["approved_path_count"] = len(expected_paths)
        self.save()

        existing = self.verify_existing_commit_if_any(repo, entries, expected_paths)
        if existing is None:
            remote_output = self.git_text(repo, ["ls-remote", "origin", REMOTE_REF], f"{repo} before commit push guard", timeout=30)
            remote_before = remote_output.split()[0] if remote_output else ""
            if remote_before != preflight["head"]:
                raise RuntimeError(f"{repo} remote advanced before commit: {remote_before}")
            commit_record = self.run_git(
                repo,
                [
                    "-c", f"user.name={user_name}",
                    "-c", f"user.email={user_email}",
                    "commit", "-m", title, "-m", body,
                ],
                timeout=30,
            )
            rr["commit_attempt"] = {
                "returncode": commit_record["returncode"],
                "stdout_bytes": commit_record["stdout_bytes"],
                "stderr_bytes": commit_record["stderr_bytes"],
                "stdout_base64": commit_record["stdout_base64"],
                "stderr_base64": commit_record["stderr_base64"],
                "argv": commit_record["argv"],
                "started_utc": commit_record["started_utc"],
                "ended_utc": commit_record["ended_utc"],
            }
            self.save()
            self.check_rc(commit_record, f"{repo} commit")
            commit = self.git_text(repo, ["rev-parse", "HEAD"], f"{repo} committed HEAD")
        else:
            commit = existing
            rr["commit_recovered_without_repeat"] = True
            self.receipt["notes"].append(f"{repo}: detected the exact approved local commit after a prior receipt issue; did not repeat commit.")
            self.save()

        parent = self.git_text(repo, ["rev-parse", f"{commit}^"], f"{repo} commit parent")
        if parent != preflight["head"]:
            raise RuntimeError(f"{repo} commit parent mismatch: {parent}")
        changed_text = self.git_text(repo, ["diff-tree", "--no-commit-id", "--name-only", "-r", commit], f"{repo} changed paths")
        changed_paths = sorted(line for line in changed_text.splitlines() if line)
        if changed_paths != expected_paths:
            raise RuntimeError(f"{repo} committed path set mismatch")
        rr["commit"] = {"commit": commit, "parent": parent, "changed_paths": changed_paths, "changed_path_count": len(changed_paths)}
        self.save()

        existing_checks = [check for check in self.receipt["commit_blob_checks"] if check["repo"] == repo]
        if existing_checks:
            if len(existing_checks) != len(entries) or any(not check["passed"] for check in existing_checks):
                raise RuntimeError(f"{repo} has incomplete prior committed blob checks")
        else:
            self.committed_blob_checks(repo, commit, entries)
        rr["commit_blob_count"] = len(entries)
        self.save()

        remote_pre = self.git_text(repo, ["ls-remote", "origin", REMOTE_REF], f"{repo} before push guard", timeout=30)
        remote_before = remote_pre.split()[0] if remote_pre else ""
        if remote_before not in {preflight["head"], commit}:
            raise RuntimeError(f"{repo} remote advanced unexpectedly before push: {remote_before}")
        if remote_before != commit:
            push_record = self.run_git(repo, ["push", "origin", f"HEAD:{REMOTE_REF}"], timeout=30)
            rr["push_attempt"] = {
                "returncode": push_record["returncode"],
                "timed_out": push_record["timed_out"],
                "stdout_bytes": push_record["stdout_bytes"],
                "stderr_bytes": push_record["stderr_bytes"],
                "stdout_base64": push_record["stdout_base64"],
                "stderr_base64": push_record["stderr_base64"],
                "argv": push_record["argv"],
                "started_utc": push_record["started_utc"],
                "ended_utc": push_record["ended_utc"],
            }
            self.save()
            if push_record["timed_out"]:
                raise RuntimeError(f"{repo} push timed out; local commit retained for remote verification")
            self.check_rc(push_record, f"{repo} push")
        else:
            rr["push_skipped_already_remote"] = True
            self.save()

        remote_post_output = self.git_text(repo, ["ls-remote", "origin", REMOTE_REF], f"{repo} remote after push", timeout=30)
        remote_after = remote_post_output.split()[0] if remote_post_output else ""
        local_head = self.git_text(repo, ["rev-parse", "HEAD"], f"{repo} final HEAD")
        staged_text = self.git_text(repo, ["diff", "--cached", "--name-only"], f"{repo} final staged paths")
        tracked_status = self.git_text(repo, ["status", "--short", "--untracked-files=no"], f"{repo} final tracked status")
        if remote_after != commit or local_head != commit or staged_text or tracked_status:
            raise RuntimeError(f"{repo} final remote/head/index/tracked state mismatch")
        rr["push"] = {"remote_before": remote_before, "remote_after": remote_after, "push_verified": True}
        rr["postflight"] = {
            "head": local_head,
            "parent": parent,
            "remote_head": remote_after,
            "branch": BRANCH,
            "changed_path_count": len(changed_paths),
            "verified_blob_count": len(entries),
            "index_clean": True,
            "tracked_worktree_clean": True,
        }
        self.receipt["execution_status"] = f"{repo}_committed_pushed_verified"
        self.save()


def main() -> int:
    run = BackupRun()
    if not STAGE_SNAPSHOT.exists():
        shutil.copy2(RECEIPT_PATH, STAGE_SNAPSHOT)
    run.receipt["stage_receipt_snapshot"] = {
        "path": str(STAGE_SNAPSHOT),
        "sha256": sha256_file(STAGE_SNAPSHOT),
        "created_utc": now_utc(),
    }
    run.receipt["execution_status"] = "commit_push_in_progress"
    run.receipt["python_orchestrator"] = str(Path(__file__).resolve())
    run.receipt["python_orchestrator_sha256"] = sha256_file(Path(__file__).resolve())
    run.receipt["git_log_directory"] = str(LOG_DIR)
    run.save()

    try:
        run.execute_repo(
            "pgfrag",
            "Archive coupled-source gates and MLS rotation diagnostics",
            "Preserve the fixed-case cohesive bridge source package and the accepted 64-query, five-check rotation-covariance diagnostic. The bridge package is source-only; the rotation result supports provider coordinate covariance only. It does not admit a provider, qualify bias, or establish physical fracture behavior.",
            "PGFrag Maintainer",
            "pgfrag@local",
        )
        run.execute_repo(
            "vesselforge",
            "Archive saved normal-offset reader and LOCAL2D previews",
            "Preserve the accepted saved-output reader and the original plus layout-fixed Local2D preview evidence, including historical pins and render captures. This is a Local2D candidate record and does not qualify material behavior, physical geometry, or global-wall behavior.",
            "A12 SynLab",
            "synlab@local",
        )
        run.receipt["execution_status"] = "both_repositories_committed_pushed_verified"
        run.receipt["finished_utc"] = now_utc()
        run.save()
        print(json.dumps({
            "status": run.receipt["execution_status"],
            "plan_sha256": run.plan_sha,
            "files": run.plan["totals"]["file_count"],
            "bytes": run.plan["totals"]["bytes"],
            "repositories": {
                name: run.receipt["repositories"][name].get("postflight")
                for name in ("pgfrag", "vesselforge")
            },
            "receipt": str(RECEIPT_PATH),
            "receipt_sha256": sha256_file(RECEIPT_PATH),
            "git_log_directory": str(LOG_DIR),
        }, indent=2))
        return 0
    except Exception as exc:
        run.receipt["execution_status"] = "commit_or_push_failed"
        run.receipt["error_message"] = repr(exc)
        run.receipt["failed_utc"] = now_utc()
        run.save()
        print(json.dumps({
            "status": run.receipt["execution_status"],
            "error": repr(exc),
            "receipt": str(RECEIPT_PATH),
            "receipt_sha256": sha256_file(RECEIPT_PATH),
        }, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
