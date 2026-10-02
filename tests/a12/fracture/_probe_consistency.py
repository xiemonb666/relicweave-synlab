"""One-shot: build the refined tree once and reconcile cell_triangles with edge_splits."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import _probe_rough_topology as probe  # noqa: E402


def main() -> int:
    built, info, basis, height = probe.build("box", 0.05, 0.01)
    tree, leaves, top_faces, top_edge_use, vertices, top_index = probe.top_surface(
        basis, height, 0.01)
    out = {"cells": len(leaves), "faces": len(top_faces)}
    # for every leaf whose declared split count is 1, check the triangulation length
    by_split = {}
    mismatch = []
    for (i, j, level) in leaves[:4000]:
        flags = tuple(bool(x) for x in tree.edge_splits(i, j, level))
        pts_ij, tris = tree.cell_triangles(i, j, level, 23 - level)
        n = int(sum(flags))
        key = f"n={n}|pts={pts_ij.shape[0]}|tris={tris.shape[0]}"
        by_split[key] = by_split.get(key, 0) + 1
        expect_pts = {0: 4, 1: 5, 2: 6}.get(n, 9)
        if pts_ij.shape[0] != expect_pts and len(mismatch) < 8:
            mismatch.append({"cell": [i, j, level], "flags": list(flags),
                             "n": n, "pts": pts_ij.shape[0], "tris": tris.shape[0],
                             "pts_ij": pts_ij.tolist()})
    out["by_split_head"] = by_split
    out["mismatch_examples"] = mismatch
    # direct double-check on the specific cell
    cell = (5, 33, 0)
    out["cell_5_33_0"] = {
        "flags": [bool(x) for x in tree.edge_splits(*cell)],
        "n": int(sum(bool(x) for x in tree.edge_splits(*cell))),
        "pts": tree.cell_triangles(*cell, 23)[0].tolist(),
        "tris": tree.cell_triangles(*cell, 23)[1].tolist(),
    }
    text = json.dumps(out, indent=2)
    Path(r"data/a12_reports/_fprec_consistency.json").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
