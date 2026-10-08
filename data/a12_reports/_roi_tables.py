"""Assemble the measured tables of docs/a12/fracture_visible.md from the run JSON."""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RUN = json.loads((ROOT / "data/a12_reports/fracture_roi_run.json").read_text(encoding="utf-8"))
TIMING = json.loads((ROOT / "data/a12_reports/fracture_roi_timing.json").read_text(encoding="utf-8"))


def med(records, key):
    values = [float(r[key]) for r in records
              if r.get(key) is not None and np.isfinite(float(r[key]))]
    return float(statistics.median(values)) if values else None


def main() -> None:
    print("== per body")
    rows = []
    for body in RUN["bodies"]:
        w, r = body["whole_records"], body["roi_records"]
        rois = body["rois"]
        row = {
            "vessel": body["body"]["vessel_id"], "material": body["body"]["material_id"],
            "asset": body["body"]["asset_id"],
            "wall_s": round(body["wall_seconds"], 1),
            "whole_views": len(w), "roi_views": len(r),
            "whole_mm_px_ray": med(w, "mm_per_px_axis_raycast"),
            "whole_mm_px_depth": med(w, "mm_per_px_measured"),
            "roi_mm_px_ray": med(r, "mm_per_px_axis_raycast"),
            "roi_mm_px_depth": med(r, "mm_per_px_measured"),
            "whole_rim_px": sum(int(x["rim_px"]) for x in w),
            "roi_rim_px": sum(int(x["rim_px"]) for x in r),
            "whole_rim_frac_obj": med(w, "rim_fraction_of_object"),
            "roi_rim_frac_obj": med(r, "rim_fraction_of_object"),
            "whole_dof_mm": med(w, "dof_cover_mm"),
            "roi_dof_mm": med(r, "dof_cover_mm"),
            "roi_in_dof_views": sum(1 for x in r if x.get("depth_centre_within_dof")),
            "disagree_max_mm": body["summary"]["instrument_disagreement_mm"]["max_abs_mm"],
            "disagree_over_1mm": body["summary"]["instrument_disagreement_mm"]["n_views_over_1mm"],
            "gpu_peak_mib": (body["timing"].get("gpu_memory") or {}).get("peak_mib"),
            "whole_s": round(float(body["timing"]["whole_fragment_seconds"]), 1),
            "roi_s": round(float(body["timing"]["fracture_roi_seconds"]), 1),
            "n_rois": len(rois),
            "roi_area_mm2": [round(x["area_mm2"], 1) for x in rois],
            "roi_parent_area_mm2": [round(x["parent_area_mm2"], 1) for x in rois],
            "ra_plane_mm": [round(x["height"]["plane"]["Ra_mm"], 5) for x in rois],
            "ra_below5_mm": [round(x["height"]["bands"]["below_5mm"]["Ra_mm"], 5) for x in rois],
            "ra_below1_mm": [round(x["height"]["bands"]["below_1mm"]["Ra_mm"], 9) for x in rois],
            "ra_below025_mm": [round(x["height"]["bands"]["below_0.25mm"]["Ra_mm"], 9)
                               for x in rois],
            "feasible": [bool((x.get("capture_feasible") if x.get("capture_feasible") is not None
                               else True)) for x in
                         [f.meta for f in []]] or None,
        }
        row.pop("feasible")
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    all_w = [x for b in RUN["bodies"] for x in b["whole_records"]]
    all_r = [x for b in RUN["bodies"] for x in b["roi_records"]]
    print("\n== totals")
    print(json.dumps({
        "n_whole": len(all_w), "n_roi": len(all_r),
        "whole_mm_px_ray": med(all_w, "mm_per_px_axis_raycast"),
        "roi_mm_px_ray": med(all_r, "mm_per_px_axis_raycast"),
        "whole_mm_px_depth": med(all_w, "mm_per_px_measured"),
        "roi_mm_px_depth": med(all_r, "mm_per_px_measured"),
        "whole_0p2_px": 0.2 / med(all_w, "mm_per_px_axis_raycast"),
        "roi_0p2_px": 0.2 / med(all_r, "mm_per_px_axis_raycast"),
        "whole_reff4": 4 * med(all_w, "mm_per_px_axis_raycast"),
        "roi_reff4": 4 * med(all_r, "mm_per_px_axis_raycast"),
        "whole_rim_px": sum(int(x["rim_px"]) for x in all_w),
        "roi_rim_px": sum(int(x["rim_px"]) for x in all_r),
        "whole_rim_frac_obj": med(all_w, "rim_fraction_of_object"),
        "roi_rim_frac_obj": med(all_r, "rim_fraction_of_object"),
        "whole_dof": med(all_w, "dof_cover_mm"), "roi_dof": med(all_r, "dof_cover_mm"),
        "disagree_max_all_mm": max(
            b["summary"]["instrument_disagreement_mm"]["max_abs_mm"] for b in RUN["bodies"]),
        "disagree_over_1mm_all": sum(
            b["summary"]["instrument_disagreement_mm"]["n_views_over_1mm"] for b in RUN["bodies"]),
        "improvement_ray": med(all_w, "mm_per_px_axis_raycast")
        / med(all_r, "mm_per_px_axis_raycast"),
    }, ensure_ascii=False, indent=1))
    print("\n== timing")
    print(json.dumps({k: v for k, v in TIMING.items() if k != "per_body_seconds"},
                     ensure_ascii=False, indent=1))
    print("\n== extra rung")
    for body in RUN["bodies"]:
        extra = body.get("extra_rung")
        if not extra:
            continue
        records = extra["records"]
        print(json.dumps({
            "vessel": body["body"]["vessel_id"], "long_edge_px": extra["long_edge_px"],
            "seconds": round(extra["seconds"], 1),
            "mm_per_px_ray": med(records, "mm_per_px_axis_raycast"),
            "mm_per_px_centre": med(records, "mm_per_px_at_centre"),
            "rim_px": sum(int(x["rim_px"]) for x in records),
            "delivered": records[0]["delivered_size_px"],
            "f_px_delivered": records[0]["f_px_delivered"],
            "structure_0p2mm_px": 0.2 / med(records, "mm_per_px_axis_raycast"),
        }, ensure_ascii=False))
    print("\n== amplitudes in px (axis-raycast scale)")
    s_w = med(all_w, "mm_per_px_axis_raycast")
    s_r = med(all_r, "mm_per_px_axis_raycast")
    for body in RUN["bodies"]:
        for roi in body["rois"]:
            h = roi["height"]
            print("%-12s %-14s plane Ra %.4f mm -> %.2f px (whole) / %.2f px (roi) | below_5mm %.5f -> %.3f/%.3f px | below_1mm %.3g -> %.3g/%.3g px"
                  % (body["body"]["vessel_id"], roi["roi_id"], h["plane"]["Ra_mm"],
                     h["plane"]["Ra_mm"] / s_w, h["plane"]["Ra_mm"] / s_r,
                     h["bands"]["below_5mm"]["Ra_mm"], h["bands"]["below_5mm"]["Ra_mm"] / s_w,
                     h["bands"]["below_5mm"]["Ra_mm"] / s_r,
                     h["bands"]["below_1mm"]["Ra_mm"], h["bands"]["below_1mm"]["Ra_mm"] / s_w,
                     h["bands"]["below_1mm"]["Ra_mm"] / s_r))


if __name__ == "__main__":
    sys.exit(main())
