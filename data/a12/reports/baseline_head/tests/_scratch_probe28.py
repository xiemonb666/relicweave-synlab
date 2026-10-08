"""Scratch probe 28: is (1,21,2) really a leaf, and where does its box sit?"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402

tree = C._Quadtree(-8.4, 8.4, -8.4, 8.4, 5)
all_leaves = tree.leaves()
print("root leaves", len(all_leaves), "levels", sorted({lv for _, _, lv in all_leaves}),
      flush=True)
leaf_set = set(all_leaves)
print("is (1,21,2) in leaves()?", (1, 21, 2) in leaf_set, flush=True)
# force a deeper tree: refine to level 6 then check
tree2 = C._Quadtree(-8.4, 8.4, -8.4, 8.4, 5)
tree2.refine_all_to(6)
tree2.refined.add((0, 0, 1))
ls2 = set(tree2.leaves())
print("t2 leaves", len(ls2), sorted({lv for _, _, lv in ls2}), flush=True)
block = tree2.leaves_at_level(2)
print("t2 level2 block", block.shape, block[:4].tolist(), flush=True)
for row in block[:4]:
    i, j, lv = (int(row[0]), int(row[1]), int(row[2]))
    print("   cell", (i, j, lv), "in leaves?", (i, j, lv) in ls2,
          "box", np.round(tree2.cell_uv(i, j, lv), 5).tolist(), flush=True)
print("descend(1,21,2) ->", tree2.descend(1, 21, 2), flush=True)
