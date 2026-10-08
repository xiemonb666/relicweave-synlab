import numpy as np
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
print("bboxes:")
for k in ("corr_point_a","corr_point_b","iface_points_a","iface_points_b","corr_normal_a","corr_normal_b"):
    A = np.asarray(ct[k], np.float64)
    print(f"  {k:16s} n={A.shape[0]:5d} min={A.min(0).round(2)} max={A.max(0).round(2)}")
print("iface_offset:", np.asarray(ct["iface_offset"]))
print("iface_id:", np.asarray(ct["iface_id"]))
print("corr_interface_id uniq:", np.unique(np.asarray(ct["corr_interface_id"])))
print("corr_face_a uniq n:", np.unique(np.asarray(ct["corr_face_a"])).size, "corr_face_b uniq n:", np.unique(np.asarray(ct["corr_face_b"])).size)
d = np.linalg.norm(np.asarray(ct["corr_point_a"])-np.asarray(ct["corr_point_b"]),axis=1)
print("|corr_point_a - corr_point_b|: med %.4g max %.4g" % (np.median(d), d.max()))
dn = np.linalg.norm(np.asarray(ct["iface_points_a"])-np.asarray(ct["iface_points_b"]),axis=1)
print("|iface_points_a - iface_points_b|: med %.4g max %.4g" % (np.median(dn), dn.max()))
dp = np.linalg.norm(np.asarray(ct["corr_point_a"])-np.asarray(ct["iface_points_a"]),axis=1)
print("|corr_point_a - iface_points_a|: med %.4g max %.4g" % (np.median(dp), dp.max()))
