"""Probe: Voronoi partition on a real mother (cells watertight, conjugate, timing)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "_frac_probe_partition.json"


def main() -> int:
    from synlab.mothers.api import create_mother, default_params, ensure_registered
    from synlab.fracture.voronoi_frag import (
        SeedConfig, build_partition, cell_mesh_stats, facet_conjugacy_report,
        partition_size_law,
    )

    ensure_registered()
    vessel = sys.argv[1] if len(sys.argv) > 1 else "V01"
    counts = [int(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else ["4"])]
    material = sys.argv[3] if len(sys.argv) > 3 else "M01"

    mother = create_mother(vessel, material, default_params(vessel),
                           np.random.default_rng(20261002))
    mesh = mother.mesh
    print(f"{vessel}/{material} faces={len(mesh.faces)} vol={abs(mesh.volume):.1f} "
          f"extents={np.round(mesh.extents, 2).tolist()}", flush=True)

    out: dict = {"vessel": vessel, "material": material,
                 "faces": int(len(mesh.faces)), "volume_mm3": float(abs(mesh.volume)),
                 "runs": []}
    for count in counts:
        t0 = time.perf_counter()
        rng = np.random.default_rng(7)
        partition, seed_report = build_partition(
            mesh, count, rng=rng, seed_cfg=SeedConfig(), impact_point=None, padding_mm=2.0)
        t_build = time.perf_counter() - t0
        t1 = time.perf_counter()
        stats = cell_mesh_stats(partition.cells)
        t_mesh = time.perf_counter() - t1
        conjugacy = facet_conjugacy_report(partition)
        law = partition_size_law(partition)
        faces_total = 0
        t2 = time.perf_counter()
        for cell in partition.cells:
            faces_total += len(cell.as_mesh().faces)
        t_dump = time.perf_counter() - t2
        run = {
            "requested": count, "cells": partition.n_cells,
            "dropped_cells": partition.dropped_seeds,
            "t_build_s": round(t_build, 3), "t_cellmesh_s": round(t_mesh, 3),
            "t_meshdump_s": round(t_dump, 3),
            "cell_faces_total": int(faces_total),
            "stats": stats, "conjugacy": conjugacy, "law": law,
            "seed_report": {k: v for k, v in seed_report.items() if k != "seed_config"},
        }
        out["runs"].append(run)
        print(f"  N={count}: cells={partition.n_cells} dropped={partition.dropped_seeds} "
              f"build={t_build:.2f}s cells_faces={faces_total} conj={conjugacy['conjugate']} "
              f"maxvert={conjugacy['max_vertex_distance_mm']:.2e} "
              f"wt={stats['watertight']}/{stats['cells']} Vol={law['volume_total_mm3']:.1f}",
              flush=True)

    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
