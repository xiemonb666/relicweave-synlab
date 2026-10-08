"""Probe: one full multi-piece Voronoi fracture event on a real mother + audit table."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from synlab.mothers.api import create_mother, default_params, ensure_registered
    from synlab.mothers.measure import thickness_samples
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.fracture.impact import BodyStats, MaterialStats
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.voronoi_event import run_voronoi_event
    from synlab.errors import SynLabError

    ensure_registered()
    vessel = sys.argv[1] if len(sys.argv) > 1 else "V01"
    material_id = sys.argv[2] if len(sys.argv) > 2 else "M01"
    override = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    out_path = Path(sys.argv[4]) if len(sys.argv) > 4 else ROOT / "_frac_probe_event.json"

    config = load_physics_config()
    mother = create_mother(vessel, material_id, default_params(vessel),
                           np.random.default_rng(20261002))
    mesh = mother.mesh
    thickness = thickness_samples(mesh, np.arange(len(mesh.faces)), max_probes=320)
    profile = build_material_profile(material_id, default_material_params(material_id),
                                     np.random.default_rng(11))
    stats = profile.get("stats", {})

    def _stat(*names: str, default: float = 0.0) -> float:
        for name in names:
            value = stats.get(name)
            if isinstance(value, (int, float)):
                return float(value)
        return default

    body = BodyStats(
        vessel_id=vessel, volume_mm3=float(abs(mesh.volume)), area_mm2=float(mesh.area),
        extents_mm=tuple(float(x) for x in mesh.extents),
        thickness_min_mm=float(thickness.get("min_mm", 0.0) or 0.0),
        thickness_p05_mm=float(thickness.get("p05_mm", 0.0) or 0.0),
        thickness_median_mm=float(thickness.get("median_mm", 0.0) or 0.0),
        thickness_max_mm=float(thickness.get("max_mm", 0.0) or 0.0),
    )
    material = MaterialStats(
        material_id=material_id,
        density_g_cm3=_stat("density_g_cm3", "density", "bulk_density_g_cm3", default=2.2),
        porosity=_stat("porosity", "porosity_fraction"),
        grain_size_mm=_stat("grain_size_mm", "grain_mm", "median_grain_mm", default=0.05),
    )

    t0 = time.perf_counter()
    try:
        result = run_voronoi_event(
            mother, event_id=f"FRACPROBE-{vessel}-{material_id}", config=config,
            rng=np.random.default_rng(2024), body=body, material=material,
            target_pieces=(override or None))
    except SynLabError as exc:
        payload = {"vessel": vessel, "material": material_id, "status": "REFUSED",
                   "code": exc.code.value if hasattr(exc.code, "value") else str(exc.code),
                   "message": str(exc), "measurements": exc.measurements}
        out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print("REFUSED", payload["code"], payload["message"][:300], flush=True)
        print("measurements", json.dumps(payload["measurements"], default=str)[:1200], flush=True)
        return 2
    elapsed = time.perf_counter() - t0

    qa = result.qa
    gaps = [p.gap_p95_mm for p in result.interfaces if p.sample_points_a.shape[0]]
    angles = [p.normal_angle_p95_deg for p in result.interfaces if p.sample_points_a.shape[0]]
    conj = [p.meta.get("vertex_identity_ratio", 0.0) for p in result.interfaces]
    unmatched = result.meta.get("unmatched_interface_area_mm2", float("nan"))
    payload = {
        "vessel": vessel, "material": material_id, "status": "OK",
        "elapsed_s": round(elapsed, 3),
        "target_pieces": result.meta["target_pieces"],
        "count_source": result.meta["count_source"],
        "pieces": len(result.fragments),
        "interfaces": len(result.interfaces),
        "faces_total": result.meta["faces_total"],
        "cell_faces_total": result.meta["cell_faces_total"],
        "cells_total": result.meta["cells_total"],
        "dropped_cells": result.meta["dropped_cells"],
        "volume_rel_diff": qa["volume_rel_diff"],
        "gap_p95_max": qa["gap_p95_mm_max"],
        "normal_p95_max": qa["normal_angle_p95_deg_max"],
        "source_coverage": qa["source_coverage"],
        "ambiguous_area_ratio_total": qa["ambiguous_area_ratio_total"],
        "conjugacy_max_mm": result.meta["facet_conjugacy"]["max_vertex_distance_mm"],
        "conjugacy_ok": result.meta["facet_conjugacy"]["conjugate"],
        "vertex_identity_min": min(conj) if conj else None,
        "unmatched_interface_area_mm2": unmatched,
        "qa_passed": qa["passed"],
        "qa_failures": qa["failures"],
        "body": body.as_dict(),
        "material": material.as_dict(),
        "count_model": result.meta["count_model"],
        "energy": result.meta["energy_ledger"],
        "piece_volumes_mm3": [float(f.volume_mm3) for f in result.fragments],
        "piece_is_tiny": [bool(f.is_tiny) for f in result.fragments],
        "thickness": {k: v for k, v in thickness.items()
                      if isinstance(v, (int, float, str, bool))},
        "interface_rows": [
            {"id": p.interface_id, "area_mm2": float(p.area_mm2),
             "gap_p95_mm": float(p.gap_p95_mm), "normal_p95_deg": float(p.normal_angle_p95_deg),
             "ambiguity": float(p.ambiguity_area_ratio),
             "vertex_identity": float(p.meta.get("vertex_identity_ratio", 0.0)),
             "nearest_p95_mm": float(p.meta.get("nearest_p95_mm", float("nan"))),
             "facet_pair": p.meta.get("facet_pair"),
             "facet_area_mm2": p.meta.get("facet_area_mm2"),
             "samples": int(p.sample_points_a.shape[0])}
            for p in result.interfaces],
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"{vessel}/{material_id}: pieces={payload['pieces']} interfaces={payload['interfaces']} "
          f"vol_rel={payload['volume_rel_diff']:.3e} gap={payload['gap_p95_max']:.5f} "
          f"norm={payload['normal_p95_max']:.5f} conj={payload['conjugacy_ok']} "
          f"faces={payload['faces_total']} t={elapsed:.1f}s qa={payload['qa_passed']}",
          flush=True)
    if payload["qa_failures"]:
        print("  failures:", payload["qa_failures"], flush=True)
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
