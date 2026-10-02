"""Debug 12: print the real tree's grid metrics and the exact failing pair."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

sys.path.insert(0, str(REPO / "_a12pl"))
from p11_locate import build_tree_and_field, box_mother  # noqa: E402,F401

KEY_LEVEL = 23


def main() -> int:
    tree, cut_mod = build_tree_and_field()
    out = {
        "u_range": [tree.u0, tree.u1], "v_range": [tree.v0, tree.v1],
        "root_level": tree.root_level, "side": tree.side,
        "hx": tree.hx, "hy": tree.hy, "grid_level": tree.grid_level,
        "cell_size": {str(level): tree.cell_size(level) for level in range(0, 6)},
        "key_span": {str(level): tree.key_span(level, KEY_LEVEL) for level in range(0, 6)},
        "key_step_mm": {str(level): tree.cell_size(level)[0] / (1 << tree.key_span(level, KEY_LEVEL))
                        for level in range(0, 6)},
    }
    for cell in ((36, 92, 2), (71, 184, 3), (71, 183, 3), (36, 93, 2)):
        i, j, level = cell
        span = tree.key_span(level, KEY_LEVEL)
        out[f"cell_{cell}"] = {
            "cell_uv": tree.cell_uv(i, j, level),
            "refined": tree.is_refined(i, j, level),
            "splits": tree.edge_splits(i, j, level),
            "span": span,
        }
    # the coarse cell's left neighbour chain
    for orient, lo in (("v", True), ("v", False), ("u", True), ("u", False)):
        acr = tree._across(36, 92, 2, orient, lo)
        out[f"across36_{orient}_{lo}"] = {
            "index": acr,
            "refined": None if acr is None else tree.is_refined(int(acr[0]), int(acr[1]), 2),
        }
    # which leaves touch the segment's u?
    target_u = -5.943052925
    touching = []
    for (i, j, level) in tree.leaves():
        cu0, cu1, cv0, cv1 = tree.cell_uv(i, j, level)
        if abs(cu0 - target_u) < 1e-6 or abs(cu1 - target_u) < 1e-6:
            touching.append({"cell": [i, j, level], "uv": [round(cu0, 6), round(cu1, 6),
                                                           round(cv0, 6), round(cv1, 6)],
                             "splits": tree.edge_splits(i, j, level)})
    out["leaves_on_u"] = touching[:14]
    out["leaves_on_u_count"] = len(touching)
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
