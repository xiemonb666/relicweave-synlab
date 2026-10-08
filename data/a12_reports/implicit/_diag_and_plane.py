"""Plane baseline on the same mother + basis, and the interface-classification diagnostic.

Two questions, both measured here:

1. does the frozen ``plane_shared_cut`` backend hit the same source-coverage / ambiguity numbers on
   this (mother, basis) pair?  That decides whether the implicit backend's coverage loss is a
   property of the *configuration* (a cut plane nearly tangent to the wall) or of its classifier;
2. are the faces the classifier calls ``INTERFACE`` really on the sheet -- i.e. is
   ``|w - h(u, v)|`` inside the realized interpolation budget?
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vessel", default="V18")
    ap.add_argument("--material", default="M01")
    args = ap.parse_args()
    import json as _json

    import trimesh

    from synlab.fracture.api import audit_fracture, make_closed_cutter
    from synlab.fracture.booleans import mesh_hash
    from synlab.fracture.event import run_shared_cut
    from synlab.fracture.implicit.assembler import assemble_implicit_event, sheet_distance
    from synlab.fracture.spec import BACKEND_PLANE, FractureSpec
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.mothers.api import create_mother, load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    demo_root = REPO_ROOT / "data" / "a12_demo"
    manifest = _json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{args.vessel}")
    demo = load_mother(AssetStore(demo_root / "store"), str(entry["asset_id"]))
    mother = create_mother(args.vessel, args.material, dict(demo.params),
                           make_rng(MASTER_SEED, LINEAGE, "mothers", args.vessel, args.material),
                           mother_id=f"{LINEAGE}_{args.vessel}_{args.material}")
    profile = build_material_profile(args.material, default_material_params(args.material),
                                     make_rng(MASTER_SEED, LINEAGE, "materials", args.material))

    from synlab.fracture.implicit.backend import build_implicit_cutter

    stage = time.time()
    cutter, field, params, report = build_implicit_cutter(
        mother, material_profile=profile, rng=make_rng(MASTER_SEED, LINEAGE, "build"),
        event_id="diag", error_budget_mm=0.01, options={"max_sheet_triangles": 420000})
    basis = cutter.basis
    print(f"[implicit build] {time.time() - stage:.1f}s faces={len(cutter.mesh.faces)} "
          f"error={report['realized_error_mm']:.6f}", flush=True)

    out: dict = {"vessel": args.vessel, "material": args.material,
                 "implicit_realized_error_mm": float(report["realized_error_mm"])}

    # ------------------------------------------------------------------ implicit diagnostics
    stage = time.time()
    result = assemble_implicit_event(mother, cutter, event_id="diag", backend="implicit_sheet_cut")
    print(f"[implicit event] {time.time() - stage:.1f}s", flush=True)
    rows = []
    for fragment in result.fragments:
        origin = np.asarray(fragment.face_origin_kind)
        distances = []
        for origin_kind in (0, 1, 2):
            ids = np.nonzero(origin == origin_kind)[0]
            if ids.size == 0:
                continue
            centroids = np.asarray(fragment.mesh.triangles_center, dtype=np.float64)[ids]
            d_sheet, _local = sheet_distance(basis, cutter.h_fn, centroids)
            rows.append({
                "fragment": fragment.fragment_id, "origin": int(origin_kind),
                "faces": int(ids.size),
                "area_mm2": float(np.asarray(fragment.mesh.area_faces)[ids].sum()),
                "d_sheet_p50": float(np.percentile(d_sheet, 50)),
                "d_sheet_p95": float(np.percentile(d_sheet, 95)),
                "d_sheet_max": float(d_sheet.max()),
                "faces_beyond_budget": int(np.sum(d_sheet > float(report["realized_error_mm"]))),
                "area_beyond_budget_mm2": float(
                    np.asarray(fragment.mesh.area_faces)[ids][
                        d_sheet > float(report["realized_error_mm"])].sum()),
            })
    out["implicit_origin_diagnostic"] = rows
    try:
        out["implicit_audit"] = audit_fracture(result, mother)
    except Exception as exc:  # noqa: BLE001
        out["implicit_audit_failed"] = f"{type(exc).__name__}: {exc}"
        out["implicit_audit_measurements"] = getattr(exc, "measurements", None)
    print(f"[implicit diagnostic] {json.dumps(rows, ensure_ascii=False)[:800]}", flush=True)
    (OUT / "diag_v18.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                       encoding="utf-8")

    # ------------------------------------------------------------------ plane baseline
    stage = time.time()
    try:
        spec = FractureSpec(backend=BACKEND_PLANE, error_budget_mm=0.01)
        plane_cutter = make_closed_cutter(mother, spec, make_rng(MASTER_SEED, LINEAGE, "plane"),
                                          basis=basis)
        plane = run_shared_cut(mother, plane_cutter, event_id="plane_baseline",
                               backend=BACKEND_PLANE)
        out["plane"] = {
            "seconds": time.time() - stage,
            "cutter_faces": int(len(plane_cutter.mesh.faces)),
            "cutter_hash": mesh_hash(plane_cutter.mesh),
            "realized_error_mm": float(plane_cutter.realized_error_mm),
            "topology": {"watertight": bool(plane_cutter.mesh.is_watertight),
                         "winding": bool(plane_cutter.mesh.is_winding_consistent),
                         "volume_mm3": float(abs(plane_cutter.mesh.volume)),
                         "bad_edges": None},
            "fragments": [{"id": f.fragment_id, "volume_mm3": float(f.volume_mm3),
                           "faces": int(len(f.mesh.faces))} for f in plane.fragments],
        }
        try:
            out["plane"]["audit"] = audit_fracture(plane, mother)
        except Exception as exc:  # noqa: BLE001
            out["plane"]["audit_failed"] = f"{type(exc).__name__}: {exc}"
            out["plane"]["audit_measurements"] = getattr(exc, "measurements", None)
    except Exception as exc:  # noqa: BLE001
        out["plane"] = {"failed": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc()[-1500:],
                        "measurements": getattr(exc, "measurements", None)}
    print(f"[plane] {json.dumps(out.get('plane', {}), ensure_ascii=False, default=str)[:900]}",
          flush=True)
    (OUT / "diag_v18.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
