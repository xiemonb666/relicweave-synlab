import numpy as np, json
from synlab.storage.store import AssetStore
from synlab.storage.export import load_projection_arrays, _obs_view_count
st = AssetStore(r"data\a12_trainable\store")
pairs = [("LIN0009_V04_M01_PAT02_E01-m","LIN0009_V04_M01_PAT02_E01-p"),
         ("LIN0010_V07_M10_PAT08_E01-m","LIN0010_V07_M10_PAT08_E01-p"),
         ("LIN0012_V03_M02_PAT01_E01-m","LIN0012_V03_M02_PAT01_E01-p"),
         ("LIN0013_V11_M02_PAT07_E01-m","LIN0013_V11_M02_PAT07_E01-p")]
obs = {}
for r in st.list_assets(role="obs_result", limit=500):
    fid = (r.meta or {}).get("fragment_id")
    if fid: obs.setdefault(fid, r.asset_id)
meshes = {}
for r in st.list_assets(role="fragment_mesh", limit=500):
    fid = (r.meta or {}).get("fragment_id")
    if fid: meshes.setdefault(fid, r.asset_id)
# truth asset per lineage
truth = {}
for r in st.list_assets(role="clean_truth", limit=500):
    truth.setdefault(r.lineage_id, []).append(r.asset_id)
for a, b in pairs:
    lin = a.rsplit("_E01",1)[0]
    print("===", lin)
    for aid in truth.get(lin, []):
        ct = st.load_arrays(aid)
        if "corr_face_a" not in ct: continue
        print("   truth", aid, "n_corr", np.asarray(ct["corr_face_a"]).size)
        for side, fid in (("a", a), ("b", b)):
            FC = np.asarray(ct[f"corr_face_{side}"])
            m = meshes.get(fid); o = obs.get(fid)
            nf = "-"
            if m:
                nf = np.asarray(st.load_arrays(m)["mesh.faces"]).shape[0]
            labels = set()
            if o:
                A = load_projection_arrays(st, o)
                for v in range(_obs_view_count(A)):
                    labels |= set(np.unique(np.asarray(A[f"v{v:03d}.id_map"])).tolist())
                labels.discard(-1)
            inter = len(set(FC.tolist()) & labels) if labels else 0
            print(f"   side {side} {fid[-6:]}: mesh_faces={nf} obs_labels={len(labels)}"
                  f" max_label={max(labels) if labels else '-'}"
                  f" corr_faces_in_idmap={inter}/{np.unique(FC).size}")
