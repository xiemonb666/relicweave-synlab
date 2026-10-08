"""Fast smoke probe of the implicit-sheet cutter on the analytic box fixture.

Only the *build* stages run here (field, sheet, closure, verification) plus, with ``--event``, the
shared-cut boolean.  It exists so the implementation can be iterated without paying for a real
mother on every edit.
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extent", type=float, default=12.0)
    parser.add_argument("--material", default="M01")
    parser.add_argument("--event", action="store_true")
    parser.add_argument("--delta", type=float, default=0.0)
    parser.add_argument("--triangles", type=int, default=420_000)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    import fixtures as fx

    from synlab.fracture.implicit.backend import build_implicit_cutter
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    mother = fx.box_mother((args.extent, args.extent, args.extent),
                           mother_id=f"{LINEAGE_ID}_box{args.extent:g}")
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "materials", args.material)
    profile = build_material_profile(args.material, default_material_params(args.material), rng)
    report: dict = {"fixture": f"box{args.extent:g}", "material": args.material}
    total = time.time()
    try:
        cutter, field, params, build_report = build_implicit_cutter(
            mother, material_profile=profile, rng=make_rng(MASTER_SEED, LINEAGE_ID, "build"),
            event_id="smoke", error_budget_mm=0.01,
            options={"max_sheet_triangles": int(args.triangles),
                     **({"delta_mm": args.delta} if args.delta > 0 else {})})
        report["build"] = {k: v for k, v in build_report.items() if k != "field"}
        report["build_ok"] = True
    except Exception as exc:
        report["build_ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()[-4000:]
        if hasattr(exc, "measurements"):
            report["measurements"] = exc.measurements
        _write(report, args.out, total)
        return 1
    if args.event:
        from synlab.fracture.api import audit_fracture
        from synlab.fracture.event import run_shared_cut

        started = time.time()
        try:
            result = run_shared_cut(mother, cutter, event_id="smoke",
                                    backend="implicit_sheet_cut")
            report["event_seconds"] = time.time() - started
            report["audit"] = audit_fracture(result, mother)
            report["fragments"] = [
                {"fragment_id": f.fragment_id, "volume_mm3": float(f.volume_mm3),
                 "faces": int(len(f.mesh.faces)), "watertight": bool(f.mesh.is_watertight),
                 "winding": bool(f.mesh.is_winding_consistent)}
                for f in result.fragments]
            report["interfaces"] = [
                {"interface_id": int(p.interface_id), "area_mm2": float(p.area_mm2),
                 "gap_p95_mm": float(p.gap_p95_mm),
                 "normal_angle_p95_deg": float(p.normal_angle_p95_deg)}
                for p in result.interfaces]
        except Exception as exc:
            report["event_ok"] = False
            report["event_error"] = f"{type(exc).__name__}: {exc}"
            report["event_traceback"] = traceback.format_exc()[-3000:]
            if hasattr(exc, "measurements"):
                report["event_measurements"] = exc.measurements
        else:
            report["event_ok"] = True
    _write(report, args.out, total)
    return 0 if report.get("build_ok") else 1


def _write(report: dict, out: str, total: float) -> None:
    report["total_seconds"] = time.time() - total
    text = json.dumps(report, ensure_ascii=False, indent=1, default=str)
    path = Path(out) if out else (REPO_ROOT / "data" / "a12_reports" / "implicit" / "smoke.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(text[:6000])


if __name__ == "__main__":
    raise SystemExit(main())
