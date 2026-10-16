"""Stage-by-stage probe of the implicit backend: every stage prints and writes its own JSON.

The host kills heavy runs, so nothing here builds the whole pipeline in one go: each stage is timed,
printed with ``flush`` and persisted before the next one starts.
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

MASTER_SEED = 20261001
LINEAGE_ID = "a12_fracture_implicit"
OUT = REPO_ROOT / "data" / "a12_reports" / "implicit"


def log(step: str, payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    print(f"[{step}] {text[:1500]}", flush=True)
    (OUT / f"stage_{step}.json").write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="")
    parser.add_argument("--material", default="M01")
    parser.add_argument("--extent", type=float, default=12.0)
    parser.add_argument("--triangles", type=int, default=120_000)
    parser.add_argument("--budget", type=float, default=0.01)
    parser.add_argument("--delta", type=float, default=0.0)
    parser.add_argument("--event", action="store_true")
    parser.add_argument("--stage", default="all")
    args = parser.parse_args()

    import fixtures as fx

    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    started = time.time()
    if args.vessel:
        import json as _json

        from synlab.mothers.api import create_mother, load_mother
        from synlab.storage.store import AssetStore

        demo_root = REPO_ROOT / "data" / "a12_demo"
        manifest = _json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
        entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{args.vessel}")
        demo = load_mother(AssetStore(demo_root / "store"), str(entry["asset_id"]))
        rng = make_rng(MASTER_SEED, LINEAGE_ID, "mothers", args.vessel, args.material)
        mother = create_mother(args.vessel, args.material, dict(demo.params), rng,
                               mother_id=f"{LINEAGE_ID}_{args.vessel}_{args.material}")
    else:
        mother = fx.box_mother((args.extent, args.extent, args.extent), mother_id="stage_probe")
    log("mother", {"seconds": round(time.time() - started, 3), "faces": int(len(mother.mesh.faces)),
                   "volume_mm3": float(abs(mother.mesh.volume)),
                   "watertight": bool(mother.mesh.is_watertight)})

    profile = build_material_profile(args.material, default_material_params(args.material),
                                     make_rng(MASTER_SEED, LINEAGE_ID, "materials", args.material))
    options = {"max_sheet_triangles": int(args.triangles)}
    if args.delta > 0:
        options["samples_per_wavelength"] = 5.0

    from synlab.fracture.implicit.backend import build_implicit_cutter

    stage = time.time()
    try:
        cutter, field, params, report = build_implicit_cutter(
            mother, material_profile=profile, rng=make_rng(MASTER_SEED, LINEAGE_ID, "build"),
            event_id="stage_probe", error_budget_mm=float(args.budget), options=options)
    except Exception as exc:  # noqa: BLE001 - report, never repair
        log("build_failed", {"seconds": round(time.time() - stage, 3),
                             "error": f"{type(exc).__name__}: {exc}",
                             "measurements": getattr(exc, "measurements", None),
                             "traceback": traceback.format_exc()[-2500:]})
        return 1
    log("build", {"seconds": round(time.time() - stage, 3),
                  "plan": report["sampling_plan"], "topology": report["topology"],
                  "error": report["realized_error"], "sampling": report["sampling_density"],
                  "timings": report["timings_seconds"], "peak_mb": report["peak_memory_mb"],
                  "slope_before_deg": report["field"]["slope"]["before"]["angle_p95_deg"],
                  "slope_after_deg": report["field"]["slope"]["after"]["angle_p95_deg"],
                  "scale": report["field"]["slope"]["amplitude_scale_applied"],
                  "ring": report["field"]["ring"],
                  "band_limit": report["field"]["band_limit"],
                  "envelope": {k: v for k, v in report["field"]["envelope"].items()
                               if k != "construction"},
                  "closure": report["closure"],
                  "cutter_triangles": int(cutter.triangles)})
    if args.stage == "build":
        return 0

    if args.event:
        from synlab.fracture.api import audit_fracture
        from synlab.fracture.implicit.assembler import assemble_implicit_event

        stage = time.time()
        try:
            result = assemble_implicit_event(mother, cutter, event_id="stage_probe",
                                            backend="implicit_sheet_cut")
            audit = audit_fracture(result, mother)
        except Exception as exc:  # noqa: BLE001
            log("event_failed", {"seconds": round(time.time() - stage, 3),
                                 "error": f"{type(exc).__name__}: {exc}",
                                 "measurements": getattr(exc, "measurements", None),
                                 "traceback": traceback.format_exc()[-2500:]})
            return 1
        log("event", {"seconds": round(time.time() - stage, 3), "audit": audit,
                      "fragments": [{"id": f.fragment_id, "volume_mm3": float(f.volume_mm3),
                                     "faces": int(len(f.mesh.faces)),
                                     "watertight": bool(f.mesh.is_watertight),
                                     "winding": bool(f.mesh.is_winding_consistent),
                                     "tiny": bool(f.is_tiny)} for f in result.fragments],
                      "interfaces": [{"id": int(p.interface_id), "area_mm2": float(p.area_mm2),
                                      "gap_p95_mm": float(p.gap_p95_mm),
                                      "normal_p95_deg": float(p.normal_angle_p95_deg),
                                      "faces_a": int(np.asarray(p.meta.get("faces_a", [])).size),
                                      "samples": int(p.sample_points_a.shape[0])}
                                     for p in result.interfaces]})
        from synlab.fracture import surface_features as sf

        basis = report_basis(result, cutter)
        stage = time.time()
        conjugate = sf.conjugate_profile_consistency(list(result.fragments), result.interfaces,
                                                     basis)
        log("conjugate", {"seconds": round(time.time() - stage, 3),
                          "summary": {k: v for k, v in conjugate.items() if k != "patches"},
                          "patches": conjugate["patches"]})
    return 0


def report_basis(result, cutter):
    from synlab.fracture.event import BASIS_META_KEY

    basis = (getattr(result, "meta", {}) or {}).get(BASIS_META_KEY)
    return basis if basis is not None else cutter.basis


if __name__ == "__main__":
    raise SystemExit(main())
