"""Diagnose the implicit field's local curvature / slope budget on a fixture (measured, not guessed)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tests" / "a12" / "fracture"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extent", type=float, default=12.0)
    parser.add_argument("--material", default="M01")
    parser.add_argument("--delta", type=float, default=0.13)
    args = parser.parse_args()

    import fixtures as fx

    from synlab.fracture import morphology as morph
    from synlab.fracture.api import _default_basis
    from synlab.fracture.implicit import field as ifield
    from synlab.fracture.spec import FractureSpec
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    mother = fx.box_mother((args.extent, args.extent, args.extent), mother_id="diag")
    profile = build_material_profile(args.material, default_material_params(args.material),
                                     make_rng(20261001, "diag", "material"))
    basis = _default_basis(mother, make_rng(20261001, "diag", "basis"), FractureSpec())
    prepared = morph.prepare_morphology(mother, material_profile=profile,
                                        rng=make_rng(20261001, "diag", "prep"), basis=basis,
                                        event_id="diag")
    params = prepared["base_params"]
    field, info = ifield.build_implicit_field(
        basis, mother.mesh, params, rng=make_rng(20261001, "diag", "field"),
        cross_section=(prepared["tris_uv"], prepared["core_area_mm2"], prepared["cross_info"]),
        delta_mm=float(args.delta), samples_per_wavelength=5.0, slope_target_p95_deg=18.0)
    env = field.envelope

    step = float(args.delta) / 3.0
    bbox = (env.u0 - 0.5, env.u0 + env.sign_raster.shape[0] * env.step_mm + 0.5,
            env.v0 - 0.5, env.v0 + env.sign_raster.shape[1] * env.step_mm + 0.5)
    gu = np.arange(bbox[0], bbox[1], step)
    gv = np.arange(bbox[2], bbox[3], step)
    GU, GV = np.meshgrid(gu, gv, indexing="ij")
    h = np.asarray(field(GU, GV), dtype=np.float64)
    gy, gx = np.gradient(h, step)
    hxx = np.gradient(gx, step, axis=0)
    hyy = np.gradient(gy, step, axis=1)
    hxy = np.gradient(gx, step, axis=1)
    curv = np.abs(hxx) + 2.0 * np.abs(hxy) + np.abs(hyy)
    grad = np.hypot(gx, gy)
    phi = env.smoothness(GU, GV)
    inside = env.smoothness(GU, GV) > 0.02
    allowed_curv = 8.0 * 0.01 / float(args.delta) ** 2
    i, j = np.unravel_index(int(np.argmax(curv)), curv.shape)
    report = {
        "fixture": f"box{args.extent:g}", "material": args.material, "delta": float(args.delta),
        "curv_max_per_mm": float(curv.max()), "curv_p99": float(np.percentile(curv, 99)),
        "curv_max_where": [float(GU[i, j]), float(GV[i, j])], "phi_there": float(phi[i, j]),
        "curv_max_inside_footprint": float(curv[inside].max()) if bool(inside.any()) else 0.0,
        "curv_allowed_for_budget": float(allowed_curv),
        "slope_max": float(grad.max()),
        "slope_p95": float(np.percentile(grad[inside], 95)) if bool(inside.any()) else 0.0,
        "amplitude_max_mm": float(field.meta.get("amplitude_max_mm", 0.0)),
        "dome_amplitude_mm": float(field.dome_amplitude_mm),
        "dome_radius_mm": float(field.dome_radius_mm),
        "envelope": env.as_dict(),
        "band_limit": info["band_limit"],
        "slope_calibration": {k: info["slope"][k] for k in
                              ("target_p95_deg", "amplitude_scale_applied",
                               "achieved_within_band")},
        "slope_before_deg": info["slope"]["before"]["angle_p95_deg"],
        "slope_after_deg": info["slope"]["after"]["angle_p95_deg"],
        "ring": info["ring"],
        "h_ptp_mm": float(np.ptp(h)),
        "phi_max_inside": float(phi.max()),
        # where does the curvature live?  report the top-5 locations with phi
        "curv_hotspots": [
            [float(GU[k // curv.shape[1], k % curv.shape[1]]),
             float(GV[k // curv.shape[1], k % curv.shape[1]]),
             float(curv.ravel()[k]), float(phi.ravel()[k])]
            for k in np.argsort(curv.ravel())[-5:][::-1]],
    }
    out = REPO_ROOT / "data" / "a12_reports" / "implicit" / "diag_field.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str)[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
