"""Periodic GitHub checkpoint loop.

Commits only compile-clean snapshots and pushes to origin/main.  Run it any time:

    .venv\\Scripts\\python.exe tools\\commit_loop.py [interval_seconds] [max_iterations]

Every iteration appends one line to data/a12/reports/git_commit_log.txt, so a skipped
mid-edit snapshot is visible instead of being silently absent.  ``data/`` is gitignored, so
the repository stays small while the generated data keeps its own archive.
"""
from __future__ import annotations

import os
import pathlib
import py_compile
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOG = ROOT / "data" / "a12" / "reports" / "git_commit_log.txt"
os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def main() -> int:
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 900
    iterations = int(sys.argv[2]) if len(sys.argv) > 2 else 96
    LOG.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(iterations):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        dirty = [line for line in git("status", "--porcelain").stdout.splitlines() if line.strip()]
        if not dirty:
            line = f"{stamp} | no changes"
        else:
            broken = []
            for entry in dirty:
                rel = entry[3:].strip().strip('"')
                path = ROOT / rel
                if rel.endswith(".py") and path.exists():
                    try:
                        py_compile.compile(str(path), doraise=True)
                    except Exception:
                        broken.append(rel)
            if broken:
                line = f"{stamp} | SKIPPED: {len(broken)} py file(s) fail py_compile: {broken[:3]}"
            else:
                git("add", "-A")
                git("-c", "user.email=synlab@local", "-c", "user.name=A12 SynLab",
                    "commit", "-q", "-m", f"auto: periodic checkpoint {stamp} ({len(dirty)} paths)")
                push = git("push", "origin", "main")
                out = (push.stdout + push.stderr).strip().splitlines()
                line = f"{stamp} | committed {len(dirty)} paths | {out[-1] if out else '(no output)'}"
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)
        time.sleep(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
