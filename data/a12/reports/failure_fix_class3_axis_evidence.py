"""Class-3 evidence: the P axis on the lineage that answered NA_NOT_APPLICABLE.

Reproduces ``LIN0004_V10_M06_PAT03`` with the real parameters, runs the real fracture and the
real declared damage recipe (``configs/a12/next_experiment.yaml`` -> ``physical.recipes[0]``),
and reports:

  * the mother's surface-connected components (the stray V10 lid skirt is expected to be gone),
  * every fragment with its interface face counts,
  * the fragment the *old* rule would have picked (largest non-tiny by volume) and the one the
    new rule picks (largest that carries an interface face),
  * ``synlab.physical.fields.roi_faces`` on both targets, i.e. the real
    ``NA_NOT_APPLICABLE`` -> applicable transition,
  * the real ``apply_damage``/``audit_physical`` outcome on the picked target.

Writes ``data/a12/reports/failure_class3_axis_evidence.json``.  Nothing is committed to the
store.
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
from synlab.errors import SynLabError  # noqa: E402
from synlab.fracture.api import fracture_event  # noqa: E402
from synlab.fracture.fragment import split_components  # noqa: E402
from synlab.mothers.api import audit_mother, create_mother  # noqa: E402
from synlab.physical.api import apply_damage, audit_physical  # noqa: E402
from synlab.physical.fields import roi_faces  # noqa: E402
from synlab.pipeline import _fragment_interface_faces, _load_damage_recipe, _pick_fragment  # noqa: E402
from synlab.schemas.runtime import ORIGIN_INTERFACE  # noqa: E402
from synlab.seeds import derive_named_rngs  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402
from synlab.truth.api import finalize_clean_truth  # noqa: E402

LIN = "LIN0004_V10_M06_PAT03"
MOTHER_ASSET = "asset_d6a31345d892ead78e4e"
SPEC = ROOT / "configs" / "a12" / "next_experiment.yaml"
OUT = ROOT / "data" / "a12" / "reports" / "failure_class3_axis_evidence.json"


def roi_probe(fragment: object, roi: dict) -> dict:
    try:
        ids, info = roi_faces(fragment.mesh, fragment, roi)
    except SynLabError as exc:
        return {"applicable": False, "code": str(exc.code), "message": exc.message[:200]}
    return {"applicable": True, "n_faces": int(len(ids)), "info": info}


def main() -> int:
    store = AssetStore(ROOT / "data" / "a12")
    record = store.get_asset(MOTHER_ASSET)
    params = dict(record.meta.get("params") or {})
    spec = load_generation_spec(SPEC)
    rngs = derive_named_rngs(spec.master_seed, LIN)

    mother = create_mother("V10", str(record.meta.get("material_id", "M06")), params,
                           rngs["shape"], mother_id=LIN)
    audit = audit_mother(mother, max_thickness_probes=48, run_self_intersection=False)
    parts = split_components(mother.mesh)
    print(f"mother faces={len(mother.mesh.faces)} watertight={bool(mother.mesh.is_watertight)} "
          f"audit_ok={bool(audit.get('ok'))} components={len(parts)}")
    component_rows = []
    for index, part in enumerate(parts):
        z = np.asarray(part.mesh.bounds)[:, 2]
        component_rows.append({"index": index, "faces": int(len(part.mesh.faces)),
                               "volume_mm3": round(part.volume_mm3, 3),
                               "z_range_mm": [round(float(z[0]), 3), round(float(z[1]), 3)]})
        print(f"  component #{index}: faces={len(part.mesh.faces)} vol={part.volume_mm3:.1f} "
              f"z=[{z[0]:.2f},{z[1]:.2f}]")

    event_id = f"{LIN}_E01"
    fracture = fracture_event(mother, spec.fracture, rngs["cut"], event_id=event_id)
    fragment_rows = []
    for fragment in fracture.fragments:
        by_id, by_origin = _fragment_interface_faces(fragment)
        fragment_rows.append({
            "fragment_id": fragment.fragment_id, "component_id": int(fragment.component_id),
            "faces": int(len(fragment.mesh.faces)), "volume_mm3": round(fragment.volume_mm3, 3),
            "is_tiny": bool(fragment.is_tiny),
            "side": int(np.asarray(fragment.face_side)[0]),
            "interface_faces_by_id": by_id, "interface_faces_by_origin": by_origin,
            "carries_interface": bool(by_id > 0 or by_origin > 0),
        })
        print(f"  {fragment.fragment_id:44s} vol={fragment.volume_mm3:10.1f} "
              f"iface(id/origin)={by_id}/{by_origin} tiny={fragment.is_tiny}")

    # the rule before the fix: largest non-tiny fragment by volume, whatever its surface
    pool = [f for f in fracture.fragments if not f.is_tiny] or list(fracture.fragments)
    old_target = max(pool, key=lambda f: float(f.volume_mm3))
    new_target = _pick_fragment(fracture)
    print(f"\nold rule target: {old_target.fragment_id} (vol={old_target.volume_mm3:.1f})")
    print(f"new rule target: {new_target.fragment_id} (vol={new_target.volume_mm3:.1f})")

    recipe_id = spec.physical.recipes[0] if spec.physical.recipes else "P03_depth_light"
    outcome: dict = {"recipe_id": recipe_id}
    try:
        old_recipe = _load_damage_recipe(recipe_id, spec, fragment=old_target,
                                         master_seed=spec.master_seed, lineage_id=LIN)
        outcome["old_target_roi"] = roi_probe(old_target, dict(old_recipe.roi))
        outcome["old_target_axis"] = {"axis_id": old_recipe.axis_id, "level": int(old_recipe.level),
                                      "variant": old_recipe.variant,
                                      "roi": dict(old_recipe.roi)}
        print(f"  old target + {old_recipe.axis_id} ROI: {outcome['old_target_roi']}")
    except SynLabError as exc:
        outcome["old_target_error"] = {"code": str(exc.code), "message": exc.message[:300]}
        print(f"  old target failed earlier: {exc.code}: {exc.message[:200]}")

    try:
        clean = finalize_clean_truth(mother, fracture)
        recipe = _load_damage_recipe(recipe_id, spec, fragment=new_target,
                                     master_seed=spec.master_seed, lineage_id=LIN)
        outcome["new_target_axis"] = {"axis_id": recipe.axis_id, "level": int(recipe.level),
                                      "variant": recipe.variant, "roi": dict(recipe.roi),
                                      "params": dict(recipe.params),
                                      "basis_source": recipe.meta.get("basis_source")}
        outcome["new_target_roi"] = roi_probe(new_target, dict(recipe.roi))
        print(f"  new target + {recipe.axis_id} ROI: {outcome['new_target_roi']}")
        physical = apply_damage(clean, new_target, recipe, rngs["damage"])
        physical_audit = audit_physical(physical, clean)
        outcome["apply_damage"] = {
            "ok": True,
            "components": int(len(physical.components)),
            "lost_volume_ratio": float(physical.lost_volume_ratio),
            "audit_status": physical_audit.get("status"),
            "audit_keys": sorted(physical_audit)[:20],
            "geometry_changed": bool(physical_audit.get("geometry_changed")),
        }
        print(f"  apply_damage ok: components={outcome['apply_damage']['components']} "
              f"lost_volume_ratio={outcome['apply_damage']['lost_volume_ratio']:.6g} "
              f"audit_status={outcome['apply_damage']['audit_status']}")
    except Exception as exc:  # recorded with its traceback, never hidden
        outcome["new_target_error"] = {"type": type(exc).__name__, "message": str(exc)[:400],
                                       "code": str(getattr(exc, "code", "")),
                                       "traceback": traceback.format_exc()[-1500:]}
        print(f"  new target failed: {type(exc).__name__}: {exc}")

    report = {
        "lineage_id": LIN,
        "config": str(SPEC.relative_to(ROOT)).replace("\\", "/"),
        "mother": {"faces": int(len(mother.mesh.faces)),
                   "watertight": bool(mother.mesh.is_watertight),
                   "audit_ok": bool(audit.get("ok")),
                   "components": component_rows},
        "fracture": {"backend": fracture.backend, "fragments": fragment_rows,
                     "interfaces": len(fracture.interfaces)},
        "old_rule_target": old_target.fragment_id,
        "new_rule_target": new_target.fragment_id,
        "outcome": outcome,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nwritten {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

