from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest


_TMP_ROOT = Path(__file__).resolve().parent / "pytest-tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def tmp_path(request):
    path = _TMP_ROOT / f"{request.node.name}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class _TemporaryPathFactory:
    def mktemp(self, basename: str, numbered: bool = True) -> Path:
        suffix = f"-{uuid.uuid4().hex[:8]}" if numbered else ""
        path = _TMP_ROOT / f"{basename}{suffix}"
        path.mkdir(parents=True, exist_ok=False)
        return path

    def getbasetemp(self) -> Path:
        return _TMP_ROOT


@pytest.fixture(scope="session")
def tmp_path_factory():
    return _TemporaryPathFactory()


if __name__ == "__main__":
    targets = sys.argv[1:]
    raise SystemExit(pytest.main([
        "-o", "addopts=", "-p", "no:cacheprovider", "-p", "no:tmpdir",
        *targets,
    ], plugins=[sys.modules[__name__]]))
