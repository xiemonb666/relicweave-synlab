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
PREVIOUS_RECEIPT_PATH = COORD / "git_execution_receipt_v3_111_20261005.json"
RECEIPT_PATH = COORD / "git_execution_receipt_v3_111_20261005_continuation.json"
LOG_PATH = COORD / "git_execution_log_v3_111_20261005_continuation.jsonl"
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


def one_repo(name, entries, scope, previous_receipt):
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
        if origin["stdout"] != expected_state["remote"]:
            raise RuntimeError(f"origin URL mismatch: {origin['stdout']}")
        if head["stdout"].strip() != expected_state["head"]:
            prior = next((r for r in previous_receipt.get("repo_results", []) if r.get("repo") == name), None)
            current_head = head["stdout"].strip()
            if not prior or prior.get("status") != "PUSHED_AND_REMOTE_VERIFIED" or prior.get("commit") != current_head:
                raise RuntimeError(f"HEAD changed from approved parent without verified prior receipt: {current_head}")
            if before_index["returncode"] != 0 or before_worktree["returncode"] != 0:
                raise RuntimeError("worktree/index changed after prior successful push")
            parent = run_git(repo, ["rev-parse", "HEAD^"])
            require_zero("rev-parse prior commit parent", parent)
            if parent["stdout"].strip() != expected_state["head"]:
                raise RuntimeError(f"prior commit parent mismatch: {parent['stdout']}")
            prior_remote = remote_head(repo)
            if prior_remote["head"] != current_head:
                raise RuntimeError(f"prior push is not at current remote head: {prior_remote['head']}")
            scope_paths = sorted(e["destination_repo_path"] for e in entries)
            previous_paths = run_git(repo, ["diff-tree", "--no-commit-id", "--name-only", "-r", current_head])
            require_zero("diff-tree prior commit", previous_paths)
            changed_paths = sorted(s for s in previous_paths["stdout"].splitlines() if s)
            if not set(changed_paths).issubset(set(scope_paths)):
                raise RuntimeError("prior commit contains paths outside the approved scope")
            tree_blobs = [
                verify_commit_blob(repo, current_head, e["destination_repo_path"], e["expected_bytes"], e["expected_sha256"])
                for e in entries
            ]
            result.update({
                "pre_git": {"branch": branch["stdout"], "head": current_head, "origin": origin["stdout"]},
                "commit": current_head,
                "parent": expected_state["head"],
                "committed_paths": changed_paths,
                "commit_blob_checks": tree_blobs,
                "all_commit_blobs_verified": len(tree_blobs) == len(entries),
                "pre_push_remote": prior_remote,
                "post_push_remote": prior_remote,
                "push_succeeded": True,
                "remote_matches_commit": True,
                "status": "ALREADY_PUSHED_AND_REVERIFIED",
                "reused_prior_execution_receipt": str(PREVIOUS_RECEIPT_PATH),
            })
            result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            log(result)
            return result
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
        elif not set(staged_before).issubset(set(paths)):
            raise RuntimeError(f"preexisting staged paths extend outside approved scope: {sorted(set(staged_before) - set(paths))}")
        else:
            result["git_add"] = {"skipped": True, "reason": "preserved exact-path stage from prior attempt; no additional files staged"}
        staged = exact_staged_paths(repo)
        result["staged_paths"] = staged
        if not set(staged).issubset(set(paths)):
            raise RuntimeError("staged path set extends beyond approved manifest")
        if not staged:
            raise RuntimeError("no staged approved changes to commit")

        staged_set = set(staged)
        for entry in entries:
            path = entry["destination_repo_path"]
            if path in staged_set:
                result["entries"].append({
                    "state": "staged",
                    **verify_blob(repo, path, entry["expected_bytes"], entry["expected_sha256"]),
                })
            else:
                unchanged = run_git(repo, ["diff", "--quiet", "HEAD", "--", path])
                if unchanged["returncode"] != 0:
                    raise RuntimeError(f"approved path is unstaged and differs from HEAD: {path}")
                result["entries"].append({
                    "state": "already_present_unchanged",
                    **verify_commit_blob(repo, "HEAD", path, entry["expected_bytes"], entry["expected_sha256"]),
                })
        if len(result["entries"]) != len(entries):
            raise RuntimeError("not every approved path was verified in index or HEAD")
        result["staged_change_count"] = len(staged)
        result["already_present_unchanged_count"] = len(entries) - len(staged)
        result["all_scope_blobs_verified_before_commit"] = True

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
        if committed_paths != staged:
            raise RuntimeError(f"commit changed paths differ from exact staged set: expected {len(staged)}, got {len(committed_paths)}")

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
    previous_receipt = json.loads(PREVIOUS_RECEIPT_PATH.read_text(encoding="utf-8"))
    copy_by_dest = {(e["repo"], e["destination_repo_path"]): e for e in copy_receipt["entries"]}
    entries = scope["approved_exact_entries"]
    for entry in entries:
        copied = copy_by_dest.get((entry["repo"], entry["destination_repo_path"]))
        if not copied or (copied["bytes"], copied["sha256"]) != (entry["expected_bytes"], entry["expected_sha256"]):
            raise RuntimeError(f"copy receipt mismatch before Git: {entry['repo']}/{entry['destination_repo_path']}")
    by_repo = {name: [e for e in entries if e["repo"] == name] for name in ("pgfrag", "vesselforge")}
    results = []
    for name in ("pgfrag", "vesselforge"):
        results.append(one_repo(name, by_repo[name], scope, previous_receipt))
        if results[-1]["status"] == "FAILED":
            break
    receipt = {
        "status": "COMPLETE" if len(results) == 2 and all(r["status"] in ("PUSHED_AND_REMOTE_VERIFIED", "ALREADY_PUSHED_AND_REVERIFIED") for r in results) else "INCOMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "approved_plan_sha256": scope["approved_plan_sha256"],
        "approved_scope_path": str(SCOPE_PATH),
        "approved_scope_sha256": hashlib.sha256(SCOPE_PATH.read_bytes()).hexdigest(),
        "copy_receipt_path": str(COPY_RECEIPT_PATH),
        "copy_receipt_sha256": hashlib.sha256(COPY_RECEIPT_PATH.read_bytes()).hexdigest(),
        "prior_git_execution_receipt_path": str(PREVIOUS_RECEIPT_PATH),
        "prior_git_execution_receipt_sha256": hashlib.sha256(PREVIOUS_RECEIPT_PATH.read_bytes()).hexdigest(),
        "approved_entries": len(entries),
        "excluded_entries": scope["explicitly_excluded_entries"],
        "repo_results": results,
        "notes": [
            "Only exact approved paths were staged, committed, and pushed; preexisting unchanged tracked files were verified in HEAD and not redundantly staged.",
            "The approved per-repo list may have fewer committed paths than manifest entries when a pinned file is unchanged and already present at the parent commit.",
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
