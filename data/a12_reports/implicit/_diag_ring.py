import sys, numpy as np
sys.path.insert(0, "tests/a12/fracture")
import fixtures as fx
from synlab.fracture import morphology as morph
from synlab.fracture.api import _default_basis
from synlab.fracture.implicit import field as ifield
from synlab.fracture.spec import FractureSpec
from synlab.materials.api import build_material_profile, default_material_params
from synlab.seeds import make_rng
from scipy import ndimage
mother = fx.box_mother((12.,12.,12.), mother_id="diag")
profile = build_material_profile("M01", default_material_params("M01"), make_rng(1,"m"))
basis = _default_basis(mother, make_rng(1,"b"), FractureSpec())
prep = morph.prepare_morphology(mother, material_profile=profile, rng=make_rng(1,"p"), basis=basis, event_id="d")
tris = np.asarray(prep["tris_uv"], dtype=float).reshape(-1,3,2)
s, info = ifield.boundary_samples_uv(tris, max_step_mm=0.05*0.065)
print("dense boundary samples", s.shape, info)
# ring cells
step=0.065; pts=tris.reshape(-1,2); pad=12*step
bbox=(pts[:,0].min()-pad, pts[:,0].max()+pad, pts[:,1].min()-pad, pts[:,1].max()+pad)
u0,v0=bbox[0],bbox[2]; nu=int(np.ceil((bbox[1]-u0)/step))+1; nv=int(np.ceil((bbox[3]-v0)/step))+1
inside = ifield.rasterize_triangles(tris,u0,v0,step,(nu,nv))
er = ndimage.binary_erosion(inside, structure=ndimage.generate_binary_structure(2,1), border_value=0)
ring = inside & ~er
ri, rj = np.nonzero(ring)
from scipy.spatial import cKDTree
# reconstruct the envelope's own field to get the base values
f, info2 = ifield.build_implicit_field(basis, mother.mesh, prep["base_params"], rng=make_rng(1,"f"),
    cross_section=(prep["tris_uv"], prep["core_area_mm2"], prep["cross_info"]), delta_mm=0.13)
env=f.envelope
val = f.unmasked(u0+ri*step, v0+rj*step)
print("ring cells", ri.size, "boundary_samples reported", env.boundary_samples)
order = np.argsort(np.arctan2(v0+rj*step-np.mean(v0+rj*step), u0+ri*step-np.mean(u0+ri*step)))
vv = val[order]
print("ring value range", vv.min(), vv.max())
d = np.abs(np.diff(vv))
print("max jump between angularly-adjacent ring cells", d.max(), "p99", np.percentile(d,99))
# also check B raster curvature near ring
off = env.offset_raster
idx = np.nonzero(inside)
print("B inside range", off[idx].min(), off[idx].max())
d2u = np.abs(np.diff(off,2,axis=0))/step**2
print("B raster curv max inside", d2u[idx[0][:-2], idx[1][:-2]].max() if idx[0].size>2 else 0)
ph = env.sign_raster
d2 = np.abs(np.diff(ph,2,axis=0))/step**2
print("phi raster curv max", d2[inside[:-2]].max())
print("phi range", ph[inside].min(), ph[inside].max(), "phi ring max", ph[ring].max())
