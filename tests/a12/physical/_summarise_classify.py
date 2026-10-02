"""Summarise the classifier retrofit probe JSON into the table used by the docs."""
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                    else "data/a12/reports/fracture_surface_signal/probe_classify_origin_4.json")
doc = json.loads(path.read_text(encoding="utf-8"))
for lineage, entry in doc["lineages"].items():
    key = next(k for k in entry["sweep"] if k.startswith(f"tol={entry['rule_tol_mm']:.4f}"))
    report = entry["sweep"][key]
    total = sum(report["classes"].values())
    print(f"{lineage}: clean_faces={entry['clean_faces']} "
          f"clean_roi_area_frac={entry['clean_roi_area_fraction'] * 100:.3f}% "
          f"damaged={entry['damaged_faces']} tol={report['tol_mm']:.4f} "
          f"band={report['roi_band_mm']:.3f}")
    print("   classes:", report["classes"],
          {k: round(v / total * 100, 3) for k, v in report["classes"].items()})
    print("   area_fraction:",
          {k: round(v * 100, 3) for k, v in report["class_area_fraction"].items()},
          "mapped_frac:", round(report["mapped_fraction"] * 100, 3),
          "born_in_roi:", report["born_in_declared_roi"],
          "inherited:", report["inherited_origin_histogram"],
          "reasons:", report["ambiguous_reasons"])
    print("   distance_mm:", {k: round(v, 6) if isinstance(v, float) else v
                              for k, v in report["distance_mm"].items()})
