#!/usr/bin/env python
"""Run one ``warped_partition`` event on a real mother and write the measured report.

    python tests\\a12\\fracture\\_run_warped_event.py --vessel V13 --material M01 --pieces 3 \\
        --out data/a12_reports/warped_partition_V13_M01.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vessel", default="V13")
    ap.add_argument("--material", default="M01")
    ap.add_argument("--pieces", type=int, default=0)
    ap.add_argument("--seed", type=int, default=20261002)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    from synlab.errors import SynLabError
    from synlab.fracture import warped
    from synlab.fracture.calibration import body_stats_of, material_stats_of
    from synlab.fracture.physics import load_physics_config
    from synlab.fracture.api import audit_fracture
    from synlab.mothers.api import create_mother, default_params, ensure_registered

    ensure_registered()
    mother = create_mother(args.vessel, args.material, default_params(args.vessel),
                           np.random.default_rng(args.seed))
    mother.vessel_id = args.vessel
    mother.material_id = args.material

    config = load_physics_config()
    body = body_stats_of(mother, args.vessel)
    material = material_stats_of(args.material)
    record: dict[str, object] = {
        "vessel": args.vessel, "material": args.material, "seed": args.seed,
        "requested_pieces": int(args.pieces),
        "mother_volume_mm3": float(abs(mother.mesh.volume)),
        "mother_wall_mm": float(body.wall_mm),
        "grain_mm": float(material.grain_size_mm),
    }
    started = time.time()
    try:
        result = warped.run_warped_partition(
            mother, event_id=f"WARP-{args.vessel}-{args.material}",
            config=config, rng=np.random.default_rng(args.seed), body=body, material=material,
            target_pieces=(int(args.pieces) if args.pieces > 0 else None))
        record["status"] = "OK"
        record["elapsed_s"] = round(time.time() - started, 3)
        record["backend"] = result.backend
        record["pieces"] = len(result.fragments)
        record["interfaces"] = len(result.interfaces)
        record["qa"] = result.qa
        record["warp"] = result.meta["warp"]
        record["warp_audit"] = result.meta["warp_audit"]
        record["volume_mesh_status"] = result.meta["volume_mesh_status"]
        record["volume_mesh_reason"] = result.meta["volume_mesh_reason"]
        record["partition"] = result.meta["partition"]
        record["fragment_volumes_mm3"] = [float(f.volume_mm3) for f in result.fragments]
        record["facet_conjugacy_planar"] = result.meta["facet_conjugacy_planar"]
        record["audit"] = audit_fracture(result, mother)
    except SynLabError as exc:
        record["status"] = "REFUSED"
        record["elapsed_s"] = round(time.time() - started, 3)
        record["error_code"] = str(getattr(exc.code, "value", exc.code))
        record["error_message"] = str(exc.message)
        record["measurements"] = _jsonable(exc.measurements or {})
    except Exception as exc:  # noqa: BLE001 - the probe reports, it never repairs
        record["status"] = "CRASH"
        record["elapsed_s"] = round(time.time() - started, 3)
        record["error_type"] = type(exc).__name__
        record["error_message"] = str(exc)
        record["traceback"] = traceback.format_exc()[-4000:]

    text = json.dumps(record, indent=2, ensure_ascii=False, default=_jsonable)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text[:12000])
    return 0


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
