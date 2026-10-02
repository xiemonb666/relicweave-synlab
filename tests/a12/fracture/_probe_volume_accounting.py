"""Root cause of the Voronoi volume loss, as a measured indicator.

For a given piece count the probe rebuilds the *event's own* partition and roughness fields (same
public functions, same rng state: see ``synlab.fracture.calibrate.event_rng``), then measures, per
cell:

* whether the discretised cutter the event would feed to the boolean is a closed positive solid;
* what the boolean ``mother ∩ cutter`` returns for it (faces, volume).

The event's audit compares ``sum(piece volumes)`` with the mother volume, so a cell whose cutter is
not closed and whose intersection therefore comes back empty is exactly one missing term of that
sum.  The report keeps both columns, so the correlation is a measurement and not an inference.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

REPORT_DIR = REPO_ROOT / "data" / "a12_reports"
SWEEP = (2, 3, 4, 6, 8, 12, 16, 24, 32)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V01")
    parser.add_argument("--material", default="M01")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--counts", default=",".join(str(x) for x in SWEEP))
    parser.add_argument("--out", default=str(REPORT_DIR / "fracture_volume_accounting.json"))
    args = parser.parse_args(list(argv) if argv is not None else None)

    import trimesh

    from synlab.fracture.booleans import boolean_intersection, tag_source
    from synlab.fracture.calibrate import (
        body_stats_of, event_rng, load_mother, material_stats_of, scaled_mother,
    )
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.voronoi_event import (
        _displaced_cell_mesh, _matching_facets, _position_of, facet_roughness_field,
    )
    from synlab.fracture.voronoi_frag import build_partition
    from synlab.mothers.api import ensure_registered

    ensure_registered()
    cfg = load_physics_config()
    mother = load_mother(args.vessel, args.material)
    if float(args.scale) != 1.0:
        mother = scaled_mother(mother, float(args.scale))
    body = body_stats_of(mother, args.vessel)
    material = material_stats_of(args.material)
    mesh = mother.mesh
    mother_clean = trimesh.Trimesh(vertices=np.asarray(mesh.vertices, dtype=np.float64),
                                   faces=np.asarray(mesh.faces, dtype=np.int64), process=False)
    mother_source = tag_source(mother_clean, 1.0, "mother")
    payload: dict = {
        "schema": "synlab.fracture_calibration.volume_accounting.v1",
        "vessel_id": args.vessel, "material_id": args.material, "scale": float(args.scale),
        "mother_volume_mm3": float(abs(mesh.volume)), "wall_mm": float(body.wall_mm), "rows": [],
    }
    out = Path(args.out)
    for count in [int(x) for x in str(args.counts).split(",") if x.strip()]:
        partition, _seed = build_partition(mesh, count, rng=event_rng(), seed_cfg=cfg.seeds,
                                           padding_mm=2.0)
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
        rows = []
        started = time.perf_counter()
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
            cutter = tag_source(trimesh.Trimesh(
                vertices=np.asarray(cm.vertices, dtype=np.float64),
                faces=np.asarray(cm.faces, dtype=np.int64), process=False),
                1000.0 + position, "cell")
            t0 = time.perf_counter()
            tagged = boolean_intersection([mother_source, cutter], label=f"vol_{position}")
            rows.append({
                "cell": position,
                "cutter_faces": int(len(np.asarray(cm.faces))),
                "cutter_closed": bool(cm.is_watertight),
                "cutter_positive": bool(cm.is_volume),
                "cutter_volume_mm3": float(abs(np.asarray(cm.volume))),
                "piece_faces": int(tagged.n_faces),
                "piece_volume_mm3": float(abs(tagged.mesh.volume)),
                "boolean_s": round(time.perf_counter() - t0, 4),
            })
        total = float(sum(r["piece_volume_mm3"] for r in rows))
        row = {
            "target_pieces": int(count), "cells": int(len(partition.cells)),
            "sum_piece_mm3": total,
            "volume_rel_diff": float(abs(total - payload["mother_volume_mm3"])
                                     / max(payload["mother_volume_mm3"], 1e-12)),
            "empty_cells": [r["cell"] for r in rows if r["piece_volume_mm3"] <= 1e-9],
            "open_cutters": [r["cell"] for r in rows if not r["cutter_closed"]],
            "open_and_empty": [r["cell"] for r in rows
                               if not r["cutter_closed"] and r["piece_volume_mm3"] <= 1e-9],
            "closed_and_empty": [r["cell"] for r in rows
                                 if r["cutter_closed"] and r["piece_volume_mm3"] <= 1e-9],
            "seconds": round(time.perf_counter() - started, 3),
            "cells_detail": rows,
        }
        payload["rows"].append(row)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        print(f"N={count}: cells={row['cells']} sum={total:.1f} "
              f"({row['volume_rel_diff']:.4f} off mother) open={len(row['open_cutters'])} "
              f"empty={len(row['empty_cells'])} open&empty={len(row['open_and_empty'])} "
              f"closed&empty={len(row['closed_and_empty'])} {row['seconds']:.2f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
