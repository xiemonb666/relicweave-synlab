"""Scratch probe 25: verify key-lattice consistency across cell levels."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402

u0, u1, v0, v1 = -8.4, 8.4, -8.4, 8.4
tree = C._Quadtree(u0, u1, v0, v1, 5)
tree.refine_all_to(8)
key_level = 12
print("side", tree.side, "hx", tree.hx, "root_level", tree.root_level, flush=True)

# After refine_all_to(8) with root_level 5, cells are at level 3 relative to the root grid.
for level in (0, 1, 2, 3):
    span = tree.key_span(level, key_level)
    print("level", level, "span", span, "cell", tree.cell_size(level),
          "key unit", tree.cell_size(level)[0] / (1 << span), flush=True)

# consistency: parent (0,0,level) and child (0,0,level+1) must place the same key identically
for level in (0, 1, 2):
    s = tree.key_span(level, key_level)
    sc = tree.key_span(level + 1, key_level)
    parent_pts, _ = tree.cell_triangles(1, 1, level, s)
    child_pts, _ = tree.cell_triangles(2, 2, level + 1, sc)
    pu, pv = C._cell_uv(tree, level, s, parent_pts)
    cu, cv = C._cell_uv(tree, level + 1, sc, child_pts)
    # the child's c00 equals the parent's centre (m_v.. convention: parent corner (half,half))
    print("level", level, "parent c00", (round(pu[0], 6), round(pv[0], 6)),
          "child c00", (round(cu[0], 6), round(cv[0], 6)), flush=True)
    shared = (2 ** (s - 1), 2 ** (s - 1))     # parent centre key
    su, sv = C._cell_uv(tree, level, s, np.array([shared], dtype=np.int64))
    print("   to_uv(level, parent-centre)",
          (round(float(su[0]), 6), round(float(sv[0]), 6)), flush=True)
