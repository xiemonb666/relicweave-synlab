#!/usr/bin/env python
"""Fine-raster curvature census of one morphology field: what actually drives the cell cost."""

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

from synlab.fracture.morphology import build_morphology_field, prepare_morphology  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V18")
    parser.add_argument("--material", default="M01")
    parser.add_argument("--step", type=float, default=0.04)
    parser.add_argument("--budget", type=float, default=0.01)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from synlab.fracture.api import _default_basis                              # noqa: PLC0415
    from synlab.fracture.morphology import _scale_params                        # noqa: PLC0415
    from synlab.fracture.spec import FractureSpec                               # noqa: PLC0415
    from synlab.materials.api import (                                          # noqa: PLC0415
        build_material_profile,
        default_material_params,
    )
    from synlab.mothers.api import create_mother, load_mother                   # noqa: PLC0415
    from synlab.seeds import make_rng                                           # noqa: PLC0415
    from synlab.storage.store import AssetStore                                 # noqa: PLC0415

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
    prepared = prepare_morphology(mother, material_profile=profile, rng=rng, basis=basis,
                                  event_id="diag")
    params = _scale_params(prepared["base_params"], float(args.scale))
    t0 = time.time()
    field = build_morphology_field(basis, mother.mesh, params, rng=rng,
                                   cross_section=(prepared["tris_uv"],
                                                  prepared["core_area_mm2"],
                                                  prepared["cross_info"]))
    print(f"[field] {time.time() - t0:.1f}s", flush=True)
    win = field.window
    step = float(args.step)
    u0, v0 = float(win.u0), float(win.v0)
    nu = int(np.ceil((float(basis.u_range[1]) - float(basis.u_range[0])) / step)) + 1
    nv = int(np.ceil((float(basis.v_range[1]) - float(basis.v_range[0])) / step)) + 1
    uu = u0 + np.arange(nu) * step
    vv = v0 + np.arange(nv) * step
    GU, GV = np.meshgrid(uu, vv, indexing="ij")
    uf = GU.ravel()
    vf = GV.ravel()
    print(f"[grid] {nu}x{nv} = {uf.size} points at step {step}", flush=True)
    t0 = time.time()
    h = field(uf, vf).reshape(GU.shape)
    w = win.value(GU, GV)
    print(f"[sample] {time.time() - t0:.2f}s", flush=True)
    gy, gx = np.gradient(h, step, axis=0), np.gradient(h, step, axis=1)
    curv = np.abs(np.gradient(gx, step, axis=0)) + 2.0 * np.abs(
        np.gradient(gx, step, axis=1)) + np.abs(np.gradient(gy, step, axis=1))
    core = w >= 1.0 - 1e-12
    touch = w > 0.0
    cell = np.sqrt(8.0 * float(args.budget) / np.maximum(curv, 1e-12))
    cells_window = float(np.sum((step / cell[touch]) ** 2)) if bool(touch.any()) else 0.0
    cells_core = float(np.sum((step / cell[core]) ** 2)) if bool(core.any()) else 0.0
    flat = {
        "scale": float(args.scale), "step_mm": step,
        "core_area_mm2": float(core.sum() * step ** 2),
        "touch_area_mm2": float(touch.sum() * step ** 2),
        "curv_p50": float(np.percentile(curv[core], 50)),
        "curv_p95": float(np.percentile(curv[core], 95)),
        "curv_p99": float(np.percentile(curv[core], 99)),
        "curv_max": float(curv[core].max()),
        "cell_median_mm": float(np.median(cell[core])),
        "cell_p05_mm": float(np.percentile(cell[core], 5)),
        "cells_core": cells_core, "cells_window": cells_window,
    }
    # where is the worst curvature?
    idx = np.argsort(-np.where(core, curv, 0.0), axis=None)[:8]
    hotspots = []
    for k in idx:
        i, j = np.unravel_index(int(k), curv.shape)
        du = GU[i, j] - params.origin_uv_mm[0]
        dv = GV[i, j] - params.origin_uv_mm[1]
        hotspots.append({"u": float(GU[i, j]), "v": float(GV[i, j]),
                         "r_from_origin_mm": float(np.hypot(du, dv)),
                         "curvature": float(curv[i, j]),
                         "cell_mm": float(cell[i, j])})
    flat["hotspots"] = hotspots
    print(json.dumps(flat, ensure_ascii=False, indent=1), flush=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(flat, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
