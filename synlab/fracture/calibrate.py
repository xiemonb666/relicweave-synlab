"""Quantitative calibration of the piece-count law (measurement instrument, no assertions).

This module is the *measuring* half of the calibration in ``docs/a12/fracture_calibration.md``.
It contains no thresholds and no test assertions; it runs the real ``warp_voronoi_cut`` event on
real mothers and writes every number it read to ``data/a12_reports/``.  The rules it follows:

* one mother per process step (this host kills heavy processes), and the report file is rewritten
  after **every** measured row, so a killed run still leaves the rows it had already taken;
* ``count_source=physics`` rows are measurements of the *declared* law; ``explicit_override`` rows
  are the N-sweep and are never mixed into the fit (they are recorded as such);
* a refused event (``SynLabError``) is written down as a refusal with its code and measurements
  instead of being dropped or retried until it passes;
* the event draws one log-normal (Weibull) factor from the caller's rng *before* it partitions, so
  every probe here draws that factor too -- a probe that skipped it would build a different
  partition and would not be measuring the same event.

Usage (repository root):

```powershell
& .venv\\Scripts\\python.exe -m synlab.fracture.calibrate matrix --out data\\a12_reports\\fracture_calibration_matrix.json
& .venv\\Scripts\\python.exe -m synlab.fracture.calibrate energy --out data\\a12_reports\\fracture_calibration_energy.json
& .venv\\Scripts\\python.exe -m synlab.fracture.calibrate size   --out data\\a12_reports\\fracture_calibration_size.json
& .venv\\Scripts\\python.exe -m synlab.fracture.calibrate stage  --out data\\a12_reports\\fracture_calibration_stage_V01.json
```
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np

__all__ = [
    "body_stats_of",
    "material_stats_of",
    "measure_one",
    "measure_matrix",
    "summarize_result",
    "stage_probe",
    "count_fit",
    "monotonicity_check",
    "event_rng",
    "fit_size_law",
    "fit_energy_law",
]

#: drop heights (mm) of the energy series: 0.1 / 0.25 / 0.5 / 1 / 2 / 4 m of free fall
DROP_HEIGHTS_MM: tuple[float, ...] = (100.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0)
#: efficiency sweep of the task: 1 / 4 / 8 / 16 / 32 pieces
PIECE_SWEEP: tuple[int, ...] = (1, 4, 8, 16, 32)
#: vessels of the size series (small -> large), one material at a fixed drop height
SIZE_VESSELS: tuple[str, ...] = ("V02", "V01", "V13")
#: materials of the material series (M04 is the fine-grained / stronger body)
SWEEP_MATERIALS: tuple[str, ...] = ("M01", "M04")
MASTER_SEED = 20261002


def _jsonable(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return f"<{type(value).__name__}>"
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v, depth=depth + 1) for v in value]
    if isinstance(value, np.ndarray):
        flat = value.reshape(-1)
        if flat.size == 0:
            return {"shape": list(value.shape), "empty": True}
        if flat.dtype.kind in "fiub":
            return {"shape": list(value.shape), "min": float(np.min(flat)),
                    "max": float(np.max(flat))}
        return {"shape": list(value.shape), "dtype": str(flat.dtype)}
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_flat(payload), indent=1, ensure_ascii=False), encoding="utf-8")


def _flat(value: Any) -> Any:
    """JSON-safe copy that never replaces a number with a ``<type>`` placeholder."""
    if isinstance(value, dict):
        return {str(k): _flat(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_flat(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def event_rng(seed: int = MASTER_SEED, log_sigma: float = 0.18) -> np.random.Generator:
    """The rng state the event partitions with, for a caller that has already made its draw.

    ``run_voronoi_event`` draws exactly one value (the log-normal count factor) from the caller's
    rng before ``build_partition`` sees it.  A probe that wants the *same* partition must burn that
    draw first; otherwise it measures a different event.  This is a measurement detail, not a
    physics one, and it is the reason a naive re-implementation of the event's first stages does
    not reproduce its cells.
    """
    rng = np.random.default_rng(int(seed))
    rng.normal(0.0, float(log_sigma))
    return rng


# ---------------------------------------------------------------------------- inputs
def load_mother(vessel_id: str, material_id: str, *, seed: int = MASTER_SEED) -> Any:
    from synlab.mothers.api import create_mother, default_params, ensure_registered

    ensure_registered()
    return create_mother(vessel_id, material_id, default_params(vessel_id),
                         np.random.default_rng(seed))


def body_stats_of(mother: Any, vessel_id: str) -> Any:
    """Measured geometry statistics of one mother (median wall thickness included)."""
    from synlab.fracture.impact import BodyStats
    from synlab.mothers.measure import thickness_samples

    mesh = mother.mesh
    faces = np.arange(len(mesh.faces))
    stride = max(1, int(faces.size // 400))
    thickness = thickness_samples(mesh, faces[::stride], max_probes=400)
    return BodyStats(
        vessel_id=vessel_id, volume_mm3=float(abs(mesh.volume)), area_mm2=float(mesh.area),
        extents_mm=tuple(float(x) for x in mesh.extents),
        thickness_min_mm=float(thickness.get("min_mm", 0.0) or 0.0),
        thickness_p05_mm=float(thickness.get("p05_mm", 0.0) or 0.0),
        thickness_median_mm=float(thickness.get("median_mm", 0.0) or 0.0),
        thickness_max_mm=float(thickness.get("max_mm", 0.0) or 0.0),
        outer_area_mm2=float(mesh.area),
    )


def material_stats_of(material_id: str) -> Any:
    """Material statistics as the pipeline builds them (profile stats, measured density wins)."""
    from synlab.fracture.impact import MaterialStats
    from synlab.materials.api import build_material_profile, default_material_params

    profile = build_material_profile(material_id, default_material_params(material_id),
                                     np.random.default_rng(11))
    stats = profile.get("stats") or {}

    def pick(*names: str, default: float = 0.0) -> float:
        for name in names:
            value = stats.get(name)
            if isinstance(value, (int, float)):
                return float(value)
        return float(default)

    return MaterialStats(
        material_id=material_id,
        density_g_cm3=pick("density_g_cm3", "density", "bulk_density_g_cm3", default=2.2),
        porosity=pick("porosity", "porosity_fraction"),
        grain_size_mm=pick("grain_size_mm", "grain_mm", "median_grain_mm", default=0.05),
    )


# ---------------------------------------------------------------------------- measurement
def summarize_result(result: Any, mother: Any, elapsed_s: float) -> dict[str, Any]:
    """Everything the audit table needs, straight off the event (no recomputation)."""
    qa = dict(result.qa)
    patches = [p for p in result.interfaces if np.asarray(p.sample_points_a).shape[0] > 0]
    conjugacy = dict(result.meta.get("facet_conjugacy") or {})
    vertex_identity = [float(p.meta.get("vertex_identity_ratio", 0.0)) for p in patches]
    nearest_p95 = [float(p.meta.get("nearest_p95_mm", float("nan"))) for p in patches]
    nearest_max = [float(p.meta.get("nearest_max_mm", float("nan"))) for p in patches]
    unmatched_area = float(result.meta.get("unmatched_interface_area_mm2", 0.0) or 0.0)
    matched_area = float(sum(float(p.area_mm2) for p in result.interfaces))
    volumes = np.asarray([float(f.volume_mm3) for f in result.fragments], dtype=np.float64)
    return {
        "pieces": int(len(result.fragments)),
        "tiny_pieces": int(sum(1 for f in result.fragments if f.is_tiny)),
        "interfaces": int(len(result.interfaces)),
        "interfaces_with_samples": int(len(patches)),
        "faces_total": int(sum(int(f.n_faces) for f in result.fragments)),
        "cells_total": int(result.meta.get("cells_total", len(result.fragments))),
        "dropped_cells": list(result.meta.get("dropped_cells") or []),
        "open_cutters": list(result.meta.get("open_cutters") or []),
        "open_cutter_count": int(result.meta.get("open_cutter_count", 0) or 0),
        "closed_but_empty_cells": list(result.meta.get("closed_but_empty_cells") or []),
        "target_pieces": int(result.meta.get("target_pieces", len(result.fragments))),
        "count_source": str(result.meta.get("count_source", "")),
        "seconds": round(float(elapsed_s), 3),
        # --- A06 audit block (verbatim from synlab.fracture.fragment.audit_fracture_result)
        "volume_rel_diff": float(qa.get("volume_rel_diff", float("nan"))),
        "volume_tolerance": float(qa.get("volume_tolerance", float("nan"))),
        "overlap_ratio": float(qa.get("overlap_ratio", float("nan"))),
        "overlap_tolerance": float(qa.get("overlap_tolerance", float("nan"))),
        "gap_p95_mm_max": float(qa.get("gap_p95_mm_max", float("nan"))),
        "gap_tolerance_mm": float(qa.get("gap_tolerance_mm", float("nan"))),
        "normal_angle_p95_deg_max": float(qa.get("normal_angle_p95_deg_max", float("nan"))),
        "normal_angle_tolerance_deg": float(qa.get("normal_angle_tolerance_deg", float("nan"))),
        "source_coverage": float(qa.get("source_coverage", float("nan"))),
        "ambiguous_area_ratio_total": float(qa.get("ambiguous_area_ratio_total", float("nan"))),
        "ambiguity_tolerance": float(qa.get("ambiguity_tolerance", float("nan"))),
        "interface_area_rel_error_max": float(qa.get("interface_area_rel_error_max", 0.0)),
        "qa_passed": bool(qa.get("passed", False)),
        "qa_failures": list(qa.get("failures") or []),
        # --- measured geometry truth of the pieces
        "watertight_pieces": int(sum(1 for f in result.fragments
                                     if bool(f.mesh.is_watertight))),
        "positive_volume_pieces": int(sum(1 for f in result.fragments
                                         if float(f.volume_mm3) > 0.0)),
        "piece_volume_sum_mm3": float(np.sum(volumes)) if volumes.size else 0.0,
        "mother_volume_mm3": float(abs(mother.mesh.volume)),
        "piece_volume_min_mm3": float(np.min(volumes)) if volumes.size else 0.0,
        "piece_volume_max_mm3": float(np.max(volumes)) if volumes.size else 0.0,
        # --- conjugacy (the shared facet is the same vertex set on both sides)
        "facet_conjugacy": conjugacy,
        "conjugate_vertex_distance_p95_mm": (None if not vertex_identity
                                             else float(np.percentile(vertex_identity, 5))),
        "nearest_surface_p95_mm_max": (float(np.nanmax(nearest_p95)) if nearest_p95 else None),
        "nearest_surface_max_mm_max": (float(np.nanmax(nearest_max)) if nearest_max else None),
        "vertex_identity_ratio_min": (float(np.min(vertex_identity)) if vertex_identity else None),
        # --- unmatched interface area (honest extra metric: pairs that could not be matched)
        "unmatched_interface_area_mm2": unmatched_area,
        "matched_interface_area_mm2": matched_area,
        "unmatched_interface_area_ratio": float(
            unmatched_area / max(matched_area + unmatched_area, 1e-12)),
        # --- physics records
        "count_model": dict(result.meta.get("count_model") or {}),
        "energy_ledger": dict(result.meta.get("energy_ledger") or {}),
        "partition_hash": str((result.event_tree or {}).get("partition_hash", "")),
        "cutter_ref": result.cutter_ref,
    }


def measure_one(*, vessel_id: str, material_id: str, drop_height_mm: float | None,
                target_pieces: int | None = None, seed: int = MASTER_SEED,
                mother: Any = None, body: Any = None, material: Any = None,
                config: Any = None) -> dict[str, Any]:
    """Run one ``warp_voronoi_cut`` event and return the measured row (never raises)."""
    from synlab.errors import SynLabError
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.voronoi_event import run_voronoi_event

    cfg = config if config is not None else load_physics_config()
    moth = mother if mother is not None else load_mother(vessel_id, material_id, seed=seed)
    bod = body if body is not None else body_stats_of(moth, vessel_id)
    mat = material if material is not None else material_stats_of(material_id)
    row: dict[str, Any] = {
        "vessel_id": vessel_id, "material_id": material_id,
        "drop_height_mm": None if drop_height_mm is None else float(drop_height_mm),
        "target_pieces_override": target_pieces,
        "body": bod.as_dict(), "material": mat.as_dict(),
        "mother_faces": int(len(moth.mesh.faces)),
    }
    started = time.perf_counter()
    try:
        result = run_voronoi_event(
            moth, event_id=f"FCAL-{vessel_id}-{material_id}-h{drop_height_mm}-n{target_pieces}",
            config=cfg, rng=np.random.default_rng(seed), body=bod, material=mat,
            target_pieces=target_pieces,
            drop_height_mm=(None if drop_height_mm is None else float(drop_height_mm)))
    except SynLabError as exc:
        row["status"] = "REFUSED"
        row["seconds"] = round(time.perf_counter() - started, 3)
        row["failure"] = {
            "code": str(getattr(exc.code, "value", exc.code)), "stage": exc.stage,
            "message": exc.message, "measurements": _jsonable(exc.measurements),
        }
        return row
    except BaseException as exc:  # noqa: BLE001 - the failure itself is a measurement
        row["status"] = "ERROR"
        row["seconds"] = round(time.perf_counter() - started, 3)
        row["failure"] = {"code": type(exc).__name__, "message": str(exc)[:800]}
        return row
    # ``run_voronoi_event`` raises on audit failure, so reaching here means the A06 gate passed;
    # the numbers below are still published so the gate can be checked by the reader.
    row["status"] = "OK"
    row["measurement"] = summarize_result(result, moth, time.perf_counter() - started)
    return row


# ---------------------------------------------------------------------------- series
def matrix_series(drop_height_mm: float = 500.0,
                  vessels: Sequence[str] = SIZE_VESSELS,
                  materials: Sequence[str] = SWEEP_MATERIALS,
                  *, seed: int = MASTER_SEED) -> list[dict[str, Any]]:
    """Vessel x material matrix at one drop height, one process step per row."""
    rows: list[dict[str, Any]] = []
    for material_id in materials:
        for vessel_id in vessels:
            rows.append(measure_one(vessel_id=vessel_id, material_id=material_id,
                                    drop_height_mm=drop_height_mm, seed=seed))
    return rows


def scaled_mother(mother: Any, scale: float) -> Any:
    """A similarity transform of a real mother mesh, as a drop-in mother object.

    ``run_voronoi_event`` reads only ``mother.mesh`` (and ``mother.mother_id`` for the default
    parent id), so a scaled copy of a real, audited mesh is a legitimate input: the geometry keeps
    its real topology, wall thickness *distribution* and curvature, and only the linear size
    changes.  Scaling up a single vessel is the only way to move volume without also changing the
    vessel family, so a size series that must not be confounded with a shape change uses this.
    """
    import copy

    import trimesh

    scaled = copy.copy(mother)
    scaled.mesh = trimesh.Trimesh(
        vertices=np.asarray(mother.mesh.vertices, dtype=np.float64) * float(scale),
        faces=np.asarray(mother.mesh.faces, dtype=np.int64), process=False)
    return scaled


def size_series(vessel_id: str = "V01", material_id: str = "M01",
                scales: Sequence[float] = (0.5, 0.75, 1.0, 1.5),
                drop_height_mm: float = 1000.0, *,
                seed: int = MASTER_SEED) -> list[dict[str, Any]]:
    """One vessel family, linear size scaled: the controlled size law (volume x s^3)."""
    base = load_mother(vessel_id, material_id, seed=seed)
    rows: list[dict[str, Any]] = []
    for scale in scales:
        mother = scaled_mother(base, float(scale))
        body = body_stats_of(mother, vessel_id)
        row = measure_one(vessel_id=vessel_id, material_id=material_id,
                          drop_height_mm=float(drop_height_mm), seed=seed, mother=mother,
                          body=body, material=material_stats_of(material_id))
        row["scale"] = float(scale)
        rows.append(row)
    return rows


def energy_series(vessel_id: str = "V01", material_id: str = "M01",
                  heights: Sequence[float] = DROP_HEIGHTS_MM, *,
                  seed: int = MASTER_SEED) -> list[dict[str, Any]]:
    """One vessel, one material, drop height swept over two orders of magnitude."""
    mother = load_mother(vessel_id, material_id, seed=seed)
    body = body_stats_of(mother, vessel_id)
    material = material_stats_of(material_id)
    return [measure_one(vessel_id=vessel_id, material_id=material_id,
                        drop_height_mm=float(h), seed=seed, mother=mother, body=body,
                        material=material)
            for h in heights]


def piece_series(vessel_id: str = "V01", material_id: str = "M01",
                 counts: Sequence[int] = PIECE_SWEEP, *, seed: int = MASTER_SEED) -> list[dict[str, Any]]:
    """Efficiency sweep: force the piece count and measure cost + audit."""
    mother = load_mother(vessel_id, material_id, seed=seed)
    body = body_stats_of(mother, vessel_id)
    material = material_stats_of(material_id)
    return [measure_one(vessel_id=vessel_id, material_id=material_id, drop_height_mm=None,
                        target_pieces=int(n), seed=seed, mother=mother, body=body,
                        material=material)
            for n in counts]


# ---------------------------------------------------------------------------- stage timing
def stage_probe(counts: Sequence[int] = PIECE_SWEEP, *, vessel_id: str = "V01",
                material_id: str = "M01", seed: int = MASTER_SEED) -> list[dict[str, Any]]:
    """Break the per-count wall time into partition / cell mesh / boolean / audit.

    The event function is one call by design (``synlab/fracture/**`` is not instrumented for this
    measurement), so the stages are timed by re-running the same primitives the event itself uses,
    with the same seeds.  The partition and discretisation stages are independent of the event
    body, so their times are directly comparable; the boolean and audit stages are measured as
    ``total - partition - cell mesh`` and are labelled as such.
    """
    import trimesh

    from synlab.fracture.booleans import boolean_intersection, tag_source
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.voronoi_event import _displaced_cell_mesh, run_voronoi_event
    from synlab.fracture.voronoi_frag import build_partition

    cfg = load_physics_config()
    mother = load_mother(vessel_id, material_id, seed=seed)
    body = body_stats_of(mother, vessel_id)
    material = material_stats_of(material_id)
    mesh = mother.mesh
    rows: list[dict[str, Any]] = []
    for n in counts:
        row: dict[str, Any] = {"target_pieces": int(n), "vessel_id": vessel_id,
                               "material_id": material_id}
        try:
            t0 = time.perf_counter()
            partition, _seed_report = build_partition(
                mesh, int(n), rng=event_rng(seed), seed_cfg=cfg.seeds,
                padding_mm=2.0)
            row["partition_s"] = round(time.perf_counter() - t0, 4)
        except BaseException as exc:  # noqa: BLE001 - a refusal is a measurement here
            row["status"] = "ERROR"
            row["failure"] = {"code": type(exc).__name__, "message": str(exc)[:400],
                              "stage": "build_partition"}
            rows.append(row)
            print(f"  stage N={n}: build_partition {type(exc).__name__}", flush=True)
            continue
        row["cells"] = int(len(partition.cells))
        t0 = time.perf_counter()
        cell_meshes = [_displaced_cell_mesh(cell, {}, refinement=cfg.roughness.facet_refinement,
                                            refine_mm=cfg.roughness.facet_refine_mm)
                       for cell in partition.cells]
        row["cell_mesh_s"] = round(time.perf_counter() - t0, 4)
        row["cell_faces_total"] = int(sum(len(np.asarray(cm.faces)) for cm in cell_meshes))
        mother_clean = trimesh.Trimesh(vertices=np.asarray(mesh.vertices, dtype=np.float64),
                                       faces=np.asarray(mesh.faces, dtype=np.int64),
                                       process=False)
        mother_source = tag_source(mother_clean, 1.0, "mother")
        t0 = time.perf_counter()
        volumes = []
        for position, cm in enumerate(cell_meshes):
            cutter = tag_source(trimesh.Trimesh(
                vertices=np.asarray(cm.vertices, dtype=np.float64),
                faces=np.asarray(cm.faces, dtype=np.int64), process=False),
                1000.0 + position, "cell")
            tagged = boolean_intersection([mother_source, cutter], label=f"probe_{position}")
            volumes.append(float(abs(tagged.mesh.volume)))
        row["boolean_s"] = round(time.perf_counter() - t0, 4)
        # audit cost is measured as the residual of the full event, so it is labelled as such
        t0 = time.perf_counter()
        full = measure_one(vessel_id=vessel_id, material_id=material_id, drop_height_mm=None,
                           target_pieces=int(n), seed=seed, mother=mother, body=body,
                           material=material, config=cfg)
        row["event_s"] = round(time.perf_counter() - t0, 4)
        if full.get("status") == "OK":
            event_total = float(full["measurement"]["seconds"])
            row["status"] = "OK"
            row["event_reported_s"] = event_total
            row["audit_and_assembly_s"] = round(
                max(event_total - row["partition_s"] - row["cell_mesh_s"] - row["boolean_s"], 0.0), 4)
            row["pieces"] = int(full["measurement"]["pieces"])
            row["qa_passed"] = bool(full["measurement"]["qa_passed"])
            row["qa_failures"] = list(full["measurement"]["qa_failures"])
        else:
            row["status"] = full.get("status")
            row["event_reported_s"] = full.get("seconds")
            row["failure"] = full.get("failure")
        row["boolean_volumes_mm3"] = [round(v, 3) for v in volumes]
        rows.append(row)
        print(f"  stage N={n}: part={row['partition_s']:.3f}s cell={row['cell_mesh_s']:.3f}s "
              f"bool={row['boolean_s']:.3f}s event={row.get('event_reported_s')}s "
              f"status={row['status']}", flush=True)
    return rows


# ---------------------------------------------------------------------------- fits
def _ols(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    """Least squares ``y = a + b x`` with R^2 and residuals."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if x.size < 2 or float(np.ptp(x)) == 0.0:
        return {"slope": float("nan"), "intercept": float("nan"), "r2": float("nan"),
                "n": int(x.size)}
    design = np.vstack([np.ones_like(x), x]).T
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    pred = design @ coef
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
    return {"intercept": float(coef[0]), "slope": float(coef[1]), "r2": r2,
            "n": int(x.size), "rmse": float(np.sqrt(ss_res / max(x.size, 1)))}


def fit_size_law(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Fit ``ln N = ln k + a ln V + b ln A + c ln t`` on measured points.

    ``points`` are the rows whose ``count_source`` is ``physics``; each needs ``volume_mm3``,
    ``area_mm2``, ``wall_mm`` and ``pieces``.  Volume and area are used together only in the
    three-term fit; the single-term fits are reported separately so the collinearity between them
    is visible rather than hidden.
    """
    usable = [p for p in points
              if p.get("pieces") and float(p["pieces"]) >= 2 and p.get("volume_mm3")]
    if len(usable) < 2:
        return {"n": len(usable), "error": "not enough distinct points for a fit"}
    n = np.asarray([float(p["pieces"]) for p in usable])
    v = np.asarray([float(p["volume_mm3"]) for p in usable])
    a = np.asarray([float(p.get("area_mm2") or 0.0) for p in usable])
    t = np.asarray([float(p.get("wall_mm") or 0.0) for p in usable])
    out: dict[str, Any] = {
        "n": int(len(usable)),
        "points": [{"label": p.get("label", ""), "pieces": float(p["pieces"]),
                    "volume_mm3": float(p["volume_mm3"]),
                    "area_mm2": float(p.get("area_mm2") or 0.0),
                    "wall_mm": float(p.get("wall_mm") or 0.0)} for p in usable],
    }
    ln_n, ln_v, ln_a, ln_t = np.log(n), np.log(v), np.log(np.maximum(a, 1e-9)), \
        np.log(np.maximum(t, 1e-9))
    out["loglog_N_vs_V"] = _ols(ln_v, ln_n)
    out["loglog_N_vs_A"] = _ols(ln_a, ln_n)
    if np.all(t > 0.0):
        out["loglog_N_vs_t"] = _ols(ln_t, ln_n)
    if len(usable) >= 4:
        design = np.vstack([np.ones_like(ln_n), ln_v, ln_t]).T
        coef, *_ = np.linalg.lstsq(design, ln_n, rcond=None)
        pred = design @ coef
        ss_res = float(np.sum((ln_n - pred) ** 2))
        ss_tot = float(np.sum((ln_n - np.mean(ln_n)) ** 2))
        out["loglog_N_vs_V_t"] = {
            "intercept": float(coef[0]), "a_volume": float(coef[1]), "c_thickness": float(coef[2]),
            "r2": float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan"),
            "n": int(len(usable)),
        }
        design = np.vstack([np.ones_like(ln_n), ln_a, ln_t]).T
        coef, *_ = np.linalg.lstsq(design, ln_n, rcond=None)
        pred = design @ coef
        ss_res = float(np.sum((ln_n - pred) ** 2))
        out["loglog_N_vs_A_t"] = {
            "intercept": float(coef[0]), "b_area": float(coef[1]), "c_thickness": float(coef[2]),
            "r2": float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan"),
            "n": int(len(usable)),
        }
    return out


def fit_energy_law(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Fit ``ln N = ln k + beta ln U`` on the one-body energy series (measured energies)."""
    usable = [p for p in points if p.get("pieces") and p.get("energy_j")]
    if len(usable) < 2:
        return {"n": len(usable), "error": "not enough distinct points for a fit"}
    n = np.asarray([float(p["pieces"]) for p in usable])
    u = np.asarray([float(p["energy_j"]) for p in usable])
    out = {"n": int(len(usable)),
           "points": [{"label": p.get("label", ""), "pieces": float(p["pieces"]),
                       "energy_j": float(p["energy_j"]),
                       "drop_height_mm": p.get("drop_height_mm")} for p in usable],
           "loglog_N_vs_U": _ols(np.log(u), np.log(n))}
    return out


def monotonicity_check(series: Sequence[dict[str, Any]], *, key: str = "volume_mm3") -> dict[str, Any]:
    """Is the measured piece count non-decreasing in ``key``?  Counter-examples are reported."""
    usable = [p for p in series
              if p.get("pieces") is not None and p.get(key) is not None
              and isinstance(p.get("pieces"), (int, float))
              and isinstance(p.get(key), (int, float, np.integer, np.floating))]
    ordered = sorted(usable, key=lambda p: float(p[key]))
    violations: list[dict[str, Any]] = []
    for left, right in zip(ordered, ordered[1:]):
        if float(right["pieces"]) < float(left["pieces"]):
            violations.append({
                "smaller": {"label": str(left.get("label", "")), key: float(left[key]),
                            "pieces": float(left["pieces"])},
                "larger": {"label": str(right.get("label", "")), key: float(right[key]),
                           "pieces": float(right["pieces"])},
            })
    return {
        "key": key, "n": int(len(ordered)),
        "monotone_non_decreasing": not violations,
        "violations": violations,
        "ordered": [{"label": str(p.get("label", "")), key: float(p[key]),
                     "pieces": float(p["pieces"])} for p in ordered],
    }


# ---------------------------------------------------------------------------- the calibrated law
#: reference impact speed (mm/s) = 3.13 m/s, i.e. a 0.5 m free drop (the declared scenario).
V_IMPACT_REF_MM_S = 3130.0
#: reference density (g/cm^3) of the reference body -- the frozen engineering value.
REFERENCE_DENSITY_G_CM3 = 2.2


def _beta_std_error(x: np.ndarray, y: np.ndarray, ln_n0: float, beta: float,
                    censored: np.ndarray | None) -> float:
    """Standard error of the fitted exponent from the active (uncensored) points."""
    active = np.ones(x.size, dtype=bool) if censored is None else ~np.asarray(censored)
    if int(np.sum(active)) < 3:
        return float("nan")
    xa, ya = x[active], y[active]
    design = np.vstack([np.ones_like(xa), xa]).T
    residual = ya - design @ np.array([ln_n0, beta], dtype=np.float64)
    dof = max(int(xa.size) - 2, 1)
    sigma2 = float(np.sum(residual ** 2) / dof)
    try:
        cov = sigma2 * np.linalg.inv(design.T @ design)
    except np.linalg.LinAlgError:
        return float("nan")
    return float(np.sqrt(max(cov[1, 1], 0.0)))


def count_fit(points: Sequence[dict[str, Any]], *,
              v_ref_mm3: float = 339292.0,
              thickness_ref_mm: float = 6.0,
              weibull_modulus: float = 7.0,
              weibull_volume_exponent: float = 0.5,
              min_pieces: int = 2,
              max_pieces: int = 64,
              censor: bool = True,
              beta_override: float | None = None,
              alpha_override: float | None = None) -> dict[str, Any]:
    """Fit ``N = N0 * (U/U_ref)^beta * (V/V_ref)^alpha * (t_ref/t)^gamma`` to measured points.

    ``U_ref`` is **not** a free parameter.  It is the energy of the declared reference body at the
    declared reference speed, ``U_ref = 0.5 * rho_ref * V_ref * v_ref**2``, and the profile of the
    fitted law is normalised on it, so the fit produces one identifiable number for the energy
    exponent ``beta`` and one for the amplitude ``N0`` (the piece count this model would give on
    the reference body at a 0.5 m drop).  Holding ``U_ref`` fixed is what makes ``N0`` and ``beta``
    separately identifiable; the previous calibration instead *solved* ``U_ref`` from ``N0``, which
    left the amplitude degenerate and pulled the law's absolute scale down by more than an order of
    magnitude (measured: ``N0 = 3`` on a 3.4e5 mm^3 reference body gives ``n_raw = 1.73`` on the
    1.85e5 mm^3 V01 bowl, i.e. the count clamps to the floor of 2 for almost every real vessel).

    ``alpha`` is held at the model's own geometry + Weibull value ``1/(2m) + weibull_volume_exponent``
    and ``gamma = weibull_volume_exponent``: both ingredients are declared separately in
    ``configs/a12/fracture_physics.yaml`` and are *not* fitted here (with only ~3 distinct measured
    counts no honest fit can separate them).  The count actually fitted is the measured
    ``n_deterministic`` when present, because the integer Weibull draw is noise added on top of the
    law and does not belong in the fit.

    Points must carry ``pieces``, ``energy_j``, ``volume_mm3`` and ``wall_mm``.
    """
    usable = [p for p in points
              if p.get("pieces") and p.get("energy_j") and p.get("volume_mm3") and p.get("wall_mm")]
    if len(usable) < 2:
        return {"n": len(usable), "error": "not enough points with pieces + energy + volume"}
    alpha = 1.0 / max(float(weibull_modulus), 1.0) / 2.0 + float(weibull_volume_exponent)
    if alpha_override is not None:
        alpha = float(alpha_override)
    gamma = float(weibull_volume_exponent)
    n_meas = np.asarray([float(p.get("n_deterministic") or p["pieces"]) for p in usable])
    energy = np.asarray([float(p["energy_j"]) for p in usable])
    volume = np.asarray([float(p["volume_mm3"]) for p in usable])
    wall = np.asarray([float(p["wall_mm"]) for p in usable])
    mass_ref = float(REFERENCE_DENSITY_G_CM3) * 1.0e-6 * float(v_ref_mm3)
    u_ref = 0.5 * mass_ref * (float(V_IMPACT_REF_MM_S) * 1.0e-3) ** 2
    size_term = (volume / float(v_ref_mm3)) ** alpha
    thick_term = (float(thickness_ref_mm) / wall) ** gamma
    x = np.log(energy / (u_ref * size_term * thick_term))
    #: points at the floor of the law (``min_pieces``) are **censored**: a real vessel that the law
    #: says should break into fewer than two pieces still yields the floor of two, so the residual
    #: of those points is one-sided and must not be treated as an exact measurement.
    censored = np.asarray([float(p.get("n_deterministic") or p["pieces"]) <= float(min_pieces)
                           for p in usable]) if censor else np.zeros(len(usable), dtype=bool)

    def _predict(ln_n0: float, beta: float) -> np.ndarray:
        return np.exp(ln_n0 + beta * x)

    ln_n0, beta = float(np.log(2.0)), 0.65
    if beta_override is not None:
        beta = float(beta_override)
        # only the intercept is left: solve it in closed form with the same censoring rule
        model = _predict(ln_n0, beta)
        residual = np.log(n_meas) - np.log(np.maximum(model, 1e-12))
        residual = np.where(censored & (residual < 0.0), 0.0, residual)
        ln_n0 += float(np.mean(residual))
    else:
        # Deterministic grid over the energy exponent; for each beta the amplitude is solved in
        # closed form (mean of the active residuals) and the censoring rule is applied.  ``beta``
        # enters the active-set decision, so the objective is not convex and a gradient step can
        # stall on the kink at the floor; a grid is both simpler and auditable.
        best: tuple[float, float, float] | None = None
        for candidate in np.linspace(0.2, 1.8, 1601):
            trial = _predict(ln_n0, float(candidate))
            res = np.log(n_meas) - np.log(np.maximum(trial, 1e-12))
            res = np.where(censored & (res < 0.0), 0.0, res)
            offset = float(np.mean(res))
            trial = _predict(ln_n0 + offset, float(candidate))
            res = np.log(n_meas) - np.log(np.maximum(trial, 1e-12))
            res = np.where(censored & (res < 0.0), 0.0, res)
            score = float(np.sum(res ** 2))
            if best is None or score < best[0]:
                best = (score, float(candidate), ln_n0 + offset)
        assert best is not None
        beta = best[1]
        ln_n0 = best[2]
    for _iteration in range(0):
        model = _predict(ln_n0, beta)
        residual = np.log(n_meas) - np.log(np.maximum(model, 1e-12))
        residual = np.where(censored & (residual < 0.0), 0.0, residual)
        # Gauss-Newton on (ln N0, beta) with the analytic Jacobian
        jac = np.vstack([np.ones_like(x), x]).T
        jac = np.where((censored & (np.log(n_meas) - np.log(np.maximum(model, 1e-12)) < 0.0))[:, None],
                       0.0, jac)
        try:
            step, *_ = np.linalg.lstsq(jac, residual, rcond=None)
        except np.linalg.LinAlgError:
            break
        ln_n0 += float(step[0])
        beta += float(step[1])
        if float(np.max(np.abs(step))) < 1e-12:
            break
    n0_fit = float(np.exp(ln_n0))
    model = _predict(ln_n0, beta)
    model_clamped = np.clip(model, float(min_pieces), float(max_pieces))
    residual = np.log(np.maximum(model_clamped, 1e-12)) - np.log(n_meas)
    residual = np.where(censored & (residual < 0.0), 0.0, residual)
    ss_res = float(np.sum(residual ** 2))
    ss_tot = float(np.sum((np.log(n_meas) - np.mean(np.log(n_meas))) ** 2))
    predicted_int = np.clip(np.round(model_clamped), min_pieces, max_pieces)
    return {
        "n": int(len(usable)),
        "n_censored_at_floor": int(np.sum(censored)),
        "model": "N = N0 * (U/U_ref)^beta * (V/V_ref)^alpha * (t_ref/t)^gamma",
        "fitted": {"n0": n0_fit, "beta": beta, "u_ref_j": float(u_ref),
                   "beta_fitted": beta_override is None},
        "pinned": {
            "alpha_size_exponent": float(alpha),
            "alpha_fitted": alpha_override is not None,
            "gamma_thickness_exponent": float(gamma),
            "weibull_modulus": float(weibull_modulus),
            "weibull_volume_exponent": float(weibull_volume_exponent),
            "v_ref_mm3": float(v_ref_mm3), "thickness_ref_mm": float(thickness_ref_mm),
            "v_impact_ref_mm_s": float(V_IMPACT_REF_MM_S),
            "reference_density_g_cm3": float(REFERENCE_DENSITY_G_CM3),
            "provenance": ("alpha/gamma pinned to the declared geometry + Weibull form and U_ref to "
                           "the declared reference body: none of the three is fitted here"),
        },
        "r2_log": float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan"),
        "rmse_log": float(np.sqrt(ss_res / max(len(usable), 1))),
        "mae_pieces": float(np.mean(np.abs(predicted_int - n_meas))),
        "max_abs_error_pieces": float(np.max(np.abs(predicted_int - n_meas))),
        "beta_std_error": _beta_std_error(x, np.log(n_meas), ln_n0, beta,
                                          censored if censor else None),
        "points": [{
            "label": p.get("label", ""), "pieces": float(p["pieces"]),
            "n_used": float(p.get("n_deterministic") or p["pieces"]),
            "censored_at_floor": bool(c),
            "energy_j": float(p["energy_j"]), "volume_mm3": float(p["volume_mm3"]),
            "wall_mm": float(p["wall_mm"]),
            "model": float(m), "model_clamped": float(mc), "model_rounded": int(pi),
            "residual_log": float(r),
        } for p, m, mc, pi, c, r in zip(usable, model, model_clamped, predicted_int, censored,
                                        residual)],
    }


def _impact_energy_of(row: dict[str, Any]) -> float | None:
    """``U = 0.5 m v^2`` for a row, from its measured mass and its declared drop height/speed.

    Refused rows have no event record, so their energy is recomputed from the measured body volume
    and density with the same formulas the law uses (``impact.impact_from_drop_height``).  The
    recomputation is *not* a substitute for a measurement: rows whose event ran always use the
    event's own ``energy_j``.
    """
    from synlab.fracture.impact import impact_from_drop_height

    measurement = row.get("measurement") or {}
    count_model = measurement.get("count_model") or {}
    if count_model.get("energy_j"):
        return float(count_model["energy_j"])
    body = row.get("body") or {}
    material = row.get("material") or {}
    drop = row.get("drop_height_mm")
    if not body.get("volume_mm3") or drop is None:
        return None
    density = float(material.get("density_g_cm3") or 2.2) * 1.0e-6
    mass = density * float(body["volume_mm3"])
    _speed, energy = impact_from_drop_height(mass, float(drop))
    return float(energy)


def _calibration_points(rows: Sequence[dict[str, Any]], *, label_prefix: str = "") -> list[dict[str, Any]]:
    """Turn measured rows into fit points, keeping refusals visible as unmeasured."""
    points: list[dict[str, Any]] = []
    for row in rows:
        measurement = row.get("measurement") or {}
        count_model = measurement.get("count_model") or {}
        body = row.get("body") or {}
        if measurement.get("count_source") != "physics":
            continue  # the N-sweep is an explicit override, never a measurement of the law
        energy = _impact_energy_of(row)
        if energy is None or not measurement.get("pieces"):
            continue
        label = (f"{label_prefix}{row.get('vessel_id')}/{row.get('material_id')}"
                 f" h={row.get('drop_height_mm')}"
                 + (f" s={row.get('scale')}" if row.get("scale") is not None else ""))
        points.append({
            "label": label, "vessel_id": row.get("vessel_id"),
            "material_id": row.get("material_id"), "drop_height_mm": row.get("drop_height_mm"),
            "scale": row.get("scale"),
            "material": dict(row.get("material") or {}),
            "pieces": float(measurement["pieces"]),
            "n_deterministic": float(count_model.get("n_deterministic") or measurement["pieces"]),
            "energy_j": float(energy), "volume_mm3": float(body.get("volume_mm3") or 0.0),
            "area_mm2": float(body.get("area_mm2") or 0.0),
            "wall_mm": float(count_model.get("wall_mm") or body.get("thickness_median_mm") or 0.0),
            "clamped": bool(count_model.get("clamped", False)),
        })
    return points


# ---------------------------------------------------------------------------- doc tables
def doc_tables(inputs: Sequence[str], *, v_ref_mm3: float = 339292.0,
               thickness_ref_mm: float = 6.0, weibull_modulus: float = 7.0,
               weibull_volume_exponent: float = 0.5, min_pieces: int = 2,
               max_pieces: int = 64) -> str:
    """Regenerate the markdown tables of ``docs/a12/fracture_calibration.md`` from the raw JSON.

    Hand-copied numbers in a calibration document drift from the measurements the moment anything
    is re-run; this renders the tables straight from the files the instrument wrote, and
    ``tests/a12/fracture/test_calibration_audit.py`` checks the same files, so the document and the
    tests cannot disagree.
    """
    merged: dict[str, Any] = {"rows": []}
    for path in inputs:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        for row in payload.get("rows") or []:
            row = dict(row)
            row["_series"] = Path(path).stem.replace("fracture_calibration_", "")
            merged["rows"].append(row)
    rows = merged["rows"]
    points = _calibration_points(rows)
    lines: list[str] = []

    def _status(row: dict[str, Any]) -> str:
        return str(row.get("status", ""))

    lines.append("### A. measurement points")
    lines.append("")
    lines.append("| # | vessel/material | series | volume mm^3 | wall mm | drop mm | U J | n_raw | "
                 "N_det | N measured | status |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for index, row in enumerate(rows, start=1):
        body = row.get("body") or {}
        measurement = row.get("measurement") or {}
        count = measurement.get("count_model") or {}
        status = _status(row)
        if status == "OK":
            failure = ""
        else:
            failure = " " + str((row.get("failure") or {}).get("code", ""))
        energy_text = ("%.3f" % float(count["energy_j"])) if count.get("energy_j") else "-"
        raw_text = ("%.3f" % float(count["n_raw"])) if count.get("n_raw") is not None else "-"
        det_text = ("%.3f" % float(count["n_deterministic"])) if count.get("n_deterministic") else "-"
        cells = [
            str(index),
            f"{row.get('vessel_id')}/{row.get('material_id')}",
            str(row.get("_series")),
            "%.0f" % float(body.get("volume_mm3") or 0.0),
            "%.3f" % float(body.get("thickness_median_mm") or 0.0),
            str(row.get("drop_height_mm")),
            energy_text, raw_text, det_text,
            str(measurement.get("pieces", "-")),
            status + failure,
        ]
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("### B. audit extremes over every green point")
    lines.append("")
    worst: dict[str, float] = {}
    for row in rows:
        measurement = row.get("measurement") or {}
        if not measurement:
            continue
        for key in ("volume_rel_diff", "overlap_ratio", "gap_p95_mm_max",
                    "normal_angle_p95_deg_max", "ambiguous_area_ratio_total",
                    "unmatched_interface_area_ratio"):
            value = measurement.get(key)
            if isinstance(value, (int, float)):
                worst[key] = max(worst.get(key, float("-inf")), float(value))
        coverage = measurement.get("source_coverage")
        if isinstance(coverage, (int, float)):
            worst["source_coverage_min"] = min(worst.get("source_coverage_min", float("inf")),
                                               float(coverage))
        identity = measurement.get("vertex_identity_ratio_min")
        if isinstance(identity, (int, float)):
            worst["vertex_identity_ratio_min"] = min(
                worst.get("vertex_identity_ratio_min", float("inf")), float(identity))
        nearest = measurement.get("nearest_surface_p95_mm_max")
        if isinstance(nearest, (int, float)):
            worst["nearest_surface_p95_mm_max"] = max(
                worst.get("nearest_surface_p95_mm_max", float("-inf")), float(nearest))
    lines.append("| metric | worst over green points |")
    lines.append("|---|---|")
    for key, value in sorted(worst.items()):
        lines.append(f"| {key} | {value:.6g} |")

    lines.append("")
    lines.append("### C. refusals")
    lines.append("")
    lines.append("| vessel/material | series | drop mm | count | status | message |")
    lines.append("|---|---|---|---|---|---|")
    for row in rows:
        if _status(row) == "OK":
            continue
        failure = row.get("failure") or {}
        lines.append("| {}/{} | {} | {} | {} | {} | {} |".format(
            row.get("vessel_id"), row.get("material_id"), row.get("_series"),
            row.get("drop_height_mm"), row.get("target_pieces_override"), _status(row),
            str(failure.get("message", failure.get("code", "")))[:160]))

    lines.append("")
    lines.append("### D. fits")
    lines.append("")
    free = [p for p in points if float(p.get("n_deterministic") or 0.0) > float(min_pieces)]
    fits = {
        "unclamped (N > floor)": count_fit(free, v_ref_mm3=v_ref_mm3,
                                           thickness_ref_mm=thickness_ref_mm,
                                           weibull_modulus=weibull_modulus,
                                           weibull_volume_exponent=weibull_volume_exponent,
                                           min_pieces=min_pieces, max_pieces=max_pieces,
                                           censor=False),
        "all points, floor censored": count_fit(points, v_ref_mm3=v_ref_mm3,
                                                thickness_ref_mm=thickness_ref_mm,
                                                weibull_modulus=weibull_modulus,
                                                weibull_volume_exponent=weibull_volume_exponent,
                                                min_pieces=min_pieces, max_pieces=max_pieces,
                                                censor=True),
    }
    lines.append("| fit | n | N0 | beta | R2(ln N) | RMSE(ln N) | MAE pieces | max abs |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for label, fit in fits.items():
        if "fitted" not in fit:
            lines.append(f"| {label} | {fit.get('n')} | - | - | - | - | - | - |")
            continue
        lines.append("| {} | {} | {:.4f} | {:.4f} | {:.4f} | {:.4f} | {:.3f} | {:.3f} |".format(
            label, fit["n"], fit["fitted"]["n0"], fit["fitted"]["beta"], fit["r2_log"],
            fit["rmse_log"], fit["mae_pieces"], fit["max_abs_error_pieces"]))
    lines.append("")
    lines.append("### E. monotonicity")
    lines.append("")
    checks = {
        "energy series (one body)": monotonicity_check(
            [{"label": p["label"], "energy_j": p["energy_j"], "pieces": p["n_deterministic"]}
             for p in points], key="energy_j"),
        "controlled size series": monotonicity_check(
            [{"label": p["label"], "volume_mm3": p["volume_mm3"],
              "pieces": p["n_deterministic"]} for p in points if p.get("scale") is not None],
            key="volume_mm3"),
        "all points by volume": monotonicity_check(
            [{"label": p["label"], "volume_mm3": p["volume_mm3"],
              "pieces": p["n_deterministic"]} for p in points], key="volume_mm3"),
    }
    lines.append("| check | monotone non-decreasing | violations |")
    lines.append("|---|---|---|")
    for label, check in checks.items():
        lines.append(f"| {label} | {check['monotone_non_decreasing']} | {len(check['violations'])} |")
        for violation in check["violations"]:
            lines.append("| ↳ {} vs {} | | pieces {} < {} |".format(
                violation["smaller"]["label"], violation["larger"]["label"],
                violation["larger"]["pieces"], violation["smaller"]["pieces"]))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------- cli
def _load(paths: Sequence[str]) -> dict[str, Any]:
    merged: dict[str, Any] = {"sources": []}
    for path in paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        merged["sources"].append(str(path))
        for key, value in payload.items():
            if key in ("rows", "matrix", "energy", "size", "sweep", "stage"):
                merged.setdefault(key, [])
                if isinstance(value, list):
                    merged[key].extend(value)
            else:
                merged.setdefault(key, value)
    return merged


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="piece-count law calibration (measurement only)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("matrix")
    p.add_argument("--out", required=True)
    p.add_argument("--drop-height", type=float, default=500.0)
    p.add_argument("--vessels", default=",".join(SIZE_VESSELS))
    p.add_argument("--materials", default=",".join(SWEEP_MATERIALS))

    p = sub.add_parser("energy")
    p.add_argument("--out", required=True)
    p.add_argument("--vessel", default="V01")
    p.add_argument("--material", default="M01")

    p = sub.add_parser("pieces")
    p.add_argument("--out", required=True)
    p.add_argument("--vessel", default="V01")
    p.add_argument("--material", default="M01")

    p = sub.add_parser("size")
    p.add_argument("--out", required=True)
    p.add_argument("--vessel", default="V01")
    p.add_argument("--material", default="M01")
    p.add_argument("--drop-height", type=float, default=1000.0)
    p.add_argument("--scales", default="0.5,0.75,1.0,1.5")

    p = sub.add_parser("stage")
    p.add_argument("--out", required=True)
    p.add_argument("--vessel", default="V01")
    p.add_argument("--material", default="M01")

    p = sub.add_parser("one")
    p.add_argument("--out", required=True)
    p.add_argument("--vessel", required=True)
    p.add_argument("--material", required=True)
    p.add_argument("--drop-height", type=float, default=None)
    p.add_argument("--target-pieces", type=int, default=None)

    p = sub.add_parser("fit")
    p.add_argument("--inputs", nargs="+", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--v-ref-mm3", type=float, default=339292.0)
    p.add_argument("--thickness-ref-mm", type=float, default=6.0)
    p.add_argument("--weibull-modulus", type=float, default=7.0)
    p.add_argument("--weibull-volume-exponent", type=float, default=0.5)
    p.add_argument("--min-pieces", type=int, default=2)
    p.add_argument("--max-pieces", type=int, default=64)
    p.add_argument("--existing", default="configs/a12/fracture_physics.yaml",
                   help="current physics config, whose declared law is also evaluated on the points")

    p = sub.add_parser("tables")
    p.add_argument("--inputs", nargs="+", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--v-ref-mm3", type=float, default=339292.0)
    p.add_argument("--thickness-ref-mm", type=float, default=6.0)
    p.add_argument("--weibull-modulus", type=float, default=7.0)

    args = parser.parse_args(list(argv) if argv is not None else None)
    out = Path(args.out)

    if args.command == "matrix":
        rows = matrix_series(args.drop_height,
                             [v.strip() for v in args.vessels.split(",") if v.strip()],
                             [m.strip() for m in args.materials.split(",") if m.strip()])
        payload = {"schema": "synlab.fracture_calibration.matrix.v1", "kind": "matrix",
                   "drop_height_mm": float(args.drop_height), "rows": rows}
        write_report(out, payload)
        for row in rows:
            print(f"{row['vessel_id']}/{row['material_id']}: status={row['status']} "
                  f"pieces={row.get('measurement', {}).get('pieces')}", flush=True)
    elif args.command == "energy":
        rows = energy_series(args.vessel, args.material)
        payload = {"schema": "synlab.fracture_calibration.energy.v1", "kind": "energy",
                   "vessel_id": args.vessel, "material_id": args.material, "rows": rows}
        write_report(out, payload)
    elif args.command == "pieces":
        rows = piece_series(args.vessel, args.material)
        payload = {"schema": "synlab.fracture_calibration.pieces.v1", "kind": "pieces",
                   "vessel_id": args.vessel, "material_id": args.material, "rows": rows}
        write_report(out, payload)
    elif args.command == "size":
        rows = size_series(args.vessel, args.material,
                           [float(s) for s in args.scales.split(",") if s.strip()],
                           args.drop_height)
        payload = {"schema": "synlab.fracture_calibration.size.v1", "kind": "size",
                   "vessel_id": args.vessel, "material_id": args.material,
                   "drop_height_mm": float(args.drop_height), "rows": rows}
        write_report(out, payload)
        for row in rows:
            m = row.get("measurement") or {}
            print(f"scale={row.get('scale')} status={row['status']} "
                  f"pieces={m.get('pieces')} V={row['body']['volume_mm3']:.0f}", flush=True)
    elif args.command == "stage":
        rows = stage_probe(vessel_id=args.vessel, material_id=args.material)
        payload = {"schema": "synlab.fracture_calibration.stage.v1", "kind": "stage",
                   "vessel_id": args.vessel, "material_id": args.material, "rows": rows}
        write_report(out, payload)
    elif args.command == "one":
        row = measure_one(vessel_id=args.vessel, material_id=args.material,
                          drop_height_mm=args.drop_height, target_pieces=args.target_pieces)
        write_report(out, {"schema": "synlab.fracture_calibration.one.v1", "kind": "one",
                           "rows": [row]})
        print(json.dumps(row.get("measurement", row.get("failure")), default=str)[:400], flush=True)
    elif args.command == "fit":
        merged = _load(args.inputs)
        rows = [row for key in ("rows", "matrix", "energy", "size", "sweep")
                for row in (merged.get(key) or [])]
        points = _calibration_points(rows)
        free = [p for p in points if float(p.get("n_deterministic") or 0.0) > float(args.min_pieces)]
        fit_all = count_fit(points, v_ref_mm3=args.v_ref_mm3,
                            thickness_ref_mm=args.thickness_ref_mm,
                            weibull_modulus=args.weibull_modulus,
                            weibull_volume_exponent=args.weibull_volume_exponent,
                            min_pieces=args.min_pieces, max_pieces=args.max_pieces, censor=True)
        fit_free = count_fit(free, v_ref_mm3=args.v_ref_mm3,
                             thickness_ref_mm=args.thickness_ref_mm,
                             weibull_modulus=args.weibull_modulus,
                             weibull_volume_exponent=args.weibull_volume_exponent,
                             min_pieces=args.min_pieces, max_pieces=args.max_pieces, censor=False)
        # the *adopted* calibration: the exponent from the unclamped fit (the only points that
        # carry a measured count above the floor) and the amplitude re-solved on all points with
        # the floor treated as censored, so the floored vessels constrain it from above.
        adopted = count_fit(points, v_ref_mm3=args.v_ref_mm3,
                            thickness_ref_mm=args.thickness_ref_mm,
                            weibull_modulus=args.weibull_modulus,
                            weibull_volume_exponent=args.weibull_volume_exponent,
                            min_pieces=args.min_pieces, max_pieces=args.max_pieces, censor=True,
                            beta_override=float(fit_free.get("fitted", {}).get("beta", 0.65)))
        adopted["provenance"] = (
            "beta from the unclamped fit (points whose measured count is above the floor); the "
            "amplitude N0 re-solved on every measured point with the floor treated as censored")
        # the declared law of the *current* config, evaluated on exactly the same points, so the
        # calibration's effect is a measured before/after and not a claim
        declared: dict[str, Any] = {}
        try:
            from synlab.fracture.impact import BodyStats, MaterialStats, count_model
            from synlab.fracture.physics import load_physics_config

            cfg = load_physics_config(args.existing)
            declared = {"config": str(args.existing), "config_hash": cfg.hash,
                        "u_ref_j": float(cfg.impact.u_ref_j), "points": []}
            for point in points:
                body = BodyStats(vessel_id=str(point["vessel_id"]), volume_mm3=point["volume_mm3"],
                                 area_mm2=point["area_mm2"],
                                 thickness_median_mm=point["wall_mm"] or 6.0)
                material = MaterialStats(
                    material_id=str(point["material_id"]),
                    density_g_cm3=float((point.get("material") or {}).get("density_g_cm3")
                                        or 2.2))
                record = count_model(body, material, cfg.impact, energy_j=point["energy_j"])
                declared["points"].append({
                    "label": point["label"], "n_raw": float(record["n_raw"]),
                    "n_deterministic": float(record["n_deterministic"]),
                    "declared_raw_clamped": bool(record["n_raw"] < record["n_deterministic"] - 1e-9
                                                 or record["clamped"])})
            declared["n_clamped"] = int(sum(1 for p in declared["points"]
                                            if p["n_raw"] <= cfg.impact.min_pieces + 1e-9))
        except Exception as exc:  # noqa: BLE001 - the comparison is evidence, not a gate
            declared = {"error": f"{type(exc).__name__}: {exc}"}
        # monotonicity in volume among the unclamped control series (the scaled-size series)
        control = [p for p in points if p.get("scale") is not None]
        # the calibrated model's own monotonicity: the same check on the *model* value, plus the
        # monotonicity of the measurement it replaced (the declared law), so a violation can be
        # attributed to the measurement or to the model
        declared_points = declared.get("points") or []
        declared_by_label = {str(p.get("label")): float(p.get("n_raw", float("nan")))
                             for p in declared_points}
        payload = {
            "schema": "synlab.fracture_calibration.v1",
            "kind": "fit",
            "sources": merged.get("sources", []),
            "points": points,
            "fit": fit_all,
            "fit_unclamped_only": fit_free,
            "fit_adopted": adopted,
            "declared_law_on_the_same_points": declared,
            "monotonicity": _flat({
                "scaled_size_series": monotonicity_check(
                    [{"label": p["label"], "volume_mm3": p["volume_mm3"],
                      "pieces": p["n_deterministic"]} for p in control], key="volume_mm3"),
                "scaled_size_series_measured_integer": monotonicity_check(
                    [{"label": p["label"], "volume_mm3": p["volume_mm3"],
                      "pieces": p["pieces"]} for p in control], key="volume_mm3"),
                "all_points_in_volume": monotonicity_check(
                    [{"label": p["label"], "volume_mm3": p["volume_mm3"],
                      "pieces": p["n_deterministic"]} for p in points], key="volume_mm3"),
                "all_points_in_energy": monotonicity_check(
                    [{"label": p["label"], "energy_j": p["energy_j"],
                      "pieces": p["n_deterministic"]} for p in points], key="energy_j"),
                "model_in_volume": monotonicity_check(
                    [{"label": p["label"], "volume_mm3": p["volume_mm3"],
                      "pieces": float(p["model"])} for p in (adopted.get("points") or [])],
                    key="volume_mm3"),
                "model_in_energy": monotonicity_check(
                    [{"label": p["label"], "energy_j": p["energy_j"],
                      "pieces": float(p["model"])} for p in (adopted.get("points") or [])],
                    key="energy_j"),
                "declared_law_in_volume": monotonicity_check(
                    [{"label": p["label"], "volume_mm3": p["volume_mm3"],
                      "pieces": declared_by_label.get(str(p["label"]), float("nan"))}
                     for p in points], key="volume_mm3"),
            }),
        }
        write_report(out, payload)
        print(json.dumps({
            "censored_fit": {k: fit_all.get(k) for k in
                             ("fitted", "r2_log", "rmse_log", "mae_pieces",
                              "max_abs_error_pieces", "n", "n_censored_at_floor")},
            "unclamped_fit": {k: fit_free.get(k) for k in
                              ("fitted", "r2_log", "rmse_log", "mae_pieces",
                               "max_abs_error_pieces", "n", "beta_std_error")},
            "adopted_fit": {k: adopted.get(k) for k in
                            ("fitted", "r2_log", "rmse_log", "mae_pieces",
                             "max_abs_error_pieces", "n", "n_censored_at_floor")},
            "declared_n_clamped": declared.get("n_clamped"),
        }, indent=1), flush=True)
    elif args.command == "tables":
        text = doc_tables(args.inputs, v_ref_mm3=args.v_ref_mm3,
                          thickness_ref_mm=args.thickness_ref_mm,
                          weibull_modulus=args.weibull_modulus)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(text[:2000], flush=True)
    print("wrote", out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
