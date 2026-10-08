import sys, numpy as np
sys.path.insert(0, "tests/a12/fracture")
import fixtures as fx
from synlab.materials.api import build_material_profile, default_material_params
from synlab.seeds import make_rng
from synlab.fracture.implicit.backend import build_implicit_cutter
from synlab.fracture.implicit.assembler import assemble_implicit_event
mother = fx.box_mother((12.,12.,12.), mother_id="b")
prof = build_material_profile("M01", default_material_params("M01"), make_rng(1,"m"))
cutter, field, params, rep = build_implicit_cutter(mother, material_profile=prof, rng=make_rng(1,"b"),
    event_id="p", options={"max_sheet_triangles": 60000})
res = assemble_implicit_event(mother, cutter, event_id="p", backend="implicit_sheet_cut")
print("volume sum", sum(float(f.volume_mm3) for f in res.fragments), "mother", float(abs(mother.mesh.volume)))
for f in res.fragments:
    o = np.asarray(f.face_origin_kind); a = np.asarray(f.mesh.area_faces)
    import collections
    hist = collections.Counter(o.tolist())
    src = np.asarray(f.face_source_tri); mid = np.asarray(f.meta["mesh_id_per_face"])
    mapped = int(np.sum((o==0)&(src>=0))) + int(np.sum(o==1))
    print(f"  {f.fragment_id}: vol={float(f.volume_mm3):.3f} faces={len(o)} origins={dict(hist)} "
          f"coverage={mapped/len(o):.6f} mother_area={a[o==0].sum():.2f} iface_area={a[o==1].sum():.2f} amb_area={a[o==2].sum():.4f}")
    bad = np.nonzero((o==0)&(src<0))[0]
    print(f"    mother faces with source<0: {bad.size}; mesh_id hist on those: "
          f"{np.bincount(mid[bad].clip(0,2), minlength=3).tolist() if bad.size else []}")
for p in res.interfaces:
    d = np.linalg.norm(p.sample_points_a - p.sample_points_b, axis=1)
    print(f"  patch {p.interface_id} area={float(p.area_mm2):.4f} gap_p95={p.gap_p95_mm:.3e} "
          f"gap_max={float(p.meta['gap_max_mm']):.3e} normal_p95={p.normal_angle_p95_deg:.3e} "
          f"area_rel={float(p.meta['area_rel_error']):.3e} pairs={p.meta['pair_count']}")
    print(f"    conjugate point distance p50={np.percentile(d,50):.3e} p95={np.percentile(d,95):.3e} max={d.max():.3e}")
