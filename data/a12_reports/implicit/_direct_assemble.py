import sys, time, traceback
sys.path.insert(0, "tests/a12/fracture")
import fixtures as fx
from synlab.materials.api import build_material_profile, default_material_params
from synlab.seeds import make_rng
from synlab.fracture.implicit.backend import build_implicit_cutter
print("building", flush=True)
mother = fx.box_mother((12.,12.,12.), mother_id="b")
prof = build_material_profile("M01", default_material_params("M01"), make_rng(1,"m"))
cutter, field, params, rep = build_implicit_cutter(mother, material_profile=prof, rng=make_rng(1,"b"),
    event_id="p", options={"max_sheet_triangles": 60000})
print("built", len(cutter.mesh.faces), flush=True)
from synlab.fracture.implicit.assembler import assemble_implicit_event
print("imported assembler", flush=True)
try:
    res = assemble_implicit_event(mother, cutter, event_id="p", backend="implicit_sheet_cut")
    print("event ok", len(res.fragments), len(res.interfaces), flush=True)
    for f in res.fragments:
        print(" frag", f.fragment_id, round(float(f.volume_mm3),4), len(f.mesh.faces), flush=True)
except Exception as exc:
    print("EXC", type(exc).__name__, exc, flush=True)
    traceback.print_exc()
