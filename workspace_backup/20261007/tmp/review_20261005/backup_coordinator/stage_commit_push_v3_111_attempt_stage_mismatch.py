import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


WORKSPACE = Path(r"C:\Users\xiemo\Desktop\ShardForge")
COORD = WORKSPACE / "tmp" / "review_20261005" / "backup_coordinator"
SCOPE_PATH = COORD / "approved_execution_scope_v3_111_20261005.json"
COPY_RECEIPT_PATH = COORD / "copy_execution_receipt_v3_111_20261005.json"
RECEIPT_PATH = COORD / "git_execution_receipt_v3_111_20261005.json"
LOG_PATH = COORD / "git_execution_log_v3_111_20261005.jsonl"
BRANCH = "backup/forge-work-20261003"


def sha_bytes(data: bytes):
    return len(data), hashlib.sha256(data).hexdigest()


def run_git(repo: Path, args, *, stream_output=False, extra_config=()):
    argv = ["git", "-c", "core.autocrlf=false", *extra_config, *args]
    if stream_output:
        p = subprocess.Popen(argv, cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        h = hashlib.sha256()
        size = 0
        while True:
            block = p.stdout.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            h.update(block)
        err = p.stderr.read()
        rc = p.wait()
        return {
            "argv": argv,
            "returncode": rc,
            "stdout_bytes": size,
            "stdout_sha256": h.hexdigest(),
            "stderr": err.decode("utf-8", "replace").strip(),
        }
    p = subprocess.run(argv, cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return {
        "argv": argv,
        "returncode": p.returncode,
        "stdout": p.stdout.decode("utf-8", "replace").strip(),
        "stderr": p.stderr.decode("utf-8", "replace").strip(),
    }


def log(rec):
    with LOG_PATH.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")


def require_zero(label, result):
    if result["returncode"] != 0:
        raise RuntimeError(f"{label} failed rc={result['returncode']}: {result.get('stderr') or result.get('stdout')}")


def read_copy_receipt():
    rec = json.loads(COPY_RECEIPT_PATH.read_text(encoding="utf-8"))
    if rec.get("status") != "COPY_VERIFIED_ALL_111" or rec.get("copied_or_verified_entries") != 111:
        raise RuntimeError("copy receipt is not a verified 111-entry success")
    return rec


def verify_blob(repo: Path, path: str, expected_bytes: int, expected_sha: str):
    oid_result = run_git(repo, ["rev-parse", f":{path}"])
    require_zero(f"rev-parse index blob {path}", oid_result)
    oid = oid_result["stdout"].strip()
    cat = run_git(repo, ["cat-file", "blob", oid], stream_output=True)
    require_zero(f"cat-file index blob {path}", cat)
    actual = (cat["stdout_bytes"], cat["stdout_sha256"])
    if actual != (expected_bytes, expected_sha):
        raise RuntimeError(f"index blob mismatch for {path}: got {actual}, expected {(expected_bytes, expected_sha)}")
    return {"path": path, "oid": oid, "bytes": actual[0], "sha256": actual[1]}


def verify_commit_blob(repo: Path, commit: str, path: str, expected_bytes: int, expected_sha: str):
    oid_result = run_git(repo, ["rev-parse", f"{commit}:{path}"])
    require_zero(f"rev-parse commit blob {path}", oid_result)
    oid = oid_result["stdout"].strip()
    cat = run_git(repo, ["cat-file", "blob", oid], stream_output=True)
    require_zero(f"cat-file commit blob {path}", cat)
    actual = (cat["stdout_bytes"], cat["stdout_sha256"])
    if actual != (expected_bytes, expected_sha):
        raise RuntimeError(f"commit blob mismatch for {path}: got {actual}, expected {(expected_bytes, expected_sha)}")
    return {"path": path, "oid": oid, "bytes": actual[0], "sha256": actual[1]}


def remote_head(repo: Path):
    r = run_git(repo, ["ls-remote", "origin", f"refs/heads/{BRANCH}"])
    require_zero("ls-remote", r)
    line = r["stdout"].strip()
    if not line:
        return {"argv": r["argv"], "returncode": r["returncode"], "head": None, "stdout": line, "stderr": r["stderr"]}
    parts = line.split()
    if len(parts) != 2 or parts[1] != f"refs/heads/{BRANCH}":
        raise RuntimeError(f"unexpected ls-remote output: {line!r}")
    return {"argv": r["argv"], "returncode": r["returncode"], "head": parts[0], "stdout": line, "stderr": r["stderr"]}


def exact_staged_paths(repo: Path):
    r = run_git(repo, ["diff", "--cached", "--name-only", "--no-renames", "-z"])
    require_zero("diff --cached --name-only", r)
    # The wrapper decodes text; all approved repo paths are ASCII and contain no newlines.
    return sorted(s for s in r["stdout"].split("\x00") if s)


def one_repo(name, entries, scope):
    repo = WORKSPACE / name
    expected_state = scope["initial_repository_state"][name]
    result = {
        "repo": name,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "entries": [],
        "errors": [],
        "status": "IN_PROGRESS",
    }
    try:
        branch = run_git(repo, ["branch", "--show-current"])
        require_zero("branch --show-current", branch)
        head = run_git(repo, ["rev-parse", "HEAD"])
        require_zero("rev-parse HEAD", head)
        origin = run_git(repo, ["remote", "get-url", "origin"])
        require_zero("remote get-url origin", origin)
        before_status = run_git(repo, ["status", "--porcelain=v1", "--untracked-files=no"])
        require_zero("status tracked", before_status)
        before_index = run_git(repo, ["diff", "--cached", "--quiet"])
        before_worktree = run_git(repo, ["diff", "--quiet"])
        if branch["stdout"] != expected_state["branch"] or branch["stdout"] != BRANCH:
            raise RuntimeError(f"branch mismatch: {branch['stdout']}")
        if head["stdout"] != expected_state["head"]:
            raise RuntimeError(f"HEAD changed from approved parent: {head['stdout']}")
        if origin["stdout"] != expected_state["remote"]:
            raise RuntimeError(f"origin URL mismatch: {origin['stdout']}")
        if before_worktree["returncode"] != 0:
            raise RuntimeError("tracked worktree has unstaged changes before staging")
        result["pre_git"] = {
            "branch": branch["stdout"],
            "head": head["stdout"],
            "origin": origin["stdout"],
            "tracked_status": before_status["stdout"],
            "index_clean": before_index["returncode"] == 0,
            "worktree_clean": before_worktree["returncode"] == 0,
        }
        rhead = remote_head(repo)
        result["pre_push_remote"] = rhead
        if rhead["head"] != expected_state["ls_remote_head"]:
            raise RuntimeError(f"remote head changed before staging: {rhead['head']}")

        paths = sorted(e["destination_repo_path"] for e in entries)
        if len(paths) != len(set(paths)):
            raise RuntimeError("duplicate path in exact per-repo list")
        staged_before = exact_staged_paths(repo)
        if not staged_before:
            add = run_git(repo, ["add", "--", *paths])
            result["git_add"] = add
            require_zero("git add exact paths", add)
        elif staged_before == paths:
            result["git_add"] = {"skipped": True, "reason": "exact approved PG stage preserved after identity-only commit refusal"}
        else:
            raise RuntimeError(f"preexisting staged paths are not the exact approved set: {len(staged_before)}")
        staged = exact_staged_paths(repo)
        result["staged_paths"] = staged
        if staged != paths:
            raise RuntimeError(f"staged path set mismatch: expected {len(paths)}, got {len(staged)}")

        for entry in entries:
            result["entries"].append(
                verify_blob(repo, entry["destination_repo_path"], entry["expected_bytes"], entry["expected_sha256"])
            )
        if len(result["entries"]) != len(entries):
            raise RuntimeError("not every approved staged blob was verified")
        result["all_index_blobs_verified"] = True

        if name == "pgfrag":
            subject = "Back up accepted pilot and formulation evidence"
            body = (
                "Preserves the reviewed free-fracture pilot, formulation source evidence, explicit-surface fixtures, and MLS kernel API phases 1 and 2. "
                "The pilot records 6,810 right-grip separations, not internal physical fracture, and retains the 53-byte launcher receipt discrepancy. "
                "The explicit-surface and MLS evidence is NOT_COUPLED; the ROI geometry scope remains blocked. "
                "These artifacts do not qualify geometry, fracture physics, or an R2 workflow."
            )
        else:
            subject = "Back up single-inner CAD evidence and visuals"
            body = (
                "Preserves the root-reviewed single-inner native adapter run and its visual evidence. "
                "This is a one-run geometry-only STEP roundtrip. Global wall checks, self-intersection, broader qualification, and physical validation remain unknown or unassessed."
            )
        previous_identity = run_git(repo, ["log", "-1", "--format=%an%x00%ae%x00%cn%x00%ce"])
        require_zero("read prior commit identity", previous_identity)
        identity_parts = previous_identity["stdout"].split("\x00")
        if len(identity_parts) != 4 or not identity_parts[0] or not identity_parts[1] or identity_parts[:2] != identity_parts[2:]:
            raise RuntimeError(f"prior author/committer identity is not a single established identity: {identity_parts}")
        approved_identities = {
            "pgfrag": ["PGFrag Maintainer", "pgfrag@local"],
            "vesselforge": ["A12 SynLab", "synlab@local"],
        }
        identity = identity_parts[:2]
        if identity != approved_identities[name]:
            raise RuntimeError(f"prior identity does not match root-approved per-repo identity: {identity}")
        result["commit_identity_source"] = {
            "source": "current HEAD author and committer metadata",
            "name": identity[0],
            "email": identity[1],
            "per_command_only": True,
        }
        commit = run_git(
            repo,
            ["commit", "-m", subject, "-m", body],
            extra_config=["-c", f"user.name={identity[0]}", "-c", f"user.email={identity[1]}"],
        )
        result["git_commit"] = commit
        require_zero("git commit", commit)
        commit_hash = run_git(repo, ["rev-parse", "HEAD"])
        require_zero("rev-parse committed HEAD", commit_hash)
        commit_hash = commit_hash["stdout"].strip()
        parent = run_git(repo, ["rev-parse", "HEAD^"])
        require_zero("rev-parse commit parent", parent)
        parent = parent["stdout"].strip()
        if parent != expected_state["head"]:
            raise RuntimeError(f"commit parent changed: {parent}")
        result["commit"] = commit_hash
        result["parent"] = parent

        committed_names = run_git(repo, ["diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash])
        require_zero("diff-tree names", committed_names)
        committed_paths = sorted(s for s in committed_names["stdout"].splitlines() if s)
        result["committed_paths"] = committed_paths
        if committed_paths != paths:
            raise RuntimeError(f"commit path set mismatch: expected {len(paths)}, got {len(committed_paths)}")

        commit_blob_checks = []
        for entry in entries:
            commit_blob_checks.append(
                verify_commit_blob(repo, commit_hash, entry["destination_repo_path"], entry["expected_bytes"], entry["expected_sha256"])
            )
        result["commit_blob_checks"] = commit_blob_checks
        result["all_commit_blobs_verified"] = len(commit_blob_checks) == len(entries)
        if not result["all_commit_blobs_verified"]:
            raise RuntimeError("not every committed blob was verified")

        push = run_git(repo, ["push", "origin", BRANCH])
        result["git_push"] = push
        result["push_succeeded"] = push["returncode"] == 0
        post_remote = remote_head(repo)
        result["post_push_remote"] = post_remote
        result["remote_matches_commit"] = post_remote["head"] == commit_hash
        post_status = run_git(repo, ["status", "--porcelain=v1", "--untracked-files=no"])
        require_zero("post status tracked", post_status)
        result["post_tracked_status"] = post_status["stdout"]
        result["status"] = "PUSHED_AND_REMOTE_VERIFIED" if result["push_succeeded"] and result["remote_matches_commit"] else "COMMITTED_PUSH_UNVERIFIED"
        if result["status"] == "COMMITTED_PUSH_UNVERIFIED":
            result["errors"].append("push/remote did not verify; local commit preserved, no force or retry")
    except Exception as exc:
        result["status"] = "FAILED"
        result["errors"].append(str(exc))
    result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    log(result)
    return result


def main():
    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    copy_receipt = read_copy_receipt()
    copy_by_dest = {(e["repo"], e["destination_repo_path"]): e for e in copy_receipt["entries"]}
    entries = scope["approved_exact_entries"]
    for entry in entries:
        copied = copy_by_dest.get((entry["repo"], entry["destination_repo_path"]))
        if not copied or (copied["bytes"], copied["sha256"]) != (entry["expected_bytes"], entry["expected_sha256"]):
            raise RuntimeError(f"copy receipt mismatch before Git: {entry['repo']}/{entry['destination_repo_path']}")
    by_repo = {name: [e for e in entries if e["repo"] == name] for name in ("pgfrag", "vesselforge")}
    results = []
    for name in ("pgfrag", "vesselforge"):
        results.append(one_repo(name, by_repo[name], scope))
        if results[-1]["status"] == "FAILED":
            break
    receipt = {
        "status": "COMPLETE" if len(results) == 2 and all(r["status"] == "PUSHED_AND_REMOTE_VERIFIED" for r in results) else "INCOMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "approved_plan_sha256": scope["approved_plan_sha256"],
        "approved_scope_path": str(SCOPE_PATH),
        "approved_scope_sha256": hashlib.sha256(SCOPE_PATH.read_bytes()).hexdigest(),
        "copy_receipt_path": str(COPY_RECEIPT_PATH),
        "copy_receipt_sha256": hashlib.sha256(COPY_RECEIPT_PATH.read_bytes()).hexdigest(),
        "approved_entries": len(entries),
        "excluded_entries": scope["explicitly_excluded_entries"],
        "repo_results": results,
        "notes": [
            "Only exact approved paths were staged, committed, and pushed; no Git attributes or persistent configuration were changed.",
            "No Syn commit was authorized or attempted.",
            "No tests were run as part of this backup operation.",
        ],
    }
    RECEIPT_PATH.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    size = RECEIPT_PATH.stat().st_size
    sha = hashlib.sha256(RECEIPT_PATH.read_bytes()).hexdigest()
    print(json.dumps({"status": receipt["status"], "receipt_path": str(RECEIPT_PATH), "receipt_bytes": size, "receipt_sha256": sha, "repo_results": [{"repo": r["repo"], "status": r["status"], "commit": r.get("commit"), "remote": r.get("post_push_remote", {}).get("head"), "error": r["errors"]} for r in results]}, indent=2, ensure_ascii=False))
    return 0 if receipt["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    sys.exit(main())
