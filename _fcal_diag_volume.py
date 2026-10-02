"""Diagnostic: where does the volume go at higher piece counts (probe vs real event)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "a12_reports" / "_fcal_diag_volume.json"


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
    report: dict = {"mother_volume_mm3": float(abs(mesh.volume)), "rows": []}
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")

    for n in (4, 8, 16, 32):
        partition, seed_report = build_partition(mesh, n, rng=np.random.default_rng(20261002),
                                                 seed_cfg=cfg.seeds, padding_mm=2.0)
        cell_meshes = [_displaced_cell_mesh(c, {}, refinement=cfg.roughness.facet_refinement,
                                            refine_mm=cfg.roughness.facet_refine_mm)
                       for c in partition.cells]
        mother_clean = trimesh.Trimesh(vertices=np.asarray(mesh.vertices, dtype=np.float64),
                                       faces=np.asarray(mesh.faces, dtype=np.int64),
                                       process=False)
        mother_source = tag_source(mother_clean, 1.0, "mother")
        probe_vols = []
        for position, cm in enumerate(cell_meshes):
            cutter = tag_source(trimesh.Trimesh(
                vertices=np.asarray(cm.vertices, dtype=np.float64),
                faces=np.asarray(cm.faces, dtype=np.int64), process=False),
                1000.0 + position, "cell")
            tagged = boolean_intersection([mother_source, cutter], label=f"probe_{position}")
            probe_vols.append({"faces": int(len(np.asarray(cm.faces))),
                               "cutter_volume_mm3": float(abs(cm.volume)) if cm.is_volume
                               else float(abs(cm.volume)),
                               "cutter_watertight": bool(cm.is_watertight),
                               "piece_faces": int(tagged.n_faces),
                               "piece_volume_mm3": float(abs(tagged.mesh.volume))})
        row: dict = {"target_pieces": n, "cells": int(len(partition.cells)),
                     "probe_sum_mm3": float(sum(p["piece_volume_mm3"] for p in probe_vols)),
                     "probe": probe_vols}
        # real event for the same count
        try:
            result = run_voronoi_event(mother, event_id=f"DIAG-{n}", config=cfg,
                                       rng=np.random.default_rng(20261002), body=body,
                                       material=material, target_pieces=n)
            row["event_pieces"] = len(result.fragments)
            row["event_volumes_mm3"] = [float(f.volume_mm3) for f in result.fragments]
            row["event_sum_mm3"] = float(sum(f.volume_mm3 for f in result.fragments))
            row["event_faces"] = [int(f.n_faces) for f in result.fragments]
            row["event_intact_pieces"] = int(sum(1 for f in result.fragments
                                                 if bool(f.mesh.is_watertight)))
            row["event_dropped"] = list(result.meta.get("dropped_cells") or [])
            row["cells_total"] = int(result.meta.get("cells_total", 0))
            row["event_interfaces"] = len(result.interfaces)
        except Exception as exc:  # noqa: BLE001
            row["event_failure"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        report["rows"].append(row)
        OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"N={n}: probe_sum={row['probe_sum_mm3']:.0f} "
              f"({row['probe_sum_mm3'] / report['mother_volume_mm3']:.4f}) "
              f"event_sum={row.get('event_sum_mm3', float('nan')):.0f} "
              f"pieces={row.get('event_pieces')} intact={row.get('event_intact_pieces')} "
              f"dropped={row.get('event_dropped')} err={row.get('event_failure', '')[:80]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
