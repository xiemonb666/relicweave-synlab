"""Stage 2b: the morphology cutter on the real V18 mother, plus the analytic height field.

Two independent measurements, so that neither can flatter the other:

* **delivered**: the full frozen chain (mother -> material -> wall audit -> shared cutter ->
  ``run_shared_cut`` -> A06 audit + ``conjugate_profile_consistency``).  If any gate fails, the
  failure is reported with its own numbers; nothing is relaxed to make it pass.
* **analytic field**: even when the discrete cutter cannot be built, the *shared* surface
  ``w = W(u,v) * h(u,v)`` that both sides would consume is a measurable object.  It is sampled on
  the material-band core in the same ``(u, v, w)`` frame and put through the same
  ``detrend_plane`` / ``amplitude_statistics`` / ``correlation_length`` / ``ridge_density`` chain,
  so the material contrast is quantified independently of the mesh.

Usage::

    .venv\\Scripts\\python.exe tests\\a12\\fracture\\_probe_physical_layer_field.py --vessel V18
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

sys.path.insert(0, str(REPO_ROOT / "tests" / "a12" / "fracture"))

MASTER_SEED = 20261001
LINEAGE_ID = "a12_physical_layer"
OUT_DIR = REPO_ROOT / "data" / "a12_reports" / "physical_layer"


def jsonable(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return f"<{type(value).__name__}>"
    if isinstance(value, dict):
        return {str(k): jsonable(v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v, depth=depth + 1) for v in value[:256]]
    if isinstance(value, np.ndarray):
        flat = value.reshape(-1)
        return {"shape": list(value.shape), "size": int(flat.size),
                "min": float(np.min(flat)) if flat.size and flat.dtype.kind in "fiub" else None,
                "max": float(np.max(flat)) if flat.size and flat.dtype.kind in "fiub" else None}
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def measure_analytic_field(field: Any, params: Any, basis: Any, *, n: int) -> dict[str, Any]:
    """Ra / Rz / correlation length / ridges of the *analytic* shared surface on its core."""
    from synlab.fracture import surface_features as sf
    from synlab.fracture.morphology import flat_cross_section  # noqa: F401  (documented import)

    window = field.window
    core = np.asarray(window.core, dtype=bool)
    ii, jj = np.nonzero(core)
    if ii.size == 0:
        return {"samples": 0, "note": "empty material band core"}
    step = float(window.step_mm)
    u = float(window.u0) + ii * step
    v = float(window.v0) + jj * step
    if u.size > int(n):
        pick = np.linspace(0, u.size - 1, int(n)).astype(np.int64)
        u, v = u[pick], v[pick]
    w = np.asarray(field(u, v), dtype=np.float64)
    detrend = sf.detrend_plane(u, v, w)
    residual = detrend["residual"]
    amplitude = sf.amplitude_statistics(u, v, residual)
    correlation = sf.correlation_length(u, v, residual)
    origin = tuple(params.origin_uv_mm)
    mirror = float(params.mirror_radius_mm)
    mist = float(params.mist_radius_mm)
    radii = [max(mirror * 1.2, 0.5), max(mist, mirror * 1.5), max(3.0 * mirror, 3.0),
             max(6.0 * mirror, 6.0), max(12.0 * mirror, 12.0)]
    ridges = sf.ridge_density(u, v, residual, origin, radii)
    radius = np.hypot(u - origin[0], v - origin[1])
    zones = {}
    for name, selector in (("mirror", radius < mirror),
                           ("mist", (radius >= mirror) & (radius < mist)),
                           ("hackle", radius >= mist)):
        if int(selector.sum()) < 32:
            zones[name] = {"samples": int(selector.sum())}
            continue
        stats = sf.amplitude_statistics(u[selector], v[selector], residual[selector])
        zones[name] = {"samples": int(selector.sum()), "Ra_mm": stats["Ra_mm"],
                       "Rz_mm": stats["Rz_mm"], "Rq_mm": stats["Rq_mm"]}
    tris_uv, core_area, _info = (None, 0.0, None)
    del tris_uv, core_area, _info
    return {
        "samples": int(u.size), "core_bins": int(core.sum()), "step_mm": float(step),
        "surface_area_mm2": float(core.sum() * step * step),
        "waviness_rms_mm": float(detrend["waviness_rms_mm"]),
        "Ra_mm": float(amplitude["Ra_mm"]), "Rq_mm": float(amplitude["Rq_mm"]),
        "Rz_mm": float(amplitude["Rz_mm"]), "Rt_mm": float(amplitude["Rt_mm"]),
        "Rz_cells": int(amplitude["Rz_cells"]),
        "correlation_length_mm": float(correlation["correlation_length_mm"]),
        "correlation_bins": int(correlation["bins"]),
        "ridge_lines_per_mm_mean": float(ridges["lines_per_mm_mean"]),
        "ridge_lines_per_mm_max": float(ridges["lines_per_mm_max"]),
        "residual_rms_mm": float(np.sqrt(np.mean(residual ** 2))),
        "residual_p99_mm": float(np.percentile(np.abs(residual), 99.0)),
        "zones": zones,
        "circle_count": len(ridges["circles"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V18")
    parser.add_argument("--materials", default="M03,M07")
    parser.add_argument("--budget", type=float, default=0.01)
    parser.add_argument("--max-cells", type=int, default=400_000)
    parser.add_argument("--field-samples", type=int, default=400_000)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from synlab.fracture.api import _default_basis
    from synlab.fracture.morphology import (MORPHOLOGY_META_KEY, build_morphology_cutter,
                                            flat_cross_section, material_fracture_inputs,
                                            wall_thickness)
    from synlab.fracture.spec import FractureSpec
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    from _run_physical_layer_matrix import build_mother, error_record

    report: dict[str, Any] = {"stage": "physical_layer_field_probe", "vessel_id": args.vessel,
                              "error_budget_mm": float(args.budget),
                              "max_cells": int(args.max_cells), "cases": {}}
    mother, mother_info = build_mother(args.vessel, args.materials.split(",")[0])
    bounds = np.asarray(mother.mesh.bounds, dtype=np.float64)
    report["mother"] = {"mother_id": mother.mother_id,
                        "faces": int(len(mother.mesh.faces)),
                        "volume_mm3": float(abs(mother.mesh.volume)),
                        "extent_mm": (bounds[1] - bounds[0]).tolist(), **mother_info}
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", args.vessel, "shared_basis")
    basis = _default_basis(mother, rng, FractureSpec())
    wall = wall_thickness(mother, max_probes=320)
    tris_uv, core_area, cross_info = flat_cross_section(basis, mother.mesh)
    report["basis"] = {"basis_id": basis.basis_id,
                       "normal": np.round(np.asarray(basis.normal, dtype=np.float64),
                                          8).tolist(),
                       "origin_mm": np.round(np.asarray(basis.origin, dtype=np.float64),
                                             6).tolist()}
    report["wall"] = wall.as_dict()
    report["cross_section"] = jsonable(cross_info)
    report["core_area_mm2"] = float(core_area)
    print(f"[mother] {mother.mother_id} faces={len(mother.mesh.faces)} "
          f"wall p05={wall.p05_mm:.3f} median={wall.median_mm:.3f} "
          f"cross core={core_area:.1f} mm2", flush=True)

    for material_id in [m.strip() for m in str(args.materials).split(",") if m.strip()]:
        row: dict[str, Any] = {"material_id": material_id}
        profile = build_material_profile(material_id, default_material_params(material_id),
                                         make_rng(MASTER_SEED, LINEAGE_ID, "materials",
                                                  material_id))
        row["fracture_inputs"] = material_fracture_inputs(
            profile, material_id=material_id).as_dict()
        case_rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", args.vessel, material_id)
        # ---------------- delivered (full frozen chain)
        started = time.time()
        try:
            from synlab.fracture.api import audit_fracture
            from synlab.fracture.event import result_basis, run_shared_cut

            cutter, field, params, cutter_report = build_morphology_cutter(
                mother, material_profile=profile, rng=case_rng, basis=basis,
                event_id=f"{LINEAGE_ID}_{args.vessel}_{material_id}",
                error_budget_mm=float(args.budget), max_cells=int(args.max_cells))
            build_seconds = time.time() - started
            result = run_shared_cut(
                mother, cutter, event_id=f"{LINEAGE_ID}_{args.vessel}_{material_id}",
                backend="morphology_shared_cut",
                extra_meta={MORPHOLOGY_META_KEY: params.as_dict(), "material_id": material_id})
            qa = audit_fracture(result, mother)
            from synlab.fracture import surface_features as sf

            conjugate = sf.conjugate_profile_consistency(result.fragments, result.interfaces,
                                                         result_basis(result))
            row["delivered"] = {
                "status": "OK", "build_seconds": round(build_seconds, 2),
                "cutter_triangles": int(cutter.triangles),
                "cutter_cells": int(cutter_report.get("cells", 0)),
                "cutter_watertight": bool(cutter.mesh.is_watertight),
                "realized_error_mm": float(cutter.realized_error_mm),
                "precision_amplitude_scale": float(
                    cutter_report.get("precision_amplitude_scale", 1.0)),
                "qa": jsonable(qa), "conjugate": jsonable(conjugate),
                "interfaces": len(result.interfaces),
                "interface_area_mm2": float(sum(float(p.area_mm2) for p in result.interfaces)),
                "fragments": [{"fragment_id": f.fragment_id, "faces": int(len(f.mesh.faces)),
                               "volume_mm3": float(f.volume_mm3),
                               "watertight": bool(f.mesh.is_watertight)}
                              for f in result.fragments],
            }
            print(f"[{material_id}] delivered OK tris={cutter.triangles} "
                  f"err={cutter.realized_error_mm:.3e} passed={qa.get('passed')} "
                  f"gapP95={qa.get('gap_p95_mm_max')} conj={conjugate['conjugate_gap_p95_mm']:.3e}",
                  flush=True)
        except BaseException as exc:  # noqa: BLE001 - a failure is a measurement
            row["delivered"] = {"status": "FAILED", "seconds": round(time.time() - started, 2),
                                "error": error_record(exc)}
            print(f"[{material_id}] delivered FAILED {row['delivered']['error']['code']} "
                  f"@ {row['delivered']['error']['stage']}: "
                  f"{row['delivered']['error']['message'][:220]}", flush=True)

        # ---------------- analytic shared surface
        try:
            from synlab.fracture.morphology import build_morphology_field, prepare_morphology

            prepared = prepare_morphology(
                mother, material_profile=profile, rng=case_rng, basis=basis,
                event_id=f"{LINEAGE_ID}_{args.vessel}_{material_id}",
                error_budget_mm=float(args.budget), max_cells=int(args.max_cells))
            params = prepared["base_params"]
            field = build_morphology_field(basis, mother.mesh, params, rng=case_rng,
                                           cross_section=(prepared["tris_uv"],
                                                          prepared["core_area_mm2"],
                                                          prepared["cross_info"]))
            surface = measure_analytic_field(field, params, basis,
                                             n=int(args.field_samples))
            row["params"] = params.as_dict()
            row["field"] = {
                "status": "OK",
                "window_area_mm2": float(field.window.as_dict()["window_area_mm2"]),
                "core_area_mm2": float(field.window.as_dict().get("core_area_mm2", 0.0)),
                "relief_rms_mm": float(field.meta.get("relief_rms_mm", 0.0)),
                "relief_amplitude_mm": float(field.meta.get("relief_amplitude_mm", 0.0)),
                "relief_peak_to_valley_mm": float(
                    field.meta.get("relief_peak_to_valley_mm", 0.0)),
                "realized_rms_mm": float(field.realized_rms_mm),
                "max_slope": float(field.max_slope),
                "wavelength_min_mm": float(field.wavelength_min_mm),
                "curvature_bound_per_mm": float(field.curvature_bound()),
                "surface": surface,
            }
            print(f"[{material_id}] analytic Ra={surface['Ra_mm']:.6f} "
                  f"Rz={surface['Rz_mm']:.6f} lc={surface['correlation_length_mm']:.4f} "
                  f"ridge={surface['ridge_lines_per_mm_mean']:.4f}/mm "
                  f"relief_rms={field.meta.get('relief_rms_mm', 0.0):.6f}mm", flush=True)
        except BaseException as exc:  # noqa: BLE001
            row["field"] = {"status": "FAILED", "error": error_record(exc)}
            print(f"[{material_id}] analytic FAILED {type(exc).__name__}: {str(exc)[:220]}",
                  flush=True)
        report["cases"][material_id] = row

    out = Path(args.out) if args.out else (OUT_DIR / f"field_probe_{args.vessel}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(jsonable(report), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[written] {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
