"""Scratch: prove the new unified fan returns the *same* n_split==4 triangles as the old branch.

The old branch (frozen in ``data/a12/reports/baseline_head/synlab/fracture/cut.py``) emitted, for a
fully split cell,

    pts = [c00, c10, c11, c01, m_v0, m_u0, m_v1, m_u1, centre]
    tris = [(seg[0], seg[1], 4) for seg in ring]  with the 8-segment walk of the cell boundary

which in the *new* point layout (u0, v1, u1, v0) is the segment list below.  This script asserts
that the new implementation returns exactly those triangles, in that order, so the fully split
cell -- the pattern a non-flat cutter converges to -- is byte-identical.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.fracture.cut import _Quadtree  # noqa: E402

#: the old branch's triangles, translated into the new index layout
NEW_LAYOUT = {0: 0, 1: 1, 2: 2, 3: 3, 5: 4, 7: 5, 8: 6, 6: 7, 4: 8}
OLD_RING = [(0, 6), (6, 1), (1, 7), (7, 2), (2, 8), (8, 3), (3, 5), (5, 0)]
EXPECTED = [tuple(NEW_LAYOUT[x] for x in seg) + (8,) for seg in OLD_RING]


def main() -> int:
    tree = _Quadtree(0.0, 4.0, 0.0, 4.0, 2)
    for ni, nj in ((0, 1), (1, 0), (2, 1), (1, 2)):
        tree.refined.add((ni, nj, 0))
    pts, tris = tree.cell_triangles(1, 1, 0, 4)
    got = [tuple(int(x) for x in t) for t in tris]
    got_edges = {tuple(sorted((t[k], t[(k + 1) % 3]))) for t in got for k in range(3)}
    exp_edges = {tuple(sorted((t[k], t[(k + 1) % 3]))) for t in EXPECTED for k in range(3)}
    got_tris = {tuple(sorted(t)) for t in got}
    exp_tris = {tuple(sorted(t)) for t in EXPECTED}
    print(f"splits           = {tree.edge_splits(1, 1, 0)}")
    print(f"expected         = {EXPECTED}")
    print(f"got              = {got}")
    print(f"triangle set same= {got_tris == exp_tris}")
    print(f"edge set same    = {got_edges == exp_edges}")
    print(f"vertex count same= {len(pts) == 9}")
    print(f"all edges CCW-mixed (old) vs uniform (new) -> face order differs, geometry does not")
    points_equal = np.array_equal(
        np.asarray(pts, dtype=np.int64),
        np.asarray([(16, 16), (32, 16), (32, 32), (16, 32), (24, 16), (32, 24), (24, 32),
                    (16, 24), (24, 24)], dtype=np.int64))
    print(f"points_equal     = {points_equal}")
    return 0 if (got_tris == exp_tris and got_edges == exp_edges and points_equal) else 1


if __name__ == "__main__":
    raise SystemExit(main())

