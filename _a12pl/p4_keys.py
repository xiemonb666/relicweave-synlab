"""Debug 2: are the shared-key vertices geometrically consistent across cells?

Prints, for a few keys created by different cells, the world position each cell computes, plus
adjacent-cell world-coordinate agreement.  A mismatch here would explain a non-manifold mesh.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402


def main() -> int:
    from synlab.fracture import cut as cut_mod

    u0, u1, v0, v1 = -20.0, 20.0, -20.0, 20.0
    tree = cut_mod._Quadtree(u0, u1, v0, v1, 3)
    print(f"root side={tree.side} hx={tree.hx:.6f} hy={tree.hy:.6f}")
    levels = [0, 1, 2, 3]
    rows = []
    for level in levels:
        span = tree.key_span(level, 23)
        hx, hy = tree.cell_size(level)
        for (i, j) in ((0, 0), (1, 0), (0, 1), (1, 1)):
            pts_ij, tris = tree.cell_triangles(i, j, level, span)
            u, v = cut_mod._cell_uv(tree, level, span, pts_ij)
            world = np.stack([u, v], axis=1)
            rows.append({"level": level, "cell": [i, j], "span": span,
                         "cell_size_mm": [hx, hy],
                         "pts_ij": pts_ij.tolist(),
                         "world_mm": np.round(world, 9).tolist(),
                         "edge_lengths_mm": np.round(np.linalg.norm(
                             world[tris][:, 1] - world[tris][:, 0], axis=1), 9).tolist(),
                         "n_tris": len(tris)})
    # cross-level agreement: cell (0,0) at level ℓ and cell (0,0) at level ℓ+1 must share corners
    print(json.dumps(rows[:8], indent=1))
    print("...")
    for level in levels[:-1]:
        span_a = tree.key_span(level, 23)
        span_b = tree.key_span(level + 1, 23)
        pa, _ = tree.cell_triangles(0, 0, level, span_a)
        pb, _ = tree.cell_triangles(2 * 0, 2 * 0, level + 1, span_b)
        ua, va = cut_mod._cell_uv(tree, level, span_a, pa)
        ub, vb = cut_mod._cell_uv(tree, level + 1, span_b, pb)
        keys_a = {tuple(int(x) for x in k) for k in pa}
        keys_b = {tuple(int(x) for x in k) for k in pb}
        shared = keys_a & keys_b
        mismatches = []
        for key in sorted(shared):
            ia = int(np.flatnonzero((pa[:, 0] == key[0]) & (pa[:, 1] == key[1]))[0])
            ib = int(np.flatnonzero((pb[:, 0] == key[0]) & (pb[:, 1] == key[1]))[0])
            da = (ua[ia], va[ia])
            db = (ub[ib], vb[ib])
            if abs(da[0] - db[0]) > 1e-12 or abs(da[1] - db[1]) > 1e-12:
                mismatches.append({"key": list(key), "a": da, "b": db})
        print(json.dumps({"level": level, "shared_keys": len(shared),
                          "mismatches": mismatches[:4]}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
