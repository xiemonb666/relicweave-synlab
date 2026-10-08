"""Scratch probe 22: watertightness of the flat cutter (uniform grid, no refinement)."""
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
flat = C.make_height_field(basis, np.random.default_rng(11), target_rms_mm=0.0)
print("flat", flat.is_flat, flush=True)
mesh, report = C.build_closed_cutter(basis, flat, error_budget_mm=0.01)
print("flat cutter watertight", mesh.is_watertight, "tris", mesh.faces.shape[0],
      "cells", report["cells"], "vol", mesh.volume, flush=True)
print("edge histogram", report["edge_use_histogram"], flush=True)

# small rough field with one band: check watertightness at two levels
for band_min in (3.0, 1.5):
    h = C.make_height_field(basis, np.random.default_rng(5), target_rms_mm=0.05, n_bands=3,
                            wavelength_min_mm=band_min)
    try:
        mesh2, rep2 = C.build_closed_cutter(basis, h, error_budget_mm=0.05)
        print("wl_min", band_min, "watertight", mesh2.is_watertight,
              "tris", mesh2.faces.shape[0], "cells", rep2["cells"],
              "edge hist", rep2["edge_use_histogram"], flush=True)
    except Exception as exc:
        print("wl_min", band_min, "FAILED", type(exc).__name__, exc, flush=True)
