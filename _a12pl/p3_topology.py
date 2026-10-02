"""Debug: build the morphology cutter's top lattice and classify every non-manifold edge.

Replicates ``cut.build_closed_cutter``'s fixed point and assembly so the edge-use table can be
inspected *before* the watertightness guard fires.  Read-only: it imports the frozen helpers and
never modifies the library.
"""

from __future__ import annotations

import json
import sys
import traceback
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests" / "a12" / "fracture"))

import numpy as np  # noqa: E402


def box_mother(extents=(14.0, 14.0, 14.0)):
    try:
        import fixtures as fx

        return fx.box_mother(extents)
    except Exception:  # noqa: BLE001
        import trimesh

        from synlab.schemas.runtime import Chart, MotherGeometry

        mesh = trimesh.creation.box(extents=list(extents))
        chart = Chart(name="default", surface_tags=("outer_wall",), kind="triplanar",
                      u_periodic=False, x_period_mm=None, area_mm2=float(mesh.area),
                      to_uv=lambda points: np.asarray(points, dtype=np.float64)[:, :2])
        return MotherGeometry(
            mesh=mesh, face_surface_tag=np.zeros(len(mesh.faces), dtype=np.int32),
            surface_tag_names={0: "outer_wall"}, charts=[chart], vessel_id="V_BOX",
            material_id="M_FIX", params={"extents": list(extents)}, mother_id="box14",
            meta={"fixture": True})


def main() -> int:
    from synlab.fracture import cut as cut_mod
    from synlab.fracture.api import _default_basis
    from synlab.fracture.morphology import build_morphology_field, prepare_morphology
    from synlab.fracture.spec import FractureSpec
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.seeds import make_rng

    mother = box_mother((14.0, 14.0, 14.0))
    profile = build_material_profile("M01", default_material_params("M01"),
                                     make_rng(20261001, "morphology_test", "materials", "M01"))
    rng = make_rng(20261001, "morphology_test", "fracture", "FIX14", "M01")
    basis = _default_basis(mother, rng, FractureSpec())
    prepared = prepare_morphology(mother, material_profile=profile, rng=rng, basis=basis,
                                  event_id="dbg", error_budget_mm=0.01, max_cells=400_000)
    params = cut_mod and prepared["base_params"]
    field = build_morphology_field(basis, mother.mesh, params, rng=rng,
                                   cross_section=(prepared["tris_uv"], prepared["core_area_mm2"],
                                                  prepared["cross_info"]))
    height = field
    budget = 0.01
    max_cells = 400_000
    max_over = budget * (1.0 + 1e-9)

    u0, u1 = float(basis.u_range[0]), float(basis.u_range[1])
    v0, v1 = float(basis.v_range[0]), float(basis.v_range[1])
    mu0, mu1 = (float(x) for x in basis.meta.get("material_u_range", (u0, u1)))
    mv0, mv1 = (float(x) for x in basis.meta.get("material_v_range", (v0, v1)))
    pad = min(mu0 - u0, u1 - mu1, mv0 - v0, v1 - mv1)
    root_level = int(np.clip(np.ceil(np.log2(max((u1 - u0), (v1 - v0)) / max(0.25 * pad, 1e-6))),
                             2, 8))
    tree = cut_mod._Quadtree(u0, u1, v0, v1, root_level)
    max_level = 22
    key_level = max_level + 1
    probes = cut_mod._ProbeSet(None if height.is_flat else float(height.wavelength_min_mm),
                               max_over)

    def leaf_span_for(level: int) -> int:
        return tree.key_span(level, key_level)

    def cell_errors(block_in: np.ndarray, level: int) -> np.ndarray:
        block = np.asarray(block_in, dtype=np.int64).reshape(-1, 3)
        if block.shape[0] == 0:
            return np.zeros(0, dtype=np.float64)
        span = leaf_span_for(level)
        hx, hy = tree.cell_size(level)
        bary = probes.for_cell(float(np.hypot(hx, hy)))
        counts = np.zeros(block.shape[0], dtype=np.int64)
        pu, pw = [], []
        for row in range(block.shape[0]):
            pts_ij, tris = tree.cell_triangles(int(block[row, 0]), int(block[row, 1]),
                                               level, span)
            u, v = cut_mod._cell_uv(tree, level, span, pts_ij)
            pts = np.stack([u, v, height(u, v)], axis=1)
            tri_pts = pts[tris]
            samp = np.einsum("bk,tkc->tbc", bary, tri_pts)
            flat = samp.reshape(-1, 3)
            pu.append(flat[:, 0:2])
            pw.append(flat[:, 2])
            counts[row] = flat.shape[0]
        uu = np.concatenate([x[:, 0] for x in pu])
        vv = np.concatenate([x[:, 1] for x in pu])
        ww = np.concatenate(pw)
        deviation = np.abs(height(uu, vv) - ww)
        starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
        return np.maximum.reduceat(deviation, starts)

    iterations = 0
    while True:
        iterations += 1
        changed = False
        groups: dict[int, list[tuple[int, int, int]]] = {}
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
        if not changed:
            break

    leaves = tree.leaves()
    levels = Counter(level for (_, _, level) in leaves)

    # ------- assembly (replica of cut.build_closed_cutter)
    top_index: dict[tuple[int, int], int] = {}
    vertices: list[tuple[float, float, float]] = []
    key_level_of: dict[int, int] = {}

    def top_vertex(level: int, gi: int, gj: int) -> int:
        shift = leaf_span_for(level)
        key = (int(gi), int(gj))
        found = top_index.get(key)
        if found is None:
            u, v = cut_mod._cell_uv(tree, level, shift,
                                    np.array([[int(gi), int(gj)]], dtype=np.int64))
            found = len(vertices)
            vertices.append((float(u[0]), float(v[0]), float(height(u, v)[0])))
            top_index[key] = found
            key_level_of[found] = key_level - (key_level - level)
        return found

    top_faces: list[tuple[int, int, int]] = []
    face_level: list[int] = []
    top_edge_use: Counter[tuple[int, int]] = Counter()
    top_edge_faces: dict[tuple[int, int], list[int]] = {}
    for i, j, level in leaves:
        pts_ij, tris = tree.cell_triangles(i, j, level, leaf_span_for(level))
        local = [top_vertex(level, int(p[0]), int(p[1])) for p in pts_ij]
        for tri in tris:
            face = (int(local[tri[0]]), int(local[tri[1]]), int(local[tri[2]]))
            if len(set(face)) < 3:
                continue
            fid = len(top_faces)
            top_faces.append(face)
            face_level.append(level)
            for k in range(3):
                edge = (face[k], face[(k + 1) % 3])
                top_edge_use[edge] += 1
                top_edge_faces.setdefault(edge, []).append(fid)

    verts = np.asarray(vertices, dtype=np.float64)
    # edge classes
    interior = 0
    boundary = 0
    bad: dict[str, int] = Counter()
    per_level_pair: Counter = Counter()
    samples: list[dict] = []
    for edge, uses in top_edge_use.items():
        reverse = top_edge_use.get((edge[1], edge[0]), 0)
        if uses == 1 and reverse == 0:
            boundary += 1
            continue
        if uses == 1 and reverse == 1:
            interior += 1
            continue
        key = f"uses_{uses}_rev_{reverse}"
        bad[key] += 1
        fwd = top_edge_faces.get(edge, [])
        rev = top_edge_faces.get((edge[1], edge[0]), [])
        lv = tuple(sorted({int(face_level[f]) for f in fwd + rev}))
        per_level_pair[str(lv)] += 1
        if len(samples) < 12:
            a, b = int(edge[0]), int(edge[1])
            samples.append({
                "uses": int(uses), "rev": int(reverse),
                "a_mm": np.round(verts[a], 6).tolist(), "b_mm": np.round(verts[b], 6).tolist(),
                "length_mm": float(np.linalg.norm(verts[a] - verts[b])),
                "levels": list(lv),
                "faces": [int(face_level[f]) for f in fwd][:4],
                "rev_faces": [int(face_level[f]) for f in rev][:4],
            })
    out = {
        "iterations": iterations, "leaves": len(leaves),
        "leaf_levels": {str(k): int(v) for k, v in sorted(levels.items())},
        "vertices": len(vertices), "top_faces": len(top_faces),
        "directed_edges": len(top_edge_use),
        "interior_edges": interior, "boundary_edges": boundary,
        "bad_edge_classes": dict(bad), "bad_edge_total": int(sum(bad.values())),
        "bad_by_level_pair": dict(per_level_pair),
        "samples": samples,
    }
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
