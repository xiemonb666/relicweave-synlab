"""Scratch: dump the raw points/triangles of one split pattern."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.fracture.cut import _Quadtree  # noqa: E402


def run(flags):
    tree = _Quadtree(0.0, 4.0, 0.0, 4.0, 2)
    i, j = 1, 1
    wants = {(i - 1, j): flags[0], (i, j - 1): flags[1], (i + 1, j): flags[2], (i, j + 1): flags[3]}
    for (ni, nj), want in wants.items():
        if want:
            tree.refined.add((ni, nj, 0))
    pts, tris = tree.cell_triangles(i, j, 0, 4)
    print(f"flags={flags} reported={tree.edge_splits(i, j, 0)}")
    for k, p in enumerate(pts):
        print(f"  pts[{k}] = {tuple(int(x) for x in p)}")
    total = 0.0
    for t in tris:
        a, b, c = (pts[int(x)].astype(float) for x in t)
        area = 0.5 * ((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))
        total += area
        print(f"  tri {tuple(int(x) for x in t)}  area={area:+.4f}")
    print(f"  total={total:+.4f}")


for flags in [(True, False, False, False), (False, True, False, False),
              (False, False, True, False), (False, False, False, True),
              (True, True, True, True)]:
    run(flags)

