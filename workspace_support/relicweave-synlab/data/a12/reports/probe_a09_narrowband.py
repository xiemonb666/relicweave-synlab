"""A09 stage-3: does the in-repo narrow-band P03 implementation deliver a legal result?

``synlab.degrade.narrowband`` / ``physical_narrowband`` implement P02/P03/P04 as
*closed-by-construction* surface operators ("per-vertex inward normal offset by the frozen
smooth depth field, pinned to zero on the ROI rim") and are the backend
``synlab.degrade.axes._PhysicalAxis`` already uses.  The generation pipeline still reaches P03
through ``physical.operators.run_damage`` (global uniform SDF + marching cubes + boolean clip),
which is the path that produced the failing A09 asset.

This probe runs *both* backends on the same clean fragment with the same frozen recipe basis and
audits each with the unmodified ``audit_physical``:

* per-component watertight / volume / ``damaged ⊆ clean`` (dense, 20 000 samples);
* the audit verdict and failure codes;
* lost volume vs the declared (linearised) effect.

Usage:
  .venv\\Scripts\\python.exe data/a12/reports/probe_a09_narrowband.py --store <store> --out <json>
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
from synlab.physical import operators as OPS  # noqa: E402
from synlab.physical import sdf as S  # noqa: E402
from synlab.physical.api import apply_damage, audit_physical, register_components  # noqa: E402
from synlab.pipeline import _load_damage_recipe  # noqa: E402
from synlab.roles import ROLE_FRAGMENT_MESH  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def _result_summary(result, clean: trimesh.Trimesh) -> dict:
    components = []
    for index, component in enumerate(result.components):
        report = S.watertight_report(component.mesh)
        outside = S.outside_fraction(component.mesh, clean, n_samples=20000, tol_mm=1e-3,
                                     seed=index)
        components.append({
            "component_id": component.component_id, "status": component.status,
            "volume_mm3": float(component.volume_mm3), "watertight": report["watertight"],
            "positive_volume": report["positive_volume"], "n_faces": report["n_faces"],
            "outside_fraction": float(outside["outside_fraction"]),
            "max_outside_mm": float(outside["max_outside_mm"]),
        })
    return {
        "lost_volume_mm3": float(result.lost_volume_mm3),
        "lost_volume_ratio": float(result.lost_volume_ratio),
        "component_count": len(result.components),
        "components": components,
        "measured": {k: (float(v) if isinstance(v, (int, float, np.floating, np.integer))
                         else str(v))
                     for k, v in (result.meta.get("measured") or {}).items()},
        "ledger": dict(result.meta.get("ledger") or {}),
        "backend": result.meta.get("damage_backend", "physical.operators.run_damage"),
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
                 "recipe": {"axis_id": recipe.axis_id, "variant": recipe.variant,
                            "level": int(recipe.level), "params": dict(recipe.params),
                            "qa": dict(recipe.qa), "basis_source": recipe.meta.get("basis_source")},
                 "source_volume_mm3": float(abs(clean.volume))}

    global_result = apply_damage(clean_stub, fragment, recipe, None)
    out["global_sdf_path"] = _result_summary(global_result, clean)
    out["global_sdf_audit"] = _audit(global_result, clean)

    narrow = run_narrowband_damage(clean, recipe, fragment=fragment)
    out["narrowband_path"] = _result_summary(narrow, clean)
    out["narrowband_audit"] = _audit(narrow, clean)
    return out


def _audit(result, clean) -> dict:
    audit = audit_physical(result, clean)
    return {"status": audit.get("status"), "failure_codes": audit.get("failure_codes"),
            "measured": {k: float(v) for k, v in (audit.get("measured") or {}).items()},
            "checks": {k: v for k, v in (audit.get("checks") or {}).items()
                       if k in ("damaged_subset_clean", "watertight", "positive_volume",
                                "loss_accounting", "min_thickness", "declared_effect_measured",
                                "source_residue")}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True)
    parser.add_argument("--lineage", default="LIN0000_V02_M01_PAT02")
    parser.add_argument("--recipe", default="P03_depth_light")
    parser.add_argument("--config", default="configs/a12/sandbox.yaml")
    parser.add_argument("--out", default="data/a12/reports/a09_p03_narrowband.json")
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
