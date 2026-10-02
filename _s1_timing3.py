import time, numpy as np, cProfile, pstats, io
from synlab.storage.store import AssetStore
from synlab.storage.export import _project_point_into_view, _obs_view_count, load_projection_arrays
st = AssetStore(r"data\a12_trainable\store")
a = load_projection_arrays(st, "asset_22fadc3fd59d942bacd8")
nv = _obs_view_count(a); print("views", nv, flush=True)
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
P = np.asarray(ct["corr_point_a"], np.float64)
t=time.time()
for i in range(20):
    for v in range(nv):
        _project_point_into_view(a, v, P[i])
print("20 pts x %d views = %.2fs (=> 552 pts would be %.1fs)" % (nv, time.time()-t, (time.time()-t)/20*552), flush=True)
# which part?
K = np.asarray(a["v000.K"], float); T = np.asarray(a["v000.T_WC"], float)
D = np.asarray(a["v000.depth_z"]); I = np.asarray(a["v000.id_map"]); R = np.asarray(a["v000.roi"])
print("dtypes: depth", D.dtype, "id", I.dtype, "roi", R.dtype, "shapes", D.shape, I.shape)
t=time.time()
for _ in range(100): x = np.linalg.inv(T) @ np.append(P[0], 1.0)
print("100x inv+matvec: %.4fs" % (time.time()-t))
t=time.time()
for _ in range(100): y = np.asarray(a["v000.depth_z"])
print("100x np.asarray(depth_z): %.4fs" % (time.time()-t))
