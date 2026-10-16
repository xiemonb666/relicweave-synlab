"""Scratch probe 27: leaves_at_level must agree with leaves() (indices and boxes)."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402

tree = C._Quadtree(-8.4, 8.4, -8.4, 8.4, 5)
tree.refine_all_to(7)      # uniform level 2
tree.refined.add((0, 0, 2))  # split exactly one cell
leaves = set(tree.leaves())
print("leaves", len(leaves), Counter(lv for _, _, lv in leaves), flush=True)
rebuilt = set()
for level in sorted({lv for _, _, lv in leaves}):
    block = tree.leaves_at_level(level)
    print("  level", level, "count", block.shape[0],
          "expected", sum(1 for x in leaves if x[2] == level), flush=True)
    rebuilt |= {(int(a), int(b), int(c)) for a, b, c in block}
print("match", rebuilt == leaves, "missing", len(leaves - rebuilt),
      "extra", len(rebuilt - leaves), flush=True)
# cell box sanity: the box of a descendant must lie inside its ancestor's box
for (i, j, level) in sorted(leaves):
    box = tree.cell_uv(i, j, level)
    if level > 0:
        anc = tree.cell_uv(i >> level, j >> level, 0)
        ok = (box[0] >= anc[0] - 1e-9 and box[1] <= anc[1] + 1e-9
              and box[2] >= anc[2] - 1e-9 and box[3] <= anc[3] + 1e-9)
        if not ok:
            print("BOX VIOLATION", (i, j, level), box, anc, flush=True)
print("box check done", flush=True)
