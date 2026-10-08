#!/usr/bin/env python
"""Print the two competing cutter triangles behind one ambiguous vertex (V01 plane cut)."""

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
    from synlab.fracture.booleans import SourceResolver, boolean_intersection, tag_source
    from synlab.fracture.spec import FractureSpec
    from synlab.mothers.api import load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    root = REPO_ROOT / "data" / "a12_demo"
    manifest = json.loads((root / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == "mother:V01")
    mother = load_mother(AssetStore(root / "store"), str(entry["asset_id"]))
    spec = FractureSpec(backend="plane_shared_cut", target_rms_mm=0.05)
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", "V01", "plane_shared_cut")
    cutter = make_closed_cutter(mother, spec, rng)
    print("cutter faces", len(cutter.mesh.faces), "verts", len(cutter.mesh.vertices))

    faces = np.asarray(cutter.mesh.faces, dtype=np.int64)
    verts = np.asarray(cutter.mesh.vertices, dtype=np.float64)
    key = {}
    for index, vertex in enumerate(verts):
        key.setdefault(tuple(np.round(vertex, 9).tolist()), []).append(index)
    duplicated = {k: v for k, v in key.items() if len(v) > 1}
    print("duplicate cutter positions:", len(duplicated))

    # duplicate *triangles* at the same three positions
    tri_keys: dict[tuple, int] = {}
    duplicates = 0
    for index, tri in enumerate(faces):
        positions = tuple(sorted(tuple(np.round(verts[v], 9).tolist()) for v in tri))
        if positions in tri_keys:
            duplicates += 1
            if duplicates <= 3:
                other = tri_keys[positions]
                print("duplicate triangle", index, "==", other)
                print("   verts", verts[tri].tolist())
        else:
            tri_keys[positions] = index
    print("duplicate triangles:", duplicates)

    # degenerate triangles
    areas = trimesh.Trimesh(vertices=verts, faces=faces, process=False).area_faces
    print("degenerate faces:", int(np.sum(areas <= 0)), "min area", float(areas.min()))
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    print("w range", float(verts[:, 2].min()), float(verts[:, 2].max()))
    top = np.isclose(a[:, 2], 0.0) & np.isclose(b[:, 2], 0.0) & np.isclose(c[:, 2], 0.0)
    print("faces exactly on w=0:", int(np.sum(top)), "of", len(faces))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
