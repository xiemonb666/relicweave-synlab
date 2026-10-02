import numpy as np, json
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
cases = (("asset_1beedec77f25cbda2f2f","a"), ("asset_b7d01b160094c06eff9b","b"))
for aid, side in cases:
    arr = st.load_arrays(aid)
    V = np.asarray(arr["mesh.vertices"], dtype=np.float64)
    F = np.asarray(arr["mesh.faces"], dtype=np.int64)
    P = np.asarray(ct[f"corr_point_{side}"], dtype=np.float64)
    FC = np.asarray(ct[f"corr_face_{side}"], dtype=np.int64)
    B = np.asarray(ct[f"corr_bary_{side}"], dtype=np.float64)
    print("===", side, "verts", V.shape, "faces", F.shape, "corr", P.shape, "face idx max", FC.max(), "bary sum med", float(np.median(B.sum(1))))
    tri = V[F[FC]]                      # [n,3,3]
    recon = (tri * B[:,:,None]).sum(1)
    d = np.linalg.norm(recon - P, axis=1)
    print("   reconstruct from (face,bary) vs corr_point: max %.3g med %.3g" % (d.max(), np.median(d)))
    # is corr_point on the triangle plane / inside?
    e1 = tri[:,1]-tri[:,0]; e2 = tri[:,2]-tri[:,0]
    nrm = np.cross(e1,e2); nrm /= np.linalg.norm(nrm,axis=1,keepdims=True)
    dist_plane = np.abs(((P-tri[:,0])*nrm).sum(1))
    print("   dist to face plane: max %.3g med %.3g" % (dist_plane.max(), np.median(dist_plane)))
    print("   bary in [0,1]:", bool(((B>=-1e-9)&(B<=1+1e-9)).all()), " min", float(B.min()), "max", float(B.max()))
