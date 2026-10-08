"""Scratch: print the run tables needed for docs/a12/synthetic_extras.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parent

run = json.loads((REPO / "data" / "a12_reports" / "synthetic_extras_run.json")
                 .read_text(encoding="utf-8"))
verify = json.loads((REPO / "_tmp_extras_verify.json").read_text(encoding="utf-8"))

print("== loaders ==")
for key, value in verify.items():
    if key.startswith("load_package") or key == "load_extras::check":
        print(f"  {key}: exit {value['exit']}")
print("  load_extras::list totals:", verify["load_extras::list"]["totals"])

print("\n== per modality ==")
print(f"{'modality':<28}{'n':>3}{'file_B':>10}{'array_B':>11}{'sec':>9}{'arrays':>7}")
for mid, entry in run["per_modality"].items():
    secs = run["export"]["generate_seconds"].get(mid, 0.0)
    print(f"{mid:<28}{entry['instances']:>3}{entry['file_bytes']:>10}"
          f"{entry['array_bytes']:>11}{secs:>9.2f}{len(entry['arrays']):>7}")

print("\n== per modality arrays (one instance) ==")
for mid, entry in run["per_modality"].items():
    print(f"-- {mid}")
    for name, meta in sorted(entry["arrays"].items()):
        print(f"   {name:<34}{str(meta['shape']):<22}{meta['dtype']:<10}{meta['bytes']:>9}")

print("\n== annotation fields ==")
for mid, ann in run["annotation_fields"].items():
    print(f"{mid:<28} rig_obtainable={ann['rig_obtainable']} "
          f"synthetic_only={ann['synthetic_only']} rig_source={ann['rig_source']!r} "
          f"claim_allowed={ann['claim_allowed']} unit={ann['unit']} frame={ann['frame']} "
          f"seconds={ann['seconds']}")

print("\n== key measured numbers ==")
for row in json.loads((REPO / "data" / "a12_exports" / "a12_extras" / "synthetic_extra"
                       / "index.json").read_text(encoding="utf-8"))["rows"].values():
    ann = row["annotation"]
    keys = ("ps_vs_geom_angle_median_deg", "ps_valid_fraction", "n_angles",
            "angle_range_deg", "declared_accuracy_mm", "realised_max_residual_mm",
            "baseline_mm", "disparity_median_px", "depth_source",
            "cross_check_max_delta_mm", "silhouette_valid_fraction", "n_views",
            "sweep_deg", "wraps", "pairs", "front_back_overlap_iou", "calibrated",
            "calibration_source", "roundtrip_max_residual_mm", "reference_present",
            "reference_asset_id", "present")
    picked = {k: ann.get(k) for k in keys if ann.get(k) is not None}
    print(row["fragment_id"], row["modality_id"], json.dumps(picked, ensure_ascii=False))

print("\n== channel diff ==")
print(json.dumps(verify["channel_diff"], ensure_ascii=False, indent=1)[:1500])
print("\n== isolation ==")
print(json.dumps(run["export"]["isolation"], ensure_ascii=False, indent=1))
print("\n== fragment sources ==")
print(json.dumps(run["export"]["resolved_targets"], ensure_ascii=False, indent=1))
