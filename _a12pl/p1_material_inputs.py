"""Stage 1 probe: material fracture-input chain for M03 (stoneware) and M07 (glass).

Writes JSON + a human-readable table.  Every number printed comes from a real
``build_material_profile`` call; nothing is synthesised here.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from synlab.fracture.morphology import material_fracture_inputs  # noqa: E402
from synlab.materials.api import (  # noqa: E402
    build_material_profile,
    canonical_material_params,
    default_material_params,
)
from synlab.seeds import make_rng  # noqa: E402

MASTER_SEED = 20261001
OUT = REPO / "data" / "a12_reports" / "physical_layer"
OUT.mkdir(parents=True, exist_ok=True)

FIELDS = [
    "material_id", "grain_scale_mm", "pore_scale_mm", "aggregate_radius_mm",
    "correlation_length_mm", "anisotropy", "fiber_period_mm", "fiber_direction",
    "fiber_amount", "grain_amount", "pore_amount", "aggregate_amount",
    "appearance_roughness", "pore_roughness", "glaze_thickness_mm", "glaze_kind",
    "porosity", "pit_radius_mm", "source",
]


def main() -> int:
    report = {"master_seed": MASTER_SEED, "materials": {}}
    failures = []
    for material_id in ("M03", "M07"):
        row = {}
        try:
            params = default_material_params(material_id)
            canonical = canonical_material_params(material_id, params)
            rng = make_rng(MASTER_SEED, "physical_layer", "materials", material_id)
            profile = build_material_profile(material_id, params, rng)
            inputs = material_fracture_inputs(profile, material_id=material_id)
            row["params"] = canonical
            row["profile_stats"] = profile.get("stats")
            row["profile_appearance"] = profile.get("appearance")
            row["profile_layers"] = profile.get("layers")
            row["profile_keys"] = sorted(profile.keys())
            row["stats_keys"] = sorted((profile.get("stats") or {}).keys())
            row["appearance_keys"] = sorted((profile.get("appearance") or {}).keys())
            row["inputs"] = inputs.as_dict()
            row["inputs_no_material_id_kwarg"] = material_fracture_inputs(profile).as_dict()
            # which of the extracted values are non-zero?
            row["nonzero_fields"] = sorted(k for k, v in inputs.as_dict().items()
                                           if isinstance(v, (int, float)) and float(v) != 0.0)
            row["zero_numeric_fields"] = sorted(
                k for k, v in inputs.as_dict().items()
                if isinstance(v, (int, float)) and float(v) == 0.0)
            row["status"] = "OK"
        except BaseException as exc:  # noqa: BLE001 - a failure is a measurement
            row["status"] = "FAILED"
            row["error"] = {"type": type(exc).__name__, "message": str(exc)[:400],
                            "traceback_tail": traceback.format_exc()[-1200:]}
            failures.append(f"{material_id}: {type(exc).__name__}: {exc}")
        report["materials"][material_id] = row
        print(f"[{material_id}] {row['status']}", flush=True)
        if row["status"] == "OK":
            print(f"    stats      = {json.dumps(row['profile_stats'], ensure_ascii=False)}")
            print(f"    appearance = {json.dumps(row['profile_appearance'], ensure_ascii=False)}")
            print(f"    layers     = {json.dumps(row['profile_layers'], ensure_ascii=False)}")
            print(f"    nonzero    = {row['nonzero_fields']}")
            print(f"    zero       = {row['zero_numeric_fields']}")

    # ---- difference table
    print()
    print("=" * 108)
    print(f"{'field':<26} {'M03 炻器':>22} {'M07 玻璃':>22}  {'differ?':>8}")
    print("=" * 108)
    m03 = report["materials"].get("M03", {}).get("inputs", {})
    m07 = report["materials"].get("M07", {}).get("inputs", {})
    table = []
    for field in FIELDS:
        a, b = m03.get(field), m07.get(field)
        if isinstance(a, list):
            a = json.dumps(a)
        if isinstance(b, list):
            b = json.dumps(b)
        differ = a != b
        table.append({"field": field, "M03": a, "M07": b, "differ": bool(differ)})
        fmt = (lambda v: f"{v:>22.6f}" if isinstance(v, float)
               else f"{str(v):>22}")
        print(f"{field:<26} {fmt(a)} {fmt(b)}  {str(differ):>8}")
    report["difference_table"] = table
    differing = [row for row in table if row["differ"]]
    report["differing_field_count"] = len(differing)
    report["identical_field_count"] = len(table) - len(differing)
    print("=" * 108)
    print(f"differing fields: {len(differing)} / {len(table)}")

    print()
    print("--- derived physical drivers (evaluated on the extracted inputs) ---")
    for material_id in ("M03", "M07"):
        inp = report["materials"].get(material_id, {}).get("inputs")
        if not inp:
            continue
        porosity = float(inp["porosity"])
        sigma = 90.0 * float(np.exp(-4.5 * porosity)) * (5.0 / 2.47) ** (1.0 / 9.0)
        r_mirror = ((2.5 / sigma) * np.sqrt(1000.0)) ** 2
        p = {"porosity": porosity, "sigma_f_mpa_at_wall_p05_2p47": float(sigma),
             "r_mirror_mm": float(r_mirror),
             "sigma_r0_mm": float(0.12 * max(inp["grain_scale_mm"], 1e-3)
                                  * (1.0 + 2.0 * porosity))}
        report["materials"][material_id]["derived_preview"] = p
        print(f"[{material_id}] {json.dumps(p)}")

    (OUT / "p1_material_inputs.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[written] {OUT / 'p1_material_inputs.json'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
