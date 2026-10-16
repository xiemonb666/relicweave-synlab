from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge").resolve()
PLAN_PATH = ROOT / "tmp/backup_coordinator/science_closed_backup_plan_20261007.json"
PLAN_SHA256 = "f2729b22b197896906900107f2388fa3f80b1b02c6d8a856f97ebed56974da9e"
RECEIPT_PATH = ROOT / "tmp/backup_coordinator/science_closed_backup_execution_20261007.json"
LOG_DIR = ROOT / "tmp/backup_coordinator/science_closed_backup_gitlogs_20261007"
BRANCH = "backup/forge-work-20261003"
REMOTE_REF = "refs/heads/backup/forge-work-20261003"
NETWORK_TIMEOUT = 30

COMMIT_INFO = {
    "pgfrag": (
        "PGFrag Maintainer",
        "pgfrag@local",
        "Archive fixed-elastic cohesive and saved-result diagnostics",
        "Preserve the fixed-93-DOF toy cohesive run, its retained failed saved-result capture and corrected diagnostic readback, and the associated render evidence. This is an elastic toy diagnostic, not material or physical-fracture qualification.",
    ),
    "vesselforge": (
        "A12 SynLab",
        "synlab@local",
        "Archive conditional monotone normal-strip evidence",
        "Preserve the initial failed run, scope correction, retry02 capture, and independent source/result review. The result is limited to a conditional 2D meridian-strip property; global wall distance, native B-rep, materials, and physics remain UNKNOWN.",
    ),
    "relicweave-synlab": (
        "A12 SynLab",
        "synlab@local",
        "Archive RelicWeave direction and material-source reviews",
        "Preserve read-only direction and calibration-source notes. They record planned scope and measurement needs only; no material calibration or physical qualification is claimed.",
    ),
}


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    temp = path.with_name(path.name + ".writing")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def file_safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")[:52] or "cmd"


class ClosedBackup:
    def __init__(self) -> None:
        if RECEIPT_PATH.exists():
            raise RuntimeError(f"refusing to overwrite execution receipt: {RECEIPT_PATH}")
        raw = PLAN_PATH.read_bytes()
        if sha256_bytes(raw) != PLAN_SHA256:
            raise RuntimeError("approved plan SHA-256 mismatch")
        self.plan = json.loads(raw.decode("utf-8"))
        if self.plan.get("status") != "PREPARED_ONLY_NOT_COPIED_NOT_STAGED":
            raise RuntimeError("plan is not the reviewed prepare-only manifest")
        if self.plan.get("totals", {}).get("file_count") != 98:
            raise RuntimeError("approved plan must contain exactly 98 files")
        self.items = self.plan["files"]
        self.by_repo = {
            repo: [item for item in self.items if item["repo"] == repo]
            for repo in self.plan["repositories"]
        }
        self.receipt: dict[str, Any] = {
            "schema": "shardforge.science_closed_backup_execution.v1",
            "plan_path": str(PLAN_PATH),
            "plan_sha256": PLAN_SHA256,
            "execution_receipt_path": str(RECEIPT_PATH),
            "started_utc": now_utc(),
            "status": "preflight_pending",
            "scope": {
                "file_count": 98,
                "bytes": 2115372,
                "copy_count": 91,
                "direct_stage_count": 7,
                "repositories": list(self.plan["repositories"]),
                "plan_only_scope_no_expansion": True,
            },
            "repositories": {},
            "copy_receipts": [],
            "direct_stage_receipts": [],
            "index_blob_checks": [],
            "commit_blob_checks": [],
            "git_commands": [],
            "notes": [
                "Only the exact 98 entries in the approved plan are copied or staged.",
                "Raw NPZ/bulk arrays, active opening-control/moving-front work, drafts, and original DOCX/PDF files are excluded.",
                "Scientific status remains bounded: fixed elastic toy, conditional 2D meridian strip, and no physical qualification.",
            ],
        }
        self.command_seq = 0
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        write_json_atomic(RECEIPT_PATH, self.receipt)

    def git(self, repo: str, args: list[str], context: str, timeout: int = 30) -> dict[str, Any]:
        repo_root = ROOT / repo
        argv = ["git", "-C", str(repo_root), "-c", "core.autocrlf=false", *args]
        self.command_seq += 1
        started = now_utc()
        tic = time.monotonic()
        timed_out = False
        exception = None
        try:
            proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
            stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, rc, timed_out = exc.stdout or b"", exc.stderr or b"", None, True
        except Exception as exc:
            stdout, stderr, rc, timed_out, exception = b"", repr(exc).encode("utf-8"), None, False, repr(exc)
        stem = f"{self.command_seq:04d}_{file_safe(repo)}_{file_safe(context)}"
        stdout_path = LOG_DIR / f"{stem}.stdout.bin"
        stderr_path = LOG_DIR / f"{stem}.stderr.bin"
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        record = {
            "repo": repo,
            "context": context,
            "argv": argv,
            "returncode": rc,
            "timed_out": timed_out,
            "exception": exception,
            "started_utc": started,
            "ended_utc": now_utc(),
            "elapsed_seconds": round(time.monotonic() - tic, 6),
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "stdout_sha256": sha256_bytes(stdout),
            "stderr_sha256": sha256_bytes(stderr),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
        self.receipt["git_commands"].append(record)
        return {**record, "stdout": stdout, "stderr": stderr}

    @staticmethod
    def require_ok(record: dict[str, Any], context: str) -> bytes:
        if record["timed_out"] or record["returncode"] != 0:
            stderr = record["stderr"].decode("utf-8", "replace")[:1200]
            raise RuntimeError(f"{context} failed rc={record['returncode']} timeout={record['timed_out']} stderr={stderr}")
        return record["stdout"]

    def git_text(self, repo: str, args: list[str], context: str, timeout: int = 30) -> str:
        return self.require_ok(self.git(repo, args, context, timeout), context).decode("utf-8", "replace").strip()

    def verify_all_inputs_and_repo_pins(self) -> None:
        dest_seen: dict[str, set[str]] = {repo: set() for repo in self.by_repo}
        preflight = {}
        for repo, entries in self.by_repo.items():
            meta = self.plan["repositories"][repo]
            repo_root = (ROOT / repo).resolve(strict=True)
            top = Path(self.git_text(repo, ["rev-parse", "--show-toplevel"], "preflight_top")).resolve()
            head = self.git_text(repo, ["rev-parse", "HEAD"], "preflight_head")
            parent = self.git_text(repo, ["rev-parse", "HEAD^"], "preflight_parent")
            branch = self.git_text(repo, ["branch", "--show-current"], "preflight_branch")
            remote_text = self.git_text(repo, ["ls-remote", "origin", REMOTE_REF], "preflight_remote", NETWORK_TIMEOUT)
            remote_head = remote_text.split()[0] if remote_text else ""
            cached = self.git_text(repo, ["diff", "--cached", "--name-only"], "preflight_cached_paths").splitlines()
            unstaged = self.git_text(repo, ["diff", "--name-only"], "preflight_unstaged_paths").splitlines()
            tracked_status = self.git_text(repo, ["status", "--short", "--untracked-files=no"], "preflight_tracked_status").splitlines()
            if top != repo_root:
                raise RuntimeError(f"repository root drift for {repo}: {top}")
            if (head, parent, branch, remote_head) != (meta["head"], meta["parent"], BRANCH, meta["head"]):
                raise RuntimeError(f"HEAD/parent/branch/remote drift for {repo}: {head}/{parent}/{branch}/{remote_head}")
            if cached or unstaged or tracked_status:
                raise RuntimeError(f"tracked/index drift for {repo}: staged={cached} unstaged={unstaged} status={tracked_status}")
            preflight[repo] = {
                "top": str(top),
                "head": head,
                "parent": parent,
                "branch": branch,
                "remote_head": remote_head,
                "index_clean": True,
                "tracked_worktree_clean": True,
                "planned_item_count": len(entries),
                "planned_bytes": sum(item["bytes"] for item in entries),
            }
            for entry in entries:
                rel_dest = entry["destination_repo_relative"]
                key = rel_dest.casefold()
                if key in dest_seen[repo]:
                    raise RuntimeError(f"duplicate planned destination: {repo}:{rel_dest}")
                dest_seen[repo].add(key)
                source = Path(entry["source_absolute"]).resolve(strict=True)
                source.relative_to(ROOT)
                src_bytes = source.read_bytes()
                if len(src_bytes) != entry["bytes"] or sha256_bytes(src_bytes) != entry["sha256"]:
                    raise RuntimeError(f"source pin drift: {repo}:{entry['source_absolute']}")
                destination = (repo_root / rel_dest).resolve(strict=False)
                destination.relative_to(repo_root)
                if entry["operation"] == "copy_exact":
                    if destination.exists():
                        raise RuntimeError(f"copy destination exists: {repo}:{rel_dest}")
                    if entry["source_kind"] == "repo":
                        source.relative_to(repo_root)
                        if source.relative_to(repo_root).as_posix() != entry["source_repo_relative"]:
                            raise RuntimeError(f"source repo-relative mismatch: {repo}:{rel_dest}")
                    elif entry["source_kind"] == "workspace":
                        if source.relative_to(ROOT).as_posix() != entry["source_workspace_relative"]:
                            raise RuntimeError(f"source workspace-relative mismatch: {repo}:{rel_dest}")
                    else:
                        raise RuntimeError(f"unknown source kind: {entry['source_kind']}")
                elif entry["operation"] == "direct_stage_untracked":
                    if source.resolve() != destination:
                        raise RuntimeError(f"direct-stage path mismatch: {repo}:{rel_dest}")
                    rc_ls, _, _ = self.raw_git(repo, ["ls-files", "--error-unmatch", "--", rel_dest], "preflight_direct_tracked")
                    if rc_ls == 0:
                        raise RuntimeError(f"direct-stage source is already tracked; plan drift: {repo}:{rel_dest}")
                    if rc_ls != 1:
                        raise RuntimeError(f"git ls-files failed for direct-stage source: {repo}:{rel_dest}")
                    ignored = self.git(repo, ["check-ignore", "-q", "--", rel_dest], "preflight_direct_ignore")
                    if ignored["returncode"] == 0:
                        raise RuntimeError(f"direct-stage source is ignored: {repo}:{rel_dest}")
                    if ignored["returncode"] != 1:
                        raise RuntimeError(f"git check-ignore failed for {repo}:{rel_dest}")
                    status = self.git_text(repo, ["status", "--short", "--untracked-files=all", "--", rel_dest], "preflight_direct_status")
                    if status != f"?? {rel_dest}":
                        raise RuntimeError(f"direct-stage status drift: {repo}:{rel_dest}: {status!r}")
                else:
                    raise RuntimeError(f"unapproved operation: {entry['operation']}")
        self.receipt["preflight"] = preflight
        self.receipt["status"] = "all_source_repo_target_pins_verified"
        self.receipt["source_pin_count"] = len(self.items)
        self.receipt["source_bytes_total"] = sum(item["bytes"] for item in self.items)
        self.save()

    def raw_git(self, repo: str, args: list[str], context: str) -> tuple[int | None, bytes, bytes]:
        record = self.git(repo, args, context)
        return record["returncode"], record["stdout"], record["stderr"]

    def copy_repo_items(self, repo: str) -> None:
        for entry in self.by_repo[repo]:
            if entry["operation"] != "copy_exact":
                continue
            source = Path(entry["source_absolute"]).resolve(strict=True)
            destination = (ROOT / repo / entry["destination_repo_relative"]).resolve(strict=False)
            destination.relative_to((ROOT / repo).resolve())
            if destination.exists():
                raise RuntimeError(f"copy target appeared before copy: {repo}:{entry['destination_repo_relative']}")
            data = source.read_bytes()
            digest = sha256_bytes(data)
            if len(data) != entry["bytes"] or digest != entry["sha256"]:
                raise RuntimeError(f"source changed immediately before copy: {repo}:{entry['source_absolute']}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(data)
            copied = destination.read_bytes()
            copied_sha = sha256_bytes(copied)
            record = {
                "repo": repo,
                "group": entry["group"],
                "source": entry["source_absolute"],
                "destination": entry["destination_repo_relative"],
                "bytes": len(copied),
                "sha256": copied_sha,
                "expected_bytes": entry["bytes"],
                "expected_sha256": entry["sha256"],
                "copy_verified": len(copied) == entry["bytes"] and copied_sha == entry["sha256"],
                "completed_utc": now_utc(),
            }
            self.receipt["copy_receipts"].append(record)
            self.receipt["status"] = f"{repo}_copying"
            self.save()
            if not record["copy_verified"]:
                raise RuntimeError(f"copied bytes mismatch: {repo}:{entry['destination_repo_relative']}")

    def verify_destinations_before_stage(self, repo: str) -> None:
        for entry in self.by_repo[repo]:
            path = Path(entry["destination_absolute"]).resolve(strict=True)
            data = path.read_bytes()
            digest = sha256_bytes(data)
            if len(data) != entry["bytes"] or digest != entry["sha256"]:
                raise RuntimeError(f"source/destination pin mismatch before stage: {repo}:{entry['destination_repo_relative']}")
            if Path(entry["source_absolute"]).resolve(strict=True).read_bytes() != data:
                raise RuntimeError(f"source bytes changed before stage: {repo}:{entry['source_absolute']}")

    def verify_index_blobs(self, repo: str, expected_paths: list[str]) -> list[dict[str, Any]]:
        staged_text = self.git_text(repo, ["diff", "--cached", "--name-only"], "stage_exact_path_set")
        staged = sorted(line for line in staged_text.splitlines() if line)
        if staged != expected_paths:
            raise RuntimeError(f"{repo} staged path set mismatch: {len(staged)} vs {len(expected_paths)}")
        unstaged = self.git_text(repo, ["diff", "--name-only"], "stage_unstaged_paths").splitlines()
        if unstaged:
            raise RuntimeError(f"{repo} tracked unstaged paths after staging: {unstaged}")
        checks = []
        expected_by_path = {item["destination_repo_relative"]: item for item in self.by_repo[repo]}
        for path in expected_paths:
            ls = self.git(repo, ["ls-files", "-s", "--", path], "index_entry")
            line = self.require_ok(ls, f"{repo} index entry {path}").decode("utf-8", "replace").strip()
            match = re.match(r"^[0-9]+\s+([0-9a-f]+)\s+0\t", line)
            if not match:
                raise RuntimeError(f"cannot parse index entry for {repo}:{path}: {line!r}")
            oid = match.group(1)
            raw = self.require_ok(self.git(repo, ["cat-file", "blob", oid], "index_blob"), f"{repo} index blob {path}")
            entry = expected_by_path[path]
            digest = sha256_bytes(raw)
            check = {
                "repo": repo,
                "path": path,
                "oid": oid,
                "bytes": len(raw),
                "sha256": digest,
                "expected_bytes": entry["bytes"],
                "expected_sha256": entry["sha256"],
                "passed": len(raw) == entry["bytes"] and digest == entry["sha256"],
            }
            self.receipt["index_blob_checks"].append(check)
            checks.append(check)
            if not check["passed"]:
                raise RuntimeError(f"index blob mismatch: {repo}:{path}")
        self.receipt["repositories"].setdefault(repo, {})["index_blob_checks_passed"] = len(checks)
        self.save()
        return checks

    def verify_committed_blobs(self, repo: str, commit: str, expected_paths: list[str]) -> list[dict[str, Any]]:
        checks = []
        expected_by_path = {item["destination_repo_relative"]: item for item in self.by_repo[repo]}
        for path in expected_paths:
            tree = self.git(repo, ["ls-tree", "-r", commit, "--", path], "commit_tree_entry")
            line = self.require_ok(tree, f"{repo} commit tree {path}").decode("utf-8", "replace").strip()
            match = re.match(r"^[0-9]+\s+blob\s+([0-9a-f]+)\t", line)
            if not match:
                raise RuntimeError(f"cannot locate committed blob: {repo}:{path}")
            oid = match.group(1)
            raw = self.require_ok(self.git(repo, ["cat-file", "blob", oid], "committed_blob"), f"{repo} cat-file {path}")
            entry = expected_by_path[path]
            digest = sha256_bytes(raw)
            check = {
                "repo": repo,
                "path": path,
                "oid": oid,
                "bytes": len(raw),
                "sha256": digest,
                "expected_bytes": entry["bytes"],
                "expected_sha256": entry["sha256"],
                "passed": len(raw) == entry["bytes"] and digest == entry["sha256"],
            }
            self.receipt["commit_blob_checks"].append(check)
            checks.append(check)
            if not check["passed"]:
                raise RuntimeError(f"committed blob mismatch: {repo}:{path}")
        changed = self.git_text(repo, ["diff-tree", "--no-commit-id", "--name-only", "-r", commit], "commit_changed_paths").splitlines()
        if sorted(changed) != expected_paths:
            raise RuntimeError(f"{repo} committed path set mismatch: {changed}")
        self.save()
        return checks

    def execute_repo(self, repo: str) -> None:
        meta = self.plan["repositories"][repo]
        entries = self.by_repo[repo]
        expected_paths = sorted(entry["destination_repo_relative"] for entry in entries)
        repo_receipt = self.receipt["repositories"].setdefault(repo, {})

        self.copy_repo_items(repo)
        self.verify_destinations_before_stage(repo)
        repo_receipt["copy_count"] = sum(entry["operation"] == "copy_exact" for entry in entries)
        repo_receipt["direct_stage_count"] = sum(entry["operation"] == "direct_stage_untracked" for entry in entries)
        repo_receipt["planned_path_count"] = len(entries)
        self.receipt["status"] = f"{repo}_ready_to_stage"
        self.save()

        stage_started = now_utc()
        stage_record = self.git(repo, ["add", "--", *expected_paths], "exact_add", timeout=30)
        repo_receipt["stage_attempt"] = {
            k: stage_record[k] for k in (
                "argv", "returncode", "timed_out", "started_utc", "ended_utc", "elapsed_seconds",
                "stdout_bytes", "stderr_bytes", "stdout_sha256", "stderr_sha256", "stdout_path", "stderr_path"
            )
        }
        repo_receipt["stage_started_utc"] = stage_started
        repo_receipt["stage_completed_utc"] = now_utc()
        self.receipt["status"] = f"{repo}_staged_pending_verify"
        self.save()
        self.require_ok(stage_record, f"{repo} exact git add")
        index_checks = self.verify_index_blobs(repo, expected_paths)

        # Recheck source pins and branch/remotes immediately before committing.
        self.verify_destinations_before_stage(repo)
        head = self.git_text(repo, ["rev-parse", "HEAD"], "precommit_head")
        parent = self.git_text(repo, ["rev-parse", "HEAD^"], "precommit_parent")
        branch = self.git_text(repo, ["branch", "--show-current"], "precommit_branch")
        remote_text = self.git_text(repo, ["ls-remote", "origin", REMOTE_REF], "precommit_remote", NETWORK_TIMEOUT)
        remote_head = remote_text.split()[0] if remote_text else ""
        if (head, parent, branch, remote_head) != (meta["head"], meta["parent"], BRANCH, meta["head"]):
            raise RuntimeError(f"precommit branch/HEAD/parent/remote drift in {repo}")
        staged = sorted(self.git_text(repo, ["diff", "--cached", "--name-only"], "precommit_staged_paths").splitlines())
        unstaged = self.git_text(repo, ["diff", "--name-only"], "precommit_unstaged_paths").splitlines()
        if staged != expected_paths or unstaged:
            raise RuntimeError(f"precommit staged/unstaged set mismatch in {repo}: {len(staged)} staged; unstaged={unstaged}")
        repo_receipt["precommit"] = {"head": head, "parent": parent, "branch": branch, "remote_head": remote_head, "path_count": len(staged), "index_blob_count": len(index_checks)}
        self.receipt["status"] = f"{repo}_commit_pending"
        self.save()

        user_name, user_email, title, body = COMMIT_INFO[repo]
        commit_record = self.git(repo, [
            "-c", f"user.name={user_name}", "-c", f"user.email={user_email}",
            "commit", "-m", title, "-m", body,
        ], "commit", timeout=30)
        repo_receipt["commit_attempt"] = {
            k: commit_record[k] for k in (
                "argv", "returncode", "timed_out", "started_utc", "ended_utc", "elapsed_seconds",
                "stdout_bytes", "stderr_bytes", "stdout_sha256", "stderr_sha256", "stdout_path", "stderr_path"
            )
        }
        self.save()
        self.require_ok(commit_record, f"{repo} commit")

        commit = self.git_text(repo, ["rev-parse", "HEAD"], "committed_head")
        commit_parent = self.git_text(repo, ["rev-parse", "HEAD^"], "committed_parent")
        if commit_parent != meta["head"]:
            raise RuntimeError(f"{repo} commit parent mismatch: {commit_parent}")
        blob_checks = self.verify_committed_blobs(repo, commit, expected_paths)
        repo_receipt["commit"] = {
            "sha": commit,
            "parent": commit_parent,
            "changed_path_count": len(expected_paths),
            "changed_paths": expected_paths,
            "blob_count": len(blob_checks),
            "all_blobs_passed": all(check["passed"] for check in blob_checks),
        }
        self.receipt["status"] = f"{repo}_local_commit_verified_push_pending"
        self.save()

        remote_before_text = self.git_text(repo, ["ls-remote", "origin", REMOTE_REF], "prepush_remote", NETWORK_TIMEOUT)
        remote_before = remote_before_text.split()[0] if remote_before_text else ""
        if remote_before != meta["head"]:
            raise RuntimeError(f"{repo} remote advanced before push; local commit retained: {remote_before}")
        push_record = self.git(repo, ["push", "origin", f"HEAD:{REMOTE_REF}"], "push", NETWORK_TIMEOUT)
        repo_receipt["push_attempt"] = {
            k: push_record[k] for k in (
                "argv", "returncode", "timed_out", "started_utc", "ended_utc", "elapsed_seconds",
                "stdout_bytes", "stderr_bytes", "stdout_sha256", "stderr_sha256", "stdout_path", "stderr_path"
            )
        }
        self.save()
        self.require_ok(push_record, f"{repo} push")
        remote_after_text = self.git_text(repo, ["ls-remote", "origin", REMOTE_REF], "postpush_remote", NETWORK_TIMEOUT)
        remote_after = remote_after_text.split()[0] if remote_after_text else ""
        final_head = self.git_text(repo, ["rev-parse", "HEAD"], "postpush_head")
        final_parent = self.git_text(repo, ["rev-parse", "HEAD^"], "postpush_parent")
        final_branch = self.git_text(repo, ["branch", "--show-current"], "postpush_branch")
        final_index = self.git_text(repo, ["diff", "--cached", "--name-only"], "postpush_index").splitlines()
        final_tracked = self.git_text(repo, ["status", "--short", "--untracked-files=no"], "postpush_tracked_status").splitlines()
        if (remote_after, final_head, final_parent, final_branch) != (commit, commit, commit_parent, BRANCH) or final_index or final_tracked:
            raise RuntimeError(f"{repo} postflight mismatch: remote={remote_after} head={final_head} parent={final_parent} branch={final_branch} staged={final_index} tracked={final_tracked}")
        repo_receipt["push"] = {"remote_before": remote_before, "remote_after": remote_after, "push_verified": True}
        repo_receipt["postflight"] = {
            "head": final_head,
            "parent": final_parent,
            "remote_head": remote_after,
            "branch": final_branch,
            "changed_path_count": len(expected_paths),
            "verified_blob_count": len(blob_checks),
            "index_clean": True,
            "tracked_worktree_clean": True,
            "untracked_preserved": True,
        }
        repo_receipt["completed_utc"] = now_utc()
        self.receipt["status"] = f"{repo}_committed_pushed_verified"
        self.save()

    def execute(self) -> dict[str, Any]:
        self.verify_all_inputs_and_repo_pins()
        self.receipt["status"] = "preflight_passed_copying_exact_plan"
        self.save()
        for repo in ("pgfrag", "vesselforge", "relicweave-synlab"):
            self.execute_repo(repo)
        self.receipt["status"] = "all_repositories_committed_pushed_verified"
        self.receipt["finished_utc"] = now_utc()
        self.save()
        return {
            "status": self.receipt["status"],
            "plan_sha256": PLAN_SHA256,
            "receipt": str(RECEIPT_PATH),
            "receipt_sha256": sha256_file(RECEIPT_PATH),
            "files": len(self.items),
            "bytes": sum(item["bytes"] for item in self.items),
            "repositories": {repo: self.receipt["repositories"][repo].get("postflight") for repo in self.by_repo},
            "git_command_count": len(self.receipt["git_commands"]),
            "git_log_directory": str(LOG_DIR),
        }


def main() -> int:
    backup = ClosedBackup()
    try:
        print(json.dumps(backup.execute(), indent=2))
        return 0
    except Exception as exc:
        backup.receipt["status"] = "execution_failed"
        backup.receipt["error"] = repr(exc)
        backup.receipt["failed_utc"] = now_utc()
        backup.save()
        print(json.dumps({
            "status": backup.receipt["status"],
            "error": repr(exc),
            "receipt": str(RECEIPT_PATH),
            "receipt_sha256": sha256_file(RECEIPT_PATH),
        }, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
