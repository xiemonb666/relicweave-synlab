"""Focused diagnostic at N=8: cutter volume vs piece volume, per cell, as the event sees it."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "a12_reports" / "_fcal_diag_n8.json"


def main() -> int:
    import trimesh

    from synlab.fracture.booleans import boolean_intersection, tag_source
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.voronoi_event import _displaced_cell_mesh, run_voronoi_event
    from synlab.fracture.voronoi_frag import build_partition
    from synlab.fracture.calibrate import body_stats_of, load_mother, material_stats_of

    cfg = load_physics_config()
    mother = load_mother("V01", "M01")
    body = body_stats_of(mother, "V01")
    material = material_stats_of("M01")
    mesh = mother.mesh
    report: dict = {"mother_volume_mm3": float(abs(mesh.volume))}
    partition, seed_report = build_partition(mesh, 8, rng=np.random.default_rng(20261002),
                                            seed_cfg=cfg.seeds, padding_mm=2.0)
    mother_clean = trimesh.Trimesh(vertices=np.asarray(mesh.vertices, dtype=np.float64),
                                   faces=np.asarray(mesh.faces, dtype=np.int64), process=False)
    mother_source = tag_source(mother_clean, 1.0, "mother")
    rows = []
    for position, cell in enumerate(partition.cells):
        cm = _displaced_cell_mesh(cell, {}, refinement=cfg.roughness.facet_refinement,
                                  refine_mm=cfg.roughness.facet_refine_mm)
        cutter = tag_source(trimesh.Trimesh(
            vertices=np.asarray(cm.vertices, dtype=np.float64),
            faces=np.asarray(cm.faces, dtype=np.int64), process=False), 1000.0 + position, "cell")
        tagged = boolean_intersection([mother_source, cutter], label=f"probe_{position}")
        rows.append({
            "cell": position,
            "cell_seed_index": int(cell.index),
            "cutter_faces": int(len(np.asarray(cm.faces))),
            "cutter_volume_mm3": float(abs(np.asarray(cm.volume))),
            "cutter_watertight": bool(cm.is_watertight),
            "cutter_positive": bool(cm.is_volume),
            "cutter_bounds": [float(x) for x in np.asarray(cm.bounds).reshape(-1)],
            "piece_faces": int(tagged.n_faces),
            "piece_volume_mm3": float(abs(tagged.mesh.volume)),
        })
    report["cells"] = rows
    report["probe_sum_mm3"] = float(sum(r["piece_volume_mm3"] for r in rows))
    report["seed_report"] = {k: v for k, v in seed_report.items() if k != "seed_config"}

    result = run_voronoi_event(mother, event_id="DIAG-N8", config=cfg,
                               rng=np.random.default_rng(20261002), body=body,
                               material=material, target_pieces=8)
    report["event"] = {
        "pieces": len(result.fragments),
        "cells_total": int(result.meta.get("cells_total", 0)),
        "dropped_cells": list(result.meta.get("dropped_cells") or []),
        "fragment_volumes_mm3": [float(f.volume_mm3) for f in result.fragments],
        "fragment_faces": [int(f.n_faces) for f in result.fragments],
        "fragment_watertight": [bool(f.mesh.is_watertight) for f in result.fragments],
        "sum_mm3": float(sum(f.volume_mm3 for f in result.fragments)),
    }
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("probe_sum", report["probe_sum_mm3"], "of", report["mother_volume_mm3"])
    for r in rows:
        print(f"  cell {r['cell']}: cutter_faces={r['cutter_faces']} "
              f"cutterV={r['cutter_volume_mm3']:.1f} wt={r['cutter_watertight']} "
              f"pos={r['cutter_positive']} pieceV={r['piece_volume_mm3']:.1f} "
              f"pieceFaces={r['piece_faces']}")
    print("event", json.dumps(report["event"], indent=1)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
