#!/usr/bin/env python
"""Scratch: what does the real basis/refinement look like at the non-conforming edge?"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(REPO_ROOT), str(Path(__file__).resolve().parents[2])):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from synlab.fracture import api as api_mod  # noqa: E402
from synlab.fracture import cut as cut_mod  # noqa: E402
from synlab.fracture.api import _default_basis  # noqa: E402
from synlab.fracture.spec import BACKEND_ROUGH, FractureSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

import fixtures as fx  # noqa: E402

KEY_LEVEL = 23
PROBE = (12.753355, 4.084518)


def main() -> int:
    real_extras = cut_mod.edge_extra_all
    calls: list[dict] = []

    def capture(tree, block, key_level):
        value = real_extras(tree, block, key_level)
        rows = np.asarray(block, dtype=np.int64).reshape(-1, 3)
        if not calls or rows.shape[0] >= calls[-1]["block"].shape[0]:
            calls.append({"tree": tree, "block": rows, "extras": value, "key_level": key_level})
        return value

    cut_mod.edge_extra_all = capture
    mother = fx.thin_bowl_mother()
    spec = FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=0.02,
                        error_budget_mm=0.011, max_cutter_cells=90000)
    rng = make_rng(20261001, "tj_resolution", "bowl-lo_0.02_0.011_90000")
    basis = _default_basis(mother, rng, spec)
    try:
        api_mod.make_closed_cutter(mother, spec, rng, basis=basis)
    except Exception as exc:  # noqa: BLE001
        print("build:", type(exc).__name__, str(exc).split("\n", 1)[0])
    finally:
        cut_mod.edge_extra_all = real_extras

    state = calls[-1]
    tree = state["tree"]
    block = state["block"]
    extras = state["extras"]
    print("u_range", basis.u_range, "v_range", basis.v_range)
    print("material_u", basis.meta.get("material_u_range"), "material_v",
          basis.meta.get("material_v_range"))
    print("tree root_level", tree.root_level, "side", tree.side, "hx", tree.hx, "hy", tree.hy)
    print("tree u0,v0", tree.u0, tree.v0, "hx*side", tree.hx * tree.side,
          "hy*side", tree.hy * tree.side)
    for level in range(0, 7):
        print(f"   level {level}: cell size {tree.cell_size(level)}")

    # which leaf contains the probe point?
    u, v = PROBE
    for (i, j, level) in block:
        hx, hy = tree.cell_size(int(level))
        u0 = tree.u0 + int(i) * hx
        v0 = tree.v0 + int(j) * hy
        if u0 - 1e-9 <= u <= u0 + hx + 1e-9 and v0 - 1e-9 <= v <= v0 + hy + 1e-9:
            pos = {tuple(int(x) for x in row): p for p, row in enumerate(block)}[(int(i), int(j),
                                                                                  int(level))]
            print(f"leaf at probe: ({i},{j},{level}) size=({hx:.6f},{hy:.6f}) "
                  f"u0={u0:.6f} v0={v0:.6f} splits={tree.edge_splits(int(i), int(j), int(level))} "
                  f"extras={tuple(int(x) for x in extras[pos])}")
            # its four siblings at the same level, and their refinement state
            for orient, lo in (("v", True), ("u", True), ("v", False), ("u", False)):
                nb = tree._across(int(i), int(j), int(level), orient, lo)
                if nb is None:
                    print(f"   neighbour {orient} lo={lo}: frame")
                    continue
                ni, nj = nb
                st = tree.is_refined(ni, nj, int(level))
                kids = [(2 * ni + di, 2 * nj + dj, int(level) + 1) for di in (0, 1) for dj in (0, 1)]
                kid_ref = [k for k in kids if tree.is_refined(*k)]
                grand = [(2 * k[0] + di, 2 * k[1] + dj, k[2] + 1)
                         for k in kid_ref for di in (0, 1) for dj in (0, 1)
                         if tree.is_refined(2 * k[0] + di, 2 * k[1] + dj, k[2] + 1)]
                in_block = [(int(a), int(b), int(c)) in
                            {tuple(int(x) for x in r) for r in block} for (a, b, c) in kids]
                print(f"   neighbour {orient} lo={lo}: ({ni},{nj},{level}) refined={st} "
                      f"kids_refined={len(kid_ref)} kids_are_leaves={in_block} "
                      f"grandkids_refined={len(grand)}")
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
