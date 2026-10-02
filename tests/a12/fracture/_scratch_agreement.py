"""Scratch: is the split predicate *two-sided*?  (the necessary and sufficient condition)

For a conforming top surface every interior edge must be split by **both** of the two leaves that
share it, or by neither.  If one side splits and the other does not, one of them carries a vertex
the other does not have -- a T-junction -- and the assembler turns it into overlapping side quads
(over-used edges) or a hole (single-use edges).

This is checked on a real refined quadtree, edge by edge, over every adjacent leaf pair.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from synlab.fracture.cut import _Quadtree  # noqa: E402


def leaf_at(tree: _Quadtree, i: int, j: int, level: int):
    """Descend from a level-``level`` cell to the leaf that covers it."""
    while tree.is_refined(i, j, level):
        i, j, level = 2 * i, 2 * j, level + 1
    return i, j, level


def audit(tree: _Quadtree) -> dict:
    """Every adjacent leaf pair: do both sides agree on the split of their shared edge?"""
    disagree = 0
    checked = 0
    examples = []
    for i, j, level in tree.leaves():
        for orient, lo in (("v", True), ("u", True), ("v", False), ("u", False)):
            mine = tree.edge_split(i, j, level, orient, lo)
            # find the neighbour leaf across this edge, at whatever level it lives
            limit = int(tree.side) << int(level)
            if orient == "v":
                ni = i - 1 if lo else i + 1
                nj = j
            else:
                nj = j - 1 if lo else j + 1
                ni = i
            if not (0 <= ni < limit and 0 <= nj < limit):
                continue
            other = leaf_at(tree, ni, nj, level)
            # is the shared edge split by the other side?  express it in ITS own coordinates
            if other[2] > level:                     # neighbour is finer: it owns the edge halves
                scale = 1 << (other[2] - level)
                oi = ni * scale + (0 if lo else scale - 1)
                oj = nj * scale
                their_edges = [tree.edge_split(oi, oj, other[2], orient, True),
                               tree.edge_split(oi, oj, other[2], orient, False)]
                theirs = all(their_edges) if lo else all(their_edges)
                # a finer neighbour leaves both halves whole when the coarse side does not split
                theirs = any(tree.edge_split(oi, oj, other[2], orient, lo2)
                             for lo2 in (True, False))
            elif other[2] == level:
                theirs = tree.edge_split(other[0], other[1], other[2], orient, not lo)
            else:                                     # neighbour is coarser: it owns the midpoint
                scale = 1 << (level - other[2])
                theirs = tree.edge_split(other[0], other[1], other[2], orient, lo)
                theirs = theirs
            del mine, theirs
            checked += 1
    del disagree, examples
    return {"checked": checked}


def main() -> int:
    tree = _Quadtree(0.0, 4.0, 0.0, 4.0, 2)
    # refine a patchy region so the tree is genuinely graded
    tree.refine_bulk([(1, 1, 0)])
    tree.refine_bulk([(2, 2, 1), (3, 2, 1)])
    tree.refine_bulk([(4, 4, 2)])
    leaves = sorted(tree.leaves())
    print(f"leaves: {len(leaves)}")
    print(f"refined: {sorted(tree.refined)}")
    bad = 0
    for i, j, level in leaves:
        for orient, lo in (("v", True), ("u", True), ("v", False), ("u", False)):
            limit = int(tree.side) << int(level)
            if orient == "v":
                ni, nj = (i - 1 if lo else i + 1), j
            else:
                ni, nj = i, (j - 1 if lo else j + 1)
            if not (0 <= ni < limit and 0 <= nj < limit):
                continue
            oi, oj, ol = leaf_at(tree, ni, nj, level)
            mine = tree.edge_split(i, j, level, orient, lo)
            # the neighbour's own answer for the same physical edge
            if ol == level:
                theirs = tree.edge_split(oi, oj, ol, orient, not lo)
            else:
                # the neighbour is at another level: the physical edge is the neighbour's edge
                # segment that faces me; use the neighbour's own predicate on its own indices
                theirs = tree.edge_split(oi, oj, ol, orient, lo if ol > level else not lo)
            if mine != theirs:
                bad += 1
                if bad <= 12:
                    print(f"  DISAGREE leaf=({i},{j},{level}) {orient} lo={lo} mine={mine} "
                          f"neighbour=({oi},{oj},{ol}) theirs={theirs}")
    print(f"disagreeing adjacent pairs: {bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
