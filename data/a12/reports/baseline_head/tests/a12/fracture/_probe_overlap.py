#!/usr/bin/env python
"""Diagnose the 2D overlap matcher on one real plane cut (candidate counts and overlap ratios)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MASTER_SEED = 20261001
LINEAGE_ID = "a12_demo"


def main() -> int:
    import shapely
    import trimesh
    from scipy.spatial import cKDTree

    from synlab.fracture.api import make_closed_cutter
    from synlab.fracture.booleans import (
        SourceResolver,
        boolean_difference,
        boolean_intersection,
        tag_source,
    )
    from synlab.fracture.event import _interface_faces
    from synlab.fracture.fragment import make_fragment, split_components
    from synlab.fracture.spec import FractureSpec
    from synlab.mothers.api import load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    vessel = sys.argv[1] if len(sys.argv) > 1 else "V13"
    root = REPO_ROOT / "data" / "a12_demo"
    manifest = json.loads((root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{vessel}")
    mother = load_mother(AssetStore(root / "store"), str(entry["asset_id"]))
    spec = FractureSpec(backend="plane_shared_cut", target_rms_mm=0.05)
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", vessel, "plane_shared_cut")
    cutter = make_closed_cutter(mother, spec, rng)
    sm = tag_source(trimesh.Trimesh(vertices=np.asarray(mother.mesh.vertices),
                                    faces=np.asarray(mother.mesh.faces), process=False), 1.0, "m")
    sc = tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                    faces=np.asarray(cutter.mesh.faces), process=False), 2.0, "c")
    minus = boolean_intersection([sm, sc], label="minus")
    plus = boolean_difference([sm, sc], label="plus")
    resolver = SourceResolver([sm, sc], tolerance_mm=1.0e-4)
    fragments = []
    for name, side, side_tag in (("M_minus", minus, -1), ("M_plus", plus, 1)):
        classification = resolver.classify(side, container=cutter.mesh,
                                           container_tolerance_mm=1.0e-4)
        classification["_faces"] = np.asarray(side.mesh.faces, dtype=np.int64)
        classification["area_faces"] = np.asarray(side.mesh.area_faces, dtype=np.float64)
        classification["mother_mesh_id"] = 1
        classification["cutter_mesh_id"] = 2
        for index, part in enumerate(split_components(side.mesh)):
            fragments.append(make_fragment(part, fragment_id=f"{name}_{index}", component_id=index,
                                           side=side_tag, classification=classification,
                                           parent_id=None, backend="plane_shared_cut",
                                           cutter_hash="probe", extra_meta={}))
    fa, sa, ca = _interface_faces(fragments[0])
    fb, sb, cb = _interface_faces(fragments[1])
    tri_a = np.asarray(fragments[0].mesh.triangles, dtype=np.float64)[fa]
    tri_b = np.asarray(fragments[1].mesh.triangles, dtype=np.float64)[fb]
    areas_a = np.asarray(fragments[0].mesh.area_faces, dtype=np.float64)[fa]
    areas_b = np.asarray(fragments[1].mesh.area_faces, dtype=np.float64)[fb]
    normals_a = np.asarray(fragments[0].mesh.face_normals, dtype=np.float64)[fa]
    normals_b = np.asarray(fragments[1].mesh.face_normals, dtype=np.float64)[fb]
    print(f"{vessel}: A faces={fa.size} area={areas_a.sum():.1f}mm2  B faces={fb.size} "
          f"area={areas_b.sum():.1f}mm2", flush=True)
    normal = normals_a.mean(axis=0) - normals_b.mean(axis=0)
    normal = normal / np.linalg.norm(normal)
    helper = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = helper - normal * float(helper @ normal)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(normal, e1)
    proj = lambda tri: np.stack([tri @ e1, tri @ e2], axis=-1)  # noqa: E731
    poly_a = shapely.polygons(proj(tri_a))
    poly_b = shapely.polygons(proj(tri_b))
    print(f"  2D areas A p50={np.median(shapely.area(poly_a)):.4f} B p50="
          f"{np.median(shapely.area(poly_b)):.4f} (3D p50 A={np.median(areas_a):.4f} "
          f"B={np.median(areas_b):.4f})", flush=True)
    tree = cKDTree(np.asarray(cb))
    scale = float(np.median(np.max(np.linalg.norm(tri_a - tri_a[:, 0:1, :], axis=2), axis=1)))
    radius = max(2.0 * scale, 1.0e-3)
    best_ratio = np.zeros(fa.size, dtype=np.float64)
    partner_count = np.zeros(fa.size, dtype=np.int64)
    for index in range(fa.size):
        partners = tree.query_ball_point(ca[index], r=radius)
        if not partners:
            continue
        partner_count[index] = len(partners)
        poly = np.asarray([poly_a[index]] * len(partners))
        inter = shapely.area(shapely.intersection(poly, poly_b[np.asarray(partners)]))
        dot = normals_b[np.asarray(partners)] @ normals_a[index]
        inter = inter[dot <= -0.5]
        if inter.size:
            best_ratio[index] = float(inter.max() / max(areas_a[index], 1e-12))
    print(f"  candidates per A face: p50={np.median(partner_count):.0f} "
          f"max={partner_count.max()}", flush=True)
    print(f"  best overlap / A area: p05={np.percentile(best_ratio, 5):.3f} "
          f"p50={np.percentile(best_ratio, 50):.3f} p95={np.percentile(best_ratio, 95):.3f} "
          f"zero={int(np.sum(best_ratio <= 0.0))}", flush=True)
    covered = float(np.sum(best_ratio * areas_a))
    print(f"  area covered by the single best partner: {covered:.1f}mm2 of "
          f"{areas_a.sum():.1f}mm2 ({covered / max(areas_a.sum(), 1e-9):.3f})", flush=True)

    # are all of A's "interface" faces really cut faces?  a cut face lies in the cut plane and
    # its normal is parallel (up to sign) to it
    local = cutter.basis.to_local(np.asarray(fragments[0].mesh.triangles_center)[fa])
    plane_dot = np.abs(normals_a @ np.asarray(cutter.basis.normal))
    order = np.argsort(-areas_a)
    print(f"  |w| centroid p95={np.percentile(np.abs(local[:, 2]), 95):.4f} "
          f"max={np.abs(local[:, 2]).max():.4f} mm", flush=True)
    print(f"  |dot(n, plane)| p05={np.percentile(plane_dot, 5):.4f} "
          f"p50={np.percentile(plane_dot, 50):.4f} "
          f"frac>0.9={float(np.mean(plane_dot > 0.9)):.3f}", flush=True)
    print("  largest 5 interface faces: area / |w| / |dot(n,plane)|:", flush=True)
    for position in order[:5]:
        print(f"    {areas_a[position]:9.3f} mm2  |w|={abs(local[position, 2]):.5f}  "
              f"|dot|={plane_dot[position]:.4f}", flush=True)
    zero = best_ratio <= 0.0
    if bool(np.any(zero)):
        print(f"  zero-overlap faces: {int(np.sum(zero))} area={areas_a[zero].sum():.1f}mm2 "
              f"| dot(n,plane)| p50={np.percentile(plane_dot[zero], 50):.4f} "
              f"|w| p95={np.percentile(np.abs(local[zero, 2]), 95):.4f}", flush=True)
        edges = np.max(np.linalg.norm(tri_a - tri_a[:, 0:1, :], axis=2), axis=1)
        print(f"  max edge length: zero-overlap p50={np.median(edges[zero]):.3f} "
              f"p95={np.percentile(edges[zero], 95):.3f} | all p50={np.median(edges):.3f}",
              flush=True)
    # inspect the largest interface faces in the basis frame + their per-vertex distance to the
    # cutter surface: a cut face must lie in the cutter surface, vertex by vertex
    for position in order[:3]:
        vertices = tri_a[position]
        vertex_local = cutter.basis.to_local(vertices)
        distances = np.asarray(cutter.mesh.nearest.on_surface(vertices)[1], dtype=np.float64)
        own = np.asarray(fragments[0].mesh.faces)[fa[position]]
        origin_kind = np.asarray(fragments[0].face_origin_kind)[fa[position]]
        print(f"  face {int(fa[position])} area={areas_a[position]:.1f} faces_idx={own.tolist()} "
              f"origin={origin_kind.tolist()}", flush=True)
        print(f"    vertices (u, v, w) = {np.round(vertex_local, 4).tolist()}", flush=True)
        print(f"    distance to cutter surface = {np.round(distances, 8).tolist()} mm", flush=True)
        print(f"    face normal={np.round(normals_a[position], 5).tolist()} "
              f"plane normal={np.round(cutter.basis.normal, 5).tolist()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
