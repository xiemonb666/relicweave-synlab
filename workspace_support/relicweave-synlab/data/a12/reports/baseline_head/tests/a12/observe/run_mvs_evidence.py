"""Evidence runner for the observation-side gaps (A14 / A24 / A25).

Run it with the repository virtualenv::

    .venv/Scripts/python.exe tests/a12/observe/run_mvs_evidence.py --frames 12

Exit codes
----------
``0``  every step ran and its report was written (the *pipeline* verdict inside the report
       may still be STOP_SFM / MVS_NOT_AVAILABLE - that is a measured result, not a crash)
``3``  a step raised; the traceback is printed and the partial on-disk evidence is kept
``4``  the pixel/display contract audit reported ``ok=false`` (A25 would be FAIL)

Steps
-----
1. ``synlab.cameras.audit.audit_pixel_contract`` -> ``data/a12/reports/pixel_contract.json``
2. ``synlab.observe.mvs_subset.run_mvs_subset`` -> ``data/a12/reports/mvs_subset.json``
3. ``synlab.observe.mvs_subset.audit_source_dependency`` ->
   ``data/a12/reports/source_dependency_audit.json``
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=12,
                        help="frames per fragment for the MVS subset (plan 13.1 budget: 12)")
    parser.add_argument("--width", type=int, default=800)
    parser.add_argument("--height", type=int, default=600)
    parser.add_argument("--mothers", type=int, default=1)
    parser.add_argument("--store", default=str(ROOT / "data" / "a12_demo" / "store"))
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--audit-frames", type=int, default=6)
    parser.add_argument("--skip-pixel", action="store_true")
    parser.add_argument("--skip-mvs", action="store_true")
    parser.add_argument("--skip-source", action="store_true")
    args = parser.parse_args()

    summary: dict[str, object] = {"steps": []}
    exit_code = 0
    store_path = Path(args.store)

    if not args.skip_pixel:
        from synlab.cameras.audit import audit_pixel_contract

        try:
            result = audit_pixel_contract()
            summary["steps"].append({
                "step": "pixel_contract", "ok": result["ok"], "status": result["status"],
                "failing_checks": result["metrics"]["failing_checks"],
                "max_px_error": result["metrics"]["pixel_transforms"]["max_px_error"],
                "max_mm_error": result["metrics"]["pixel_transforms"]["max_mm_error"],
                "display_edge_error_m":
                    result["metrics"]["display"]["display_edge_max_error_m"],
                "reports": result["report_paths"],
            })
            if not result["ok"]:
                exit_code = 4
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            summary["steps"].append({"step": "pixel_contract", "error": "raised"})
            return 3

    if not args.skip_mvs:
        from synlab.observe.mvs_subset import MvsConfig, run_mvs_subset

        try:
            config = MvsConfig(frames_per_fragment=int(args.frames),
                               delivered_size=(int(args.width), int(args.height)),
                               render_pixels=int(args.width) * int(args.height),
                               max_image_size=int(args.width))
            report = run_mvs_subset(store_path, limit_mothers=int(args.mothers),
                                    out_dir=args.out_dir, config=config)
            summary["steps"].append({
                "step": "mvs_subset", "ok": report["ok"], "pipeline_ok": report["pipeline_ok"],
                "attempted": report["attempted"],
                "registered_frames": report["registered_frames"],
                "sparse_points": report["sparse_points"],
                "dense_points": report["dense_points"],
                "reprojection_error_px": report["reprojection_error_px"],
                "seconds": report["seconds"], "failure_code": report["failure_code"],
                "dense_status": report.get("dense_status"),
                "reports": report.get("report_paths"),
            })
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            summary["steps"].append({"step": "mvs_subset", "error": "raised"})
            return 3

    if not args.skip_source:
        from synlab.observe.mvs_subset import MvsConfig, audit_source_dependency

        try:
            audit = audit_source_dependency(
                store_path, frames=int(args.audit_frames),
                config=MvsConfig(frames_per_fragment=int(args.audit_frames),
                                 delivered_size=(640, 480), render_pixels=640 * 480,
                                 max_image_size=640))
            summary["steps"].append({
                "step": "source_dependency", "ok": audit["ok"], "status": audit["status"],
                "checks": {name: bool(value.get("ok"))
                           for name, value in audit["checks"].items()},
                "metrics": {k: v for k, v in audit["metrics"].items()
                            if k in ("pose_table_translation_delta_mm",
                                     "pose_table_rotation_delta_deg")},
                "reports": audit.get("report_paths"),
            })
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            summary["steps"].append({"step": "source_dependency", "error": "raised"})
            return 3

    summary["exit_code"] = exit_code
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
