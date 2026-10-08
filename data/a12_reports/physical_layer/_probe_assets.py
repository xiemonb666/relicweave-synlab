import sys, json, time
sys.path.insert(0, '.')
from pathlib import Path
import numpy as np
from synlab.storage.store import AssetStore
from synlab.storage.mesh_io import arrays_to_mesh
out = {}
for store_name, asset_id, tag in [
    ("data/a12_iface/store", "asset_8ad98a2081675cc92587", "V02_M01"),
    ("data/a12_campaign/store", "asset_745a78313d0d5b045b3a", "V10_M11"),
    ("data/a12_campaign/store", "asset_aba4549620450f1f6adf", "V23_M07"),
]:
    st = AssetStore(Path(store_name))
    a = st.get_asset(asset_id)
    arr = st.load_arrays(asset_id)
    mesh, attrs = arrays_to_mesh(arr)
    d = {"asset": asset_id, "tag": tag,
         "array_keys": sorted(arr.keys()),
         "attr_keys": sorted(attrs.keys()),
         "n_vertices": int(np.asarray(mesh.vertices).shape[0]),
         "n_faces": int(np.asarray(mesh.faces).shape[0]),
         "asset_meta": {k: str(v) for k, v in (a.meta or {}).items()},
         }
    for k, v in attrs.items():
        vv = np.asarray(v)
        if vv.dtype.kind in "iu" and vv.ndim == 1 and vv.size == d["n_faces"]:
            u, c = np.unique(vv, return_counts=True)
            d[f"attr_hist_{k}"] = {int(x): int(y) for x, y in zip(u, c)}
    out[tag] = d
Path("data/a12_reports/physical_layer/probe_assets.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print("written")
