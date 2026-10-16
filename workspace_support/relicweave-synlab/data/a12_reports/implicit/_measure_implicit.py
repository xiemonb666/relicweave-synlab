"""Measure the implicit-sheet backend against the ten hard metrics (checkpointed per section).

Every section is written to its own JSON as soon as it is measured, because the host kills heavy
runs: a later section failing never loses the earlier numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tests" / "a12" / "fracture"))
OUT = REPO_ROOT / "data" / "a12_reports" / "implicit"
MASTER_SEED = 20261001
LINEAGE = "a12_fracture_implicit"


def save(name: str, payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=1, default=str)
    (OUT / f"{name}.json").write_text(text, encoding="utf-8")
    print(f"[saved] {name}.json ({len(text)} bytes)", flush=True)


def build_mother(vessel: str, material: str):
    import json as _json

    from synlab.mothers.api import create_mother, load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    demo_root = REPO_ROOT / "data" / "a12_demo"
    manifest = _json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{vessel}")
    demo = load_mother(AssetStore(demo_root / "store"), str(entry["asset_id"]))
    return create_mother(vessel, material, dict(demo.params),
                         make_rng(MASTER_SEED, LINEAGE, "mothers", vessel, material),
                         mother_id=f"{LINEAGE}_{vessel}_{material}")


def build_material(material: str):
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    return build_material_profile(material, default_material_params(material),
                                 make_rng(MASTER_SEED, LINEAGE, "materials", material))


def band_decomposition(u, v, residual, *, raster_mm: float = 0.05, cutoff_a: float = 1.0,
                       cutoff_b: float = 0.25) -> dict:
    """Banded Ra of a detrended residual: >1 mm, 0.25-1 mm, <0.25 mm (Gaussian band split)."""
    from scipy import ndimage

    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    r = np.asarray(residual, dtype=np.float64)
    if r.size < 64:
        return {"note": "too few samples", "samples": int(r.size)}
    u0, v0 = float(u.min()), float(v.min())
    nu = int(np.ceil((u.max() - u0) / raster_mm)) + 1
    nv = int(np.ceil((v.max() - v0) / raster_mm)) + 1
    nu, nv = min(nu, 2048), min(nv, 2048)
    gi = np.clip(((u - u0) / raster_mm).astype(np.int64), 0, nu - 1)
    gj = np.clip(((v - v0) / raster_mm).astype(np.int64), 0, nv - 1)
    flat = gi * nv + gj
    count = np.bincount(flat, minlength=nu * nv).astype(np.float64)
    total = np.bincount(flat, weights=r, minlength=nu * nv)
    mean = np.where(count > 0, total / np.maximum(count, 1.0), 0.0).reshape(nu, nv)
    filled = np.where(count.reshape(nu, nv) > 0, mean, 0.0)

    def blur(sigma_mm: float) -> np.ndarray:
        sigma_cells = max(sigma_mm / raster_mm, 1.0e-6)
        num = ndimage.gaussian_filter(filled, sigma=sigma_cells, mode="nearest")
        den = ndimage.gaussian_filter((count.reshape(nu, nv) > 0).astype(float),
                                      sigma=sigma_cells, mode="nearest")
        out = np.where(den > 1e-6, num / np.maximum(den, 1e-12), 0.0)
        return out

    low = blur(cutoff_a / 2.0)                      # > 1 mm content
    mid_all = blur(cutoff_b / 2.0)
    mid = mid_all - low                             # 0.25-1 mm content
    high = filled - mid_all                         # < 0.25 mm content
    grid_mask = count.reshape(nu, nv) > 0
    cells = int(grid_mask.sum())
    return {
        "raster_mm": raster_mm, "cells": cells,
        "Ra_gt_1mm": float(np.abs(low[grid_mask]).mean()) if cells else 0.0,
        "Ra_0p25_to_1mm": float(np.abs(mid[grid_mask]).mean()) if cells else 0.0,
        "Ra_lt_0p25mm": float(np.abs(high[grid_mask]).mean()) if cells else 0.0,
        "note": ("the < 0.25 mm band is carried by the discrete surface (mesh chordal residual) "
                 "plus whatever model content survives band-limiting; both are reported"),
    }


def delivered_statistics(result, basis, params, *, n_samples: int = 400_000) -> dict:
    """Everything measurable on the delivered fracture faces (metrics 6 and 7)."""
    from synlab.fracture import surface_features as sf

    fragments = list(result.fragments)
    measurement = sf.measure_interface_surface(fragments, basis, params, n_samples=int(n_samples))
    # residual samples in the same frame, for the band decomposition
    out = {"measurement": measurement}
    triangles = []
    for fragment in fragments:
        origin = np.asarray(fragment.face_origin_kind)
        ids = np.nonzero(origin == 1)[0]
        if ids.size == 0:
            continue
        local = sf.triangle_vertices_local(fragment.mesh, basis, ids)
        triangles.append(local.reshape(-1, 3, 3))
    if triangles:
        soup = np.concatenate(triangles, axis=0)
        rng = np.random.default_rng(20261011)
        samples = sf._sample_triangles(soup, int(n_samples), rng)
        detrend = sf.detrend_plane(samples["u"], samples["v"], samples["w"])
        out["bands"] = band_decomposition(samples["u"], samples["v"], detrend["residual"])
        out["ls_plane_rms_mm"] = float(np.sqrt(np.mean(detrend["residual"] ** 2)))
        out["form_waviness_rms_mm"] = float(detrend["waviness_rms_mm"])
        # slope of the delivered surface vs the mean (cut-plane) normal
        normals = []
        for fragment in fragments:
            origin = np.asarray(fragment.face_origin_kind)
            ids = np.nonzero(origin == 1)[0]
            if ids.size == 0:
                continue
            normals.append(np.asarray(fragment.mesh.face_normals)[ids])
        if normals:
            n = np.concatenate(normals, axis=0)
            cos = np.clip(n @ np.asarray(basis.normal, dtype=np.float64), -1.0, 1.0)
            angle = np.degrees(np.arccos(np.abs(cos)))
            out["delivered_normal_angle_deg"] = {
                "faces": int(angle.size), "p50": float(np.percentile(angle, 50)),
                "p95": float(np.percentile(angle, 95)), "max": float(angle.max())}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vessel", default="V18")
    ap.add_argument("--material", default="M01")
    ap.add_argument("--triangles", type=int, default=420000)
    ap.add_argument("--sections", default="event,delivered,materials,plane")
    ap.add_argument("--materials", default="M01,M04,M07")
    args = ap.parse_args()
    sections = set(args.sections.split(","))
    OUT.mkdir(parents=True, exist_ok=True)
    summary: dict = {"vessel": args.vessel, "material": args.material,
                     "triangle_budget": args.triangles, "master_seed": MASTER_SEED}

    mother = build_mother(args.vessel, args.material)
    profile = build_material(args.material)
    summary["mother"] = {"mother_id": mother.mother_id, "faces": int(len(mother.mesh.faces)),
                         "volume_mm3": float(abs(mother.mesh.volume)),
                         "watertight": bool(mother.mesh.is_watertight),
                         "bounds": np.asarray(mother.mesh.bounds).tolist()}
    save("measure_mother", summary)

    from synlab.fracture.implicit.backend import build_implicit_cutter
    from synlab.seeds import make_rng

    stage = time.time()
    cutter, field, params, report = build_implicit_cutter(
        mother, material_profile=profile, rng=make_rng(MASTER_SEED, LINEAGE, "build"),
        event_id=f"{args.vessel}_{args.material}", error_budget_mm=0.01,
        options={"max_sheet_triangles": int(args.triangles)})
    summary["build"] = {
        "seconds": time.time() - stage, "faces": int(len(cutter.mesh.faces)),
        "top_triangles": int(report["sheet"]["top_triangles"]),
        "delta_mm": float(report["sampling_plan"]["delta_final_mm"]),
        "lambda_requested_mm": float(report["sampling_plan"]["requested_lambda_min_mm"]),
        "lambda_realized_mm": float(report["sampling_plan"]["lambda_min_realized_mm"]),
        "band_limited": bool(report["field"]["band_limit"]["band_limited"]),
        "dropped_bands": report["field"]["band_limit"]["dropped"],
        "realized_error_mm": float(report["realized_error_mm"]),
        "budget_mm": float(report["requested_error_mm"]),
        "topology": report["topology"], "closure": report["closure"],
        "sampling_density": report["sampling_density"],
        "timings": report["timings_seconds"], "peak_memory_mb": float(report["peak_memory_mb"]),
        "slope": {"before_deg": float(report["field"]["slope"]["before"]["angle_p95_deg"]),
                  "after_deg": float(report["field"]["slope"]["after"]["angle_p95_deg"]),
                  "scale": float(report["field"]["slope"]["amplitude_scale_applied"]),
                  "target_deg": float(report["field"]["slope"]["target_p95_deg"]),
                  "achieved_within_band": bool(report["field"]["slope"]["achieved_within_band"]),
                  "curvature_p99_per_mm":
                      float(report["field"]["slope"]["after"]["curvature_p99_per_mm"]),
                  "before_slope_p95": float(report["field"]["slope"]["before"]["slope_p95"]),
                  "after_slope_p95": float(report["field"]["slope"]["after"]["slope_p95"])},
        "envelope": {k: v for k, v in report["field"]["envelope"].items() if k != "construction"},
        "ring": report["field"]["ring"],
        "spectrum": report["field"]["spectrum"],
        "spacing_decision": report["sampling_plan"]["refinement_attempts"],
    }
    save("measure_build", summary)
    if "event" not in sections:
        return 0

    from synlab.fracture.api import audit_fracture
    from synlab.fracture.implicit.assembler import assemble_implicit_event

    stage = time.time()
    result = assemble_implicit_event(mother, cutter, event_id=f"{args.vessel}_{args.material}",
                                    backend="implicit_sheet_cut")
    summary["event"] = {"seconds": time.time() - stage,
                        "fragments": [{"id": f.fragment_id, "volume_mm3": float(f.volume_mm3),
                                       "faces": int(len(f.mesh.faces)),
                                       "watertight": bool(f.mesh.is_watertight),
                                       "winding": bool(f.mesh.is_winding_consistent),
                                       "tiny": bool(f.is_tiny)} for f in result.fragments],
                        "timings": result.meta.get("assembly_timings_seconds")}
    save("measure_event", summary)

    from synlab.fracture import surface_features as sf

    basis = result.meta.get("basis") or cutter.basis
    stage = time.time()
    conjugate = sf.conjugate_profile_consistency(list(result.fragments), result.interfaces, basis)
    gaps = [np.linalg.norm(p.sample_points_a - p.sample_points_b, axis=1)
            for p in result.interfaces if p.sample_points_a.size]
    summary["conjugacy"] = {
        "seconds": time.time() - stage,
        "patches": conjugate["patch_count"],
        "conjugate_gap_p95_mm": conjugate["conjugate_gap_p95_mm"],
        "profile_correlation_min": conjugate["profile_correlation_min"],
        "profile_rms_diff_mm_max": conjugate["profile_rms_diff_mm_max"],
        "gap_p95_mm_max": conjugate["gap_p95_mm_max"],
        "normal_angle_p95_deg_max": conjugate["normal_angle_p95_deg_max"],
        "area_rel_error_max": conjugate["area_rel_error_max"],
        "measured_area_mm2": conjugate["measured_area_mm2"],
        "own_conjugate_point_distance": {
            "p50": float(np.percentile(np.concatenate(gaps), 50)) if gaps else None,
            "p95": float(np.percentile(np.concatenate(gaps), 95)) if gaps else None,
            "max": float(np.concatenate(gaps).max()) if gaps else None} if gaps else None,
    }
    save("measure_conjugacy", summary)

    stage = time.time()
    try:
        audit = audit_fracture(result, mother)
        summary["audit"] = {"seconds": time.time() - stage, "report": audit}
    except Exception as exc:  # noqa: BLE001 - the audit refuses failures on purpose
        summary["audit"] = {"seconds": time.time() - stage,
                            "failed": f"{type(exc).__name__}: {exc}",
                            "measurements": getattr(exc, "measurements", None)}
    save("measure_audit", summary)

    stage = time.time()
    try:
        summary["delivered"] = delivered_statistics(result, basis, params)
    except Exception as exc:  # noqa: BLE001
        summary["delivered"] = {"failed": f"{type(exc).__name__}: {exc}",
                                "traceback": traceback.format_exc()[-1500:]}
    summary["delivered"]["seconds"] = time.time() - stage
    save("measure_delivered", summary)

    if "materials" in sections:
        summary["materials"] = material_matrix(args, cutter, field, params, mother, profile)
        save("measure_materials", summary)

    if "plane" in sections:
        summary["plane_baseline"] = plane_baseline(mother, report, basis)
        save("measure_plane", summary)
    return 0


def cutter_surface_statistics(cutter, field, params) -> dict:
    """Measure the *built* sheet (no boolean): the same surface both halves would carry."""
    from synlab.fracture import surface_features as sf

    envelope = field.envelope
    window = envelope if hasattr(envelope, "is_exactly_one") else None
    stats = sf.measure_cutter_surface(cutter.mesh, cutter.basis, params, window=window,
                                      n_samples=300_000)
    u, v, w = stats.get("u"), stats.get("v"), stats.get("w")
    del u, v, w
    return stats


def material_matrix(args, cutter, field, params, mother, profile) -> dict:
    """Metric 8: three materials on the same cut plane, measured on the built sheet."""
    from synlab.fracture.implicit.backend import build_implicit_cutter
    from synlab.seeds import make_rng

    rows: dict[str, dict] = {}
    for material in str(args.materials).split(","):
        material = material.strip()
        if not material:
            continue
        stage = time.time()
        try:
            if material == args.material:
                built, built_field, built_params = cutter, field, params
            else:
                other_profile = build_material(material)
                built, built_field, built_params, _rep = build_implicit_cutter(
                    mother, material_profile=other_profile,
                    rng=make_rng(MASTER_SEED, LINEAGE, "build", material),
                    event_id=f"{args.vessel}_{material}", error_budget_mm=0.01,
                    options={"max_sheet_triangles": int(args.triangles)})
            stats = cutter_surface_statistics(built, built_field, built_params)
            rows[material] = {
                "seconds": time.time() - stage,
                "requested_rms_mm": float(built_params.requested_rms_mm),
                "correlation_length_mm": float(stats.get("correlation_length_mm", 0.0)),
                "ridge_lines_per_mm": float(stats.get("ridge_lines_per_mm", 0.0)),
                "Ra_mm": float(stats.get("Ra_mm", 0.0)),
                "Rq_mm": float(stats.get("Rq_mm", 0.0)),
                "Rz_mm": float(stats.get("Rz_mm", 0.0)),
                "waviness_rms_mm": float(stats.get("waviness_rms_mm", 0.0)),
                "zones": stats.get("zones", {}),
                "cutter_faces": int(len(built.mesh.faces)),
                "amplitude_scale": float(built.meta.get("precision_amplitude_scale", 1.0)),
            }
            u, v, w = stats.get("u"), stats.get("v"), stats.get("w")
            del u, v, w
        except Exception as exc:  # noqa: BLE001
            rows[material] = {"failed": f"{type(exc).__name__}: {exc}",
                              "traceback": traceback.format_exc()[-1200:]}
    return rows


def plane_baseline(mother, implicit_report, basis) -> dict:
    """Metric 9: the frozen plane backend on the same mother, audited and hash-recorded."""
    from synlab.fracture.api import audit_fracture, make_closed_cutter
    from synlab.fracture.booleans import mesh_hash
    from synlab.fracture.event import run_shared_cut
    from synlab.fracture.spec import BACKEND_PLANE, FractureSpec
    from synlab.seeds import make_rng

    out: dict = {}
    rng = make_rng(MASTER_SEED, LINEAGE, "plane")
    stage = time.time()
    try:
        spec = FractureSpec(backend=BACKEND_PLANE, error_budget_mm=0.01)
        cutter = make_closed_cutter(mother, spec, rng, basis=basis)
        result = run_shared_cut(mother, cutter, event_id="plane_baseline", backend=BACKEND_PLANE)
        out["seconds"] = time.time() - stage
        out["cutter_hash"] = mesh_hash(cutter.mesh)
        out["cutter_faces"] = int(len(cutter.mesh.faces))
        out["cutter_triangles_reported"] = int(cutter.triangles)
        out["realized_error_mm"] = float(cutter.realized_error_mm)
        out["topology"] = {
            "watertight": bool(cutter.mesh.is_watertight),
            "winding": bool(cutter.mesh.is_winding_consistent),
            "volume_mm3": float(abs(cutter.mesh.volume))}
        out["fragments"] = [{"id": f.fragment_id, "volume_mm3": float(f.volume_mm3),
                             "faces": int(len(f.mesh.faces))} for f in result.fragments]
        out["audit"] = audit_fracture(result, mother)
    except Exception as exc:  # noqa: BLE001
        out["failed"] = f"{type(exc).__name__}: {exc}"
        out["traceback"] = traceback.format_exc()[-1500:]
        out["measurements"] = getattr(exc, "measurements", None)
    out["implicit_realized_error_mm"] = float(implicit_report["realized_error_mm"])
    return out


if __name__ == "__main__":
    raise SystemExit(main())
