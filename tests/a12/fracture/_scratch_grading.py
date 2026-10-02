"""Scratch: the level grading of the *real* refinement fixed point.

For every leaf and each of its four edges this finds the leaf on the other side **by world key**
(a cell at level ``l`` with index ``(i, j)`` occupies keys ``i << (KL - l)`` onward, so a world key
point identifies a leaf unambiguously no matter which level it lives at) and records the level
difference.  A 2:1-graded quadtree shows only differences in ``{-1, 0, +1}``; any ``+2`` or more is
a place where one midpoint cannot make the two sides agree, i.e. where the top surface is
necessarily non-conforming.

Usage: ``_scratch_grading.py [--vessel V18] [--rms 0.05] [--budget 0.01] [--max-cells N]``
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synlab.fracture import cut as cut_mod  # noqa: E402
from synlab.fracture.spec import BACKEND_ROUGH, FractureSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

KEY_LEVEL = 23


def key_of(i: int, j: int, level: int) -> tuple[int, int]:
    """World key coordinates of a cell's lower-left corner.

    A level-``level`` cell's local index unit is ``cell_size(level) / 2 ** (KEY_LEVEL - level)``,
    i.e. one key unit, so its corner key is simply ``i << (KEY_LEVEL - level)``.
    """
    shift = KEY_LEVEL - int(level)
    return int(i) << shift, int(j) << shift


def leaf_at_key(tree, ki: int, kj: int):
    """Descend the tree to the leaf covering world key ``(ki, kj)``.

    The descent must track **two** different indices: the cell's index on its own level lattice
    (``2 * parent + bit``, starting from the root grid index ``ki >> (KEY_LEVEL - log2(side))``)
    and the index of the corresponding key bit, which is ``KEY_LEVEL - 1 - depth`` and therefore
    independent of ``side``.  Conflating the two silently stops at the root cell and reports every
    neighbour as level 0.
    """
    root_level = int(tree.root_level)
    cell_i = int(ki) >> (KEY_LEVEL - root_level)
    cell_j = int(kj) >> (KEY_LEVEL - root_level)
    i, j, level, depth = cell_i, cell_j, 0, root_level
    while tree.is_refined(i, j, level):
        bit = KEY_LEVEL - 1 - depth
        ci = (int(ki) >> bit) & 1
        cj = (int(kj) >> bit) & 1
        i, j, level, depth = 2 * i + ci, 2 * j + cj, level + 1, depth + 1
    return i, j, level


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default=None)
    parser.add_argument("--material", default="M01")
    parser.add_argument("--rms", type=float, default=0.05)
    parser.add_argument("--budget", type=float, default=0.01)
    parser.add_argument("--max-cells", type=int, default=400000)
    args = parser.parse_args()

    if args.vessel:
        from synlab.mothers.api import create_mother
        mother = create_mother(args.vessel, args.material, {}, make_rng(20261001, "shape"),
                              mother_id=f"{args.vessel}-{args.material}-grading")
        source = f"{args.vessel}/{args.material}"
    else:
        import fixtures as fx
        mother = fx.thin_bowl_mother()
        source = "fixture thin_bowl"

    from synlab.fracture.api import _default_basis
    spec = FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=args.rms,
                        error_budget_mm=args.budget, max_cutter_cells=args.max_cells)
    rng = make_rng(20261001, "grading_probe", "cut")
    basis = _default_basis(mother, rng, spec)
    height = cut_mod.make_height_field(basis, rng, target_rms_mm=args.rms, n_bands=spec.n_bands)
    height = cut_mod.attach_material_band(height, mother.mesh)

    captured: dict = {}
    base = cut_mod._Quadtree

    class Capturing(base):                       # type: ignore[misc, valid-type]
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            captured["tree"] = self

    cut_mod._Quadtree = Capturing
    try:
        cut_mod.build_closed_cutter(basis, height, error_budget_mm=args.budget,
                                    max_cells=args.max_cells)
        status = "OK"
    except Exception as exc:                     # noqa: BLE001 - probe reports, never raises
        status = f"{type(exc).__name__}: {str(exc)[:140]}"
    finally:
        cut_mod._Quadtree = base

    print(f"mother: {source}")
    print(f"status: {status}")
    tree = captured.get("tree")
    if tree is None:
        return 1
    leaves = tree.leaves()
    print(f"leaves: {len(leaves)}   side={tree.side}   root_level={tree.root_level}")
    print(f"leaf levels: {dict(sorted(Counter(lv for _i, _j, lv in leaves).items()))}")

    key_limit = int(tree.side) << KEY_LEVEL
    grading = Counter()
    total = 0
    for i, j, level in leaves:
        ki, kj = key_of(i, j, level)
        stride = 1 << (KEY_LEVEL - level)
        for orient, lo in (("v", True), ("u", True), ("v", False), ("u", False)):
            if orient == "v":
                nki = ki - 1 if lo else ki + stride
                nkj = kj + (stride >> 1)
            else:
                nkj = kj - 1 if lo else kj + stride
                nki = ki + (stride >> 1)
            if not (0 <= nki < key_limit and 0 <= nkj < key_limit):
                grading["frame"] += 1
                continue
            _oi, _oj, ol = leaf_at_key(tree, nki, nkj)
            grading[ol - level] += 1
            total += 1
    print(f"adjacent-leaf level differences (neighbour - mine) over {total} interior edges:")
    for delta, count in sorted(grading.items(), key=lambda kv: (isinstance(kv[0], str), kv[0])):
        print(f"   {delta}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
