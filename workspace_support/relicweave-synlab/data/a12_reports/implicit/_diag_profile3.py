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
print("slope after deg", round(info["slope"]["after"]["angle_p95_deg"],2), "scale", round(info["slope"]["amplitude_scale_applied"],5),
      "| ring max", round(info["ring"]["boundary_height_max_mm"],6), "| phi_max", round(env.phi_max_inside,3))
u = np.linspace(6.55, 6.80, 400); v = np.full(400, 1.6682158732614671)
dome, relief = f._parts(u,v)
base = dome + relief
phi = env.mask(u,v); B = env.offset(u,v)
h = f(u,v)
d = u[1]-u[0]
def curve(a): return np.abs(np.diff(a,2))/d**2
for name, arr in (("h",h),("base",base),("phi",phi),("B",B),("base-B",base-B)):
    c = curve(arr); print(f"{name:8s} range[{arr.min(): .4f},{arr.max(): .4f}] curv_max={c.max(): .1f} /mm at u={u[1:-1][np.argmax(c)]:.4f}")
print("curv(h)<= 0.125*C*d^2 ->", 0.125*curve(h).max()*(0.13**2))
i = int(np.argmax(curve(h)))
for k in range(max(0,i-8), min(400,i+9)):
    print(f"  u={u[k]:7.4f} h={h[k]: .6f} phi={phi[k]: .5f} base={base[k]: .5f} B={B[k]: .5f}")
