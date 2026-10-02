"""Debug 4: manifoldness of the leaf lattice for controlled refinement patterns."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

KEY_LEVEL = 23


def assemble(tree):
    top_index: dict[tuple[int, int], int] = {}
    verts: list[tuple[float, float]] = []

    def top_vertex(level: int, gi: int, gj: int) -> int:
        span = tree.key_span(level, KEY_LEVEL)
        key = (int(gi), int(gj))
        got = top_index.get(key)
        if got is None:
            u, v = _cell_uv(tree, level, span, np.array([[int(gi), int(gj)]], dtype=np.int64))
            got = len(verts)
            verts.append((float(u[0]), float(v[0])))
            top_index[key] = got
        return got

    faces = []
    for i, j, level in tree.leaves():
        pts_ij, tris = tree.cell_triangles(i, j, level, tree.key_span(level, KEY_LEVEL))
        local = [top_vertex(level, int(p[0]), int(p[1])) for p in pts_ij]
        for tri in tris:
            face = (int(local[tri[0]]), int(local[tri[1]]), int(local[tri[2]]))
            if len(set(face)) < 3:
                continue
            faces.append(face)
    return faces, verts


def classify(faces):
    directed: Counter = Counter()
    for face in faces:
        for k in range(3):
            directed[(face[k], face[(k + 1) % 3])] += 1
    stats = Counter()
    for edge, uses in directed.items():
        rev = directed.get((edge[1], edge[0]), 0)
        if uses == 1 and rev == 0:
            stats["boundary"] += 1
        elif uses == 1 and rev == 1:
            stats["interior"] += 1
        else:
            stats[f"BAD_{uses}_{rev}"] += 1
    return stats


def main() -> int:
    from synlab.fracture.cut import _Quadtree, _cell_uv

    globals()["_cell_uv"] = _cell_uv
    u0, u1, v0, v1 = -20.0, 20.0, -20.0, 20.0

    # uniform level 0 (no refinement)
    tree = _Quadtree(u0, u1, v0, v1, 3)
    faces, verts = assemble(tree)
    print("uniform L0: leaves=%d faces=%d verts=%d -> %s"
          % (len(tree.leaves()), len(faces), len(verts), dict(classify(faces))))

    # uniform: refuse nothing -> refine every cell at level 0
    tree = _Quadtree(u0, u1, v0, v1, 3)
    all0 = np.array([(i, j, 0) for i in range(tree.side) for j in range(tree.side)],
                    dtype=np.int64)
    tree.refine_bulk(all0)
    faces, verts = assemble(tree)
    print("uniform L1: leaves=%d faces=%d verts=%d -> %s"
          % (len(tree.leaves()), len(faces), len(verts), dict(classify(faces))))

    tree = _Quadtree(u0, u1, v0, v1, 3)
    tree.refine_bulk(all0)
    all1 = np.array([(i, j, 1) for i in range(2 * tree.side) for j in range(2 * tree.side)],
                    dtype=np.int64)
    tree.refine_bulk(all1)
    faces, verts = assemble(tree)
    print("uniform L2: leaves=%d faces=%d verts=%d -> %s"
          % (len(tree.leaves()), len(faces), len(verts), dict(classify(faces))))

    # one refined quadrant at L1 (2:1 grading by construction)
    tree = _Quadtree(u0, u1, v0, v1, 3)
    tree.refine_bulk(np.array([(4, 4, 0)], dtype=np.int64))
    faces, verts = assemble(tree)
    print("one cell L1: leaves=%d faces=%d verts=%d -> %s"
          % (len(tree.leaves()), len(faces), len(verts), dict(classify(faces))))

    # one refined quadrant at L2 with the level-1 parents also refined (conforming)
    tree = _Quadtree(u0, u1, v0, v1, 3)
    tree.refine_bulk(np.array([(4, 4, 0)], dtype=np.int64))
    tree.refine_bulk(np.array([(8, 8, 1), (9, 8, 1), (8, 9, 1), (9, 9, 1)], dtype=np.int64))
    faces, verts = assemble(tree)
    print("one cell L2: leaves=%d faces=%d verts=%d -> %s"
          % (len(tree.leaves()), len(faces), len(verts), dict(classify(faces))))

    # a single cell refined at L1 without re-rooting: splits determined by edge_split
    tree = _Quadtree(u0, u1, v0, v1, 3)
    tree.refine_bulk(np.array([(4, 4, 0)], dtype=np.int64))
    print("edge splits of the coarse neighbour (4,3,L0):", tree.edge_splits(4, 3, 0))
    print("edge splits of the coarse neighbour (4,5,L0):", tree.edge_splits(4, 5, 0))
    print("edge splits of the refined child (8,8,L1):", tree.edge_splits(8, 8, 1))
    print("needs_balance(4,3,L0) =", tree.needs_balance(4, 3, 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
