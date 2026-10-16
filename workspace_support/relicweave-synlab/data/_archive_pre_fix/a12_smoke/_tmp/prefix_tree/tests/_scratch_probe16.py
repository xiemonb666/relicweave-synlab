"""Scratch probe 16: sample h along a cell edge to see the real variation."""
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
print("bands:", [(round(b.amplitude_mm, 5), round(b.wavelength_mm, 5),
                  np.round(b.direction, 4).tolist()) for b in height.bands], flush=True)
print("bend:", [(round(b.amplitude_mm, 6), round(b.wavelength_mm, 4)) for b in height.bend],
      flush=True)
print("mean", height.mean_mm, "rms", height.realized_rms_mm, flush=True)
print("max_slope", height.max_slope, flush=True)
print("sum amp", sum(b.amplitude_mm for b in height.bands), flush=True)

t = np.linspace(-4.2, -2.1, 25)
u = np.full_like(t, 6.3)
print("h(6.3, v):", np.round(height(u, t), 6).tolist(), flush=True)
t2 = np.linspace(6.3, 8.4, 25)
v2 = np.full_like(t2, -3.15)
print("h(u, -3.15):", np.round(height(t2, v2), 6).tolist(), flush=True)
print("h at 3 corners", [round(float(height(np.array([a]), np.array([b]))[0]), 6)
                          for a, b in ((6.3, -4.2), (7.35, -4.2), (8.4, -2.1))], flush=True)
