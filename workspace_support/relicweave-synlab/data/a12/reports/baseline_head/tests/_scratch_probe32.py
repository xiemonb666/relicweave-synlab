"""Scratch probe 32: inspect the worst assembled triangle's cell directly."""
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
u0, u1 = basis.u_range
v0, v1 = basis.v_range
tree = C._Quadtree(u0, u1, v0, v1, 5)
tree.refine_uniform_to(6)
key_level = tree.absolute_level(0) + 12
print("root_level", tree.root_level, "side", tree.side, "hx", tree.hx, "key", key_level,
      flush=True)
for level in (0, 1, 2):
    span = tree.key_span(level, key_level)
    pij, tris = tree.cell_triangles(0, 0, level, span)
    u, v = C._cell_uv(tree, level, span, pij)
    print("level", level, "span", span, "cell", tree.cell_size(level),
          "uv range", round(float(u.min()), 4), round(float(u.max()), 4),
          "box", np.round(tree.cell_uv(0, 0, level), 4).tolist(), flush=True)
print("leaves:", sorted({lv for _, _, lv in tree.leaves()}), flush=True)
# the reported worst triangle spans u 0.525..8.4 -> which cell can produce that?
for (i, j, level) in sorted(tree.leaves())[:6]:
    span = tree.key_span(level, key_level)
    pij, tris = tree.cell_triangles(i, j, level, span)
    u, v = C._cell_uv(tree, level, span, pij)
    print("  leaf", (i, j, level), "span", span, "uv u", round(float(u.min()), 4),
          round(float(u.max()), 4), "box", np.round(tree.cell_uv(i, j, level), 4).tolist(),
          flush=True)
