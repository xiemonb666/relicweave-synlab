"""Capture pytest summary counts for the docs (stdout only, no PowerShell pipeline)."""
from __future__ import annotations

import re
import subprocess
import sys

PY = r".venv\Scripts\python.exe"

for target in ("tests/a12/truth", "tests/a12/fracture", "tests/a12"):
    proc = subprocess.run([PY, "-m", "pytest", target, "-p", "no:cacheprovider", "--tb=no",
                           "-q", "-rfE"],
                          capture_output=True, text=True, cwd=r".")
    text = (proc.stdout or "") + (proc.stderr or "")
    summary = [line for line in text.splitlines()
               if re.search(r"\d+ (passed|failed|error|xfail|skipped)", line)]
    tail = summary[-1] if summary else "<no summary line>"
    print(f"{target:22s} exit={proc.returncode}  {tail}")
    fails = [line for line in text.splitlines() if line.startswith(("FAILED", "ERROR"))]
    for line in fails:
        print("    ", line.strip())
sys.stdout.flush()
