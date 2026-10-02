"""Scratch: ground truth for the ``refined`` set's index lattice."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from synlab.fracture.cut import _Quadtree  # noqa: E402


def show(title: str, tree: _Quadtree) -> None:
    print(f"{title}")
    print(f"  refined = {sorted(tree.refined)}")
    print(f"  leaves  = {sorted(tree.leaves())}")


t = _Quadtree(0.0, 4.0, 0.0, 4.0, 2)
print(f"side={t.side} hx={t.hx} hy={t.hy}")
show("refine (0,1,0) only:", t)
t.refine_bulk([(0, 1, 0)])
show("after refine_bulk([(0,1,0)]):", t)

t2 = _Quadtree(0.0, 4.0, 0.0, 4.0, 2)
t2.refine_bulk([(0, 1, 0), (0, 2, 1)])
show("after refine_bulk([(0,1,0),(0,2,1)]):", t2)
print(f"  edge_splits(1,1,0) = {t2.edge_splits(1, 1, 0)}")
