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
env=f.envelope
print("scale", round(info["slope"]["amplitude_scale_applied"],4), "slope after", round(info["slope"]["after"]["angle_p95_deg"],2),
      "ring max", round(info["ring"]["boundary_height_max_mm"],6), "phi_max", round(env.phi_max_inside,3), "width", env.width_mm)
# line through the reported worst point, along u and along v
for axis in ("u","v"):
    n=600
    if axis=="u":
        u=np.linspace(6.2,7.0,n); v=np.full(n,-0.40088908582252436)
    else:
        u=np.full(n,6.608169683756); v=np.linspace(-0.9,-0.1,n)
    d=u[1]-u[0] if axis=="u" else v[1]-v[0]
    h=f(u,v); dome,relief=f._parts(u,v); phi=env.mask(u,v)
    c=lambda a: np.abs(np.diff(a,2))/d**2
    print(f"--- axis {axis} step {d:.5f}")
    for nm,arr in (("h",h),("phi",phi),("relief",relief),("dome",dome),("dome+relief",dome+relief)):
        cc=c(arr); k=int(np.argmax(cc))
        print(f"   {nm:12s} curv_max={cc.max():8.1f} /mm at {axis}={ (u if axis=='u' else v)[1:-1][k]:.4f}  range[{arr.min(): .4f},{arr.max(): .4f}]")
    cc=c(h); k=int(np.argmax(cc))
    lo=max(0,k-6); hi=min(n,k+8)
    for j in range(lo,hi):
        print(f"     {axis}={ (u if axis=='u' else v)[j]:7.4f} h={h[j]: .6f} phi={phi[j]: .4f} relief={relief[j]: .5f} dome={dome[j]: .5f}")
