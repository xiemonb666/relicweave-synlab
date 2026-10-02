#!/usr/bin/env python
"""Scratch: do the leaf rectangles tile the frame?  (a leaf set that overlaps is not a quadtree)"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(REPO_ROOT), str(Path(__file__).resolve().parents[2])):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from synlab.fracture import api as api_mod  # noqa: E402
from synlab.fracture import cut as cut_mod  # noqa: E402
from synlab.fracture.spec import BACKEND_ROUGH, FractureSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

import fixtures as fx  # noqa: E402

PAIR = ((229, 208, 3), (228, 207, 3))


def main() -> int:
    real_extras = cut_mod.edge_extra_all
    calls: list[dict] = []

    def capture(tree, block, key_level):
        value = real_extras(tree, block, key_level)
        rows = np.asarray(block, dtype=np.int64).reshape(-1, 3)
        if not calls or rows.shape[0] >= calls[-1]["block"].shape[0]:
            calls.append({"tree": tree, "block": rows, "extras": value})
        return value

    cut_mod.edge_extra_all = capture
    mother = fx.thin_bowl_mother()
    spec = FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=0.02,
                        error_budget_mm=0.011, max_cutter_cells=90000)
    try:
        api_mod.make_closed_cutter(mother, spec, make_rng(20261001, "tj_resolution",
                                                          "bowl-lo_0.02_0.011_90000"))
    except Exception as exc:  # noqa: BLE001
        print("build:", type(exc).__name__, str(exc).split("\n", 1)[0])
    finally:
        cut_mod.edge_extra_all = real_extras

    state = calls[-1]
    tree, block = state["tree"], state["block"]
    leaf_set = {(int(a), int(b), int(c)) for a, b, c in block}
    print("leaves", block.shape[0], "refined entries", len(tree.refined), "side", tree.side)
    print("refined entries that are also leaves:", len(leaf_set & tree.refined))
    levels = {}
    for (i, j, level) in block:
        levels[int(level)] = levels.get(int(level), 0) + 1
    print("leaf levels:", dict(sorted(levels.items())))
    # is (228,207,3) really in the refined set's subtree sense?  print its ancestors
    for cell in PAIR:
        i, j, level = cell
        chain = []
        ci, cj, cl = int(i), int(j), int(level)
        while cl > 0:
            cl, ci, cj = cl - 1, ci >> 1, cj >> 1
            chain.append(((ci, cj, cl), (ci, cj, cl) in tree.refined))
        print(f"{cell} ancestors: {chain}")
    print("root cells refined:", sum(1 for k in tree.refined if k[2] == 0),
          "of", tree.side ** 2)
    print("(228,207,3) in refined:", (228, 207, 3) in tree.refined)
    print("(229,208,3) in refined:", (229, 208, 3) in tree.refined)
    kids_b = [(2 * 228 + di, 2 * 207 + dj, 4) for di in (0, 1) for dj in (0, 1)]
    print("children of (228,207,3):",
          [(k, k in tree.refined, k in leaf_set) for k in kids_b])

    # does any leaf have a refined ancestor in the set?  (a stale entry)
    stale = 0
    leaf_set = {(int(a), int(b), int(c)) for a, b, c in block}
    for (i, j, level) in block:
        ci, cj, cl = int(i), int(j), int(level)
        while cl > 0:
            cl, ci, cj = cl - 1, ci >> 1, cj >> 1
            if (ci, cj, cl) in tree.refined:
                stale += 1
                break
    print("leaves with a refined ancestor still in the set:", stale)

    for cell in PAIR:
        i, j, level = cell
        hx, hy = tree.cell_size(level)
        u0 = tree.u0 + i * hx
        v0 = tree.v0 + j * hy
        print(f"leaf {cell}: u=[{u0:.9f},{u0 + hx:.9f}) v=[{v0:.9f},{v0 + hy:.9f}) "
              f"in_leaves={cell in leaf_set} refined={cell in tree.refined}")

    # independent check of 'leaves()': walk the grid from the root and count the covering cells
    side = tree.side
    cover: dict[tuple[int, int], tuple[int, int, int]] = {}
    stack = [(i, j, 0) for i in range(side) for j in range(side)]
    multiplicity = np.zeros((side, side), dtype=np.int64)
    while stack:
        i, j, level = stack.pop()
        if (i, j, level) in tree.refined:
            stack.extend([(2 * i, 2 * j, level + 1), (2 * i + 1, 2 * j, level + 1),
                          (2 * i, 2 * j + 1, level + 1), (2 * i + 1, 2 * j + 1, level + 1)])
            continue
        scale = 1 << level
        multiplicity[i * scale:(i + 1) * scale, j * scale:(j + 1) * scale] += 1
        cover[(i, j)] = (i, j, level)
    print("coverage multiplicity histogram:", dict(zip(*np.unique(multiplicity,
                                                                  return_counts=True))))

    # direct rectangle overlap test on the two cells of interest
    (ai, aj, al), (bi, bj, bl) = PAIR
    ahx, ahy = tree.cell_size(al)
    bhx, bhy = tree.cell_size(bl)
    a0, a1 = tree.u0 + ai * ahx, tree.u0 + (ai + 1) * ahx
    b0, b1 = tree.u0 + bi * bhx, tree.u0 + (bi + 1) * bhx
    c0, c1 = tree.v0 + aj * ahy, tree.v0 + (aj + 1) * ahy
    d0, d1 = tree.v0 + bj * bhy, tree.v0 + (bj + 1) * bhy
    print(f"  A u=[{a0:.9f},{a1:.9f}) v=[{c0:.9f},{c1:.9f})")
    print(f"  B u=[{b0:.9f},{b1:.9f}) v=[{d0:.9f},{d1:.9f})")
    print(f"  overlap u: ({max(a0, b0):.9f},{min(a1, b1):.9f}) "
          f"v: ({max(c0, d0):.9f},{min(c1, d1):.9f})")
    print("  total leaf area vs frame area:",
          sum(tree.cell_size(int(l))[0] * tree.cell_size(int(l))[1] for _i, _j, l in block),
          (tree.u1 - tree.u0) * (tree.v1 - tree.v0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
