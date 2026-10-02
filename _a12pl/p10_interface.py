"""Debug 10: build a level-0/level-1 interface directly and print both sides' geometry."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

KEY_LEVEL = 23


def main() -> int:
    from synlab.fracture import cut as cut_mod

    u0, u1, v0, v1 = -20.0, 20.0, -20.0, 20.0
    tree = cut_mod._Quadtree(u0, u1, v0, v1, 3)

    def report(cell):
        i, j, level = cell
        span = tree.key_span(level, KEY_LEVEL)
        pts_ij, tris = tree.cell_triangles(i, j, level, span)
        u, v = cut_mod._cell_uv(tree, level, span, pts_ij)
        world = np.round(np.stack([u, v], axis=1), 9)
        return {"cell": [i, j, level], "span": span,
                "cell_uv": [round(x, 6) for x in tree.cell_uv(i, j, level)],
                "splits": tree.edge_splits(i, j, level),
                "world": world.tolist(), "tris": tris.tolist()}

    # interface: cell (1,0,L0) on the left, children of (2,0,L0) on the right
    tree.refine_bulk(np.array([(2, 0, 0)], dtype=np.int64))
    out = {"edges": []}
    for orient, lo in (("v", True), ("u", True), ("v", False), ("u", False)):
        acr = tree._across(1, 0, 0, orient, lo)
        out["edges"].append({"orient": orient, "lo": bool(lo), "across": acr,
                             "split": tree.edge_split(1, 0, 0, orient, lo)})
    out["coarse"] = report((1, 0, 0))
    out["children"] = [report((4 + di, dj, 1)) for di in (0, 1) for dj in (0, 1)]
    # what does the coarse cell's right edge look like vs the two children's left edges?
    print(json.dumps(out, indent=1, default=str))

    # which world segments does each side traverse?
    def segments(cell):
        data = report(cell)
        world = np.asarray(data["world"])
        segs = []
        for tri in data["tris"]:
            for k in range(3):
                a = tuple(world[tri[k]])
                b = tuple(world[tri[(k + 1) % 3]])
                segs.append((a, b))
        return segs

    print("\n--- coarse right-edge segments (x == cell u_max) ---")
    for a, b in segments((1, 0, 0)):
        if abs(a[0] - 1.25) < 1e-9 and abs(b[0] - 1.25) < 1e-9:
            print("  ", a, "->", b)
    print("--- fine left-edge segments (x == cell u_min) ---")
    for cell in [(4, 0, 1), (4, 1, 1)]:
        for a, b in segments(cell):
            if abs(a[0] - 1.25) < 1e-9 and abs(b[0] - 1.25) < 1e-9:
                print("  ", cell, a, "->", b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
