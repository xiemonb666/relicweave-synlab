import sys
sys.path.insert(0,'.'); sys.path.insert(0,'tests/a12/observe')
import numpy as np
from _run_fracture_roi import STUDY, load_target
from _run_fracture_appearance import patch_faces
from synlab.observe import fracture_appearance as fa
from synlab.observe import routes as rt
import trimesh
target, body = load_target(STUDY[0])
mesh = target.mesh
print("vertices", np.asarray(mesh.vertices).shape, "faces", np.asarray(mesh.faces).shape)
for iid in (6, 7, 1):
    f = patch_faces(mesh, iid)
    print("iface", iid, "nfaces", f.shape, f.dtype, f[:5])
