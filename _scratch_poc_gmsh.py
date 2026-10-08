"""PoC variants for gmsh internal-face fragmentation."""
import gmsh

gmsh.initialize()
gmsh.option.setNumber("General.Terminal", 0)
gmsh.model.add("poc")
occ = gmsh.model.occ
box = occ.addBox(-5, -5, -5, 10, 10, 10)
pads = 6.0
p1 = occ.addRectangle(2.0, -5 - pads, -5 - pads, 2 * pads, 2 * pads)
occ.synchronize()
print("entities", gmsh.model.getEntities())
print("plane bbox", occ.getBoundingBox(2, p1))
print("box bbox", occ.getBoundingBox(3, box))

print("-- intersect(plane, box) --")
try:
    out, m = occ.intersect([(2, p1)], [(3, box)], removeObject=False, removeTool=False)
    occ.synchronize()
    print("   ->", out, "vols", gmsh.model.getEntities(3), "surfs", len(gmsh.model.getEntities(2)))
except Exception as exc:
    print("   ERR", type(exc).__name__, exc)

print("-- try addSurfaceFilling / addPlaneSurface from a wire --")
gmsh.model.add("poc2")
occ2 = gmsh.model.occ
b2 = occ2.addBox(-5, -5, -5, 10, 10, 10)
# build a big wire rectangle in plane x=2 by hand
q = 8.0
pts = [occ2.addPoint(2.0, -5 - q, -5 - q), occ2.addPoint(2.0, 5 + q, -5 - q),
       occ2.addPoint(2.0, 5 + q, 5 + q), occ2.addPoint(2.0, -5 - q, 5 + q)]
ls = [occ2.addLine(pts[i], pts[(i + 1) % 4]) for i in range(4)]
cl = occ2.addCurveLoop(ls)
s = occ2.addPlaneSurface([cl])
occ2.synchronize()
print("   surface bbox", occ2.getBoundingBox(2, s))
out, m = occ2.fragment([(3, b2)], [(2, s)])
occ2.synchronize()
print("   fragment ->", out, "vols", gmsh.model.getEntities(3))
for dim, tag in gmsh.model.getEntities(3):
    print("     vol", tag, occ2.getBoundingBox(3, tag), "mass", occ2.getMass(3, tag))
gmsh.finalize()
