"""Probe 5: prove the cut plane normal is a closed set and that plane_normal is honoured.

Loads a committed mother from the store, runs one plane cut with the body-determined default
and one with an explicit normal, and reports the measured interface normal of each.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.fracture.api import fracture_event  # noqa: E402
from synlab.fracture.spec import FractureSpec  # noqa: E402
from synlab.mothers.api import load_mother  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def plane_normal_of(fracture) -> np.ndarray | None:
    """PCA of the interface sample points -> the cut plane normal (world mm)."""
    from synlab.truth.api import _merge_pair_edges  # noqa: F401  (import check only)

    pts = []
    for patch in fracture.interfaces:
        p = getattr(patch, "points_a", None)
        if p is not None and np.asarray(p).size:
            pts.append(np.asarray(p, dtype=np.float64))
    if not pts:
        return None
    P = np.concatenate(pts, axis=0)
    P = P - P.mean(axis=0)
    _, _, vt = np.linalg.svd(P, full_matrices=False)
    n = vt[2]
    return n / max(float(np.linalg.norm(n)), 1e-12)


store = AssetStore(ROOT / "data" / "a12")
conn = store._conn if hasattr(store, "_conn") else None
import sqlite3  # noqa: E402

c = sqlite3.connect(f"file:{(ROOT / 'data/a12/metadata.sqlite').as_posix()}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
rows = c.execute("SELECT asset_id, lineage_id, meta_json FROM assets WHERE role='mother_mesh' "
                 "AND meta_json LIKE '%V01%' ORDER BY created_at LIMIT 3").fetchall()
print("mother candidates:", [(r["asset_id"], r["lineage_id"]) for r in rows])

normals = {}
for r in rows:
    mother = load_mother(store, r["asset_id"])
    meta = json.loads(r["meta_json"])
    for tag, spec in (
        ("default", FractureSpec(backend="plane_shared_cut")),
        ("explicit", FractureSpec(backend="plane_shared_cut",
                                  plane_normal=np.array([0.0, 0.0, 1.0]),
                                  plane_point=np.asarray(mother.mesh.vertices, dtype=np.float64).mean(axis=0))),
    ):
        fr = fracture_event(mother, spec, make_rng(20261001, r["lineage_id"], "cut"),
                            event_id=f"{r['lineage_id']}_{tag}")
        n = plane_normal_of(fr)
        normals.setdefault(tag, []).append(n)
        print(f"{r['lineage_id']:28s} {tag:9s} backend={fr.backend:18s} "
              f"frags={len(fr.fragments)} n={None if n is None else np.round(n, 6).tolist()}")

print()
for tag, ns in normals.items():
    good = [n for n in ns if n is not None]
    if len(good) >= 2:
        d = float(np.degrees(np.arccos(np.clip(abs(np.dot(good[0], good[1])), -1, 1))))
        print(f"{tag}: pairwise |angle| between first two = {d:.6f} deg")
