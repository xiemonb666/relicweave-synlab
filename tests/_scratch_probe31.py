"""Scratch probe 31: after one refinement pass, does leaves() == leaves_at_level()?"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402

tree = C._Quadtree(-8.4, 8.4, -8.4, 8.4, 5)
tree.refine_uniform_to(7)                     # uniform, relative level 0, side 128
leaves0 = tree.leaves()
print("uniform leaves", len(leaves0), "levels",
      sorted({lv for _, _, lv in leaves0}), "side", tree.side, flush=True)
# mark a single cell for refinement, as the error loop would
target = leaves0[0]
tree.refine_bulk(np.asarray([target], dtype=np.int64))
leaves = tree.leaves()
by_level: dict[int, set] = {}
for cell in leaves:
    by_level.setdefault(cell[2], set()).add(cell)
print("after split: leaves", len(leaves), {lv: len(v) for lv, v in by_level.items()},
      flush=True)
for level, want in sorted(by_level.items()):
    got = {(int(a), int(b), int(c)) for a, b, c in tree.leaves_at_level(level)}
    print("  level", level, "want", len(want), "got", len(got), "equal", got == want,
          flush=True)
    if got != want:
        print("    missing", sorted(want - got)[:3], flush=True)
        print("    extra", sorted(got - want)[:3], flush=True)
        for cell in sorted(want - got)[:2]:
            print("    want cell box", np.round(tree.cell_uv(*cell), 6).tolist(),
                  "refined ancestors:",
                  [(cell[0] >> k, cell[1] >> k, cell[2] - k) in tree.refined
                   for k in range(1, cell[2] + 1)], flush=True)
