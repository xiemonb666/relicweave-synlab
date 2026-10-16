"""Dev server launcher for the UI work (real backend, real store root).

``synlab.api.app:create_app`` is a factory that requires ``store_root``; uvicorn's
``--factory`` cannot pass it, so this thin launcher builds the real app exactly the way
``tests/a12/api/conftest.py`` does and hands it to uvicorn.

Usage::

    python tests/a12/api_ui/_serve.py --store-root data/a12 --port 8077 --role researcher
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-root", default=str(REPO_ROOT / "data" / "a12"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8077)
    parser.add_argument("--role", default="researcher",
                        choices=("researcher", "operator", "deployment_client"))
    parser.add_argument("--workspace", default="default")
    args = parser.parse_args()

    import uvicorn

    from synlab.api import create_app

    root = Path(args.store_root)
    root.mkdir(parents=True, exist_ok=True)
    app = create_app(root, role=args.role, workspace=args.workspace, docs=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
