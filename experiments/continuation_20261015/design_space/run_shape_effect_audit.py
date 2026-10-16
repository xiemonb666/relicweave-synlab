"""Record fixed-seed behavior probes for known shape-field metadata mismatches."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
SYNLAB_ROOT = REPO_ROOT / "relicweave-synlab"
if str(SYNLAB_ROOT) not in sys.path:
    sys.path.insert(0, str(SYNLAB_ROOT))

from synlab.mothers.design_space import probe_parameter_effect  # noqa: E402


PROBES = (
    ("V01", "warp_amplitude", 0.0, None),
    ("V01", "warp_eccentricity_mm", 0.0, None),
    ("V01", "warp_lobes", 6, None),
    ("V04", "with_handle", False, None),
    ("V18", "groove_width_mm", 14.0, None),
    ("V18", "hole_diameter_mm", 14.0, {"aeration_holes": 4}),
    ("V23", "diameter_mm", 280.0, None),
    ("V23", "wall_mm", 8.0, None),
    ("V23", "base_mm", 12.0, None),
)


def main() -> None:
    rows = []
    for vessel_id, parameter, value, base_params in PROBES:
        row = probe_parameter_effect(vessel_id, parameter, value,
                                     base_params=base_params, seed=81)
        row["base_params"] = base_params or {}
        rows.append(row)
    payload = {
        "schema": "a12_shape_effect_probe_audit.v1",
        "seed": 81,
        "method": "same-seed baseline and single-parameter variant using existing create_mother",
        "limitations": [
            "Mesh effect is measured for the supplied parameter value and base parameters only.",
            "No effect at one value does not prove a field is globally inert; fields may be conditional.",
            "The probe does not establish source, daily-use, archaeological or physical validity.",
        ],
        "probes": rows,
    }
    output = Path(__file__).resolve().parent / "outputs" / "shape_effect_probes.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(f"wrote {len(rows)} behavior probes to {output}")


if __name__ == "__main__":
    main()
