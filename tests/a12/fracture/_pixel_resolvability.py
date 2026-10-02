#!/usr/bin/env python
"""Pixel resolvability of the *measured* fracture relief on the scanning-desk mm/px ladder.

Input: one or more ``fracture_realism_*.json`` reports written by
``tests/a12/fracture/_measure_fracture_realism.py``.
Output: ``data/a12_reports/morph_pixel_resolvability.json``.

Criteria are the capture contract's own (``configs/a12/capture_contract.json``), not invented here:

* ``working_distance_and_resolution.resolution_table`` -> the mm/px ladder and the contract's own
  worked example (``structure_0p2mm_px``: how many pixels a 0.2 mm structure spans).
* ``working_distance_and_resolution.structure_sampling_targets.pilot_start`` -> "0.2 mm structure,
  >= 4 px"; ``detail_goal`` -> 6-8 px.  So a lateral feature of scale ``L`` is *laterally resolved*
  when ``L / mm_per_px >= 4``.
* ``mask_and_quality.quality_3d_floor_q2_equivalent.sigma_max_mm`` = 0.2 mm, the contract's Q2 3D
  scatter floor (the contract itself flags this block ``confidence: assumption``).  Relief whose
  peak-to-valley does not clear that floor cannot be separated from the acquisition's own scatter.

Two independent gates are therefore reported per ladder rung, and a rung counts as "can see the
feature" only when both hold.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: the contract's pilot sampling target: >= 4 px across a 0.2 mm structure
MIN_PX_PER_FEATURE = 4.0
#: Nyquist floor for the lateral scale (reported next to the contract target, not instead of it)
NYQUIST_PX = 2.0


def load_contract() -> dict[str, Any]:
    return json.loads((REPO_ROOT / "configs" / "a12" / "capture_contract.json")
                      .read_text(encoding="utf-8"))


def ladder(contract: dict[str, Any]) -> list[dict[str, float]]:
    rows = contract["working_distance_and_resolution"]["resolution_table"]["rows"]
    return [{"distance_mm": float(r["distance_mm"]), "mm_per_px": float(r["mm_per_px"]),
             "contract_structure_0p2mm_px": float(r["structure_0p2mm_px"])} for r in rows]


def measure_features(report: dict[str, Any]) -> dict[str, Any]:
    """Measured relief amplitude and lateral scale per variant of one report."""
    out: dict[str, Any] = {"vessel_id": report.get("vessel_id"),
                           "material_id": report.get("material_id"),
                           "source_report": report.get("_source"), "variants": {}}
    for label, block in (report.get("variants") or {}).items():
        if not isinstance(block, dict) or block.get("status") != "OK":
            out["variants"][label] = {"status": (block or {}).get("status", "MISSING"),
                                      "error_code": ((block or {}).get("error") or {}).get("code")}
            continue
        delivered = block.get("delivered") or {}
        out["variants"][label] = {
            "status": "OK",
            "Ra_mm": delivered.get("Ra_mm"),
            "Rz_mm": delivered.get("Rz_mm"),
            "Rt_mm": delivered.get("Rt_mm"),
            "correlation_length_mm": delivered.get("correlation_length_mm"),
            "ridge_lines_per_mm": delivered.get("ridge_lines_per_mm"),
            "measured_area_mm2": delivered.get("measured_area_mm2"),
        }
    return out


def table_for(mm_per_px: float, *, correlation_length_mm: float | None,
              peak_to_valley_mm: float | None, noise_floor_mm: float,
              contract_structure_px: float) -> dict[str, Any]:
    row: dict[str, Any] = {"mm_per_px": mm_per_px,
                           "contract_structure_0p2mm_px": contract_structure_px}
    if correlation_length_mm:
        row["px_per_correlation_length"] = correlation_length_mm / mm_per_px
        row["lateral_resolved_contract_4px"] = row["px_per_correlation_length"] >= MIN_PX_PER_FEATURE
        row["lateral_resolved_nyquist_2px"] = row["px_per_correlation_length"] >= NYQUIST_PX
    else:
        row["px_per_correlation_length"] = None
        row["lateral_resolved_contract_4px"] = False
        row["lateral_resolved_nyquist_2px"] = False
    if peak_to_valley_mm is not None:
        row["amplitude_over_noise_floor"] = peak_to_valley_mm / noise_floor_mm
        row["amplitude_visible"] = peak_to_valley_mm > noise_floor_mm
    else:
        row["amplitude_over_noise_floor"] = None
        row["amplitude_visible"] = False
    row["can_see_feature"] = bool(row["lateral_resolved_contract_4px"] and row["amplitude_visible"])
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", nargs="+", required=True)
    parser.add_argument("--out", default="data/a12_reports/morph_pixel_resolvability.json")
    args = parser.parse_args()

    contract = load_contract()
    rungs = ladder(contract)
    noise_floor = float(contract["mask_and_quality"]["quality_3d_floor_q2_equivalent"]
                        ["sigma_max_mm"])
    sampling = contract["working_distance_and_resolution"]["structure_sampling_targets"]
    target_note = f"{sampling['pilot_start']['spec']} / detail {sampling['detail_goal']['spec']}"
    q2 = contract["mask_and_quality"]["quality_3d_floor_q2_equivalent"]

    payload: dict[str, Any] = {
        "criteria": {
            "source": "configs/a12/capture_contract.json",
            "ladder_rows": rungs,
            "min_px_per_feature_contract": MIN_PX_PER_FEATURE,
            "nyquist_px": NYQUIST_PX,
            "amplitude_noise_floor_mm": noise_floor,
            "noise_floor_block": "mask_and_quality.quality_3d_floor_q2_equivalent",
            "noise_floor_contract_confidence": q2.get("confidence", "unspecified"),
            "contract_sampling_targets": target_note,
            "rule": ("a rung can see the feature only when the correlation length spans >= 4 px "
                     "(the contract's own pilot target for a 0.2 mm structure) AND the measured "
                     "peak-to-valley clears the contract's 0.2 mm Q2 3D scatter floor"),
        },
        "reports": [],
    }

    for path in args.reports:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        report["_source"] = path
        features = measure_features(report)
        entry: dict[str, Any] = {"source": path, **features, "tables": {}}
        for label, feat in features["variants"].items():
            if feat.get("status") != "OK":
                entry["tables"][label] = {"status": feat.get("status"),
                                          "error_code": feat.get("error_code")}
                continue
            entry["tables"][label] = {
                "correlation_length_mm": feat["correlation_length_mm"],
                "peak_to_valley_mm": feat["Rt_mm"],
                "Ra_mm": feat["Ra_mm"],
                "Rz_mm": feat["Rz_mm"],
                "rows": [table_for(r["mm_per_px"],
                                   correlation_length_mm=feat["correlation_length_mm"],
                                   peak_to_valley_mm=feat["Rt_mm"],
                                   noise_floor_mm=noise_floor,
                                   contract_structure_px=r["contract_structure_0p2mm_px"])
                         for r in rungs],
            }
            entry["tables"][label]["visible_rung_count"] = int(sum(
                1 for row in entry["tables"][label]["rows"] if row["can_see_feature"]))
        payload["reports"].append(entry)

    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[written] {out}")
    for entry in payload["reports"]:
        for label, table in entry["tables"].items():
            if table.get("status"):
                print(f"  {entry['vessel_id']}/{entry['material_id']} {label}: "
                      f"{table['status']} {table.get('error_code')}")
                continue
            print(f"  {entry['vessel_id']}/{entry['material_id']} {label}: "
                  f"lc={table['correlation_length_mm']:.4f}mm Rt={table['peak_to_valley_mm']:.5f}mm "
                  f"visible rungs={table['visible_rung_count']}/5")
            for row in table["rows"]:
                print(f"    {row['mm_per_px']:.3f} mm/px -> "
                      f"{row['px_per_correlation_length']:.2f} px/lc, "
                      f"amp/floor={row['amplitude_over_noise_floor']:.3f}, "
                      f"see={row['can_see_feature']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
