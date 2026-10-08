import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge")
COORD = ROOT / "tmp" / "review_20261005" / "backup_coordinator"
scope = json.loads((COORD / "approved_execution_scope_v3_111_20261005.json").read_text(encoding="utf-8"))
repo = ROOT / "vesselforge"
entries = [e for e in scope["approved_exact_entries"] if e["repo"] == "vesselforge"]
staged = subprocess.run(["git", "-c", "core.autocrlf=false", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True, check=True).stdout.splitlines()
missing = [e for e in entries if e["destination_repo_path"] not in staged]
rows = []
for e in missing:
    path = e["destination_repo_path"]
    src = Path(e["source_path"])
    current_hash = hashlib.sha256(src.read_bytes()).hexdigest()
    current_size = src.stat().st_size
    oidp = subprocess.run(["git", "-c", "core.autocrlf=false", "rev-parse", f"HEAD:{path}"], cwd=repo, capture_output=True, text=True)
    git_blob = None
    if oidp.returncode == 0:
        oid = oidp.stdout.strip()
        cat = subprocess.Popen(["git", "-c", "core.autocrlf=false", "cat-file", "blob", oid], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        h = hashlib.sha256()
        size = 0
        while True:
            b = cat.stdout.read(1024 * 1024)
            if not b:
                break
            size += len(b)
            h.update(b)
        stderr = cat.stderr.read().decode("utf-8", "replace")
        rc = cat.wait()
        git_blob = {"oid": oid, "bytes": size, "sha256": h.hexdigest(), "rc": rc, "stderr": stderr}
    diff = subprocess.run(["git", "-c", "core.autocrlf=false", "diff", "--quiet", "HEAD", "--", path], cwd=repo)
    tracked = subprocess.run(["git", "-c", "core.autocrlf=false", "ls-files", "--error-unmatch", "--", path], cwd=repo, capture_output=True, text=True)
    rows.append({
        "path": path,
        "operation": e["operation"],
        "expected_bytes": e["expected_bytes"],
        "expected_sha256": e["expected_sha256"],
        "current_bytes": current_size,
        "current_sha256": current_hash,
        "tracked_in_HEAD": tracked.returncode == 0,
        "HEAD_blob": git_blob,
        "diff_HEAD_returncode": diff.returncode,
        "source_path": str(src),
    })
out = {"approved_count": len(entries), "staged_count": len(staged), "missing_stage_entries": rows}
out_path = COORD / "vesselforge_unstaged6_head_audit_v3.json"
out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(out, indent=2, ensure_ascii=False))
print(f"AUDIT_PATH {out_path}")
print(f"AUDIT_SHA256 {hashlib.sha256(out_path.read_bytes()).hexdigest()}")
