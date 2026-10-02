"""Root-cause probe for the volume loss at N>=16: are the empty cells' cutters watertight?

The event builds one roughness field per shared facet and hands each cell its own facets' fields.
This probe does exactly that (same public functions, same seeds), then reports, per cell, whether
the discretised cutter is a closed positive solid.  A non-watertight cutter is the mechanism that
turns a cell into an empty boolean and therefore into missing material.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "a12_reports" / "_fcal_diag_cells_fields.json"


def main() -> int:
    import trimesh

    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.voronoi_event import (
        _displaced_cell_mesh, _matching_facets, _position_of, _symmetric_facet_polygon,
        facet_roughness_field,
    )
    from synlab.fracture.voronoi_frag import build_partition
    from synlab.fracture.calibrate import body_stats_of, load_mother, material_stats_of

    cfg = load_physics_config()
    mother = load_mother("V01", "M01")
    body = body_stats_of(mother, "V01")
    material = material_stats_of("M01")
    mesh = mother.mesh
    report: dict = {"mother_volume_mm3": float(abs(mesh.volume)), "runs": []}
    for n in (8, 16, 32):
        partition, _sr = build_partition(mesh, n, rng=np.random.default_rng(20261002),
                                         seed_cfg=cfg.seeds, padding_mm=2.0)
        fields = {}
        for cell in partition.cells:
            for facet_index, neighbour in enumerate(cell.facet_neighbours):
                if neighbour < 0:
                    continue
                key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
                if key in fields:
                    continue
                other_position = _position_of(partition, int(neighbour))
                if other_position is None:
                    continue
                other = partition.cells[other_position]
                pair = _matching_facets(cell, facet_index, other)
                if pair is None:
                    continue
                fields[key] = facet_roughness_field(cell, other, pair[0], config=cfg,
                                                    wall_mm=body.wall_mm,
                                                    grain_mm=material.grain_size_mm, seed=0)
        run: dict = {"target_pieces": n, "cells": int(len(partition.cells)),
                     "shared_facets": int(len(fields)), "cell_rows": []}
        for position, cell in enumerate(partition.cells):
            own = {}
            for facet_index, neighbour in enumerate(cell.facet_neighbours):
                if neighbour < 0:
                    continue
                key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
                if key in fields:
                    own[facet_index] = fields[key]
            cm = _displaced_cell_mesh(cell, own, refinement=cfg.roughness.facet_refinement,
                                      refine_mm=cfg.roughness.facet_refine_mm)
            run["cell_rows"].append({
                "cell": position, "facets": int(len(cell.facet_neighbours)),
                "shared_facets": int(len(own)),
                "faces": int(len(np.asarray(cm.faces))),
                "watertight": bool(cm.is_watertight),
                "volume_mm3": float(abs(np.asarray(cm.volume))),
                "euler": int(cm.euler_number),
                "boundary_edges": int(np.sum(np.asarray(cm.edges_unique_inverse).size and
                                             (np.bincount(np.asarray(cm.edges_unique_inverse))
                                              == 1))),
            })
        run["not_watertight"] = [r["cell"] for r in run["cell_rows"] if not r["watertight"]]
        run["n_not_watertight"] = len(run["not_watertight"])
        report["runs"].append(run)
        OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"N={n}: cells={run['cells']} shared_facets={run['shared_facets']} "
              f"non-watertight cutters={run['n_not_watertight']} at {run['not_watertight']}",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
