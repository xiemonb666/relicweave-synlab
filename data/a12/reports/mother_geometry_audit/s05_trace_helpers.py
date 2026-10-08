"""Step 5 (read-only): trace the real profile-helper calls of every vessel builder.

Wraps ``wall_points`` / ``monotone_radius_control_points`` / ``shell_profile`` *in the
already-imported vessel modules* (no repository file is touched, the wrapper lives only in
this process) and builds each vessel once, recording:

* the exact arguments each builder passes,
* the control points the helper returns,
* how many control points the monotone filter dropped and which ones.

That is the "input control points -> output control points -> geometry" chain for all 24
vessels, taken from the real call sites instead of a re-implementation of the builders.
"""
from __future__ import annotations

import json
import sys
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


def _pts(value):
    return [[round(float(r), 6), round(float(z), 6)] for r, z in value]


def make_wall_points_wrapper(original):
    def wrapper(*args, **kwargs):
        out = original(*args, **kwargs)
        TRACE.append({"helper": "wall_points",
                      "call": {"kwargs": {k: (float(v) if isinstance(v, (int, float))
                                              else v) for k, v in kwargs.items()}},
                      "args": {k: v for k, v in kwargs.items() if k not in
                               ("r_start_mm", "R_mm", "z_start", "z_rim_mm", "count",
                                "exponent", "flare_mm", "flare_from")},
                      "out": _pts(out),
                      "out_r_min": min(float(r) for r, _ in out),
                      "out_r_max": max(float(r) for r, _ in out),
                      "out_r_span": max(float(r) for r, _ in out) - min(float(r) for r, _ in out)})
        return out
    return wrapper


def make_monotone_wrapper(original):
    def wrapper(ctrl, **kwargs):
        out = original(ctrl, **kwargs)
        TRACE.append({"helper": "monotone_radius_control_points",
                      "n_in": int(len(ctrl)), "n_out": int(len(out)),
                      "n_dropped": int(len(ctrl) - len(out)),
                      "in": _pts(ctrl), "out": _pts(out)})
        return out
    return wrapper


def make_shell_wrapper(original):
    def wrapper(**kwargs):
        prof = original(**kwargs)
        TRACE.append({"helper": "shell_profile",
                      "z_rim_mm_argument": float(kwargs.get("z_rim_mm", float("nan"))),
                      "R_mm_argument": float(kwargs.get("R_mm", float("nan"))),
                      "wall_pts": _pts(kwargs.get("wall_pts") or []),
                      "z_rim_measured": float(prof.z_rim),
                      "r_max_measured": float(prof.r_max)})
        return prof
    return wrapper


def main() -> int:
    wall_original = common_mod.wall_points
    mono_original = common_mod.monotone_radius_control_points
    shell_original = common_mod.shell_profile
    for module in MODULES:
        if hasattr(module, "wall_points"):
            module.wall_points = make_wall_points_wrapper(wall_original)
        if hasattr(module, "shell_profile"):
            module.shell_profile = make_shell_wrapper(shell_original)
    common_mod.monotone_radius_control_points = make_monotone_wrapper(mono_original)

    out: dict = {}
    for index in range(1, 25):
        vessel_id = f"V{index:02d}"
        TRACE.clear()
        params = default_params(vessel_id)
        try:
            rng = make_rng(int(seed64(0xA12, vessel_id, "mother_geometry_audit")), vessel_id,
                           "audit")
            mother = create_mother(vessel_id, "M01", dict(params), rng,
                                   mother_id=f"{vessel_id}-trace")
            status = "OK"
            meta_profile = dict((mother.meta or {}).get("profile_metrics") or {})
            del mother
        except Exception as exc:
            status = f"RAISED {type(exc).__name__}: {exc}"[:300]
            meta_profile = {}
        out[vessel_id] = {
            "status": status,
            "params": params,
            "profile_metrics": {k: v for k, v in meta_profile.items()
                                if isinstance(v, (int, float, bool))},
            "trace": json.loads(json.dumps(TRACE)),
        }
        wp = [t for t in TRACE if t["helper"] == "wall_points"]
        mono = [t for t in TRACE if t["helper"] == "monotone_radius_control_points"]
        print(f"{vessel_id}: {status}")
        for t in wp:
            print(f"   wall_points(r_start={t['call']['kwargs'].get('r_start_mm')}, "
                  f"R={t['call']['kwargs'].get('R_mm')}, count={t['call']['kwargs'].get('count')}, "
                  f"exp={t['call']['kwargs'].get('exponent')}) -> r_span={t['out_r_span']:.4f} "
                  f"(r in [{t['out_r_min']:.3f}, {t['out_r_max']:.3f}])")
        for t in mono:
            print(f"   monotone: {t['n_in']} in -> {t['n_out']} out (dropped {t['n_dropped']})")

    (HERE / "s05_trace.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
