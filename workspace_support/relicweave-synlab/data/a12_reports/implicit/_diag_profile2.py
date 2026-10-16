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
print("slope before/after deg:", round(info["slope"]["before"]["angle_p95_deg"],2), round(info["slope"]["after"]["angle_p95_deg"],2), "scale", round(info["slope"]["amplitude_scale_applied"],5))
print("ring:", {k: round(v,6) if isinstance(v,float) else v for k,v in info["ring"].items()})
print("env residual", round(env.extension_residual_mm,5), "iters", env.extension_iterations, "phi_res", env.phi_residual)
u = np.linspace(5.2, 8.0, 200); v = np.full(200, 1.6682158732614671)
dome, relief = f._parts(u, v)
h = f(u,v)
phi = env.mask(u,v); Br = env.offset(u,v); Bd = env.dome_offset(u,v)
d = u[1]-u[0]
print(f"step {d:.4f}")
for name, arr in (("h",h),("dome",dome),("dome-Bd",dome-Bd),("relief",relief),("relief-Br",relief-Br),("phi",phi),("Br",Br),("Bd",Bd)):
    d2 = np.abs(np.diff(arr,2))/d**2
    print(f"{name:11s} min={arr.min(): .5f} max={arr.max(): .5f} curv_max={d2.max(): .2f} /mm  at u={u[1:-1][np.argmax(d2)]:.3f}")
i = int(np.argmax(np.abs(np.diff(h,2))))
print("hotspot k=",i, "u=",u[i])
for k in range(max(0,i-6), min(200,i+7)):
    print(f"  u={u[k]:7.4f} h={h[k]: .5f} phi={phi[k]: .4f} Br={Br[k]: .5f} Bd={Bd[k]: .5f} dome={dome[k]: .5f} relief={relief[k]: .5f}")
