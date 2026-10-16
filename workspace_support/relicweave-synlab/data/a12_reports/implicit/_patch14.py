import pathlib
p = pathlib.Path("synlab/fracture/implicit/assembler.py")
s = p.read_text(encoding="utf-8")
s = s.replace("np.asarray(signed_distance(points, mother_mesh), dtype=np.float64)",
              "np.asarray(signed_distance(mother_mesh, points), dtype=np.float64)")
s = s.replace("_closest, _distance, mother_tri = closest_point(mother_mesh, points)",
              "_closest, _distance, mother_tri = closest_point(mother_mesh, points)")
s = s.replace("d_mother = np.abs(np.asarray(signed_distance(pts, mother_mesh), dtype=np.float64))",
              "d_mother = np.abs(np.asarray(signed_distance(mother_mesh, pts), dtype=np.float64))")
p.write_text(s, encoding="utf-8")
print("fixed signature order")
