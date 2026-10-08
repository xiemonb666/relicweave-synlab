"""Scratch probe 10: trace refine_all_to and leaves()."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collections import Counter  # noqa: E402

from synlab.fracture.cut import _Quadtree  # noqa: E402

t = _Quadtree(-8.4, 8.4, -8.4, 8.4, 5)
print("root", t.root_level, "side", t.side, flush=True)
t.refined.add((0, 0, 0))
print("after single refine:", sorted(Counter(lv for _, _, lv in t.leaves()).items()),
      len(t.leaves()), flush=True)
t2 = _Quadtree(-8.4, 8.4, -8.4, 8.4, 5)
for step in range(4):
    t2.refine_all_to(t2.root_level + 1)
    print("step", step, "root", t2.root_level, "leaves", len(t2.leaves()),
          sorted(Counter(lv for _, _, lv in t2.leaves()).items()), flush=True)
