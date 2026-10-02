#!/usr/bin/env python
"""Measure the per-cell triangulation of ``_Quadtree.cell_triangles`` for all 13 split patterns.

Writes ``data/a12_reports/cutfix/cell_triangulation_<label>.json``.

For every ``(n_split, which edges)`` combination this records

* the shoelace area sum of the returned triangles (the unit cell has area 1.0);
* the count of *positive area* / degenerate triangles;
* the per-triangle signed area (so an overlap -- a negative or duplicated triangle -- is visible);
* an undirected edge-use histogram of the triangulation *on its own* (no side quads): every
  interior edge of the tiling must be used twice, every boundary edge once.  The correct
  combination is therefore ``{"1": <boundary segments>, "2": <interior edges>}`` and, crucially,
  ``edge_use_histogram["3"..]`` must be empty and no boundary segment may be missing.

The split flags are not faked: a ``_Quadtree`` is built and its neighbours are refined exactly the
way :meth:`_Quadtree.edge_split` reads them (``is_refined(sibling, level)``), so the flags come out
of the production predicate.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.fracture.cut import _cell_uv, _Quadtree  # noqa: E402

SPAN = 4                     # key span used for the probe (uniform scaling; areas are key-space)
LEVEL = 0
TARGET = (1, 1)              # target leaf inside the root grid
ROOT_LEVEL = 2               # side = 4 -> a 2x2 neighbourhood exists around TARGET


def _tree_with_flags(flags: tuple[bool, bool, bool, bool]) -> _Quadtree:
    """Quadtree whose ``TARGET`` cell reports exactly ``flags`` = (v0, u0, v1, u1) as split."""
    tree = _Quadtree(0.0, 4.0, 0.0, 4.0, ROOT_LEVEL)
    i, j = TARGET
    wants = {
        (i - 1, j): flags[0],   # left  neighbour, "v" lo
        (i, j - 1): flags[1],   # lower neighbour, "u" lo
        (i + 1, j): flags[2],   # right neighbour, "v" hi
        (i, j + 1): flags[3],   # upper neighbour, "u" hi
    }
    for (ni, nj), want in wants.items():
        if want:
            tree.refined.add((ni, nj, LEVEL))
    return tree


def _signed_area(tri: np.ndarray) -> float:
    (x0, y0), (x1, y1), (x2, y2) = tri
    return 0.5 * ((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0))


def _union_area(key: np.ndarray, tris: np.ndarray, res: int = 2048) -> float:
    """Rasterised measure of ``|union of the triangles|`` in key space (split-cell exactness).

    Summing the *signed* areas cannot see an overlap (two positive triangles covering the same
    region add up); the union can.  The lattice is sampled at cell centres and the count is a
    lower bound of the union area whose error is one lattice cell per triangle boundary.
    """
    h = float(key[:, 0].max() - key[:, 0].min()) / res
    gx = key[:, 0].min() + (np.arange(res) + 0.5) * h
    gy = key[:, 1].min() + (np.arange(res) + 0.5) * h
    X, Y = np.meshgrid(gx, gy, indexing="ij")
    covered = np.zeros(X.shape, dtype=bool)
    for t in tris:
        p, q, r = key[t[0]], key[t[1]], key[t[2]]
        d = (q[1] - r[1]) * (p[0] - r[0]) + (r[0] - q[0]) * (p[1] - r[1])
        if abs(d) < 1e-12:
            continue
        w0 = ((q[1] - r[1]) * (X - r[0]) + (r[0] - q[0]) * (Y - r[1])) / d
        w1 = ((r[1] - p[1]) * (X - r[0]) + (p[0] - r[0]) * (Y - r[1])) / d
        inside = (w0 >= 0) & (w1 >= 0) & (w0 + w1 <= 1)
        covered |= inside
    return float(covered.sum()) * h * h

def measure(flags: tuple[bool, bool, bool, bool]) -> dict:
    tree = _tree_with_flags(flags)
    tree.edge_splits(*TARGET, LEVEL)          # sanity: the tree really reports these flags
    pts, tris = tree.cell_triangles(*TARGET, LEVEL, SPAN)
    got = tree.edge_splits(*TARGET, LEVEL)
    u, v = _cell_uv(tree, LEVEL, SPAN, pts)
    xy = np.stack([u, v], axis=1)
    key = np.stack([pts[:, 0], pts[:, 1]], axis=1).astype(np.float64)
    areas_key = np.array([_signed_area(key[t]) for t in tris])
    areas_world = np.array([_signed_area(xy[t]) for t in tris])
    uses: Counter[tuple[int, int]] = Counter()
    for t in tris:
        for k in range(3):
            a, b = int(t[k]), int(t[(k + 1) % 3])
            uses[(min(a, b), max(a, b))] += 1
    histogram = Counter(uses.values())
    boundary_edges = int(sum(1 for value in uses.values() if value == 1))
    over_used = int(sum(count for use, count in histogram.items() if use > 2))
    n_expected_boundary = 4 + int(sum(flags))
    return {
        "flags_v0_u0_v1_u1": [bool(x) for x in flags],
        "n_split": int(sum(flags)),
        "flags_reported_by_tree": [bool(x) for x in got],
        "points": int(pts.shape[0]),
        "triangles": int(tris.shape[0]),
        "area_key": float(areas_key.sum()),
        "area_world": float(areas_world.sum()),
        "union_area_key": _union_area(key, tris),
        "min_signed_area": float(areas_key.min()),
        "degenerate_triangles": int(np.sum(areas_key <= 0.0)),
        "negative_triangles": int(np.sum(areas_key < 0.0)),
        "edge_use_histogram": {str(k): int(c) for k, c in sorted(histogram.items())},
        "boundary_segments": boundary_edges,
        "boundary_segments_expected": n_expected_boundary,
        "boundary_complete": boundary_edges == n_expected_boundary,
        "over_used_edges": over_used,
        "edge_check_ok": (set(histogram) <= {1, 2}) and boundary_edges == n_expected_boundary,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="head")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    combos = []
    for n in range(5):
        for mask in itertools.combinations(range(4), n):
            flags = tuple(idx in mask for idx in range(4))
            combos.append(flags)

    rows = [measure(flags) for flags in combos]
    payload = {
        "source": "synlab.fracture.cut._Quadtree.cell_triangles",
        "label": args.label,
        "span": SPAN,
        "unit_cell_area": 1.0,
        "combinations": len(rows),
        "area_tolerance": 1e-9,
        "area_ok_all": all(abs(r["area_key"] / 256.0 - 1.0) <= 1e-9 for r in rows),
        "union_area_ok_all": all(abs(r["union_area_key"] / 256.0 - 1.0) <= 2e-3 for r in rows),
        "no_degenerate_all": all(r["degenerate_triangles"] == 0 for r in rows),
        "edge_check_ok_all": all(r["edge_check_ok"] for r in rows),
        "rows": rows,
    }
    out = Path(args.out) if args.out else (
        REPO_ROOT / "data" / "a12_reports" / "cutfix" / f"cell_triangulation_{args.label}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"[written] {out}")
    header = f"{'flags v0u0v1u1':>16} {'n':>2} {'pts':>4} {'tris':>5} {'area':>10} " \
             f"{'union':>10} {'degen':>5} {'neg':>4} {'hist':>22} {'bnd':>5} ok"
    print(header)
    for r in rows:
        flags = "".join("1" if x else "0" for x in r["flags_v0_u0_v1_u1"])
        print(f"{flags:>16} {r['n_split']:>2} {r['points']:>4} {r['triangles']:>5} "
              f"{r['area_key'] / 256.0:>10.6f} {r['union_area_key'] / 256.0:>10.6f} "
              f"{r['degenerate_triangles']:>5} "
              f"{r['negative_triangles']:>4} {json.dumps(r['edge_use_histogram']):>22} "
              f"{r['boundary_segments']:>5} {r['edge_check_ok']}")
    print(f"area_ok_all={payload['area_ok_all']} union_area_ok_all={payload['union_area_ok_all']} "
          f"no_degenerate_all={payload['no_degenerate_all']} "
          f"edge_check_ok_all={payload['edge_check_ok_all']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
