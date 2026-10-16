"""Scratch probe 14: instrumented build_closed_cutter loop (module patch, no source edit)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402

orig_leaves_at_level = C._Quadtree.leaves_at_level


def traced(self, level):
    out = orig_leaves_at_level(self, level)
    return out


C._Quadtree.leaves_at_level = traced

pts = np.asarray([[-6, -6, -6], [6, -6, -6], [6, 6, -6], [-6, 6, -6],
                  [-6, -6, 6], [6, -6, 6], [6, 6, 6], [-6, 6, 6]], dtype=np.float64)
basis = C.build_basis(pts, np.array([1.0, 0.0, 0.0]), anchor=np.zeros(3), basis_id="fx",
                      pad_ratio=0.15, pad_min_mm=2.4)
height = C.make_height_field(basis, np.random.default_rng(11), target_rms_mm=0.05,
                             n_bands=3, wavelength_min_mm=0.9)

# monkeypatch leaves() to log the level histogram each call from build_closed_cutter
orig_leaves = C._Quadtree.leaves
calls = {"n": 0}


def traced_leaves(self):
    out = orig_leaves(self)
    calls["n"] += 1
    hist: dict[int, int] = {}
    for _, _, lv in out:
        hist[lv] = hist.get(lv, 0) + 1
    if calls["n"] <= 40:
        print("  leaves() call", calls["n"], "n", len(out),
              "hist", dict(sorted(hist.items())), flush=True)
    return out


C._Quadtree.leaves = traced_leaves
try:
    mesh, report = C.build_closed_cutter(basis, height, error_budget_mm=0.01)
    print("OK", report["cells"], report["leaf_level"], report["start_level"], flush=True)
except Exception as exc:
    print("FAILED:", type(exc).__name__, exc, flush=True)
