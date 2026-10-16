"""Scratch probe 11: does top_vertex() give the same (u,v) for a shared key from two levels?"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402

tree = C._Quadtree(0.0, 32.0, 0.0, 32.0, 5)
tree.refine_all_to(2)
key_level = 2 + 5 + 12  # root(0..2 relative) + level0 5 + 12 headroom
print("key_level", key_level, flush=True)
for level in (0, 1, 2):
    span = key_level - tree.absolute_level(level)
    print("level", level, "abs", tree.absolute_level(level), "span", span,
          "cell", tree.cell_size(level), flush=True)
# global key of a shared vertex: level-0 cell (0,0) has span S0, its corner index 0 and
# the right edge midpoint index 2**(S0-1).  The level-1 child's corner index for that point
# must be 2**S1.
s0 = key_level - tree.absolute_level(0)
s1 = key_level - tree.absolute_level(1)
shared_from_parent = np.array([[2 ** (s0 - 1), 0]], dtype=np.int64)   # midpoint of left edge
shared_from_child = np.array([[2 ** s1, 2 ** s1]], dtype=np.int64)     # corner of child? see below
u_p, v_p = C._cell_uv(tree, 0, s0, shared_from_parent)
# child cell (0,1) is the top-left child of parent (0,0): its own (0,0) corner index is
# 0 but in the parent's key space that point is the parent's left-edge midpoint.
u_c, v_c = C._cell_uv(tree, 1, s1, np.array([[0, 0]], dtype=np.int64))
print("parent midpoint", u_p, v_p, "child corner (0,0)", u_c, v_c, flush=True)
u_c2, v_c2 = C._cell_uv(tree, 1, s1, np.array([[2 * 2 ** (s0 - 1), 0]], dtype=np.int64))
print("child with parent-scaled index", u_c2, v_c2, flush=True)
