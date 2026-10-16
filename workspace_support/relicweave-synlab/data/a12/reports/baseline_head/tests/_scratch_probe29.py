"""Scratch probe 29: leaves() vs leaves_at_level() on a genuinely mixed-level tree."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402

tree = C._Quadtree(-8.4, 8.4, -8.4, 8.4, 5)
print("initial side", tree.side, flush=True)
tree.refine_all_to(7)
print("after refine side", tree.side, "root_level", tree.root_level,
      "leaves", len(tree.leaves()), flush=True)
# split a handful of specific cells to force multiple levels
for cell in [(0, 0, 0), (1, 1, 0), (5, 3, 0)]:
    tree.refined.add(cell)
leaves = tree.leaves()
by_level: dict[int, list[tuple[int, int, int]]] = {}
for cell in leaves:
    by_level.setdefault(cell[2], []).append(cell)
print("levels", {lv: len(v) for lv, v in sorted(by_level.items())}, flush=True)
ok = True
for level, cells in sorted(by_level.items()):
    block = tree.leaves_at_level(level)
    got = {(int(a), int(b), int(c)) for a, b, c in block}
    want = set(cells)
    same = got == want
    ok &= same
    print("level", level, "leaves", len(want), "leaves_at_level", len(got), "match", same,
          flush=True)
print("ALL MATCH", ok, flush=True)
