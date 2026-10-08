"""Scratch probe 24: find the assembled top triangle with the largest local refinement error."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.fracture import cut as C  # noqa: E402


def build_and_report(budget: float = 0.01, wl_min: float = 0.9):
    pts = np.asarray([[-6, -6, -6], [6, -6, -6], [6, 6, -6], [-6, 6, -6],
                      [-6, -6, 6], [6, -6, 6], [6, 6, 6], [-6, 6, 6]], dtype=np.float64)
    basis = C.build_basis(pts, np.array([1.0, 0.0, 0.0]), anchor=np.zeros(3), basis_id="fx",
                          pad_ratio=0.15, pad_min_mm=2.4)
    height = C.make_height_field(basis, np.random.default_rng(11), target_rms_mm=0.05,
                                 n_bands=3, wavelength_min_mm=wl_min)
    u0, u1 = basis.u_range
    v0, v1 = basis.v_range
    pad = min(basis.meta["material_u_range"][0] - u0, u1 - basis.meta["material_u_range"][1],
              basis.meta["material_v_range"][0] - v0, v1 - basis.meta["material_v_range"][1])
    root = int(np.clip(np.ceil(np.log2(max((u1 - u0), (v1 - v0)) / max(0.25 * pad, 1e-6))), 2, 8))
    tree = C._Quadtree(u0, u1, v0, v1, root)
    by_wl = height.wavelength_min_mm / C.POINTS_PER_WAVELENGTH
    by_k = float(np.sqrt(8.0 * budget / height.curvature_bound()))
    needed = min(by_wl, by_k)
    root_cell = max((u1 - u0), (v1 - v0)) / (1 << root)
    start = root + int(np.ceil(max(np.log2(max(root_cell / needed, 1.0)), 0.0)))
    tree.refine_all_to(start)
    key_level = start + 12
    print("start", start, "key", key_level, "cell at key", (u1 - u0) / (1 << key_level), flush=True)

    top_index: dict[tuple[int, int], int] = {}
    vertices: list[tuple[float, float, float]] = []
    collisions = 0

    def top_vertex(level, gi, gj):
        nonlocal collisions
        shift = tree.key_span(level, key_level)
        key = (int(gi) << shift, int(gj) << shift)
        found = top_index.get(key)
        if found is None:
            u, v = C._cell_uv(tree, level, shift, np.array([[gi, gj]], dtype=np.int64))
            found = len(vertices)
            vertices.append((float(u[0]), float(v[0]), float(height(u, v)[0])))
            top_index[key] = found
        else:
            expected_u = u0 + key[0] * ((u1 - u0) / (1 << key_level))
            if abs(vertices[found][0] - expected_u) > 1e-9:
                collisions += 1
        return found

    faces = []
    for i, j, level in tree.leaves():
        pij, tris = tree.cell_triangles(i, j, level, tree.key_span(level, key_level))
        local = [top_vertex(level, int(p[0]), int(p[1])) for p in pij]
        for tri in tris:
            faces.append((local[tri[0]], local[tri[1]], local[tri[2]]))
    print("top faces", len(faces), "vertices", len(vertices),
          "collisions", collisions, flush=True)
    verts = np.asarray(vertices, dtype=np.float64)
    idx = np.asarray(faces, dtype=np.int64)
    pts3 = verts[idx]
    samp = np.einsum("bk,tkc->tbc", C._ERROR_BARY, pts3)
    dev = np.abs(height(samp[:, :, 0], samp[:, :, 1]) - samp[:, :, 2])
    worst = int(np.argmax(dev.max(axis=1)))
    print("worst tri dev", float(dev[worst].max()), "at uv",
          np.round(samp[worst][int(np.argmax(dev[worst]))][:2], 6), flush=True)
    print("  corners uv", np.round(pts3[worst][:, :2], 6).tolist(), flush=True)
    print("  corners w", np.round(pts3[worst][:, 2], 8).tolist(), flush=True)
    edge = np.linalg.norm(pts3[worst][1] - pts3[worst][0])
    print("  edge lengths", np.round([np.linalg.norm(pts3[worst][k] - pts3[worst][(k + 1) % 3])
                                      for k in range(3)], 8).tolist(), flush=True)
    print("  distinct uv", len({tuple(np.round(p, 9)) for p in pts3[worst][:, :2]}), flush=True)
    hist = Counter()
    for f in faces:
        a, b, c = (verts[f[0]], verts[f[1]], verts[f[2]])
        hist[round(float(np.linalg.norm(b - a)), 6)] += 1
    print("  edge-length histogram (top 6)",
          sorted(hist.items(), key=lambda kv: -kv[1])[:6], flush=True)


build_and_report()
