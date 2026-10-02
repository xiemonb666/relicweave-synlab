#!/usr/bin/env python
"""Real-cutter topology probe: does a *refined* shared cutter come out watertight now?

Builds cutters through the production path (``synlab.fracture.api.make_closed_cutter``) on

* analytic fixtures (thin bowl, boxes) and, when ``--vessel``/``--material`` are given, on a real
  frozen mother from ``synlab.mothers.api.create_mother``;

and reports, per configuration, the numbers the A07 contract cares about:

* ``cells`` / ``leaf_level`` / ``triangles`` and the wall time;
* ``edge_use_histogram`` of the exported solid (must be ``{"2": <edges>}``);
* ``is_watertight`` / ``is_winding_consistent`` / signed volume;
* the per-cell ``n_split`` census of the leaves (how many leaves have 1, 2, 3 or 4 split edges),
  which is what tells us whether the fixed point really leaves mixed generations behind.

Everything is written to ``data/a12_reports/cutfix/cutter_topology_<label>.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.errors import SynLabError  # noqa: E402
from synlab.fracture import cut as cut_mod  # noqa: E402
from synlab.fracture.api import make_closed_cutter  # noqa: E402
from synlab.fracture.spec import BACKEND_PLANE, BACKEND_ROUGH, FractureSpec  # noqa: E402


def edge_use(mesh: Any) -> dict[str, int]:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    a = faces[:, [0, 1, 2]].ravel()
    b = faces[:, [1, 2, 0]].ravel()
    low = np.minimum(a, b)
    high = np.maximum(a, b)
    keys = np.stack([low, high], axis=1)
    unique, counts = np.unique(keys, axis=0, return_counts=True)
    histogram = Counter(counts.tolist())
    del unique
    return {str(k): int(v) for k, v in sorted(histogram.items())}


def build_with_census(mother, spec, rng, label: str) -> dict[str, Any]:
    """Build a cutter and census the split pattern by wrapping ``cell_triangles``."""
    census: Counter[int] = Counter()
    original = cut_mod._Quadtree.cell_triangles

    def wrapped(self, i, j, level, span):
        pts, tris = original(self, i, j, level, span)
        census[int(tris.shape[0])] += 1
        return pts, tris

    cut_mod._Quadtree.cell_triangles = wrapped  # type: ignore[method-assign]
    started = time.perf_counter()
    try:
        cutter = make_closed_cutter(mother, spec, rng)
    finally:
        cut_mod._Quadtree.cell_triangles = original  # type: ignore[method-assign]
    elapsed = time.perf_counter() - started

    mesh = cutter.mesh
    histogram = edge_use(mesh)
    report = dict(cutter.meta or {})
    out: dict[str, Any] = {
        "label": label,
        "backend": str(spec.backend),
        "mother_id": getattr(mother, "mother_id", "?"),
        "target_rms_mm": float(getattr(spec, "target_rms_mm", 0.0)),
        "error_budget_mm": float(getattr(spec, "error_budget_mm", 0.0)),
        "max_cells": int(getattr(spec, "max_cutter_cells", 0)),
        "seconds": float(elapsed),
        "status": "OK",
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "volume_mm3": float(mesh.volume),
        "edge_use_histogram": histogram,
        "bad_edges": int(sum(v for k, v in histogram.items() if k != "2")),
        "vertices": int(np.asarray(mesh.vertices).shape[0]),
        "faces": int(np.asarray(mesh.faces).shape[0]),
        "realized_error_mm": float(getattr(cutter, "realized_error_mm", float("nan"))),
        "requested_error_mm": float(getattr(cutter, "requested_error_mm", float("nan"))),
        "cells": report.get("cells"),
        "leaf_level": report.get("leaf_level"),
        "top_triangles": report.get("top_triangles"),
        "bottom_triangles": report.get("bottom_triangles"),
        "side_triangles": report.get("side_triangles"),
        "degenerate_faces": report.get("degenerate_faces"),
        "edge_use_histogram_reported": report.get("edge_use_histogram"),
        "height_flat": bool((report.get("height_field") or {}).get("flat", True)),
        "wavelength_min_mm": (report.get("height_field") or {}).get("wavelength_min_mm"),
        # census of triangles per leaf cell: 2 = no split, 1+n = unified fan with n split edges
        "triangles_per_leaf_census": {str(k): int(v) for k, v in sorted(census.items())},
    }
    return out


def fixture_mothers() -> dict[str, Any]:
    import fixtures as fx

    return {
        "bowl_thin": fx.thin_bowl_mother(),
        "box20": fx.box_mother((20.0, 20.0, 20.0)),
    }


def real_mother(vessel: str, material: str):
    from synlab.mothers.api import create_mother
    from synlab.seeds import make_rng

    return create_mother(vessel, material, {}, make_rng(20261001, "shape"),
                         mother_id=f"{vessel}-{material}-cutfix")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="head")
    parser.add_argument("--vessel", default=None)
    parser.add_argument("--material", default="M01")
    parser.add_argument("--rms", type=float, default=0.05)
    parser.add_argument("--budget", type=float, default=0.01)
    parser.add_argument("--max-cells", type=int, default=30000)
    parser.add_argument("--cases", default="bowl,box,plane-bowl,zero-rough")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from synlab.seeds import make_rng

    mothers: dict[str, Any] = {}
    wanted = args.cases.split(",")
    need_fixtures = any(name in wanted for name in ("bowl", "box", "plane-bowl", "zero-rough"))
    if need_fixtures:
        mothers.update(fixture_mothers())
    if "real" in wanted:
        if not args.vessel:
            print("--cases real needs --vessel")
            return 2
        mothers[f"real:{args.vessel}/{args.material}"] = real_mother(args.vessel, args.material)

    rows: list[dict[str, Any]] = []
    for name in wanted:
        name = name.strip()
        if name == "plane-bowl":
            mother, backend, rms = mothers["bowl_thin"], BACKEND_PLANE, 0.0
        elif name == "zero-rough":
            mother, backend, rms = mothers["box20"], BACKEND_ROUGH, 0.0
        elif name == "bowl":
            mother, backend, rms = mothers["bowl_thin"], BACKEND_ROUGH, args.rms
        elif name == "box":
            mother, backend, rms = mothers["box20"], BACKEND_ROUGH, args.rms
        elif name == "real":
            key = f"real:{args.vessel}/{args.material}"
            mother, backend, rms = mothers[key], BACKEND_ROUGH, args.rms
        else:
            continue
        spec = FractureSpec(backend=backend, target_rms_mm=rms, error_budget_mm=args.budget,
                            max_cutter_cells=int(args.max_cells))
        rng = make_rng(20261001, "cutfix_probe", name)
        label = f"{name}_rms{rms}_b{args.budget}_c{args.max_cells}"
        print(f"[run] {label}", flush=True)
        started = time.perf_counter()
        try:
            row = build_with_census(mother, spec, rng, label)
        except SynLabError as exc:
            row = {"label": label, "backend": backend, "target_rms_mm": float(rms),
                   "error_budget_mm": float(args.budget), "max_cells": int(args.max_cells),
                   "status": "REFUSED", "error_code": str(exc.code),
                   "message": str(exc)[:400], "measurements": dict(exc.measurements or {}),
                   "seconds": time.perf_counter() - started}
        except MemoryError as exc:  # pragma: no cover - resource guard
            row = {"label": label, "backend": backend, "target_rms_mm": float(rms),
                   "error_budget_mm": float(args.budget), "max_cells": int(args.max_cells),
                   "status": "MEMORY_ERROR", "message": str(exc)[:300],
                   "seconds": time.perf_counter() - started}
        rows.append(row)
        print(f"  -> {json.dumps(row, ensure_ascii=False)[:600]}", flush=True)

    out = Path(args.out) if args.out else (
        REPO_ROOT / "data" / "a12_reports" / "cutfix" / f"cutter_topology_{args.label}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"label": args.label, "rows": rows}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"[written] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
