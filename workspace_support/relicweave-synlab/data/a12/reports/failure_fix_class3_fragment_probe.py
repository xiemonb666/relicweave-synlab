"""Read-only audit of the committed fragments of the class-3 failing lineage.

Prints, per fragment, how many faces carry an interface face attribute, so the real
root cause (attribute absent / attribute all -1 / attribute length mismatch) is decided
from the stored asset instead of from a guess.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.schemas.runtime import ORIGIN_INTERFACE, ORIGIN_MOTHER_SURFACE  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

LINEAGES = sys.argv[1].split(",") if len(sys.argv) > 1 else ["LIN0004_V10_M06_PAT03"]

store = AssetStore(ROOT / "data" / "a12")
assets = store.list_assets(limit=500000)
for lineage in LINEAGES:
    print("=" * 90)
    print(lineage)
    frags = [a for a in assets if getattr(a, "lineage_id", None) == lineage
             and a.role == "fragment_mesh"]
    print(f"  committed fragment assets: {len(frags)}")
    for asset in frags:
        arrays = store.load_arrays(asset.asset_id)
        keys = sorted(k for k in arrays if "face__" in k)
        mesh = store.load_mesh(asset.asset_id, "mesh")
        n_faces = len(mesh.faces)
        meta = dict(asset.meta or {})
        info = []
        for key in keys:
            arr = np.asarray(arrays[key])
            row = f"{key.split('face__')[-1]}:n={arr.shape[0]}"
            if arr.shape[0] != n_faces:
                row += " LENGTH_MISMATCH"
            else:
                if arr.dtype.kind in "iu":
                    uniq, counts = np.unique(arr, return_counts=True)
                    if "interface_id" in key:
                        n_if = int(np.count_nonzero(arr >= 0))
                        row += f" interface_faces={n_if} values={dict(zip(uniq.tolist(), counts.tolist()))}"[:150]
                    else:
                        row += f" values={dict(zip(uniq.tolist(), counts.tolist()))}"[:150]
            info.append(row)
        print(f"  {asset.asset_id} faces={n_faces} frag={meta.get('fragment_id')} "
              f"comp={meta.get('component_id')} tiny={meta.get('is_tiny')} "
              f"vol={meta.get('volume_mm3')}")
        for row in info:
            print(f"      {row}")
        if not keys:
            print("      NO face__ arrays stored at all")
        print(f"      ORIGIN_INTERFACE={ORIGIN_INTERFACE} ORIGIN_MOTHER_SURFACE={ORIGIN_MOTHER_SURFACE}")
        md = dict(getattr(mesh, "metadata", None) or {})
        fa = md.get("face_attr_arrays") or {}
        print(f"      mesh.metadata face_attr_arrays keys: {sorted(fa)}")

