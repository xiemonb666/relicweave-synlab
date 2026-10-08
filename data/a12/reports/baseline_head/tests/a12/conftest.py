"""Make ``tests/a12`` importable regardless of the pytest rootdir / import mode."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for path in (str(HERE), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
