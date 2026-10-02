#!/usr/bin/env python
"""Measure the *modelled* fracture surface on a real mother, without the mesh builder.

Why this probe exists
---------------------
The realized discrete surface cannot currently be produced on any body: the shared-cutter
quadtree emits a wrong triangulation for 8 of its 12 per-cell branches as soon as an edge is
split (see ``docs/a12/fracture_realism.md``), so ``build_closed_cutter`` raises
``CUTTER_NOT_CLOSED`` for every non-planar field.  A flat field never splits an edge, which is
why ``plane_shared_cut`` is exact.

That does not make the morphology *model* unmeasurable.  This probe measures the analytic height
field the model requests, on the real mother, in the same ``(u, v, w)`` cut basis and over the
same material-band footprint the cutter would use.  Everything it reports is therefore the
**request** (what the physics asks the fracture face to look like), measured on the real body —
and it is labelled as such in the output (``surface_kind = "analytic_field_request"``).

What is measured
----------------
* ``Ra`` / ``Rq`` / ``Rz`` / ``Rt`` of the de-trended relief, with the same definitions
  :mod:`synlab.fracture.surface_features` uses;
* correlation length (radial lag where the autocorrelation falls to ``1/e``) and ridge density;
* the **normal-angle distribution** of the modelled surface against the cut-basis normal, from
  the analytic gradient ``n = (-dw/du, -dw/dv, 1) / |...|``;
* the **curvature** of the modelled surface: the turning of the normal over one measurement cell
  (deg/mm), which is the direct analogue of the discrete dihedral measurement;
* the cell demand the frozen interpolation budget implies (``estimate_cell_demand``), so the
  gap between "physically requested" and "realizable inside the resource guard" is a number.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MASTER_SEED = 20261001
LINEAGE_ID = "a12_fracture_realism"
#: measurement cell for the discrete curvature analogue and for Rz
CELL_MM = 2.5


def _jsonable(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return f"<{type(value).__name__}>"
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v, depth=depth + 1) for v in (value if len(value) <= 512 else [])]
    if isinstance(value, np.ndarray):
        flat = value.reshape(-1)
        if flat.size == 0:
            return {"shape": list(value.shape), "empty": True}
        return {"shape": list(value.shape), "size": int(flat.size),
                "min": float(np.min(flat)), "max": float(np.max(flat))}
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "as_dict"):
        return _jsonable(value.as_dict(), depth=depth + 1)
    return str(value)


def build_mother(vessel_id: str, material_id: str, fixture: str = ""):
    import json as _json

    from synlab.seeds import make_rng

    rng = make_rng(MASTER_SEED, LINEAGE_ID, "mothers", vessel_id, material_id)
    if fixture == "box":
        import fixtures as fx

        return fx.box_mother((12.0, 12.0, 12.0), mother_id=f"{LINEAGE_ID}_box12"), {
            "source": "tests/a12/fracture/fixtures.py::box_mother((12,12,12))"}

    from synlab.mothers.api import create_mother, load_mother
    from synlab.storage.store import AssetStore

    demo_root = REPO_ROOT / "data" / "a12_demo"
    manifest = _json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{vessel_id}")
    demo = load_mother(AssetStore(demo_root / "store"), str(entry["asset_id"]))
    mother = create_mother(vessel_id, material_id, dict(demo.params), rng,
                           mother_id=f"{LINEAGE_ID}_{vessel_id}_{material_id}")
    return mother, {"demo_mother_id": demo.mother_id,
                    "source": "synlab.mothers.api.create_mother(demo params, real material)"}


def sample_field_points(field: Any, *, n_samples: int, rng: np.random.Generator
                        ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Area-uniform ``(u, v)`` samples over the *core* of the material-band envelope."""
    window = field.window
    values = np.asarray(window.values, dtype=np.float64)
    step = float(window.step_mm)
    u0, v0 = float(window.u0), float(window.v0)
    core = values >= 1.0 - 1e-12
    ii, jj = np.nonzero(core)
    if ii.size == 0:
        core = values > 0.0
        ii, jj = np.nonzero(core)
    if ii.size == 0:
        raise RuntimeError("the material-band envelope is empty: nothing to sample")
    pick = rng.integers(0, ii.size, size=int(n_samples))
    # stratified jitter inside each chosen core cell
    u = u0 + (ii[pick] + rng.random(int(n_samples))) * step
    v = v0 + (jj[pick] + rng.random(int(n_samples))) * step
    info = {"core_bins": int(ii.size), "cell_area_mm2": step ** 2,
            "core_area_mm2": float(ii.size) * step ** 2,
            "window_shape": list(values.shape), "step_mm": step}
    return u, v, info


def _gradient_by_radius(inside: np.ndarray, radius: np.ndarray, grad_mag: np.ndarray,
                        mirror_mm: float) -> list[dict[str, Any]]:
    """Slope statistics per radial band from the fracture origin.

    The hackle term is ``a * ramp(r) * growth(r) * cos(N * theta)``; ``theta`` is singular at
    ``r = 0``, so ``|dh/dx|`` carries an ``a * N / r`` term that grows without bound at the
    initiation point.  Binning the measured slope by radius is what separates that singularity
    from the ordinary roughness slope.
    """
    edges = [0.0, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, mirror_mm, 2.0 * mirror_mm, 4.0 * mirror_mm,
             float(radius.max()) + 1.0]
    out: list[dict[str, Any]] = []
    for lo, hi in zip(edges, edges[1:]):
        sel = inside & (radius >= lo) & (radius < hi)
        n = int(sel.sum())
        if n < 8:
            continue
        g = grad_mag[sel]
        out.append({"r_lo_mm": float(lo), "r_hi_mm": float(hi), "cells": n,
                    "slope_p50_deg": float(np.degrees(np.arctan(np.percentile(g, 50)))),
                    "slope_p95_deg": float(np.degrees(np.arctan(np.percentile(g, 95)))),
                    "slope_max_deg": float(np.degrees(np.arctan(g.max())))})
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V18")
    parser.add_argument("--material", default="M01")
    parser.add_argument("--fixture", default="")
    parser.add_argument("--samples", type=int, default=400_000)
    parser.add_argument("--budget", type=float, default=0.01)
    parser.add_argument("--max-cells", type=int, default=400_000)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from synlab.fracture import surface_features as sf
    from synlab.fracture.api import _default_basis
    from synlab.fracture.morphology import (
        build_morphology_field, derive_morphology_parameters, estimate_cell_demand,
    )
    from synlab.fracture.spec import FractureSpec
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    out_path = Path(args.out) if args.out else (
        REPO_ROOT / "data" / "a12_reports"
        / f"field_morphology_{args.vessel}_{args.material}.json")
    report: dict[str, Any] = {
        "vessel_id": args.vessel, "material_id": args.material,
        "master_seed": MASTER_SEED, "lineage_id": LINEAGE_ID,
        "surface_kind": "analytic_field_request",
        "surface_kind_note": ("the physics-requested fracture surface, measured analytically on "
                              "the real mother; the realized discrete surface is blocked by the "
                              "shared-cutter triangulation defect (see docs/a12/fracture_realism"
                              ".md), so this is a REQUEST measurement, not a delivered one"),
        "probe": "tests/a12/fracture/_measure_field_morphology.py",
        "error_budget_mm": float(args.budget), "max_cells": int(args.max_cells),
        "rng": np.random.default_rng(MASTER_SEED).integers(0, 2 ** 31 - 1).item(),
    }
    started = time.time()
    rng = np.random.default_rng(int(report["rng"]))

    try:
        mother, mother_info = build_mother(args.vessel, args.material, args.fixture)
        profile = build_material_profile(args.material, default_material_params(args.material),
                                         make_rng(MASTER_SEED, LINEAGE_ID, "materials",
                                                  args.material))
        basis = _default_basis(mother, make_rng(MASTER_SEED, LINEAGE_ID, "fracture",
                                                args.vessel, args.material), FractureSpec())
        bounds = np.asarray(mother.mesh.bounds, dtype=np.float64)
        report["mother"] = {
            "mother_id": mother.mother_id, "faces": int(len(mother.mesh.faces)),
            "watertight": bool(mother.mesh.is_watertight),
            "volume_mm3": float(abs(mother.mesh.volume)),
            "extent_mm": (bounds[1] - bounds[0]).tolist(), **mother_info}
        report["basis"] = {"basis_id": basis.basis_id,
                           "normal": np.round(basis.normal, 8).tolist()}

        # ---- the same measurement the cutter path does, up to (but not including) the mesh build
        from synlab.fracture.morphology import flat_cross_section, material_fracture_inputs, \
            wall_thickness, initiate_origin

        material = material_fracture_inputs(profile)
        wall = wall_thickness(mother, max_probes=320)
        tris_uv, core_area, cross_info = flat_cross_section(basis, mother.mesh)
        mu = basis.meta.get("material_u_range", basis.u_range)
        mv = basis.meta.get("material_v_range", basis.v_range)
        ex, ey = float(mu[1] - mu[0]), float(mv[1] - mv[0])
        origin = initiate_origin(tris_uv, wall.p05_mm)
        params = derive_morphology_parameters(
            material=material, wall=wall, origin_uv=origin, tris_uv=tris_uv,
            core_area_mm2=core_area, window_area_mm2=float(core_area * 2.2 + 500.0),
            extent_mm=(ex, ey), rng=rng,
            vessel_id=str(getattr(mother, "vessel_id", "")),
            mother_id=str(getattr(mother, "mother_id", "")), event_id="field_probe",
            error_budget_mm=float(args.budget), max_cells=int(args.max_cells),
            origin_world_mm=basis.to_world(np.array([[origin[0], origin[1], 0.0]]))[0])
        report["params"] = _jsonable(params.as_dict())
        report["cross_section"] = _jsonable(cross_info)
        report["wall"] = _jsonable(wall.as_dict())
        print(f"[params] wall_p05={wall.p05_mm:.3f} sigma_f={params.sigma_f_mpa:.1f} "
              f"r_mirror={params.mirror_radius_mm:.3f} N_hackle={params.hackle_count} "
              f"sigma_r0={params.requested_rms_mm:.4f} lc={params.correlation_length_mm:.3f} "
              f"pits={params.pit_count}", flush=True)

        field = build_morphology_field(basis, mother.mesh, params, rng=rng,
                                       cross_section=(tris_uv, core_area, cross_info))
        report["field"] = {
            "wavelength_min_mm": float(field.wavelength_min_mm),
            "target_rms_mm": float(field.target_rms_mm),
            "realized_rms_mm": float(field.realized_rms_mm),
            "relief_amplitude_mm": float(field.meta.get("relief_amplitude_mm", 0.0)),
            "relief_rms_mm": float(field.meta.get("relief_rms_mm", 0.0)),
            "relief_peak_to_valley_mm": float(field.meta.get("relief_peak_to_valley_mm", 0.0)),
            "max_slope": float(field.max_slope),
            "curvature_bound_per_mm": float(field.curvature_bound()),
            "curvature_requested_per_mm": float(params.requested_curvature_per_mm),
            "curvature_budget_per_mm": float(params.curvature_budget_per_mm),
            "predicted_amplitude_scale": float(params.predicted_amplitude_scale),
            "window": _jsonable(field.window.as_dict()),
            "components": field.as_dict().get("components"),
        }
        demand = estimate_cell_demand(field, budget_mm=float(args.budget))
        report["cell_demand"] = _jsonable(demand)
        report["cell_demand"]["fits_frozen_cell_budget"] = bool(
            float(demand.get("predicted_cells", 0.0)) <= float(args.max_cells))
        print(f"[field] wl_min={field.wavelength_min_mm:.4f} realized_rms={field.realized_rms_mm:.4f} "
              f"max_slope={field.max_slope:.4f} curv_bound={field.curvature_bound():.3f}/mm "
              f"predicted_cells={demand.get('predicted_cells')}", flush=True)

        # ---- measure the modelled surface
        u, v, sinfo = sample_field_points(field, n_samples=int(args.samples), rng=rng)
        w = np.asarray(field(u, v), dtype=np.float64)
        detrend = sf.detrend_plane(u, v, w)
        residual = detrend["residual"]
        amplitude = sf.amplitude_statistics(u, v, residual, cell_mm=CELL_MM)
        correlation = sf.correlation_length(u, v, residual, step_mm=sf.BIN_STEP_MM)
        radii = [max(params.mirror_radius_mm * f, 0.5) for f in (1.2, 1.8, 3.0, 6.0, 12.0)]
        ridges = sf.ridge_density(u, v, residual, params.origin_uv_mm, radii,
                                  step_mm=sf.BIN_STEP_MM)

        du, dv = field.gradient(u, v)
        normals = np.stack([-du, -dv, np.ones_like(du)], axis=1)
        normals /= np.linalg.norm(normals, axis=1)[:, None]
        # NOTE: the field is sampled in the cut basis, so its gradient is already expressed in the
        # local (u, v, w) frame; the reference direction is therefore the local +w axis (0, 0, 1),
        # NOT the world-space basis normal (mixing the two frames produced meaningless angles).
        axis_n = np.array([0.0, 0.0, 1.0])
        angles_analytic = np.degrees(np.arccos(np.clip(np.abs(normals @ axis_n), 0.0, 1.0)))

        # roughness only: the conchoidal bow (dome) removed, i.e. exactly what a "Ra/Rz" number is
        # supposed to describe.  Taken from the field's own relief accessor so the definition is
        # the model's, not this probe's.
        relief = np.asarray(field._relief(u, v), dtype=np.float64)
        relief_detrend = sf.detrend_plane(u, v, relief)
        relief_amp = sf.amplitude_statistics(u, v, relief_detrend["residual"], cell_mm=CELL_MM)
        relief_corr = sf.correlation_length(u, v, relief_detrend["residual"],
                                            step_mm=sf.BIN_STEP_MM)

        # discrete curvature: principal curvatures of the modelled surface on a regular grid, i.e.
        # the eigenvalues of the shape operator, in 1/mm.  ``requested_curvature_per_mm`` is the
        # area-weighted curvature the model asked for, so the two are directly comparable.
        step = 0.25
        gu = np.arange(float(u.min()), float(u.max()) + 0.5 * step, step)
        gv = np.arange(float(v.min()), float(v.max()) + 0.5 * step, step)
        GU, GV = np.meshgrid(gu, gv, indexing="ij")
        W = np.asarray(field(GU.ravel(), GV.ravel()), dtype=np.float64).reshape(GU.shape)
        inside = np.asarray(field.window.is_exactly_one(GU, GV), dtype=bool)
        # erode by two cells: the finite-difference stencil reaches one cell out, and the band
        # envelope decays to zero across the halo, so an un-eroded mask measures the ENVELOPE's
        # slope (measured: 89.999 deg) instead of the fracture surface's
        for _ in range(2):
            inside[1:, :] &= inside[:-1, :]
            inside[:-1, :] &= inside[1:, :]
            inside[:, 1:] &= inside[:, :-1]
            inside[:, :-1] &= inside[:, 1:]
        wu, wv = np.gradient(W, step, axis=0), np.gradient(W, step, axis=1)
        wuu = np.gradient(wu, step, axis=0)
        wuv = np.gradient(wu, step, axis=1)
        wvv = np.gradient(wv, step, axis=1)
        denom = (1.0 + wu ** 2 + wv ** 2) ** 1.5
        mean_curv = ((1.0 + wv ** 2) * wuu - 2.0 * wu * wv * wuv
                     + (1.0 + wu ** 2) * wvv) / np.maximum(denom, 1e-12)
        gauss = (wuu * wvv - wuv ** 2) / np.maximum(denom, 1e-12) * 1.0
        disc = np.maximum(mean_curv ** 2 - gauss, 0.0)
        k_max = np.abs(mean_curv / 2.0 + np.sqrt(disc))
        k_min = np.abs(mean_curv / 2.0 - np.sqrt(disc))
        k_abs = np.maximum(k_max, k_min)
        inside_core = inside & np.isfinite(k_abs)
        # Normals from the SAME grid finite differences as the curvature.  The analytic
        # ``field.gradient`` is exact for the smooth Fourier/hackle/rib terms but the band
        # envelope and the pit set are bucketed tables, so their analytic derivative carries
        # step discontinuities (measured: |grad| up to ~2e5, i.e. 89.9997 deg).  A finite
        # difference at the measurement cell size is what a realized surface would actually
        # carry, and it is the number quoted below.
        nrm = np.stack([-wu, -wv, np.ones_like(wu)], axis=-1)
        nrm /= np.linalg.norm(nrm, axis=-1)[..., None]
        cos_grid = np.clip(np.abs(nrm @ axis_n), 0.0, 1.0)
        angles_grid = np.degrees(np.arccos(cos_grid))
        if bool(inside_core.any()):
            angles = angles_grid[inside_core]
        if bool(inside_core.any()):
            kk = k_abs[inside_core]
            curvature = {
                "grid_step_mm": step,
                "grid_inside_cells": int(inside_core.sum()),
                "k_abs_p50_per_mm": float(np.percentile(kk, 50)),
                "k_abs_p95_per_mm": float(np.percentile(kk, 95)),
                "k_abs_p99_per_mm": float(np.percentile(kk, 99)),
                "k_abs_max_per_mm": float(kk.max()),
                "turning_p95_deg_per_mm": float(np.degrees(np.percentile(kk, 95))),
                "turning_max_deg_per_mm": float(np.degrees(kk.max())),
                "requested_curvature_per_mm": float(params.requested_curvature_per_mm),
                "curvature_budget_per_mm": float(params.curvature_budget_per_mm),
            }
        else:
            curvature = {"grid_step_mm": step, "grid_inside_cells": 0,
                         "note": "no grid node fell inside the band envelope"}

        zones = {}
        radius = np.hypot(u - params.origin_uv_mm[0], v - params.origin_uv_mm[1])
        for name, sel in (("mirror", radius < params.mirror_radius_mm),
                          ("mist", (radius >= params.mirror_radius_mm)
                           & (radius < params.mist_radius_mm)),
                          ("hackle", radius >= params.mist_radius_mm)):
            if int(sel.sum()) < 32:
                zones[name] = {"samples": int(sel.sum())}
                continue
            st = sf.amplitude_statistics(u[sel], v[sel], residual[sel], cell_mm=CELL_MM)
            zones[name] = {"samples": int(sel.sum()), **{k: st[k] for k in
                                                         ("Ra_mm", "Rq_mm", "Rz_mm", "Rt_mm")}}

        report["sampling"] = sinfo
        report["modelled_surface"] = {
            "samples": int(u.size),
            "waviness_rms_mm": float(detrend["waviness_rms_mm"]),
            "roughness": _jsonable(amplitude),
            "Ra_mm": float(amplitude["Ra_mm"]), "Rq_mm": float(amplitude["Rq_mm"]),
            "Rz_mm": float(amplitude["Rz_mm"]), "Rt_mm": float(amplitude["Rt_mm"]),
            "correlation": _jsonable(correlation),
            "correlation_length_mm": float(correlation["correlation_length_mm"]),
            "ridges": _jsonable(ridges),
            "ridge_lines_per_mm": float(ridges["lines_per_mm_mean"]),
            "normals": {
                "source": "grid finite differences at 0.25 mm inside the band core",
                "grid_inside_cells": int(inside_core.sum()) if bool(inside_core.any()) else 0,
                "angle_mean_deg": float(np.mean(angles)) if angles.size else None,
                "angle_p50_deg": float(np.percentile(angles, 50)) if angles.size else None,
                "angle_p95_deg": float(np.percentile(angles, 95)) if angles.size else None,
                "angle_p99_deg": float(np.percentile(angles, 99)) if angles.size else None,
                "angle_max_deg": float(np.max(angles)) if angles.size else None,
                "frac_gt_0p5deg": float(np.mean(angles > 0.5)) if angles.size else None,
                "frac_gt_2deg": float(np.mean(angles > 2.0)) if angles.size else None,
                "analytic_gradient_note": ("field.gradient() at the random samples is reported "
                                           "separately because the bucketed envelope/pit tables "
                                           "make its derivative discontinuous"),
                "analytic_angle_p95_deg": float(np.percentile(angles_analytic, 95)),
                "analytic_angle_max_deg": float(np.max(angles_analytic)),
            },
            "roughness_only": {
                "note": "conchoidal bow removed via the field's own relief accessor",
                "Ra_mm": float(relief_amp["Ra_mm"]),
                "Rq_mm": float(relief_amp["Rq_mm"]),
                "Rz_mm": float(relief_amp["Rz_mm"]),
                "Rt_mm": float(relief_amp["Rt_mm"]),
                "correlation_length_mm": float(relief_corr["correlation_length_mm"]),
                "waviness_rms_mm": float(relief_detrend["waviness_rms_mm"]),
                "roughness": _jsonable(relief_amp),
                "correlation": _jsonable(relief_corr),
            },
            "gradient": {
                "slope_p50_deg": float(np.degrees(np.arctan(np.percentile(
                    np.hypot(du, dv), 50)))),
                "slope_p95_deg": float(np.degrees(np.arctan(np.percentile(
                    np.hypot(du, dv), 95)))),
                "slope_max_deg": float(np.degrees(np.arctan(np.max(np.hypot(du, dv))))),
            },
            "curvature": curvature,
            "gradient_by_radius": _gradient_by_radius(
                inside_core, np.hypot(GU - float(params.origin_uv_mm[0]),
                                      GV - float(params.origin_uv_mm[1])),
                np.hypot(wu, wv), float(params.mirror_radius_mm)),
            "zones": zones,
        }
        ms = report["modelled_surface"]
        ro = ms["roughness_only"]
        print(f"[surface] form+roughness Ra={ms['Ra_mm']:.5f} Rz={ms['Rz_mm']:.5f} "
              f"Rt={ms['Rt_mm']:.5f} lc={ms['correlation_length_mm']:.4f} "
              f"ridges={ms['ridge_lines_per_mm']:.4f}/mm", flush=True)
        print(f"[surface] roughness-only Ra={ro['Ra_mm']:.5f} Rz={ro['Rz_mm']:.5f} "
              f"Rt={ro['Rt_mm']:.5f} lc={ro['correlation_length_mm']:.4f}", flush=True)
        print(f"[surface] normals(grid) p50={ms['normals']['angle_p50_deg']:.3f} "
              f"p95={ms['normals']['angle_p95_deg']:.3f} "
              f"max={ms['normals']['angle_max_deg']:.3f} deg  "
              f"k_p95={ms['curvature'].get('k_abs_p95_per_mm')} /mm", flush=True)
    except BaseException as exc:  # noqa: BLE001 - a failure is a measurement
        report["status"] = "FAILED"
        report["error"] = _jsonable({
            "code": getattr(getattr(exc, "code", None), "value", type(exc).__name__),
            "stage": getattr(exc, "stage", ""), "message": str(exc)[:600],
            "measurements": getattr(exc, "measurements", None),
            "traceback_tail": traceback.format_exc()[-1500:]})
        print(f"[FAILED] {report['error']['code']} {report['error']['message'][:300]}", flush=True)

    report.setdefault("status", "OK")
    report["duration_s"] = round(time.time() - started, 3)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[written] {out_path}", flush=True)
    return 0 if report["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
