#!/usr/bin/env python
"""Diagnose the cutter-refinement cost of one morphology field without building the cutter.

Rasterises the realized field over the material band and turns the discrete curvature into the
cell size the ``0.01 mm`` interpolation budget implies, so the predicted cell count can be
compared with what the quadtree actually needs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.fracture import cut as cut_mod                                  # noqa: E402
from synlab.fracture.morphology import (                                    # noqa: E402
    build_morphology_field,
    build_morphology_cutter,
    prepare_morphology,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V18")
    parser.add_argument("--material", default="M01")
    parser.add_argument("--raster", type=float, default=0.05)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--max-cells", type=int, default=400_000)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from synlab.fracture.api import _default_basis                             # noqa: PLC0415
    from synlab.fracture.spec import FractureSpec                              # noqa: PLC0415
    from synlab.materials.api import (                                         # noqa: PLC0415
        build_material_profile,
        default_material_params,
    )
    from synlab.mothers.api import create_mother, load_mother                  # noqa: PLC0415
    from synlab.seeds import make_rng                                          # noqa: PLC0415
    from synlab.storage.store import AssetStore                                # noqa: PLC0415

    demo_root = REPO_ROOT / "data" / "a12_demo"
    manifest = json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{args.vessel}")
    demo = load_mother(AssetStore(demo_root / "store"), str(entry["asset_id"]))
    rng = make_rng(20261001, "diag", "mothers", args.vessel, args.material)
    mother = create_mother(args.vessel, args.material, dict(demo.params), rng,
                           mother_id=f"diag_{args.vessel}_{args.material}")
    profile = build_material_profile(
        args.material, default_material_params(args.material),
        make_rng(20261001, "diag", "materials", args.material))
    rng = make_rng(20261001, "diag", "fracture", args.vessel, args.material)
    basis = _default_basis(mother, rng, FractureSpec())
    t0 = time.time()
    prepared = prepare_morphology(mother, material_profile=profile, rng=rng, basis=basis,
                                  event_id="diag")
    print(f"[prepare] {time.time() - t0:.2f}s core_area={prepared['core_area_mm2']:.1f}", flush=True)
    base = prepared["base_params"]
    print(json.dumps({k: base.as_dict()[k] for k in
                      ("sigma_f_mpa", "mirror_radius_mm", "mist_radius_mm", "hackle_count",
                       "requested_rms_mm", "requested_curvature_per_mm",
                       "curvature_budget_per_mm", "predicted_amplitude_scale",
                       "dome_radius_mm", "dome_amplitude_mm", "pit_count", "pit_radius_mm",
                       "pit_depth_mm", "rib_amplitude_mm", "hackle_amplitude_mm")},
                     ensure_ascii=False, indent=1), flush=True)
    print("bands", np.round(np.asarray(base.bands), 4).tolist(), flush=True)

    t0 = time.time()
    field = build_morphology_field(basis, prepared["basis"].mesh if False else mother.mesh, base,
                                   rng=rng,
                                   cross_section=(prepared["tris_uv"], prepared["core_area_mm2"],
                                                  prepared["cross_info"]))
    print(f"[field] {time.time() - t0:.2f}s window={json.dumps(field.window.as_dict(), default=str)[:400]}",
          flush=True)

    # curvature map over the band core
    win = field.window
    step = float(args.raster)
    u0, v0 = float(win.u0), float(win.v0)
    nu, nv = win.values.shape
    uu = u0 + np.arange(nu) * win.step_mm
    vv = v0 + np.arange(nv) * win.step_mm
    GU, GV = np.meshgrid(uu, vv, indexing="ij")
    t0 = time.time()
    h = field(GU.ravel(), GV.ravel()).reshape(GU.shape)
    w = win.value(GU, GV)
    print(f"[sample] {time.time() - t0:.2f}s on {GU.size} points", flush=True)
    gy, gx = np.gradient(h, win.step_mm, axis=0), np.gradient(h, win.step_mm, axis=1)
    hxx = np.gradient(gx, win.step_mm, axis=0)
    hyy = np.gradient(gy, win.step_mm, axis=1)
    hxy = np.gradient(gx, win.step_mm, axis=1)
    curv = np.abs(hxx) + 2.0 * np.abs(hxy) + np.abs(hyy)
    budget = 0.01
    cell = np.sqrt(8.0 * budget / np.maximum(curv, 1e-12))
    cell = np.clip(cell, win.step_mm, 1.0e3)
    inside = w > 0.0
    cells = float(np.sum((win.step_mm / cell[inside]) ** 2)) if bool(inside.any()) else 0.0
    core_cells = float(np.sum((win.step_mm / cell[w >= 1.0 - 1e-12]) ** 2))
    report = {
        "core_area_mm2": float(np.sum(w >= 1.0 - 1e-12) * win.step_mm ** 2),
        "window_area_mm2": float(np.sum(inside) * win.step_mm ** 2),
        "curvature_p50": float(np.percentile(curv[w >= 1.0 - 1e-12], 50)) if bool(
            np.any(w >= 1.0 - 1e-12)) else 0.0,
        "curvature_p95": float(np.percentile(curv[w >= 1.0 - 1e-12], 95)) if bool(
            np.any(w >= 1.0 - 1e-12)) else 0.0,
        "curvature_max": float(np.max(curv[w >= 1.0 - 1e-12])) if bool(
            np.any(w >= 1.0 - 1e-12)) else 0.0,
        "predicted_cells_window": cells,
        "predicted_cells_core": core_cells,
        "cell_size_p05_mm": float(np.percentile(cell[w >= 1.0 - 1e-12], 5)),
        "cell_size_median_mm": float(np.median(cell[w >= 1.0 - 1e-12])),
        "field_curvature_bound": float(field.curvature_bound()),
        "field_realized_rms_mm": float(field.realized_rms_mm),
        "field_max_slope": float(field.max_slope),
        "window": win.as_dict(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str), flush=True)

    if args.build:
        t0 = time.time()
        try:
            mesh, rep = cut_mod.build_closed_cutter(basis, field, error_budget_mm=budget,
                                                    max_cells=int(args.max_cells))
            print(f"[build] OK {time.time() - t0:.1f}s cells={rep['cells']} "
                  f"triangles={rep['triangles']} err={rep['realized_error_mm']:.3e} "
                  f"leaf_level={rep['leaf_level']}", flush=True)
        except BaseException as exc:  # noqa: BLE001
            print(f"[build] FAILED {time.time() - t0:.1f}s "
                  f"{getattr(getattr(exc, 'code', None), 'value', type(exc).__name__)} "
                  f"@ {getattr(exc, 'stage', '')}: {str(exc)[:300]}", flush=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                                  encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
