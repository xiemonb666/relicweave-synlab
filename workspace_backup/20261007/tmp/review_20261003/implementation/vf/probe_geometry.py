import cadquery as cq

outer = [(0,0),(14,0),(14.8,2),(15.8,6),(17.8,12),(19.6,20),(20.5,28),(20,36),(18.8,44),(18,50),(18,56)]
inner = [(13.5,56),(13.5,50),(14.3,44),(15.5,36),(16,28),(15.1,20),(13.3,12),(11.3,6),(10.5,4),(0,4)]
body = cq.Workplane("XZ").polyline(outer+inner).close().revolve(360,(0,0,0),(0,1,0),combine=False).val()
path_wp = (cq.Workplane("XZ").moveTo(17,12).lineTo(25,12)
        .threePointArc((28.535533906,13.464466094),(30,17))
        .lineTo(30,39)
        .threePointArc((28.535533906,42.535533906),(25,44))
        .lineTo(18,44))
path = path_wp.wire().val()
print("wire",path.Length(),len(path.Edges()),path.Edges()[0].tangentAt(0).toTuple())
plane = cq.Plane(origin=(17,0,12),xDir=(0,1,0),normal=path.Edges()[0].tangentAt(0).toTuple())
handle = cq.Workplane(plane).circle(2.6).sweep(path,isFrenet=True,transition="round").val()
merged=body.fuse(handle).clean()
print("body",body.isValid(),len(body.Solids()),body.Volume())
print("handle",handle.isValid(),len(handle.Solids()),handle.Volume())
print("merged",merged.isValid(),len(merged.Solids()),merged.Volume(),"overlap",body.Volume()+handle.Volume()-merged.Volume())
bb=merged.BoundingBox()
print("bbox",bb.xmin,bb.xmax,bb.ymin,bb.ymax,bb.zmin,bb.zmax,bb.xlen,bb.ylen,bb.zlen)
print("faces",len(merged.Faces()),"shells",len(merged.Shells()))

