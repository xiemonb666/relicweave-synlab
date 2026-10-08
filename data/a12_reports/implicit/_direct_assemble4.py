import sys, numpy as np, time
sys.path.insert(0, "tests/a12/fracture")
import fixtures as fx
from synlab.materials.api import build_material_profile, default_material_params
from synlab.seeds import make_rng
from synlab.fracture.implicit.backend import build_implicit_cutter
from synlab.fracture.implicit.assembler import assemble_implicit_event
from synlab.fracture.api import audit_fracture
mother = fx.box_mother((12.,12.,12.), mother_id="b")
prof = build_material_profile("M01", default_material_params("M01"), make_rng(1,"m"))
cutter, field, params, rep = build_implicit_cutter(mother, material_profile=prof, rng=make_rng(1,"b"),
    event_id="p", options={"max_sheet_triangles": 60000})
res = assemble_implicit_event(mother, cutter, event_id="p", backend="implicit_sheet_cut")
t=time.time(); audit = audit_fracture(res, mother); print("audit seconds", round(time.time()-t,1))
keys = ('mother_volume_mm3','fragment_volume_sum_mm3','volume_rel_diff','volume_tolerance','overlap_ratio','overlap_tolerance',
        'interface_count','gap_p95_mm_max','normal_angle_p95_deg_max','source_coverage','ambiguous_area_ratio_max',
        'ambiguous_area_ratio_total','interface_area_rel_error_max','faces_total','fragment_count','passed','failures')
for k in keys:
    v = audit.get(k)
    print(f"  {k} = {round(v,12) if isinstance(v,float) else v}")
