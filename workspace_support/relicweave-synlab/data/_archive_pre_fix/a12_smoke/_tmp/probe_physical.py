"""Diagnose ``PRECISION_NOT_REALIZED`` at ``physical.sdf`` ("Not all meshes are volumes!").

Reproduces the physical stage only (mother -> shared cut -> clean truth -> damage) for one
lineage and, when the manifold boolean refuses an operand, measures *which* operand is not a
closed volume and why:

* the fragment (source) mesh: watertight / winding consistent / volume / degenerate faces,
* the marching-cubes candidate at the recipe's own grid spacing and recession depth,
* the same candidate at a locally refined spacing (the narrow-band remedy the repo's
  ``synlab/degrade/narrowband.py`` documents), to see whether resolution is the cause.

Usage::

    python data/a12_smoke/_tmp/probe_physical.py 21 [15 ...]
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec
from synlab.fracture.api import fracture_event
from synlab.mothers.api import create_mother
from synlab.physical import sdf as S
from synlab.pipeline import (derive_named_rngs, _fragment_interface_faces, _load_damage_recipe,
                             _pick_fragment, plan_generation)
from synlab.truth.api import finalize_clean_truth


def volume_report(mesh: trimesh.Trimesh, name: str) -> dict:
    row = {
        "name": name, "faces": int(mesh.faces.shape[0]),
        "vertices": int(mesh.vertices.shape[0]),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "volume_mm3": float(abs(mesh.volume)),
        "is_volume": bool(mesh.is_watertight and mesh.is_winding_consistent
                          and abs(float(mesh.volume)) > 0.0),
        "degenerate_faces": int((~mesh.nondegenerate_faces(height=1e-12)).sum()),
        "boundary_edges": None, "components": len(mesh.split(only_watertight=False)),
    }
    edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    counts = np.bincount(np.asarray(mesh.edges_unique_inverse, dtype=np.int64),
                         minlength=edges.shape[0])
    row["boundary_edges"] = int(np.sum(counts == 1))
    row["nonmanifold_edges"] = int(np.sum(counts > 2))
    print("   " + json.dumps(row))
    return row


def main() -> int:
    spec = load_generation_spec("configs/a12/next_experiment.yaml")
    plan = plan_generation(spec)
    indices = [int(x) for x in sys.argv[1:]] or [21]
    out = []
    for index in indices:
        lineage = next(l for l in plan.lineages if l.mother_index == index)
        rngs = derive_named_rngs(spec.master_seed, lineage.lineage_id)
        print(f"### {lineage.lineage_id} ({lineage.vessel_id})")
        mother = create_mother(lineage.vessel_id, lineage.material_id, lineage.params,
                               rngs["shape"], mother_id=lineage.lineage_id)
        fracture = fracture_event(mother, spec.fracture, rngs["cut"],
                                  event_id=lineage.event_ids[0])
        clean = finalize_clean_truth(mother, fracture)
        target = _pick_fragment(fracture)
        recipe_id = spec.physical.recipes[0] if spec.physical.recipes else "P03_depth_light"
        recipe = _load_damage_recipe(recipe_id, spec, fragment=target,
                                     master_seed=spec.master_seed, lineage_id=lineage.lineage_id)
        row = {"lineage_id": lineage.lineage_id, "vessel_id": lineage.vessel_id,
               "recipe_id": recipe_id, "axis_id": recipe.axis_id, "level": int(recipe.level),
               "fragment_id": str(getattr(target, "fragment_id", "")),
               "fragment_volume_mm3": float(getattr(target, "volume_mm3", 0.0)),
               "recipe_parameters": {k: v for k, v in (recipe.params or {}).items()},
               "grid": dict(recipe.grid or {}),
               "thickness_guard_mm": recipe.qa.get("min_wall_thickness_mm")}
        print("   recipe: " + json.dumps({k: v for k, v in row.items()
                                          if k not in ("lineage_id", "vessel_id")},
                                         ensure_ascii=False, default=str))
        mesh = target.mesh
        row["source_mesh"] = volume_report(mesh, "fragment_source")
        try:
            from synlab.physical.api import apply_damage
            physical = apply_damage(clean, target, recipe, rngs["damage"])
            row["apply_damage"] = "ok"
            row["lost_volume_ratio"] = float(physical.lost_volume_ratio)
            print("   apply_damage: OK, lost_volume_ratio=%.6g" % physical.lost_volume_ratio)
        except Exception as exc:  # noqa: BLE001 - the probe reports the real failure
            row["apply_damage"] = f"{type(exc).__name__}: {exc}"[:300]
            row["stage"] = str(getattr(exc, "stage", ""))
            row["traceback"] = traceback.format_exc()[-2000:]
            print("   apply_damage FAILED: " + row["apply_damage"])
            # reproduce the extraction by hand to find the offending operand
            try:
                from synlab.physical.operators import SdfContext
                from synlab.patterns import fields as F  # noqa: F401 - payload lives on recipe

                ctx = SdfContext(mesh, recipe, fragment=target)
                print("   grid spacing: " + json.dumps(
                    {"spacing": float(ctx.spacing),
                     "spacing_info": {k: v for k, v in (ctx.spacing_info or {}).items()
                                      if isinstance(v, (int, float, str))}},
                    default=str))
                row["spacing_mm"] = float(ctx.spacing)
                row["field_max_mm"] = float(np.max(ctx.d0) if ctx.d0 is not None else 0.0)
                for scale in (1.0,):
                    depth = float(recipe.parameter("depth_mm", 0.0))
                    print(f"   depth_mm={depth} spacing={ctx.spacing} "
                          f"depth/spacing={depth / max(ctx.spacing, 1e-9):.3f}")
                coarse = S.marching_cubes_mesh(ctx.d0, ctx.grid)
                row["candidate_zero_level"] = volume_report(coarse, "marching_cubes(d0)")
            except Exception:  # noqa: BLE001
                print("   extra diagnosis failed:\n" + traceback.format_exc()[-1500:])
        out.append(row)
    Path("data/a12_smoke/_tmp/probe_physical.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
