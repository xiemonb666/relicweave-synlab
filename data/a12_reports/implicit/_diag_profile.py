import sys, numpy as np
sys.path.insert(0, "tests/a12/fracture")
import fixtures as fx
from synlab.fracture import morphology as morph
from synlab.fracture.api import _default_basis
from synlab.fracture.implicit import field as ifield
from synlab.fracture.spec import FractureSpec
from synlab.materials.api import build_material_profile, default_material_params
from synlab.seeds import make_rng
mother = fx.box_mother((12.,12.,12.), mother_id="diag")
profile = build_material_profile("M01", default_material_params("M01"), make_rng(1,"m"))
basis = _default_basis(mother, make_rng(1,"b"), FractureSpec())
prep = morph.prepare_morphology(mother, material_profile=profile, rng=make_rng(1,"p"), basis=basis, event_id="d")
f, info = ifield.build_implicit_field(basis, mother.mesh, prep["base_params"], rng=make_rng(1,"f"),
    cross_section=(prep["tris_uv"], prep["core_area_mm2"], prep["cross_info"]), delta_mm=0.13)
env = f.envelope
u = np.full(200, -0.4296); v = np.linspace(-8.3, -6.6, 200)
h = f(u,v)
# raw morphology (no envelope)
saved = f.envelope; f.envelope = None
raw = f.raw(u,v); f.envelope = saved
phi = env.smoothness(u,v); B = ifield.bilinear_lookup(env.offset_raster, env.u0, env.v0, env.step_mm, u, v)
d = np.diff(v)[0]
for name, arr in (("h",h),("raw",raw),("phi",phi),("B",B)):
    d2 = np.diff(arr,2)/d**2
    print(f"{name:4s} min={arr.min(): .5f} max={arr.max(): .5f} | curv_max={np.abs(d2).max(): .3f} /mm")
print()
print("  v      h        raw      phi      B")
for k in range(0, 200, 8):
    print(f"{v[k]:7.3f} {h[k]: .5f} {raw[k]: .5f} {phi[k]: .4f} {B[k]: .5f}")
