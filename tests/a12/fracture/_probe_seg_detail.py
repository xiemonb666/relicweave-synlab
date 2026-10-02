"""Dump the emitted top triangles around one bad edge, with world coordinates and edge use."""

from __future__ import annotations

import json
import sys
from collections import Counter

import numpy as np
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import _probe_rough_topology as probe  # noqa: E402

SEG = ((41943040, 276824064), (41943040, 285212672))


def main() -> int:
    built, info, basis, height = probe.build("box", 0.05, 0.01)
    tree, leaves, top_faces, top_edge_use, vertices, top_index = probe.top_surface(
        basis, height, 0.01)
    verts = np.asarray(vertices, dtype=np.float64)
    print(f"cells={len(leaves)} faces={len(top_faces)} verts={verts.shape[0]}")
    # which cells own the segment?
    lo = min(SEG[0], SEG[1])
    hi = max(SEG[0], SEG[1])
    owners = []
    for (i, j, level) in leaves:
        span = 23 - level
        base_i, base_j = i << span, j << span
        end = 1 << span
        x0, x1 = base_i, base_i + end
        y0, y1 = base_j, base_j + end
        inside = (x0 <= lo[0] <= x1 and y0 <= lo[1] <= y1
                  and x0 <= hi[0] <= x1 and y0 <= hi[1] <= y1)
        if inside and x0 == x1 - end and lo[0] in (x0, x1):
            owners.append((i, j, level))
    print("cells whose box contains the segment:", owners)
    for cell in owners:
        pts_ij, tris = tree.cell_triangles(cell[0], cell[1], cell[2], 23 - cell[2])
        keys = [(int(p[0]), int(p[1])) for p in pts_ij]
        ids = [top_index.get(k) for k in keys]
        print(f"\ncell {cell} splits={[bool(x) for x in tree.edge_splits(*cell)]}")
        for n, (k, v) in enumerate(zip(keys, ids)):
            print(f"   p{n} key={k} vert={v} world=({verts[v,0]:.6f},{verts[v,1]:.6f})")
        for n, tri in enumerate(tris):
            ring = [f"p{tri[m]}" for m in range(3)]
            w = [(float(verts[ids[tri[m]], 0]), float(verts[ids[tri[m]], 1])) for m in range(3)]
            print(f"   tri {ring} verts={[ids[tri[m]] for m in range(3)]} "
                  f"world={[(round(a,4), round(b,4)) for a, b in w]}")
    # edge use of the segment's lattice key
    seg_key = (lo, hi)
    print("\nsegment lattice key:", seg_key)
    for n, tri in enumerate(top_faces):
        ring = [(int(tri[0]), int(tri[1])), (int(tri[1]), int(tri[2])),
                (int(tri[2]), int(tri[0]))]
        for a, b in ring:
            ka = [k for k, v in top_index.items() if v == a]
            kb = [k for k, v in top_index.items() if v == b]
            if not ka or not kb:
                continue
            key = (min(ka[0], kb[0]), max(ka[0], kb[0]))
            if key == seg_key:
                print(f"  face {n} {tri} uses the segment as ({a},{b})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
