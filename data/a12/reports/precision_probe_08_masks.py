"""precision audit probe 08 - mask coverage / CoC instrument (dimension 3).

Read only.  For each view of every ``obs_result`` in one store:

* object pixels (finite depth > 0)
* ``deployment_mask`` pixels and the coverage defined by the store's own
  ``mask_semantics`` instrument (see docs/a12/data_semantics_versions.md 1.3): the
  coverage denominator is the object pixels, not the frame;
* ``uncertain_mask`` count over object pixels;
* CoC in delivered pixels from the thin-lens expression with the v2 (mm x sampling
  density) instrument, and the share of object pixels under the declared 2.0 px
  mark-out.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sqlite3
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]


def coc_px_mm_instrument(z_mm, focus_mm, f_number, f_px, px_per_mm_sensor):
    """Thin-lens CoC, evaluated in mm and converted with D = px per mm of sensor.

    This is the ``coc_units_v2`` instrument documented in
    docs/a12/data_semantics_versions.md 1.3 and implemented in
    ``synlab.observe.render.circle_of_confusion_px``.
    """
    z = np.asarray(z_mm, dtype=np.float64)
    f_mm = f_px / px_per_mm_sensor
    denom = np.maximum(z, 1e-9)
    coc_mm = np.abs(z - focus_mm) / denom * f_mm / float(f_number)
    return coc_mm * px_per_mm_sensor


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/a12_final/store")
    ap.add_argument("--out", default="data/a12/reports/precision_probe_08_masks.json")
    ap.add_argument("--f-number", type=float, default=2.0)
    ap.add_argument("--focal-mm", type=float, default=3.1252012858255296)
    ap.add_argument("--pixel-pitch-mm", type=float, default=0.002442659615453226)
    ap.add_argument("--mark-out-px", type=float, default=2.0)
    args = ap.parse_args()

    db = ROOT / args.store / "metadata.sqlite"
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("SELECT asset_id, meta_json FROM assets WHERE role='obs_result'")
    rows = cur.fetchall()
    con.close()

    per_view = []
    for asset_id, meta_json in rows:
        npz = db.parent / "assets" / asset_id / "arrays.npz"
        if not npz.exists():
            continue
        try:
            mj = json.loads(meta_json)
        except Exception:
            mj = {}
        inner = mj.get("meta", mj)
        with np.load(npz, allow_pickle=False) as z:
            keys = list(z.files)
            vids = sorted({k.split(".")[0] for k in keys if "." in k})
            for vid in vids:
                if f"{vid}.depth_z" not in keys:
                    continue
                depth = np.asarray(z[f"{vid}.depth_z"], dtype=np.float64)
                K = np.asarray(z[f"{vid}.K"], dtype=np.float64)
                dm = (np.asarray(z[f"{vid}.deployment_mask"]).astype(bool)
                      if f"{vid}.deployment_mask" in keys else None)
                um = (np.asarray(z[f"{vid}.uncertain_mask"]).astype(bool)
                      if f"{vid}.uncertain_mask" in keys else None)
                valid = np.isfinite(depth) & (depth > 0)
                n_obj = int(valid.sum())
                if n_obj == 0:
                    continue
                f_px = float(K[0, 0])
                density = 1.0 / args.pixel_pitch_mm
                focus = float(np.median(depth[valid]))
                coc = coc_px_mm_instrument(depth[valid], focus, args.f_number, f_px, density)
                per_view.append({
                    "asset_id": asset_id, "view": vid,
                    "frame_px": int(depth.size), "object_px": n_obj,
                    "object_frac_of_frame": float(valid.mean()),
                    "mask_px": (int(dm.sum()) if dm is not None else None),
                    "coverage_of_object": (float(dm[valid].mean()) if dm is not None else None),
                    "coverage_of_frame": (float(dm.mean()) if dm is not None else None),
                    "uncertain_px_of_object": (int(um[valid].sum()) if um is not None else None),
                    "uncertain_frac_of_object": (float(um[valid].mean()) if um is not None else None),
                    "focus_mm": focus,
                    "coc_px_p50": float(np.median(coc)),
                    "coc_px_p95": float(np.percentile(coc, 95)),
                    "coc_below_markout_frac": float(np.mean(coc < args.mark_out_px)),
                    "mask_semantics": str(inner.get("mask_semantics")
                                          or (inner.get("obs_spec") or {}).get("mask_semantics")),
                })

    def col(k):
        return [v[k] for v in per_view if v.get(k) is not None]

    agg = {
        "n_views": len(per_view),
        "coverage_of_object_mean": float(np.mean(col("coverage_of_object"))) if col("coverage_of_object") else None,
        "coverage_of_object_min": float(np.min(col("coverage_of_object"))) if col("coverage_of_object") else None,
        "coverage_of_object_max": float(np.max(col("coverage_of_object"))) if col("coverage_of_object") else None,
        "coverage_of_frame_mean": float(np.mean(col("coverage_of_frame"))) if col("coverage_of_frame") else None,
        "uncertain_frac_of_object_mean": float(np.mean(col("uncertain_frac_of_object"))) if col("uncertain_frac_of_object") else None,
        "coc_px_p50_median": float(np.median(col("coc_px_p50"))) if col("coc_px_p50") else None,
        "coc_px_p95_median": float(np.median(col("coc_px_p95"))) if col("coc_px_p95") else None,
        "coc_below_markout_frac_mean": float(np.mean(col("coc_below_markout_frac"))) if col("coc_below_markout_frac") else None,
        "coc_below_markout_frac_min": float(np.min(col("coc_below_markout_frac"))) if col("coc_below_markout_frac") else None,
        "n_views_with_full_coc_markout": int(np.sum([1 for v in col("coc_below_markout_frac") if v >= 0.999999])),
        "object_frac_of_frame_mean": float(np.mean(col("object_frac_of_frame"))),
        "mask_semantics_values": sorted({str(v["mask_semantics"]) for v in per_view}),
        "instrument": "coc_units_v2: CoC_mm = |z-focus|/z * f/(N); CoC_px = CoC_mm * D",
        "f_number": args.f_number, "focal_mm": args.focal_mm,
        "pixel_pitch_mm": args.pixel_pitch_mm, "mark_out_px": args.mark_out_px,
    }
    out = {"store": args.store, "aggregate": agg, "per_view": per_view}
    (ROOT / args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote", args.out)
    print(json.dumps(agg, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
