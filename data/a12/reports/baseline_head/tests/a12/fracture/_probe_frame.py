#!/usr/bin/env python
"""Is the returned cutter mesh really expressed in the stored ``CutBasis`` frame?

The cutter of the *plane* backend must be a slab whose top surface is the analytic plane
``w = 0`` (offset along ``basis.normal`` from ``basis.origin``).  This probe measures that
directly instead of trusting the frame: PCA of the cutter vertices gives the slab's thickness
direction, and the material's spread along that direction shows where the cut really is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MASTER_SEED = 20261001
LINEAGE_ID = "a12_demo"


def main() -> int:
    from synlab.fracture.api import make_closed_cutter
    from synlab.fracture.spec import FractureSpec
    from synlab.mothers.api import load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    vessel = sys.argv[1] if len(sys.argv) > 1 else "V01"
    root = REPO_ROOT / "data" / "a12_demo"
    manifest = json.loads((root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{vessel}")
    mother = load_mother(AssetStore(root / "store"), str(entry["asset_id"]))
    spec = FractureSpec(backend="plane_shared_cut", target_rms_mm=0.05)
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", vessel, "plane_shared_cut")
    cutter = make_closed_cutter(mother, spec, rng)
    basis = cutter.basis
    verts = np.asarray(cutter.mesh.vertices, dtype=np.float64)
    centre = verts.mean(axis=0)
    centred = verts - centre
    values, vectors = np.linalg.eigh(centred.T @ centred)
    order = np.argsort(values)
    thin = vectors[:, order[0]]
    print(f"{vessel}: cutter verts={verts.shape[0]} faces={len(cutter.mesh.faces)}", flush=True)
    print(f"  basis.normal={np.round(basis.normal, 6).tolist()} "
          f"origin={np.round(basis.origin, 4).tolist()}", flush=True)
    print(f"  PCA thin axis={np.round(thin, 6).tolist()} "
          f"|dot(thin, basis.normal)|={abs(float(thin @ basis.normal)):.6f}", flush=True)
    print(f"  eigen sqrt={np.round(np.sqrt(np.maximum(values[order], 0.0)), 3).tolist()}", flush=True)
    # thickness and top/bottom along the PCA thin axis
    along = centred @ thin
    print(f"  extent along thin axis: min={along.min():.3f} max={along.max():.3f} "
          f"thickness={along.max() - along.min():.3f}", flush=True)
    # where is the material relative to that slab?
    material = np.asarray(mother.mesh.vertices, dtype=np.float64) - centre
    material_along = material @ thin
    print(f"  material along thin axis: min={material_along.min():.3f} "
          f"max={material_along.max():.3f}", flush=True)
    # and in the *stored* basis frame
    local = basis.to_local(verts)
    local_material = basis.to_local(np.asarray(mother.mesh.vertices, dtype=np.float64))
    print(f"  cutter w in basis frame: {local[:, 2].min():.3f} .. {local[:, 2].max():.3f}", flush=True)
    print(f"  material w in basis frame: {local_material[:, 2].min():.3f} .. "
          f"{local_material[:, 2].max():.3f}", flush=True)
    print(f"  basis.meta w_min/w_max: {basis.meta['w_min_mm']:.3f} / {basis.meta['w_max_mm']:.3f}",
          flush=True)
    # do the cutter's side walls stay outside the material's (u, v) rectangle?
    u_lo, u_hi = float(basis.u_range[0]), float(basis.u_range[1])
    v_lo, v_hi = float(basis.v_range[0]), float(basis.v_range[1])
    mu_lo, mu_hi = (float(x) for x in basis.meta.get("material_u_range", (u_lo, u_hi)))
    mv_lo, mv_hi = (float(x) for x in basis.meta.get("material_v_range", (v_lo, v_hi)))
    cu_lo, cu_hi = float(local[:, 0].min()), float(local[:, 0].max())
    cv_lo, cv_hi = float(local[:, 1].min()), float(local[:, 1].max())
    print(f"  frame u: cutter[{cu_lo:.3f},{cu_hi:.3f}] basis[{u_lo:.3f},{u_hi:.3f}] "
          f"material[{mu_lo:.3f},{mu_hi:.3f}]", flush=True)
    print(f"  frame v: cutter[{cv_lo:.3f},{cv_hi:.3f}] basis[{v_lo:.3f},{v_hi:.3f}] "
          f"material[{mv_lo:.3f},{mv_hi:.3f}]", flush=True)
    outside = ((local_material[:, 0] < cu_lo) | (local_material[:, 0] > cu_hi)
               | (local_material[:, 1] < cv_lo) | (local_material[:, 1] > cv_hi))
    print(f"  material vertices OUTSIDE the cutter's (u,v) frame: "
          f"{int(np.sum(outside))} of {local_material.shape[0]}", flush=True)
    # the top surface must be the largest connected flat plane of the slab: check the vertices
    # that sit on the boundary of the two extreme w clusters
    near_top = verts[np.abs(local[:, 2] - local[:, 2].max()) < 1.0e-6]
    near_bottom = verts[np.abs(local[:, 2] - local[:, 2].min()) < 1.0e-6]
    print(f"  vertices at max w: {near_top.shape[0]}  at min w: {near_bottom.shape[0]}", flush=True)
    # decisive test: for a cutter {w <= 0} ∩ frame, the set of material points inside the cutter
    # must be exactly the set with w <= 0 in the stored basis frame
    material_points = np.asarray(mother.mesh.vertices, dtype=np.float64)
    inside_cutter = np.asarray(cutter.mesh.contains(material_points), dtype=bool)
    expected_inside = local_material[:, 2] <= 0.0
    agree = int(np.sum(inside_cutter == expected_inside))
    print(f"  material vertices inside the cutter: {int(inside_cutter.sum())} of "
          f"{material_points.shape[0]}; expected from basis frame (w<=0): "
          f"{int(expected_inside.sum())}; agreement={agree}/{material_points.shape[0]} "
          f"({agree / material_points.shape[0]:.4f})", flush=True)
    if near_top.shape[0] > 2:
        top_centred = near_top - near_top.mean(axis=0)
        values_top, vectors_top = np.linalg.eigh(top_centred.T @ top_centred)
        top_normal = vectors_top[:, int(np.argmin(values_top))]
        print(f"  'top' cluster normal={np.round(top_normal, 6).tolist()} "
              f"|dot(basis.normal)|={abs(float(top_normal @ basis.normal)):.6f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
