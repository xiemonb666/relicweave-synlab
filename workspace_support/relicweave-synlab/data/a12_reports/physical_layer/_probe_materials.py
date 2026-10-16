"""Probe: material profiles -> fracture appearance inputs (read-only, real code)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synlab.materials import build_material_profile, default_material_params, material_ids  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402
from synlab.fracture import morphology as mo  # noqa: E402

OUT = ROOT / "data/a12_reports/physical_layer/probe_materials.json"

rows = {}
for mid in material_ids():
    try:
        prof = build_material_profile(mid, default_material_params(mid),
                                      make_rng(20261001, f"mat_{mid}", "material"))
    except Exception as exc:  # noqa: BLE001
        rows[mid] = {"error": f"{type(exc).__name__}: {exc}"}
        continue
    stats = dict(prof.get("stats") or {})
    appearance = dict(prof.get("appearance") or {})
    layers = list(prof.get("layers") or [])
    inp = mo.material_fracture_inputs(prof)
    sigma_r0 = mo.GRAIN_RELIEF_FRACTION * max(inp.grain_scale_mm, 1e-3) * (
        1.0 + mo.POROSITY_RELIEF_GAIN * inp.porosity)
    lc = max(inp.correlation_length_mm, 1e-3)
    bands = [lc * (2.0 ** (i - (mo.ROUGHNESS_BANDS - 1) / 2.0))
             for i in range(mo.ROUGHNESS_BANDS)]
    bands = [float(np.clip(b, 0.20, max(4.0 * lc, 0.5))) for b in bands]
    rows[mid] = {
        "material_name": prof.get("material_name"),
        "grain_scale_mm": inp.grain_scale_mm,
        "pore_scale_mm": inp.pore_scale_mm,
        "correlation_length_mm": inp.correlation_length_mm,
        "anisotropy": inp.anisotropy,
        "fiber_period_mm": inp.fiber_period_mm,
        "fiber_amount": inp.fiber_amount,
        "grain_amount": inp.grain_amount,
        "pore_amount": inp.pore_amount,
        "porosity": inp.porosity,
        "pit_radius_mm": inp.pit_radius_mm,
        "appearance_roughness": inp.appearance_roughness,
        "pore_roughness": inp.pore_roughness,
        "glaze_thickness_mm": inp.glaze_thickness_mm,
        "glaze_kind": inp.glaze_kind,
        "transmission": float(appearance.get("transmission") or 0.0),
        "albedo": appearance.get("albedo"),
        "ior": appearance.get("ior"),
        "cut_mode": (stats.get("cut_statistics") or {}).get("mode"),
        "sigma_r0_mm": float(max(sigma_r0, 1e-4)),
        "band_wavelengths_mm": bands,
        "lambda_min_mm": float(min(bands)),
        "layers": [{"layer_id": l.get("layer_id"), "name": l.get("name"),
                    "kind": l.get("kind"), "mode": l.get("mode"),
                    "thickness_mm": l.get("thickness_mm")}
                   for l in layers],
        "notes": str(prof.get("notes", ""))[:200],
    }

OUT.write_text(json.dumps({"rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
print("materials:", len(rows))
for mid, r in rows.items():
    if "error" in r:
        print(mid, "ERROR", r["error"])
    else:
        print(f"{mid} grain={r['grain_scale_mm']:.3f} lc={r['correlation_length_mm']:.3f} "
              f"poro={r['porosity']:.4f} sigma_r0={r['sigma_r0_mm']:.4f} "
              f"lam_min={r['lambda_min_mm']:.3f} fiber={r['fiber_period_mm']:.2f}/"
              f"{r['fiber_amount']:.2f} glaze={r['glaze_thickness_mm']:.3f} "
              f"T={r['transmission']:.2f} mode={r['cut_mode']}")
