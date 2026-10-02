"""Debug 13: does a *conforming ring* triangulation make the mixed-level lattice manifold?

The current `cell_triangles` picks a fixed template from four boolean edge-split flags.  That is
conforming only while the flag agrees with the *actual* leaf across the edge.  Here the ring is
built from the union of the leaf's own key points and every corner the surrounding leaves place on
its boundary, all on the absolute key lattice, so a T-junction cannot survive by construction.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests" / "a12" / "fracture"))

import numpy as np  # noqa: E402

sys.path.insert(0, str(REPO / "_a12pl"))
from p11_locate import build_tree_and_field  # noqa: E402

KEY_LEVEL = 23


def main() -> int:
    tree, cut_mod = build_tree_and_field()
    leaves = tree.leaves()
    leaf_set = set(leaves)
    # leaf_span per level (absolute scale cancels, so use the absolute key lattice)
    spans = {level: tree.key_span(level, KEY_LEVEL) for level in range(0, KEY_LEVEL)}

    def boundary_keys(i, j, level):
        """Absolute key coordinates of the four corners of a leaf."""
        span = spans[level]
        c00 = (i << span, j << span)
        c10 = (c00[0] + (1 << span), c00[1])
        c11 = (c00[0] + (1 << span), c00[1] + (1 << span))
        c01 = (c00[0], c00[1] + (1 << span))
        return c00, c10, c11, c01

    # gather, per leaf, every key point that any *surrounding* leaf places on its boundary.
    # A surrounding leaf is one whose key rectangle touches this leaf's rectangle.
    from collections import defaultdict

    corners: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    corner_owner: dict[tuple[int, int], int] = {}
    rects = {}
    for index, (i, j, level) in enumerate(leaves):
        c00, c10, c11, c01 = boundary_keys(i, j, level)
        rects[index] = (c00[0], c00[1], c11[0], c11[1], level, i, j)
        for key in (c00, c10, c11, c01):
            corner_owner.setdefault(key, index)
    # bucket leaves by their key bounding box for a cheap neighbour query
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    fine = min(spans[level] for (_, _, level) in leaves)
    bucket_shift = max(fine - 6, 0)
    for index, (x0, y0, x1, y1, _level, _i, _j) in rects.items():
        bx0, by0 = x0 >> bucket_shift, y0 >> bucket_shift
        bx1, by1 = x1 >> bucket_shift, y1 >> bucket_shift
        for bx in range(bx0, bx1 + 1):
            for by in range(by0, by1 + 1):
                buckets[(bx, by)].append(index)
    for index, (i, j, level) in enumerate(leaves):
        x0, y0, x1, y1, _l, _ii, _jj = rects[index]
        span = spans[level]
        step = 1 << span
        points = list(boundary_keys(i, j, level))
        bx0, by0 = (x0 - step) >> bucket_shift, (y0 - step) >> bucket_shift
        bx1, by1 = (x1 + step) >> bucket_shift, (y1 + step) >> bucket_shift
        seen = set()
        for bx in range(bx0, bx1 + 1):
            for by in range(by0, by1 + 1):
                for other in buckets.get((bx, by), ()):
                    if other in seen:
                        continue
                    seen.add(other)
                    ox0, oy0, ox1, oy1, _ol, _oi, _oj = rects[other]
                    if ox1 < x0 or ox0 > x1 or oy1 < y0 or oy0 > y1:
                        continue
                    # only corners that lie ON this leaf's boundary and inside its span
                    for key in ((ox0, oy0), (ox1, oy0), (ox1, oy1), (ox0, oy1)):
                        if not (x0 <= key[0] <= x1 and y0 <= key[1] <= y1):
                            continue
                        on = (key[0] in (x0, x1)) or (key[1] in (y0, y1))
                        if not on:
                            continue
                        if key in points:
                            continue
                        points.append(key)
        corners[index] = points

    # ---- ring assembly per leaf
    faces: list[tuple[int, int]] = []
    vertex_of: dict[tuple[int, int], int] = {}
    world: list[tuple[float, float]] = []

    def vertex(key):
        got = vertex_of.get(key)
        if got is None:
            got = len(world)
            # absolute key -> world: level 0 has span 23; a key unit is hx / 2**23
            u = tree.u0 + key[0] * (tree.hx / float(1 << KEY_LEVEL))
            v = tree.v0 + key[1] * (tree.hy / float(1 << KEY_LEVEL))
            world.append((u, v))
            vertex_of[key] = got
        return got

    stats = Counter()
    for index, (i, j, level) in enumerate(leaves):
        x0, y0, x1, y1, _l, _ii, _jj = rects[index]
        pts = corners[index]
        # order the boundary points: bottom (y=y0, x asc), right (x=x1, y asc),
        # top (y=y1, x desc), left (x=x0, y desc)
        bottom = sorted([p for p in pts if p[1] == y0], key=lambda p: p[0])
        right = sorted([p for p in pts if p[0] == x1 and p[1] != y0 and p[1] != y1],
                       key=lambda p: p[1])
        top = sorted([p for p in pts if p[1] == y1 and p[0] != x1], key=lambda p: -p[0])
        left = sorted([p for p in pts if p[0] == x0 and p[1] != y0 and p[1] != y1],
                      key=lambda p: -p[1])
        ring = bottom + right + top + left
        # dedupe consecutive duplicates (and the wrap)
        dedup = []
        for key in ring:
            if dedup and dedup[-1] == key:
                continue
            dedup.append(key)
        if len(dedup) > 1 and dedup[0] == dedup[-1]:
            dedup.pop()
        if len(dedup) < 3:
            stats["degenerate_ring"] += 1
            continue
        centre = (x0 + (x1 - x0) // 2, y0 + (y1 - y0) // 2)
        if centre[0] > x1:
            centre = (x1 - 1, centre[1])
        cidx = vertex(centre)
        ring_idx = [vertex(key) for key in dedup]
        for k in range(len(ring_idx)):
            a = ring_idx[k]
            b = ring_idx[(k + 1) % len(ring_idx)]
            if a == b:
                continue
            faces.append((a, b, cidx))

    # manifold census on the geometric segments
    seg_fwd: Counter = Counter()
    seg_rev: Counter = Counter()
    for face in faces:
        for k in range(3):
            a, b = face[k], face[(k + 1) % 3]
            key = (world[a], world[b])
            if key[0] == key[1]:
                continue
            if key[0] < key[1]:
                seg_fwd[key] += 1
            else:
                seg_rev[(key[1], key[0])] += 1
    boundary = overlap = 0
    for key in set(seg_fwd) | set(seg_rev):
        f, r = seg_fwd.get(key, 0), seg_rev.get(key, 0)
        if f == 1 and r == 1:
            continue
        if f + r == 1:
            boundary += 1
        else:
            overlap += 1
    print(json.dumps({"leaves": len(leaves), "faces": len(faces),
                      "vertices": len(world), "ring_stats": dict(stats),
                      "segments": len(set(seg_fwd) | set(seg_rev)),
                      "conforming": len(set(seg_fwd) | set(seg_rev)) - boundary - overlap,
                      "boundary_once": boundary, "overlap_or_dup": overlap},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
