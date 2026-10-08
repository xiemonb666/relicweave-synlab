"""Scratch probe 6: instrumented copy of refine_all_to."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from synlab.fracture.cut import _Quadtree  # noqa: E402

tree = _Quadtree(0.0, 30.0, 0.0, 30.0, 5)
target_level = 6
iteration = 0
start = time.perf_counter()
while tree.root_level < target_level:
    iteration += 1
    leaves = tree.leaves()
    print("iter", iteration, "root_level", tree.root_level, "leaves", len(leaves),
          "refined_set", len(tree.refined), flush=True)
    for i, j, level in leaves:
        tree.refined.add((i, j, level))
    print("  after marking refined_set", len(tree.refined), flush=True)
    if iteration > 5:
        print("BAIL", flush=True)
        break
print("done", round(time.perf_counter() - start, 4), flush=True)
