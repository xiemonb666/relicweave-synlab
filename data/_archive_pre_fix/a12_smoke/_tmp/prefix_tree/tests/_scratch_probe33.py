"""Scratch probe 33: replicate the refined tree and check every leaf against its own box."""
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
                             n_bands=3, wavelength_min_mm=1.5)
budget = 0.02
u0, u1 = basis.u_range
v0, v1 = basis.v_range
mu0, mu1 = basis.meta["material_u_range"]
mv0, mv1 = basis.meta["material_v_range"]
pad = min(mu0 - u0, u1 - mu1, mv0 - v0, v1 - mv1)
root_level = int(np.clip(np.ceil(np.log2(max((u1 - u0), (v1 - v0)) / max(0.25 * pad, 1e-6))), 2, 8))
tree = C._Quadtree(u0, u1, v0, v1, root_level)
max_over = budget * (1 + 1e-9)
by_wl = height.wavelength_min_mm / C.POINTS_PER_WAVELENGTH
by_k = float(np.sqrt(8.0 * max_over / height.curvature_bound()))
needed = min(by_wl, by_k)
root_cell = max((u1 - u0), (v1 - v0)) / (1 << root_level)
start_level = root_level + int(np.ceil(max(np.log2(max(root_cell / needed, 1.0)), 0.0)))
tree.refine_uniform_to(start_level)
max_level = max(start_level - tree.root_level, 0) + 12
key_level = tree.absolute_level(max_level)
print("root_level", root_level, "start", start_level, "tree.root_level", tree.root_level,
      "max_level", max_level, "key_level", key_level, flush=True)


def span_for(level):
    return tree.key_span(level, key_level)


def box_violations(tag):
    bad = 0
    for (i, j, level) in tree.leaves():
        span = span_for(level)
        pij, tris = tree.cell_triangles(i, j, level, span)
        u, v = C._cell_uv(tree, level, span, pij)
        box = tree.cell_uv(i, j, level)
        inside = (u >= box[0] - 1e-9) & (u <= box[1] + 1e-9) & \
                 (v >= box[2] - 1e-9) & (v <= box[3] + 1e-9)
        if not inside.all():
            bad += 1
            if bad == 1:
                print("  ", tag, "FIRST BAD leaf", (i, j, level), "span", span,
                      "uv", np.round(u, 4).tolist(), np.round(v, 4).tolist(),
                      "box", np.round(box, 4).tolist(), flush=True)
    print(tag, "bad leaves", bad, "of", len(tree.leaves()), flush=True)


box_violations("seed")

# replicate the fixed-point loop
for it in range(8):
    changed = False
    groups: dict[int, list] = {}
    for cell in tree.leaves():
        groups.setdefault(cell[2], []).append(cell)
    for level in sorted(groups):
        block = np.asarray(groups[level], dtype=np.int64).reshape(-1, 3)
        marked = np.zeros(block.shape[0], dtype=bool)
        for row in range(block.shape[0]):
            if tree.split_count(int(block[row, 0]), int(block[row, 1]), level) > 0:
                marked[row] = True
        todo = block[~marked]
        if todo.shape[0]:
            span = span_for(level)
            counts, uvs, ws = [], [], []
            for row in range(todo.shape[0]):
                pij, tris = tree.cell_triangles(int(todo[row, 0]), int(todo[row, 1]), level, span)
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
            err = np.maximum.reduceat(dev, starts)
            over = err > max_over
            print("  it", it, "level", level, "checked", todo.shape[0], "over",
                  int(over.sum()), "maxerr", round(float(err.max()), 6),
                  "box of worst", np.round(tree.cell_uv(
                      int(todo[int(np.argmax(err))][0]), int(todo[int(np.argmax(err))][1]),
                      level), 4).tolist(), flush=True)
            unmarked = np.nonzero(~marked)[0]
            marked[unmarked[over]] = True
        if bool(marked.any()):
            tree.refine_bulk(block[marked])
            changed = True
    print("it", it, "leaves", len(tree.leaves()), "changed", changed, flush=True)
    if not changed:
        break
box_violations("final")

# analytic check on the assembled triangles
top_index: dict[tuple[int, int], int] = {}
vertices: list[tuple[float, float, float]] = []


def top_vertex(level, gi, gj):
    shift = span_for(level)
    key = (int(gi) << shift, int(gj) << shift)
    found = top_index.get(key)
    if found is None:
        u, v = C._cell_uv(tree, level, shift, np.array([[gi, gj]], dtype=np.int64))
        found = len(vertices)
        vertices.append((float(u[0]), float(v[0]), float(height(u, v)[0])))
        top_index[key] = found
    return found


tri_info = []
for (i, j, level) in tree.leaves():
    pij, tris = tree.cell_triangles(i, j, level, span_for(level))
    local = [top_vertex(level, int(p[0]), int(p[1])) for p in pij]
    for tri in tris:
        tri_info.append(((local[tri[0]], local[tri[1]], local[tri[2]]), (i, j, level)))
verts = np.asarray(vertices, dtype=np.float64)
idx = np.asarray([t[0] for t in tri_info], dtype=np.int64)
samp = np.einsum("bk,tkc->tbc", C._ERROR_BARY, verts[idx])
dev = np.abs(height(samp[:, :, 0], samp[:, :, 1]) - samp[:, :, 2])
worst = int(np.argmax(dev.max(axis=1)))
print("worst", float(dev[worst].max()), "cell", tri_info[worst][1],
      "box", np.round(tree.cell_uv(*tri_info[worst][1]), 4).tolist(),
      "tri uv", np.round(verts[idx[worst]][:, 0:2], 4).tolist(), flush=True)
