#!/usr/bin/env python
"""Scratch: unit-scale check of the assembler-level T-junction resolution (not a production test).

Builds small quadtrees whose refinement pattern is valid (never a refined cell below a refined
ancestor) and known exactly, then asks the *production* ``edge_extra_all`` / ``cell_triangles``
what geometry they emit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(REPO_ROOT), str(Path(__file__).resolve().parents[2])):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from synlab.fracture import cut as cut_mod  # noqa: E402

KEY_LEVEL = 23
ROOT = 2
SIDE = 1 << ROOT


def tree_of(refined):
    tree = cut_mod._Quadtree(0.0, 4.0, 0.0, 4.0, ROOT)
    for (i, j, level) in refined:
        # only mark cells that are still leaves (a refined ancestor would make this invalid)
        ci, cj, cl = int(i), int(j), int(level)
        ok = True
        while cl > 0:
            cl, ci, cj = cl - 1, ci >> 1, cj >> 1
            if (ci, cj, cl) in tree.refined:
                ok = False
                break
        if ok:
            tree.refined.add((int(i), int(j), int(level)))
    return tree


def child_facing(cell, orient, lo, sub):
    """The child of ``cell`` (one level down) that faces ``orient``/``lo`` with sub-index ``sub``."""
    i, j, level = (int(x) for x in cell)
    if orient == "v":
        return (2 * i + (0 if lo else 1), 2 * j + int(sub), level + 1)
    return (2 * i + int(sub), 2 * j + (0 if lo else 1), level + 1)


def tri_area(pts, tri):
    p, q, r = (np.asarray(pts[t], dtype=np.float64) for t in tri)
    return 0.5 * ((q[0] - p[0]) * (r[1] - p[1]) - (r[0] - p[0]) * (q[1] - p[1]))


def show(title, tree, cell):
    block = np.asarray([cell], dtype=np.int64).reshape(-1, 3)
    ex = cut_mod.edge_extra_all(tree, block, KEY_LEVEL)[0]
    span = tree.key_span(cell[2], KEY_LEVEL)
    pts, tris = tree.cell_triangles(cell[0], cell[1], cell[2], span, ex)
    areas = np.array([tri_area(pts, t) for t in tris])
    print(f"--- {title}\n    cell={cell} splits={tree.edge_splits(*cell)} "
          f"extra={tuple(int(x) for x in ex)} pts={pts.shape[0]} tris={tris.shape[0]} "
          f"area_sum={areas.sum() / float((1 << (KEY_LEVEL - cell[2])) ** 2):.12f} "
          f"min_area={areas.min():.3e}")
    print("    pts:", [tuple(int(x) for x in p) for p in pts])
    return ex, pts, tris


def edge_interior_corners(tree, cell, orient, lo, key_level=KEY_LEVEL):
    """Key points strictly inside one edge of ``cell`` that are corners of *other* leaves.

    This is the ground truth for a conforming boundary: after T-junction resolution the ring
    ``cell_triangles`` emits must place exactly these points on the edge.
    """
    i, j, level = (int(x) for x in cell)
    span = int(key_level) - level
    step = 1 << span
    gu, gv = i << span, j << span
    if orient == "v":
        line = gu if lo else gu + step
        lo_k, hi_k = gv, gv + step
        mine = {"u": gu, "v": gv}
    else:
        line = gv if lo else gv + step
        lo_k, hi_k = gu, gu + step
        mine = {"u": gu, "v": gv}
    points = set()
    for (li, lj, ll) in tree.leaves():
        if (li, lj, ll) == (i, j, level):
            continue
        lspan = int(key_level) - int(ll)
        lstep = 1 << lspan
        lu, lv = li << lspan, lj << lspan
        corners = ((lu, lv), (lu + lstep, lv), (lu + lstep, lv + lstep), (lu, lv + lstep))
        for (cu, cv) in corners:
            if orient == "v" and cu == line and lo_k < cv < hi_k:
                points.add((cu, cv))
            elif orient == "u" and cv == line and lo_k < cu < hi_k:
                points.add((cu, cv))
    del mine
    return points


def ring_points_on_edge(pts, cell, orient, lo, key_level=KEY_LEVEL):
    i, j, level = (int(x) for x in cell)
    span = int(key_level) - level
    step = 1 << span
    gu, gv = i << span, j << span
    if orient == "v":
        line = gu if lo else gu + step
        lo_k, hi_k = gv, gv + step
        return {tuple(int(x) for x in p) for p in pts
                if int(p[0]) == line and lo_k < int(p[1]) < hi_k}
    line = gv if lo else gv + step
    lo_k, hi_k = gu, gu + step
    return {tuple(int(x) for x in p) for p in pts
            if int(p[1]) == line and lo_k < int(p[0]) < hi_k}


def check_edge(title, tree, cell, orient, lo):
    """Conformance of one edge: every *neighbour leaf corner* on it must be a point of my ring.

    The ring also carries the split midpoints the predicate puts there (that is the pre-existing
    behaviour), so the test is one-sided: no neighbour corner may be missing.  A missing one is
    exactly a T-junction — the neighbour would traverse an edge I never emit.
    """
    block = np.asarray([cell], dtype=np.int64).reshape(-1, 3)
    ex = cut_mod.edge_extra_all(tree, block, KEY_LEVEL)[0]
    index = {("v", True): 0, ("u", True): 1, ("v", False): 2, ("u", False): 3}[(orient, lo)]
    span = tree.key_span(cell[2], KEY_LEVEL)
    pts, _tris = tree.cell_triangles(cell[0], cell[1], cell[2], span, ex)
    want = edge_interior_corners(tree, cell, orient, lo)
    got = ring_points_on_edge(pts, cell, orient, lo)
    missing = want - got
    ok = not missing
    print(f"    [{'OK ' if ok else 'BAD'}] {title} edge=({orient},lo={lo}) extra={int(ex[index])} "
          f"corner_points={len(want)} ring_mid_points={len(got)} missing={sorted(missing)[:2]}")
    return ok, ex


def all_edges_ok(tree, cell):
    ok = True
    for orient, lo in (("v", True), ("u", True), ("v", False), ("u", False)):
        good, _ex = check_edge("conformance", tree, cell, orient, lo)
        ok = ok and good
    return ok


def main() -> int:
    target = (1, 1, 0)
    # B: nothing refined -> the pinned 4-point branch, no extras
    b = tree_of([])
    ex_b, pts_b, tris_b = show("B nothing refined", b, target)
    assert not ex_b.any() and pts_b.shape[0] == 4
    assert np.array_equal(tris_b, np.array([[0, 1, 2], [0, 2, 3]]))
    assert all_edges_ok(b, target)

    # C: plain 2:1 interface on the left -> midpoint only, extra == 1 (the neighbour's midline
    #    vertex is one halving inside my edge)
    c = tree_of([(0, 1, 0)])
    ex_c, _, _ = show("C plain 2:1 interface", c, target)
    assert c.edge_splits(*target)[0] is True
    assert int(ex_c[0]) == 1, ex_c
    assert all_edges_ok(c, target)

    # A: left neighbour refined AND the child facing my left edge refined too -> extra == 1
    a = tree_of([(0, 1, 0), child_facing((0, 1, 0), "v", False, 0)])
    ex_a, pts_a, _ = show("A left neighbour + facing child refined", a, target)
    assert int(ex_a[0]) == 1, ex_a
    assert all_edges_ok(a, target)
    #    the neighbour's own midline corner (at half of my edge) must be a point of my ring
    span = a.key_span(0, KEY_LEVEL)
    want = (1 << span, (1 << span) + (1 << (span - 1)))
    assert any(tuple(int(x) for x in p) == want for p in pts_a), (want, pts_a.tolist())
    # D: the *non-facing* child refined -> same extra, because the neighbour's own midline corner
    #    is what hangs inside my edge
    d = tree_of([(0, 1, 0), child_facing((0, 1, 0), "v", False, 1)])
    ex_d, _, _ = show("D non-facing child refined", d, target)
    assert int(ex_d[0]) == 1, ex_d
    assert all_edges_ok(d, target)

    # E: right neighbour with its facing child refined -> extra only on the right
    e = tree_of([(2, 1, 0), child_facing((2, 1, 0), "v", True, 1)])
    ex_e, _, _ = show("E right neighbour + facing child", e, target)
    assert int(ex_e[2]) == 1 and int(ex_e[0]) == 0, ex_e
    assert all_edges_ok(e, target)

    # F: both sides two levels finer -> two edges carry extras
    f = tree_of([(0, 1, 0), child_facing((0, 1, 0), "v", False, 0),
                 (2, 1, 0), child_facing((2, 1, 0), "v", True, 1)])
    ex_f, _, _ = show("F both sides", f, target)
    assert int(ex_f[0]) == 1 and int(ex_f[2]) == 1, ex_f
    assert all_edges_ok(f, target)

    # G: three levels -> extra == 2 (quarter points) on that edge
    g_ref = [(0, 1, 0), child_facing((0, 1, 0), "v", False, 0)]
    g_ref.append(child_facing(g_ref[-1], "v", False, 1))
    g_ref.append(child_facing(g_ref[-1], "u", False, 1))
    g = tree_of(g_ref)
    ex_g, _, _ = show("G three levels", g, target)
    print("    G refined:", sorted(g.refined), " extra =", tuple(int(x) for x in ex_g))
    assert all_edges_ok(g, target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
