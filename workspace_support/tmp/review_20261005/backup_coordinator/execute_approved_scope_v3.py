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
PLAN_PATH = COORD / "next_curated_backup_plan_20261005_v3.json"
RECEIPT_PATH = COORD / "copy_execution_receipt_v3_111_20261005.json"
LOG_PATH = COORD / "copy_execution_log_v3_111_20261005.jsonl"


def sha_file(path: Path):
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            h.update(block)
            size += len(block)
    return size, h.hexdigest()


def run_git(repo: Path, args):
    p = subprocess.run(
        ["git", "-c", "core.autocrlf=false", *args],
        cwd=str(repo),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "argv": ["git", "-c", "core.autocrlf=false", *args],
        "returncode": p.returncode,
        "stdout": p.stdout.decode("utf-8", "replace").strip(),
        "stderr": p.stderr.decode("utf-8", "replace").strip(),
    }


def relpath_is_safe(repo: Path, relpath: str):
    p = (repo / Path(relpath.replace("/", os.sep))).resolve()
    return p == repo.resolve() or repo.resolve() in p.parents


def append_log(rec):
    with LOG_PATH.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")


def main():
    scope_bytes, scope_sha = sha_file(SCOPE_PATH)
    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    plan_bytes, plan_sha = sha_file(PLAN_PATH)
    if plan_sha != scope["approved_plan_sha256"]:
        raise RuntimeError(f"approved plan SHA changed: {plan_sha}")
    if len(scope["approved_exact_entries"]) != 111:
        raise RuntimeError("approved scope entry count is not 111")

    repo_dirs = {
        "pgfrag": WORKSPACE / "pgfrag",
        "vesselforge": WORKSPACE / "vesselforge",
        "relicweave-synlab": WORKSPACE / "relicweave-synlab",
    }
    approved_repos = {"pgfrag", "vesselforge"}
    entries = scope["approved_exact_entries"]
    errors = []
    destinations = set()
    for entry in entries:
        repo_name = entry["repo"]
        if repo_name not in approved_repos:
            errors.append(f"unexpected repo in scope: {repo_name}")
            continue
        repo = repo_dirs[repo_name]
        dest_rel = entry["destination_repo_path"]
        if not relpath_is_safe(repo, dest_rel):
            errors.append(f"destination escapes repo: {repo_name}/{dest_rel}")
            continue
        key = (repo_name, dest_rel.casefold())
        if key in destinations:
            errors.append(f"duplicate destination: {repo_name}/{dest_rel}")
        destinations.add(key)
        source = Path(entry["source_path"])
        try:
            n, h = sha_file(source)
        except Exception as exc:
            errors.append(f"source unreadable: {source}: {exc}")
            continue
        if (n, h) != (entry["expected_bytes"], entry["expected_sha256"]):
            errors.append(f"source pin mismatch: {source}: {n}/{h}")
        dest = repo / Path(dest_rel.replace("/", os.sep))
        if entry["operation"] == "stage_existing":
            if not dest.exists() or dest.resolve() != source.resolve():
                errors.append(f"stage_existing source/destination mismatch: {source} -> {dest}")
        elif entry["operation"] in ("copy_then_stage", "copy_external_then_stage"):
            if dest.exists():
                errors.append(f"destination already exists: {dest}")
        else:
            errors.append(f"unsupported operation: {entry['operation']}")

    initial_repo = {}
    for name in sorted(approved_repos):
        repo = repo_dirs[name]
        checks = {
            "branch": run_git(repo, ["branch", "--show-current"]),
            "head": run_git(repo, ["rev-parse", "HEAD"]),
            "origin": run_git(repo, ["remote", "get-url", "origin"]),
            "status_tracked": run_git(repo, ["diff", "--quiet"]),
            "status_index": run_git(repo, ["diff", "--cached", "--quiet"]),
        }
        expected = scope["initial_repository_state"][name]
        if checks["branch"]["stdout"] != expected["branch"]:
            errors.append(f"branch changed for {name}: {checks['branch']['stdout']}")
        if checks["head"]["stdout"] != expected["head"]:
            errors.append(f"HEAD changed for {name}: {checks['head']['stdout']}")
        if checks["origin"]["stdout"] != expected["remote"]:
            errors.append(f"origin changed for {name}: {checks['origin']['stdout']}")
        if checks["status_tracked"]["returncode"] != 0:
            errors.append(f"tracked worktree is dirty for {name}")
        if checks["status_index"]["returncode"] != 0:
            errors.append(f"index is dirty for {name}")
        initial_repo[name] = checks

    if errors:
        receipt = {
            "status": "PRECOPY_ABORTED",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope_path": str(SCOPE_PATH),
            "scope_sha256": scope_sha,
            "scope_bytes": scope_bytes,
            "plan_path": str(PLAN_PATH),
            "plan_sha256": plan_sha,
            "plan_bytes": plan_bytes,
            "errors": errors,
            "initial_repo_checks": initial_repo,
        }
        RECEIPT_PATH.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
        return 2

    copied = []
    for index, entry in enumerate(entries, start=1):
        repo = repo_dirs[entry["repo"]]
        source = Path(entry["source_path"])
        dest = repo / Path(entry["destination_repo_path"].replace("/", os.sep))
        source_before = sha_file(source)
        if source_before != (entry["expected_bytes"], entry["expected_sha256"]):
            raise RuntimeError(f"source changed before action {index}: {source}")
        created = False
        try:
            if entry["operation"] == "stage_existing":
                actual = sha_file(dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                n = 0
                with source.open("rb") as src, dest.open("xb") as dst:
                    created = True
                    while True:
                        block = src.read(1024 * 1024)
                        if not block:
                            break
                        dst.write(block)
                        h.update(block)
                        n += len(block)
                    dst.flush()
                    os.fsync(dst.fileno())
                actual = (n, h.hexdigest())
                if actual != (entry["expected_bytes"], entry["expected_sha256"]):
                    raise RuntimeError(f"copy stream mismatch for {dest}: {actual}")
                dest_after = sha_file(dest)
                if dest_after != actual:
                    raise RuntimeError(f"destination readback mismatch for {dest}: {dest_after}")
            source_after = sha_file(source)
            if source_after != source_before:
                raise RuntimeError(f"source changed during copy for {source}")
            if actual != (entry["expected_bytes"], entry["expected_sha256"]):
                raise RuntimeError(f"destination/staged source pin mismatch for {dest}: {actual}")
            record = {
                "index": index,
                "repo": entry["repo"],
                "group": entry["group"],
                "operation": entry["operation"],
                "source_path": str(source),
                "destination_repo_path": entry["destination_repo_path"],
                "bytes": actual[0],
                "sha256": actual[1],
                "source_sha256_after": source_after[1],
                "status": "PASS",
            }
            copied.append(record)
            append_log(record)
            print(f"{index}/111 PASS {entry['repo']}/{entry['destination_repo_path']} {actual[0]} {actual[1]}")
        except Exception:
            if created and dest.exists():
                dest.unlink()
            raise

    receipt = {
        "status": "COPY_VERIFIED_ALL_111",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope_path": str(SCOPE_PATH),
        "scope_sha256": scope_sha,
        "scope_bytes": scope_bytes,
        "approved_plan_path": str(PLAN_PATH),
        "approved_plan_sha256": plan_sha,
        "approved_plan_bytes": plan_bytes,
        "copied_or_verified_entries": len(copied),
        "entries": copied,
        "initial_repo_checks": initial_repo,
        "notes": [
            "Copies only exact approved entries; no Git operations performed by this script.",
            "Three explicit exclusions remain local and were not copied.",
            "No repository attributes or persistent Git configuration were modified.",
        ],
    }
    RECEIPT_PATH.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"RECEIPT {RECEIPT_PATH}")
    print(f"RECEIPT_SHA256 {sha_file(RECEIPT_PATH)[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
