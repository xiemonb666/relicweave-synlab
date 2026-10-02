#!/usr/bin/env python
"""Scratch: capture the real refinement state and inspect one edge where a hanging corner is missing."""
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
from synlab.fracture.spec import BACKEND_ROUGH, FractureSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

import fixtures as fx  # noqa: E402

KEY_LEVEL = 23
TARGETS = [("first", (31, 26, 0)), ("second", (31, 25, 0))]


def inspect(tree, block, extras, tag, target):
    index = {tuple(int(x) for x in row): pos for pos, row in enumerate(block)}
    if target not in index:
        print(f"[{tag}] {target} is not a leaf")
        return
    i, j, level = target
    print(f"[{tag}] target {target} extras={tuple(int(x) for x in extras[index[target]])} "
          f"splits={tree.edge_splits(i, j, level)}")
    span = tree.key_span(level, KEY_LEVEL)
    step = 1 << span
    gu, gv = i << span, j << span
    line = gu
    corners: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    for (li, lj, ll) in block:
        lspan = KEY_LEVEL - int(ll)
        lstep = 1 << lspan
        lu, lv = int(li) << lspan, int(lj) << lspan
        for (cu, cv) in ((lu, lv), (lu + lstep, lv), (lu + lstep, lv + lstep), (lu, lv + lstep)):
            if cu == line and gv < cv < gv + step:
                corners.setdefault((cu, cv), []).append((int(li), int(lj), int(ll)))
    print(f"     left edge line(u)={line} v window=({gv},{gv + step})")
    for key, owners in sorted(corners.items(), key=lambda kv: kv[0][1]):
        print(f"     corner v-offset={key[1] - gv:>12} owners={owners}")
    ring = tree.cell_triangles(i, j, level, span, extras[index[target]])[0]
    print("     ring v-offsets on the line:",
          sorted(int(p[1]) - gv for p in ring if int(p[0]) == line))


def main() -> int:
    state: dict = {}
    real_extras = cut_mod.edge_extra_all
    calls: list[dict] = []

    def capture(tree, block, key_level):
        value = real_extras(tree, block, key_level)
        rows = np.asarray(block, dtype=np.int64).reshape(-1, 3)
        if not calls or rows.shape[0] >= calls[-1]["block"].shape[0]:
            calls.append({"tree": tree, "block": rows, "extras": value})
        return value

    cut_mod.edge_extra_all = capture
    mother = fx.thin_bowl_mother()
    spec = FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=0.02,
                        error_budget_mm=0.011, max_cutter_cells=90000)
    try:
        api_mod.make_closed_cutter(mother, spec, make_rng(20261001, "tj_resolution",
                                                          "bowl-lo_0.02_0.011_90000"))
    except Exception as exc:  # noqa: BLE001 - the build is expected to refuse here
        print("build:", type(exc).__name__, str(exc).split("\n", 1)[0])
    finally:
        cut_mod.edge_extra_all = real_extras
    state = calls[-1]

    tree = state["tree"]
    block = state["block"]
    extras = state["extras"]
    print("leaves", block.shape[0], "refined entries", len(tree.refined), "side", tree.side)
    index = {tuple(int(x) for x in row): pos for pos, row in enumerate(block)}

    corner_map: dict[tuple[str, int], set[int]] = {}
    for (li, lj, ll) in block:
        lspan = KEY_LEVEL - int(ll)
        lstep = 1 << lspan
        lu, lv = int(li) << lspan, int(lj) << lspan
        corner_map.setdefault(("v", lu), set()).update((lv, lv + lstep))
        corner_map.setdefault(("v", lu + lstep), set()).update((lv, lv + lstep))
        corner_map.setdefault(("u", lv), set()).update((lu, lu + lstep))
        corner_map.setdefault(("u", lv + lstep), set()).update((lu, lu + lstep))
    columns = {k: np.sort(np.fromiter(v, dtype=np.int64, count=len(v)))
               for k, v in corner_map.items()}
    found = 0
    dumped = False
    for pos, (i, j, level) in enumerate(block):
        span = tree.key_span(int(level), KEY_LEVEL)
        step = 1 << span
        gu, gv = int(i) << span, int(j) << span
        ring = np.asarray(tree.cell_triangles(int(i), int(j), int(level), span,
                                              extras[pos])[0], dtype=np.int64)
        windows = (("v", gu, gv, step), ("u", gv, gu, step),
                   ("v", gu + step, gv, step), ("u", gv + step, gu, step))
        for edge_index, (orient, line, start, length) in enumerate(windows):
            column = columns.get((orient, int(line)))
            if column is None:
                continue
            lo_i = int(np.searchsorted(column, int(start), side="right"))
            hi_i = int(np.searchsorted(column, int(start) + int(length), side="left"))
            if hi_i <= lo_i:
                continue
            axis = 0 if orient == "v" else 1
            fixed = 1 - axis
            ring_axis = np.sort(ring[ring[:, fixed] == int(line), axis])
            wanted = column[lo_i:hi_i]
            if ring_axis.size:
                at = np.clip(np.searchsorted(ring_axis, wanted), 0, ring_axis.size - 1)
                hit = ring_axis[at] == wanted
            else:
                hit = np.zeros(wanted.shape, dtype=bool)
            if not bool(np.all(hit)):
                found += 1
                if not dumped and int(i) == 31 and int(j) == 26:
                    dumped = True
                    print("  DUMP ring rows:", ring.tolist())
                    print("  DUMP columns on line:",
                          {str(k): v.tolist()[:6] for k, v in columns.items()
                           if str(k[0]) == "v" and int(k[1]) == 260046848})
                if found <= 6:
                    print(f"  MISSING leaf=({i},{j},{level}) edge={edge_index} orient={orient} "
                          f"line={line} start={start} len={length} "
                          f"extras={tuple(int(x) for x in extras[pos])} "
                          f"splits={tree.edge_splits(int(i), int(j), int(level))} "
                          f"missing={[int(v) for v in wanted[~hit][:4]]} "
                          f"ring={[int(v) for v in ring_axis[:8]]}")
    print("edges with a missing hanging point (own audit):", found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
