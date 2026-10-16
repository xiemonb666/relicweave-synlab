#!/usr/bin/env python
"""Debug probe: why does the plane baseline report a non-zero delivered-face roughness?"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.fracture import surface_features as sf          # noqa: E402
from synlab.fracture.api import _default_basis, audit_fracture, make_closed_cutter  # noqa: E402
from synlab.fracture.event import run_shared_cut            # noqa: E402
from synlab.fracture.spec import BACKEND_PLANE, FractureSpec  # noqa: E402
from synlab.schemas.runtime import ORIGIN_INTERFACE          # noqa: E402


def main() -> int:
    from synlab.mothers.api import create_mother, load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore
    import json

    demo_root = REPO_ROOT / "data" / "a12_demo"
    manifest = json.loads((demo_root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == "mother:V18")
    demo = load_mother(AssetStore(demo_root / "store"), str(entry["asset_id"]))
    rng = make_rng(20261001, "probe", "mothers", "V18", "M01")
    mother = create_mother("V18", "M01", dict(demo.params), rng, mother_id="probe_V18_M01")
    rng = make_rng(20261001, "probe", "fracture", "V18", "M01")
    basis = _default_basis(mother, rng, FractureSpec())
    cutter = make_closed_cutter(mother, FractureSpec(backend=BACKEND_PLANE), rng, basis=basis)
    result = run_shared_cut(mother, cutter, event_id="probe", backend=BACKEND_PLANE)
    print("qa passed", audit_fracture(result, mother).get("passed"))
    for fragment in result.fragments:
        origin = np.asarray(fragment.face_origin_kind)
        ids = np.nonzero(origin == ORIGIN_INTERFACE)[0]
        print(f"fragment {fragment.fragment_id}: faces={origin.shape[0]} interface={ids.size} "
              f"kinds={np.bincount(origin).tolist()}")
        local = sf.triangle_vertices_local(fragment.mesh, basis, ids)
        if local.shape[0]:
            w = local[:, 2]
            print(f"   local w: min={w.min():.6f} max={w.max():.6f} "
                  f"p99={np.percentile(np.abs(w), 99):.6f}")
            tri = local.reshape(-1, 3, 3)
            span = np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1)
            print(f"   edge length: median={np.median(span):.4f} max={span.max():.4f}")
            # per-triangle planarity: how far is each vertex off the plane of the other two?
            n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            nn = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
            h = np.abs(np.einsum("ij,ij->i", nn, tri[:, 0] - tri[:, 0]))
            print(f"   degenerate normal count={int(np.sum(h != h))} "
                  f"areasum={sf._triangle_area(tri):.3f}")
    samples = sf.measure_interface_surface(result.fragments, basis, None)
    print("measure (no params):", {k: samples.get(k) for k in
                                   ("samples", "Ra_mm", "Rz_mm", "measured_area_mm2")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
