import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge")
COORD = ROOT / "tmp" / "review_20261005" / "backup_coordinator"
SCOPE_PATH = COORD / "approved_execution_scope_v3_111_20261005.json"
EXEC_PATH = COORD / "git_execution_receipt_v3_111_20261005_continuation.json"
OUT_PATH = COORD / "post_execution_verification_v3_20261005.json"
BRANCH = "backup/forge-work-20261003"


def run(repo: Path, args):
    argv = ["git", "-c", "core.autocrlf=false", *args]
    p = subprocess.run(argv, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return {
        "argv": argv,
        "returncode": p.returncode,
        "stdout": p.stdout.decode("utf-8", "replace").strip(),
        "stderr": p.stderr.decode("utf-8", "replace").strip(),
    }


def stream_blob(repo: Path, oid: str):
    argv = ["git", "-c", "core.autocrlf=false", "cat-file", "blob", oid]
    p = subprocess.Popen(argv, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    h = hashlib.sha256()
    size = 0
    while True:
        b = p.stdout.read(1024 * 1024)
        if not b:
            break
        size += len(b)
        h.update(b)
    err = p.stderr.read().decode("utf-8", "replace").strip()
    rc = p.wait()
    return {"argv": argv, "returncode": rc, "bytes": size, "sha256": h.hexdigest(), "stderr": err}


def main():
    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    execution = json.loads(EXEC_PATH.read_text(encoding="utf-8"))
    results = []
    errors = []
    for name in ("pgfrag", "vesselforge"):
        repo = ROOT / name
        planned = next(r for r in execution["repo_results"] if r["repo"] == name)
        commit = planned["commit"]
        entries = [e for e in scope["approved_exact_entries"] if e["repo"] == name]
        checks = []
        for e in entries:
            path = e["destination_repo_path"]
            oid_result = run(repo, ["rev-parse", f"{commit}:{path}"])
            if oid_result["returncode"] != 0:
                errors.append(f"{name}/{path}: commit path missing")
                checks.append({"path": path, "status": "MISSING", "rev_parse": oid_result})
                continue
            oid = oid_result["stdout"].strip()
            blob = stream_blob(repo, oid)
            passed = blob["returncode"] == 0 and blob["bytes"] == e["expected_bytes"] and blob["sha256"] == e["expected_sha256"]
            checks.append({
                "path": path,
                "oid": oid,
                "expected_bytes": e["expected_bytes"],
                "expected_sha256": e["expected_sha256"],
                "blob": blob,
                "status": "PASS" if passed else "MISMATCH",
            })
            if not passed:
                errors.append(f"{name}/{path}: committed Git blob differs from approved pin")
        branch = run(repo, ["branch", "--show-current"])
        head = run(repo, ["rev-parse", "HEAD"])
        parent = run(repo, ["rev-parse", "HEAD^"])
        origin = run(repo, ["remote", "get-url", "origin"])
        remote = run(repo, ["ls-remote", "origin", f"refs/heads/{BRANCH}"])
        tracked_status = run(repo, ["status", "--porcelain=v1", "--untracked-files=no"])
        worktree_diff = run(repo, ["diff", "--quiet"])
        index_diff = run(repo, ["diff", "--cached", "--quiet"])
        changed_paths = run(repo, ["diff-tree", "--no-commit-id", "--name-only", "-r", commit])
        attrs_delta = run(repo, ["diff-tree", "--no-commit-id", "--name-only", "-r", commit, "--", ".gitattributes"])
        remote_oid = remote["stdout"].split()[0] if remote["stdout"] else None
        repo_pass = (
            commit == planned["commit"]
            and head["stdout"] == commit
            and parent["stdout"] == planned["parent"]
            and remote_oid == commit
            and branch["stdout"] == BRANCH
            and worktree_diff["returncode"] == 0
            and index_diff["returncode"] == 0
            and all(c["status"] == "PASS" for c in checks)
        )
        if not repo_pass:
            errors.append(f"{name}: final repository state did not satisfy verification")
        results.append({
            "repo": name,
            "status": "PASS" if repo_pass else "FAIL",
            "approved_path_count": len(entries),
            "commit_blob_count": len(checks),
            "commit_blob_checks": checks,
            "branch": branch,
            "head": head,
            "parent": parent,
            "origin": origin,
            "remote_head": remote,
            "tracked_status": tracked_status,
            "unstaged_diff": worktree_diff,
            "staged_diff": index_diff,
            "commit_changed_paths": changed_paths,
            "gitattributes_delta": attrs_delta,
        })
    absent_exclusions = []
    for e in scope["explicitly_excluded_entries"]:
        dest = ROOT / "pgfrag" / Path(e["destination_repo_path"].replace("/", "\\"))
        exists = dest.exists()
        absent_exclusions.append({"destination": str(dest), "exists": exists, "sha256": e["expected_sha256"], "bytes": e["expected_bytes"]})
        if exists:
            errors.append(f"excluded destination exists unexpectedly: {dest}")
    receipt = {
        "schema": "backup_coordinator.post_execution_verification.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "approved_plan_sha256": scope["approved_plan_sha256"],
        "approved_scope_sha256": hashlib.sha256(SCOPE_PATH.read_bytes()).hexdigest(),
        "execution_receipt_sha256": hashlib.sha256(EXEC_PATH.read_bytes()).hexdigest(),
        "approved_entries": len(scope["approved_exact_entries"]),
        "excluded_entries": absent_exclusions,
        "repo_results": results,
        "errors": errors,
        "notes": [
            "Independently re-read all 111 committed Git blobs with git cat-file and recomputed SHA-256 and byte counts.",
            "Post-push HEAD and ls-remote were compared for each approved branch.",
            "No tests were run; this is a backup integrity verification.",
        ],
    }
    OUT_PATH.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    data = OUT_PATH.read_bytes()
    print(json.dumps({
        "status": receipt["status"],
        "path": str(OUT_PATH),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "approved_entries": receipt["approved_entries"],
        "repos": [{"repo": r["repo"], "status": r["status"], "head": r["head"]["stdout"], "remote": r["remote_head"]["stdout"], "verified_blobs": r["commit_blob_count"]} for r in results],
        "errors": errors,
    }, indent=2, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
