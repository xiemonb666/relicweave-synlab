"""precision audit probe 09 - degradation applied-vs-declared error (dimension 5).

Read only: consumes ``precision_probe_07_degrade_audit.json`` (produced by
``synlab.degrade.api.audit_all_axes(None, levels=[0,1,2,3,4])``) and, for every axis level,
pairs the ``planned_*`` declaration with the independent ``measured_*`` verification
quantity of the same physical unit, computing the absolute and relative error.

The mapping "which measured_* quantity verifies which planned_* quantity" is declared in
``PAIRS`` below and is printed in the output so the correspondence is auditable.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]

#: planned parameter -> (measured verification key, unit, relative-to)
PAIRS: dict[str, tuple[str, str]] = {
    "P02": ("planned_max_recession_mm", "measured_measured_max_recession_mm", "mm"),
    "P03": ("planned_depth_mm", "measured_applied_depth_mm", "mm"),
    "P04": ("planned_contact_loss_target", "measured_achieved_contact_loss", "ratio"),
    "P07": ("planned_depth_mm", "measured_realized_max_recession_mm", "mm"),
    "P08": ("planned_affected_area", "measured_achieved_affected_area_fraction", "ratio"),
    "G01": ("planned_target_rms_mm", "measured_applied_rms_mm", "mm"),
    "G02": ("planned_keep_fraction", "measured_kept_fraction", "ratio"),
    "G03": ("planned_retained_coverage", "measured_retained_coverage", "ratio"),
    "G04": ("planned_translation_mm", "measured_realized_translation_mm", "mm"),
    "G05": ("planned_max_error_mm", "measured_realized_max_error_mm", "mm"),
    "G06": ("planned_ratio_error", "measured_measured_ratio", "ratio (+1)"),
    "G07": ("planned_focal_ratio", "measured_measured_focal_ratio", "ratio"),
    "G08": ("planned_height_mm", "measured_measured_max_displacement_mm", "mm"),
    "I01": ("planned_psf_sigma_px", "measured_measured_psf_sigma_px", "px"),
    "I02": ("planned_length_px", "measured_measured_length_px", "px"),
    "I03": ("planned_read_sigma", "measured_measured_read_sigma", "sigma"),
    "I04": ("planned_exposure_ev", "measured_measured_exposure_ev", "EV"),
    "I05": ("planned_wb_deviation", "measured_measured_wb_deviation", "ratio"),
    "I06": ("planned_saturation_target", "measured_measured_saturation_target", "ratio"),
    "I07": ("planned_target_coverage", "measured_measured_target_coverage", "ratio"),
    "I08": ("planned_keep_fraction", "measured_measured_keep_fraction", "ratio"),
    "I09": ("planned_resize_scale", "measured_measured_resize_scale", "ratio"),
    "I10": ("planned_jpeg_quality", "measured_measured_jpeg_quality", "quality"),
    "X01": ("planned_missing_rate", "measured_measured_missing_rate", "ratio"),
    "X02": ("planned_boundary_px", "measured_measured_boundary_px", "px"),
    "X03": ("planned_missing_rate", "measured_measured_missing_rate", "ratio"),
    "X04": ("planned_bias_sigma", "measured_measured_mean_shift", "sigma"),
    "X05": ("planned_preset_index", "measured_measured_preset_index", "index"),
}


def num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", default="data/a12/reports/precision_probe_07_degrade_audit.json")
    ap.add_argument("--out", default="data/a12/reports/precision_probe_09_degrade_error.json")
    args = ap.parse_args()

    src = json.loads((ROOT / args.audit).read_text(encoding="utf-8"))
    ms = src["measurements"]

    per_axis: dict[str, list] = {}
    level0 = []
    for m in ms:
        ax = m["axis_id"]
        per_axis.setdefault(ax, []).append(m)
        if int(m.get("level", -1)) == 0:
            level0.append({"axis_id": ax, "variant": m.get("variant"),
                           "identity": m.get("identity"), "status": m.get("status"),
                           "source_hash": m.get("source_hash"),
                           "result_hash": m.get("result_hash"),
                           "hash_equal": m.get("source_hash") == m.get("result_hash"),
                           "result_asset_id": m.get("result_asset_id")})

    rows = []
    for ax, recs in sorted(per_axis.items()):
        pair = PAIRS.get(ax)
        for m in sorted(recs, key=lambda r: int(r.get("level", 0))):
            lvl = int(m.get("level", 0))
            row = {"axis_id": ax, "level": lvl, "variant": m.get("variant"),
                   "status": m.get("status"), "identity": m.get("identity"),
                   "realized": m.get("realized"), "na_reason": m.get("na_reason"),
                   "failure_code": m.get("failure_code")}
            if pair:
                pk, mk, unit = pair
                planned = num(m.get(pk))
                measured = num(m.get(mk))
                if ax == "G06" and measured is not None:
                    measured = measured - 1.0      # measured_measured_ratio == 1 + ratio_error
                if ax == "G07" and measured is None:
                    # the audit writes the realised focal ratio under a different key for the
                    # focal_only variant; derive it from the before/after pixel focal lengths
                    fb, fa = num(m.get("measured_focal_before_px")), num(m.get("measured_focal_after_px"))
                    if fb and fa:
                        measured = (fa - fb) / fb
                        mk = "measured_focal_after_px/before_px - 1"
                row.update({"planned_key": pk, "measured_key": mk, "unit": unit,
                            "planned": planned, "measured": measured})
                if planned is not None and measured is not None:
                    row["abs_error"] = abs(measured - planned)
                    row["rel_error"] = (abs(measured - planned) / abs(planned)
                                        if abs(planned) > 0 else None)
            else:
                # no declared pair: dump the planned_*/measured_* keys verbatim
                row["planned_keys"] = sorted(k for k in m if k.startswith("planned_"))
                row["measured_keys"] = sorted(k for k in m if k.startswith("measured_"))
            rows.append(row)

    matched = [r for r in rows if r.get("abs_error") is not None]
    worst = sorted(matched, key=lambda r: -r["abs_error"])[:12]
    summary = {
        "n_levels": len(rows),
        "n_levels_with_paired_quantity": len(matched),
        "n_axes_with_paired_quantity": len({r["axis_id"] for r in matched}),
        "max_abs_error": max((r["abs_error"] for r in matched), default=None),
        "max_rel_error": max((r["rel_error"] for r in matched
                              if r.get("rel_error") is not None), default=None),
        "n_rel_error_gt_1pct": int(sum(1 for r in matched
                                       if (r.get("rel_error") or 0.0) > 0.01)),
        "level0_n": len(level0),
        "level0_identity_all_true": all(bool(r["identity"]) for r in level0),
        "level0_hash_equal_all": all(bool(r["hash_equal"]) for r in level0),
        "level0_failures": [r for r in level0 if not (r["identity"] and r["hash_equal"])],
        "denominators": src.get("denominators"),
        "limits": src.get("limits"),
        "pair_definition": {k: list(v) for k, v in PAIRS.items()},
    }
    out = {"summary": summary, "worst_abs_error": worst, "unpaired_axes":
           sorted({r["axis_id"] for r in rows if "planned" not in r}),
           "rows": rows, "level0": level0}
    (ROOT / args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote", args.out)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("unpaired axes:", out["unpaired_axes"])
    for r in worst:
        print("worst:", json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
