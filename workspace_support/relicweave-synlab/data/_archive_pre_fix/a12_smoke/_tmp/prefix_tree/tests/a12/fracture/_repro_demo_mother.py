#!/usr/bin/env python
"""Diagnose *where* the failure happens on the demo mother (cutter vs boolean).

Loads the real stored demo mother (``data/a12_demo/store``), rebuilds the shared cutter for a
backend exactly like ``tools/build_demo_assets.py::task_fracture`` does and reports:

* the cutter build report + edge-use histogram of C;
* the edge-use histogram of the Manifold outputs ``M ∩ C`` and ``M \\ C`` (so a non-watertight
  boolean is attributed to a concrete edge multiplicity instead of a boolean).

Usage:

```powershell
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_repro_demo_mother.py --vessel V01 --backend plane_shared_cut
```
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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MASTER_SEED = 20261001
LINEAGE_ID = "a12_demo"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return {"shape": list(value.shape), "dtype": str(value.dtype)}
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if hasattr(value, "as_dict"):
        return _jsonable(value.as_dict())
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _jsonable({k: v for k, v in vars(value).items()})
    return str(value)


def edge_histogram(mesh: Any) -> dict[str, Any]:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    counter: Counter[tuple[int, int]] = Counter()
    for tri in faces:
        for k in range(3):
            a, b = int(tri[k]), int(tri[(k + 1) % 3])
            counter[(min(a, b), max(a, b))] += 1
    hist = Counter(counter.values())
    boundary = int(sum(1 for n in counter.values() if n == 1))
    return {
        "faces": int(faces.shape[0]),
        "vertices": int(np.asarray(mesh.vertices).shape[0]),
        "unique_edges": len(counter),
        "edge_use_histogram": {str(k): int(v) for k, v in sorted(hist.items())},
        "boundary_edges": boundary,
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "volume_mm3": float(mesh.volume) if faces.shape[0] else 0.0,
        "area_mm2": float(mesh.area) if faces.shape[0] else 0.0,
        "duplicate_vertices": int(len(np.asarray(mesh.vertices)) -
                                  len(np.unique(np.round(np.asarray(mesh.vertices), 9), axis=0))),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V01")
    parser.add_argument("--backend", default="plane_shared_cut")
    parser.add_argument("--budget", type=float, default=0.0, help="override error budget (mm)")
    parser.add_argument("--rms", type=float, default=0.05)
    parser.add_argument("--out", default="")
    parser.add_argument("--demo-root", default=str(REPO_ROOT / "data" / "a12_demo"))
    args = parser.parse_args()

    from synlab.fracture.api import make_closed_cutter
    from synlab.fracture.booleans import boolean_difference, boolean_intersection, tag_source
    from synlab.fracture.spec import FractureSpec
    from synlab.mothers.api import load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    manifest = json.loads((Path(args.demo_root) / "demo_manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["entries"] if e["entry_id"] == f"mother:{args.vessel}")
    store = AssetStore(Path(args.demo_root) / "store")
    mother = load_mother(store, str(entry["asset_id"]))

    report: dict[str, Any] = {
        "vessel_id": args.vessel,
        "backend": args.backend,
        "mother_asset": str(entry["asset_id"]),
        "mother": {
            "faces": int(len(mother.mesh.faces)),
            "watertight": bool(mother.mesh.is_watertight),
            "volume_mm3": float(abs(mother.mesh.volume)),
        },
    }
    report["mother"].update(edge_histogram(mother.mesh))
    print(f"[mother] {args.vessel} asset={entry['asset_id']} faces={report['mother']['faces']} "
          f"watertight={report['mother']['watertight']} "
          f"hist={report['mother']['edge_use_histogram']} "
          f"dup_vertices={report['mother']['duplicate_vertices']}", flush=True)

    spec = FractureSpec(backend=args.backend, target_rms_mm=float(args.rms))
    if args.budget:
        spec.error_budget_mm = float(args.budget)
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", args.vessel, args.backend)

    t0 = time.time()
    cutter = make_closed_cutter(mother, spec, rng)
    report["cutter_build_s"] = round(time.time() - t0, 3)
    report["cutter"] = edge_histogram(cutter.mesh)
    report["cutter_report"] = _jsonable({k: v for k, v in cutter.meta.items() if k != "height_field"})
    report["cutter_height_field"] = _jsonable(cutter.meta.get("height_field"))
    print(f"[cutter] {report['cutter']}", flush=True)
    print(f"[cutter-report] {json.dumps(report['cutter_report'], ensure_ascii=False)[:1200]}", flush=True)

    sm = tag_source(mother.mesh, 1.0, "mother")
    sc = tag_source(cutter.mesh, 2.0, "cutter")
    minus = boolean_intersection([sm, sc], label="M_minus")
    report["M_minus"] = edge_histogram(minus.mesh)
    print(f"[M-] {report['M_minus']}", flush=True)
    plus = boolean_difference([sm, sc], label="M_plus")
    report["M_plus"] = edge_histogram(plus.mesh)
    print(f"[M+] {report['M_plus']}", flush=True)

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[written] {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
