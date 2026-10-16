#!/usr/bin/env python
"""Run one real fracture event on a real mother and print the measured QA table.

This is the measurement harness behind the evidence document: it loads a *real* mother (from the
demo store when it exists, otherwise generated through ``synlab.mothers.api``), runs
``fracture_event`` with the requested backend and reports the audit numbers that the plan's A06
requires (volume conservation, overlap, shared-surface P95 distance and normal reversal, source
coverage, ambiguity area ratio) plus the cutter report.

Usage:

```powershell
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_run_event.py --vessel V01 --backend plane_shared_cut
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_run_event.py --vessel V13 --backend rough_shared_cut --out docs\\a12\\evidence\\event_V13_rough.json
```
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
LINEAGE_ID = "a12_demo"


def _jsonable(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
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
        return {"shape": list(value.shape), "dtype": str(value.dtype)}
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "as_dict"):
        return _jsonable(value.as_dict(), depth=depth + 1)
    if hasattr(value, "__dict__"):
        return _jsonable({k: v for k, v in vars(value).items()}, depth=depth + 1)
    return str(value)


def load_mother(vessel_id: str, material_id: str, *, demo_root: Path | None,
                seed: int) -> tuple[Any, str]:
    """Use the stored demo mother when present, otherwise generate a real one."""
    if demo_root is not None:
        manifest_path = demo_root / "demo_manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entry = next((e for e in manifest["entries"]
                          if e["entry_id"] == f"mother:{vessel_id}"), None)
            if entry and entry.get("asset_id"):
                from synlab.mothers.api import load_mother as _load
                from synlab.storage.store import AssetStore

                store = AssetStore(demo_root / "store")
                return _load(store, str(entry["asset_id"])), f"demo_store:{entry['asset_id']}"
    from synlab.mothers.api import create_mother, sample_parameters
    from synlab.seeds import make_rng

    rng = make_rng(seed, LINEAGE_ID, "mothers", vessel_id)
    params = sample_parameters(vessel_id, 1, rng, require_feasible=True)[0]
    mother = create_mother(vessel_id, material_id, params, rng,
                           mother_id=f"{LINEAGE_ID}_{vessel_id}")
    return mother, "synlab.mothers.api.create_mother"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", default="V01")
    parser.add_argument("--material", default="M01")
    parser.add_argument("--backend", default="plane_shared_cut")
    parser.add_argument("--rms", type=float, default=0.05)
    parser.add_argument("--budget", type=float, default=0.0)
    parser.add_argument("--demo-root", default=str(REPO_ROOT / "data" / "a12_demo"))
    parser.add_argument("--no-demo", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from synlab.errors import SynLabError
    from synlab.fracture.api import audit_fracture, fracture_event
    from synlab.fracture.spec import FractureSpec
    from synlab.seeds import make_rng

    report: dict[str, Any] = {"vessel_id": args.vessel, "backend": args.backend,
                              "material_id": args.material, "master_seed": MASTER_SEED}
    started = time.time()
    demo_root = None if args.no_demo else Path(args.demo_root)
    mother, source = load_mother(args.vessel, args.material, demo_root=demo_root,
                                 seed=MASTER_SEED)
    bounds = np.asarray(mother.mesh.bounds, dtype=np.float64)
    report["mother_source"] = source
    report["mother"] = {
        "faces": int(len(mother.mesh.faces)), "vertices": int(len(mother.mesh.vertices)),
        "watertight": bool(mother.mesh.is_watertight),
        "volume_mm3": float(abs(mother.mesh.volume)), "area_mm2": float(mother.mesh.area),
        "extent_mm": (bounds[1] - bounds[0]).tolist(),
    }
    print(f"[mother] {args.vessel} faces={report['mother']['faces']} "
          f"extent={np.round(bounds[1] - bounds[0], 3).tolist()} src={source}", flush=True)

    spec = FractureSpec(backend=args.backend, target_rms_mm=float(args.rms))
    if args.budget:
        spec.error_budget_mm = float(args.budget)
    rng = make_rng(MASTER_SEED, LINEAGE_ID, "fracture", args.vessel, args.backend)
    event_id = f"{LINEAGE_ID}_{args.vessel}_{args.backend}"
    try:
        result = fracture_event(mother, spec, rng, event_id=event_id)
        qa = audit_fracture(result, mother)
        report["status"] = "OK"
        report["event"] = {
            "fragments": len(result.fragments),
            "tiny": int(sum(1 for f in result.fragments if f.is_tiny)),
            "debris": len(result.debris),
            "interfaces": len(result.interfaces),
            "cutter_ref": result.cutter_ref,
            "backend": result.backend,
            "fragment_volumes_mm3": [float(f.volume_mm3) for f in result.fragments],
            "fragment_faces": [int(len(f.mesh.faces)) for f in result.fragments],
            "interface_areas_mm2": [float(p.area_mm2) for p in result.interfaces],
            "interface_area_mm2_total": float(sum(float(p.area_mm2)
                                                  for p in result.interfaces)),
            "unmatched_interface_faces": int(result.meta.get("unmatched_interface_faces", 0)),
            "unmatched_interface_area_mm2": float(
                result.meta.get("unmatched_interface_area_mm2", 0.0)),
        }
        matched_area = report["event"]["interface_area_mm2_total"]
        unmatched_area = report["event"]["unmatched_interface_area_mm2"]
        report["event"]["unmatched_interface_area_ratio"] = float(
            unmatched_area / max(matched_area + unmatched_area, 1e-12))
        report["qa"] = _jsonable(qa)
        report["event_tree"] = _jsonable(result.event_tree)
        print(f"[event] OK fragments={report['event']['fragments']} "
              f"interfaces={report['event']['interfaces']}", flush=True)
        print(f"[qa] volume_rel={qa.get('volume_rel_diff'):.3e} "
              f"overlap={qa.get('overlap_ratio'):.3e} "
              f"gap_p95={qa.get('gap_p95_mm_max'):.4f}mm "
              f"normal_p95={qa.get('normal_angle_p95_deg_max'):.4f}deg "
              f"coverage={qa.get('source_coverage'):.4f} "
              f"ambiguity={qa.get('ambiguous_area_ratio_total'):.3e} "
              f"passed={qa.get('passed')}", flush=True)
    except BaseException as exc:  # noqa: BLE001 - the failure itself is the measurement
        report["status"] = "FAILED"
        if isinstance(exc, SynLabError):
            report["failure"] = {"code": getattr(exc.code, "value", str(exc.code)),
                                 "stage": exc.stage, "message": exc.message,
                                 "measurements": _jsonable(exc.measurements)}
        else:
            report["failure"] = {"code": type(exc).__name__, "message": str(exc),
                                 "traceback_tail": traceback.format_exc()[-1200:]}
        print(f"[event] FAILED {report['failure'].get('code')} @ "
              f"{report['failure'].get('stage', '')}\n    {report['failure'].get('message')}",
              flush=True)
    report["duration_s"] = round(time.time() - started, 3)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[written] {args.out}", flush=True)
    return 0 if report["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
