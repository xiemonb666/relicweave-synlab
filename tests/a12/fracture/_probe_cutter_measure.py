#!/usr/bin/env python
"""Headless cutter-topology measurement through the *production* path.

One row per case: status, structured error + measurements on refusal, and on success the closed
solid's own numbers (edge-use histogram, watertightness, winding, volume, cells, realized error,
triangles) plus the wall-clock time.  Nothing is analysed by hand here, so the cost is the
production build only; the per-leaf traversal that made the earlier T-junction probe slow lives in
``_probe_tjunction.py`` and is not needed to decide whether the solid closes.

Usage::

    python tests/a12/fracture/_probe_cutter_measure.py --cases bowl,zero,bowl-lo --max-cells 90000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.errors import SynLabError  # noqa: E402
from synlab.fracture.booleans import mesh_hash  # noqa: E402
from synlab.fracture.spec import BACKEND_PLANE, BACKEND_ROUGH, FractureSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

import fixtures as fx  # noqa: E402


def edge_use_from_faces(faces: np.ndarray) -> dict[str, int]:
    a = faces[:, [0, 1, 2]].ravel()
    b = faces[:, [1, 2, 0]].ravel()
    keys = np.stack([np.minimum(a, b), np.maximum(a, b)], axis=1)
    _unique, counts = np.unique(keys, axis=0, return_counts=True)
    out: dict[str, int] = {}
    for value in counts.tolist():
        out[str(int(value))] = out.get(str(int(value)), 0) + 1
    return dict(sorted(out.items()))


def measure_mesh(mesh: Any) -> dict[str, Any]:
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    histogram = edge_use_from_faces(faces)
    return {
        "edge_use_histogram": histogram,
        "bad_edges": int(sum(v for k, v in histogram.items() if k != "2")),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "volume_mm3": float(mesh.volume),
        "vertices": int(verts.shape[0]),
        "faces": int(faces.shape[0]),
        "degenerate_faces": int(np.sum(mesh.area_faces <= 0.0)),
        "coincident_vertices": int(verts.shape[0]
                                   - np.unique(np.round(verts, 9), axis=0).shape[0]),
        "mesh_hash": mesh_hash(mesh),
    }


def run_case(name: str, *, rms: float, budget: float, max_cells: int, seed: int,
             backend: str) -> dict[str, Any]:
    mother = fx.thin_bowl_mother() if name.startswith("bowl") else fx.box_mother((20.0,) * 3)
    spec = FractureSpec(backend=backend, target_rms_mm=float(rms),
                        error_budget_mm=float(budget), max_cutter_cells=int(max_cells))
    rng = make_rng(seed, "tj_resolution", f"{name}_{rms}_{budget}_{max_cells}")
    from synlab.fracture.api import make_closed_cutter

    started = time.perf_counter()
    row: dict[str, Any] = {"case": name, "backend": backend, "target_rms_mm": float(rms),
                           "error_budget_mm": float(budget), "max_cells": int(max_cells)}
    try:
        cutter = make_closed_cutter(mother, spec, rng)
    except SynLabError as exc:
        row["status"] = "REFUSED"
        row["error_code"] = str(exc.code)
        row["message"] = str(exc).split("\n", 1)[0]
        row["measurements"] = {str(k): _json(v) for k, v in (exc.measurements or {}).items()}
    else:
        row["status"] = "OK"
        row.update(measure_mesh(cutter.mesh))
        row["realized_error_mm"] = float(cutter.realized_error_mm)
        meta = dict(cutter.meta or {})
        for key in ("cells", "leaf_level", "root_level", "key_level", "top_triangles",
                    "bottom_triangles", "side_triangles", "triangles", "error_samples",
                    "refine_iterations", "cells_tested", "cutter_local_hash",
                    "analytic_cell_size_for_budget_mm", "hanging_corner_points",
                    "edges_missing_a_hanging_point", "edge_extra_histogram"):
            if key in meta:
                row[key] = _json(meta[key])
        row["reported_edge_use_histogram"] = meta.get("edge_use_histogram")
        height = meta.get("height_field") or {}
        row["height_field"] = {
            "flat": height.get("flat"),
            "wavelength_min_mm": height.get("wavelength_min_mm"),
            "realized_rms_mm": height.get("realized_rms_mm"),
            "max_slope": height.get("max_slope"),
            "curvature_bound": height.get("curvature_bound"),
            "curvature_bound_windowed": height.get("curvature_bound_windowed"),
            "amplitude_max_mm": height.get("amplitude_max_mm"),
            "n_bands": (height.get("meta") or {}).get("n_bands"),
        }
    row["seconds"] = float(time.perf_counter() - started)
    return row


def _json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


CASES: dict[str, dict[str, Any]] = {
    "bowl": {"rms": 0.05, "backend": BACKEND_ROUGH},
    "bowl-lo": {"rms": 0.02, "backend": BACKEND_ROUGH},
    "box": {"rms": 0.05, "backend": BACKEND_ROUGH},
    "box20": {"rms": 0.05, "backend": BACKEND_ROUGH},
    "zero": {"rms": 0.0, "backend": BACKEND_ROUGH},
    "plane": {"rms": 0.0, "backend": BACKEND_PLANE},
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="bowl")
    parser.add_argument("--rms", type=float, default=None)
    parser.add_argument("--budget", type=float, default=0.01)
    parser.add_argument("--max-cells", type=int, default=400000)
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--backend", default=None)
    parser.add_argument("--label", default="measure")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    rows = []
    for name in [c.strip() for c in args.cases.split(",") if c.strip()]:
        preset = dict(CASES.get(name, {}))
        rms = float(args.rms) if args.rms is not None else float(preset.get("rms", 0.05))
        backend = args.backend or str(preset.get("backend", BACKEND_ROUGH))
        print(f"[run] {name} rms={rms} budget={args.budget} max_cells={args.max_cells} "
              f"backend={backend}", flush=True)
        row = run_case(name, rms=rms, budget=args.budget, max_cells=args.max_cells,
                       seed=args.seed, backend=backend)
        rows.append(row)
        summary = {k: v for k, v in row.items()
                   if k not in ("measurements", "height_field")
                   and not (k == "measurements")}
        print(f"  -> {json.dumps(summary, ensure_ascii=False)}", flush=True)
        if row.get("measurements"):
            compact = {k: v for k, v in row["measurements"].items()
                       if k not in ("first_missing", "ambiguous_directed_examples",
                                    "bad_edge_details")}
            print(f"     measurements: {json.dumps(compact, ensure_ascii=False)[:900]}", flush=True)
    out = Path(args.out) if args.out else (
        REPO_ROOT / "data" / "a12_reports" / "tjunction" / f"measure_{args.label}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"label": args.label, "rows": rows}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"[written] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
