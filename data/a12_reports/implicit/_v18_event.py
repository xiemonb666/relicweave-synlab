"""Staged V18 event attempt: build (exported to disk) then the assembler step by step.

The cutter is cached on disk so the expensive build is paid once while the event stages are probed.
Every step prints with ``flush`` so a host kill leaves the last completed step on disk.
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
CACHE = OUT / "cutter_cache"


def log(step: str, payload: dict) -> None:
    (OUT / f"v18_{step}.json").write_text(
        json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[{step}] {json.dumps(payload, ensure_ascii=False, default=str)[:900]}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vessel", default="V18")
    ap.add_argument("--material", default="M01")
    ap.add_argument("--triangles", type=int, default=420000)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    tag = f"{args.vessel}_{args.material}_{args.triangles}"

    import fixtures as fx

    import trimesh

    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    if args.vessel:
        import json as _json

        from synlab.mothers.api import create_mother, load_mother
        from synlab.storage.store import AssetStore

        demo_root = REPO_ROOT / "data" / "a12_demo"
        manifest = _json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
        entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{args.vessel}")
        demo = load_mother(AssetStore(demo_root / "store"), str(entry["asset_id"]))
        mother = create_mother(args.vessel, args.material, dict(demo.params),
                               make_rng(20261001, "imp", "m"), mother_id=f"imp_{args.vessel}")
    else:
        mother = fx.box_mother((12.0, 12.0, 12.0), mother_id="imp_box")
    profile = build_material_profile(args.material, default_material_params(args.material),
                                     make_rng(20261001, "imp", "mat"))
    log("mother", {"volume": float(abs(mother.mesh.volume)), "faces": int(len(mother.mesh.faces))})

    from synlab.fracture.implicit.backend import build_implicit_cutter

    mesh_path = CACHE / f"cutter_{tag}.ply"
    meta_path = CACHE / f"cutter_{tag}.json"
    stage = time.time()
    cutter, field, params, report = build_implicit_cutter(
        mother, material_profile=profile, rng=make_rng(20261001, "imp", "build"),
        event_id="imp", error_budget_mm=0.01,
        options={"max_sheet_triangles": int(args.triangles)})
    log("build", {"seconds": round(time.time() - stage, 2),
                  "faces": int(len(cutter.mesh.faces)),
                  "triangles_top": report["sheet"]["top_triangles"],
                  "delta_mm": report["sampling_plan"]["delta_final_mm"],
                  "lambda_realized": report["sampling_plan"]["lambda_min_realized_mm"],
                  "error_mm": report["realized_error_mm"],
                  "bad_edges": report["bad_edges"], "watertight": report["watertight"],
                  "timings": report["timings_seconds"], "peak_mb": report["peak_memory_mb"],
                  "sampling": report["sampling_density"],
                  "slope_before": report["field"]["slope"]["before"]["angle_p95_deg"],
                  "slope_after": report["field"]["slope"]["after"]["angle_p95_deg"],
                  "scale": report["field"]["slope"]["amplitude_scale_applied"],
                  "ring": report["field"]["ring"], "band_limit": report["field"]["band_limit"]})
    cutter.mesh.export(mesh_path)
    meta_path.write_text(json.dumps(
        {"basis": {"origin": np.asarray(cutter.basis.origin).tolist(),
                   "e_u": np.asarray(cutter.basis.e_u).tolist(),
                   "e_v": np.asarray(cutter.basis.e_v).tolist(),
                   "normal": np.asarray(cutter.basis.normal).tolist(),
                   "u_range": list(cutter.basis.u_range), "v_range": list(cutter.basis.v_range),
                   "basis_id": cutter.basis.basis_id},
         "report": report}, ensure_ascii=False, default=str), encoding="utf-8")

    from synlab.fracture.booleans import boolean_difference, boolean_intersection, mesh_hash
    from synlab.fracture.booleans import tag_source

    stage = time.time()
    source_mother = tag_source(trimesh.Trimesh(vertices=np.asarray(mother.mesh.vertices),
                                               faces=np.asarray(mother.mesh.faces), process=False),
                               1.0, "mother")
    source_cutter = tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                               faces=np.asarray(cutter.mesh.faces), process=False),
                               2.0, "cutter")
    log("tagged", {"seconds": round(time.time() - stage, 2)})
    stage = time.time()
    minus = boolean_intersection([source_mother, source_cutter], label="M_minus")
    log("intersection", {"seconds": round(time.time() - stage, 2), "faces": int(minus.n_faces)})
    stage = time.time()
    plus = boolean_difference([source_mother, source_cutter], label="M_plus")
    log("difference", {"seconds": round(time.time() - stage, 2), "faces": int(plus.n_faces)})

    stage = time.time()
    try:
        from synlab.fracture.implicit.assembler import assemble_implicit_event

        result = assemble_implicit_event(mother, cutter, event_id="imp",
                                        backend="implicit_sheet_cut")
    except Exception as exc:  # noqa: BLE001
        log("event_failed", {"error": f"{type(exc).__name__}: {exc}",
                             "measurements": getattr(exc, "measurements", None),
                             "traceback": traceback.format_exc()[-2000:]})
        return 1
    log("event", {"seconds": round(time.time() - stage, 2),
                  "fragments": [{"id": f.fragment_id, "volume_mm3": float(f.volume_mm3),
                                 "faces": int(len(f.mesh.faces)),
                                 "tiny": bool(f.is_tiny)} for f in result.fragments],
                  "interfaces": [{"id": int(p.interface_id), "area_mm2": float(p.area_mm2),
                                  "gap_p95_mm": float(p.gap_p95_mm),
                                  "gap_max_mm": float(p.meta.get("gap_max_mm", 0.0)),
                                  "normal_angle_p95_deg": float(p.normal_angle_p95_deg),
                                  "area_rel_error": float(p.meta.get("area_rel_error", 0.0)),
                                  "pairs": int(p.meta.get("pair_count", 0))}
                                 for p in result.interfaces],
                  "timings": result.meta.get("assembly_timings_seconds")})
    from synlab.fracture.api import audit_fracture

    stage = time.time()
    try:
        audit = audit_fracture(result, mother)
    except Exception as exc:  # noqa: BLE001
        log("audit_failed", {"error": f"{type(exc).__name__}: {exc}",
                             "measurements": getattr(exc, "measurements", None),
                             "traceback": traceback.format_exc()[-1500:]})
        return 2
    log("audit", {"seconds": round(time.time() - stage, 2), "audit": audit})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
