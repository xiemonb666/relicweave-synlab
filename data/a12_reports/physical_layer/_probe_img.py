import sys
sys.path.insert(0,'.')
import numpy as np
from synlab.observe import routes as rt
from synlab.observe.imaging import apply_imaging_chain, ImagingSpec
from synlab.seeds import make_rng
rgb = np.full((64,64,3), 0.5, dtype=np.float32)
K = np.array([[800.,0,32],[0,800.,32],[0,0,1.]])
depth = np.full((64,64), 60.0, dtype=np.float32)
spec = ImagingSpec()
a = apply_imaging_chain(rgb, K=K, dist=None, uncertain_mask=np.zeros((64,64),bool), depth_z=depth,
                        focus_distance_mm=60.0, rng=make_rng(1,"x"), spec=spec, camera_model="PINHOLE")
b = apply_imaging_chain(rgb, K=K, dist=None, uncertain_mask=np.zeros((64,64),bool), depth_z=depth,
                        focus_distance_mm=60.0, rng=make_rng(2,"y"), spec=spec, camera_model="PINHOLE")
print("image a unique", np.unique(a.image)[:8], a.image.dtype)
print("maxdiff", float(np.abs(a.image.astype(float)-b.image.astype(float)).max()))
print("linear a", float(a.linear.mean()), "scene_linear", float(a.scene_linear.mean()))
print("stages", [s["stage"] for s in a.stages])
