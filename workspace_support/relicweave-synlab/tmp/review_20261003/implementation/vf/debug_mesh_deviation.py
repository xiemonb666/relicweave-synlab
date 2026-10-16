import cadquery as cq
import numpy as np
from OCP.BRep import BRep_Tool
from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
from OCP.BRepTools import BRepTools
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.TopAbs import TopAbs_IN, TopAbs_ON
from OCP.gp import gp_Pnt2d
from OCP.gp import gp_Pnt

root = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261003\implementation\vf\artifacts\four_bands_absolute1"
with np.load(root + r"\geometry\surface.npz", allow_pickle=False) as arrays:
    vertices = arrays["vertices_mm"]
    faces = arrays["faces"]
shape = cq.importers.importStep(root + r"\geometry\solid.step").val()
from vesselforge.geometry import VesselSpec, build_vessel
source_shape = build_vessel(VesselSpec())
cad_faces = shape.Faces()
edge_set = set()
for a, b, c in faces:
    for i, j in ((int(a), int(b)), (int(b), int(c)), (int(c), int(a))):
        edge_set.add((min(i, j), max(i, j)))
samples = []
for a, b in sorted(edge_set):
    samples.append(("edge", (vertices[a].astype(float) + vertices[b].astype(float)) / 2))
for tri in faces:
    samples.append(("centroid", vertices[tri].astype(float).mean(axis=0)))
samples = samples[::max(1, len(samples) // 2500)]
results = []
for kind, point in samples:
    vertex = cq.Vertex.makeVertex(*point.tolist())
    distances = [vertex.distance(face) for face in cad_faces]
    index = int(np.argmin(distances))
    results.append((float(distances[index]), kind, point.tolist(), index, cad_faces[index].geomType(), cad_faces[index].Center().toTuple()))
for row in sorted(results, reverse=True)[:20]:
    print(row)
print("count", len(results), "quantiles", np.quantile([r[0] for r in results], [0, .5, .9, .99, 1]))
point = np.asarray([28.558934672263685, -2.5087219288692184, 14.554545037189497])
vertex = cq.Vertex.makeVertex(*point.tolist())
print("reported point min source", min(vertex.distance(face) for face in source_shape.Faces()))
print("reported point min STEP", min(vertex.distance(face) for face in shape.Faces()))
print("point source solid distance", vertex.distance(source_shape))
print("point step solid distance", vertex.distance(shape))
print("source-vs-step volume", source_shape.Volume(), shape.Volume())
print("source-vs-step bbox", source_shape.BoundingBox().xlen, shape.BoundingBox().xlen, source_shape.BoundingBox().ylen, shape.BoundingBox().ylen, source_shape.BoundingBox().zlen, shape.BoundingBox().zlen)
for label, candidate in (("source", source_shape), ("step", shape)):
    distances = [vertex.distance(face) for face in candidate.Faces()]
    idx = int(np.argmin(distances))
    face = candidate.Faces()[idx]
    print(label, "faces", len(candidate.Faces()), "nearest", distances[idx], idx, face.geomType(), face.Center().toTuple(), "area", face.Area(), "bbox", face.BoundingBox().xmin, face.BoundingBox().xmax, face.BoundingBox().zmin, face.BoundingBox().zmax)
print("paired face7 distance", source_shape.Faces()[7].distance(shape.Faces()[7]))
print("point to faces7", vertex.distance(source_shape.Faces()[7]), vertex.distance(shape.Faces()[7]))
print("face7 areas", source_shape.Faces()[7].Area(), shape.Faces()[7].Area())
print("face7 types", source_shape.Faces()[7].geomType(), shape.Faces()[7].geomType())
print("source bounds point distance", source_shape.Faces()[7].BoundingBox().xmin, source_shape.Faces()[7].BoundingBox().xmax, source_shape.Faces()[7].BoundingBox().zmin, source_shape.Faces()[7].BoundingBox().zmax)
print("step bounds point distance", shape.Faces()[7].BoundingBox().xmin, shape.Faces()[7].BoundingBox().xmax, shape.Faces()[7].BoundingBox().zmin, shape.Faces()[7].BoundingBox().zmax)
for label, candidate in (("source", source_shape), ("step", shape)):
    surf = BRep_Tool.Surface_s(candidate.Faces()[7].wrapped)
    basis = surf.BasisSurface() if hasattr(surf, "BasisSurface") else surf
    proj = GeomAPI_ProjectPointOnSurf(gp_Pnt(*point.tolist()), basis)
    print(label, type(surf), type(basis), "project_count", proj.NbPoints(), "supporting_surface_dist", proj.LowerDistance())
    print(label, "uv_bounds", BRepTools.UVBounds_s(candidate.Faces()[7].wrapped), "project_params", proj.LowerDistanceParameters())
    surf0 = BRep_Tool.Surface_s(candidate.Faces()[7].wrapped)
    proj0 = GeomAPI_ProjectPointOnSurf(gp_Pnt(*point.tolist()), surf0)
    print(label, "face_surface", type(surf0), "project0_count", proj0.NbPoints())
    for i in range(1, proj0.NbPoints() + 1):
        uv = proj0.Parameters(i)
        classifier = BRepClass_FaceClassifier(candidate.Faces()[7].wrapped, gp_Pnt2d(*uv), 1e-7)
        print(label, "candidate", i, "uv", uv, "distance", proj0.Distance(i), "state", classifier.State(), "is_in_on", classifier.State() in (TopAbs_IN, TopAbs_ON))
    dss = BRepExtrema_DistShapeShape(vertex.wrapped, candidate.Faces()[7].wrapped)
    dss.Perform()
    print(label, "BRepExtrema", dss.IsDone(), dss.Value())
