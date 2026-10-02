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
    """Measured relief amplitude and lateral scale per variant of one report.

    Two report kinds are accepted:

    * ``field_morphology_*.json`` (``surface_kind = "analytic_field_request"``) -- the modelled
      fracture surface, whose ``roughness_only`` block is the conchoidal bow removed, i.e. the
      signal an ``Ra``/``Rz`` number is supposed to describe;
    * ``fracture_realism_*.json`` -- realized events, per variant.
    """
    out: dict[str, Any] = {"vessel_id": report.get("vessel_id"),
                           "material_id": report.get("material_id"),
                           "source_report": report.get("_source"),
                           "surface_kind": report.get("surface_kind", "realized_event"),
                           "variants": {}}
    if "modelled_surface" in report:
        ms = report["modelled_surface"]
        ro = ms.get("roughness_only") or {}
        out["variants"]["morphology_modelled"] = {
            "status": report.get("status", "OK"),
            "Ra_mm": ro.get("Ra_mm"), "Rz_mm": ro.get("Rz_mm"), "Rt_mm": ro.get("Rt_mm"),
            "correlation_length_mm": ro.get("correlation_length_mm"),
            "ridge_lines_per_mm": ms.get("ridge_lines_per_mm"),
            "measured_area_mm2": (report.get("sampling") or {}).get("core_area_mm2"),
            "form_and_roughness_Ra_mm": ms.get("Ra_mm"),
            "form_and_roughness_Rt_mm": ms.get("Rt_mm"),
            "normal_angle_p95_deg": (ms.get("normals") or {}).get("angle_p95_deg"),
            "curvature_k_p95_per_mm": (ms.get("curvature") or {}).get("k_abs_p95_per_mm"),
            # the lateral resolution limit is the SHORTEST wavelength in the relief, not the
            # correlation length: the correlation length of this model is dominated by the
            # radial hackle pattern (tens of mm) and says nothing about the finest structure.
            "shortest_wavelength_mm": (report.get("field") or {}).get("wavelength_min_mm"),
            "material_correlation_length_mm": (report.get("params") or {}).get(
                "correlation_length_mm"),
        }
        return out
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
              contract_structure_px: float,
              shortest_wavelength_mm: float | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"mm_per_px": mm_per_px,
                           "contract_structure_0p2mm_px": contract_structure_px}
    if shortest_wavelength_mm:
        row["px_per_shortest_wavelength"] = shortest_wavelength_mm / mm_per_px
        row["shortest_wavelength_resolved_contract_4px"] = (
            row["px_per_shortest_wavelength"] >= MIN_PX_PER_FEATURE)
        row["shortest_wavelength_above_nyquist"] = (
            row["px_per_shortest_wavelength"] >= NYQUIST_PX)
    else:
        row["px_per_shortest_wavelength"] = None
        row["shortest_wavelength_resolved_contract_4px"] = False
        row["shortest_wavelength_above_nyquist"] = False
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
    row["can_see_feature"] = bool(row["lateral_resolved_contract_4px"] and row["amplitude_visible"]
                                  and row["shortest_wavelength_resolved_contract_4px"])
    row["sees_amplitude_and_correlation"] = bool(row["lateral_resolved_contract_4px"]
                                                 and row["amplitude_visible"])
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
                "shortest_wavelength_mm": feat.get("shortest_wavelength_mm"),
                "material_correlation_length_mm": feat.get("material_correlation_length_mm"),
                "peak_to_valley_mm": feat["Rt_mm"],
                "Ra_mm": feat["Ra_mm"],
                "Rz_mm": feat["Rz_mm"],
                "rows": [table_for(r["mm_per_px"],
                                   correlation_length_mm=feat["correlation_length_mm"],
                                   peak_to_valley_mm=feat["Rt_mm"],
                                   noise_floor_mm=noise_floor,
                                   contract_structure_px=r["contract_structure_0p2mm_px"],
                                   shortest_wavelength_mm=feat.get("shortest_wavelength_mm"))
                         for r in rungs],
            }
            entry["tables"][label]["visible_rung_count"] = int(sum(
                1 for row in entry["tables"][label]["rows"] if row["can_see_feature"]))
            entry["tables"][label]["visible_rung_count_amplitude_and_correlation"] = int(sum(
                1 for row in entry["tables"][label]["rows"]
                if row["sees_amplitude_and_correlation"]))
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
                  f"lambda_min={table.get('shortest_wavelength_mm')} "
                  f"visible(amp+lc)={table['visible_rung_count_amplitude_and_correlation']}/5 "
                  f"visible(amp+lc+lam)={table['visible_rung_count']}/5")
            for row in table["rows"]:
                lam = row["px_per_shortest_wavelength"]
                lam_text = f"{lam:.2f} px/lam_min" if lam is not None else "n/a (no relief)"
                lc_px = row["px_per_correlation_length"]
                lc_text = f"{lc_px:.2f} px/lc" if lc_px is not None else "n/a"
                print(f"    {row['mm_per_px']:.3f} mm/px -> {lc_text}, {lam_text}, "
                      f"amp/floor={row['amplitude_over_noise_floor']:.3f}, "
                      f"see={row['can_see_feature']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
