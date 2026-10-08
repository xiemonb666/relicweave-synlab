"""Scratch probe 15: compare cell_errors() with the verification formula for the same cell."""
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
print("domain", u0, u1, "root", root_level, flush=True)
tree = C._Quadtree(u0, u1, v0, v1, root_level)
for level in (0, 1, 2, 3, 4):
    tree.refine_all_to(level)
    key_level = level + 12
    span = tree.key_span(level, key_level)
    cell = np.array([[0, 0, level]], dtype=np.int64)
    pij, tris = tree.cell_triangles(0, 0, level, span)
    u, v = C._cell_uv(tree, level, span, pij)
    p3 = np.stack([u, v, height(u, v)], axis=1)
    devs = []
    for tri in tris:
        samp = C._ERROR_BARY @ p3[tri]
        devs.append(float(np.max(np.abs(samp[:, 2] - height(samp[:, 0], samp[:, 1])))))
    corners = tree.cell_uv(0, 0, level)
    print("level", level, "span", span, "cell box", np.round(corners, 4),
          "max dev", round(max(devs), 8), "uv range",
          round(float(u.min()), 4), round(float(u.max()), 4),
          round(float(v.min()), 4), round(float(v.max()), 4), flush=True)
