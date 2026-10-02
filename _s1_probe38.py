import numpy as np
from synlab.storage.store import AssetStore
from synlab.storage.export import load_projection_arrays, _obs_view_count
st = AssetStore(r"data\a12_trainable\store")
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
for side, oaid, mail in (("a","asset_22fadc3fd59d942bacd8","asset_1beedec77f25cbda2f2f"),
                         ("b","asset_60a0b55c09cfc4785213","asset_b7d01b160094c06eff9b")):
    M = st.load_arrays(mail); nf = np.asarray(M["mesh.faces"]).shape[0]
    A = load_projection_arrays(st, oaid)
    labels = set()
    for v in range(_obs_view_count(A)):
        labels |= set(np.unique(np.asarray(A[f"v{v:03d}.id_map"])).tolist())
    labels.discard(-1)
    FC = np.unique(np.asarray(ct[f"corr_face_{side}"]))
    print(f"side {side}: mesh_faces={nf} labels_in_idmap={len(labels)} labels_below_mesh_faces={sum(1 for x in labels if x<nf)}")
    # is the label set exactly [0, nf-1]?
    print(f"   labels == range(nf)? {labels == set(range(nf))}   label min={min(labels)} max={max(labels)}")
    # how many id_map labels are NOT valid mesh faces
    print(f"   labels beyond mesh face count: {sum(1 for x in labels if x>=nf)}")
    inter = len(set(FC.tolist()) & labels)
    print(f"   corr faces present: {inter}/{FC.size}  ratio={inter/FC.size:.3f}")
    # if we shift by an offset, is coverage better?
    best=(0,0)
    for off in range(-400, 400, 1):
        r = len({int(x)+off for x in FC.tolist()} & labels)/FC.size
        if r>best[1]: best=(off,r)
    print(f"   best constant offset: {best[0]} -> coverage {best[1]:.3f} (identity {inter/FC.size:.3f})")
