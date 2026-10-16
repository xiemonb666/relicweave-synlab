#!/usr/bin/env python
"""Reproduce the shared-cutter failure on a real mother (plan 10.1 step 5).

Minimal, self-contained: build the real mother through ``synlab.mothers.api``, then call
``synlab.fracture.api.make_closed_cutter`` for both required backends and print the
*structured* error (code / stage / measurements) plus the raw edge-use histogram.

Usage (PowerShell):

```powershell
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_repro_cutter.py --vessel V01 --material M01
```

The script never swallows an exception: it prints the real ``SynLabError`` fields and exits
with ``1`` when either backend fails, ``0`` when both succeed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MASTER_SEED = 20261001


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return {"shape": list(value.shape), "dtype": str(value.dtype)}
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def failure_block(exc: BaseException) -> dict[str, Any]:
    from synlab.errors import SynLabError

    if isinstance(exc, SynLabError):
        return {
            "code": getattr(exc.code, "value", str(exc.code)),
            "stage": exc.stage,
            "message": exc.message,
            "measurements": _jsonable(exc.measurements),
            "traceback_tail": traceback.format_exc()[-800:],
        }
    return {
        "code": type(exc).__name__,
        "stage": "",
        "message": str(exc),
        "measurements": {},
        "traceback_tail": traceback.format_exc()[-800:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V01")
    parser.add_argument("--material", default="M01")
    parser.add_argument("--backends", default="plane_shared_cut,rough_shared_cut")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from synlab.fracture.api import make_closed_cutter
    from synlab.fracture.spec import FractureSpec
    from synlab.mothers.api import create_mother, sample_parameters
    from synlab.seeds import make_rng

    report: dict[str, Any] = {"vessel_id": args.vessel, "material_id": args.material,
                              "master_seed": MASTER_SEED, "backends": {}}
    started = time.time()
    rng = make_rng(MASTER_SEED, "a12_fracture_fix", "repro", args.vessel)
    params = sample_parameters(args.vessel, 1, rng, require_feasible=True)[0]
    mother = create_mother(args.vessel, args.material, params, rng,
                           mother_id=f"repro_{args.vessel}_{args.material}")
    bounds = np.asarray(mother.mesh.bounds, dtype=np.float64)
    report["mother"] = {
        "faces": int(len(mother.mesh.faces)),
        "vertices": int(len(mother.mesh.vertices)),
        "watertight": bool(mother.mesh.is_watertight),
        "volume_mm3": float(abs(mother.mesh.volume)),
        "area_mm2": float(mother.mesh.area),
        "extent_mm": (bounds[1] - bounds[0]).tolist(),
        "params": _jsonable(params),
    }
    print(f"[mother] {args.vessel}/{args.material} faces={report['mother']['faces']} "
          f"extent={np.round(bounds[1] - bounds[0], 3).tolist()} "
          f"watertight={report['mother']['watertight']}", flush=True)

    failures = 0
    for backend in [b for b in args.backends.split(",") if b]:
        entry: dict[str, Any] = {"backend": backend}
        t0 = time.time()
        try:
            spec = FractureSpec(backend=backend, target_rms_mm=0.05)
            cutter = make_closed_cutter(mother, spec, rng)
            entry.update({
                "status": "OK",
                "triangles": int(cutter.triangles),
                "realized_error_mm": float(cutter.realized_error_mm),
                "requested_error_mm": float(cutter.requested_error_mm),
                "watertight": bool(cutter.mesh.is_watertight),
                "cutter_hash": cutter.meta.get("cutter_hash"),
                "report": _jsonable({k: v for k, v in cutter.meta.items()
                                     if k not in ("height_field",)}),
            })
            print(f"[{backend}] OK triangles={entry['triangles']} "
                  f"realized_error={entry['realized_error_mm']:.6g}", flush=True)
        except BaseException as exc:  # noqa: BLE001 - the failure itself is the evidence
            failures += 1
            entry.update({"status": "FAILED", "failure": failure_block(exc)})
            print(f"[{backend}] FAILED {entry['failure']['code']} @ {entry['failure']['stage']}\n"
                  f"    {entry['failure']['message']}", flush=True)
        entry["duration_s"] = round(time.time() - t0, 3)
        report["backends"][backend] = entry

    report["duration_s"] = round(time.time() - started, 3)
    text = json.dumps(report, ensure_ascii=False, indent=1, sort_keys=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[written] {args.out}", flush=True)
    else:
        print(text, flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
