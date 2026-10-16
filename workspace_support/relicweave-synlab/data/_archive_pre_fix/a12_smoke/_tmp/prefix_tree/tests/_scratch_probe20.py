"""Scratch probe 20: direct quadtree sanity after refine_all_to."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from synlab.fracture.cut import _Quadtree  # noqa: E402

t = _Quadtree(-8.4, 8.4, -8.4, 8.4, 5)
print("side", t.side, "root_level", t.root_level, "hx", t.hx, flush=True)
for target in (5, 6, 7, 8):
    t2 = _Quadtree(-8.4, 8.4, -8.4, 8.4, 5)
    t2.refine_all_to(target)
    leaves = t2.leaves()
    hist = Counter(lv for _, _, lv in leaves)
    print("target", target, "root_level", t2.root_level, "leaves", len(leaves),
          "hist", dict(sorted(hist.items())),
          "cell_size(0)", t2.cell_size(0), "cell_size(1)", t2.cell_size(1), flush=True)
