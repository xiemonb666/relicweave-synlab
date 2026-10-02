"""Scratch: compare the new fan against the *frozen baseline* implementation, cell by cell.

Loads ``data/a12/reports/baseline_head/synlab/fracture/cut.py`` as a standalone module (its
imports are resolved against the repo package layout) and calls its ``_Quadtree.cell_triangles``
for every split pattern, then the same on the live module.  Reports, per pattern:

* whether the two return the same *vertex set* and the same *triangle set*;
* the total triangle area of each;
* the per-cell edge-use histogram of each (on the triangulation alone).

This is the evidence that the rewrite changes exactly the broken patterns and leaves the
``n_split == 0`` path (the only one a flat field takes) untouched.
"""

from __future__ import annotations

import ast
import itertools
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BASELINE = (REPO_ROOT / "data" / "a12" / "reports" / "baseline_head" / "synlab"
            / "fracture" / "cut.py")


def load_baseline():
    """Compile just the frozen ``_Quadtree`` class out of the baseline source file.

    Importing the file as a module would collide with the live ``synlab`` package (its relative
    imports are the production ones), so only the class definition is extracted: that is the unit
    under test and it needs no module-level dependency beyond ``np``/``SynLabError``.
    """
    from synlab.errors import ErrorCode, SynLabError

    source = BASELINE.read_text(encoding="utf-8")
    module_ast = ast.parse(source)
    node = next(n for n in module_ast.body
                if isinstance(n, ast.ClassDef) and n.name == "_Quadtree")
    extracted = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(extracted)
    namespace: dict = {"np": np, "SynLabError": SynLabError, "ErrorCode": ErrorCode}
    exec(compile(extracted, str(BASELINE), "exec"), namespace)  # noqa: S102 - frozen baseline
    return namespace["_Quadtree"]


def build(tree_cls, flags):
    tree = tree_cls(0.0, 4.0, 0.0, 4.0, 2)
    i, j = 1, 1
    wants = {(i - 1, j): flags[0], (i, j - 1): flags[1],
             (i + 1, j): flags[2], (i, j + 1): flags[3]}
    for (ni, nj), want in wants.items():
        if want:
            tree.refined.add((ni, nj, 0))
    return tree.cell_triangles(i, j, 0, 4)


def describe(pts, tris):
    xy = np.asarray(pts, dtype=np.float64)
    areas = []
    for t in tris:
        a, b, c = xy[t[0]], xy[t[1]], xy[t[2]]
        areas.append(0.5 * ((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])))
    areas = np.asarray(areas)
    uses: Counter[tuple[int, int]] = Counter()
    for t in tris:
        for k in range(3):
            a, b = int(t[k]), int(t[(k + 1) % 3])
            uses[(min(a, b), max(a, b))] += 1
    return {
        "area": float(areas.sum()),
        "positive": int(np.sum(areas > 0)),
        "negative": int(np.sum(areas < 0)),
        "zero": int(np.sum(areas == 0)),
        "hist": {str(k): int(v) for k, v in sorted(Counter(uses.values()).items())},
        "point_set": sorted(tuple(int(x) for x in p) for p in pts),
        "triangle_set": sorted(tuple(sorted(tuple(int(x) for x in pts[k]) for k in t))
                               for t in tris),
    }


def main() -> int:
    OldTree = load_baseline()
    from synlab.fracture.cut import _Quadtree as NewTree  # noqa: E402

    print(f"baseline module: {BASELINE}")
    print(f"{'flags':>8} {'old_area':>9} {'new_area':>9} {'old_hist':>24} {'new_hist':>24} "
          f"{'pts==':>6} {'tris==':>7} {'old +/-/0':>10} {'new +/-/0':>10}")
    differ = []
    for n in range(5):
        for mask in itertools.combinations(range(4), n):
            flags = tuple(idx in mask for idx in range(4))
            opt, otri = build(OldTree, flags)
            npt, ntri = build(NewTree, flags)
            old = describe(opt, otri)
            new = describe(npt, ntri)
            same_pts = old["point_set"] == new["point_set"]
            same_tris = old["triangle_set"] == new["triangle_set"]
            tag = "".join("1" if x else "0" for x in flags)
            print(f"{tag:>8} {old['area'] / 256.0:>9.6f} {new['area'] / 256.0:>9.6f} "
                  f"{str(old['hist']):>24} {str(new['hist']):>24} "
                  f"{str(same_pts):>6} {str(same_tris):>7} "
                  f"{old['positive']}/{old['negative']}/{old['zero']:>2} "
                  f"{new['positive']}/{new['negative']}/{new['zero']:>2}")
            if not same_tris:
                differ.append((tag, old["area"] / 256.0, new["area"] / 256.0))
    print(f"patterns whose triangle set changed: {len(differ)}")
    for tag, oa, na in differ:
        print(f"  {tag}: area {oa:.6f} -> {na:.6f}")
    unchanged = [t for t, _, _ in differ if t == "0000"]
    print(f"'0000' (the flat-field path) changed: {bool(unchanged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

