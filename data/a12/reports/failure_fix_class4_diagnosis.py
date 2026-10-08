"""Diagnose the post-fix ``IndexError`` on ``LIN0016_V19_M04_PAT08`` (physical stage).

The lineage failed with ``IndexError: index 1024 is out of bounds for axis 1 with size 1024``
after ``clean_truth`` (stage times: mother 0.05, material 0.01, pattern 1.04, fracture 7.02,
clean_truth 0.12, physical 4.81).  This script replays the chain and runs the declared P recipe
on **both** candidate targets - the one the previous largest-volume rule picked and the one the
fixed rule picks - so the failure can be attributed to the target selection or to the operator
itself.  Nothing is committed; the store is only read for the plan parameters.
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
                             _resolve_observe_spec)  # noqa: E402
from synlab.patterns.api import apply_pattern_geometry, build_pattern, evaluate  # noqa: E402
from synlab.seeds import derive_named_rngs  # noqa: E402
from synlab.truth.api import finalize_clean_truth  # noqa: E402

LIN = "LIN0016_V19_M04_PAT08"
PLAN = ROOT / "data" / "a12" / "reports" / "failure_class1_param_validation.json"
SPEC = ROOT / "configs" / "a12" / "next_experiment.yaml"
OUT = ROOT / "data" / "a12" / "reports" / "failure_class4_pat08_diagnosis.json"


def attempt(label: str, clean, target, recipe, rng) -> dict:
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
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    row = next(r for r in plan["rows"] if r["lineage_id"] == LIN)
    vessel, material, pattern_id = row["vessel_id"], row["material_id"], row["pattern_id"]
    params = row["params"]
    spec = load_generation_spec(SPEC)
    rngs = derive_named_rngs(spec.master_seed, LIN)
    mother = create_mother(vessel, material, params, rngs["shape"], mother_id=LIN)
    recipe = build_pattern(mother, {"family": pattern_id, "seed_ref": f"{LIN}-PAT",
                                    "quota_class": "FREE"}, rngs["pattern"])
    pts = np.asarray(mother.mesh.vertices, dtype=np.float64)
    channels = evaluate(recipe, mother, pts, np.zeros(len(pts), dtype=np.int32))
    mother = apply_pattern_geometry(mother, recipe, rngs["pattern"]) if spec.pattern.height_policy != "none" else mother
    fracture = fracture_event(mother, spec.fracture, rngs["cut"], event_id=f"{LIN}_E01")
    clean = finalize_clean_truth(mother, fracture)
    fragments = [f for f in fracture.fragments if not f.is_tiny] or list(fracture.fragments)
    old_target = max(fragments, key=lambda f: float(f.volume_mm3))
    new_target = _pick_fragment(fracture)
    print(f"{LIN}: fragments={len(fracture.fragments)} old_target={old_target.fragment_id} "
          f"new_target={new_target.fragment_id} channels_ok={channels.albedo.shape}")
    for fragment in fragments:
        by_id, by_origin = _fragment_interface_faces(fragment)
        print(f"   {fragment.fragment_id:44s} vol={fragment.volume_mm3:10.1f} "
              f"iface={by_id}/{by_origin}")
    recipe_id = spec.physical.recipes[0] if spec.physical.recipes else "P03_depth_light"
    results = []
    for label, target in (("old_rule_largest_volume", old_target),
                          ("new_rule_interface_capable", new_target)):
        damage = _load_damage_recipe(recipe_id, spec, fragment=target,
                                     master_seed=spec.master_seed, lineage_id=LIN)
        results.append(attempt(label, clean, target, damage, rngs["damage"]))
    report = {"lineage_id": LIN, "vessel_id": vessel, "material_id": material,
              "pattern_id": pattern_id, "recipe_id": recipe_id,
              "old_target": old_target.fragment_id, "new_target": new_target.fragment_id,
              "same_target": old_target.fragment_id == new_target.fragment_id,
              "results": results}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for item in results:
        print(f"  {item['label']:28s} target={item['fragment']:44s} ok={item['ok']} "
              f"{item.get('error', '')}")
        if not item["ok"]:
            print(item["traceback"][-1200:])
    print(f"written {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
