"""Step 15a (post-fix): trace the real profile-helper calls of ONE vessel, one process.

Usage:  python s15_trace_helpers.py <VID> [--out DIR]

Same tracer policy as ``mother_geometry_audit/s05_trace_helpers.py`` (wrap the helper
attributes in the already-imported vessel modules; no repository file is touched), but it
follows the **post-fix** names: the filter is now ``advancing_control_points``.

The two numbers that mattered in the pre-fix audit are recorded per call:

* ``out_r_span``  - the radius span of the points ``wall_points`` returns.  Pre-fix this was
  ``0.0000`` for all 15 call sites (defect A1, the wall was clamped flat).
* ``n_dropped``   - how many mid-line control points the filter removed.  Pre-fix the
  radius-monotone filter dropped the whole shoulder/neck cone of the 7 neck vessels (A2).

A post-fix sweep with ``out_r_span > 0`` on the widening calls and ``n_dropped == 0`` on every
call is the direct measurement that A1/A2 are gone.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

from synlab.mothers.api import create_mother, default_params  # noqa: E402
from synlab.mothers.vessels import common as common_mod  # noqa: E402
from synlab.mothers.vessels import (group_composite, group_extrude,  # noqa: E402
                                    group_revolve, group_sheet)
from synlab.seeds import make_rng, seed64  # noqa: E402

MODULES = (group_composite, group_extrude, group_revolve, group_sheet)
TRACE: list[dict] = []


def _pts(value) -> list[list[float]]:
    return [[round(float(r), 6), round(float(z), 6)] for r, z in value]


def make_wall_points_wrapper(original):
    def wrapper(*args, **kwargs):
        out = original(*args, **kwargs)
        radii = [float(r) for r, _ in out]
        TRACE.append({
            "helper": "wall_points",
            "call": {k: (float(v) if isinstance(v, (int, float)) else v)
                     for k, v in kwargs.items()},
            "n_out": len(out),
            "out_r_min": min(radii), "out_r_max": max(radii),
            "out_r_span": max(radii) - min(radii),
            "out": _pts(out),
        })
        return out
    return wrapper


def make_filter_wrapper(original):
    def wrapper(ctrl, **kwargs):
        out = original(ctrl, **kwargs)
        ctrl_arr = np.asarray(ctrl, dtype=np.float64)
        TRACE.append({
            "helper": "advancing_control_points",
            "n_in": int(len(ctrl_arr)), "n_out": int(len(out)),
            "n_dropped": int(len(ctrl_arr) - len(out)),
            "kept_z_advances": bool(np.all(np.diff(np.asarray(out)[:, 1]) > 0)),
            "in": _pts(ctrl_arr), "out": _pts(out),
        })
        return out
    return wrapper


def install() -> None:
    common_mod.wall_points = make_wall_points_wrapper(common_mod.wall_points)
    for module in MODULES:
        if hasattr(module, "wall_points"):
            module.wall_points = make_wall_points_wrapper(module.wall_points)
    common_mod.advancing_control_points = make_filter_wrapper(
        common_mod.advancing_control_points)
    # keep the legacy alias honest if it is ever reintroduced
    if hasattr(common_mod, "monotone_radius_control_points"):
        common_mod.monotone_radius_control_points = make_filter_wrapper(
            common_mod.monotone_radius_control_points)


def main(argv: list[str]) -> int:
    vessel_id = argv[1]
    out_dir = Path(argv[argv.index("--out") + 1]) if "--out" in argv else HERE / "trace_parts"
    install()
    row: dict = {"vessel_id": vessel_id, "params_source": "registry defaults"}
    started = time.time()
    try:
        params = default_params(vessel_id)
        row["params"] = {k: (float(v) if isinstance(v, float) else v)
                         for k, v in sorted(params.items())}
        rng = make_rng(int(seed64(0xA12, vessel_id, "mother_geometry_audit")), vessel_id, "audit")
        mother = create_mother(vessel_id, "M01", dict(params), rng,
                               mother_id=f"{vessel_id}-audit-fixed")
        row["status"] = "OK"
        row["registry_version"] = (mother.meta or {}).get("registry_version")
        row["geometry_hash"] = (mother.meta or {}).get("geometry_hash")
        wall_calls = [t for t in TRACE if t["helper"] == "wall_points"]
        filt_calls = [t for t in TRACE if t["helper"].endswith("control_points")]
        row["n_wall_points_calls"] = len(wall_calls)
        row["n_filter_calls"] = len(filt_calls)
        row["wall_points_r_span_max"] = max((t["out_r_span"] for t in wall_calls), default=None)
        row["wall_points_all_flat"] = (bool(wall_calls)
                                       and all(t["out_r_span"] <= 1e-9 for t in wall_calls))
        row["filter_dropped_total"] = sum(t["n_dropped"] for t in filt_calls)
        row["filter_all_z_advance"] = all(t["kept_z_advances"] for t in filt_calls)
        row["trace"] = TRACE
    except Exception as exc:  # never swallowed
        code = getattr(getattr(exc, "code", None), "value", None) or getattr(exc, "code", None)
        row.update({"status": "RAISED", "error_type": type(exc).__name__,
                    "error_code": str(code) if code is not None else None,
                    "error": str(exc)[:1500], "traceback": traceback.format_exc()[-2000:],
                    "trace": TRACE})
    row["seconds"] = round(time.time() - started, 2)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{vessel_id}.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"{vessel_id}: status={row['status']} wall_calls={row.get('n_wall_points_calls')} "
          f"span_max={row.get('wall_points_r_span_max')} "
          f"dropped={row.get('filter_dropped_total')} seconds={row['seconds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
