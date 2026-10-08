from __future__ import annotations

import itertools
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WHEELHOUSE = ROOT / "wheelhouse"
TEMP_POOL = ROOT / "tempbase"
wheel_dirs = iter(sorted(WHEELHOUSE.glob(".staging-*")))
temp_dirs = iter(sorted(TEMP_POOL.glob("precreated-*")))


def precreated_mkdtemp(suffix=None, prefix=None, dir=None):
    pool = wheel_dirs if dir and Path(dir).resolve() == WHEELHOUSE.resolve() else temp_dirs
    try:
        path = next(pool)
    except StopIteration as exc:
        raise RuntimeError("pre-created wheel build scratch pool exhausted") from exc
    if any(path.iterdir()):
        raise RuntimeError(f"pre-created scratch directory is not empty: {path}")
    return str(path)


tempfile.mkdtemp = precreated_mkdtemp
from setuptools.build_meta import build_wheel

print(build_wheel(str(WHEELHOUSE)))
