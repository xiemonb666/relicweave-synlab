"""A09 diagnostic: reproduce the failing P03_depth_light physical result from an archived store.

The L0 census (``data/a12/reports/l0_role_census.json``) recorded

    asset_373e79ee5e6bafaabe78  physical_result  QA_FAIL
    DAMAGED_NOT_SUBSET_OF_CLEAN + NON_POSITIVE_VOLUME + NOT_WATERTIGHT
    recipe P03_depth_light / level 1 / P03 smooth_recession_field
    lost_volume_mm3 276.58  components 3 = core 1 + debris 2

This probe re-runs the *same* operator on the *same* clean fragment (loaded from the archived
store) with the *same* frozen recipe basis (rebuilt through
``synlab.pipeline._load_damage_recipe`` with the census master seed and lineage id), and prints
the per-component measurements that the audit uses:

* watertightness / winding / signed and absolute volume / degenerate faces (``sdf.watertight_report``);
* ``damaged ⊆ clean`` per component (``sdf.outside_fraction``) plus the operator's own
  ``_inside_mask`` number;
* what ``sdf.component_split`` returns before the identity policy runs, and what
  ``register_components`` keeps.

Usage:
  .venv\\Scripts\\python.exe data/a12/reports/probe_a09_p03.py --store <store> --out <json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.physical import sdf as S  # noqa: E402
from synlab.physical.api import apply_damage, audit_physical  # noqa: E402
from synlab.pipeline import _load_damage_recipe  # noqa: E402
from synlab.roles import ROLE_FRAGMENT_MESH  # noqa: E402
from synlab.seeds import derive_named_rngs  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def _component_report(component, clean_mesh, index: int) -> dict:
    mesh = component.mesh
    report = S.watertight_report(mesh)
    outside = S.outside_fraction(mesh, clean_mesh, n_samples=1500, tol_mm=1e-3, seed=index)
    return {
        "component_id": component.component_id,
        "status": component.status,
        "is_representative": bool(component.is_representative),
        "is_contamination": bool(component.meta.get("is_contamination")),
        "supportable": bool(component.meta.get("supportable")),
        "volume_mm3": float(component.volume_mm3),
        "watertight": report["watertight"],
        "winding_consistent": report["winding_consistent"],
        "signed_volume_mm3": report["signed_volume_mm3"],
        "abs_volume_mm3": report["volume_mm3"],
        "euler_number": report["euler_number"],
        "n_faces": report["n_faces"],
        "n_vertices": report["n_vertices"],
        "degenerate_faces": report["degenerate_faces"],
        "outside_fraction": outside["outside_fraction"],
        "max_outside_mm": outside["max_outside_mm"],
        "outside_points": outside["outside_points"],
        "samples": outside["samples"],
        "n_bodies_in_component": len(S.component_split(mesh)),
    }


def probe(store_root: Path, lineage_id: str, recipe_id: str, config: Path) -> dict:
    store = AssetStore(store_root)
    out: dict = {"store": str(store_root), "lineage_id": lineage_id, "recipe_id": recipe_id,
                 "config": str(config)}
    fragments = store.list_assets(role=ROLE_FRAGMENT_MESH, limit=200)
    rows = []
    for record in fragments:
        mesh = store.load_mesh(record.asset_id, "mesh")
        rows.append({"asset_id": record.asset_id, "fragment_id": record.meta.get("fragment_id"),
                     "volume_mm3": float(abs(mesh.volume)), "n_faces": int(len(mesh.faces)),
                     "is_tiny": bool(record.meta.get("is_tiny")),
                     "watertight": bool(mesh.is_watertight)})
    out["fragments"] = sorted(rows, key=lambda r: -r["volume_mm3"])
    if not rows:
        raise SystemExit("no fragment_mesh asset in this store")
    target = max((r for r in rows if not r["is_tiny"]), key=lambda r: r["volume_mm3"],
                 default=max(rows, key=lambda r: r["volume_mm3"]))
    clean_mesh = store.load_mesh(target["asset_id"], "mesh")
    out["clean_fragment"] = target

    spec = load_generation_spec(config)
    fragment = SimpleNamespace(
        mesh=clean_mesh, fragment_id=str(target["fragment_id"]),
        volume_mm3=float(abs(clean_mesh.volume)), is_tiny=False,
        meta={"material_id": ""})
    recipe = _load_damage_recipe(recipe_id, spec, fragment=fragment,
                                 master_seed=spec.master_seed, lineage_id=lineage_id)
    out["recipe"] = {"axis_id": recipe.axis_id, "variant": recipe.variant,
                     "level": int(recipe.level), "params": dict(recipe.params),
                     "roi": dict(recipe.roi), "qa": dict(recipe.qa),
                     "basis_source": recipe.meta.get("basis_source"),
                     "basis_keys": sorted(recipe.basis)}
    rng = derive_named_rngs(spec.master_seed, lineage_id)["damage"]
    clean_stub = SimpleNamespace(mother_id="M_probe", event_id=f"{lineage_id}_E01", version=1)
    result = apply_damage(clean_stub, fragment, recipe, rng)

    out["raw_component_split_of_operator_body"] = None
    out["result"] = {
        "lost_volume_mm3": float(result.lost_volume_mm3),
        "lost_volume_ratio": float(result.lost_volume_ratio),
        "component_count": len(result.components),
        "qa_status": result.qa.get("status"),
        "realized": result.qa.get("realized"),
        "geometry_hash_unchanged": result.qa.get("geometry_hash_unchanged"),
        "measured": {k: float(v) for k, v in (result.meta.get("measured") or {}).items()},
        "ledger": dict(result.meta.get("ledger") or {}),
        "components": [_component_report(c, clean_mesh, i) for i, c in enumerate(result.components)],
    }
    audit = audit_physical(result, clean_mesh)
    out["audit"] = {
        "status": audit.get("status"),
        "failure_codes": audit.get("failure_codes"),
        "measured": {k: float(v) for k, v in (audit.get("measured") or {}).items()},
        "checks": {k: v for k, v in (audit.get("checks") or {}).items()
                   if k in ("damaged_subset_clean", "watertight", "positive_volume",
                            "loss_accounting", "min_thickness", "declared_effect_measured")},
        "no_auto_repair": audit.get("no_auto_repair"),
    }
    # per-clean-surface-sample diagnosis: where does the damage leave the clean body?
    worst = max(result.components,
                key=lambda c: S.outside_fraction(c.mesh, clean_mesh, n_samples=1500,
                                                 tol_mm=1e-3, seed=0)["max_outside_mm"])
    dense = S.outside_fraction(worst.mesh, clean_mesh, n_samples=20000, tol_mm=1e-3, seed=3)
    out["worst_component_dense_outside"] = {"component_id": worst.component_id, **{
        k: (float(v) if isinstance(v, (int, float)) else v) for k, v in dense.items()}}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True)
    parser.add_argument("--lineage", default="LIN0000_V02_M01_PAT02")
    parser.add_argument("--recipe", default="P03_depth_light")
    parser.add_argument("--config", default="configs/a12/sandbox.yaml")
    parser.add_argument("--out", default="data/a12/reports/a09_p03_probe.json")
    args = parser.parse_args()
    report = probe(Path(args.store), args.lineage, args.recipe, Path(args.config))
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
