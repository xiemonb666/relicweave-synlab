"""Attribute the post-fix ``LIN0019_V12_M05_PAT11`` failure (physical stage) to a target rule.

The ledger row has stage times up to ``clean_truth`` and no ``physical`` key, so the exception was
raised inside the physical block.  Because the class-3 fix changes *which* fragment the recipe is
applied to, this script runs the declared P recipe on **both** candidates:

* ``old_rule`` - the largest non-tiny fragment by volume (the rule before the fix),
* ``new_rule`` - the largest fragment that carries an interface face (``_pick_fragment``),

and prints the traceback of whichever one fails.  A failure under both rules cannot be caused by
the target selection.

Usage::

    python data/a12/reports/failure_fix_physical_attribution.py LIN0019_V12_M05_PAT11
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
from synlab.pipeline import (_fragment_interface_faces, _load_damage_recipe, _pick_fragment,
                             _build_pattern_recipe)  # noqa: E402
from synlab.patterns.api import evaluate  # noqa: E402
from synlab.seeds import derive_named_rngs  # noqa: E402
from synlab.truth.api import finalize_clean_truth  # noqa: E402

LIN = sys.argv[1] if len(sys.argv) > 1 else "LIN0019_V12_M05_PAT11"
DRIFT = ROOT / "data" / "a12" / "reports" / "failure_fix_plan_drift.json"
SPEC = ROOT / "configs" / "a12" / "next_experiment.yaml"
OUT = ROOT / "data" / "a12" / "reports" / f"failure_class5_{LIN.split('_')[0]}_attribution.json"


def run(label: str, clean, target, recipe, rng) -> dict:
    try:
        physical = apply_damage(clean, target, recipe, rng)
    except Exception as exc:
        return {"label": label, "fragment": target.fragment_id, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-2500:]}
    return {"label": label, "fragment": target.fragment_id, "ok": True,
            "components": len(physical.components),
            "lost_volume_ratio": float(physical.lost_volume_ratio)}


def main() -> int:
    drift = json.loads(DRIFT.read_text(encoding="utf-8"))
    row = next(r for r in drift["rows"] if r["lineage_id"] == LIN)
    spec = load_generation_spec(SPEC)
    rngs = derive_named_rngs(spec.master_seed, LIN)
    mother = create_mother(row["vessel_id"], row["material_id"], row["params_now"],
                           rngs["shape"], mother_id=LIN)
    recipe = _build_pattern_recipe(mother, spec, rngs["pattern"], row["pattern_id"])
    points = np.asarray(mother.mesh.vertices, dtype=np.float64)
    evaluate(recipe, mother, points, np.zeros(len(points), dtype=np.int32))
    fracture = fracture_event(mother, spec.fracture, rngs["cut"], event_id=f"{LIN}_E01")
    clean = finalize_clean_truth(mother, fracture)
    pool = [f for f in fracture.fragments if not f.is_tiny] or list(fracture.fragments)
    old_target = max(pool, key=lambda f: float(f.volume_mm3))
    new_target = _pick_fragment(fracture)
    print(f"{LIN}: fragments={len(fracture.fragments)} "
          f"old_target={old_target.fragment_id} new_target={new_target.fragment_id}")
    for fragment in pool:
        by_id, by_origin = _fragment_interface_faces(fragment)
        print(f"   {fragment.fragment_id:44s} vol={fragment.volume_mm3:12.1f} "
              f"iface={by_id}/{by_origin}")
    recipe_id = spec.physical.recipes[0]
    results = []
    for label, target in (("new_rule_interface_capable", new_target),
                          ("old_rule_largest_volume", old_target)):
        damage = _load_damage_recipe(recipe_id, spec, fragment=target,
                                     master_seed=spec.master_seed, lineage_id=LIN)
        results.append(run(label, clean, target, damage, rngs["damage"]))
    report = {"lineage_id": LIN, "recipe_id": recipe_id,
              "same_target": old_target.fragment_id == new_target.fragment_id,
              "results": results}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for item in results:
        print(f"  {item['label']:28s} ok={item['ok']} {item.get('error', '')}")
        if not item["ok"]:
            print(item["traceback"][-1800:])
    print(f"written {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
