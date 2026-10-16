#!/usr/bin/env python
"""Throwaway feasibility probe: can a physically-shaped morphology field be realized?

Question under test: given the frozen ``0.01 mm`` interpolation budget and the ``400_000``
cell budget, what cell size / band area / total curvature can a fracture-morphology height
field afford on a real mother, and does the *realized* error from the quadtree verification
agree with the per-cell refinement measurement (the ``verify`` probe lattice is finer than
the per-cell one, so a field that is only marginally resolved can pass refinement and fail
verification).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.fracture import cut as cut_mod                     # noqa: E402
from synlab.fracture.cut import HeightField, FourierBand, build_basis  # noqa: E402


class ProbeField(HeightField):
    """Fourier roughness + conchoidal dome + radial hackle ridges (analytic, physics-shaped)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def raw(self, u, v):
        u = np.asarray(u, dtype=np.float64)
        v = np.asarray(v, dtype=np.float64)
        out = np.zeros(np.broadcast(u, v).shape, dtype=np.float64)
        for band in list(self.bend) + list(self.bands):
            k = band.k
            out = out + band.amplitude_mm * np.cos(
                k * (band.direction[0] * u + band.direction[1] * v) + band.phase)
        meta = self.meta
        dome_r = float(meta.get("dome_radius_mm", 0.0))
        if dome_r > 0.0:
            cu = u - float(meta["origin_u_mm"])
            cv = v - float(meta["origin_v_mm"])
            out = out + (cu ** 2 + cv ** 2) / (2.0 * dome_r)
        hackle = int(meta.get("hackle_count", 0))
        if hackle > 0:
            du = u - float(meta["origin_u_mm"])
            dv = v - float(meta["origin_v_mm"])
            r = np.hypot(du, dv)
            theta = np.arctan2(dv, du)
            r_m = float(meta["mirror_radius_mm"])
            ramp = np.clip((r - r_m) / max(0.25 * r_m, 1e-6), 0.0, 1.0)
            amp = float(meta["hackle_amplitude_mm"]) * ramp * np.clip(r / max(r_m, 1e-6), 0.0, 3.0)
            out = out + amp * np.cos(hackle * theta + float(meta.get("hackle_phase", 0.0)))
        return out

    def gradient(self, u, v):
        u = np.asarray(u, dtype=np.float64)
        v = np.asarray(v, dtype=np.float64)
        du = np.zeros(np.broadcast(u, v).shape, dtype=np.float64)
        dv = np.zeros_like(du)
        for band in list(self.bend) + list(self.bands):
            k = band.k
            arg = k * (band.direction[0] * u + band.direction[1] * v) + band.phase
            s = -band.amplitude_mm * k * np.sin(arg)
            du = du + s * band.direction[0]
            dv = dv + s * band.direction[1]
        # dome/hackle derivatives are not needed by the refinement (it measures h, not grad)
        return du, dv

    def curvature_bound(self):
        total = 0.0
        for band in list(self.bend) + list(self.bands):
            total += band.amplitude_mm * band.k ** 2
        hackle = int(self.meta.get("hackle_count", 0))
        if hackle > 0:
            r_m = max(float(self.meta["mirror_radius_mm"]), 1e-6)
            total += float(self.meta["hackle_amplitude_mm"]) * (hackle / r_m) ** 2
        return float(total)


def make_field(basis, rng, *, rms, wl, amps_scale=1.0, dome_r=0.0, hackle=0, mirror_mm=1.0,
               hackle_amp=0.0, origin=(0.0, 0.0)):
    bands = []
    for w, a in zip(wl, rms):
        theta = float(rng.uniform(0.0, 2.0 * np.pi))
        phase = float(rng.uniform(0.0, 2.0 * np.pi))
        bands.append(FourierBand(float(a) * amps_scale, float(w),
                                 np.array([np.cos(theta), np.sin(theta)]), phase))
    field = ProbeField(
        basis=basis, bands=bands, bend=[], mean_mm=0.0, target_rms_mm=float(np.sqrt(
            0.5 * sum((b.amplitude_mm ** 2) for b in bands))),
        realized_rms_mm=0.0, wavelength_min_mm=float(min(wl)), max_slope=0.0,
        meta={"origin_u_mm": float(origin[0]), "origin_v_mm": float(origin[1]),
              "mirror_radius_mm": float(mirror_mm), "hackle_count": int(hackle),
              "hackle_amplitude_mm": float(hackle_amp), "hackle_phase": 0.7,
              "dome_radius_mm": float(dome_r),
              "amplitude_max_mm": float(max([b.amplitude_mm for b in bands] + [hackle_amp]))},
    )
    return field


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V13")
    parser.add_argument("--asset", default="")
    parser.add_argument("--amps", default="0.10,0.06,0.02,0.01")
    parser.add_argument("--wls", default="1.5,1.0,0.6,0.35")
    parser.add_argument("--hackle", type=int, default=0)
    parser.add_argument("--hackle-amp", type=float, default=0.0)
    parser.add_argument("--mirror-mm", type=float, default=1.0)
    parser.add_argument("--band-only", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from synlab.fracture.spec import DEFAULT_ERROR_BUDGET_MM
    from synlab.mothers.api import load_mother
    from synlab.storage.store import AssetStore

    demo = REPO_ROOT / "data" / "a12_demo" / "store"
    manifest = json.loads((REPO_ROOT / "data" / "a12_demo" / "demo_manifest.json")
                          .read_text(encoding="utf-8"))
    asset = args.asset or next(e["asset_id"] for e in manifest["entries"]
                               if e["entry_id"] == f"mother:{args.vessel}")
    mother = load_mother(AssetStore(demo), asset)
    mesh = mother.mesh
    print(f"[mother] {args.vessel} faces={len(mesh.faces)} volume={abs(mesh.volume):.1f} "
          f"extent={np.round(mesh.bounds[1] - mesh.bounds[0], 2).tolist()}", flush=True)

    points = np.asarray(mesh.vertices, dtype=np.float64)
    from synlab.fracture.api import _default_basis
    from synlab.fracture.spec import FractureSpec
    basis = _default_basis(mother, np.random.default_rng(0), FractureSpec())
    print(f"[basis] origin={np.round(basis.origin, 3).tolist()} "
          f"n={np.round(basis.normal, 5).tolist()} u={np.round(basis.u_range, 2).tolist()} "
          f"v={np.round(basis.v_range, 2).tolist()} "
          f"material_u={np.round(basis.meta['material_u_range'], 2).tolist()} "
          f"material_v={np.round(basis.meta['material_v_range'], 2).tolist()}", flush=True)

    rng = np.random.default_rng(7)
    amps = [float(x) for x in args.amps.split(",")]
    wls = [float(x) for x in args.wls.split(",")]
    field = make_field(basis, rng, rms=amps, wl=wls, hackle=args.hackle,
                       hackle_amp=args.hackle_amp, mirror_mm=args.mirror_mm)
    t0 = time.time()
    field = cut_mod.attach_material_band(field, mesh)
    t_band = time.time() - t0
    window = field.window
    print(f"[band] {t_band:.2f}s core_area={window.stats.get('flat_cross_section_area_mm2'):.1f} "
          f"window_area={window.as_dict()['window_area_mm2']:.1f} "
          f"halo={window.halo_mm:.3f} margin={window.margin_mm:.3f}", flush=True)
    print(f"[band] realized_rms={field.realized_rms_mm:.5f}mm "
          f"requested_rms={field.target_rms_mm:.5f}mm", flush=True)

    t0 = time.time()
    if args.band_only:
        summary = {"status": "BAND_ONLY", "band_seconds": t_band,
                   "window_area_mm2": window.as_dict()["window_area_mm2"],
                   "core_area_mm2": window.stats.get("flat_cross_section_area_mm2"),
                   "halo_mm": window.halo_mm, "margin_mm": window.margin_mm,
                   "realized_rms_mm": field.realized_rms_mm,
                   "cells_at_budget": 400_000.0 * 0.08 / max(1e-9, sum(
                       b.amplitude_mm * b.k ** 2 for b in field.bands))}
        print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        return 0
    try:
        cutter, report = cut_mod.build_closed_cutter(
            basis, field, error_budget_mm=DEFAULT_ERROR_BUDGET_MM,
            max_cells=400_000, max_triangles=3_000_000)
        dt = time.time() - t0
        print(f"[cutter] OK {dt:.1f}s cells={report.get('cells')} "
              f"triangles={len(cutter.faces)} realized_error={report.get('realized_error_mm')}",
              flush=True)
        summary = {"status": "OK", "seconds": dt, "cells": report.get("cells"),
                   "triangles": int(len(cutter.faces)),
                   "leaf_level": report.get("leaf_level"),
                   "realized_error_mm": report.get("realized_error_mm"),
                   "band_seconds": t_band,
                   "window_area_mm2": window.as_dict()["window_area_mm2"],
                   "core_area_mm2": window.stats.get("flat_cross_section_area_mm2"),
                   "realized_rms_mm": field.realized_rms_mm}
    except BaseException as exc:  # noqa: BLE001
        dt = time.time() - t0
        code = getattr(getattr(exc, "code", None), "value", type(exc).__name__)
        print(f"[cutter] FAILED after {dt:.1f}s code={code} stage={getattr(exc, 'stage', '')}\n"
              f"    {exc}", flush=True)
        summary = {"status": "FAILED", "seconds": dt, "code": str(code),
                   "stage": getattr(exc, "stage", ""), "message": str(exc)[:500],
                   "measurements": {k: (float(v) if isinstance(v, (int, float)) else str(v))
                                    for k, v in (getattr(exc, "measurements", {}) or {}).items()},
                   "band_seconds": t_band}
    text = json.dumps(summary, ensure_ascii=False, indent=1)
    print(text, flush=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if summary["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
