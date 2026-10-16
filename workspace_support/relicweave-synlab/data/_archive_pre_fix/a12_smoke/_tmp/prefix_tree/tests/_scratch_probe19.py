"""Scratch probe 19: instrument the exact fixed-point loop of build_closed_cutter."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402

pts = np.asarray([[-6, -6, -6], [6, -6, -6], [6, 6, -6], [-6, 6, -6],
                  [-6, -6, 6], [6, -6, 6], [6, 6, 6], [-6, 6, 6]], dtype=np.float64)
basis = C.build_basis(pts, np.array([1.0, 0.0, 0.0]), anchor=np.zeros(3), basis_id="fx",
                      pad_ratio=0.15, pad_min_mm=2.4)
height = C.make_height_field(basis, np.random.default_rng(11), target_rms_mm=0.05,
                             n_bands=3, wavelength_min_mm=0.9)

# Replicate the loop body with explicit printing.
u0, u1 = basis.u_range
v0, v1 = basis.v_range
pad = min(basis.meta["material_u_range"][0] - u0, u1 - basis.meta["material_u_range"][1],
          basis.meta["material_v_range"][0] - v0, v1 - basis.meta["material_v_range"][1])
root_level = int(np.clip(np.ceil(np.log2(max((u1 - u0), (v1 - v0)) / max(0.25 * pad, 1e-6))), 2, 8))
tree = C._Quadtree(u0, u1, v0, v1, root_level)
budget = 0.01
by_wl = height.wavelength_min_mm / C.POINTS_PER_WAVELENGTH
by_k = float(np.sqrt(8.0 * budget / height.curvature_bound()))
needed = min(by_wl, by_k)
root_cell = max((u1 - u0), (v1 - v0)) / (1 << root_level)
start_level = root_level + int(np.ceil(max(np.log2(max(root_cell / needed, 1.0)), 0.0)))
tree.refine_all_to(start_level)
max_level = start_level + 12
key_level = max_level
print("start", start_level, "key", key_level, "leaves", len(tree.leaves()), flush=True)


def span_for(level):
    return tree.key_span(level, key_level)


def cell_errors(block, level):
    span = span_for(level)
    counts, uvs, ws = [], [], []
    for row in range(block.shape[0]):
        pij, tris = tree.cell_triangles(int(block[row, 0]), int(block[row, 1]), level, span)
        u, v = C._cell_uv(tree, level, span, pij)
        p3 = np.stack([u, v, height(u, v)], axis=1)
        samp = np.einsum("bk,tkc->tbc", C._ERROR_BARY, p3[tris]).reshape(-1, 3)
        counts.append(samp.shape[0])
        uvs.append(samp[:, 0:2])
        ws.append(samp[:, 2])
    uu = np.concatenate([a[:, 0] for a in uvs])
    vv = np.concatenate([a[:, 1] for a in uvs])
    ww = np.concatenate(ws)
    dev = np.abs(height(uu, vv) - ww)
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    return np.maximum.reduceat(dev, starts)


for it in range(6):
    changed = False
    levels = sorted({lv for (_, _, lv) in tree.leaves()})
    print("pass", it, "levels", levels, "leaves", len(tree.leaves()), flush=True)
    for level in levels:
        block = tree.leaves_at_level(level)
        marked = np.zeros(block.shape[0], dtype=bool)
        splits = 0
        for row in range(block.shape[0]):
            if tree.split_count(int(block[row, 0]), int(block[row, 1]), level) > 0:
                marked[row] = True
                splits += 1
        todo = block[~marked]
        err = cell_errors(todo, level) if todo.shape[0] else np.zeros(0)
        over = err > budget if err.size else np.zeros(0, dtype=bool)
        unmarked = np.nonzero(~marked)[0]
        marked[unmarked[over]] = True
        print("   level", level, "cells", block.shape[0], "split_marked", splits,
              "checked", int(todo.shape[0]), "over", int(over.sum()),
              "maxerr", round(float(err.max()) if err.size else 0.0, 6),
              "marked", int(marked.sum()), flush=True)
        if bool(marked.any()):
            tree.refine_bulk(block[marked])
            changed = True
    if not changed:
        print("converged at pass", it, flush=True)
        break
print("final leaves", len(tree.leaves()), flush=True)
