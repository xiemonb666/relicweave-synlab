#!/usr/bin/env python
"""Measure where M- / M+ vertices actually sit relative to the cut plane and the cutter."""

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
    import trimesh

    from synlab.fracture.api import make_closed_cutter
    from synlab.fracture.booleans import boolean_difference, boolean_intersection, tag_source
    from synlab.fracture.spec import FractureSpec
    from synlab.mothers.api import load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    vessel = sys.argv[1] if len(sys.argv) > 1 else "V18"
    root = REPO_ROOT / "data" / "a12_demo"
    manifest = json.loads((root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{vessel}")
    mother = load_mother(AssetStore(root / "store"), str(entry["asset_id"]))
    spec = FractureSpec(backend="plane_shared_cut", target_rms_mm=0.05)
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", vessel, "plane_shared_cut")
    cutter = make_closed_cutter(mother, spec, rng)
    basis = cutter.basis
    print(f"{vessel}: mother faces={len(mother.mesh.faces)} area={mother.mesh.area:.1f} "
          f"volume={abs(mother.mesh.volume):.1f}", flush=True)
    print(f"basis: w_min={basis.meta['w_min_mm']:.3f} w_max={basis.meta['w_max_mm']:.3f} "
          f"depth_margin={basis.meta['depth_margin_mm']}", flush=True)
    local_cutter = basis.to_local(np.asarray(cutter.mesh.vertices, dtype=np.float64))
    print(f"cutter local w range: {local_cutter[:, 2].min():.3f} .. {local_cutter[:, 2].max():.3f}",
          flush=True)
    sm = tag_source(trimesh.Trimesh(vertices=np.asarray(mother.mesh.vertices),
                                    faces=np.asarray(mother.mesh.faces), process=False), 1.0, "m")
    sc = tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                    faces=np.asarray(cutter.mesh.faces), process=False), 2.0, "c")
    for name, side in (("M-", boolean_intersection([sm, sc], label="minus")),
                       ("M+", boolean_difference([sm, sc], label="plus"))):
        verts = np.asarray(side.mesh.vertices, dtype=np.float64)
        local = basis.to_local(verts)
        distance = np.asarray(cutter.mesh.nearest.on_surface(verts)[1], dtype=np.float64)
        w = local[:, 2]
        print(f"{name}: verts={verts.shape[0]} faces={side.n_faces} vol={abs(side.mesh.volume):.1f} "
              f"|w| p50={np.percentile(np.abs(w), 50):.3f} p95={np.percentile(np.abs(w), 95):.3f} "
              f"max={np.abs(w).max():.3f}", flush=True)
        print(f"     cutter distance: p50={np.percentile(distance, 50):.6f} "
              f"p95={np.percentile(distance, 95):.6f} max={distance.max():.3f} "
              f"frac<1e-4={float(np.mean(distance <= 1e-4)):.3f}", flush=True)
        near = distance <= 1e-4
        if bool(np.any(near)):
            print(f"     near-boundary |w| p50={np.percentile(np.abs(w[near]), 50):.3f} "
                  f"p95={np.percentile(np.abs(w[near]), 95):.3f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
