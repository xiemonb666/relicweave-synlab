import sys, time, numpy as np, trimesh
sys.path.insert(0, "tests/a12/fracture")
import fixtures as fx
from synlab.materials.api import build_material_profile, default_material_params
from synlab.seeds import make_rng
from synlab.fracture.implicit.backend import build_implicit_cutter
print("has_embree", trimesh.ray.has_embree, "has_embree4", getattr(trimesh.ray, "has_embree4", None), flush=True)
mother = fx.box_mother((12.,12.,12.), mother_id="b")
prof = build_material_profile("M01", default_material_params("M01"), make_rng(1,"m"))
cutter, field, params, rep = build_implicit_cutter(mother, material_profile=prof, rng=make_rng(1,"b"),
    event_id="p", options={"max_sheet_triangles": 60000})
m = cutter.mesh
print("cutter faces", len(m.faces), flush=True)
rng = np.random.default_rng(0)
pts = rng.uniform(m.bounds[0], m.bounds[1], size=(40000,3))
for n in (1000, 4000, 16000):
    t=time.time(); r = m.contains(pts[:n]); dt=time.time()-t
    print(f"contains n={n} {dt:.3f}s  ({dt/n*1e6:.1f} us/pt)", flush=True)
t=time.time(); _c,_n,_t = m.nearest.on_surface(pts); print(f"nearest n=40000 {time.time()-t:.3f}s", flush=True)
