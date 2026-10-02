import time, numpy as np
from synlab.storage.store import AssetStore
from synlab.storage.export import load_projection_arrays
st = AssetStore(r"data\a12_trainable\store")
t=time.time(); a = load_projection_arrays(st, "asset_22fadc3fd59d942bacd8"); print("load_projection_arrays: %.2fs, %d arrays, %.1f MB" % (time.time()-t, len(a), sum(v.nbytes for v in a.values())/1e6))
print(sorted(a)[:6])
T = np.asarray(a["v000.T_WC"], float)
t=time.time()
for _ in range(2000): np.linalg.inv(T)
print("2000x inv(4x4): %.3fs" % (time.time()-t))
