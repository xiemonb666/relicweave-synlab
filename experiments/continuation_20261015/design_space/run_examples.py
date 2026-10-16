"""Build reproducible A12 design-space examples and save measured mesh inputs.

Run from the repository root with the synlab virtual environment:
    relicweave-synlab/.venv/Scripts/python.exe \
      relicweave-synlab/experiments/continuation_20261015/design_space/run_examples.py

The saved meshes are synthetic controls. They do not represent source-measured objects.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[5]
SYNLAB_ROOT = REPO_ROOT / "relicweave-synlab"
if str(SYNLAB_ROOT) not in sys.path:
    sys.path.insert(0, str(SYNLAB_ROOT))

from synlab.mothers.design_space import build_designed_mother, parameter_space  # noqa: E402
from synlab.mothers.api import geometry_hash  # noqa: E402


OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
MESH_DIR = OUTPUT_DIR / "mesh_arrays"

EXAMPLES: dict[str, dict[str, dict[str, Any]]] = {
    "V01": {
        "default": {},
        "deeper_profile": {"depth_ratio": 0.62},
        "rim_flare": {"rim_flare": 0.35},
    },
    "V04": {
        "default": {},
        "thicker_handle": {"handle_thickness_mm": 11.0},
        "without_handle": {"with_handle": False},
    },
    "V06": {
        "default": {},
        "higher_shoulder": {"shoulder_position": 0.78},
        "wider_mouth": {"mouth_ratio": 0.78},
    },
    "V09": {
        "default": {},
        "longer_spout": {"spout_length_mm": 145.0},
        "steeper_spout": {"spout_angle_deg": 55.0},
    },
}


def main() -> None:
    MESH_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for vessel_id, cases in EXAMPLES.items():
        space = parameter_space(vessel_id)
        declared = {item["name"] for item in space["parameters"]}
        type_fields = set(space["type_specific_parameters"])
        for case_name, overrides in cases.items():
            if case_name != "default":
                requested_fields = set(overrides)
                if not requested_fields <= declared:
                    raise RuntimeError(f"{vessel_id}/{case_name}: unknown fields {requested_fields - declared}")
                if len(requested_fields & type_fields) == 0:
                    raise RuntimeError(f"{vessel_id}/{case_name}: no catalogue-unique field varied")
            result = build_designed_mother(
                vessel_id,
                overrides=overrides,
                seed=20261015,
                mother_id=f"design-space-{vessel_id}-{case_name}",
            )
            mesh = result.mother.mesh
            stem = f"{vessel_id}_{case_name}"
            np.savez_compressed(
                MESH_DIR / f"{stem}.npz",
                vertices=np.asarray(mesh.vertices, dtype=np.float64),
                faces=np.asarray(mesh.faces, dtype=np.int32),
            )
            records.append({
                "vessel_id": vessel_id,
                "case": case_name,
                "requested_overrides": dict(overrides),
                "resolved_canonical_values": result.resolved_canonical_values,
                "realized_values": result.realized_values,
                "parameter_adjustments": result.parameter_adjustments,
                "bounds_mm": np.asarray(mesh.bounds, dtype=float).tolist(),
                "volume_mm3": float(result.mother.volume_mm3),
                "geometry_hash": geometry_hash(mesh),
                "vertex_count": int(len(mesh.vertices)),
                "face_count": int(len(mesh.faces)),
                "source_class": "SYNTHETIC_CONTROL",
                "validation_status": "PARAMETRIC_CANDIDATE",
                "real_world_validation": "NOT_ESTABLISHED",
                "archaeological_attribution": False,
            })

    payload = {
        "schema": "a12_design_space_examples.v1",
        "description": "Fixed-seed same-type parameter perturbations over existing registered A12 models.",
        "seed": 20261015,
        "evidence_boundary": {
            "source_dimensions": None,
            "visual_style": None,
            "generator_assumption": "existing registry families and construction builders",
            "no_real_object_match_claimed": True,
        },
        "examples": records,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(records)} measured examples to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
