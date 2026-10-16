#!/usr/bin/env python
"""Attribute the non-watertight boolean output: inputs vs Manifold vs weld.

The demo run of ``plane_shared_cut`` fails with ``M_minus is not watertight after the
boolean`` even though the mother *and* the plane cutter are index-watertight.  This probe
separates the possible causes with measurements instead of guesses:

* mother / cutter: edge histogram, degenerate faces, duplicate positions, Manifold status;
* boolean outputs: edge histogram, degenerate faces, boundary-edge position parity
  (i.e. *positionally* closed but index-split) and the same after a positional weld;
* a control run with the same plane offset by ``--offset`` mm (removes the coincidence).

Usage:

```powershell
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_probe_boolean.py --vessel V01
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


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return {"shape": list(value.shape), "dtype": str(value.dtype)}
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value


def edge_report(mesh: Any) -> dict[str, Any]:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    counter: Counter[tuple[int, int]] = Counter()
    for tri in faces:
        for k in range(3):
            a, b = int(tri[k]), int(tri[(k + 1) % 3])
            counter[(min(a, b), max(a, b))] += 1
    boundary = [e for e, n in counter.items() if n == 1]
    # positional parity of the boundary edges: a positionally closed surface uses every
    # position an even number of times in the boundary edge set
    keys = np.round(verts, 6)
    lookup: dict[tuple[float, float, float], int] = {}
    ids = []
    for row in keys:
        key = (float(row[0]), float(row[1]), float(row[2]))
        lookup.setdefault(key, len(lookup))
        ids.append(lookup[key])
    ids = np.asarray(ids, dtype=np.int64)
    parity: Counter[int] = Counter()
    for a, b in boundary:
        parity[int(ids[a])] += 1
        parity[int(ids[b])] += 1
    odd = int(sum(1 for v in parity.values() if v % 2))
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    return {
        "faces": int(faces.shape[0]),
        "vertices": int(verts.shape[0]),
        "edge_use_histogram": {str(k): int(v) for k, v in sorted(Counter(counter.values()).items())},
        "boundary_edges": len(boundary),
        "boundary_odd_parity_positions": odd,
        "unique_positions": len(lookup),
        "duplicate_positions": int(verts.shape[0] - len(lookup)),
        "degenerate_faces": int(np.sum(areas <= 0.0)),
        "min_face_area_mm2": float(areas.min()) if areas.size else 0.0,
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "volume_mm3": float(mesh.volume),
    }


def manifold_status(mesh: Any, *, mesh_id: float = 1.0) -> dict[str, Any]:
    from manifold3d import Manifold, Mesh

    from synlab.fracture.booleans import _vertex_properties, tag_source

    source = tag_source(mesh, mesh_id, "probe")
    try:
        mani = Manifold(Mesh(vert_properties=_vertex_properties(source),
                             tri_verts=np.asarray(mesh.faces, dtype=np.uint32)))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    out = {
        "status": str(mani.status()),
        "num_tri": int(mani.num_tri()),
        "num_vert": int(mani.num_vert()),
        "volume_mm3": float(mani.volume()),
        "genus": int(mani.genus()),
        "is_empty": bool(mani.is_empty()),
    }
    for extra in ("is_manifold", "is_convex", "is_winding_consistent"):
        hook = getattr(mani, extra, None)
        if callable(hook):
            out[extra] = bool(hook())
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V01")
    parser.add_argument("--backend", default="plane_shared_cut")
    parser.add_argument("--offset", type=float, default=0.0)
    parser.add_argument("--rms", type=float, default=0.05)
    parser.add_argument("--demo-root", default=str(REPO_ROOT / "data" / "a12_demo"))
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    import trimesh
    from manifold3d import Manifold, Mesh

    from synlab.fracture.api import make_closed_cutter
    from synlab.fracture.booleans import _vertex_properties, tag_source
    from synlab.fracture.spec import FractureSpec
    from synlab.mothers.api import load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    manifest = json.loads((Path(args.demo_root) / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{args.vessel}")
    store = AssetStore(Path(args.demo_root) / "store")
    mother = load_mother(store, str(entry["asset_id"]))

    spec = FractureSpec(backend=args.backend, target_rms_mm=float(args.rms))
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", args.vessel, args.backend)
    cutter = make_closed_cutter(mother, spec, rng)
    cutter_mesh = cutter.mesh
    if args.offset:
        shift = np.asarray(cutter.basis.normal, dtype=np.float64) * float(args.offset)
        cutter_mesh = trimesh.Trimesh(vertices=np.asarray(cutter_mesh.vertices) + shift[None, :],
                                      faces=np.asarray(cutter_mesh.faces), process=False)

    report: dict[str, Any] = {"vessel_id": args.vessel, "backend": args.backend,
                              "offset_mm": float(args.offset)}
    report["mother"] = edge_report(mother.mesh)
    report["mother_manifold"] = manifold_status(mother.mesh, mesh_id=1.0)
    report["cutter"] = edge_report(cutter_mesh)
    report["cutter_manifold"] = manifold_status(cutter_mesh, mesh_id=2.0)

    ma = Manifold(Mesh(vert_properties=_vertex_properties(tag_source(mother.mesh, 1.0, "m")),
                       tri_verts=np.asarray(mother.mesh.faces, dtype=np.uint32)))
    mb = Manifold(Mesh(vert_properties=_vertex_properties(tag_source(cutter_mesh, 2.0, "c")),
                       tri_verts=np.asarray(cutter_mesh.faces, dtype=np.uint32)))
    for name, result in (("M_minus", ma ^ mb), ("M_plus", ma - mb)):
        data = result.to_mesh()
        props = np.asarray(data.vert_properties, dtype=np.float64)
        faces = np.asarray(data.tri_verts, dtype=np.int64)
        mesh = trimesh.Trimesh(vertices=props[:, 0:3].copy(), faces=faces, process=False)
        block = {"manifold_status": str(result.status()),
                 "raw": edge_report(mesh)}
        welded = trimesh.Trimesh(vertices=np.asarray(mesh.vertices, dtype=np.float64),
                                 faces=np.asarray(mesh.faces, dtype=np.int64), process=True)
        welded.merge_vertices()
        block["welded"] = edge_report(welded)
        report[name] = block
        print(f"[{name}] raw={block['raw']['edge_use_histogram']} "
              f"boundary={block['raw']['boundary_edges']} deg={block['raw']['degenerate_faces']} "
              f"dup={block['raw']['duplicate_positions']} | welded watertight="
              f"{block['welded']['watertight']} hist={block['welded']['edge_use_histogram']}",
              flush=True)

    print(f"[mother] {report['mother']['edge_use_histogram']} "
          f"deg={report['mother']['degenerate_faces']} manifold={report['mother_manifold']}",
          flush=True)
    print(f"[cutter] {report['cutter']['edge_use_histogram']} "
          f"deg={report['cutter']['degenerate_faces']} manifold={report['cutter_manifold']}",
          flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"[written] {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
