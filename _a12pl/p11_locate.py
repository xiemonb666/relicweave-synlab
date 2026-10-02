"""Debug 11: locate the offending segments in the real leaf set and name the owning cells."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests" / "a12" / "fracture"))

import numpy as np  # noqa: E402

KEY_LEVEL = 23


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


def build_tree_and_field():
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
    params = prepared["base_params"]
    height = build_morphology_field(basis, mother.mesh, params, rng=rng,
                                    cross_section=(prepared["tris_uv"], prepared["core_area_mm2"],
                                                   prepared["cross_info"]))
    budget, max_over = 0.01, 0.01 * (1.0 + 1e-9)
    u0, u1 = float(basis.u_range[0]), float(basis.u_range[1])
    v0, v1 = float(basis.v_range[0]), float(basis.v_range[1])
    mu0, mu1 = (float(x) for x in basis.meta.get("material_u_range", (u0, u1)))
    mv0, mv1 = (float(x) for x in basis.meta.get("material_v_range", (v0, v1)))
    pad = min(mu0 - u0, u1 - mu1, mv0 - v0, v1 - mv1)
    root_level = int(np.clip(np.ceil(np.log2(max((u1 - u0), (v1 - v0))
                                              / max(0.25 * pad, 1e-6))), 2, 8))
    tree = cut_mod._Quadtree(u0, u1, v0, v1, root_level)
    probes = cut_mod._ProbeSet(None if height.is_flat else float(height.wavelength_min_mm),
                               max_over)

    def cell_errors(block_in, level):
        block = np.asarray(block_in, dtype=np.int64).reshape(-1, 3)
        if block.shape[0] == 0:
            return np.zeros(0)
        span = tree.key_span(level, KEY_LEVEL)
        hx, hy = tree.cell_size(level)
        bary = probes.for_cell(float(np.hypot(hx, hy)))
        counts = np.zeros(block.shape[0], dtype=np.int64)
        pu, pw = [], []
        for row in range(block.shape[0]):
            pts_ij, tris = tree.cell_triangles(int(block[row, 0]), int(block[row, 1]), level, span)
            u, v = cut_mod._cell_uv(tree, level, span, pts_ij)
            pts = np.stack([u, v, height(u, v)], axis=1)
            samp = np.einsum("bk,tkc->tbc", bary, pts[tris])
            flat = samp.reshape(-1, 3)
            pu.append(flat[:, 0:2])
            pw.append(flat[:, 2])
            counts[row] = flat.shape[0]
        uu = np.concatenate([x[:, 0] for x in pu])
        vv = np.concatenate([x[:, 1] for x in pu])
        ww = np.concatenate(pw)
        dev = np.abs(height(uu, vv) - ww)
        starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
        return np.maximum.reduceat(dev, starts)

    while True:
        changed = False
        groups: dict[int, list[tuple[int, int, int]]] = {}
        for cell in tree.leaves():
            groups.setdefault(cell[2], []).append(cell)
        for level in sorted(groups):
            block = np.asarray(groups[level], dtype=np.int64).reshape(-1, 3)
            errors = cell_errors(block, level)
            marked = errors > max_over
            for row in range(block.shape[0]):
                if not marked[row] and tree.needs_balance(int(block[row, 0]),
                                                          int(block[row, 1]), level):
                    marked[row] = True
            if bool(np.any(marked)):
                tree.refine_bulk(block[marked])
                changed = True
        if not changed:
            break
    return tree, cut_mod


def main() -> int:
    tree, cut_mod = build_tree_and_field()
    leaves = tree.leaves()
    seg_fwd: Counter = Counter()
    seg_rev: Counter = Counter()
    owners: dict = {}
    for i, j, level in leaves:
        span = tree.key_span(level, KEY_LEVEL)
        pts_ij, tris = tree.cell_triangles(i, j, level, span)
        u, v = cut_mod._cell_uv(tree, level, span, pts_ij)
        world = np.stack([np.round(u, 9), np.round(v, 9)], axis=1)
        for tri in tris:
            for k in range(3):
                a = (float(world[tri[k]][0]), float(world[tri[k]][1]))
                b = (float(world[tri[(k + 1) % 3]][0]), float(world[tri[(k + 1) % 3]][1]))
                if a == b:
                    continue
                if a < b:
                    seg_fwd[(a, b)] += 1
                else:
                    seg_rev[(b, a)] += 1
                owners.setdefault((a, b) if a < b else (b, a), set()).add((i, j, level))

    bad = []
    for key in set(seg_fwd) | set(seg_rev):
        fwd, rev = seg_fwd.get(key, 0), seg_rev.get(key, 0)
        if fwd == 1 and rev == 1:
            continue
        bad.append((key, fwd, rev))
    print(f"leaves={len(leaves)} segments={len(set(seg_fwd) | set(seg_rev))} bad={len(bad)}")
    # cross-check against edge_split for the owning cells
    detail = []
    for key, fwd, rev in bad[:400]:
        cells = sorted(owners.get(key, set()))
        rows = []
        for (i, j, level) in cells:
            cu = tree.cell_uv(i, j, level)
            rows.append({"cell": [i, j, level], "cell_uv": [round(x, 6) for x in cu],
                         "splits": tree.edge_splits(i, j, level)})
        detail.append({"seg": [list(key[0]), list(key[1])], "fwd": fwd, "rev": rev,
                       "length_mm": float(np.hypot(key[1][0] - key[0][0], key[1][1] - key[0][1])),
                       "owners": rows})
    print(json.dumps(detail[:6], indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
