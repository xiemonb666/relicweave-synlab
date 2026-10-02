#!/usr/bin/env python
"""Scratch: dump the vectorised walk step by step (a copy of the helper's body)."""
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


def main() -> int:
    tree = cut_mod._Quadtree(0.0, 4.0, 0.0, 4.0, 2)
    tree.refined.add((0, 1, 0))
    rows = np.array([[1, 1, 0]], dtype=np.int64)
    n = 1
    lookup = np.fromiter((i * (1 << 32) + j * 256 + l for (i, j, l) in tree.refined),
                         dtype=np.int64, count=len(tree.refined))
    level = np.repeat(rows[:, 2], 4).astype(np.int64)
    span = np.repeat(KEY_LEVEL - rows[:, 2], 4).astype(np.int64)
    corner_u = np.repeat(rows[:, 0], 4) << span
    corner_v = np.repeat(rows[:, 1], 4) << span
    edge = np.tile(np.arange(4, dtype=np.int64), n)
    vertical = (edge % 2) == 0
    lo_side = np.tile(np.array([True, True, False, False]), n)
    si = np.where(vertical, np.repeat(rows[:, 0], 4) + np.where(lo_side, -1, 1),
                  np.repeat(rows[:, 0], 4))
    sj = np.where(vertical, np.repeat(rows[:, 1], 4),
                  np.repeat(rows[:, 1], 4) + np.where(lo_side, -1, 1))
    limit = np.int64(tree.side) << level
    alive = (si >= 0) & (sj >= 0) & (si < limit) & (sj < limit)
    shift_1 = span - 1
    sub_u = np.int64(1) - ((corner_u >> shift_1) & np.int64(1))
    sub_v = np.int64(1) - ((corner_v >> shift_1) & np.int64(1))
    depth = np.zeros((n, 4), dtype=np.int64)
    remaining = span - 1
    print("init si", si, "sj", sj, "alive", alive, "sub", sub_u, sub_v)
    for step in range(4):
        present = np.zeros(alive.shape, dtype=bool)
        if lookup.size:
            live = np.flatnonzero(alive)
            if live.size:
                keys = si[live] * (1 << 32) + sj[live] * (1 << 8) + level[live]
                present[live] = np.isin(keys, lookup)
        print(f"step {step}: level={level} alive={alive} present={present} "
              f"keys={si * (1 << 32) + sj * 256 + level}")
        depth = np.where(present, depth + 1, depth)
        remaining = np.where(present & (remaining > 0), remaining - 1, 0)
        if not bool(np.any(present & (remaining > 0))):
            break
        si = 2 * si + np.where(vertical, sub_u, sub_v)
        sj = 2 * sj + np.where(vertical, sub_v, sub_u)
        level = level + 1
        shift_1 = shift_1 - 1
        sub_u = np.int64(1) - ((corner_u >> shift_1) & np.int64(1))
        sub_v = np.int64(1) - ((corner_v >> shift_1) & np.int64(1))
        limit = np.int64(tree.side) << level
        alive = (si >= 0) & (sj >= 0) & (si < limit) & (sj < limit)
    print("depth", depth)
    print("helper", cut_mod.edge_extra_all(tree, rows, KEY_LEVEL))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
