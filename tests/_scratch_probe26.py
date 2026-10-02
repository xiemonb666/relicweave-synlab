"""Scratch probe 26: faithful replica of build_closed_cutter, with per-triangle provenance."""
from __future__ import annotations

import sys
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
budget = 0.01
u0, u1 = basis.u_range
v0, v1 = basis.v_range
mu0, mu1 = basis.meta["material_u_range"]
mv0, mv1 = basis.meta["material_v_range"]
pad = min(mu0 - u0, u1 - mu1, mv0 - v0, v1 - mv1)
root_level = int(np.clip(np.ceil(np.log2(max((u1 - u0), (v1 - v0)) / max(0.25 * pad, 1e-6))), 2, 8))
tree = C._Quadtree(u0, u1, v0, v1, root_level)
max_over = budget * (1.0 + 1e-9)
by_wl = height.wavelength_min_mm / C.POINTS_PER_WAVELENGTH
by_k = float(np.sqrt(8.0 * max_over / height.curvature_bound()))
needed = min(by_wl, by_k)
root_cell = max((u1 - u0), (v1 - v0)) / (1 << root_level)
start_level = root_level + int(np.ceil(max(np.log2(max(root_cell / needed, 1.0)), 0.0)))
tree.refine_all_to(start_level)
max_level = (start_level - tree.root_level) + 12
key_level = max_level
print("root", root_level, "start", start_level, "max_level", max_level, "key", key_level,
      "leaves", len(tree.leaves()), flush=True)


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


for it in range(20):
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
            err = cell_errors(todo, level)
            over = err > max_over
            unmarked = np.nonzero(~marked)[0]
            marked[unmarked[over]] = True
        if bool(marked.any()):
            tree.refine_bulk(block[marked])
            changed = True
    if not changed:
        print("converged after", it, "passes; leaves", len(tree.leaves()), flush=True)
        break

# assemble with provenance
top_index: dict[tuple[int, int], int] = {}
vertices: list[tuple[float, float, float]] = []
vert_level: list[int] = []


def top_vertex(level, gi, gj):
    shift = span_for(level)
    key = (int(gi) << shift, int(gj) << shift)
    found = top_index.get(key)
    if found is None:
        u, v = C._cell_uv(tree, level, shift, np.array([[gi, gj]], dtype=np.int64))
        found = len(vertices)
        vertices.append((float(u[0]), float(v[0]), float(height(u, v)[0])))
        vert_level.append(level)
        top_index[key] = found
    return found


tri_info = []
for i, j, level in tree.leaves():
    pij, tris = tree.cell_triangles(i, j, level, span_for(level))
    local = [top_vertex(level, int(p[0]), int(p[1])) for p in pij]
    for tri in tris:
        tri_info.append(((local[tri[0]], local[tri[1]], local[tri[2]]), (i, j, level)))

verts = np.asarray(vertices, dtype=np.float64)
idx = np.asarray([t[0] for t in tri_info], dtype=np.int64)
samp = np.einsum("bk,tkc->tbc", C._ERROR_BARY, verts[idx])
dev = np.abs(height(samp[:, :, 0], samp[:, :, 1]) - samp[:, :, 2])
worst = int(np.argmax(dev.max(axis=1)))
print("worst dev", float(dev[worst].max()), "cell", tri_info[worst][1],
      "vertex levels", [vert_level[v] for v in tri_info[worst][0]], flush=True)
wc = tri_info[worst][1]
print("  cell box", np.round(tree.cell_uv(wc[0], wc[1], wc[2]), 6).tolist(),
      "span", span_for(wc[2]), "key unit",
      tree.cell_size(wc[2])[0] / (1 << span_for(wc[2])), flush=True)
print("  tri uv", np.round(verts[idx[worst]][:, 0:2], 6).tolist(), flush=True)
print("  probe uv", np.round(samp[worst][int(np.argmax(dev[worst]))][:2], 6).tolist(), flush=True)
print("  tri edge lengths",
      np.round([np.linalg.norm(verts[idx[worst][k]] - verts[idx[worst][(k + 1) % 3]])
                for k in range(3)], 8).tolist(), flush=True)
