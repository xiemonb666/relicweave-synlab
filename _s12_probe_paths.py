import io, json, sys
from synlab.degrade.api import probe_sources
from synlab.degrade.registry import AXIS_REGISTRY
src = probe_sources()
P = src["P"]
mesh = P.get("mesh")
print("mesh:", type(mesh).__name__, len(mesh.faces) if mesh is not None else None)
from synlab.physical.api import apply_damage
from synlab.degrade.axes import P03 as P03Axis, P02 as P02Axis, P04 as P04Axis
from synlab.degrade.registry import basis_rng
import numpy as np
for axis_cls in (P02Axis, P03Axis, P04Axis):
    op = AXIS_REGISTRY.get(axis_cls.AXIS_ID)
    ctx = {"source": P, "lineage_id": "lin_audit", "fragment_id": "frag", "master_seed": 1234}
    basis = op.sample_basis(ctx, np.random.default_rng(7), op.default_variant)
    rec = op.recipe(level=1, variant=op.default_variant, params=op.params_for(1, op.default_variant), basis=basis, fragment=__import__("synlab.degrade.axes", fromlist=["x"]).physical_fragment(P), source=P)
    print(axis_cls.AXIS_ID, "recipe grid:", rec.grid, "axis_id", rec.axis_id, "level", rec.level)
