"""Debug 3: smallest non-manifold reproduction -- one cell family, printed in full."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402


def main() -> int:
    from synlab.fracture import cut as cut_mod

    u0, u1, v0, v1 = -20.0, 20.0, -20.0, 20.0
    tree = cut_mod._Quadtree(u0, u1, v0, v1, 3)
    key_level = 23
    # one coarse cell with every edge split, next to four finer neighbours
    tree.refined.add((0, 0, 0))
    for di in (0, 1):
        for dj in (0, 1):
            tree.refined.add((di, dj, 1))
    leaves = tree.leaves()
    print("leaves:", leaves)
    top_index: dict[tuple[int, int], int] = {}
    verts: list[tuple[float, float]] = []

    def top_vertex(level: int, gi: int, gj: int) -> int:
        span = tree.key_span(level, key_level)
        key = (int(gi), int(gj))
        got = top_index.get(key)
        if got is None:
            u, v = cut_mod._cell_uv(tree, level, span,
                                    np.array([[int(gi), int(gj)]], dtype=np.int64))
            got = len(verts)
            verts.append((float(u[0]), float(v[0])))
            top_index[key] = got
        return got

    tris = []
    for i, j, level in leaves:
        pts_ij, t = tree.cell_triangles(i, j, level, tree.key_span(level, key_level))
        local = [top_vertex(level, int(p[0]), int(p[1])) for p in pts_ij]
        for tri in t:
            face = (int(local[tri[0]]), int(local[tri[1]]), int(local[tri[2]]))
            tris.append(face)
        print(f"cell ({i},{j},L{level}) splits={tree.edge_splits(i, j, level)} "
              f"keys={[list(map(int, p)) for p in pts_ij]} local={local} tris={t}")
    print("world vertices:")
    for index, (u, v) in enumerate(verts):
        print(f"  {index}: ({u:.6f}, {v:.6f})")
    print("faces:")
    for face in tris:
        print("  ", face, "len-set", len(set(face)))
    edge: dict[tuple[int, int], int] = {}
    for face in tris:
        for k in range(3):
            e = (face[k], face[(k + 1) % 3])
            edge[e] = edge.get(e, 0) + 1
    print("edge table:")
    for e, n in sorted(edge.items()):
        rev = edge.get((e[1], e[0]), 0)
        flag = ""
        if n == 1 and rev == 0:
            flag = "BOUNDARY"
        elif n == 1 and rev == 1:
            flag = "BAD one-each"
        elif n == 2 and rev == 0:
            flag = "interior"
        print(f"  {e}: uses={n} reverse={rev} {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
