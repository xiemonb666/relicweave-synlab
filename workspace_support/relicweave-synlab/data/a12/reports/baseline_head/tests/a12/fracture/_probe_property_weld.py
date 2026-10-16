#!/usr/bin/env python
"""Decide whether the non-watertight boolean output comes from the vertex *properties*.

``synlab.fracture.booleans`` feeds each cutter/mother vertex a 7-column property block
(position + mesh id + source triangle + barycentric slot).  Manifold only merges coincident
vertices whose properties agree, so a tight experiment is: run the same boolean with
*constant* properties and count the boundary edges of the result.

Usage:

```powershell
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_probe_property_weld.py --vessel V01
```
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MASTER_SEED = 20261001
LINEAGE_ID = "a12_demo"


def edge_stats(vertices: np.ndarray, faces: np.ndarray) -> dict[str, Any]:
    counter: Counter[tuple[int, int]] = Counter()
    for tri in faces:
        for k in range(3):
            a, b = int(tri[k]), int(tri[(k + 1) % 3])
            counter[(min(a, b), max(a, b))] += 1
    positions = np.round(np.asarray(vertices, dtype=np.float64), 9)
    unique = len(np.unique(positions, axis=0))
    return {
        "faces": int(faces.shape[0]),
        "vertices": int(vertices.shape[0]),
        "boundary_edges": int(sum(1 for n in counter.values() if n == 1)),
        "edge_use_histogram": {str(k): int(v) for k, v in sorted(Counter(counter.values()).items())},
        "duplicate_positions": int(vertices.shape[0] - unique),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V01")
    parser.add_argument("--backend", default="plane_shared_cut")
    parser.add_argument("--demo-root", default=str(REPO_ROOT / "data" / "a12_demo"))
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from manifold3d import Manifold, Mesh

    from synlab.fracture.api import make_closed_cutter
    from synlab.fracture.spec import FractureSpec
    from synlab.mothers.api import load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    manifest = json.loads((Path(args.demo_root) / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{args.vessel}")
    store = AssetStore(Path(args.demo_root) / "store")
    mother = load_mother(store, str(entry["asset_id"]))
    spec = FractureSpec(backend=args.backend, target_rms_mm=0.05)
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", args.vessel, args.backend)
    cutter = make_closed_cutter(mother, spec, rng)

    report: dict[str, Any] = {"vessel_id": args.vessel, "backend": args.backend}
    for label, constant in (("position_only_properties", True), ("full_properties", False)):
        blocks = []
        for mesh, mesh_id in ((mother.mesh, 1.0), (cutter.mesh, 2.0)):
            verts = np.asarray(mesh.vertices, dtype=np.float64)
            props = np.zeros((verts.shape[0], 3), dtype=np.float32)
            props[:, 0:3] = verts
            if not constant:
                props = np.zeros((verts.shape[0], 7), dtype=np.float32)
                props[:, 0:3] = verts
                props[:, 3] = mesh_id                 # mesh id differs per input
                props[:, 4] = 0.5                     # constant triangle id
                props[:, 5] = 0.5                     # constant barycentric slot
                props[:, 6] = 0.5
            blocks.append(Manifold(Mesh(vert_properties=props,
                                        tri_verts=np.asarray(mesh.faces, dtype=np.uint32))))
        result = blocks[0] ^ blocks[1]
        data = result.to_mesh()
        out = edge_stats(np.asarray(data.vert_properties, dtype=np.float64)[:, 0:3],
                         np.asarray(data.tri_verts, dtype=np.int64))
        out["manifold_status"] = str(result.status())
        report[label] = out
        print(f"[{label}] boundary={out['boundary_edges']} dup={out['duplicate_positions']} "
              f"hist={out['edge_use_histogram']} status={out['manifold_status']}", flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[written] {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
