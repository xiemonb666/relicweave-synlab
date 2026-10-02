#!/usr/bin/env python
"""Scratch: is the *top surface* itself conformal?  Count undirected top-edge usage.

``build_closed_cutter`` measures top-edge usage only to decide which edges are on the silhouette;
this reproduces that bookkeeping for the captured tree and prints where the top surface uses an
edge more than twice (an overlap) -- before any side quad is built.
"""
from __future__ import annotations

import sys
from collections import Counter
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


def main() -> int:
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
    except Exception as exc:  # noqa: BLE001
        print("build:", type(exc).__name__, str(exc).split("\n", 1)[0])
    finally:
        cut_mod.edge_extra_all = real_extras

    state = calls[-1]
    tree = state["tree"]
    block = state["block"]
    extras = state["extras"]
    print("leaves", block.shape[0], "side", tree.side)

    top_index: dict[tuple[int, int], int] = {}
    vertices: list[tuple[float, float, float]] = []
    from synlab.fracture.cut import _cell_uv

    def top_vertex(level, gi, gj):
        shift = KEY_LEVEL - level
        key = (int(gi), int(gj))
        found = top_index.get(key)
        if found is None:
            u, v = _cell_uv(tree, level, shift, np.array([[int(gi), int(gj)]], dtype=np.int64))
            found = len(vertices)
            vertices.append((float(u[0]), float(v[0]), 0.0))
            top_index[key] = found
        return found

    use: Counter[tuple[int, int]] = Counter()
    directed: Counter[tuple[int, int]] = Counter()
    for row, (i, j, level) in enumerate(block):
        span = KEY_LEVEL - int(level)
        pts, tris = tree.cell_triangles(int(i), int(j), int(level), span, extras[row])
        local = [top_vertex(int(level), int(p[0]), int(p[1])) for p in pts]
        for tri in tris:
            face = (local[tri[0]], local[tri[1]], local[tri[2]])
            if len(set(face)) < 3:
                continue
            for k in range(3):
                a, b = face[k], face[(k + 1) % 3]
                if a == b:
                    continue
                use[(min(a, b), max(a, b))] += 1
                directed[(a, b)] += 1

    hist = Counter(use.values())
    print("top undirected edge-use histogram:", dict(sorted(hist.items())))
    print("top directed edge-use histogram:", dict(sorted(Counter(directed.values()).items())))
    odd = [(e, n) for e, n in use.items() if n != 2]
    print("top edges not used exactly twice:", len(odd))
    coords = np.asarray(vertices, dtype=np.float64)
    dup = coords.shape[0] - np.unique(np.round(coords, 12), axis=0).shape[0]
    print("vertices", coords.shape[0], "coincident positions", int(dup))
    for (a, b), n in sorted(odd, key=lambda kv: -kv[1])[:6]:
        print(f"   edge {a}-{b} used {n}: {coords[a]} / {coords[b]}")
    both = [(e, n) for e, n in directed.items() if n > 1]
    print("directed edges used more than once:", len(both), both[:4])

    # ---- where do the single-use top edges live?  (frame vs material band)
    def bbox(edges):
        pts = np.array([[coords[a], coords[b]] for (a, b), _n in edges]).reshape(-1, 3)
        return (np.round(pts.min(axis=0), 4).tolist(), np.round(pts.max(axis=0), 4).tolist())

    one = [(e, n) for e, n in odd if n == 1]
    print("single-use edges:", len(one), "bbox", bbox(one))
    material = [e for e in one
                if max(abs(coords[e[0][0]][0]), abs(coords[e[0][1]][0])) < 13.0
                and max(abs(coords[e[0][0]][1]), abs(coords[e[0][1]][1])) < 13.0]
    print("single-use edges inside the material bbox (|u|,|v| < 13):", len(material))
    if material:
        print("  bbox", bbox(material))
        interesting = material[:4]
    else:
        interesting = one[:2]
    for (a, b), n in interesting:
        print(f"  single-use edge {a}-{b} (n={n}) z={coords[a][2]:.6f} "
              f"A={np.round(coords[a], 6).tolist()} B={np.round(coords[b], 6).tolist()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
