from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge")
REPO = ROOT / "relicweave-synlab"
MANIFEST_PATH = ROOT / "tmp/review_20261007/a12_claims_alignment/BACKUP_MANIFEST_PROPOSAL_v2.json"
MANIFEST_SHA256 = "1ae5b299ce72f9e37d2c80f04324affa20dfd60f56a0ff9e90fd29477e0de6a6"
RECEIPT_PATH = ROOT / "tmp/backup_coordinator/a12_claims_backup_execution_20261007.json"
LOG_DIR = ROOT / "tmp/backup_coordinator/a12_claims_backup_gitlogs_20261007"
BRANCH = "backup/forge-work-20261003"
REMOTE_REF = "refs/heads/backup/forge-work-20261003"
EXPECTED_HEAD = "b6058511e1255f70bc4f026bad57a7bb595aaa85"
EXPECTED_PARENT = "c9c342bd936d87e3b52372498943fdb5fb7a9c5b"
EXPECTED_MD_PATHS = ["docs/a12/patterns.md", "docs/a12/status.md"]


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    temp = path.with_name(path.name + ".writing")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


class Backup:
    def __init__(self) -> None:
        if RECEIPT_PATH.exists():
            raise RuntimeError(f"refusing to overwrite existing execution receipt: {RECEIPT_PATH}")
        raw = MANIFEST_PATH.read_bytes()
        if sha256_bytes(raw) != MANIFEST_SHA256:
            raise RuntimeError("manifest SHA-256 mismatch")
        self.manifest = json.loads(raw.decode("utf-8"))
        if len(self.manifest.get("items", [])) != 7:
            raise RuntimeError("expected exactly seven approved manifest items")
        self.entries = [self.normalize_item(item) for item in self.manifest["items"]]
        self.receipt: dict[str, Any] = {
            "schema": "a12_claims_alignment_backup_execution.v1",
            "manifest_path": str(MANIFEST_PATH),
            "manifest_sha256": MANIFEST_SHA256,
            "receipt_path": str(RECEIPT_PATH),
            "started_utc": now_utc(),
            "status": "preflight_pending",
            "expected_head": EXPECTED_HEAD,
            "expected_parent": EXPECTED_PARENT,
            "branch": BRANCH,
            "remote_ref": REMOTE_REF,
            "allowed_preexisting_tracked_changes": EXPECTED_MD_PATHS,
            "items": [],
            "git_commands": [],
            "notes": [
                "Only the two approved tracked Markdown link edits and five exact-byte review copies are in scope.",
                "No production or report data was modified; report JSON files are copied without changes.",
            ],
        }
        self.sequence = 0
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    def normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        source = (ROOT / item["source_path"]).resolve(strict=True)
        destination_path = item["destination_path"]
        prefix = "relicweave-synlab/"
        if not destination_path.startswith(prefix):
            raise RuntimeError(f"destination outside approved repo: {destination_path}")
        destination_rel = destination_path[len(prefix):]
        destination = (REPO / destination_rel).resolve(strict=False)
        destination.relative_to(REPO.resolve())
        expected_sha = item.get("after_sha256", item.get("source_sha256"))
        expected_bytes = item.get("after_bytes", item.get("source_bytes"))
        if not isinstance(expected_sha, str) or not isinstance(expected_bytes, int):
            raise RuntimeError(f"missing source pin for {item.get('item_id')}")
        if item["operation"] == "edit_links_in_place":
            if source != destination:
                raise RuntimeError(f"tracked edit path mismatch: {item['item_id']}")
        elif item["operation"] == "proposed_exact_byte_copy":
            if destination.exists():
                raise RuntimeError(f"approved copy destination already exists: {destination}")
        else:
            raise RuntimeError(f"unapproved manifest operation: {item['operation']}")
        data = source.read_bytes()
        if len(data) != expected_bytes or sha256_bytes(data) != expected_sha:
            raise RuntimeError(f"source pin mismatch: {item['item_id']}")
        return {
            "item_id": item["item_id"],
            "operation": item["operation"],
            "source": str(source),
            "destination_repo_relative": destination_rel,
            "destination": str(destination),
            "expected_bytes": expected_bytes,
            "expected_sha256": expected_sha,
        }

    def git(self, args: list[str], context: str, timeout: int = 30) -> dict[str, Any]:
        self.sequence += 1
        argv = ["git", "-C", str(REPO), "-c", "core.autocrlf=false", *args]
        started = now_utc()
        t0 = time.monotonic()
        try:
            result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
            rc, stdout, stderr, timed_out = result.returncode, result.stdout, result.stderr, False
        except subprocess.TimeoutExpired as exc:
            rc, stdout, stderr, timed_out = None, exc.stdout or b"", exc.stderr or b"", True
        stem = f"{self.sequence:03d}_{context.replace(' ', '_').replace('/', '_')}"
        stdout_path = LOG_DIR / f"{stem}.stdout.bin"
        stderr_path = LOG_DIR / f"{stem}.stderr.bin"
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        record = {
            "context": context,
            "argv": argv,
            "returncode": rc,
            "timed_out": timed_out,
            "elapsed_seconds": round(time.monotonic() - t0, 6),
            "started_utc": started,
            "ended_utc": now_utc(),
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "stdout_sha256": sha256_bytes(stdout),
            "stderr_sha256": sha256_bytes(stderr),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "stdout_base64": base64.b64encode(stdout).decode("ascii"),
            "stderr_base64": base64.b64encode(stderr).decode("ascii"),
        }
        self.receipt["git_commands"].append(record)
        return {**record, "stdout": stdout, "stderr": stderr}

    @staticmethod
    def require_ok(record: dict[str, Any], context: str) -> bytes:
        if record["timed_out"] or record["returncode"] != 0:
            raise RuntimeError(
                f"{context} failed rc={record['returncode']} timeout={record['timed_out']} "
                f"stderr={record['stderr'].decode('utf-8', 'replace')[:1000]}"
            )
        return record["stdout"]

    def git_text(self, args: list[str], context: str, timeout: int = 30) -> str:
        return self.require_ok(self.git(args, context, timeout), context).decode("utf-8", "replace").strip()

    def verify_preflight(self) -> dict[str, Any]:
        top = Path(self.git_text(["rev-parse", "--show-toplevel"], "repo_top")).resolve()
        head = self.git_text(["rev-parse", "HEAD"], "head")
        parent = self.git_text(["rev-parse", "HEAD^"], "parent")
        branch = self.git_text(["branch", "--show-current"], "branch")
        remote_output = self.git_text(["ls-remote", "origin", REMOTE_REF], "remote_before", timeout=30)
        remote_head = remote_output.split()[0] if remote_output else ""
        staged = self.git_text(["diff", "--cached", "--name-only"], "cached_paths").splitlines()
        unstaged = self.git_text(["diff", "--name-only"], "unstaged_paths").splitlines()
        expected_staged: list[str] = []
        if top != REPO.resolve() or head != EXPECTED_HEAD or parent != EXPECTED_PARENT or branch != BRANCH:
            raise RuntimeError(f"repo/root/head/parent/branch drift: {top} {head} {parent} {branch}")
        if remote_head != EXPECTED_HEAD:
            raise RuntimeError(f"origin branch advanced: {remote_head}")
        if sorted(staged) != expected_staged:
            raise RuntimeError(f"unexpected preexisting staged paths: {staged}")
        if sorted(unstaged) != EXPECTED_MD_PATHS:
            raise RuntimeError(f"unexpected tracked worktree changes: {unstaged}")
        for entry in self.entries:
            source = Path(entry["source"])
            destination = Path(entry["destination"])
            data = source.read_bytes()
            if len(data) != entry["expected_bytes"] or sha256_bytes(data) != entry["expected_sha256"]:
                raise RuntimeError(f"source changed during preflight: {entry['item_id']}")
            if entry["operation"] == "proposed_exact_byte_copy" and destination.exists():
                raise RuntimeError(f"copy destination appeared after manifest review: {destination}")
        identity = self.git_text(["log", "-1", "--format=%an <%ae>"], "existing_identity")
        result = {
            "top": str(top),
            "head": head,
            "parent": parent,
            "branch": branch,
            "remote_head": remote_head,
            "preexisting_staged_paths": staged,
            "allowed_tracked_worktree_changes": sorted(unstaged),
            "identity_observed": identity,
            "source_pins_verified": len(self.entries),
            "destination_preflight_passed": True,
        }
        self.receipt["preflight"] = result
        self.receipt["status"] = "preflight_passed"
        write_json_atomic(RECEIPT_PATH, self.receipt)
        return result

    def copy_approved_files(self) -> None:
        for entry in self.entries:
            if entry["operation"] != "proposed_exact_byte_copy":
                continue
            source = Path(entry["source"])
            destination = Path(entry["destination"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = source.read_bytes()
            if len(data) != entry["expected_bytes"] or sha256_bytes(data) != entry["expected_sha256"]:
                raise RuntimeError(f"source changed immediately before copy: {entry['item_id']}")
            with destination.open("xb") as output:
                output.write(data)
            copied = destination.read_bytes()
            result = {
                **entry,
                "copied_bytes": len(copied),
                "copied_sha256": sha256_bytes(copied),
                "copy_verified": len(copied) == entry["expected_bytes"] and sha256_bytes(copied) == entry["expected_sha256"],
                "copy_completed_utc": now_utc(),
            }
            self.receipt["items"].append(result)
            self.receipt["status"] = "copy_in_progress"
            write_json_atomic(RECEIPT_PATH, self.receipt)
            if not result["copy_verified"]:
                raise RuntimeError(f"copied bytes mismatch: {entry['item_id']}")

    def path_index_blob(self, path: str, context: str) -> dict[str, Any]:
        ls = self.git(["ls-files", "-s", "--", path], f"{context}_index")
        raw = self.require_ok(ls, f"{context} ls-files").decode("utf-8", "replace").strip()
        parts = raw.split()
        if len(parts) < 2 or parts[-1] != path:
            raise RuntimeError(f"index entry missing/invalid: {path}: {raw!r}")
        oid = parts[1]
        blob_record = self.git(["cat-file", "blob", oid], f"{context}_blob")
        blob = self.require_ok(blob_record, f"{context} cat-file")
        return {"path": path, "oid": oid, "bytes": len(blob), "sha256": sha256_bytes(blob), "data": blob}

    def verify_stage(self) -> list[dict[str, Any]]:
        paths = sorted(entry["destination_repo_relative"] for entry in self.entries)
        staged = self.git_text(["diff", "--cached", "--name-only"], "stage_exact_paths").splitlines()
        unstaged = self.git_text(["diff", "--name-only"], "stage_unstaged_paths").splitlines()
        if sorted(staged) != paths:
            raise RuntimeError(f"staged set is not the exact seven paths: {staged}")
        if unstaged:
            raise RuntimeError(f"unexpected unstaged tracked paths after stage: {unstaged}")
        checks = []
        for entry in self.entries:
            blob = self.path_index_blob(entry["destination_repo_relative"], "stage")
            passed = blob["bytes"] == entry["expected_bytes"] and blob["sha256"] == entry["expected_sha256"]
            checks.append({k: v for k, v in blob.items() if k != "data"} | {
                "expected_bytes": entry["expected_bytes"],
                "expected_sha256": entry["expected_sha256"],
                "passed": passed,
            })
            if not passed:
                raise RuntimeError(f"staged blob mismatch: {entry['destination_repo_relative']}")
        self.receipt["stage_verification"] = {
            "staged_paths": paths,
            "staged_path_count": len(paths),
            "unstaged_paths": unstaged,
            "blob_checks": checks,
            "blob_check_count": len(checks),
            "all_passed": True,
            "completed_utc": now_utc(),
        }
        self.receipt["status"] = "exact_stage_verified_commit_pending"
        write_json_atomic(RECEIPT_PATH, self.receipt)
        return checks

    def verify_commit_blobs(self, commit: str, paths: list[str]) -> list[dict[str, Any]]:
        checks = []
        for entry in self.entries:
            path = entry["destination_repo_relative"]
            tree = self.git(["ls-tree", "-r", commit, "--", path], "commit_tree")
            line = self.require_ok(tree, f"ls-tree {path}").decode("utf-8", "replace").strip()
            parts = line.split()
            if len(parts) < 3 or parts[1] != "blob":
                raise RuntimeError(f"committed blob missing: {path}")
            oid = parts[2]
            raw = self.require_ok(self.git(["cat-file", "blob", oid], "commit_blob"), f"cat-file {path}")
            digest = sha256_bytes(raw)
            check = {
                "path": path,
                "oid": oid,
                "bytes": len(raw),
                "sha256": digest,
                "expected_bytes": entry["expected_bytes"],
                "expected_sha256": entry["expected_sha256"],
                "passed": len(raw) == entry["expected_bytes"] and digest == entry["expected_sha256"],
            }
            checks.append(check)
            if not check["passed"]:
                raise RuntimeError(f"committed blob mismatch: {path}")
        changed = self.git_text(["diff-tree", "--no-commit-id", "--name-only", "-r", commit], "commit_changed_paths").splitlines()
        if sorted(changed) != paths:
            raise RuntimeError(f"commit changed path set differs: {changed}")
        return checks

    def execute(self) -> dict[str, Any]:
        preflight = self.verify_preflight()
        self.copy_approved_files()
        expected_paths = sorted(entry["destination_repo_relative"] for entry in self.entries)

        self.receipt["status"] = "stage_in_progress"
        self.receipt["stage_attempt_started_utc"] = now_utc()
        write_json_atomic(RECEIPT_PATH, self.receipt)
        stage_record = self.git(["add", "--", *expected_paths], "exact_git_add")
        self.receipt["stage_attempt"] = {k: stage_record[k] for k in (
            "argv", "returncode", "timed_out", "started_utc", "ended_utc", "stdout_bytes", "stderr_bytes",
            "stdout_sha256", "stderr_sha256", "stdout_path", "stderr_path", "stdout_base64", "stderr_base64"
        )}
        write_json_atomic(RECEIPT_PATH, self.receipt)
        self.require_ok(stage_record, "exact git add")
        stage_checks = self.verify_stage()

        # Pin the approved branch state again immediately before commit.
        head = self.git_text(["rev-parse", "HEAD"], "precommit_head")
        parent = self.git_text(["rev-parse", "HEAD^"], "precommit_parent")
        branch = self.git_text(["branch", "--show-current"], "precommit_branch")
        remote_out = self.git_text(["ls-remote", "origin", REMOTE_REF], "precommit_remote", timeout=30)
        remote_head = remote_out.split()[0] if remote_out else ""
        if (head, parent, branch, remote_head) != (EXPECTED_HEAD, EXPECTED_PARENT, BRANCH, EXPECTED_HEAD):
            raise RuntimeError("branch/parent/head/remote changed after staging")
        if sorted(self.git_text(["diff", "--cached", "--name-only"], "precommit_staged_paths").splitlines()) != expected_paths:
            raise RuntimeError("exact staged path set changed before commit")
        if self.git_text(["diff", "--name-only"], "precommit_unstaged_paths").splitlines():
            raise RuntimeError("unexpected tracked unstaged changes before commit")

        self.receipt["precommit_state"] = {"head": head, "parent": parent, "branch": branch, "remote_head": remote_head}
        self.receipt["status"] = "commit_in_progress"
        write_json_atomic(RECEIPT_PATH, self.receipt)
        commit = self.git([
            "-c", "user.name=A12 SynLab", "-c", "user.email=synlab@local",
            "commit", "-m", "Archive portable A12 claim-alignment review evidence",
            "-m", "Keep the approved link-retargeted documentation and exact copies of the claims review and associated audit reports together in the repository. The source reports remain unchanged.",
        ], "commit", timeout=30)
        self.receipt["commit_attempt"] = {k: commit[k] for k in (
            "argv", "returncode", "timed_out", "started_utc", "ended_utc", "stdout_bytes", "stderr_bytes",
            "stdout_sha256", "stderr_sha256", "stdout_path", "stderr_path", "stdout_base64", "stderr_base64"
        )}
        write_json_atomic(RECEIPT_PATH, self.receipt)
        self.require_ok(commit, "commit")
        commit_sha = self.git_text(["rev-parse", "HEAD"], "committed_head")
        commit_parent = self.git_text(["rev-parse", "HEAD^"], "committed_parent")
        if commit_parent != EXPECTED_HEAD:
            raise RuntimeError(f"commit parent mismatch: {commit_parent}")
        commit_checks = self.verify_commit_blobs(commit_sha, expected_paths)
        self.receipt["commit"] = {
            "sha": commit_sha,
            "parent": commit_parent,
            "changed_paths": expected_paths,
            "changed_path_count": len(expected_paths),
            "blob_checks": commit_checks,
            "blob_check_count": len(commit_checks),
            "all_blobs_passed": True,
        }
        self.receipt["status"] = "local_commit_verified_push_pending"
        write_json_atomic(RECEIPT_PATH, self.receipt)

        remote_before_push_out = self.git_text(["ls-remote", "origin", REMOTE_REF], "remote_before_push", timeout=30)
        remote_before_push = remote_before_push_out.split()[0] if remote_before_push_out else ""
        if remote_before_push != EXPECTED_HEAD:
            raise RuntimeError(f"remote advanced before push: {remote_before_push}")
        push = self.git(["push", "origin", f"HEAD:{REMOTE_REF}"], "push", timeout=30)
        self.receipt["push_attempt"] = {k: push[k] for k in (
            "argv", "returncode", "timed_out", "started_utc", "ended_utc", "stdout_bytes", "stderr_bytes",
            "stdout_sha256", "stderr_sha256", "stdout_path", "stderr_path", "stdout_base64", "stderr_base64"
        )}
        write_json_atomic(RECEIPT_PATH, self.receipt)
        self.require_ok(push, "push")
        remote_after_out = self.git_text(["ls-remote", "origin", REMOTE_REF], "remote_after_push", timeout=30)
        remote_after = remote_after_out.split()[0] if remote_after_out else ""
        final_head = self.git_text(["rev-parse", "HEAD"], "final_head")
        final_staged = self.git_text(["diff", "--cached", "--name-only"], "final_staged_paths").splitlines()
        final_tracked = self.git_text(["status", "--short", "--untracked-files=no"], "final_tracked_status").splitlines()
        if remote_after != commit_sha or final_head != commit_sha or final_staged or final_tracked:
            raise RuntimeError(f"final remote/head/index/tracked state mismatch: {remote_after} {final_head} {final_staged} {final_tracked}")
        self.receipt["status"] = "committed_pushed_verified"
        self.receipt["finished_utc"] = now_utc()
        self.receipt["postflight"] = {
            "head": final_head,
            "parent": commit_parent,
            "remote_head": remote_after,
            "branch": BRANCH,
            "changed_path_count": len(expected_paths),
            "verified_blob_count": len(commit_checks),
            "index_clean": True,
            "tracked_worktree_clean": True,
            "untracked_preserved": True,
        }
        write_json_atomic(RECEIPT_PATH, self.receipt)
        return {
            "status": self.receipt["status"],
            "commit": commit_sha,
            "parent": commit_parent,
            "remote_head": remote_after,
            "changed_path_count": len(expected_paths),
            "blob_count": len(commit_checks),
            "copy_count": len(self.receipt["items"]),
            "copy_bytes": sum(item["copied_bytes"] for item in self.receipt["items"]),
            "receipt": str(RECEIPT_PATH),
            "receipt_sha256": sha256_file(RECEIPT_PATH),
            "preflight_head": preflight["head"],
            "index_blob_checks": len(stage_checks),
        }


def main() -> int:
    run = Backup()
    try:
        print(json.dumps(run.execute(), indent=2))
        return 0
    except Exception as exc:
        run.receipt["status"] = "execution_failed"
        run.receipt["error"] = repr(exc)
        run.receipt["failed_utc"] = now_utc()
        write_json_atomic(RECEIPT_PATH, run.receipt)
        print(json.dumps({
            "status": run.receipt["status"],
            "error": repr(exc),
            "receipt": str(RECEIPT_PATH),
            "receipt_sha256": sha256_file(RECEIPT_PATH),
        }, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
