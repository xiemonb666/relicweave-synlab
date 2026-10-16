"""Scratch probe 12: verify one cell's interpolant against the analytic height field."""
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
pad = min(basis.meta["material_u_range"][0] - u0, u1 - basis.meta["material_u_range"][1],
          basis.meta["material_v_range"][0] - v0, v1 - basis.meta["material_v_range"][1])
root_level = int(np.clip(np.ceil(np.log2(max((u1 - u0), (v1 - v0)) / max(0.25 * pad, 1e-6))), 2, 8))
tree = C._Quadtree(u0, u1, v0, v1, root_level)
budget = 0.01
needed = float(np.sqrt(8.0 * budget / height.curvature_bound()))
root_cell = max((u1 - u0), (v1 - v0)) / (1 << root_level)
start_level = root_level + int(np.ceil(max(np.log2(max(root_cell / needed, 1.0)), 0.0)))
tree.refine_all_to(start_level)
key_level = start_level + 12
span = tree.key_span(3, key_level)
print("start", start_level, "key", key_level, "span(3)", span, "cell", tree.cell_size(3),
      flush=True)

i, j, level = 7, 2, 3
pij, tris = tree.cell_triangles(i, j, level, span)
u, v = C._cell_uv(tree, level, span, pij)
print("pij", pij.tolist(), flush=True)
print("u", np.round(u, 6).tolist(), flush=True)
print("v", np.round(v, 6).tolist(), flush=True)
print("exact h", np.round(height(u, v), 8).tolist(), flush=True)
print("cell_uv() box", tree.cell_uv(i, j, level), flush=True)
for tri in tris:
    a3 = np.array([u[tri[0]], v[tri[0]], height(u[tri[0]], v[tri[0]])])
    b3 = np.array([u[tri[1]], v[tri[1]], height(u[tri[1]], v[tri[1]])])
    c3 = np.array([u[tri[2]], v[tri[2]], height(u[tri[2]], v[tri[2]])])
    samp = C._ERROR_BARY @ np.stack([a3, b3, c3], axis=0)
    exact = height(samp[:, 0], samp[:, 1])
    dev = np.abs(samp[:, 2] - exact)
    print("tri", tri, "max dev", round(float(dev.max()), 8),
          "at uv", np.round(samp[int(np.argmax(dev))][:2], 4), flush=True)
