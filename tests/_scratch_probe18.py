"""Scratch probe 18: verify the cutter refinement now converges (histogram + timing)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402

orig_leaves = C._Quadtree.leaves
state = {"n": 0}


def traced(self):
    out = orig_leaves(self)
    state["n"] += 1
    if state["n"] <= 30:
        hist: dict[int, int] = {}
        for _, _, lv in out:
            hist[lv] = hist.get(lv, 0) + 1
        print("  leaves#", state["n"], len(out), dict(sorted(hist.items())), flush=True)
    return out


C._Quadtree.leaves = traced

pts = np.asarray([[-6, -6, -6], [6, -6, -6], [6, 6, -6], [-6, 6, -6],
                  [-6, -6, 6], [6, -6, 6], [6, 6, 6], [-6, 6, 6]], dtype=np.float64)
basis = C.build_basis(pts, np.array([1.0, 0.0, 0.0]), anchor=np.zeros(3), basis_id="fx",
                      pad_ratio=0.15, pad_min_mm=2.4)
height = C.make_height_field(basis, np.random.default_rng(11), target_rms_mm=0.05,
                             n_bands=3, wavelength_min_mm=0.9)
t0 = time.perf_counter()
try:
    mesh, report = C.build_closed_cutter(basis, height, error_budget_mm=0.01)
    print("OK sec", round(time.perf_counter() - t0, 2), "tris", mesh.faces.shape[0],
          "cells", report["cells"], "leaf_level", report["leaf_level"],
          "start", report["start_level"], "rule", report["seed_rule"],
          "realized", report["realized_error_mm"], flush=True)
except Exception as exc:
    print("FAILED after", round(time.perf_counter() - t0, 2), ":", type(exc).__name__, exc,
          flush=True)
