"""Scratch: localise the remaining non-2 edges of a refined cutter.

Reproduces the ``test_shared_cutter`` rough bowl fixture, catches ``CUTTER_NOT_CLOSED`` and, from
the *reported* numbers only, re-derives what the surplus looks like.  To see the offending
triangles the probe re-runs the assembly with a hook that records every top triangle together with
the leaf that emitted it, then groups the over-used edges by (leaf level, split pattern).
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.errors import SynLabError  # noqa: E402
from synlab.fracture import cut as cut_mod  # noqa: E402
from synlab.fracture.api import make_closed_cutter  # noqa: E402
from synlab.fracture.spec import BACKEND_ROUGH, FractureSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

import fixtures as fx  # noqa: E402


def run() -> int:
    mother = fx.thin_bowl_mother()
    rng = make_rng(20261001, "fracture_test", BACKEND_ROUGH)
    spec = FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=0.05)

    # ---- 1. census the split patterns actually used, and the triangles per leaf
    shapes: Counter[tuple[int, int]] = Counter()
    original = cut_mod._Quadtree.cell_triangles

    def wrapped(self, i, j, level, span):
        pts, tris = original(self, i, j, level, span)
        shapes[(int(sum(self.edge_splits(i, j, level))), int(tris.shape[0]))] += 1
        return pts, tris

    cut_mod._Quadtree.cell_triangles = wrapped
    try:
        make_closed_cutter(mother, spec, rng)
        print("cutter built OK")
        return 0
    except SynLabError as exc:
        print(f"refused: {exc.code}")
        print(f"measurements: {exc.measurements}")
    finally:
        cut_mod._Quadtree.cell_triangles = original

    print("\n(n_split, triangles) census over all cell_triangles calls:")
    for key, count in sorted(shapes.items()):
        print(f"  n_split={key[0]} tris={key[1]}: {count}")

    # ---- 2. rebuild the height field and inspect the vertices involved in bad edges
    spec2 = FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=0.05)
    rng2 = make_rng(20261001, "fracture_test", BACKEND_ROUGH)
    from synlab.fracture.api import _default_basis

    basis = _default_basis(mother, rng2, spec2)
    height = cut_mod.make_height_field(basis, rng2, target_rms_mm=0.05,
                                      n_bands=spec2.n_bands)
    height = cut_mod.attach_material_band(height, mother.mesh)

    # capture the assembled faces by wrapping the region around the verify step: the report does
    # not expose them, so rebuild with a monkey-patched edge counter.
    detail: dict = {}
    original_hash = cut_mod.hash_json

    def patched_hash(payload):  # capture verts/faces on the way out
        if isinstance(payload, dict) and "v" in payload and "f" in payload:
            detail["verts"] = np.asarray(payload["v"], dtype=np.float64)
            detail["faces"] = np.asarray(payload["f"], dtype=np.int64)
        return original_hash(payload)

    cut_mod.hash_json = patched_hash
    try:
        cut_mod.build_closed_cutter(basis, height, error_budget_mm=0.01,
                                    max_cells=int(spec2.max_cutter_cells))
    except SynLabError as exc:
        print(f"\nrebuild refused (expected): {exc.measurements}")
    finally:
        cut_mod.hash_json = original_hash

    verts = detail.get("verts")
    faces = detail.get("faces")
    if verts is None or faces is None:
        print("no faces captured")
        return 1

    a = faces[:, [0, 1, 2]].ravel()
    b = faces[:, [1, 2, 0]].ravel()
    low = np.minimum(a, b)
    high = np.maximum(a, b)
    keys = np.stack([low, high], axis=1)
    unique, counts = np.unique(keys, axis=0, return_counts=True)
    histogram = Counter(counts.tolist())
    print(f"\nexported faces={faces.shape[0]} vertices={verts.shape[0]}")
    print(f"edge-use histogram: {dict(sorted(histogram.items()))}")
    bad = unique[counts != 2]
    print(f"bad edges: {bad.shape[0]}")
    if bad.shape[0]:
        top = bad[:12]
        for edge in top:
            p = verts[edge[0]]
            q = verts[edge[1]]
            length = float(np.linalg.norm(p - q))
            print(f"  {tuple(int(x) for x in edge)} len={length:.6e} "
                  f"p={np.round(p, 6).tolist()} q={np.round(q, 6).tolist()}")
        lengths = np.linalg.norm(verts[bad[:, 0]] - verts[bad[:, 1]], axis=1)
        print(f"bad edge length: min={lengths.min():.3e} median={np.median(lengths):.3e} "
              f"max={lengths.max():.3e}")
        zero = int(np.sum(lengths < 1e-12))
        print(f"zero-length bad edges: {zero} / {bad.shape[0]}")
        dup = defaultdict(int)
        for edge in bad:
            dup[tuple(np.round(verts[edge[0]], 9))] += 1
        print(f"distinct bad-edge first vertices: {len(dup)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
