"""A09 acceptance: the audit verdicts before/after the subset_v2 fix, on archived assets.

Controls (all four must be read together, otherwise a PASS proves nothing):

1. **identity (level 0)** -- the component *is* the clean mesh object.  With the shipped
   instrument this control FAILED ``DAMAGED_NOT_SUBSET_OF_CLEAN`` (measured max outside
   0.0087 mm for a body measured against itself); with the exact instrument it must pass.
2. **self-distance of the clean mesh** -- the instrument's own floor: Open3D 0.0161 mm /
   0.275 % outside, exact 1.4e-10 mm / 0 outside.
3. **P03_depth_light L1 through the shipped global-SDF operator** (the failing A09 asset):
   before = 3 failure codes, after = PASS with the damage magnitude unchanged.
4. **P03_depth_light L1 through the narrow-band operator** (the backend the degrade registry
   already declares for P03): before = DAMAGED_NOT_SUBSET_OF_CLEAN only, after = PASS.

Usage:
  .venv\\Scripts\\python.exe data/a12/reports/probe_a09_acceptance.py --store <store> --out <json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.degrade.physical_narrowband import run_narrowband_damage  # noqa: E402
from synlab.physical import sdf as S  # noqa: E402
from synlab.physical.api import (  # noqa: E402
    DAMAGE_SEMANTICS,
    apply_damage,
    audit_physical,
    subset_outside_stats,
)
from synlab.physical.recipe import DamageRecipe  # noqa: E402
from synlab.pipeline import _load_damage_recipe  # noqa: E402
from synlab.roles import ROLE_FRAGMENT_MESH  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def _audit_row(result, clean) -> dict:
    audit = audit_physical(result, clean)
    check = (audit.get("checks") or {}).get("damaged_subset_clean") or {}
    return {
        "status": audit.get("status"),
        "failure_codes": audit.get("failure_codes"),
        "damage_semantics": audit.get("damage_semantics"),
        "subset_instrument": audit.get("subset_instrument"),
        "subset_max_outside_mm_exact": check.get("max_outside_mm"),
        "subset_max_outside_mm_open3d": check.get("approx_open3d_max_outside_mm"),
        "subset_outside_points": check.get("outside_points"),
        "watertight": (audit.get("checks") or {}).get("watertight", {}).get("pass"),
        "positive_volume": (audit.get("checks") or {}).get("positive_volume", {}).get("pass"),
        "components": [(c["component_id"].split("#")[-1], c["status"],
                        round(float(c["volume_mm3"]), 6)) for c in audit.get("components", [])],
        "lost_volume_mm3": float(audit.get("measured", {}).get("lost_volume_mm3", 0.0)),
        "component_count": int(audit.get("measured", {}).get("component_count", 0.0)),
        "assembly": audit.get("pinhole_closure"),
    }


def probe(store_root: Path, lineage_id: str, recipe_id: str, config: Path) -> dict:
    store = AssetStore(store_root)
    fragments = store.list_assets(role=ROLE_FRAGMENT_MESH, limit=200)
    best = max(fragments, key=lambda r: float(abs(store.load_mesh(r.asset_id, "mesh").volume)))
    clean = store.load_mesh(best.asset_id, "mesh")
    spec = load_generation_spec(config)
    fragment = SimpleNamespace(mesh=clean, fragment_id=str(best.meta.get("fragment_id")),
                               volume_mm3=float(abs(clean.volume)), is_tiny=False,
                               meta={"material_id": ""})
    recipe = _load_damage_recipe(recipe_id, spec, fragment=fragment,
                                 master_seed=spec.master_seed, lineage_id=lineage_id)
    clean_stub = SimpleNamespace(mother_id="M_probe", event_id=f"{lineage_id}_E01", version=1)
    out: dict = {"store": str(store_root), "fragment_id": fragment.fragment_id,
                 "damage_semantics": DAMAGE_SEMANTICS, "recipe_id": recipe_id}

    # 1 + 2: instrument controls
    out["control_clean_vs_clean"] = subset_outside_stats(clean, clean, n_samples=1200, seed=1)
    identity_recipe = DamageRecipe(axis_id="P03", variant=recipe.variant, level=0,
                                   recipe_id="P03_identity", params=dict(recipe.params),
                                   roi=dict(recipe.roi), basis=dict(recipe.basis),
                                   meta=dict(recipe.meta), qa=dict(recipe.qa))
    identity = apply_damage(clean_stub, fragment, identity_recipe, None)
    out["control_identity_level"] = _audit_row(identity, clean)
    out["control_identity_level"]["shared_source_object"] = bool(
        identity.components[0].mesh is clean)

    # 3: the failing A09 asset, repaired
    repaired = apply_damage(clean_stub, fragment, recipe, None)
    out["global_sdf_path_after"] = _audit_row(repaired, clean)
    out["global_sdf_path_after"]["measured"] = {
        k: float(v) for k, v in (repaired.meta.get("measured") or {}).items()}
    out["global_sdf_path_after"]["ledger"] = dict(repaired.meta.get("ledger") or {})

    # 4: the narrow-band backend on the same recipe
    narrow = run_narrowband_damage(clean, recipe, fragment=fragment)
    out["narrowband_path_after"] = _audit_row(narrow, clean)

    # 5: the same material-before/after comparison through the superseded instrument
    out["shipped_instrument_would_say"] = {
        "identity": "DAMAGED_NOT_SUBSET_OF_CLEAN (measured 0.0087 mm on an identical body)",
        "global_body": "DAMAGED_NOT_SUBSET_OF_CLEAN (0.0014 mm > tol 1e-3) + NON_POSITIVE_VOLUME "
                       "+ NOT_WATERTIGHT",
        "narrowband_body": "DAMAGED_NOT_SUBSET_OF_CLEAN (0.0035 mm > tol 1e-3)",
    }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True)
    parser.add_argument("--lineage", default="LIN0000_V02_M01_PAT02")
    parser.add_argument("--recipe", default="P03_depth_light")
    parser.add_argument("--config", default="configs/a12/sandbox.yaml")
    parser.add_argument("--out", default="data/a12/reports/a09_acceptance_after.json")
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
