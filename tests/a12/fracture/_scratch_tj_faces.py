#!/usr/bin/env python
"""Scratch: find which top faces disagree about a given vertex, and read their rings."""
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
from synlab.fracture.cut import _cell_uv  # noqa: E402
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
    tree, block, extras = state["tree"], state["block"], state["extras"]
    top_index: dict[tuple[int, int], int] = {}
    keys_of: dict[int, tuple[int, int]] = {}
    vertices: list[tuple[float, float]] = []

    def top_vertex(level, gi, gj):
        key = (int(gi), int(gj))
        found = top_index.get(key)
        if found is None:
            u, v = _cell_uv(tree, level, KEY_LEVEL - level,
                            np.array([[int(gi), int(gj)]], dtype=np.int64))
            found = len(vertices)
            vertices.append((float(u[0]), float(v[0])))
            top_index[key] = found
            keys_of[found] = key
        return found

    use: Counter[tuple[int, int]] = Counter()
    directed_use: Counter[tuple[int, int]] = Counter()
    incident: dict[int, list[str]] = {}
    rings: list[tuple[tuple[int, int, int], int, list[int]]] = []
    for row, (i, j, level) in enumerate(block):
        span = KEY_LEVEL - int(level)
        pts, tris = tree.cell_triangles(int(i), int(j), int(level), span, extras[row])
        local = [int(top_vertex(int(level), int(p[0]), int(p[1]))) for p in pts]
        rings.append(((int(i), int(j), int(level)), row, local))
        for tri in tris:
            face = (local[tri[0]], local[tri[1]], local[tri[2]])
            if len(set(face)) < 3:
                continue
            for k in range(3):
                a, b = face[k], face[(k + 1) % 3]
                if a == b:
                    continue
                use[(min(a, b), max(a, b))] += 1
                directed_use[(a, b)] += 1
                incident.setdefault(a, []).append(f"({i},{j},{level})")
    odd = {e: n for e, n in use.items() if n != 2}
    odd_vertices = sorted({v for e in odd for v in e})
    print("odd edges:", len(odd), "vertices involved:", len(odd_vertices))
    dup_directed = [(e, n) for e, n in directed_use.items() if n > 1]
    print("directed edges used more than once:", len(dup_directed), dup_directed[:6])
    target = dup_directed[0][0][0] if dup_directed else odd_vertices[0]
    print(f"vertex {target} key={keys_of.get(target)} uv={np.round(vertices[target], 6).tolist()} "
          f"faces={len(incident.get(target, []))} from={sorted(set(incident.get(target, [])))[:8]}")
    print("duplicate directed edges at the target:",
          [(e, n) for e, n in dup_directed if target in e])
    # vertices sharing the target's exact position (a second global vertex for one key point)
    here = np.round(vertices[target], 12)
    twins = [v for v, p in enumerate(vertices) if np.array_equal(np.round(p, 12), here)]
    print("global vertices at that position:", twins, "keys:",
          [keys_of.get(v) for v in twins])
    # how does the neighbour of a duplicated directed edge traverse it?
    for (a, b), n in [e for e in dup_directed if target in e][:2]:
        print(f"  directed ({a},{b}) used {n}x; reverse used "
              f"{directed_use.get((b, a), 0)}x; incident faces at {b}: "
              f"{sorted(set(incident.get(b, [])))[:6]}")
    for (cell, row, local) in rings:
        if target in local:
            span = KEY_LEVEL - cell[2]
            pts = tree.cell_triangles(cell[0], cell[1], cell[2], span, extras[row])[0]
            hx, hy = tree.cell_size(int(cell[2]))
            sequence = [int(v) for v in local]
            print(f"  ring of {cell} extras={tuple(int(x) for x in extras[row])} "
                  f"splits={tree.edge_splits(*cell)} size=({hx:.6f},{hy:.6f}) "
                  f"u0={tree.u0 + cell[0] * hx:.6f} v0={tree.v0 + cell[1] * hy:.6f}")
            print(f"     sequence={sequence}")
            print(f"     keys={[(int(p[0]), int(p[1])) for p in pts]}")
            print(f"     repeated in ring: "
                  f"{[v for v in set(sequence) if sequence.count(v) > 1]}")
    print("odd edges at the target:",
          [(e, n) for e, n in odd.items() if target in e])

    # which cells produced each duplicated directed edge, and through which key points?
    index_of = {tuple(int(x) for x in row): pos for pos, row in enumerate(block)}
    from collections import defaultdict
    ring_sources: dict[tuple[int, int], list[tuple[tuple[int, int, int], tuple[int, int]]]] = \
        defaultdict(list)
    for (cell, row, local) in rings:
        span = KEY_LEVEL - cell[2]
        pts = tree.cell_triangles(cell[0], cell[1], cell[2], span, extras[row])[0]
        seq = list(local)
        for k in range(len(seq)):
            e = (seq[k], seq[(k + 1) % len(seq)])
            ring_sources[e].append((cell, (int(pts[k][0]), int(pts[k][1]))))
    # every emitted triangle that touches the target vertex, with its cell
    touching: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = []
    for row, (i, j, level) in enumerate(block):
        span = KEY_LEVEL - int(level)
        _pts, tris = tree.cell_triangles(int(i), int(j), int(level), span, extras[row])
        local = [int(v) for v in rings[row][2]]
        for tri in tris:
            face = (local[tri[0]], local[tri[1]], local[tri[2]])
            if len(set(face)) < 3:
                continue
            if target in face:
                touching.append(((int(i), int(j), int(level)), face))
    print(f"triangles touching vertex {target}: {len(touching)}")
    for entry in touching:
        print("   ", entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
