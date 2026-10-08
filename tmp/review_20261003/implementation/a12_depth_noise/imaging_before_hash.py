import hashlib, json
import numpy as np
from synlab.observe.imaging import ImagingSpec, apply_imaging_chain
rng = np.random.default_rng(4)
scene = (np.random.default_rng(2).random((48,64,3))*0.4).astype(np.float32)
K=np.array([[50.,0,31.5],[0,50.,23.5],[0,0,1.]])
out=apply_imaging_chain(scene,K=K,dist=None,uncertain_mask=None,depth_z=None,focus_distance_mm=200.,rng=rng,spec=ImagingSpec())
print(json.dumps({k:hashlib.sha256(np.ascontiguousarray(getattr(out,k)).tobytes()).hexdigest() for k in ('linear','image','scene_linear')}))
