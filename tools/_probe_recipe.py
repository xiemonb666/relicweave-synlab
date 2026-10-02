"""Probe: does the pipeline's damage-recipe resolver now carry a frozen basis?"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

from synlab.config import load_generation_spec  # noqa: E402
from synlab.pipeline import _load_damage_recipe  # noqa: E402


class _Frag:
    def __init__(self, mesh):
        self.mesh = mesh
        self.fragment_id = "probe_frag"
        self.meta = {"material_id": "M01"}


def main() -> None:
    spec = load_generation_spec("configs/a12/sandbox.yaml")
    mesh = trimesh.creation.box(extents=(30.0, 20.0, 10.0))
    frag = _Frag(mesh)
    out = {}
    for recipe_id in ("P03_depth_light", "P07_erode_outer_light"):
        try:
            recipe = _load_damage_recipe(recipe_id, spec, fragment=frag,
                                         master_seed=spec.master_seed, lineage_id="probe_lin")
            basis_keys = sorted(recipe.basis)
            has_field = "field" in recipe.basis
            field_ok = None
            if has_field:
                from synlab.physical import fields as F

                field = F.FourierField.from_payload(recipe.basis["field"])
                vals = field(mesh.vertices)
                field_ok = {"shape": list(np.asarray(vals).shape),
                            "finite": bool(np.isfinite(vals).all()),
                            "min": float(np.min(vals)), "max": float(np.max(vals))}
            out[recipe_id] = {"ok": True, "axis": recipe.axis_id, "variant": recipe.variant,
                              "level": recipe.level, "params": recipe.params,
                              "basis_keys": basis_keys, "field_ok": field_ok,
                              "basis_source": recipe.meta.get("basis_source"),
                              "min_wall": recipe.qa.get("min_wall_thickness_mm"),
                              "roi": recipe.roi}
        except Exception as exc:  # noqa: BLE001
            import traceback

            out[recipe_id] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                              "traceback": traceback.format_exc()[-1500:]}
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
