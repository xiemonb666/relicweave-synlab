"""Scratch probe 30: minimal reproduction — refine once, then check every assembled triangle."""
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
u0, u1 = basis.u_range
v0, v1 = basis.v_range
tree = C._Quadtree(u0, u1, v0, v1, 5)
tree.refine_all_to(6)                 # uniform level 1 relative to the new root
key_level = 12
leaves = tree.leaves()
print("root_level", tree.root_level, "leaves", len(leaves),
      "levels", sorted({lv for _, _, lv in leaves}), flush=True)
top_index: dict[tuple[int, int], int] = {}
vertices: list[tuple[float, float, float]] = []
owner: dict[tuple[int, int], tuple[int, int, int]] = {}


def top_vertex(level, gi, gj, cell):
    shift = tree.key_span(level, key_level)
    key = (int(gi) << shift, int(gj) << shift)
    found = top_index.get(key)
    if found is None:
        u, v = C._cell_uv(tree, level, shift, np.array([[gi, gj]], dtype=np.int64))
        found = len(vertices)
        vertices.append((float(u[0]), float(v[0]), float(height(u, v)[0])))
        top_index[key] = found
        owner[key] = cell
    return found, key


bad = 0
for (i, j, level) in leaves:
    span = tree.key_span(level, key_level)
    pij, tris = tree.cell_triangles(i, j, level, span)
    box = np.array(tree.cell_uv(i, j, level))
    indices, keys = [], []
    for p in pij:
        idx, key = top_vertex(level, int(p[0]), int(p[1]), (i, j, level))
        indices.append(idx)
        keys.append(key)
    for tri in tris:
        uv = np.asarray([vertices[indices[k]][0:2] for k in tri])
        inside = (uv[:, 0] >= box[0] - 1e-9) & (uv[:, 0] <= box[1] + 1e-9) & \
                 (uv[:, 1] >= box[2] - 1e-9) & (uv[:, 1] <= box[3] + 1e-9)
        if not inside.all():
            bad += 1
            if bad <= 3:
                print("OUT-OF-BOX tri for cell", (i, j, level), "box", np.round(box, 6).tolist(),
                      flush=True)
                print("   uv", np.round(uv, 6).tolist(), flush=True)
                for k in tri:
                    print("     idx", indices[k], "key", keys[k],
                          "owner", owner[keys[k]], flush=True)
print("out-of-box triangles:", bad, "of", len(leaves) * 2, flush=True)
