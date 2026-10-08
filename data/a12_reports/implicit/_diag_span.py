import sys, numpy as np
sys.path.insert(0, "tests/a12/fracture")
import fixtures as fx
from synlab.materials.api import build_material_profile, default_material_params
from synlab.seeds import make_rng
from synlab.fracture.implicit.backend import build_implicit_cutter
from synlab.fracture.implicit.assembler import assemble_implicit_event, sheet_distance
mother = fx.box_mother((12.,12.,12.), mother_id="b")
prof = build_material_profile("M01", default_material_params("M01"), make_rng(1,"m"))
cutter, field, params, rep = build_implicit_cutter(mother, material_profile=prof, rng=make_rng(1,"b"),
    event_id="p", options={"max_sheet_triangles": 60000})
b = cutter.basis
M = np.stack([b.e_u,b.e_v,b.normal],0); o = np.asarray(b.origin)
loc = lambda P: (np.asarray(P,dtype=float)-o) @ M.T
print("frame u", b.u_range, "v", b.v_range)
ml = loc(mother.mesh.vertices)
print("mother local u", ml[:,0].min(), ml[:,0].max(), "v", ml[:,1].min(), ml[:,1].max(), "w", ml[:,2].min(), ml[:,2].max())
cl = loc(cutter.mesh.vertices)
print("cutter local u", cl[:,0].min(), cl[:,0].max(), "v", cl[:,1].min(), cl[:,1].max(), "w", cl[:,2].min(), cl[:,2].max())
print("cutter meta plan", rep["sampling_plan"]["delta_final_mm"], rep["sheet"]["axis_u"]["lo"], rep["sheet"]["axis_u"]["hi"])
res = assemble_implicit_event(mother, cutter, event_id="p", backend="implicit_sheet_cut")
small = [f for f in res.fragments if f.fragment_id.endswith("c1")][0]
sl = loc(small.mesh.vertices)
print("small piece local u", sl[:,0].min(), sl[:,0].max(), "v", sl[:,1].min(), sl[:,1].max(), "w", sl[:,2].min(), sl[:,2].max())
# distance of the small piece's vertices to the sheet
d,_ = sheet_distance(b, cutter.h_fn, small.mesh.vertices)
print("small piece |w-h| min/max", d.min(), d.max())
d2,_ = sheet_distance(b, cutter.h_fn, mother.mesh.vertices)
print("mother |w-h| min/max", d2.min(), d2.max())
# how many mother vertices lie beyond the frame in u/v?
print("mother verts outside frame u:", int(((ml[:,0]<b.u_range[0])|(ml[:,0]>b.u_range[1])).sum()),
      "v:", int(((ml[:,1]<b.v_range[0])|(ml[:,1]>b.v_range[1])).sum()))
