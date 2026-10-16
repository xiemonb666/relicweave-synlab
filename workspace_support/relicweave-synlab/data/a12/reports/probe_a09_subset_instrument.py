"""A09 stage-4: is the audit's ``damaged ⊆ clean`` instrument able to pass at all?

``audit_physical`` measures the subset claim with ``sdf.outside_fraction``, i.e. Open3D's
``compute_signed_distance`` on points cast to **float32** (``+`` = outside).  Two controls decide
whether the 1e-3 mm tolerance is a geometry criterion or a measurement floor:

* **control 1 (self-distance):** the clean fragment's own surface sampled and measured against
  itself -- a perfect subset by construction;
* **control 2 (identity level):** a level-0 ``PhysicalResult`` whose single component *is* the
  clean mesh (``apply_damage`` returns the shared source object for level 0), audited with the
  unmodified ``audit_physical``.

Both controls are repeated with an exact float64 point-to-mesh instrument
(``trimesh.proximity.signed_distance``: closest point + normal-projection sign; **its own
convention is positive = INSIDE, the opposite of Open3D**, verified against an axis-aligned box
in ``data/a12/reports/a09_signed_distance_convention.json``).

Usage:
  .venv\\Scripts\\python.exe data/a12/reports/probe_a09_subset_instrument.py --store <store>
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
from synlab.physical.api import apply_damage, audit_physical  # noqa: E402
from synlab.physical.recipe import DamageRecipe  # noqa: E402
from synlab.pipeline import _load_damage_recipe  # noqa: E402
from synlab.roles import ROLE_FRAGMENT_MESH  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

TOL_MM = 1e-3


def _out_stats(positive_is_outside: np.ndarray, tol_mm: float = TOL_MM) -> dict:
    """Statistics of an ``outside`` distance array (already converted, >= 0 = outside)."""
    values = np.asarray(positive_is_outside, dtype=np.float64)
    return {
        "samples": int(len(values)),
        "outside_points": int(np.count_nonzero(values > tol_mm)),
        "outside_fraction": float(np.mean(values > tol_mm)) if len(values) else 0.0,
        "max_outside_mm": float(values.max()) if len(values) else 0.0,
        "p99_outside_mm": float(np.percentile(values, 99)) if len(values) else 0.0,
        "p999_outside_mm": float(np.percentile(values, 99.9)) if len(values) else 0.0,
        "tol_mm": float(tol_mm),
    }


def instruments(mesh: trimesh.Trimesh, reference: trimesh.Trimesh, *, n: int = 20000,
                seed: int = 0) -> dict:
    points, _fid = trimesh.sample.sample_surface(mesh, int(n), seed=int(seed) % (2 ** 31))
    points = np.asarray(points, dtype=np.float64)
    approx = np.asarray(S.scene_for(reference).signed_distance(points), dtype=np.float64)
    exact = np.asarray(trimesh.proximity.signed_distance(reference, points), dtype=np.float64)
    return {
        "measurement": "sampled surface points of the damaged body measured against the clean body",
        "samples": int(len(points)),
        # Open3D compute_signed_distance: positive = outside, negative = inside
        "open3d_approx": _out_stats(approx),
        # trimesh proximity.signed_distance: positive = inside (verified), so outside = -value
        "trimesh_exact": _out_stats(-exact),
    }


def probe(store_root: Path, lineage_id: str, recipe_id: str, config: Path,
          cache_dir: Path) -> dict:
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
                 "tol_mm": TOL_MM, "sign_convention": {
                     "open3d_compute_signed_distance": "positive = OUTSIDE",
                     "trimesh_proximity_signed_distance": "positive = INSIDE"}}

    out["control_clean_vs_clean"] = instruments(clean, clean, n=20000, seed=1)

    identity_recipe = DamageRecipe(axis_id="P03", variant=recipe.variant, level=0,
                                   recipe_id="P03_identity", params=dict(recipe.params),
                                   roi=dict(recipe.roi), basis=dict(recipe.basis),
                                   meta=dict(recipe.meta), qa=dict(recipe.qa))
    identity = apply_damage(clean_stub, fragment, identity_recipe, None)
    identity_audit = audit_physical(identity, clean)
    out["control_identity_level"] = {
        "shared_source_object": bool(identity.components[0].mesh is clean),
        "audit_status": identity_audit.get("status"),
        "audit_failure_codes": identity_audit.get("failure_codes"),
        "subset_check_as_shipped": (identity_audit.get("checks") or {}).get("damaged_subset_clean"),
    }

    global_result = apply_damage(clean_stub, fragment, recipe, None)
    narrow = run_narrowband_damage(clean, recipe, fragment=fragment)
    cache_dir.mkdir(parents=True, exist_ok=True)
    clean.export(cache_dir / "clean.ply")
    global_result.components[0].mesh.export(cache_dir / "global_body.ply")
    narrow.components[0].mesh.export(cache_dir / "narrowband_body.ply")
    out["cache"] = {"dir": str(cache_dir), "files": ["clean.ply", "global_body.ply",
                                                     "narrowband_body.ply"]}
    out["global_body"] = instruments(global_result.components[0].mesh, clean, n=20000, seed=2)
    out["narrowband_body"] = instruments(narrow.components[0].mesh, clean, n=20000, seed=3)
    for name, entry in (("global_body", out["global_body"]),
                        ("narrowband_body", out["narrowband_body"])):
        entry["would_pass_exact"] = bool(
            entry["trimesh_exact"]["max_outside_mm"] <= max(TOL_MM, 5e-4))
        entry["would_pass_open3d"] = bool(
            entry["open3d_approx"]["max_outside_mm"] <= max(TOL_MM, 5e-4))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True)
    parser.add_argument("--lineage", default="LIN0000_V02_M01_PAT02")
    parser.add_argument("--recipe", default="P03_depth_light")
    parser.add_argument("--config", default="configs/a12/sandbox.yaml")
    parser.add_argument("--out", default="data/a12/reports/a09_subset_instrument.json")
    parser.add_argument("--cache", default="data/a12/reports/a09_cache")
    args = parser.parse_args()
    report = probe(Path(args.store), args.lineage, args.recipe, Path(args.config),
                   Path(args.cache))
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
