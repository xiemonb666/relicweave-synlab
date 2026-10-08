#!/usr/bin/env python
"""Locate the remaining ``ORIGIN_AMBIGUOUS`` vertices of one real plane cut.

Prints, for each boolean output, the ambiguous-vertex count per source mesh, the distance to the
closest and to the first non-adjacent candidate, and where those vertices sit (so an artefact can
be told apart from a genuine double surface).

Usage:

```powershell
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_probe_ambiguity.py --vessel V01
```
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MASTER_SEED = 20261001
LINEAGE_ID = "a12_demo"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V01")
    parser.add_argument("--backend", default="plane_shared_cut")
    parser.add_argument("--demo-root", default=str(REPO_ROOT / "data" / "a12_demo"))
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    import trimesh

    from synlab.fracture.api import make_closed_cutter
    from synlab.fracture.booleans import (
        SourceResolver,
        boolean_difference,
        boolean_intersection,
        tag_source,
    )
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

    source_mother = tag_source(trimesh.Trimesh(vertices=np.asarray(mother.mesh.vertices),
                                               faces=np.asarray(mother.mesh.faces), process=False),
                               1.0, "mother")
    source_cutter = tag_source(trimesh.Trimesh(vertices=np.asarray(cutter.mesh.vertices),
                                               faces=np.asarray(cutter.mesh.faces), process=False),
                               2.0, "cutter")
    resolver = SourceResolver([source_mother, source_cutter], tolerance_mm=1.0e-4)
    report: dict[str, Any] = {"vessel_id": args.vessel, "backend": args.backend}
    for name, side in (("M_minus", boolean_intersection([source_mother, source_cutter],
                                                        label="M_minus")),
                       ("M_plus", boolean_difference([source_mother, source_cutter],
                                                     label="M_plus"))):
        classification = resolver.classify(side, container=cutter.mesh,
                                           container_tolerance_mm=1.0e-4)
        origin = np.asarray(classification["vertex_origin"])
        ambiguous = np.asarray(classification["vertex_ambiguous"], dtype=bool)
        mesh_id = np.asarray(classification["vertex_mesh_id"])
        points = np.asarray(side.point, dtype=np.float64)
        row: dict[str, Any] = {
            "vertices": int(origin.shape[0]),
            "ambiguous": int(np.sum(ambiguous)),
            "ambiguous_ratio": float(np.mean(ambiguous)),
            "ambiguous_by_mesh": {str(int(m)): int(np.sum(ambiguous & (mesh_id == m)))
                                  for m in sorted(set(mesh_id.tolist()))},
            "watertight": bool(side.mesh.is_watertight),
            "welded_coincident_vertices": int(side.mesh.metadata.get(
                "welded_coincident_vertices", 0)),
        }
        if bool(np.any(ambiguous)):
            pts = points[ambiguous]
            row["ambiguous_bounds_mm"] = [np.round(pts.min(axis=0), 3).tolist(),
                                          np.round(pts.max(axis=0), 3).tolist()]
            # how close is the competing *non-adjacent* patch?  A gap of ~0 means the source
            # mesh really carries two coincident surface patches; a gap near the tolerance is an
            # artefact of the matching tolerance.
            stats: dict[str, Any] = {}
            for mesh_name, locator, ids in (("mother", resolver.locators[1.0],
                                             np.nonzero(ambiguous & (mesh_id == 1))[0]),
                                            ("cutter", resolver.locators[2.0],
                                             np.nonzero(ambiguous & (mesh_id == 2))[0])):
                if ids.size == 0:
                    continue
                selected = points[ids]
                _, _, best_distance, _ = locator.locate(selected, tolerance_mm=0.0)
                faces = np.asarray(locator.mesh.faces, dtype=np.int64)
                triangles = np.asarray(locator.mesh.triangles, dtype=np.float64)
                from scipy.spatial import cKDTree

                tree = cKDTree(np.asarray(locator.mesh.triangles_center, dtype=np.float64))
                k = int(min(locator.AMBIGUITY_NEIGHBOURS + 1, triangles.shape[0]))
                _, candidates = tree.query(selected, k=k)
                candidates = np.atleast_2d(np.asarray(candidates, dtype=np.int64))
                tris = triangles[candidates]
                distance, _ = locator._point_triangle(selected, tris)
                order = np.argsort(distance, axis=1, kind="stable")
                rows = np.arange(selected.shape[0])
                best_faces = faces[candidates[rows, order[:, 0]]]
                gaps = []
                for index in rows:
                    for rank in range(1, order.shape[1]):
                        other = candidates[index, order[index, rank]]
                        if set(faces[other].tolist()) & set(best_faces[index].tolist()):
                            continue
                        gaps.append(float(distance[index, order[index, rank]]
                                          - distance[index, order[index, 0]]))
                        break
                gaps_array = np.asarray(gaps, dtype=np.float64) if gaps else np.zeros(0)
                stats[mesh_name] = {
                    "ambiguous": int(ids.size),
                    "best_distance_p95_mm": float(np.percentile(best_distance, 95)),
                    "best_distance_max_mm": float(np.max(best_distance)),
                    "non_adjacent_gap_p50_mm": (float(np.median(gaps_array))
                                                if gaps_array.size else None),
                    "non_adjacent_gap_p95_mm": (float(np.percentile(gaps_array, 95))
                                                if gaps_array.size else None),
                    "non_adjacent_gap_max_mm": (float(np.max(gaps_array))
                                                if gaps_array.size else None),
                    "no_non_adjacent_candidate": int(ids.size - gaps_array.size),
                }
                if mesh_name == "cutter" and ids.size:
                    # dump the first two competing triangle pairs for the record
                    examples = []
                    for index in rows[:2]:
                        entry = {"point": np.round(selected[index], 6).tolist(),
                                 "best_tri": int(candidates[index, order[index, 0]]),
                                 "best_distance": float(distance[index, order[index, 0]]),
                                 "candidates": []}
                        for rank in range(order.shape[1]):
                            tri_id = int(candidates[index, order[index, rank]])
                            shares = bool(set(faces[tri_id].tolist())
                                          & set(best_faces[index].tolist()))
                            entry["candidates"].append({
                                "tri": tri_id, "distance": float(distance[index, order[index, rank]]),
                                "shares_vertex": shares,
                                "vertices": np.round(triangles[tri_id], 6).tolist()})
                            if len(entry["candidates"]) >= 4:
                                break
                        examples.append(entry)
                    stats[mesh_name]["examples"] = examples
            row["ambiguous_distance_stats"] = stats
        report[name] = row
        print(f"[{name}] {row}", flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[written] {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
