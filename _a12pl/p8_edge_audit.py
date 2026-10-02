"""Debug 8: find the exact coarse/fine pair whose shared edge split state disagrees."""

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

    # ---------------------------------------------------------------- leaf-edge audit
    leaf_set = {(i, j, level) for (i, j, level) in tree.leaves()}
    mismatches: list[dict] = []
    counts = Counter()
    for (i, j, level) in sorted(leaf_set):
        for orient, lo in (("v", True), ("u", True), ("v", False), ("u", False)):
            sib = tree._across(i, j, level, orient, lo)
            if sib is None:
                counts["frame"] += 1
                continue
            si, sj = int(sib[0]), int(sib[1])
            sib_refined = tree.is_refined(si, sj, level)
            split = bool(tree.edge_split(i, j, level, orient, lo))
            # what is the finest leaf level adjacent to this edge?
            if not sib_refined:
                neighbour_is_leaf = (si, sj, level) in leaf_set
                if not neighbour_is_leaf:
                    counts["sibling_not_leaf_but_not_refined"] += 1
                if split:
                    counts["split_with_same_level_leaf_sibling"] += 1
                    mismatches.append({"cell": [i, j, level], "orient": orient, "lo": bool(lo),
                                       "sibling": [si, sj, level], "split": split,
                                       "sibling_refined": False})
            else:
                # the sibling is refined: all four children must be refined at level+1
                children = [(2 * si + di, 2 * sj + dj, level + 1)
                            for di in (0, 1) for dj in (0, 1)]
                missing = [c for c in children if c not in leaf_set
                           and not tree.is_refined(c[0], c[1], c[2])]
                if not split:
                    counts["no_split_with_refined_sibling"] += 1
                    mismatches.append({"cell": [i, j, level], "orient": orient, "lo": bool(lo),
                                       "sibling": [si, sj, level], "split": split,
                                       "sibling_refined": True, "missing_children": missing})
                if missing:
                    counts["refined_sibling_with_missing_children"] += 1
                # depth of the subtree under the sibling along this edge
                depths = Counter()
                for ci, cj, cl in children:
                    di, dj, dl = tree.descend(ci, cj, cl)
                    depths[dl - level] += 1
                counts[f"child_depth_{dict(depths)}"] += 1
    print(json.dumps({"iterations": iterations, "leaves": len(leaf_set),
                      "counts": {str(k): int(v) for k, v in counts.items()},
                      "mismatch_count": len(mismatches),
                      "mismatches": mismatches[:10]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
