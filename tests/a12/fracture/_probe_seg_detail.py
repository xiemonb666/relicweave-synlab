"""Dump the emitted top triangles around one bad edge, with world coordinates and edge use."""

from __future__ import annotations

import json
import sys
from collections import Counter

import numpy as np
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import _probe_rough_topology as probe  # noqa: E402

SEG = ((41943040, 276824064), (41943040, 285212672))


def main() -> int:
    built, info, basis, height = probe.build("box", 0.05, 0.01)
    tree, leaves, top_faces, top_edge_use, vertices, top_index = probe.top_surface(
        basis, height, 0.01)
    verts = np.asarray(vertices, dtype=np.float64)
    print(f"cells={len(leaves)} faces={len(top_faces)} verts={verts.shape[0]}")
    # which cells own the segment?
    lo = min(SEG[0], SEG[1])
    hi = max(SEG[0], SEG[1])
    owners = []
    for (i, j, level) in leaves:
        span = 23 - level
        base_i, base_j = i << span, j << span
        end = 1 << span
        x0, x1 = base_i, base_i + end
        y0, y1 = base_j, base_j + end
        inside = (x0 <= lo[0] <= x1 and y0 <= lo[1] <= y1
                  and x0 <= hi[0] <= x1 and y0 <= hi[1] <= y1)
        if inside and x0 == x1 - end and lo[0] in (x0, x1):
            owners.append((i, j, level))
    print("cells whose box contains the segment:", owners)
    for cell in owners:
        pts_ij, tris = tree.cell_triangles(cell[0], cell[1], cell[2], 23 - cell[2])
        keys = [(int(p[0]), int(p[1])) for p in pts_ij]
        ids = [top_index.get(k) for k in keys]
        print(f"\ncell {cell} splits={[bool(x) for x in tree.edge_splits(*cell)]}")
        for n, (k, v) in enumerate(zip(keys, ids)):
            print(f"   p{n} key={k} vert={v} world=({verts[v,0]:.6f},{verts[v,1]:.6f})")
        for n, tri in enumerate(tris):
            ring = [f"p{tri[m]}" for m in range(3)]
            w = [(float(verts[ids[tri[m]], 0]), float(verts[ids[tri[m]], 1])) for m in range(3)]
            print(f"   tri {ring} verts={[ids[tri[m]] for m in range(3)]} "
                  f"world={[(round(a,4), round(b,4)) for a, b in w]}")
    # edge use of the segment's lattice key
    seg_key = (lo, hi)
    print("\nsegment lattice key:", seg_key)
    vert_to_key = {int(v): (int(k[0]), int(k[1])) for k, v in top_index.items()}
    hits = 0
    for n, tri in enumerate(top_faces):
        ring = [(int(tri[0]), int(tri[1])), (int(tri[1]), int(tri[2])),
                (int(tri[2]), int(tri[0]))]
        for a, b in ring:
            ka, kb = vert_to_key.get(a), vert_to_key.get(b)
            if ka is None or kb is None:
                continue
            key = (min(ka, kb), max(ka, kb))
            if key == seg_key:
                hits += 1
                print(f"  face {n} {tri} uses the segment as ({a},{b}) "
                      f"keys {ka}->{kb} world=({verts[a,0]:.6f},{verts[a,1]:.6f})"
                      f"->({verts[b,0]:.6f},{verts[b,1]:.6f})")
    print("faces using the exact segment:", hits)
    print("\n--- neighbour state around the segment ---")
    for cell, orient, lo in (((4, 33, 0), "v", False), ((5, 33, 0), "v", True),
                             ((5, 33, 0), "v", False), ((4, 34, 0), "v", False)):
        i, j, level = cell
        nb = tree._across(i, j, level, orient, lo)
        si, sj = (None, None) if nb is None else (int(nb[0]), int(nb[1]))
        leaf = None if nb is None else tree._leaf_on_path(si, sj, level)
        print(f"cell {cell} {orient} lo={lo}: sibling={nb} "
              f"is_refined(sibling)={None if nb is None else tree.is_refined(si, sj, level)} "
              f"leaf_on_path={leaf} my_split={tree.edge_split(i, j, level, orient, lo)}")
    print("\nrefined entries near (4,33,0):",
          sorted(c for c in tree.refined if c[2] == 0 and 3 <= c[0] <= 6 and 31 <= c[1] <= 36))
    for (i, j, level) in ((5, 33, 0), (5, 34, 0), (4, 34, 0), (4, 33, 0)):
        print(f"  cell ({i},{j},{level}) refined={tree.is_refined(i, j, level)} "
              f"splits={[bool(x) for x in tree.edge_splits(i, j, level)]}")

    # ---- coverage accounting: does the triangulation tile the frame? ----
    import trimesh
    cell_area = 0.0
    for (i, j, level) in leaves:
        hx, hy = tree.cell_size(level)
        cell_area += hx * hy
    tri = np.asarray(top_faces, dtype=np.int64).reshape(-1, 3)
    uv = verts[:, 0:2]
    pts = uv[tri]
    a = pts[:, 1] - pts[:, 0]
    b = pts[:, 2] - pts[:, 0]
    tri_area = float(np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]).sum() * 0.5)
    mesh = trimesh.Trimesh(vertices=np.column_stack([uv, np.zeros(uv.shape[0])]),
                           faces=tri, process=False)
    union_area = float(mesh.area)
    print(f"\ncell area sum      = {cell_area:.6f} mm^2")
    print(f"triangle area sum  = {tri_area:.6f} mm^2  (overlap count)")
    print(f"covered area       = {union_area:.6f} mm^2")
    print(f"ratio tri/cells    = {tri_area / cell_area:.9f}")
    # ---- ground truth: what does THIS run's tree say about the two cells? ----
    print("\n--- tree state in this run ---")
    for cell in ((4, 33, 0), (5, 33, 0)):
        print(f"  {cell} splits={[bool(x) for x in tree.edge_splits(*cell)]} "
              f"refined={tree.is_refined(*cell)}")
        pts_ij, tris = tree.cell_triangles(cell[0], cell[1], cell[2], 23 - cell[2])
        print(f"     pts={pts_ij.tolist()}")
    # ---- does the emitted triangulation actually use each cell's declared split midpoint? ----
    vert_to_key2 = {int(v): (int(k[0]), int(k[1])) for k, v in top_index.items()}
    for cell in ((4, 33, 0), (5, 33, 0)):
        flags = [bool(x) for x in tree.edge_splits(*cell)]
        span = 23 - cell[2]
        base_i, base_j = cell[0] << span, cell[1] << span
        end = 1 << span
        half = end >> 1
        mids = [((base_i, base_j + half), flags[0]), ((base_i + half, base_j), flags[1]),
                ((base_i + end, base_j + half), flags[2]), ((base_i + half, base_j + end),
                                                            flags[3])]
        for (key, flag) in mids:
            if not flag:
                continue
            found = top_index.get((int(key[0]), int(key[1])))
            used = 0
            if found is not None:
                for tri in top_faces:
                    if int(found) in (int(tri[0]), int(tri[1]), int(tri[2])):
                        used += 1
            print(f"  {cell} declared midpoint {key} -> vertex {found}, used by {used} faces")
    print("cells:", len(leaves), "faces:", len(top_faces), "verts:", verts.shape[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
