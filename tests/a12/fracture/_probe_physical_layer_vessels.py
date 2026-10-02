"""Find a mother on which the frozen morphology cutter is actually deliverable.

For each demo vessel: the shared basis, the measured wall thickness, the cross-section, the
predicted amplitude scale and the cell demand -- then one real cutter build.  Nothing is relaxed:
a vessel that does not fit the frozen 0.01 mm / 400 000-cell budget is reported as such.
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
LINEAGE_ID = "a12_physical_layer"
OUT_DIR = REPO_ROOT / "data" / "a12_reports" / "physical_layer"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessels", default="V01,V02,V03,V04,V06,V10,V18")
    parser.add_argument("--materials", default="M03,M07")
    parser.add_argument("--budget", type=float, default=0.01)
    parser.add_argument("--max-cells", type=int, default=400_000)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from synlab.fracture.api import _default_basis
    from synlab.fracture.morphology import (build_morphology_cutter, flat_cross_section,
                                            prepare_morphology, wall_thickness)
    from synlab.fracture.spec import FractureSpec
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    from _run_physical_layer_matrix import build_mother, error_record

    report: dict[str, Any] = {"stage": "physical_layer_vessel_sweep",
                              "error_budget_mm": float(args.budget),
                              "max_cells": int(args.max_cells), "vessels": {}}
    for vessel_id in [v.strip() for v in str(args.vessels).split(",") if v.strip()]:
        row: dict[str, Any] = {}
        print(f"=== {vessel_id} ===", flush=True)
        try:
            mother, info = build_mother(vessel_id, "M03")
            bounds = np.asarray(mother.mesh.bounds, dtype=np.float64)
            extent = (bounds[1] - bounds[0]).tolist()
            wall = wall_thickness(mother, max_probes=320)
            rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", vessel_id, "shared_basis")
            basis = _default_basis(mother, rng, FractureSpec())
            tris_uv, core_area, _info = flat_cross_section(basis, mother.mesh)
            row.update({"mother_id": mother.mother_id, "faces": int(len(mother.mesh.faces)),
                        "extent_mm": extent, "wall": wall.as_dict(),
                        "core_area_mm2": float(core_area),
                        "basis_normal": np.round(np.asarray(basis.normal, dtype=np.float64),
                                                 6).tolist()})
            print(f"  extent={np.round(extent, 1).tolist()} wall p05={wall.p05_mm:.2f} "
                  f"core={core_area:.1f}mm2", flush=True)
            for material_id in [m.strip() for m in str(args.materials).split(",") if m.strip()]:
                profile = build_material_profile(
                    material_id, default_material_params(material_id),
                    make_rng(MASTER_SEED, LINEAGE_ID, "materials", material_id))
                case_rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", vessel_id, material_id)
                started = time.time()
                try:
                    prepared = prepare_morphology(
                        mother, material_profile=profile, rng=case_rng, basis=basis,
                        event_id=f"{LINEAGE_ID}_{vessel_id}_{material_id}",
                        error_budget_mm=float(args.budget), max_cells=int(args.max_cells))
                    params = prepared["base_params"]
                    prepared_info = {
                        "predicted_amplitude_scale": float(params.predicted_amplitude_scale),
                        "requested_rms_mm": float(params.requested_rms_mm),
                        "requested_curvature_per_mm": float(params.requested_curvature_per_mm),
                        "curvature_budget_per_mm": float(params.curvature_budget_per_mm),
                        "mirror_radius_mm": float(params.mirror_radius_mm),
                        "hackle_count": int(params.hackle_count),
                        "pit_count": int(params.pit_count),
                        "sigma_f_mpa": float(params.sigma_f_mpa),
                        "window_area_estimate_mm2": float(
                            prepared["window_area_estimate_mm2"]),
                    }
                    cutter, field, params2, cutter_report = build_morphology_cutter(
                        mother, material_profile=profile, rng=case_rng, basis=basis,
                        event_id=f"{LINEAGE_ID}_{vessel_id}_{material_id}",
                        error_budget_mm=float(args.budget), max_cells=int(args.max_cells))
                    row[material_id] = {
                        "status": "OK", "seconds": round(time.time() - started, 2),
                        "prepared": prepared_info,
                        "cells": int(cutter_report.get("cells", 0)),
                        "triangles": int(cutter.triangles),
                        "realized_error_mm": float(cutter.realized_error_mm),
                        "watertight": bool(cutter.mesh.is_watertight),
                        "precision_amplitude_scale": float(
                            cutter_report.get("precision_amplitude_scale", 1.0)),
                        "cell_demand_estimate": cutter_report.get("cell_demand_estimate"),
                        "relief_rms_mm": float(field.meta.get("relief_rms_mm", 0.0)),
                    }
                    print(f"  {material_id}: OK tris={cutter.triangles} "
                          f"cells={cutter_report.get('cells')} "
                          f"scale={cutter_report.get('precision_amplitude_scale'):.4f} "
                          f"err={cutter.realized_error_mm:.3e} "
                          f"wt={cutter.mesh.is_watertight}", flush=True)
                except BaseException as exc:  # noqa: BLE001
                    row[material_id] = {"status": "FAILED",
                                        "seconds": round(time.time() - started, 2),
                                        "prepared": prepared_info
                                        if "prepared_info" in dir() else None,
                                        "error": error_record(exc)}
                    print(f"  {material_id}: FAILED "
                          f"{row[material_id]['error']['code']} @ "
                          f"{row[material_id]['error']['stage']}: "
                          f"{row[material_id]['error']['message'][:220]}", flush=True)
        except BaseException as exc:  # noqa: BLE001
            row["status"] = "FAILED"
            row["error"] = error_record(exc)
            print(f"  mother FAILED: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
            traceback.print_exc()
        report["vessels"][vessel_id] = row

    out = Path(args.out) if args.out else (OUT_DIR / "vessel_sweep.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                   encoding="utf-8")
    print(f"[written] {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
