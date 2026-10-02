"""Acceptance rate of the production backends: N seeds x 2 backends, measured.

The batch chain accepts a lineage when the whole DAG completes; the fracture step is the first gate
that can refuse it, and it refuses on the *frozen* A06 audit.  This driver measures that gate
directly -- one event per seed per backend, with the same measured body and material -- so the
document can state a rate instead of a single lucky run.

Usage:

```powershell
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_run_acceptance.py --out data\\a12_reports\\fracture_acceptance.json
```
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REPORT_DIR = REPO_ROOT / "data" / "a12_reports"
SEEDS: tuple[int, ...] = (7, 11, 23, 47, 101, 20261002, 20261003, 20261004)
COUNTS: tuple[int, ...] = (4, 6)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(REPORT_DIR / "fracture_acceptance.json"))
    parser.add_argument("--vessel", default="V01")
    parser.add_argument("--material", default="M01")
    parser.add_argument("--counts", default=",".join(str(c) for c in COUNTS))
    args = parser.parse_args(list(argv) if argv is not None else None)

    from synlab.errors import SynLabError
    from synlab.fracture.api import fracture_event
    from synlab.fracture.calibrate import body_stats_of, load_mother, material_stats_of
    from synlab.fracture.spec import FractureSpec

    mother = load_mother(args.vessel, args.material)
    mother.vessel_id = args.vessel
    mother.material_id = args.material
    body = body_stats_of(mother, args.vessel)
    material = material_stats_of(args.material)
    out = Path(args.out)
    payload: dict[str, Any] = {
        "schema": "synlab.fracture_calibration.acceptance.v1",
        "vessel_id": args.vessel, "material_id": args.material,
        "mother_volume_mm3": float(body.volume_mm3), "wall_mm": float(body.wall_mm),
        "seeds": list(SEEDS), "counts": [int(c) for c in str(args.counts).split(",") if c.strip()],
        "runs": [],
    }
    for backend in ("plane_shared_cut", "warp_voronoi_cut"):
        for count in payload["counts"]:
            for seed in SEEDS:
                meta: dict[str, Any] = {"target_pieces": int(count)}
                started = time.perf_counter()
                row: dict[str, Any] = {"backend": backend, "target_pieces": int(count),
                                       "seed": int(seed)}
                try:
                    result = fracture_event(mother, FractureSpec(backend=backend, meta=meta),
                                            __import__("numpy").random.default_rng(int(seed)),
                                            event_id=f"ACC-{backend}-{count}-{seed}")
                    row["status"] = "OK"
                    row["pieces"] = int(len(result.fragments))
                    row["volume_rel_diff"] = float(result.qa["volume_rel_diff"])
                    row["gap_p95_mm_max"] = float(result.qa["gap_p95_mm_max"])
                    row["normal_p95_deg_max"] = float(result.qa["normal_angle_p95_deg_max"])
                    row["source_coverage"] = float(result.qa["source_coverage"])
                    row["ambiguous_area_ratio_total"] = float(
                        result.qa["ambiguous_area_ratio_total"])
                    row["open_cutter_count"] = int(result.meta.get("open_cutter_count", 0) or 0)
                    row["count_source"] = str(result.meta.get("count_source", ""))
                    row["n_raw"] = float((result.meta.get("count_model") or {}).get("n_raw", 0.0))
                except SynLabError as exc:
                    row["status"] = "REFUSED"
                    row["code"] = str(getattr(exc.code, "value", exc.code))
                    row["message"] = str(exc.message)[:200]
                    row["measurements"] = {k: v for k, v in (exc.measurements or {}).items()
                                           if isinstance(v, (int, float, str, list))}
                except BaseException as exc:  # noqa: BLE001 - the failure itself is a measurement
                    row["status"] = "ERROR"
                    row["code"] = type(exc).__name__
                    row["message"] = str(exc)[:200]
                row["seconds"] = round(time.perf_counter() - started, 3)
                payload["runs"].append(row)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
                print(f"{backend} n={count} seed={seed}: {row['status']} "
                      f"pieces={row.get('pieces')} {row.get('seconds')}s "
                      f"vol_rel={row.get('volume_rel_diff')} "
                      f"open={row.get('open_cutter_count')} "
                      f"{(row.get('message') or '')[:80]}", flush=True)
    summary: dict[str, Any] = {}
    for row in payload["runs"]:
        key = f"{row['backend']}|n={row['target_pieces']}"
        entry = summary.setdefault(key, {"runs": 0, "ok": 0, "refused": 0, "error": 0,
                                         "seconds": []})
        entry["runs"] += 1
        entry["ok" if row["status"] == "OK" else
              ("refused" if row["status"] == "REFUSED" else "error")] += 1
        entry["seconds"].append(row["seconds"])
    for key, entry in summary.items():
        seconds = sorted(entry.pop("seconds"))
        entry["median_seconds"] = seconds[len(seconds) // 2]
        entry["max_seconds"] = seconds[-1]
        entry["accept_rate"] = round(entry["ok"] / max(entry["runs"], 1), 4)
    payload["summary"] = summary
    out.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=1), flush=True)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
