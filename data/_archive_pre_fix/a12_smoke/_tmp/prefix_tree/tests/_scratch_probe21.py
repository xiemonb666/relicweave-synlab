"""Scratch probe 21: print refine_all_to progress inside _Quadtree."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from synlab.fracture.cut import _Quadtree  # noqa: E402

t = _Quadtree(-8.4, 8.4, -8.4, 8.4, 5)
target = 8
guard = 0
while t.root_level < target:
    guard += 1
    leaves = t.leaves()
    hist = Counter(lv for _, _, lv in leaves)
    print("iter", guard, "root_level", t.root_level, "leaves", len(leaves),
          "hist", dict(sorted(hist.items())), flush=True)
    t.refined.update((i, j, level) for i, j, level in leaves)
    t.root_level += 1
    if guard > 6:
        print("GUARD", flush=True)
        break
print("final root_level", t.root_level, "leaves", len(t.leaves()),
      "hist", dict(sorted(Counter(lv for _, _, lv in t.leaves()).items())), flush=True)
