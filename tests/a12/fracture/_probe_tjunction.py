#!/usr/bin/env python
"""T-junction probe: is the *assembled* top surface non-conforming, and where?

The cutfix campaign (``docs/a12/fracture_realism.md`` §10.5) located the remaining defect as
"edges used once" on the top surface of a refined cutter, and attributed them to *mixed-level*
interfaces.  This probe measures the structure of that defect on the real refinement fixed point
instead of guessing:

* the leaf-level histogram of the final quadtree;
* for every leaf edge, the level of **every leaf across it** (walking the neighbour side in the
  real tree), so the level-difference histogram is measured, not assumed;
* for every leaf edge, how many *leaf corner keys* fall strictly inside it (the true T-junction
  count of a corner-keyed conforming ring) versus what ``_Quadtree.edge_split`` decides;
* the assembled solid's edge-use histogram when the build succeeds, or the faces the assembler
  produced when it is refused (captured through the ``trimesh.Trimesh`` call site).

Nothing here is part of the production path; the assertions live in
``tests/a12/fracture/test_tjunction_assembly.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import types
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.errors import SynLabError  # noqa: E402
from synlab.fracture import cut as cut_mod  # noqa: E402
from synlab.fracture.api import make_closed_cutter  # noqa: E402
from synlab.fracture.spec import BACKEND_PLANE, BACKEND_ROUGH, FractureSpec  # noqa: E402

#: ``build_closed_cutter`` fixes ``key_level = max_level + 1`` with ``max_level = 22``.
KEY_LEVEL = 23


def leaf_of_key(tree: Any, key_level: int, ku: int, kv: int) -> tuple[int, int, int]:
    """Leaf containing a *key-lattice integer point* by descending from the root."""
    level = 0
    while True:
        shift = int(key_level) - level
        if shift < 0:
            raise RuntimeError("descended past the key lattice")
        i, j = int(ku) >> shift, int(kv) >> shift
        if not tree.is_refined(i, j, level):
            return i, j, level
        level += 1


def neighbour_edges(tree: Any, leaf: tuple[int, int, int], key_level: int,
                    orient: str, lo: bool) -> list[tuple[int, int, int]]:
    """Every leaf across one side of ``leaf``, in order along the edge.

    ``orient == "v"`` is the vertical edge at the cell's ``lo``/``hi`` u, ``orient == "u"`` the
    horizontal edge at its ``lo``/``hi`` v.  The walk steps by the neighbour's own extent, so the
    cost is the number of neighbours, not the edge length in key units.
    """
    i, j, level = (int(x) for x in leaf)
    span = int(key_level) - level
    step = 1 << span
    gi, gj = i << span, j << span
    if orient == "v":
        line = gi if lo else gi + step
        probe = line - 1 if lo else line + 1          # one key unit inside the neighbour side
        lo_k, hi_k = gj, gj + step
        fixed_axis = "u"
    else:
        line = gj if lo else gj + step
        probe = line - 1 if lo else line + 1
        lo_k, hi_k = gi, gi + step
        fixed_axis = "v"
    out: list[tuple[int, int, int]] = []
    cursor = int(lo_k)
    while cursor < int(hi_k):
        if fixed_axis == "u":
            ni, nj, nl = leaf_of_key(tree, key_level, probe, cursor)
        else:
            ni, nj, nl = leaf_of_key(tree, key_level, cursor, probe)
        out.append((ni, nj, nl))
        nspan = int(key_level) - nl
        next_boundary = ((nj >> nspan) + 1) << nspan if fixed_axis == "u" \
            else ((ni >> nspan) + 1) << nspan
        if next_boundary <= cursor:                    # pragma: no cover - safety
            next_boundary = cursor + 1
        cursor = int(next_boundary)
    return out


def analyse(tree: Any, leaves: list[tuple[int, int, int]], key_level: int = KEY_LEVEL) -> dict[str, Any]:
    """Measure the conforming structure of the final leaf set."""
    levels = Counter(int(level) for (_, _, level) in leaves)
    #: key-lattice u -> sorted key-lattice v of every leaf corner (the conforming point set)
    by_u: dict[int, set[int]] = {}
    by_v: dict[int, set[int]] = {}
    spans: dict[int, int] = {}
    for (i, j, level) in leaves:
        span = int(key_level) - int(level)
        spans[int(level)] = span
        step = 1 << span
        c00 = (int(i) << span, int(j) << span)
        corners = ((c00[0], c00[1]), (c00[0] + step, c00[1]),
                   (c00[0] + step, c00[1] + step), (c00[0], c00[1] + step))
        for (ku, kv) in corners:
            by_u.setdefault(ku, set()).add(kv)
            by_v.setdefault(kv, set()).add(ku)
    level_diff = Counter()
    edge_total = 0
    missing = 0            # edge_split says "whole" but a leaf corner sits inside it
    spurious = 0           # edge_split says "split" but no leaf corner sits inside it
    interior_points = Counter()
    severity = Counter()
    interior_edges = 0
    for (i, j, level) in leaves:
        span = int(key_level) - int(level)
        step = 1 << span
        gi, gj = int(i) << span, int(j) << span
        corners = ((gi, gj), (gi + step, gj), (gi + step, gj + step), (gi, gj + step))
        plan = (("v", True, 0, 3), ("u", True, 0, 1), ("v", False, 1, 2), ("u", False, 3, 2))
        splits = tree.edge_splits(int(i), int(j), int(level))
        for index, (orient, lo, a, b) in enumerate(plan):
            pa, pb = corners[a], corners[b]
            if orient == "v":
                table, lo_k, hi_k = by_u.get(pa[0], set()), min(pa[1], pb[1]), max(pa[1], pb[1])
            else:
                table, lo_k, hi_k = by_v.get(pa[1], set()), min(pa[0], pb[0]), max(pa[0], pb[0])
            inside = [k for k in table if lo_k < k < hi_k]
            neighbours = neighbour_edges(tree, (i, j, level), key_level, orient, lo)
            edge_total += 1
            if neighbours:
                interior_edges += 1
                for (_, _, nl) in neighbours:
                    level_diff[int(nl) - int(level)] += 1
            interior_points[len(inside)] += 1
            severity[len(inside)] += 1
            if inside and not splits[index]:
                missing += 1
            if splits[index] and not inside:
                spurious += 1
    return {
        "leaves": len(leaves),
        "leaf_levels": {str(k): int(v) for k, v in sorted(levels.items())},
        "edges": int(edge_total),
        "interior_edges": int(interior_edges),
        "neighbour_level_minus_mine": {str(k): int(v) for k, v in sorted(level_diff.items())},
        "interior_corner_points_per_edge": {str(k): int(v) for k, v in sorted(interior_points.items())},
        "edges_with_predicate_missing_a_corner": int(missing),
        "edges_with_predicate_inventing_a_split": int(spurious),
        "worst_interior_points_on_one_edge": int(max(severity) if severity else 0),
    }


def edge_use(mesh: Any) -> dict[str, int]:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    a = faces[:, [0, 1, 2]].ravel()
    b = faces[:, [1, 2, 0]].ravel()
    keys = np.stack([np.minimum(a, b), np.maximum(a, b)], axis=1)
    unique, counts = np.unique(keys, axis=0, return_counts=True)
    return {str(k): int(v) for k, v in sorted(Counter(counts.tolist()).items())}


def build_captured(mother: Any, spec: FractureSpec, rng: Any, label: str) -> dict[str, Any]:
    """Run the production build, capturing the final tree and the assembled faces."""
    state: dict[str, Any] = {}
    captured: list[tuple[np.ndarray, np.ndarray]] = []
    original_leaves = cut_mod._Quadtree.leaves

    def leaves(self):                                   # type: ignore[no-untyped-def]
        out = original_leaves(self)
        state["tree"] = self
        state["leaves"] = out
        return out

    real_trimesh = cut_mod.trimesh

    class _Recorder(real_trimesh.Trimesh):              # type: ignore[misc,valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            captured.append((np.asarray(self.vertices, dtype=np.float64),
                             np.asarray(self.faces, dtype=np.int64)))

    started = time.perf_counter()
    cut_mod._Quadtree.leaves = leaves                     # type: ignore[method-assign]
    cut_mod.trimesh = types.SimpleNamespace(Trimesh=_Recorder)
    try:
        try:
            cutter = make_closed_cutter(mother, spec, rng)
            status, error, measurements, mesh = "OK", None, {}, cutter.mesh
            report = dict(cutter.meta or {})
            realized = float(cutter.realized_error_mm)
        except SynLabError as exc:
            status, error = "REFUSED", str(exc.code)
            measurements = {str(k): _json(v) for k, v in (exc.measurements or {}).items()}
            report, realized = {}, float("nan")
            mesh = None
            if captured:
                verts, faces = captured[-1]
                mesh = real_trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    finally:
        cut_mod._Quadtree.leaves = original_leaves        # type: ignore[method-assign]
        cut_mod.trimesh = real_trimesh
    elapsed = time.perf_counter() - started

    out: dict[str, Any] = {
        "label": label, "backend": str(spec.backend),
        "target_rms_mm": float(spec.target_rms_mm),
        "error_budget_mm": float(spec.error_budget_mm),
        "max_cells": int(spec.max_cutter_cells),
        "seconds": float(elapsed), "status": status, "error_code": error,
        "measurements": measurements,
        "realized_error_mm": realized,
        "cells": report.get("cells"), "leaf_level": report.get("leaf_level"),
        "triangles": report.get("triangles"),
        "top_triangles": report.get("top_triangles"),
        "side_triangles": report.get("side_triangles"),
        "bottom_triangles": report.get("bottom_triangles"),
        "reported_histogram": report.get("edge_use_histogram"),
    }
    tree, final_leaves = state.get("tree"), state.get("leaves")
    if tree is not None and final_leaves is not None:
        out["tjunction"] = analyse(tree, final_leaves)
    if mesh is not None:
        out["edge_use_histogram"] = edge_use(mesh)
        out["bad_edges"] = int(sum(v for k, v in out["edge_use_histogram"].items() if k != "2"))
        out["watertight"] = bool(mesh.is_watertight)
        out["winding_consistent"] = bool(mesh.is_winding_consistent)
        out["volume_mm3"] = float(mesh.volume)
        out["faces"] = int(np.asarray(mesh.faces).shape[0])
        out["vertices"] = int(np.asarray(mesh.vertices).shape[0])
    return out


def _json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="tjunction")
    parser.add_argument("--cases", default="bowl")
    parser.add_argument("--rms", type=float, default=0.05)
    parser.add_argument("--budget", type=float, default=0.01)
    parser.add_argument("--max-cells", type=int, default=400000)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from synlab.seeds import make_rng

    import fixtures as fx

    mothers = {"bowl": fx.thin_bowl_mother(), "box20": fx.box_mother((20.0, 20.0, 20.0))}
    rows = []
    for name in [c.strip() for c in args.cases.split(",") if c.strip()]:
        if name == "plane-bowl":
            mother, backend, rms = mothers["bowl"], BACKEND_PLANE, 0.0
        elif name == "zero-rough":
            mother, backend, rms = mothers["box20"], BACKEND_ROUGH, 0.0
        elif name in mothers:
            mother, backend, rms = mothers[name], BACKEND_ROUGH, args.rms
        else:
            continue
        spec = FractureSpec(backend=backend, target_rms_mm=rms,
                            error_budget_mm=args.budget, max_cutter_cells=args.max_cells)
        rng = make_rng(20261001, "cutfix_probe", name)
        label = f"{name}_rms{rms}_b{args.budget}_c{args.max_cells}"
        print(f"[run] {label}", flush=True)
        row = build_captured(mother, spec, rng, label)
        rows.append(row)
        print(f"  -> {json.dumps(row, ensure_ascii=False)[:1200]}", flush=True)
    out = Path(args.out) if args.out else (
        REPO_ROOT / "data" / "a12_reports" / "cutfix" / f"tjunction_{args.label}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"label": args.label, "rows": rows}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"[written] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
