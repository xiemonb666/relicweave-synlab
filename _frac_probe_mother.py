"""Probe: build a real mother (V01/M01), report geometry, thickness and material facts."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "_frac_probe_mother.json"


def main() -> int:
    from synlab.mothers.api import audit_mother, create_mother, default_params, ensure_registered

    ensure_registered()
    report: dict = {"vessels": {}}
    for vessel in ("V01", "V02", "V04", "V13", "V18"):
        t0 = time.perf_counter()
        try:
            params = default_params(vessel)
            mother = create_mother(vessel, "M01", params, np.random.default_rng(20261002))
        except Exception as exc:  # noqa: BLE001
            report["vessels"][vessel] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        mesh = mother.mesh
        entry: dict = {
            "build_s": round(time.perf_counter() - t0, 3),
            "faces": int(len(mesh.faces)),
            "vertices": int(len(mesh.vertices)),
            "watertight": bool(mesh.is_watertight),
            "volume_mm3": float(abs(mesh.volume)),
            "area_mm2": float(mesh.area),
            "extents_mm": [float(x) for x in mesh.extents],
            "bounds": np.asarray(mesh.bounds, dtype=float).tolist(),
            "material_id": getattr(mother, "material_id", None),
            "mother_id": getattr(mother, "mother_id", None),
            "meta_keys": sorted((getattr(mother, "meta", {}) or {}).keys()),
        }
        try:
            audit = audit_mother(mother, max_thickness_probes=200)
            entry["audit"] = {
                k: v for k, v in audit.items()
                if isinstance(v, (int, float, str, bool)) or (isinstance(v, list) and len(v) < 12)
            }
        except Exception as exc:  # noqa: BLE001
            entry["audit_error"] = f"{type(exc).__name__}: {exc}"
        report["vessels"][vessel] = entry
        print(vessel, entry.get("faces"), entry.get("watertight"), entry.get("extents_mm"),
              flush=True)

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
