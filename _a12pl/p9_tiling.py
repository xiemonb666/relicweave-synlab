"""Debug 9: does ``cell_triangles`` tile its own cell, and are the key-lattice corners correct?"""

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
    bad: list[dict] = []
    checked = 0
    for level in (0, 1, 2, 3, 4):
        span = tree.key_span(level, 23)
        hx, hy = tree.cell_size(level)
        for i in range(min(tree.side << level, 4)):
            for j in range(min(tree.side << level, 4)):
                cu0, cu1, cv0, cv1 = tree.cell_uv(i, j, level)
                pts_ij, tris = tree.cell_triangles(i, j, level, span)
                u, v = cut_mod._cell_uv(tree, level, span, pts_ij)
                world = np.stack([u, v], axis=1)
                # 1. every point must be on the cell's own boundary (it is a corner/midpoint)
                tol = 1e-9
                on_edge = ((np.abs(world[:, 0] - cu0) < tol) | (np.abs(world[:, 0] - cu1) < tol)
                           | (np.abs(world[:, 1] - cv0) < tol) | (np.abs(world[:, 1] - cv1) < tol))
                inside = ((world[:, 0] >= cu0 - tol) & (world[:, 0] <= cu1 + tol)
                          & (world[:, 1] >= cv0 - tol) & (world[:, 1] <= cv1 + tol))
                # 2. the triangles must tile the quad exactly: area sum == hx*hy, no overlap
                area = 0.0
                for tri in tris:
                    p = world[tri]
                    area += 0.5 * abs((p[1, 0] - p[0, 0]) * (p[2, 1] - p[0, 1])
                                      - (p[2, 0] - p[0, 0]) * (p[1, 1] - p[0, 1]))
                checked += 1
                problems = []
                if not bool(inside.all()):
                    problems.append("point_outside_cell")
                if not bool(on_edge.all()):
                    problems.append("point_not_on_boundary")
                if abs(area - hx * hy) > 1e-9 * max(hx * hy, 1.0):
                    problems.append("area_mismatch")
                # 3. no triangle may straddle a cell edge (it would be a real crossing)
                if problems:
                    bad.append({"level": level, "cell": [i, j], "span": span,
                                "cell_size": [hx, hy], "tri_area": area,
                                "quad_area": hx * hy, "problems": problems,
                                "world": np.round(world, 6).tolist(),
                                "tris": tris.tolist(),
                                "splits": tree.edge_splits(i, j, level)})
    print(json.dumps({"checked": checked, "bad": len(bad), "samples": bad[:6]},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
