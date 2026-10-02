"""Series driver (one process, one mother at a time, report rewritten after every row).

The sub-commands here are thin wrappers that exist because a single calibration series needs more
than one distinct piece count to be fittable, and the shipped configurations only reach 2-3 pieces
at the standard drop heights.  The instrument itself is :mod:`synlab.fracture.calibrate`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="calibration series driver")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("heights")
    p.add_argument("--out", required=True)
    p.add_argument("--vessels", default="V01,V13")
    p.add_argument("--materials", default="M01,M04")
    p.add_argument("--heights", default="2000,4000,8000")
    p.add_argument("--repeats", type=int, default=1)

    args = parser.parse_args(list(argv) if argv is not None else None)

    from synlab.fracture.calibrate import (
        body_stats_of, load_mother, material_stats_of, measure_one, write_report,
    )

    out = Path(args.out)
    payload: dict[str, Any] = {
        "schema": "synlab.fracture_calibration.heights.v1", "kind": "heights",
        "heights_mm": [float(v) for v in args.heights.split(",") if v.strip()], "rows": [],
    }
    for material_id in [m.strip() for m in args.materials.split(",") if m.strip()]:
        material = material_stats_of(material_id)
        for vessel_id in [v.strip() for v in args.vessels.split(",") if v.strip()]:
            mother = load_mother(vessel_id, material_id)
            body = body_stats_of(mother, vessel_id)
            for repeat in range(int(args.repeats)):
                for height in [float(v) for v in args.heights.split(",") if v.strip()]:
                    row = measure_one(vessel_id=vessel_id, material_id=material_id,
                                      drop_height_mm=height, seed=20261002 + repeat,
                                      mother=mother, body=body, material=material)
                    row["repeat"] = int(repeat)
                    payload["rows"].append(row)
                    write_report(out, payload)
                    m = row.get("measurement") or {}
                    print(f"{vessel_id}/{material_id} h={height:g} rep={repeat}: "
                          f"status={row['status']} pieces={m.get('pieces')} "
                          f"n_raw={((m.get('count_model') or {}).get('n_raw'))} "
                          f"open_cutters={(m.get('open_cutters'))} "
                          f"vol_rel={m.get('volume_rel_diff')}", flush=True)
    print("wrote", out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
