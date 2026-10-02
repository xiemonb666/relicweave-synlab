"""Throw-away recon for S11: which store has a big clean fragment + a P03 recipe?"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.roles import ROLE_FRAGMENT_MESH  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def main() -> int:
    for root in sys.argv[1:]:
        store = AssetStore(root)
        try:
            assets = store.list_assets(role=ROLE_FRAGMENT_MESH, limit=100000)
        except Exception as exc:  # noqa: BLE001
            print(f"{root}: {type(exc).__name__}: {exc}")
            continue
        rows = []
        for record in assets[:40]:
            try:
                mesh = store.load_mesh(record.asset_id, "mesh")
            except Exception:  # noqa: BLE001
                continue
            rows.append((float(abs(mesh.volume)), int(len(mesh.faces)), bool(mesh.is_watertight),
                         str(record.meta.get("fragment_id")), int(len(mesh.vertices))))
        rows.sort(reverse=True)
        print(f"=== {root}: {len(assets)} fragment_mesh assets")
        for volume, faces, wt, fid, nv in rows[:4]:
            print(f"    vol={volume:12.2f} faces={faces:7d} verts={nv:6d} wt={wt} {fid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
