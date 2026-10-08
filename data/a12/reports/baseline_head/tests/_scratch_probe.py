"""Scratch probe 7: full rough event timing on a small box."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.fracture import cut as cut_module  # noqa: E402
from synlab.fracture.cut import build_basis, build_closed_cutter, make_height_field  # noqa: E402
from synlab.fracture.event import run_shared_cut  # noqa: E402
from synlab.schemas.runtime import CutterResult  # noqa: E402
from tests.a12.fracture.fixtures import box_mother  # noqa: E402

EXTENT = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
WL_MIN = float(sys.argv[2]) if len(sys.argv) > 2 else 0.9
BUDGET = float(sys.argv[3]) if len(sys.argv) > 3 else 0.01
mother = box_mother((EXTENT, EXTENT, EXTENT), mother_id=f"box{EXTENT:g}")

basis = build_basis(np.asarray(mother.mesh.vertices), np.array([1.0, 0.0, 0.0]),
                    anchor=np.zeros(3), basis_id="fixture-x",
                    pad_ratio=0.15, pad_min_mm=max(2.0, EXTENT * 0.2))
t0 = time.perf_counter()
height = make_height_field(basis, np.random.default_rng(11), target_rms_mm=0.05,
                           n_bands=3, wavelength_min_mm=WL_MIN)
print("height", round(time.perf_counter() - t0, 4), "wmin", round(height.wavelength_min_mm, 4),
      "kappa", round(height.curvature_bound(), 2), flush=True)
t0 = time.perf_counter()
try:
    _orig_leaves = cut_module._Quadtree.leaves
    _state = {"n": 0}

    def _traced(self):
        out = _orig_leaves(self)
        _state["n"] += 1
        if _state["n"] <= 12:
            _hist: dict = {}
            for _, _, lv in out:
                _hist[lv] = _hist.get(lv, 0) + 1
            print("  leaves#", _state["n"], len(out), dict(sorted(_hist.items())), flush=True)
        return out

    cut_module._Quadtree.leaves = _traced
    mesh, report = build_closed_cutter(basis, height, error_budget_mm=BUDGET)
except Exception as exc:
    print("FAILED", type(exc).__name__, exc, flush=True)
    print("measurements", getattr(exc, "measurements", None), flush=True)
    raise SystemExit(0)
print("cutter sec", round(time.perf_counter() - t0, 3), "tris", mesh.faces.shape[0],
      "cells", report["cells"], "leaf_level", report["leaf_level"],
      "start", report["start_level"], "iters", report["refine_iterations"],
      "realized", round(report["realized_error_mm"], 6), "watertight", mesh.is_watertight,
      flush=True)

cutter = CutterResult(mesh=mesh, basis=basis, h_fn=height.__call__,
                      requested_error_mm=BUDGET, realized_error_mm=report["realized_error_mm"],
                      triangles=int(mesh.faces.shape[0]), meta=dict(report))
t0 = time.perf_counter()
result = run_shared_cut(mother, cutter, event_id="E1", backend="rough_shared_cut")
print("event sec", round(time.perf_counter() - t0, 3), "frags", len(result.fragments),
      "interfaces", len(result.interfaces), flush=True)
print("passed", result.qa.get("passed"), result.qa.get("failures"), flush=True)
for key in ("volume_rel_diff", "overlap_ratio", "gap_p95_mm_max", "normal_angle_p95_deg_max",
            "source_coverage", "ambiguous_area_ratio_max", "faces_total"):
    print("  ", key, result.qa.get(key), flush=True)
for patch in result.interfaces:
    print("  patch", patch.interface_id, round(patch.area_mm2, 4),
          "gap", round(patch.gap_p95_mm, 8), "ang", round(patch.normal_angle_p95_deg, 6),
          "amb", round(patch.ambiguity_area_ratio, 6), flush=True)
for frag in result.fragments:
    print("  frag", frag.fragment_id, round(frag.volume_mm3, 5), "tiny", frag.is_tiny, flush=True)
