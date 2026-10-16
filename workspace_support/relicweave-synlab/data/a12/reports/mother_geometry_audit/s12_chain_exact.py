"""Step 12 (read-only w.r.t. the repository): the exact control-point chain.

Prints, with the *exact* frozen-batch parameters, every intermediate value of the two
profile guards: the builder's control points, what ``wall_points`` returns, which points
``monotone_radius_control_points`` drops, and the geometry the resulting profile produces -
before and after the proposed patch (the patch is applied in-process only).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

from s11_fix_simulation import (fixed_monotone_radius_control_points,  # noqa: E402
                                fixed_wall_points)

from synlab.mothers.vessels import common as common_mod  # noqa: E402

#: the untouched helpers, captured before anything is patched in this process
_ORIGINAL_WALL = common_mod.wall_points
_ORIGINAL_MONO = common_mod.monotone_radius_control_points

FROZEN = {
    "V10": {
        "base_mm": 10.649771173028173, "belly_ratio": 0.68991973127168,
        "diameter_mm": 222.77854733012697, "height_mm": 352.12756141776987,
        "knob_diameter_mm": 64.43440084462063, "lid_height_ratio": 0.568826035425881,
        "lid_seat_mm": 3.3710449924909853, "mouth_ratio": 0.30098125744230925,
        "wall_mm": 2.8443414248422236, "warp_amplitude": 0.016873063698682116,
        "warp_eccentricity_mm": 1.848518300460957, "warp_lobes": 2,
    },
    "V07": {   # registry prototype parameters (the worst measured shortfall, 201.50 mm)
        "diameter_mm": 190.0, "wall_mm": 4.0, "base_mm": 6.5, "height_mm": 240.0,
        "belly_ratio": 1.0, "neck_length_ratio": 0.32, "neck_ratio": 0.30,
        "shoulder_angle_deg": 52.0,
    },
}


def fmt(pts) -> str:
    return ", ".join(f"({float(r):.3f}, {float(z):.3f})" for r, z in pts)


def chain(vessel_id: str, p: dict, *, patched: bool) -> dict:
    # ``shell_profile`` lives in ``common`` and resolves both helpers as module globals, so the
    # in-process patch has to be installed there before the profile is built.
    common_mod.wall_points = fixed_wall_points if patched else _ORIGINAL_WALL
    common_mod.monotone_radius_control_points = (fixed_monotone_radius_control_points
                                                 if patched else _ORIGINAL_MONO)
    wall_fn = fixed_wall_points if patched else _ORIGINAL_WALL
    mono_fn = (fixed_monotone_radius_control_points if patched else _ORIGINAL_MONO)
    R = float(p["diameter_mm"]) / 2.0
    t_w, t_b = float(p["wall_mm"]), float(p["base_mm"])
    h = float(p["height_mm"])
    out: dict = {"vessel_id": vessel_id, "patched": patched,
                 "t_base_mm": t_b, "t_wall_mm": t_w, "height_mm": h,
                 "belly_r_mm": R * float(p.get("belly_ratio", 1.0))}

    if vessel_id == "V10":
        r_belly = R * float(p["belly_ratio"])
        r_mouth = r_belly * float(p["mouth_ratio"])
        z_rim = t_b / 2.0 + h
        z_shoulder = t_b / 2.0 + 0.6 * h
        r_base = 0.55 * r_belly
        base_pts = [(0.0, t_b / 2.0), (0.55 * r_base, t_b / 2.0 + 0.6 * t_b)]
        wall = wall_fn(r_start_mm=r_base, R_mm=r_belly, z_start=t_b / 2.0 + 0.7 * t_b,
                       z_rim_mm=z_shoulder, count=4, exponent=0.62)
        shoulder = [(float(r_belly + (r_mouth - r_belly) * ((i / 4.0) ** 0.6)),
                     float(z_shoulder + (z_rim - z_shoulder) * (i / 4.0))) for i in range(1, 5)]
        out.update({"R_asked_mm": r_belly, "r_mouth_declared_mm": r_mouth,
                    "z_rim_target_mm": z_rim, "z_shoulder_mm": z_shoulder,
                    "r_base_mm": r_base})
    else:  # V07 bottle
        r_belly = 0.5 * float(p["diameter_mm"]) * float(p["belly_ratio"])
        neck_len = float(p["neck_length_ratio"]) * h
        z_neck = t_b / 2.0 + h - neck_len
        z_rim = t_b / 2.0 + h
        r_neck = 0.5 * float(p["neck_ratio"]) * float(p["diameter_mm"])
        r_base = 0.6 * r_belly
        ang = np.deg2rad(float(p["shoulder_angle_deg"]))
        rise = max((r_belly - r_neck) * np.tan(ang) * 0.35, 1e-3)
        z_sh_end = max(min(z_neck, t_b / 2.0 + rise + t_b), t_b / 2.0 + 2.0)
        base_pts = [(0.0, t_b / 2.0), (0.55 * r_base, t_b / 2.0 + 0.55 * t_b)]
        wall = wall_fn(r_start_mm=r_base, R_mm=r_belly, z_start=t_b / 2.0 + 0.6 * t_b,
                       z_rim_mm=z_sh_end, count=4, exponent=0.72)
        span = max(z_rim - z_sh_end, t_w)
        shoulder = [(float(r_belly + (r_neck - r_belly) * ((i / 3.0) ** 0.7)),
                     float(z_sh_end + span * (i / 3.0))) for i in range(1, 4)]
        out.update({"R_asked_mm": r_belly, "r_neck_declared_mm": r_neck,
                    "z_rim_target_mm": z_rim, "z_shoulder_mm": z_sh_end,
                    "r_base_mm": r_base})

    ctrl_in = np.asarray(base_pts + wall[1:] + shoulder, dtype=np.float64)
    ctrl_out = mono_fn(ctrl_in)
    dropped = [row for row in ctrl_in.tolist()
               if not any(abs(row[0] - k[0]) < 1e-12 and abs(row[1] - k[1]) < 1e-12
                          for k in ctrl_out.tolist())]
    out.update({
        "base_pts": [[float(a), float(b)] for a, b in base_pts],
        "wall_points_out": [[float(a), float(b)] for a, b in wall],
        "shoulder_appended": [[float(a), float(b)] for a, b in shoulder],
        "ctrl_in": ctrl_in.tolist(),
        "ctrl_out": ctrl_out.tolist(),
        "dropped": dropped,
        "n_in": int(len(ctrl_in)), "n_out": int(len(ctrl_out)),
        "wall_out_r_span_mm": float(max(r for r, _ in wall) - min(r for r, _ in wall)),
    })

    profile = common_mod.shell_profile(
        R_mm=out["R_asked_mm"] if vessel_id == "V10" else out["R_asked_mm"],
        z_rim_mm=out["z_rim_target_mm"], base_pts=base_pts, wall_pts=wall + shoulder,
        t_base_mm=t_b, t_wall_mm=t_w,
        rim_mode="flat" if vessel_id == "V10" else "bevel",
        rim_bulge=1.0 if vessel_id == "V10" else 1.2,
        min_wall_mm=1.2, stage=f"audit.chain.{vessel_id}")
    out.update({"profile_z_rim": float(profile.z_rim),
                "profile_z_bottom": float(profile.z_bottom),
                "profile_r_max": float(profile.r_max),
                "profile_z_rim_target": float(profile.metrics["z_rim_target_mm"]),
                "shortfall_mm": float(profile.metrics["z_rim_target_mm"] - profile.z_rim)})
    return out


def main() -> int:
    rows = []
    for vessel_id, params in FROZEN.items():
        for patched in (False, True):
            row = chain(vessel_id, params, patched=patched)
            rows.append(row)
            tag = "PATCHED" if patched else "CURRENT"
            print(f"===== {vessel_id} [{tag}]")
            print(f"  R asked = {row['R_asked_mm']:.4f} mm, r_base = {row['r_base_mm']:.4f} mm, "
                  f"z_shoulder = {row['z_shoulder_mm']:.4f}, z_rim target = "
                  f"{row['z_rim_target_mm']:.4f}")
            print(f"  wall_points -> r span {row['wall_out_r_span_mm']:.6f} mm")
            print(f"  ctrl IN  ({row['n_in']}): {fmt(row['ctrl_in'])}")
            print(f"  ctrl OUT ({row['n_out']}): {fmt(row['ctrl_out'])}")
            print(f"  dropped  ({len(row['dropped'])}): {fmt(row['dropped'])}")
            print(f"  profile: z_rim={row['profile_z_rim']:.4f} "
                  f"z_bottom={row['profile_z_bottom']:.4f} r_max={row['profile_r_max']:.4f} "
                  f"shortfall={row['shortfall_mm']:.4f} mm")
            print()
    (HERE / "s12_chain_exact.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
