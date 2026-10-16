"""Attribute the post-fix ``IndexError`` on ``LIN0016_V19_M04_PAT08`` to its real stage.

The batch ledger records stage times up to ``physical`` but no ``observe``, which means the
exception was raised inside the observation block.  This script replays the whole chain with the
same rngs/recipe the pipeline uses and prints the full traceback of the observation stage.
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
PLAN = ROOT / "data" / "a12" / "reports" / "failure_class1_param_validation.json"
SPEC = ROOT / "configs" / "a12" / "next_experiment.yaml"
OUT = ROOT / "data" / "a12" / "reports" / "failure_class4_pat08_observe.json"


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    row = next(r for r in plan["rows"] if r["lineage_id"] == LIN)
    spec = load_generation_spec(SPEC)
    rngs = derive_named_rngs(spec.master_seed, LIN)
    mother = create_mother(row["vessel_id"], row["material_id"], row["params"], rngs["shape"],
                           mother_id=LIN)
    recipe = _build_pattern_recipe(mother, spec, rngs["pattern"], row["pattern_id"])
    points = np.asarray(mother.mesh.vertices, dtype=np.float64)
    from synlab.patterns.api import evaluate

    evaluate(recipe, mother, points, np.zeros(len(points), dtype=np.int32))
    fracture = fracture_event(mother, spec.fracture, rngs["cut"], event_id=f"{LIN}_E01")
    clean = finalize_clean_truth(mother, fracture)
    target = _pick_fragment(fracture)
    recipe_id = spec.physical.recipes[0]
    damage = _load_damage_recipe(recipe_id, spec, fragment=target,
                                 master_seed=spec.master_seed, lineage_id=LIN)
    physical = apply_damage(clean, target, damage, rngs["damage"])
    print(f"physical ok: components={len(physical.components)} "
          f"lost_volume_ratio={physical.lost_volume_ratio:.6g} target={target.fragment_id}")

    result = {"lineage_id": LIN, "target": target.fragment_id,
              "physical": {"components": len(physical.components),
                           "lost_volume_ratio": float(physical.lost_volume_ratio)}}
    store = AssetStore(ROOT / "data" / "a12" / "reports" / "failure_fix_store")
    observe_spec = _resolve_observe_spec(spec, store)
    route = spec.observation.routes[0].value
    result["observe_spec"] = {
        "view_count": int(observe_spec.view_count),
        "delivered_size": list(observe_spec.delivered_size),
        "max_render_pixels": int(observe_spec.max_render_pixels),
        "route": route,
    }
    print(f"observe spec: {result['observe_spec']}")
    from synlab.observe.api import observe

    try:
        observation = observe(physical, None, rngs, route=route, spec=observe_spec)
    except Exception as exc:
        result["observe"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                             "traceback": traceback.format_exc()}
        print("OBSERVE FAILED:")
        print(result["observe"]["traceback"][-3000:])
    else:
        result["observe"] = {"ok": True, "views": len(observation.views)}
        print(f"observe ok: views={len(observation.views)}")
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"written {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
