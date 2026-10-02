"""Root-cause probe: non-watertight Voronoi cell cutters vs the volume a partition delivers.

For a piece count the cell mesh that the event feeds to the boolean must be a closed positive
solid; when it is not, the boolean returns nothing for that cell and the mother loses exactly that
cell's material.  This probe builds the event's own fields (same public functions, same seed
sequence) and reports, per cell, whether the discretised cutter is watertight -- the mechanism
behind a ``volume_rel_diff`` failure, as a measured per-cell indicator rather than an inference.

It also checks the *padding* term of the partition bounds, which is the only free numeric input on
this path.
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
SWEEP = (2, 3, 4, 6, 8, 12, 16)


def _cells_report(partition, config, body, material) -> list[dict]:
    from synlab.fracture.voronoi_event import (
        _displaced_cell_mesh, _matching_facets, _position_of, facet_roughness_field,
    )

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
            fields[key] = facet_roughness_field(cell, other, pair[0], config=config,
                                                wall_mm=body.wall_mm,
                                                grain_mm=material.grain_size_mm, seed=0)
    rows = []
    for position, cell in enumerate(partition.cells):
        own = {}
        for facet_index, neighbour in enumerate(cell.facet_neighbours):
            if neighbour < 0:
                continue
            key = (min(int(cell.index), int(neighbour)), max(int(cell.index), int(neighbour)))
            if key in fields:
                own[facet_index] = fields[key]
        cm = _displaced_cell_mesh(cell, own, refinement=config.roughness.facet_refinement,
                                  refine_mm=config.roughness.facet_refine_mm)
        rows.append({
            "cell": position,
            "facets": int(len(cell.facet_neighbours)),
            "shared_facets": int(len(own)),
            "faces": int(len(np.asarray(cm.faces))),
            "watertight": bool(cm.is_watertight),
            "positive": bool(cm.is_volume),
            "volume_mm3": float(abs(np.asarray(cm.volume))),
        })
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V01")
    parser.add_argument("--material", default="M01")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--out", default=str(REPORT_DIR / "fracture_cell_watertightness.json"))
    args = parser.parse_args(list(argv) if argv is not None else None)

    from synlab.fracture.calibrate import body_stats_of, load_mother, material_stats_of, \
        event_rng, scaled_mother
    from synlab.fracture.physics import load_physics_config
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
    payload: dict = {
        "schema": "synlab.fracture_calibration.cell_watertightness.v1",
        "vessel_id": args.vessel, "material_id": args.material, "scale": float(args.scale),
        "mother_volume_mm3": float(abs(mesh.volume)),
        "wall_mm": float(body.wall_mm), "rows": [],
    }
    out = Path(args.out)
    cell_meshes_all = {}
    for count in SWEEP:
        started = time.perf_counter()
        partition, _seed = build_partition(mesh, int(count), rng=event_rng(),
                                           seed_cfg=cfg.seeds, padding_mm=2.0)
        cells = _cells_report(partition, cfg, body, material)
        row = {
            "target_pieces": int(count), "partition_s": round(time.perf_counter() - started, 4),
            "cells": int(len(partition.cells)),
            "not_watertight": [c["cell"] for c in cells if not c["watertight"]],
            "n_not_watertight": int(sum(1 for c in cells if not c["watertight"])),
            "not_positive": [c["cell"] for c in cells if not c["positive"]],
            "cells_detail": cells,
        }
        payload["rows"].append(row)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        print(f"N={count}: cells={row['cells']} non-watertight={row['n_not_watertight']} "
              f"at {row['not_watertight']} ({row['partition_s']:.3f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
