from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import time

ROOT = pathlib.Path(r"C:\Users\xiemo\Desktop\ShardForge")
COORD = ROOT / "tmp" / "review_20261005" / "backup_coordinator"
PLAN = COORD / "next_incremental_backup_plan_20261005_v1.json"
EXECUTION = COORD / "next_incremental_backup_execution_receipt_20261005.json"
OUTPUT = COORD / "next_incremental_backup_postpush_verification_20261005.json"
EXPECTED_PLAN_SHA256 = "44067acff8d4350c57b62503be557ae13a54fd26443f3701adb03bc26beeb905"
GIT = pathlib.Path(r"C:\Users\xiemo\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe")
BRANCH = "backup/forge-work-20261003"
REPOS = {"pgfrag": ROOT / "pgfrag", "vesselforge": ROOT / "vesselforge"}


def git(repo: pathlib.Path, *args: str) -> bytes:
    cmd = [str(GIT), "-c", "core.autocrlf=false", "-C", str(repo), *args]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    CALLS.append({"argv": cmd, "returncode": p.returncode, "stderr": p.stderr.decode("utf-8", "replace")})
    if p.returncode != 0:
        raise RuntimeError(f"git failed ({p.returncode}): {args!r}: {p.stderr.decode('utf-8','replace')}")
    return p.stdout


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    plan_bytes = PLAN.read_bytes()
    plan_sha = sha256(plan_bytes)
    if plan_sha != EXPECTED_PLAN_SHA256:
        raise RuntimeError(f"plan SHA mismatch: {plan_sha}")
    plan = json.loads(plan_bytes)
    entries = [entry for group in plan["groups"] for entry in group["entries"]]
    if len(entries) != 48:
        raise RuntimeError(f"expected 48 approved entries, found {len(entries)}")
    execution = json.loads(EXECUTION.read_text(encoding="utf-8"))
    if execution.get("status") != "COMPLETE_ALL_REPOS_PUSHED_AND_48_HEAD_BLOBS_VERIFIED":
        raise RuntimeError(f"executor receipt is not complete: {execution.get('status')!r}")

    result = {
        "status": "POSTPUSH_VERIFICATION_IN_PROGRESS",
        "plan_sha256": plan_sha,
        "approved_entries": len(entries),
        "execution_receipt": str(EXECUTION),
        "repos": {},
        "calls": CALLS,
    }
    grouped = {name: [e for e in entries if e["repo"] == name] for name in REPOS}
    for name, repo in REPOS.items():
        baseline = plan["baseline_after_previous_backup"]["repos"][name]
        branch = git(repo, "branch", "--show-current").decode().strip()
        head = git(repo, "rev-parse", "HEAD").decode().strip()
        parent = git(repo, "rev-parse", "HEAD^").decode().strip()
        remote_line = git(repo, "ls-remote", "origin", f"refs/heads/{BRANCH}").decode().strip()
        remote_fields = remote_line.split()
        if len(remote_fields) != 2 or remote_fields[1] != f"refs/heads/{BRANCH}":
            raise RuntimeError(f"unexpected remote lookup in {name}: {remote_line!r}")
        remote_head = remote_fields[0]
        origin = git(repo, "remote", "get-url", "origin").decode().strip()
        ident_fields = git(repo, "show", "-s", "--format=%H%x00%P%x00%an%x00%ae%x00%cn%x00%ce%x00%s", "HEAD").decode().rstrip("\n").split("\0")
        if len(ident_fields) != 7:
            raise RuntimeError(f"unexpected commit identity output for {name}: {ident_fields!r}")
        changed = [p.decode("utf-8", "strict") for p in git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "HEAD").split(b"\0") if p]
        allowed = {entry["destination_repo_path"] for entry in grouped[name]}
        if not set(changed).issubset(allowed):
            raise RuntimeError(f"unexpected committed paths in {name}: {sorted(set(changed) - allowed)!r}")
        if branch != BRANCH or parent != baseline["head"] or head != remote_head:
            raise RuntimeError(f"head/parent/remote mismatch in {name}: {branch}, {parent}, {head}, {remote_head}")
        if origin != baseline["origin"]:
            raise RuntimeError(f"origin changed in {name}: {origin!r}")

        blob_checks = []
        for entry in grouped[name]:
            rel = entry["destination_repo_path"]
            blob = git(repo, "show", f"HEAD:{rel}")
            actual_sha = sha256(blob)
            if len(blob) != entry["bytes"] or actual_sha != entry["sha256"]:
                raise RuntimeError(
                    f"HEAD blob pin mismatch {name}:{rel}: {len(blob)} bytes {actual_sha}; "
                    f"expected {entry['bytes']} bytes {entry['sha256']}"
                )
            blob_checks.append({"path": rel, "bytes": len(blob), "sha256": actual_sha})

        status = git(repo, "status", "--porcelain=v1", "--untracked-files=all").decode("utf-8", "replace")
        staged = git(repo, "diff", "--cached", "--name-only", "-z").decode("utf-8", "strict").split("\0")
        planned_dirty = [line for line in status.splitlines() if any(line[3:].replace("\\", "/") == p for p in allowed)]
        if staged and any(staged):
            raise RuntimeError(f"index is not clean after push in {name}: {staged!r}")
        if planned_dirty:
            raise RuntimeError(f"approved paths remain dirty after commit in {name}: {planned_dirty!r}")

        result["repos"][name] = {
            "branch": branch,
            "origin": origin,
            "parent_commit": parent,
            "commit": head,
            "remote_head": remote_head,
            "author_name": ident_fields[2],
            "author_email": ident_fields[3],
            "committer_name": ident_fields[4],
            "committer_email": ident_fields[5],
            "commit_subject": ident_fields[6],
            "committed_paths": changed,
            "committed_path_count": len(changed),
            "verified_HEAD_blobs": blob_checks,
            "all_repo_roster_HEAD_blobs_match": len(blob_checks) == len(grouped[name]),
            "index_clean": True,
            "planned_paths_clean": True,
            "other_worktree_status": status,
        }

    if sum(len(value["verified_HEAD_blobs"]) for value in result["repos"].values()) != 48:
        raise RuntimeError("final blob verification count is not 48")
    result["status"] = "PASS_48_HEAD_BLOBS_AND_BOTH_REMOTE_HEADS_VERIFIED"
    result["completed_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "verification_receipt": str(OUTPUT),
        "repos": {
            name: {
                "commit": data["commit"],
                "remote_head": data["remote_head"],
                "author": f"{data['author_name']} <{data['author_email']}>",
                "committed_paths": data["committed_path_count"],
                "head_blobs_verified": len(data["verified_HEAD_blobs"]),
            }
            for name, data in result["repos"].items()
        },
    }, ensure_ascii=False, indent=2))


CALLS: list[dict[str, object]] = []


if __name__ == "__main__":
    main()
