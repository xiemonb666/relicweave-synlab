import numpy as np, json
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
for k in ("corr_normal_a","corr_normal_b"):
    A = np.asarray(ct[k], np.float64)
    print(k, "first 5:", A[:5].round(4).tolist())
    print(k, "unique rows:", np.unique(A, axis=0).shape[0], " std:", A.std(0).round(6).tolist())
# how far are corr points from facet planes of each mesh (interface faces only)?
for aid, side in (("asset_1beedec77f25cbda2f2f","a"),("asset_b7d01b160094c06eff9b","b")):
    m = st.load_arrays(aid)
    V = np.asarray(m["mesh.vertices"], np.float64); F = np.asarray(m["mesh.faces"], np.int64)
    FC = np.asarray(ct[f"corr_face_{side}"], np.int64); B = np.asarray(ct[f"corr_bary_{side}"], np.float64)
    P = np.asarray(ct[f"corr_point_{side}"], np.float64)
    tri = V[F[FC]]
    nrm = np.cross(tri[:,1]-tri[:,0], tri[:,2]-tri[:,0]); nn = np.linalg.norm(nrm,axis=1,keepdims=True)
    nrm = nrm/np.maximum(nn,1e-15)
    dist = np.abs(((P-tri[:,0])*nrm).sum(1))
    inside = ((B>=-1e-9)&(B<=1+1e-9)).all(1)
    print(f"mesh_{side}: n_faces {F.shape[0]} corr_face max {FC.max()} | dist to its own corr face plane med {np.median(dist):.3g} max {dist.max():.3g} | bary inside {inside.mean():.3f}")
    # do the other side's faces contain these points too?
    FC2 = np.asarray(ct[f"corr_face_{'b' if side=='a' else 'a'}"], np.int64)
    tri2 = V[F[FC2]]; n2 = np.cross(tri2[:,1]-tri2[:,0], tri2[:,2]-tri2[:,0]); n2 = n2/np.maximum(np.linalg.norm(n2,axis=1,keepdims=True),1e-15)
    d2 = np.abs(((P-tri2[:,0])*n2).sum(1))
    print(f"          dist to OTHER side's face index within THIS mesh: med {np.median(d2):.3g} max {d2.max():.3g}")
