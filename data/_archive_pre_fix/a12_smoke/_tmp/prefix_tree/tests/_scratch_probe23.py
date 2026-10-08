"""Scratch probe 23: is the top surface (unrefined) edge-manifold?"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402

pts = np.asarray([[-6, -6, -6], [6, -6, -6], [6, 6, -6], [-6, 6, -6],
                  [-6, -6, 6], [6, -6, 6], [6, 6, 6], [-6, 6, 6]], dtype=np.float64)
basis = C.build_basis(pts, np.array([1.0, 0.0, 0.0]), anchor=np.zeros(3), basis_id="fx",
                      pad_ratio=0.15, pad_min_mm=2.4)
flat = C.make_height_field(basis, np.random.default_rng(11), target_rms_mm=0.0)
u0, u1 = basis.u_range
v0, v1 = basis.v_range
pad = min(basis.meta["material_u_range"][0] - u0, u1 - basis.meta["material_u_range"][1],
          basis.meta["material_v_range"][0] - v0, v1 - basis.meta["material_v_range"][1])
root_level = int(np.clip(np.ceil(np.log2(max((u1 - u0), (v1 - v0)) / max(0.25 * pad, 1e-6))), 2, 8))
tree = C._Quadtree(u0, u1, v0, v1, root_level)
print("root", root_level, "side", tree.side, "cell", tree.cell_size(0), flush=True)
leaves = tree.leaves()
key_level = root_level + 12
top_index: dict[tuple[int, int], int] = {}


def top_vertex(level, gi, gj):
    found = top_index.get((gi, gj))
    if found is None:
        found = len(top_index)
        top_index[(gi, gj)] = found
    return found


faces = []
for i, j, level in leaves:
    span = tree.key_span(level, key_level)
    pij, tris = tree.cell_triangles(i, j, level, span)
    local = [top_vertex(level, int(p[0]), int(p[1])) for p in pij]
    for tri in tris:
        faces.append((local[tri[0]], local[tri[1]], local[tri[2]]))
counter: Counter = Counter()
for tri in faces:
    for k in range(3):
        a, b = tri[k], tri[(k + 1) % 3]
        counter[(min(a, b), max(a, b))] += 1
hist = Counter(counter.values())
print("top faces", len(faces), "vertices", len(top_index), "edge use hist", dict(hist),
      flush=True)
print("sample bad edges", [e for e, n in counter.items() if n != 2][:5], flush=True)
