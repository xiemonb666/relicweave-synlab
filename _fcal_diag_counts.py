"""Minimal check: how many fragments does a real N=8 / N=6 event produce, and do they sum?"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "a12_reports" / "_fcal_diag_counts.json"


def main() -> int:
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.voronoi_event import run_voronoi_event
    from synlab.fracture.calibrate import body_stats_of, load_mother, material_stats_of

    cfg = load_physics_config()
    mother = load_mother("V01", "M01")
    body = body_stats_of(mother, "V01")
    material = material_stats_of("M01")
    report: dict = {"mother_volume_mm3": float(abs(mother.mesh.volume)), "rows": []}
    for n in (6, 8):
        result = run_voronoi_event(mother, event_id=f"CHK-{n}", config=cfg,
                                   rng=np.random.default_rng(20261002), body=body,
                                   material=material, target_pieces=n)
        row = {
            "target": n,
            "cells_total": int(result.meta.get("cells_total", 0)),
            "records": int(result.meta.get("pieces_produced", 0)),
            "dropped_cells": list(result.meta.get("dropped_cells") or []),
            "fragments": len(result.fragments),
            "interfaces": len(result.interfaces),
            "fragment_ids": [f.fragment_id for f in result.fragments],
            "cell_indices": [int(f.meta.get("voronoi_cell", -1)) for f in result.fragments],
            "volumes": [float(f.volume_mm3) for f in result.fragments],
            "faces": [int(f.n_faces) for f in result.fragments],
            "watertight": [bool(f.mesh.is_watertight) for f in result.fragments],
            "volume_sum": float(sum(f.volume_mm3 for f in result.fragments)),
            "qa_passed": bool(result.qa.get("passed")),
            "qa_volume_rel": float(result.qa.get("volume_rel_diff", float("nan"))),
        }
        report["rows"].append(row)
        OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"target={n}: cells={row['cells_total']} fragments={row['fragments']} "
              f"dropped={row['dropped_cells']} sum={row['volume_sum']:.1f} "
              f"mother={report['mother_volume_mm3']:.1f} cells_of_frags={row['cell_indices']} "
              f"wt={row['watertight']}", flush=True)
        print("   volumes", [round(v, 1) for v in row["volumes"]], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
