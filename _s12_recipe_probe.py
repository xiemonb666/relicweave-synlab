import json, sys
from types import SimpleNamespace
import numpy as np
from synlab.config import load_generation_spec
from synlab.degrade.registry import get_operator
from synlab.pipeline import _load_damage_recipe
from synlab.storage.store import AssetStore
from synlab.roles import ROLE_FRAGMENT_MESH

store = AssetStore("data/a12_degrade/store")
assets = store.list_assets(role=ROLE_FRAGMENT_MESH, limit=100000)
best = max(assets, key=lambda r: float(abs(store.load_mesh(r.asset_id, "mesh").volume)))
mesh = store.load_mesh(best.asset_id, "mesh")
frag = SimpleNamespace(mesh=mesh, fragment_id=str(best.meta.get("fragment_id")), volume_mm3=float(abs(mesh.volume)), is_tiny=False, meta={"material_id": ""})
spec = load_generation_spec("configs/a12/sandbox.yaml")
data = json.load(open("configs/a12/physical_recipes.json", encoding="utf-8"))
for r in data["recipes"]:
    rid = r["recipe_id"]; op = r["operators"][0]
    axis = op["axis_id"]; variant = op.get("variant","")
    try:
        reg = get_operator(axis)
        resolved = reg.resolve_variant(variant or None)
        status = f"OK resolved={resolved}"
    except Exception as exc:
        status = f"VARIANT_FAIL {type(exc).__name__}: {exc}"
    try:
        recipe = _load_damage_recipe(rid, spec, fragment=frag, master_seed=spec.master_seed, lineage_id="lin_probe")
        load = f"recipe ok axis={recipe.axis_id} variant={recipe.variant} level={recipe.level} basis_source={recipe.meta.get('basis_source')} grid={recipe.grid}"
    except Exception as exc:
        load = f"recipe FAIL {type(exc).__name__}: {exc}"
    print(f"{rid:<28} {axis} {variant:<24} {status} | {load}")
