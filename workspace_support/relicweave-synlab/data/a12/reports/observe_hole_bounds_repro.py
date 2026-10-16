"""Replay the real observation-stage ``IndexError`` of ``LIN0016_V19_M04_PAT08``.

This is an *independent* copy of ``failure_fix_class4_real_params.py`` (that file's JSON output is
left untouched): it replays the lineage with the parameters of the current plan straight through
mother -> pattern -> fracture -> clean truth -> physical -> observe and prints the traceback of the
failing stage.  ``--out`` selects the JSON the script writes, so the same script can be run before
and after a fix of ``synlab/observe/routes.py`` and the two reports compared.

Usage::

    .venv\\Scripts\\python.exe data\\a12\\reports\\observe_hole_bounds_repro.py \
        --out data\\a12\\reports\\observe_hole_bounds_repro_before.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.config import load_generation_spec  # noqa: E402
from synlab.fracture.api import fracture_event  # noqa: E402
from synlab.mothers.api import create_mother  # noqa: E402
from synlab.physical.api import apply_damage  # noqa: E402
from synlab.pipeline import (  # noqa: E402
    _build_pattern_recipe,
    _load_damage_recipe,
    _pick_fragment,
    _resolve_observe_spec,
)
from synlab.seeds import derive_named_rngs  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402
from synlab.truth.api import finalize_clean_truth  # noqa: E402

LIN = "LIN0016_V19_M04_PAT08"
DRIFT = ROOT / "data" / "a12" / "reports" / "failure_fix_plan_drift.json"
SPEC = ROOT / "configs" / "a12" / "next_experiment.yaml"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/a12/reports/observe_hole_bounds_repro.json")
    ap.add_argument("--lineage", default=LIN)
    args = ap.parse_args()
    lin = args.lineage
    drift = json.loads(DRIFT.read_text(encoding="utf-8"))
    row = next(r for r in drift["rows"] if r["lineage_id"] == lin)
    spec = load_generation_spec(SPEC)
    rngs = derive_named_rngs(spec.master_seed, lin)
    result: dict = {"lineage_id": lin, "params": row["params_now"], "stages": {}}
    t0 = time.time()
    mother = create_mother(row["vessel_id"], row["material_id"], row["params_now"],
                           rngs["shape"], mother_id=lin)
    result["stages"]["mother"] = {"ok": True, "faces": int(len(mother.mesh.faces)),
                                  "verts": int(len(mother.mesh.vertices))}
    print(f"mother faces={len(mother.mesh.faces)} verts={len(mother.mesh.vertices)}", flush=True)

    from synlab.patterns.api import evaluate

    recipe = _build_pattern_recipe(mother, spec, rngs["pattern"], row["pattern_id"])
    points = np.asarray(mother.mesh.vertices, dtype=np.float64)
    evaluate(recipe, mother, points, np.zeros(len(points), dtype=np.int32))
    fracture = fracture_event(mother, spec.fracture, rngs["cut"], event_id=f"{lin}_E01")
    clean = finalize_clean_truth(mother, fracture)
    target = _pick_fragment(fracture)
    damage = _load_damage_recipe(spec.physical.recipes[0], spec, fragment=target,
                                 master_seed=spec.master_seed, lineage_id=lin)
    try:
        physical = apply_damage(clean, target, damage, rngs["damage"])
    except Exception as exc:  # noqa: BLE001 - the report must keep the real failure
        result["stages"]["physical"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                        "traceback": traceback.format_exc()[-2500:]}
        print("PHYSICAL FAILED:", f"{type(exc).__name__}: {exc}", flush=True)
    else:
        result["stages"]["physical"] = {"ok": True, "components": len(physical.components),
                                        "lost_volume_ratio": float(physical.lost_volume_ratio),
                                        "target": target.fragment_id}
        print(f"physical ok: components={len(physical.components)} target={target.fragment_id}",
              flush=True)
        store = AssetStore(ROOT / "data" / "a12" / "reports" / "failure_fix_store")
        observe_spec = _resolve_observe_spec(spec, store)
        result["observe_spec"] = {"view_count": int(observe_spec.view_count),
                                  "delivered_size": list(observe_spec.delivered_size),
                                  "max_render_pixels": int(observe_spec.max_render_pixels),
                                  "route": str(spec.observation.routes[0].value)}
        print(f"observe spec: {result['observe_spec']}", flush=True)
        from synlab.observe.api import observe

        try:
            observation = observe(physical, None, rngs,
                                  route=spec.observation.routes[0].value, spec=observe_spec)
        except Exception as exc:  # noqa: BLE001 - keep the real error, never mask it
            result["stages"]["observe"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                           "traceback": traceback.format_exc()}
            print("OBSERVE FAILED:", f"{type(exc).__name__}: {exc}", flush=True)
            print(result["stages"]["observe"]["traceback"][-3000:], flush=True)
        else:
            shapes = [tuple(np.asarray(v.depth_z).shape) for v in observation.views]
            result["stages"]["observe"] = {"ok": True, "views": len(observation.views),
                                           "depth_shapes": shapes}
            print(f"observe ok: views={len(observation.views)} depth_shapes={shapes[:2]}", flush=True)
    result["wall_s"] = round(time.time() - t0, 3)
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"written {out.relative_to(ROOT)} wall_s={result['wall_s']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
