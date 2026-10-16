import sys, numpy as np
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
print("mother volume", float(abs(mother.mesh.volume)))
for f in res.fragments:
    o = np.asarray(f.face_origin_kind); a = np.asarray(f.mesh.area_faces)
    import collections
    print(f" {f.fragment_id:12s} vol={float(f.volume_mm3):9.3f} faces={len(f.mesh.faces):6d} "
          f"bounds={np.round(f.mesh.bounds,2).tolist()} iface_area={a[o==1].sum():8.3f} "
          f"mother_area={a[o==0].sum():8.3f} tiny={f.is_tiny}")
audit = audit_fracture(res, mother)
print("AUDIT", {k: (round(v,9) if isinstance(v,float) else v) for k,v in audit.items() if k in
      ('mother_volume_mm3','fragment_volume_sum_mm3','volume_rel_diff','overlap_ratio',
       'interface_count','gap_p95_mm_max','normal_angle_p95_deg_max','source_coverage',
       'ambiguous_area_ratio_max','interface_area_rel_error_max','faces_total','fragment_count','passed','failures')})
for p in res.interfaces:
    print(" patch", p.interface_id, p.fragment_a, p.fragment_b, "area", round(float(p.area_mm2),4),
          "gap_p95", p.gap_p95_mm, "normal_p95", p.normal_angle_p95_deg,
          "area_rel", round(float(p.meta['area_rel_error']),9), "pairs", p.meta['pair_count'],
          "samples", p.sample_points_a.shape)
    d = np.linalg.norm(p.sample_points_a - p.sample_points_b, axis=1)
    print("   conjugate point distance: p50", float(np.percentile(d,50)), "p95", float(np.percentile(d,95)), "max", float(d.max()))
