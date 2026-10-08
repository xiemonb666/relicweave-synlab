import numpy as np
from synlab.storage.store import AssetStore
st = AssetStore(r"data\a12_trainable\store")
ct = st.load_arrays("asset_bd3812b8c9b5059ac091")
m = st.load_arrays("asset_1beedec77f25cbda2f2f")
V = np.asarray(m["mesh.vertices"], np.float64); F = np.asarray(m["mesh.faces"], np.int64)
FC = np.asarray(ct["corr_face_a"], np.int64)
tri = V[F[FC]]
e1 = tri[:,1]-tri[:,0]; e2 = tri[:,2]-tri[:,0]
def tri_dist(p0, A, B, C):
    # 3D point-triangle distance (vectorised, Ericson)
    ab=B-A; ac=C-A; ap=p0-A
    d1=(ab*ap).sum(1); d2=(ac*ap).sum(1)
    bp=p0-B; d3=(ab*bp).sum(1); d4=(ac*bp).sum(1)
    cp=p0-C; d5=(ab*cp).sum(1); d6=(ac*cp).sum(1)
    vc=d1*d4-d3*d2; vb=d5*d2-d1*d6; va=d3*d6-d5*d4
    denom=va+vb+vc
    out=np.zeros(p0.shape[0])
    # vertex regions
    mA=(d1<=0)&(d2<=0); out[mA]=np.linalg.norm(p0[mA]-A[mA],axis=1)
    mB=(d3>=0)&(d4<=d3); out[mB]=np.linalg.norm(p0[mB]-B[mB],axis=1)
    mC=(d6>=0)&(d5<=d6); out[mC]=np.linalg.norm(p0[mC]-C[mC],axis=1)
    vcA=(vc<=0)&(d1>=0)&(d3<=0); t=np.where(np.abs(d1-d3)>1e-15,(d1)/(d1-d3),0.0)
    P=A+ (B-A)*t[:,None]; out[vcA]=np.linalg.norm(p0[vcA]-P[vcA],axis=1)
    print("   tri_dist done (sampled)", out.shape)
    return out
print("mesh_a has corr faces", np.unique(FC).size, "of", F.shape[0])
for aid, nm in (("asset_22fadc3fd59d942bacd8","obsA"),("asset_60a0b55c09cfc4785213","obsB")):
    arr = st.load_arrays(aid); P = np.asarray(arr["points"], np.float64)
    print("===", nm, "cloud", P.shape)
    # distance from every cloud point to the correspondence facet set of mesh_a (sampled cloud)
    idx = np.linspace(0, P.shape[0]-1, 4000).astype(int); Q = P[idx]
    A=tri[:,0]; B=tri[:,1]; C=tri[:,2]
    # brute force over 529 unique faces in chunks
    U = np.unique(FC)
    dmin = np.full(Q.shape[0], np.inf)
    for j in U:
        i = np.where(FC==j)[0][0]
        d = tri_dist(Q, tri[i,0][None].repeat(Q.shape[0],0), tri[i,1][None].repeat(Q.shape[0],0), tri[i,2][None].repeat(Q.shape[0],0))
        dmin = np.minimum(dmin, d)
    print("   cloud->interface-facet dist: min %.4g med %.4g p95 %.4g" % (dmin.min(), np.median(dmin), np.percentile(dmin,95)))
    print("   frac cloud pts within 0.05mm of interface facet: %.4f  within 0.5mm: %.4f" % ((dmin<0.05).mean(), (dmin<0.5).mean()))
