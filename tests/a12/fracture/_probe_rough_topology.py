"""Diagnose why the refined (rough) cutter solid fails the watertight gate.

Read-only probe: rebuild the top surface the way ``build_closed_cutter`` does, then classify every
edge that is not used exactly twice (T-junction / hanging node / duplicate directed edge / winding).

    python tests\\a12\\fracture\\_probe_rough_topology.py --fixture box --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import fixtures as fx  # noqa: E402
from synlab.errors import SynLabError  # noqa: E402
from synlab.fracture import cut as cut_mod  # noqa: E402
from synlab.fracture.api import _default_basis  # noqa: E402
from synlab.fracture.spec import BACKEND_ROUGH, FractureSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402


def build(fixture: str, rms: float, budget: float):
    mother = fx.box_mother((20.0, 20.0, 20.0)) if fixture == "box" else fx.thin_bowl_mother()
    rng = make_rng(20261001, "fracture_test", BACKEND_ROUGH)
    spec = FractureSpec(backend=BACKEND_ROUGH, target_rms_mm=rms)
    basis = _default_basis(mother, rng, spec)
    height = cut_mod.make_height_field(basis, rng, target_rms_mm=rms)
    height = cut_mod.attach_material_band(height, mother.mesh)
    info = {"fixture": fixture, "rms": rms,
            "wavelength_min_mm": float(height.wavelength_min_mm),
            "admitted": height.meta.get("admitted_wavelength_window_mm"),
            "band": height.window.as_dict() if height.window is not None else None}
    try:
        mesh, report = cut_mod.build_closed_cutter(basis, height, error_budget_mm=budget)
    except SynLabError as exc:
        info["error"] = {"code": str(exc.code), "message": str(exc.message),
                         "measurements": {k: v for k, v in (exc.measurements or {}).items()
                                          if not isinstance(v, (list, dict))}}
        return None, info, basis, height
    return (mesh, report), info, basis, height


def top_surface(basis, height, budget: float):
    """Replicate the top-surface assembly without the watertight assertion."""
    u0, u1 = float(basis.u_range[0]), float(basis.u_range[1])
    v0, v1 = float(basis.v_range[0]), float(basis.v_range[1])
    mu0, mu1 = (float(x) for x in basis.meta.get("material_u_range", (u0, u1)))
    mv0, mv1 = (float(x) for x in basis.meta.get("material_v_range", (v0, v1)))
    pad = min(mu0 - u0, u1 - mu1, mv0 - v0, v1 - mv1)
    root_level = int(np.clip(np.ceil(np.log2(max((u1 - u0), (v1 - v0)) / max(0.25 * pad, 1e-6))),
                             2, 8))
    tree = cut_mod._Quadtree(u0, u1, v0, v1, root_level)
    max_over = budget * (1.0 + 1e-9)
    key_level = 23
    probes = cut_mod._ProbeSet(float(height.wavelength_min_mm), max_over)

    def leaf_span_for(level: int) -> int:
        return tree.key_span(level, key_level)

    def cell_errors(cells, level):
        block = np.asarray(cells, dtype=np.int64).reshape(-1, 3)
        if block.shape[0] == 0:
            return np.zeros(0)
        span = leaf_span_for(level)
        hx, hy = tree.cell_size(level)
        bary = probes.for_cell(float(np.hypot(hx, hy)))
        counts = np.zeros(block.shape[0], dtype=np.int64)
        uv_all, w_all = [], []
        for row in range(block.shape[0]):
            pts_ij, tris = tree.cell_triangles(int(block[row, 0]), int(block[row, 1]),
                                               level, span)
            u, v = cut_mod._cell_uv(tree, level, span, pts_ij)
            pts = np.stack([u, v, height(u, v)], axis=1)
            tri_pts = pts[tris]
            samp = np.einsum("bk,tkc->tbc", bary, tri_pts)
            flat = samp.reshape(-1, 3)
            uv_all.append(flat[:, 0:2])
            w_all.append(flat[:, 2])
            counts[row] = flat.shape[0]
        uu = np.concatenate([a[:, 0] for a in uv_all])
        vv = np.concatenate([a[:, 1] for a in uv_all])
        ww = np.concatenate(w_all)
        dev = np.abs(height(uu, vv) - ww)
        starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
        return np.maximum.reduceat(dev, starts)

    iterations = 0
    while True:
        iterations += 1
        changed = False
        groups: dict[int, list] = {}
        for cell in tree.leaves():
            groups.setdefault(cell[2], []).append(cell)
        for level in sorted(groups):
            block = np.asarray(groups[level], dtype=np.int64).reshape(-1, 3)
            errors = cell_errors(block, level)
            over = errors > max_over
            marked = over.copy()
            for row in range(block.shape[0]):
                if not marked[row] and tree.needs_balance(int(block[row, 0]),
                                                          int(block[row, 1]), level):
                    marked[row] = True
            if bool(np.any(marked)):
                tree.refine_bulk(block[marked])
                changed = True
        if not changed or iterations > 60:
            break

    leaves = tree.leaves()
    top_index: dict[tuple[int, int], int] = {}
    vertices: list[tuple[float, float, float]] = []

    def top_vertex(level, gi, gj):
        shift = leaf_span_for(level)
        key = (int(gi), int(gj))
        found = top_index.get(key)
        if found is None:
            u, v = cut_mod._cell_uv(tree, level, shift,
                                    np.array([[int(gi), int(gj)]], dtype=np.int64))
            found = len(vertices)
            vertices.append((float(u[0]), float(v[0]), float(height(u, v)[0])))
            top_index[key] = found
        return found

    top_faces = []
    top_edge_use: Counter = Counter()
    for i, j, level in leaves:
        pts_ij, tris = tree.cell_triangles(i, j, level, leaf_span_for(level))
        local = [top_vertex(level, int(p[0]), int(p[1])) for p in pts_ij]
        for tri in tris:
            face = (int(local[tri[0]]), int(local[tri[1]]), int(local[tri[2]]))
            if len(set(face)) < 3:
                continue
            top_faces.append(face)
            for k in range(3):
                top_edge_use[(face[k], face[(k + 1) % 3])] += 1
    return tree, leaves, top_faces, top_edge_use, vertices, top_index


def classify(tree, leaves, top_faces, top_edge_use, vertices):
    verts = np.asarray(vertices, dtype=np.float64)
    level_of = {int(v): lv for (_, _, lv) in leaves for v in ()}  # placeholder
    undirected: Counter = Counter()
    for (a, b), uses in top_edge_use.items():
        undirected[(min(a, b), max(a, b))] += uses
    bad = {e: n for e, n in undirected.items() if n != 2}
    dup_directed = {e: n for e, n in top_edge_use.items() if n > 1}
    # classify boundary edges by geometry: is a *third* vertex exactly on the segment?
    mid_hits = 0
    for (a, b) in bad:
        pa, pb = verts[a], verts[b]
        others = np.delete(verts, [a, b], axis=0)
        d = pb - pa
        length = float(np.linalg.norm(d))
        if length <= 0:
            continue
        t = (others - pa) @ d / (length * length)
        on = (t > 1e-9) & (t < 1 - 1e-9)
        if not bool(on.any()):
            continue
        proj = pa + t[on][:, None] * d[None, :]
        dist = np.linalg.norm(others[on] - proj, axis=1)
        if float(dist.min()) <= 1e-9:
            mid_hits += 1
    n_boundary = len([e for e, n in undirected.items() if n == 1])
    # vertex duplicates by position (T-junction signature)
    uniq = len(np.unique(np.round(verts, 9), axis=0))
    # cell sizes
    sizes = Counter(lv for (_, _, lv) in leaves)
    return {
        "cells": len(leaves),
        "cell_levels": {str(k): int(v) for k, v in sorted(sizes.items())},
        "top_faces": len(top_faces),
        "top_vertices": int(verts.shape[0]),
        "unique_vertices_by_position": int(uniq),
        "directed_edges_used_twice": len(dup_directed),
        "undirected_edges_total": len(undirected),
        "undirected_edges_not_2": len(bad),
        "undirected_edges_used_once": n_boundary,
        "undirected_edges_used_more": len([e for e, n in undirected.items() if n > 2]),
        "bad_edges_with_a_vertex_inside": mid_hits,
        "edge_use_histogram": {str(k): int(v) for k, v in sorted(Counter(undirected.values()).items())},
    }


def cell_uv(tree, i, j, level):
    hx, hy = tree.cell_size(level)
    return (tree.u0 + i * hx, tree.u0 + (i + 1) * hx,
            tree.v0 + j * hy, tree.v0 + (j + 1) * hy)


def neighbour_pairs(tree, leaves):
    """Every (cell, neighbour, orientation) pair with the split flag each side computes."""
    index = {}
    for (i, j, level) in leaves:
        index[(i, j, level)] = (i, j, level)
    rows = []
    for (i, j, level) in leaves:
        for orient, lo in (("v", True), ("u", True), ("v", False), ("u", False)):
            nb = tree._across(i, j, level, orient, lo)
            if nb is None:
                continue
            li, lj, reached, refined = tree._leaf_on_path(nb[0], nb[1], level)
            rows.append({
                "cell": [i, j, level],
                "neighbour_index": [nb[0], nb[1]],
                "neighbour_leaf": [li, lj, reached],
                "neighbour_refined": bool(refined),
                "orient": orient,
                "lo": bool(lo),
                "my_edge_split": bool(tree.edge_split(i, j, level, orient, lo)),
            })
    return rows


def diagnose_mismatch(tree, leaves):
    """Count neighbour pairs whose split decision disagrees with the finer side's expectation."""
    out = Counter()
    examples = {}
    for (i, j, level) in leaves:
        hx, hy = tree.cell_size(level)
        for orient, lo in (("v", True), ("u", True), ("v", False), ("u", False)):
            nb = tree._across(i, j, level, orient, lo)
            if nb is None:
                continue
            si, sj = int(nb[0]), int(nb[1])
            mine = bool(tree.edge_split(i, j, level, orient, lo))
            nb_refined = bool(tree.is_refined(si, sj, level))
            key = f"mine={int(mine)}|nb_refined={int(nb_refined)}"
            out[key] += 1
            if mine != nb_refined:
                examples.setdefault(key, {"cell": [i, j, level], "nb": [si, sj],
                                          "orient": orient, "lo": bool(lo),
                                          "cell_size_mm": [hx, hy]})
    return {"counts": dict(out), "mismatch_examples": examples}


def edge_segment_census(tree, leaves, key_level: int = 23):
    """Every leaf edge, split into the segments it actually owns, on one global key lattice.

    A conforming triangulation owns each *segment* exactly twice (once from each side).  Segments
    owned once or three times are the exact combinatorial signature of a hanging node.
    """
    sparse = key_level - min(level for (_, _, level) in leaves)
    seg_use: Counter = Counter()
    owner_level: dict[tuple, set] = {}
    for (i, j, level) in leaves:
        span = key_level - level
        base_i, base_j = i << span, j << span
        end = 1 << span
        half = end >> 1
        flags = tree.edge_splits(i, j, level)
        edges = [
            ("v_lo", (base_i, base_j), (base_i, base_j + end)),
            ("u_lo", (base_i, base_j), (base_i + end, base_j)),
            ("v_hi", (base_i + end, base_j), (base_i + end, base_j + end)),
            ("u_hi", (base_i, base_j + end), (base_i + end, base_j + end)),
        ]
        for k, (name, start, stop) in enumerate(edges):
            if flags[k]:
                mid = ((start[0] + stop[0]) // 2, (start[1] + stop[1]) // 2)
                points = [start, mid, stop]
            else:
                points = [start, stop]
            for a, b in zip(points[:-1], points[1:]):
                key = (min(a, b), max(a, b))
                seg_use[key] += 1
                owner_level.setdefault(key, set()).add((name, level))
    hist = Counter(seg_use.values())
    over = {k: v for k, v in seg_use.items() if v > 2}
    under = {k: v for k, v in seg_use.items() if v < 2}
    return {
        "segments": len(seg_use),
        "use": seg_use,
        "owners": owner_level,
        "use_histogram": {str(k): int(v) for k, v in sorted(hist.items())},
        "sparse_level": int(sparse),
        "over_examples": [{"seg": [list(k[0]), list(k[1])], "use": int(v),
                           "owners": sorted(owner_level[k])}
                          for k, v in list(sorted(over.items()))[:6]],
        "under_examples": [{"seg": [list(k[0]), list(k[1])], "use": int(v),
                            "owners": sorted(owner_level[k])}
                           for k, v in list(sorted(under.items()))[:6]],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", default="box")
    ap.add_argument("--rms", type=float, default=0.05)
    ap.add_argument("--budget", type=float, default=0.01)
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    built, info, basis, height = build(args.fixture, args.rms, args.budget)
    tree, leaves, top_faces, top_edge_use, vertices, top_index = top_surface(basis, height,
                                                                             args.budget)
    info["topology"] = classify(tree, leaves, top_faces, top_edge_use, vertices)
    # per-level-pair split agreement
    import collections
    agree = collections.Counter()
    examples = {}
    for row in neighbour_pairs(tree, leaves):
        li, lj, reached = row["neighbour_leaf"]
        key = (row["cell"][2], reached, row["orient"], row["my_edge_split"])
        agree[key] += 1
        examples.setdefault(str(key), row)
    info["neighbour_split_table"] = {"|".join(str(x) for x in k): int(v)
                                     for k, v in sorted(agree.items())}
    info["neighbour_examples"] = examples
    info["build_error"] = None if built else info.get("error")
    info["tree"] = {
        "root_level": int(tree.root_level),
        "side": int(tree.side),
        "grid_level": int(tree.grid_level),
        "refined_entries": len(tree.refined),
        "cell_size_level0_mm": [float(tree.hx), float(tree.hy)],
        "source_sha256": __import__("hashlib").sha256(
            Path(cut_mod.__file__).read_bytes()).hexdigest()[:16],
    }
    sample = [(63, 63, 0), (113, 61, 1), (449, 237, 3)]
    info["tree"]["probe_calls"] = [
        {"cell": list(c),
         "is_refined": bool(tree.is_refined(*c)),
         "splits": [bool(x) for x in tree.edge_splits(*c)],
         "needs_balance": bool(tree.needs_balance(*c))}
        for c in sample
    ]
    info["tree"]["refined_sample"] = sorted(list(tree.refined))[:12]
    info["tree"]["leaf_sample"] = sorted(leaves)[:12]
    info["split_mismatch"] = diagnose_mismatch(tree, leaves)
    census = edge_segment_census(tree, leaves)
    mesh_use = {}
    for (a, b), uses in top_edge_use.items():
        key = (min(a, b), max(a, b))
        mesh_use[key] = mesh_use.get(key, 0) + uses
    diff = []
    for key in sorted(set(census["use"]) | set(mesh_use)):
        c = census["use"].get(key, 0)
        m = mesh_use.get(key, 0)
        if c != m:
            diff.append((key, int(c), int(m), sorted(census["owners"].get(key, []))))
    info["edge_segment_census"] = {k: v for k, v in census.items()
                                   if k not in ("use", "owners")}
    info["edge_segment_census"]["mismatch_vs_mesh"] = len(diff)
    info["edge_segment_census"]["mismatch_examples"] = [
        {"seg": [list(k[0]), list(k[1])], "ownership": c, "mesh_use": m, "owners": o}
        for (k, c, m, o) in diff[:12]
    ]
    text = json.dumps(info, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
