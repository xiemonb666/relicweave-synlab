"""Scratch probe 8: per-cell interpolation error statistics after refinement."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402

pts = np.asarray([[-6, -6, -6], [6, -6, -6], [6, 6, -6], [-6, 6, -6],
                  [-6, -6, 6], [6, -6, 6], [6, 6, 6], [-6, 6, 6]], dtype=np.float64)
basis = C.build_basis(pts, np.array([1.0, 0.0, 0.0]), anchor=np.zeros(3), basis_id="fx",
                      pad_ratio=0.15, pad_min_mm=2.4)
height = C.make_height_field(basis, np.random.default_rng(11), target_rms_mm=0.05,
                             n_bands=3, wavelength_min_mm=0.9)
u0, u1 = basis.u_range
v0, v1 = basis.v_range
print("u", u0, u1, "v", v0, v1, "kappa", height.curvature_bound(), flush=True)
pad = min(basis.meta["material_u_range"][0] - u0, u1 - basis.meta["material_u_range"][1],
          basis.meta["material_v_range"][0] - v0, v1 - basis.meta["material_v_range"][1])
root_level = int(np.clip(np.ceil(np.log2(max((u1 - u0), (v1 - v0)) / max(0.25 * pad, 1e-6))), 2, 8))
tree = C._Quadtree(u0, u1, v0, v1, root_level)
budget = 0.01
needed = float(np.sqrt(8.0 * budget / height.curvature_bound()))
root_cell = max((u1 - u0), (v1 - v0)) / (1 << root_level)
start_level = root_level + int(np.ceil(max(np.log2(max(root_cell / needed, 1.0)), 0.0)))
print("root", root_level, "cell", root_cell, "needed", needed, "start", start_level, flush=True)
tree.refine_all_to(start_level)
print("leaves", len(tree.leaves()), flush=True)
max_level = start_level + 12
key = max_level


def cell_errors(block, level):
    span = key - level
    counts, uvs, ws = [], [], []
    for row in range(block.shape[0]):
        pij, tris = tree.cell_triangles(int(block[row, 0]), int(block[row, 1]), level, span)
        u, v = C._cell_uv(tree, level, span, pij)
        p3 = np.stack([u, v, height(u, v)], axis=1)
        tri_pts = p3[tris]
        samp = np.einsum("bk,tkc->tbc", C._ERROR_BARY, tri_pts).reshape(-1, 3)
        counts.append(samp.shape[0])
        uvs.append(samp[:, 0:2])
        ws.append(samp[:, 2])
    uu = np.concatenate([a[:, 0] for a in uvs])
    vv = np.concatenate([a[:, 1] for a in uvs])
    ww = np.concatenate(ws)
    dev = np.abs(height(uu, vv) - ww)
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    return np.maximum.reduceat(dev, starts), dev, starts, counts


for it in range(4):
    changed = False
    for level in sorted({lv for (_, _, lv) in tree.leaves()}):
        block = tree.leaves_at_level(level)
        if block.shape[0] == 0:
            continue
        marked = np.zeros(block.shape[0], dtype=bool)
        for row in range(block.shape[0]):
            if tree.split_count(int(block[row, 0]), int(block[row, 1]), level) > 0:
                marked[row] = True
        todo = block[~marked]
        if todo.shape[0]:
            err, dev, starts, counts = cell_errors(todo, level)
            print("  it", it, "level", level, "cells", todo.shape[0],
                  "maxerr", round(float(err.max()), 6), "med", round(float(np.median(err)), 8),
                  "frac_over", round(float(np.mean(err > budget)), 4), flush=True)
            over = err > budget
            if bool(over.any()):
                idx = np.nonzero(marked)[0]
                marked[idx[over]] = True
        if bool(marked.any()):
            tree.refine_bulk(block[marked])
            changed = True
    print("it", it, "leaves", len(tree.leaves()), "changed", changed, flush=True)
    if not changed:
        break
