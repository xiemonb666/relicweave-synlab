"""Record the exact code state the survey ran against (hashes, not timestamps).

The workspace is edited concurrently by other work streams, so every before/after claim in
``docs/a12/synthesis_functional.md`` is pinned to hashes of the files that can change a
synthesis outcome.

Usage::

    python data/a12/reports/synthesis_functional_code_state.py --out data/a12/reports/\
synthesis_functional_code_state.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

TRACKED_GLOBS = ("synlab/**/*.py", "configs/a12/next_experiment.yaml", "tools/batch_generate.py",
                 "tests/a12/fracture/*.py")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(prog="synthesis_functional_code_state")
    parser.add_argument("--out", default="data/a12/reports/synthesis_functional_code_state.json")
    args = parser.parse_args()
    files: dict[str, str] = {}
    for pattern in TRACKED_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if "__pycache__" in path.parts:
                continue
            if path.suffix == ".pyc":
                continue
            files[str(path.relative_to(REPO_ROOT)).replace("\\", "/")] = sha256(path)
    document = {
        "schema": "synlab.a12.synthesis_functional_code_state.v1",
        "recorded_at": time.time(),
        "recorded_at_local": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "note": "hashes of every file that can change a synthesis outcome; the workspace is "
                "edited concurrently, so compare these before trusting any before/after row",
        "files": files,
        "fixed_files": {name: files[name] for name in files if name in (
            "synlab/fracture/booleans.py", "synlab/fracture/event.py",
            "synlab/fracture/api.py", "synlab/fracture/cut.py", "synlab/fracture/fragment.py",
            "synlab/pipeline.py", "configs/a12/next_experiment.yaml")},
    }
    Path(args.out).write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(document["fixed_files"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
