from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from synlab.mothers import audit

A = np.asarray([(0,100,0),(10,100,0),(0,101,0)], dtype=np.float64)
B = np.asarray([(1,99,-1),(1,120,-1),(1,100,1)], dtype=np.float64)
tris = np.stack([A,B])
faces = np.asarray([(0,1,2),(3,4,5)], dtype=np.int64)
mesh = trimesh.Trimesh(vertices=np.vstack([A,B]), faces=faces, process=False)

# Independent analytic plane-cut oracle: cut each triangle by the other's plane,
# then compare the two resulting intervals along the plane-plane intersection line.
def cut_segment(tri, plane_tri, tol=1e-10):
    n = np.cross(plane_tri[1]-plane_tri[0], plane_tri[2]-plane_tri[0])
    vals = (tri-plane_tri[0]) @ n
    points = []
    for i,j in ((0,1),(1,2),(2,0)):
        a,b = vals[i], vals[j]
        if abs(a) <= tol:
            points.append(tri[i])
        if (a < -tol and b > tol) or (a > tol and b < -tol):
            t = a/(a-b)
            points.append(tri[i] + t*(tri[j]-tri[i]))
    unique=[]
    for p in points:
        if not any(np.linalg.norm(p-q) <= 1e-8 for q in unique):
            unique.append(p)
    if len(unique) < 2:
        return n, np.asarray(unique)
    return n, np.asarray(unique[:2])

nA, nB = (np.cross(t[1]-t[0], t[2]-t[0]) for t in (A,B))
segA_planeB = cut_segment(A,B)[1]
segB_planeA = cut_segment(B,A)[1]
line = np.cross(nA,nB)
line = line / np.linalg.norm(line)
projA = segA_planeB @ line
projB = segB_planeA @ line
lo = max(float(projA.min()), float(projB.min()))
hi = min(float(projA.max()), float(projB.max()))
analytic = {
  "cut_A_by_plane_B": segA_planeB.tolist(),
  "cut_B_by_plane_A": segB_planeA.tolist(),
  "intersection_line_direction": line.tolist(),
  "overlap_length_mm": max(0.0, hi-lo),
  "positive_length_intersection": bool(hi-lo > 1e-8),
  "shared_vertex_indices": bool(set(faces[0]) & set(faces[1])),
  "shared_vertex_positions": bool(any(np.allclose(a,b) for a in A for b in B)),
}

pairs, candidate_meta = audit._candidate_pairs(tris, faces)
axes = audit._axes_for_pair(A[None,...], B[None,...])
interval = bool(audit._interval_overlap(A[None,...], B[None,...], axes, 1e-4)[0])
report = audit.self_intersection_report(mesh)

# A second independent reproducer for budget exhaustion: overlapping coplanar triangles
# with distinct vertices and face indices.
C = np.asarray([(0,0,0),(2,0,0),(0,2,0)], dtype=np.float64)
D = np.asarray([(0.5,0.5,0),(2,0.5,0),(0.5,2,0)], dtype=np.float64)
coplanar_mesh = trimesh.Trimesh(vertices=np.vstack([C,D]), faces=faces, process=False)
zero_budget = audit.self_intersection_report(coplanar_mesh, max_coplanar_checks=0)

open3d_probe = {"installed": importlib.util.find_spec("open3d") is not None}
if open3d_probe["installed"]:
    try:
        import open3d as o3d
        open3d_probe["version"] = getattr(o3d, "__version__", None)
        legacy = o3d.geometry.TriangleMesh()
        tensor = o3d.t.geometry.TriangleMesh()
        open3d_probe["legacy_self_intersection_methods"] = [n for n in dir(legacy) if "intersect" in n.lower()]
        open3d_probe["tensor_self_intersection_methods"] = [n for n in dir(tensor) if "intersect" in n.lower()]
        open3d_probe["independent_triangle_mesh_self_intersection_oracle_available"] = any(
            "intersect" in n.lower() for n in dir(legacy) + dir(tensor))
        def open3d_check(vertices, triangles):
            omesh = o3d.geometry.TriangleMesh(
                o3d.utility.Vector3dVector(np.asarray(vertices, dtype=np.float64)),
                o3d.utility.Vector3iVector(np.asarray(triangles, dtype=np.int32)))
            return {
                "is_self_intersecting": bool(omesh.is_self_intersecting()),
                "self_intersecting_triangles": np.asarray(
                    omesh.get_self_intersecting_triangles()).tolist(),
            }
        open3d_probe["A_B"] = open3d_check(np.vstack([A,B]), faces)
        open3d_probe["coplanar_overlap"] = open3d_check(np.vstack([C,D]), faces)
    except Exception as e:
        open3d_probe["import_error"] = f"{type(e).__name__}: {e}"
else:
    open3d_probe["independent_triangle_mesh_self_intersection_oracle_available"] = False

out = {
  "python": sys.version,
  "repro_A_B": {
    "A": A.tolist(), "B": B.tolist(),
    "candidate_pairs": pairs.tolist(), "candidate_meta": candidate_meta,
    "axes_shape": list(axes.shape), "interval_overlap_every_axis": interval,
    "self_intersection_report": report,
    "independent_analytic_reference": analytic,
  },
  "coplanar_budget_zero": zero_budget,
  "open3d": open3d_probe,
  "source_observations": {
    "candidate_sweep": "one lower bound is selected from each triangle's own widest axis, then scalar lower/upper values are mixed in one sort; comparisons are not along a common coordinate axis",
    "interval_overlap": "returns true only when every nondegenerate SAT axis has overlap > eps; zero-thickness normal projections have overlap 0",
    "coplanar_budget": "budget exhaustion skips remaining exact 2D checks but final report hardcodes complete=true",
  },
}
path = Path(__file__).with_name("mother_audit_min_repro.json")
path.write_text(json.dumps(out, indent=2), encoding="utf-8")
print(json.dumps(out, indent=2))
