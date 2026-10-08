from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest


_TMP_ROOT = Path(__file__).resolve().parent / "custom-pytest-tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def tmp_path(request):
    component = f"{request.node.name}-{uuid.uuid4().hex[:8]}"
    path = _TMP_ROOT / component
    path.mkdir(parents=True, exist_ok=True)
    return path


if __name__ == "__main__":
    targets = sys.argv[1:]
    raise SystemExit(pytest.main([
        "-o", "addopts=", "-p", "no:cacheprovider", "-p", "no:tmpdir",
        *targets,
    ], plugins=[sys.modules[__name__]]))
