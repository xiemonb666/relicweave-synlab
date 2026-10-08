import sys
sys.path.insert(0,'.'); sys.path.insert(0,'tests/a12/observe')
import numpy as np
from _run_fracture_roi import STUDY, load_target
from _run_fracture_appearance import patch_faces
from synlab.observe import fracture_appearance as fa
target, body = load_target(STUDY[0]); mesh = target.mesh
v = np.asarray(mesh.vertices); f = patch_faces(mesh, 6)
u, vv = fa.tangent_basis(np.array([0.0,0.0,1.0]))
print("u",u,"v",vv)
tri = v[f]
print("tri shape", tri.shape, "matmul", (tri @ u).shape)
out = fa._patch_triangles_uv(v, f, np.zeros(3), u, vv)
print("out", out.shape)
