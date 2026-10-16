#!/usr/bin/env python
"""Why do some interface faces find no complementary partner? (V18 plane cut)."""

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
    from scipy.spatial import cKDTree

    from synlab.fracture.api import make_closed_cutter
    from synlab.fracture.booleans import (
        SourceResolver,
        boolean_difference,
        boolean_intersection,
        tag_source,
    )
    from synlab.fracture.event import _face_area_sum, _interface_faces
    from synlab.fracture.fragment import make_fragment, split_components
    from synlab.fracture.spec import FractureSpec
    from synlab.mothers.api import load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    root = REPO_ROOT / "data" / "a12_demo"
    manifest = json.loads((root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == "mother:V18")
    mother = load_mother(AssetStore(root / "store"), str(entry["asset_id"]))
    spec = FractureSpec(backend="plane_shared_cut", target_rms_mm=0.05)
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", "V18", "plane_shared_cut")
    cutter = make_closed_cutter(mother, spec, rng)
    sm = tag_source(trimesh.Trimesh(vertices=np.asarray(mother.mesh.vertices),
                                    faces=np.asarray(mother.mesh.faces), process=False), 1.0, "m")
    sc = tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                    faces=np.asarray(cutter.mesh.faces), process=False), 2.0, "c")
    minus = boolean_intersection([sm, sc], label="M_minus")
    plus = boolean_difference([sm, sc], label="M_plus")
    resolver = SourceResolver([sm, sc], tolerance_mm=1.0e-4)
    fragments = []
    for name, side, side_tag in (("M_minus", minus, -1), ("M_plus", plus, 1)):
        classification = resolver.classify(side, container=cutter.mesh,
                                           container_tolerance_mm=1.0e-4)
        classification["_faces"] = np.asarray(side.mesh.faces, dtype=np.int64)
        classification["area_faces"] = np.asarray(side.mesh.area_faces, dtype=np.float64)
        classification["mother_mesh_id"] = 1
        classification["cutter_mesh_id"] = 2
        for index, part in enumerate(split_components(side.mesh)):
            fragments.append(make_fragment(part, fragment_id=f"{name}_{index}", component_id=index,
                                           side=side_tag, classification=classification,
                                           parent_id=None, backend="plane_shared_cut",
                                           cutter_hash="probe", extra_meta={}))
    faces_a, sources_a, centres_a = _interface_faces(fragments[0])
    faces_b, sources_b, centres_b = _interface_faces(fragments[1])
    tree = cKDTree(np.asarray(centres_b))
    distances, _ = tree.query(np.asarray(centres_a), k=1)
    basis = cutter.basis
    local_a = basis.to_local(np.asarray(fragments[0].mesh.triangles_center)[faces_a])
    local_b = basis.to_local(np.asarray(fragments[1].mesh.triangles_center)[faces_b])
    normals_a = np.asarray(fragments[0].mesh.face_normals)[faces_a]
    plane_dot = np.abs(normals_a @ np.asarray(basis.normal))
    unmatched = distances > 1.0e-3
    print(f"A faces={faces_a.size} B faces={faces_b.size} unmatched={int(np.sum(unmatched))} "
          f"area={_face_area_sum(fragments[0], faces_a[unmatched]):.3f}mm2", flush=True)
    if bool(np.any(unmatched)):
        print("unmatched centroid distance to nearest B: "
              f"p50={np.percentile(distances[unmatched], 50):.4f} "
              f"p95={np.percentile(distances[unmatched], 95):.4f} "
              f"max={np.max(distances[unmatched]):.4f} mm", flush=True)
        print("unmatched |w| (distance to the cut plane): "
              f"p50={np.percentile(np.abs(local_a[unmatched, 2]), 50):.5f} "
              f"max={np.max(np.abs(local_a[unmatched, 2])):.5f} mm", flush=True)
        print("unmatched |dot(n, plane normal)|: "
              f"p50={np.percentile(plane_dot[unmatched], 50):.4f} "
              f"min={np.min(plane_dot[unmatched]):.4f}", flush=True)
        print("matched   |w| p95: "
              f"{np.percentile(np.abs(local_a[~unmatched, 2]), 95):.6f} mm", flush=True)
    print("B |w| p95:", float(np.percentile(np.abs(local_b[:, 2]), 95)), flush=True)
    print("A |w| p95:", float(np.percentile(np.abs(local_a[:, 2]), 95)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
