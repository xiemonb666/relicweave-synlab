#!/usr/bin/env python
"""Run one real (vessel x material) fracture pair: plane baseline + morphology event.

Every number this writes is measured on the real artifacts:

* the mother is built through ``synlab.mothers.api.create_mother`` with the demo vessel's own
  frozen parameters and the requested material, so the geometry is the real vessel and the
  material is the real profile;
* the material profile comes from ``synlab.materials.api.build_material_profile``;
* the wall thickness comes from the frozen mother audit;
* both fracture events go through the frozen shared-cutter path
  (``synlab.fracture.cut.build_closed_cutter`` + ``synlab.fracture.event.run_shared_cut``);
* roughness / correlation length / ridge density are measured on the realized cutter surface and
  on the interface faces of the produced fragments;
* conjugacy is measured from the interface patches the event itself built.

Usage:

```powershell
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_run_morphology_event.py `
    --vessel V18 --material M01 --out data\\a12_reports\\morph_V18_M01.json
```
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


def _jsonable(value: Any, *, depth: int = 0, max_array: int = 32) -> Any:
    if depth > 6:
        return f"<{type(value).__name__}>"
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth=depth + 1, max_array=max_array)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > 512:
            return {"length": len(value),
                    "head": [_jsonable(v, depth=depth + 1, max_array=max_array)
                             for v in value[:8]]}
        return [_jsonable(v, depth=depth + 1, max_array=max_array) for v in value]
    if isinstance(value, np.ndarray):
        flat = value.reshape(-1)
        if flat.size == 0:
            return {"shape": list(value.shape), "empty": True}
        if flat.size > max_array:
            return {"shape": list(value.shape), "size": int(flat.size),
                    "min": float(np.min(flat)) if flat.dtype.kind in "fiub" else None,
                    "max": float(np.max(flat)) if flat.dtype.kind in "fiub" else None}
        return [_jsonable(v, depth=depth + 1, max_array=max_array) for v in flat.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "as_dict"):
        return _jsonable(value.as_dict(), depth=depth + 1, max_array=max_array)
    return str(value)


def build_mother(vessel_id: str, material_id: str) -> tuple[Any, dict[str, Any]]:
    """A real mother of the demo vessel's own geometry, carrying the requested material."""
    import json as _json

    from synlab.mothers.api import create_mother, load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    demo_root = REPO_ROOT / "data" / "a12_demo"
    manifest = _json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{vessel_id}")
    demo = load_mother(AssetStore(demo_root / "store"), str(entry["asset_id"]))
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "mothers", vessel_id, material_id)
    mother = create_mother(vessel_id, material_id, dict(demo.params), rng,
                           mother_id=f"{LINEAGE_ID}_{vessel_id}_{material_id}")
    return mother, {"demo_mother_id": demo.mother_id, "demo_material_id": demo.material_id,
                    "demo_params": _jsonable(dict(demo.params)),
                    "source": "synlab.mothers.api.create_mother(demo params, real material)"}


def build_material(material_id: str) -> dict[str, Any]:
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    rng = make_rng(MASTER_SEED, LINEAGE_ID, "materials", material_id)
    return build_material_profile(material_id, default_material_params(material_id), rng)


def run_plane_baseline(mother: Any, basis: Any, rng: np.random.Generator, event_id: str
                       ) -> tuple[Any, dict[str, Any], float]:
    from synlab.fracture.api import audit_fracture, make_closed_cutter
    from synlab.fracture.event import run_shared_cut
    from synlab.fracture.spec import BACKEND_PLANE, FractureSpec

    spec = FractureSpec(backend=BACKEND_PLANE)
    started = time.time()
    cutter = make_closed_cutter(mother, spec, rng, basis=basis)
    result = run_shared_cut(mother, cutter, event_id=event_id, backend=BACKEND_PLANE)
    qa = audit_fracture(result, mother)
    return result, {"cutter": cutter, "qa": qa}, time.time() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V18")
    parser.add_argument("--material", default="M01")
    parser.add_argument("--samples", type=int, default=600_000)
    parser.add_argument("--out", default="")
    parser.add_argument("--skip-plane", action="store_true")
    parser.add_argument("--budget", type=float, default=0.01)
    parser.add_argument("--max-cells", type=int, default=400_000)
    args = parser.parse_args()

    from synlab.fracture import surface_features as sf
    from synlab.fracture.api import _default_basis
    from synlab.fracture.event import run_shared_cut
    from synlab.fracture.morphology import (
        MORPHOLOGY_META_KEY,
        BACKEND_MORPHOLOGY,
        build_morphology_cutter,
        prepare_morphology,
    )
    from synlab.fracture.spec import FractureSpec
    from synlab.seeds import make_rng

    report: dict[str, Any] = {
        "vessel_id": args.vessel, "material_id": args.material, "master_seed": MASTER_SEED,
        "lineage_id": LINEAGE_ID, "error_budget_mm": float(args.budget),
        "max_cells": int(args.max_cells),
    }
    started = time.time()
    mother, mother_info = build_mother(args.vessel, args.material)
    profile = build_material(args.material)
    bounds = np.asarray(mother.mesh.bounds, dtype=np.float64)
    report["mother"] = {
        "mother_id": mother.mother_id, "material_id": mother.material_id,
        "faces": int(len(mother.mesh.faces)), "vertices": int(len(mother.mesh.vertices)),
        "watertight": bool(mother.mesh.is_watertight),
        "volume_mm3": float(abs(mother.mesh.volume)), "area_mm2": float(mother.mesh.area),
        "extent_mm": (bounds[1] - bounds[0]).tolist(), **mother_info,
    }
    report["material_profile"] = {
        "stats": _jsonable(profile.get("stats")),
        "appearance": _jsonable(profile.get("appearance")),
        "layers": _jsonable(profile.get("layers")),
    }
    print(f"[mother] {args.vessel}/{args.material} faces={report['mother']['faces']} "
          f"vol={report['mother']['volume_mm3']:.1f} "
          f"extent={np.round(bounds[1] - bounds[0], 2).tolist()}", flush=True)

    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", args.vessel, args.material)
    basis = _default_basis(mother, rng, FractureSpec())
    report["basis"] = {"basis_id": basis.basis_id,
                       "origin": np.round(basis.origin, 6).tolist(),
                       "normal": np.round(basis.normal, 8).tolist()}

    # the body is measured once, so the plane baseline and the morphology event share the basis,
    # the wall-thickness measurement, the material profile and the fracture origin
    prepared = prepare_morphology(
        mother, material_profile=profile, rng=rng, basis=basis,
        event_id=f"{LINEAGE_ID}_{args.vessel}_{args.material}_morphology",
        error_budget_mm=float(args.budget), max_cells=int(args.max_cells))
    base_params = prepared["base_params"]
    report["prepared"] = {
        "wall": base_params.wall, "material": base_params.material,
        "origin_uv_mm": list(base_params.origin_uv_mm),
        "origin_world_mm": list(base_params.origin_world_mm),
        "core_area_mm2": float(prepared["core_area_mm2"]),
        "cross_section": _jsonable(prepared["cross_info"]),
        "predicted_amplitude_scale": float(base_params.predicted_amplitude_scale),
        "requested_curvature_per_mm": float(base_params.requested_curvature_per_mm),
        "curvature_budget_per_mm": float(base_params.curvature_budget_per_mm),
        "notes": list(base_params.notes),
    }
    print(f"[prepare] wall p05={base_params.wall['p05_mm']:.3f}mm "
          f"median={base_params.wall['median_mm']:.3f}mm "
          f"sigma_f={base_params.sigma_f_mpa:.1f}MPa r_mirror={base_params.mirror_radius_mm:.3f}mm "
          f"N_hackle={base_params.hackle_count} sigma_r0={base_params.requested_rms_mm:.4f}mm "
          f"pred_scale={base_params.predicted_amplitude_scale:.4f}", flush=True)

    # ---------------------------------------------------------------- plane baseline
    plane: dict[str, Any] = {}
    if not args.skip_plane:
        try:
            plane_result, plane_bundle, plane_seconds = run_plane_baseline(
                mother, basis, rng, f"{LINEAGE_ID}_{args.vessel}_{args.material}_plane")
            plane_cutter = plane_bundle["cutter"]
            plane_faces = sf.measure_interface_surface(plane_result.fragments, basis, base_params,
                                                       cutter_mesh=plane_cutter.mesh,
                                                       n_samples=int(args.samples))
            plane_conjugate = sf.conjugate_profile_consistency(
                plane_result.fragments, plane_result.interfaces, basis)
            plane = {
                "status": "OK", "seconds": round(plane_seconds, 3),
                "cutter_triangles": int(plane_cutter.triangles),
                "cutter_cells": int(plane_cutter.meta.get("cells", 0)),
                "qa": _jsonable(plane_bundle["qa"]),
                "delivered_faces": _jsonable(plane_faces),
                "conjugate": _jsonable(plane_conjugate),
                "fragments": [{"fragment_id": f.fragment_id, "faces": int(len(f.mesh.faces)),
                               "volume_mm3": float(f.volume_mm3)} for f in plane_result.fragments],
                "interfaces": len(plane_result.interfaces),
                "interface_area_mm2": float(sum(float(p.area_mm2)
                                                for p in plane_result.interfaces)),
            }
            print(f"[plane] {plane_seconds:.2f}s triangles={plane['cutter_triangles']} "
                  f"cells={plane['cutter_cells']} "
                  f"gap_p95={plane_bundle['qa'].get('gap_p95_mm_max'):.3e} "
                  f"passed={plane_bundle['qa'].get('passed')} "
                  f"faceRa={plane_faces.get('Ra_mm')}", flush=True)
        except BaseException as exc:  # noqa: BLE001 - a failure is a measurement
            plane = {"status": "FAILED", "error": _jsonable(
                {"code": getattr(getattr(exc, "code", None), "value", type(exc).__name__),
                 "stage": getattr(exc, "stage", ""), "message": str(exc)[:400],
                 "traceback_tail": traceback.format_exc()[-800:]})}
            print(f"[plane] FAILED {plane['error'].get('code')} {plane['error'].get('message')}",
                  flush=True)
    report["plane_baseline"] = plane

    # ---------------------------------------------------------------- morphology event
    morph: dict[str, Any] = {}
    try:
        cutter, field, params, cutter_report = build_morphology_cutter(
            mother, rng=rng, prepared=prepared, basis=basis,
            event_id=f"{LINEAGE_ID}_{args.vessel}_{args.material}_morphology",
            error_budget_mm=float(args.budget), max_cells=int(args.max_cells))
        cat = field.window
        cutter_window = sf.measure_cutter_surface(cutter.mesh, basis, params, window=cat,
                                                  n_samples=int(args.samples))
        t_event = time.time()
        result = run_shared_cut(
            mother, cutter, event_id=f"{LINEAGE_ID}_{args.vessel}_{args.material}_morphology",
            backend=BACKEND_MORPHOLOGY,
            extra_meta={MORPHOLOGY_META_KEY: params.as_dict(),
                        "cutter_cells": int(cutter_report.get("cells", 0)),
                        "cutter_realized_error_mm": float(cutter.realized_error_mm)})
        event_seconds = time.time() - t_event
        from synlab.fracture.api import audit_fracture

        qa = audit_fracture(result, mother)
        for patch in result.interfaces:
            patch.meta[MORPHOLOGY_META_KEY] = {
                "params": params.as_dict(),
                "realized": {k: cutter_window.get(k) for k in
                             ("Ra_mm", "Rz_mm", "correlation_length_mm",
                              "ridge_lines_per_mm", "waviness_rms_mm")},
            }
        for fragment in result.fragments:
            fragment.meta[MORPHOLOGY_META_KEY] = params.as_dict()
        face_surface = sf.measure_interface_surface(result.fragments, basis, params,
                                                    cutter_mesh=cutter.mesh,
                                                    n_samples=int(args.samples))
        conjugate = sf.conjugate_profile_consistency(result.fragments, result.interfaces, basis)
        morph = {
            "status": "OK",
            "seconds": round(event_seconds, 3),
            "params": params.as_dict(),
            "cutter": {
                "triangles": int(cutter.triangles),
                "cells": int(cutter_report.get("cells", 0)),
                "leaf_level": int(cutter_report.get("leaf_level", 0)),
                "realized_error_mm": float(cutter.realized_error_mm),
                "requested_error_mm": float(cutter.requested_error_mm),
                "cell_size_min_mm": float(cutter_report.get("cell_size_min_mm", 0.0)),
                "seed_cell_mm": float(cutter_report.get("seed_cell_mm", 0.0)),
                "top_triangles": int(cutter_report.get("top_triangles", 0)),
                "refine_iterations": int(cutter_report.get("refine_iterations", 0)),
                "cells_tested": int(cutter_report.get("cells_tested", 0)),
                "width_range_mm": cutter_report.get("w_range_mm"),
                "cutter_hash": cutter_report.get("cutter_hash"),
                "precision_ladder": cutter_report.get("precision_ladder"),
                "precision_ladder_attempts": cutter_report.get("precision_ladder_attempts"),
                "height_field_summary": {
                    "wavelength_min_mm": float(field.wavelength_min_mm),
                    "realized_rms_mm": float(field.realized_rms_mm),
                    "max_slope": float(field.max_slope),
                    "curvature_bound": float(field.curvature_bound()),
                    "window": _jsonable(cat.as_dict()),
                    "components": field.as_dict().get("components"),
                },
            },
            "surface": _jsonable(cutter_window),
            "delivered_faces": _jsonable(face_surface),
            "conjugate": _jsonable(conjugate),
            "qa": _jsonable(qa),
            "fragments": [{"fragment_id": f.fragment_id, "faces": int(len(f.mesh.faces)),
                           "volume_mm3": float(f.volume_mm3),
                           "interface_faces": int(np.sum(np.asarray(f.face_origin_kind) == 1))}
                          for f in result.fragments],
            "interfaces": len(result.interfaces),
            "interface_area_mm2": float(sum(float(p.area_mm2) for p in result.interfaces)),
            "unmatched_interface_area_ratio": float(
                result.meta.get("unmatched_interface_area_mm2", 0.0)
                / max(float(result.meta.get("unmatched_interface_area_mm2", 0.0))
                      + float(sum(float(p.area_mm2) for p in result.interfaces)), 1e-12)),
            "meta_key_present": all(MORPHOLOGY_META_KEY in p.meta for p in result.interfaces),
        }
        print(f"[morph] {morph['seconds']:.2f}s cells={morph['cutter']['cells']} "
              f"triangles={morph['cutter']['triangles']} "
              f"err={morph['cutter']['realized_error_mm']:.3e} "
              f"Ra={cutter_window.get('Ra_mm'):.5f}mm Rz={cutter_window.get('Rz_mm'):.5f}mm "
              f"lc={cutter_window.get('correlation_length_mm'):.4f}mm "
              f"ridges={cutter_window.get('ridge_lines_per_mm'):.4f}/mm", flush=True)
        print(f"[qa] vol_rel={qa.get('volume_rel_diff'):.3e} "
              f"overlap={qa.get('overlap_ratio'):.3e} gap_p95={qa.get('gap_p95_mm_max'):.4e}mm "
              f"normal_p95={qa.get('normal_angle_p95_deg_max'):.4f}deg "
              f"coverage={qa.get('source_coverage'):.5f} "
              f"ambig={qa.get('ambiguous_area_ratio_total'):.3e} passed={qa.get('passed')}",
              flush=True)
        if qa.get("failures"):
            print(f"[qa] FAILURES {qa['failures']}", flush=True)
    except BaseException as exc:  # noqa: BLE001 - a failure is a measurement
        morph = {"status": "FAILED", "error": _jsonable(
            {"code": getattr(getattr(exc, "code", None), "value", type(exc).__name__),
             "stage": getattr(exc, "stage", ""), "message": str(exc)[:600],
             "measurements": getattr(exc, "measurements", None),
             "traceback_tail": traceback.format_exc()[-1500:]})}
        print(f"[morph] FAILED {morph['error'].get('code')} @ {morph['error'].get('stage')}\n"
              f"    {morph['error'].get('message')}", flush=True)
    report["morphology_event"] = morph

    if plane.get("status") == "OK" and morph.get("status") == "OK":
        report["comparison"] = {
            "Ra_mm": {"plane": 0.0, "morphology": morph["surface"]["Ra_mm"]},
            "Rz_mm": {"plane": 0.0, "morphology": morph["surface"]["Rz_mm"]},
            "correlation_length_mm": {"plane": 0.0,
                                      "morphology": morph["surface"]["correlation_length_mm"]},
            "ridge_lines_per_mm": {"plane": 0.0,
                                   "morphology": morph["surface"]["ridge_lines_per_mm"]},
            "cutter_triangles": {"plane": plane["cutter_triangles"],
                                 "morphology": morph["cutter"]["triangles"],
                                 "ratio": (morph["cutter"]["triangles"]
                                           / max(plane["cutter_triangles"], 1))},
            "cutter_cells": {"plane": plane["cutter_cells"],
                             "morphology": morph["cutter"]["cells"],
                             "ratio": morph["cutter"]["cells"]
                             / max(plane["cutter_cells"], 1)},
            "event_seconds": {"plane": plane["seconds"], "morphology": morph["seconds"],
                              "ratio": morph["seconds"] / max(plane["seconds"], 1e-9)},
            "delivered_Ra_mm": {
                "plane": (plane.get("delivered_faces") or {}).get("Ra_mm", 0.0),
                "morphology": (morph.get("delivered_faces") or {}).get("Ra_mm", 0.0)},
            "delivered_Rz_mm": {
                "plane": (plane.get("delivered_faces") or {}).get("Rz_mm", 0.0),
                "morphology": (morph.get("delivered_faces") or {}).get("Rz_mm", 0.0)},
            "fragment_faces": {
                "plane": [f["faces"] for f in plane.get("fragments", [])],
                "morphology": [f["faces"] for f in morph.get("fragments", [])]},
        }

    report["duration_s"] = round(time.time() - started, 3)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[written] {args.out} ({len(text)/1024:.0f} KiB)", flush=True)
    return 0 if morph.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
