"""Scratch: end-to-end plane cut smoke test."""
import sys
import time

import numpy as np
import trimesh

sys.path.insert(0, r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
sys.path.insert(0, r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tests\a12\fracture")

from fixtures import box_mother, thin_bowl_mother
from synlab.fracture.cut import build_basis, build_closed_cutter, make_height_field
from synlab.fracture.event import run_shared_cut
from synlab.schemas.runtime import CutterResult
from synlab.seeds import make_rng

t0 = time.time()
mother = box_mother((20.0, 20.0, 20.0))
print("mother faces", len(mother.mesh.faces), "volume", mother.mesh.volume,
      "watertight", mother.mesh.is_watertight)
basis = build_basis(np.asarray(mother.mesh.vertices), np.array([1.0, 0.0, 0.0]),
                    anchor=np.zeros(3))
print("basis origin", basis.origin, "e_u", basis.e_u, "e_v", basis.e_v, "n", basis.normal)
print("u_range", basis.u_range, "v_range", basis.v_range)
print("meta", {k: v for k, v in basis.meta.items() if k != "material_extent_mm"})
field = make_height_field(basis, make_rng(1, "cut", "plane"), target_rms_mm=0.0)
print("flat", field.is_flat)
mesh, report = build_closed_cutter(basis, field, error_budget_mm=0.01, max_cells=200000)
print("cutter faces", len(mesh.faces), "verts", len(mesh.vertices), "volume", mesh.volume,
      "watertight", mesh.is_watertight)
print("report", {k: v for k, v in report.items() if k != "height_field"})
earlier = time.time()
cutter = CutterResult(mesh=mesh, basis=basis, h_fn=field, requested_error_mm=0.01,
                      realized_error_mm=report["realized_error_mm"],
                      triangles=len(mesh.faces), meta={"cutter_hash": report["cutter_local_hash"]})
cutter.meta["cutter_hash"] = None
result = run_shared_cut(mother, cutter, event_id="E1", backend="plane_shared_cut")
print("cut in %.2fs" % (time.time() - earlier))
print("fragments", [(f.fragment_id, round(f.volume_mm3, 4), f.is_tiny) for f in result.fragments])
for patch in result.interfaces:
    print("interface", patch.interface_id, patch.fragment_a, patch.fragment_b,
          "area", round(patch.area_mm2, 4), "gap95", patch.gap_p95_mm,
          "angle95", patch.normal_angle_p95_deg, "amb", patch.ambiguity_area_ratio,
          "identity", patch.meta.get("vertex_identity_ratio"))
print("qa", {k: v for k, v in result.qa.items() if k not in ("failures",)})
print("elapsed %.2fs" % (time.time() - t0))
