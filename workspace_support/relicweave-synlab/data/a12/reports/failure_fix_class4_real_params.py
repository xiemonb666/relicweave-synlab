"""Reproduce the post-fix observation-stage ``IndexError`` with the plan's *real* parameters.

``data/a12/reports/failure_fix_plan_drift.json`` holds the 120-target plan of the current working
tree, whose parameters match the running batch's committed mothers 20/20.  This script replays
``LIN0016_V19_M04_PAT08`` with those parameters through the real chain (mother, pattern, fracture,
clean truth, physical, observe) and prints the traceback of the stage that fails.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.config import load_generation_spec  # noqa: E402
from synlab.fracture.api import fracture_event  # noqa: E402
from synlab.mothers.api import create_mother  # noqa: E402
from synlab.physical.api import apply_damage  # noqa: E402
from synlab.pipeline import _build_pattern_recipe, _load_damage_recipe, _pick_fragment, _resolve_observe_spec  # noqa: E402
from synlab.seeds import derive_named_rngs  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402
from synlab.truth.api import finalize_clean_truth  # noqa: E402

LIN = "LIN0016_V19_M04_PAT08"
DRIFT = ROOT / "data" / "a12" / "reports" / "failure_fix_plan_drift.json"
SPEC = ROOT / "configs" / "a12" / "next_experiment.yaml"
OUT = ROOT / "data" / "a12" / "reports" / "failure_class4_pat08_real_params.json"


def main() -> int:
    drift = json.loads(DRIFT.read_text(encoding="utf-8"))
    row = next(r for r in drift["rows"] if r["lineage_id"] == LIN)
    spec = load_generation_spec(SPEC)
    rngs = derive_named_rngs(spec.master_seed, LIN)
    print("params:", json.dumps(row["params_now"], sort_keys=True))
    mother = create_mother(row["vessel_id"], row["material_id"], row["params_now"],
                           rngs["shape"], mother_id=LIN)
    print(f"mother faces={len(mother.mesh.faces)} verts={len(mother.mesh.vertices)} "
          f"watertight={bool(mother.mesh.is_watertight)} "
          f"volume={float(mother.mesh.volume):.1f}")
    result: dict = {"lineage_id": LIN, "params": row["params_now"],
                    "mother": {"faces": int(len(mother.mesh.faces)),
                               "verts": int(len(mother.mesh.vertices)),
                               "watertight": bool(mother.mesh.is_watertight),
                               "volume_mm3": float(mother.mesh.volume)},
                    "stages": {}}
    from synlab.patterns.api import evaluate

    recipe = _build_pattern_recipe(mother, spec, rngs["pattern"], row["pattern_id"])
    points = np.asarray(mother.mesh.vertices, dtype=np.float64)
    evaluate(recipe, mother, points, np.zeros(len(points), dtype=np.int32))
    fracture = fracture_event(mother, spec.fracture, rngs["cut"], event_id=f"{LIN}_E01")
    clean = finalize_clean_truth(mother, fracture)
    target = _pick_fragment(fracture)
    damage = _load_damage_recipe(spec.physical.recipes[0], spec, fragment=target,
                                 master_seed=spec.master_seed, lineage_id=LIN)
    try:
        physical = apply_damage(clean, target, damage, rngs["damage"])
    except Exception as exc:
        result["stages"]["physical"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                        "traceback": traceback.format_exc()[-2500:]}
        print("PHYSICAL FAILED:", exc)
    else:
        result["stages"]["physical"] = {"ok": True, "components": len(physical.components),
                                        "lost_volume_ratio": float(physical.lost_volume_ratio)}
        print(f"physical ok: components={len(physical.components)} "
              f"target={target.fragment_id}")
        store = AssetStore(ROOT / "data" / "a12" / "reports" / "failure_fix_store")
        observe_spec = _resolve_observe_spec(spec, store)
        result["observe_spec"] = {"view_count": int(observe_spec.view_count),
                                  "delivered_size": list(observe_spec.delivered_size),
                                  "max_render_pixels": int(observe_spec.max_render_pixels)}
        from synlab.observe.api import observe

        try:
            observation = observe(physical, None, rngs,
                                  route=spec.observation.routes[0].value, spec=observe_spec)
        except Exception as exc:
            result["stages"]["observe"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                           "traceback": traceback.format_exc()}
            print("OBSERVE FAILED:", f"{type(exc).__name__}: {exc}")
            print(result["stages"]["observe"]["traceback"][-3000:])
        else:
            result["stages"]["observe"] = {"ok": True, "views": len(observation.views)}
            print(f"observe ok: views={len(observation.views)}")
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"written {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
