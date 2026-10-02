"""Audit matrix: physically constrained multi-piece fracture on real mothers.

Runs, in ONE process (the host kills heavy multi-process work):

* the piece-count law on every (vessel, material) pair -- N is a physics output, not an input;
* a full event there, with the A06 audit, the conjugate/facet evidence and the energy ledger;
* the efficiency sweep: 1 / 4 / 8 / 16 / 32 pieces per vessel, with per-stage timings;
* the plane two-piece baseline for the comparison table.

Every result is appended to the report file after each step, so a killed process still leaves
the measurements it had already taken.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "a12" / "reports" / "fracture_physics_audit.json"
VESSELS = ("V01", "V02", "V13")
MATERIALS = ("M01", "M04")
SWEEP = (1, 4, 8, 16, 32)


def _stats(profile: dict) -> dict:
    return dict(profile.get("stats") or {})


def _body(mother, thickness, vessel: str):
    from synlab.fracture.impact import BodyStats

    mesh = mother.mesh
    return BodyStats(
        vessel_id=vessel, volume_mm3=float(abs(mesh.volume)), area_mm2=float(mesh.area),
        extents_mm=tuple(float(x) for x in mesh.extents),
        thickness_min_mm=float(thickness.get("min_mm", 0.0) or 0.0),
        thickness_p05_mm=float(thickness.get("p05_mm", 0.0) or 0.0),
        thickness_median_mm=float(thickness.get("median_mm", 0.0) or 0.0),
        thickness_max_mm=float(thickness.get("max_mm", 0.0) or 0.0),
    )


def _material(material_id: str, stats: dict):
    from synlab.fracture.impact import MaterialStats

    def pick(*names, default=0.0):
        for name in names:
            value = stats.get(name)
            if isinstance(value, (int, float)):
                return float(value)
        return float(default)

    return MaterialStats(
        material_id=material_id,
        density_g_cm3=pick("density_g_cm3", "density", "bulk_density_g_cm3", default=2.2),
        porosity=pick("porosity", "porosity_fraction"),
        grain_size_mm=pick("grain_size_mm", "grain_mm", "grain_scale_mm",
                           "median_grain_mm", default=0.05),
    )


def _summary(result, elapsed: float) -> dict:
    qa = result.qa
    patches = [p for p in result.interfaces if p.sample_points_a.shape[0]]
    return {
        "pieces": len(result.fragments),
        "interfaces": len(result.interfaces),
        "empty_interfaces": len(result.interfaces) - len(patches),
        "faces_total": int(sum(f.n_faces for f in result.fragments)),
        "cells_total": int(result.meta.get("cells_total", len(result.fragments))),
        "dropped_cells": result.meta.get("dropped_cells", []),
        "target_pieces": int(result.meta.get("target_pieces", len(result.fragments))),
        "count_source": result.meta.get("count_source", "n/a (plane baseline)"),
        "volume_rel_diff": float(qa["volume_rel_diff"]),
        "gap_p95_mm_max": float(qa["gap_p95_mm_max"]),
        "normal_p95_deg_max": float(qa["normal_angle_p95_deg_max"]),
        "source_coverage": float(qa["source_coverage"]),
        "ambiguous_area_ratio_total": float(qa["ambiguous_area_ratio_total"]),
        "conjugacy": result.meta.get("facet_conjugacy", {}),
        "unmatched_interface_area_mm2": float(
            result.meta.get("unmatched_interface_area_mm2", float("nan"))),
        "unmatched_interface_area_ratio": float(
            result.meta.get("unmatched_interface_area_ratio", float("nan"))),
        "vertex_identity_min": float(min(
            (p.meta.get("vertex_identity_ratio", 0.0) for p in patches), default=0.0)),
        "nearest_p95_mm_max": float(max(
            (p.meta.get("nearest_p95_mm", 0.0) for p in patches), default=0.0)),
        "qa_passed": bool(qa["passed"]),
        "qa_failures": list(qa["failures"]),
        "seconds": round(elapsed, 3),
        "piece_volumes_mm3": [float(f.volume_mm3) for f in result.fragments],
        "piece_faces": [int(f.n_faces) for f in result.fragments],
        "count_model": result.meta.get("count_model", {}),
        "energy_ledger": result.meta.get("energy_ledger", {}),
        "seed_report": {k: v for k, v in (result.meta.get("seed_report") or {}).items()
                        if k != "seed_config"},
    }


def _piece_size_law(result, mother_volume_mm3: float) -> dict:
    volumes = np.asarray([f.volume_mm3 for f in result.fragments], dtype=np.float64)
    if volumes.size == 0:
        return {}
    equivalent = (6.0 * volumes / np.pi) ** (1.0 / 3.0)
    return {
        "n": int(volumes.size),
        "volume_min_mm3": float(volumes.min()),
        "volume_median_mm3": float(np.median(volumes)),
        "volume_max_mm3": float(volumes.max()),
        "diameter_min_mm": float(equivalent.min()),
        "diameter_median_mm": float(np.median(equivalent)),
        "diameter_max_mm": float(equivalent.max()),
        "size_ratio": float(volumes.max() / max(volumes.min(), 1e-12)),
        "mother_volume_mm3": float(mother_volume_mm3),
    }


def main() -> int:
    from synlab.mothers.api import create_mother, default_params, ensure_registered
    from synlab.mothers.measure import thickness_samples
    from synlab.materials.api import build_material_profile, default_material_params
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.voronoi_event import run_voronoi_event
    from synlab.fracture.api import fracture_event
    from synlab.fracture.spec import FractureSpec
    from synlab.errors import SynLabError

    ensure_registered()
    config = load_physics_config()
    report: dict = {
        "schema": "synlab.fracture_physics.audit.v1",
        "config_path": config.path, "config_hash": config.hash,
        "config": config.as_dict(),
        "vessels": {}, "plane_baseline": {}, "notes": [
            "all numbers are measured on this host in this run",
            "count_source=physics means the piece count came from the law; explicit_override is "
            "the efficiency sweep and is recorded as such",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    for material_id in MATERIALS:
        profile = build_material_profile(material_id, default_material_params(material_id),
                                         np.random.default_rng(11))
        stats = _stats(profile)
        for vessel in VESSELS:
            key = f"{vessel}_{material_id}"
            entry: dict = {"vessel": vessel, "material": material_id,
                           "material_stats": {k: v for k, v in stats.items()
                                              if isinstance(v, (int, float, str))}}
            mother = create_mother(vessel, material_id, default_params(vessel),
                                   np.random.default_rng(20261002))
            thickness = thickness_samples(mother.mesh, np.arange(len(mother.mesh.faces)),
                                          max_probes=320)
            entry["thickness"] = {k: v for k, v in thickness.items()
                                  if isinstance(v, (int, float, str, bool))}
            body = _body(mother, thickness, vessel)
            material = _material(material_id, stats)
            entry["body"] = body.as_dict()
            entry["material"] = material.as_dict()
            # ---- one physics-count event
            try:
                start = time.perf_counter()
                result = run_voronoi_event(mother, event_id=f"AUD-{key}", config=config,
                                           rng=np.random.default_rng(20261002), body=body,
                                           material=material)
                elapsed = time.perf_counter() - start
                entry["physics_event"] = _summary(result, elapsed)
                entry["physics_event"]["size_law"] = _piece_size_law(result, abs(mother.mesh.volume))
            except SynLabError as exc:
                entry["physics_event"] = {"error": str(exc), "code": str(exc.code)}
            # ---- plane two-piece baseline
            try:
                start = time.perf_counter()
                baseline = fracture_event(mother, FractureSpec(backend="plane_shared_cut"),
                                          np.random.default_rng(20261002),
                                          event_id=f"BASE-{key}")
                elapsed = time.perf_counter() - start
                entry["plane_baseline"] = _summary(baseline, elapsed)
                entry["plane_baseline"]["size_law"] = _piece_size_law(baseline, abs(mother.mesh.volume))
            except SynLabError as exc:
                entry["plane_baseline"] = {"error": str(exc), "code": str(exc.code)}
            report["vessels"][key] = entry
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(f"{key}: physics={entry['physics_event'].get('pieces')} pieces, "
                  f"plane={entry['plane_baseline'].get('pieces')} pieces", flush=True)

    # ---- efficiency sweep
    sweep_report: dict = {}
    for vessel in VESSELS:
        material_id = MATERIALS[0]
        profile = build_material_profile(material_id, default_material_params(material_id),
                                         np.random.default_rng(11))
        stats = _stats(profile)
        mother = create_mother(vessel, material_id, default_params(vessel),
                               np.random.default_rng(20261002))
        thickness = thickness_samples(mother.mesh, np.arange(len(mother.mesh.faces)),
                                      max_probes=320)
        body = _body(mother, thickness, vessel)
        material = _material(material_id, stats)
        runs = []
        for count in SWEEP:
            try:
                start = time.perf_counter()
                result = run_voronoi_event(mother, event_id=f"SW-{vessel}-{count}",
                                           config=config, rng=np.random.default_rng(2024),
                                           body=body, material=material,
                                           target_pieces=count)
                elapsed = time.perf_counter() - start
                summary = _summary(result, elapsed)
                summary["size_law"] = _piece_size_law(result, abs(mother.mesh.volume))
                summary["configured_impact_speed_mm_s"] = float(
                    summary["count_model"]["impact_speed_mm_s"])
                runs.append(summary)
                print(f"  sweep {vessel} N={count}: pieces={summary['pieces']} "
                      f"faces={summary['faces_total']} {elapsed:.2f}s", flush=True)
            except SynLabError as exc:
                runs.append({"target_pieces": count, "error": str(exc), "code": str(exc.code)})
                print(f"  sweep {vessel} N={count}: REFUSED {exc.code}", flush=True)
            sweep_report.setdefault(vessel, []).append(runs[-1])
            report["efficiency_sweep"] = sweep_report
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
