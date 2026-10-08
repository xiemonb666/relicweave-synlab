"""Step 2 (read-only): numeric chain of the flagged profile helpers.

Calls the real ``wall_points`` / ``monotone_radius_control_points`` / ``shell_profile``
with the arguments the builders actually pass, and prints input -> output control points
plus the resulting profile metrics.  No mesh is built, so this is cheap.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from synlab.mothers.vessels.common import (monotone_radius_control_points, shell_profile,
                                           wall_points)

OUT = Path(__file__).resolve().parent


def show(label: str, pts) -> None:
    print(f"  {label}: " + ", ".join(f"({r:.3f},{z:.3f})" for r, z in pts))


def main() -> int:
    report: dict = {}

    # ---- 1. wall_points with an INCREASING target radius (every non-neck call site) -----
    print("== wall_points: rising target (r_start=12 -> R=40), exponent 0.75, count 6")
    rising = wall_points(r_start_mm=12.0, R_mm=40.0, z_start=0.0, z_rim_mm=50.0,
                         count=6, exponent=0.75)
    show("out", rising)
    report["wall_points_rising"] = rising

    print("== wall_points: rising target WITH flare (V01-style, flare_mm=4)")
    flared = wall_points(r_start_mm=12.0, R_mm=40.0, z_start=0.0, z_rim_mm=50.0,
                         count=6, exponent=0.75, flare_mm=4.0, flare_from=0.7)
    show("out", flared)
    report["wall_points_flared"] = flared

    # ---- 2. the shoulder-cone pattern used by V06/V07/V08/V09/V10/V11/V16 ---------------
    print("== shoulder pattern: wall_points to z_shoulder, then decreasing neck points")
    r_belly, r_mouth, t_b, h = 76.8, 23.1, 10.65, 352.128
    z_sh = t_b / 2.0 + 0.6 * h
    z_rim = t_b / 2.0 + h
    belly = wall_points(r_start_mm=0.55 * r_belly, R_mm=r_belly, z_start=t_b / 2.0 + 0.7 * t_b,
                        z_rim_mm=z_sh, count=4, exponent=0.62)
    show("belly_wall (input)", belly)
    shoulder = [(r_belly + (r_mouth - r_belly) * ((i / 4.0) ** 0.6),
                 z_sh + (z_rim - z_sh) * (i / 4.0)) for i in range(1, 5)]
    show("shoulder/neck (input)", shoulder)
    wall = belly + shoulder
    base_pts = [(0.0, t_b / 2.0), (0.55 * 0.55 * r_belly, t_b / 2.0 + 0.6 * t_b)]
    ctrl_in = np.asarray(base_pts + wall[1:], dtype=np.float64)
    show("shell_profile ctrl IN  (base + wall[1:])", ctrl_in)
    ctrl_out = monotone_radius_control_points(ctrl_in)
    show("ctrl OUT (after monotone_radius_control_points)", ctrl_out)
    report["ctrl_in"] = ctrl_in.tolist()
    report["ctrl_out"] = ctrl_out.tolist()
    report["z_shoulder"] = z_sh
    report["z_rim_target"] = z_rim

    prof = shell_profile(R_mm=r_belly, z_rim_mm=z_rim, base_pts=base_pts, wall_pts=wall,
                         t_base_mm=t_b, t_wall_mm=2.8443, rim_mode="flat", min_wall_mm=1.2,
                         stage="audit.probe")
    print(f"  profile.z_rim (MEASURED)   = {prof.z_rim:.4f}")
    print(f"  profile z_rim_target_mm    = {prof.metrics['z_rim_target_mm']:.4f}")
    print(f"  profile.z_bottom           = {prof.z_bottom:.4f}")
    print(f"  profile.r_max              = {prof.r_max:.4f}")
    print(f"  shortfall                  = {prof.metrics['z_rim_target_mm'] - prof.z_rim:.4f}")
    report["profile_z_rim"] = prof.z_rim
    report["profile_r_max"] = prof.r_max
    report["profile_z_bottom"] = prof.z_bottom

    # ---- 3. control: a genuinely monotone rising profile for comparison ----------------
    print("== control: monotone rising ctrl passes through unchanged")
    rising_ctrl = np.asarray([(0.0, 0.0), (20.0, 5.0), (40.0, 30.0), (55.0, 60.0), (60.0, 90.0)],
                             dtype=np.float64)
    show("in", rising_ctrl)
    show("out", monotone_radius_control_points(rising_ctrl))

    (OUT / "s02_chain.json").write_text(json.dumps(report, indent=2, sort_keys=True),
                                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
