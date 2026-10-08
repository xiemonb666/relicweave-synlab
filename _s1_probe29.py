import numpy as np
from synlab.storage.store import AssetStore
from synlab.storage.export import load_projection_arrays, _obs_view_count
st = AssetStore(r"data\a12_trainable\store")
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
for side, maid, oaid in (("a","asset_1beedec77f25cbda2f2f","asset_22fadc3fd59d942bacd8"),
                         ("b","asset_b7d01b160094c06eff9b","asset_60a0b55c09cfc4785213")):
    M = st.load_arrays(maid); V = np.asarray(M["mesh.vertices"]); F = np.asarray(M["mesh.faces"])
    FC = np.asarray(ct[f"corr_face_{side}"])
    print(f"side {side}: mesh faces {F.shape[0]}, corr_face range [{FC.min()},{FC.max()}], unique {np.unique(FC).size}")
    # id_map value range for the paired observation
    A = load_projection_arrays(st, oaid)
    nv = _obs_view_count(A); vals = set()
    for v in range(nv):
        im = np.asarray(A[f"v{v:03d}.id_map"])
        vals |= set(np.unique(im).tolist())
    vals.discard(-1)
    print(f"   obs id_map distinct labels {len(vals)}, range [{min(vals)},{max(vals)}]")
    inter = set(FC.tolist()) & vals
    print(f"   corr faces present in this obs id_map: {len(inter)} / {np.unique(FC).size}")
    # does the OTHER side's corr faces appear here?
    other = "b" if side=="a" else "a"
    FC2 = np.asarray(ct[f"corr_face_{other}"])
    inter2 = set(FC2.tolist()) & vals
    print(f"   OTHER side corr faces present here:    {len(inter2)} / {np.unique(FC2).size}")
