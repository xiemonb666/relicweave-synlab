"""Step 11 (read-only w.r.t. the repository): simulate the proposed minimal fix.

The two helpers are replaced **in this process only** by the patched versions described in
``docs/a12/mother_geometry_audit.md``; no file under ``synlab/**`` is written.  Every vessel is
then rebuilt with the same parameters and seed as the audit, so the table below is a direct
before/after comparison.

Patch A1 (``wall_points``): return the sampled control points unchanged.  The "clamp every
rising radius to the first sample" rule is removed.
Patch A2 (``monotone_radius_control_points``): keep every point whose z advances (the mid-line
must rise), instead of dropping every point whose radius falls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

from mga_lib import component_report, gaps_between_components, jsonable  # noqa: E402

from synlab.errors import ErrorCode, SynLabError  # noqa: E402
from synlab.mothers.api import audit_mother, create_mother, default_params  # noqa: E402
from synlab.mothers.vessels import common as common_mod  # noqa: E402
from synlab.mothers.vessels import (group_composite, group_extrude,  # noqa: E402
                                    group_revolve, group_sheet)
from synlab.seeds import make_rng, seed64  # noqa: E402

MODULES = (group_composite, group_extrude, group_revolve, group_sheet)


def fixed_wall_points(*, r_start_mm: float, R_mm: float, z_start: float, z_rim_mm: float,
                      count: int = 6, exponent: float = 1.0, flare_mm: float = 0.0,
                      flare_from: float = 0.75, neck_r_mm: float | None = None,
                      neck_from: float = 0.75) -> list[tuple[float, float]]:
    """Original body of ``wall_points`` with the radius clamp removed (patch A1)."""
    n = int(max(count, 3))
    r_start_mm = float(r_start_mm)
    R_mm = float(R_mm)
    neck_r_mm = float(neck_r_mm) if neck_r_mm is not None else None
    top = R_mm if neck_r_mm is None else neck_r_mm
    pts: list[tuple[float, float]] = []
    for i in range(n):
        u = (i + 1) / n
        z = z_start + (z_rim_mm - z_start) * u
        rr = r_start_mm + (top - r_start_mm) * (u ** float(exponent))
        if neck_r_mm is not None and u >= float(neck_from):
            w = (u - float(neck_from)) / max(1.0 - float(neck_from), 1e-6)
            rr = rr + (neck_r_mm - rr) * (w ** 0.8)
        if flare_mm and u >= float(flare_from):
            w = (u - float(flare_from)) / max(1.0 - float(flare_from), 1e-6)
            rr = rr + float(flare_mm) * (w ** 1.6)
        pts.append((float(max(rr, 0.0)), float(z)))
    return pts


def fixed_monotone_radius_control_points(ctrl, *, min_ratio: float = 0.05,
                                         stage: str = "mothers.vessels.shell"):
    """Original body with the radius-monotonicity filter replaced by a z-advance filter."""
    pts = np.asarray(ctrl, dtype=np.float64)
    kept: list[np.ndarray] = [pts[0]]
    for row in pts[1:]:
        if row[1] <= kept[-1][1] + 1e-9:      # the mid-line must rise in z
            continue
        kept.append(row)
    out = np.asarray(kept, dtype=np.float64)
    if len(out) < 3:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "mid-line control points collapse after enforcing rising z",
                          stage=stage, measurements={"requested": int(len(pts)),
                                                     "kept": int(len(out))})
    if out[0, 0] > 1e-9:
        out = np.vstack([[0.0, out[0, 1]], out])
    if float(np.max(out[:, 0])) < float(min_ratio) * float(np.max(pts[:, 0])):
        raise SynLabError(ErrorCode.MOTHER_INVALID, "vessel radius is degenerate after cleanup",
                          stage=stage)
    return out


REAL = {
    "LIN0004_V10_M06_PAT03": ("V10", {
        "base_mm": 10.649771173028173, "belly_ratio": 0.68991973127168,
        "diameter_mm": 222.77854733012697, "height_mm": 352.12756141776987,
        "knob_diameter_mm": 64.43440084462063, "lid_height_ratio": 0.568826035425881,
        "lid_seat_mm": 3.3710449924909853, "mouth_ratio": 0.30098125744230925,
        "wall_mm": 2.8443414248422236, "warp_amplitude": 0.016873063698682116,
        "warp_eccentricity_mm": 1.848518300460957, "warp_lobes": 2}),
    "LIN0006_V09_M09_PAT03": ("V09", {
        "base_mm": 15.158553801891568, "belly_ratio": 1.1161788491776976,
        "diameter_mm": 262.5068873811831, "handle_span_ratio": 0.9508241451705133,
        "height_mm": 294.88495327061656, "neck_ratio": 0.40728578426690004,
        "spout_angle_deg": 16.752630179838093, "spout_bore_mm": 28.26905787271389,
        "spout_length_mm": 87.82286120683884, "wall_mm": 8.29251376441934,
        "warp_amplitude": 0.012910494651944234, "warp_eccentricity_mm": 0.22546127956209078,
        "warp_lobes": 2}),
    "LIN0014_V16_M07_PAT10": ("V16", {
        "base_mm": 8.16478352807982, "belly_ratio": 0.7058423758393259,
        "diameter_mm": 235.75435316131734, "foot_count": 5,
        "foot_height_mm": 96.41921641393304, "height_mm": 265.4053512410892,
        "shoulder_ratio": 0.36401622797259525, "vent_count": 11,
        "vent_diameter_mm": 29.760870991711116, "wall_mm": 5.432194146934794,
        "warp_amplitude": 0.029918694893006234, "warp_eccentricity_mm": 0.07738022154521806,
        "warp_lobes": 2}),
}


def build_and_measure(vessel_id: str, params: dict, seed_parts, label: str) -> dict:
    rng = make_rng(*seed_parts) if isinstance(seed_parts, tuple) else seed_parts
    try:
        mother = create_mother(vessel_id, "M01", dict(params), rng, mother_id=label)
    except SynLabError as exc:
        return {"status": "MOTHER_INVALID", "code": str(exc.code), "stage": exc.stage,
                "message": exc.message[:400],
                "measurements": jsonable(dict(exc.measurements or {}))}
    except Exception as exc:
        return {"status": "RAISED", "error": f"{type(exc).__name__}: {exc}"[:400]}
    pm = dict((mother.meta or {}).get("profile_metrics") or {})
    report = audit_mother(mother, max_thickness_probes=96, run_self_intersection=False)
    comps = component_report(mother.mesh)
    gaps = gaps_between_components(comps)
    declared = pm.get("z_rim_target_mm")
    return {
        "status": "OK",
        "declared_z_rim_target_mm": declared,
        "profile_z_rim_mm": pm.get("z_rim"),
        "profile_shortfall_mm": (float(declared) - float(pm["z_rim"]))
        if declared is not None and pm.get("z_rim") is not None else None,
        "profile_r_max_mm": pm.get("r_max"),
        "n_bodies": len(comps),
        "max_positive_gap_mm": max([g["gap_mm"] for g in gaps], default=0.0),
        "component_gaps": gaps,
        "volume_mm3": float(mother.mesh.volume),
        "audit_ok": bool(report.get("ok")),
        "audit_failures": [f.get("check") for f in (report.get("failures") or [])],
        "geometry_hash": report.get("geometry_hash"),
    }


def main() -> int:
    out: dict = {"patch_A1": "wall_points: remove the non-increasing radius clamp",
                 "patch_A2": "monotone_radius_control_points: keep points whose z advances",
                 "defaults": {}, "frozen_params": {}}

    for module in MODULES:
        if hasattr(module, "wall_points"):
            module.wall_points = fixed_wall_points
    common_mod.wall_points = fixed_wall_points
    common_mod.monotone_radius_control_points = fixed_monotone_radius_control_points

    print("=== after the proposed patch, registry prototype parameters")
    for index in range(1, 25):
        vessel_id = f"V{index:02d}"
        params = default_params(vessel_id)
        row = build_and_measure(
            vessel_id, params,
            (int(seed64(0xA12, vessel_id, "mother_geometry_audit")), vessel_id, "audit"),
            f"{vessel_id}-audit-patched")
        out["defaults"][vessel_id] = row
        if row["status"] == "OK":
            print(f"{vessel_id} OK   target={row['declared_z_rim_target_mm']} "
                  f"z_rim={row['profile_z_rim_mm']} short={row['profile_shortfall_mm']} "
                  f"r_max={row['profile_r_max_mm']} bodies={row['n_bodies']} "
                  f"vol={row['volume_mm3']:.1f} audit={row['audit_ok']} "
                  f"fail={row['audit_failures']}")
        else:
            print(f"{vessel_id} {row['status']} {row.get('code', '')} {row.get('message', '')}")

    print()
    print("=== after the proposed patch, frozen-batch parameters")
    for lineage, (vessel_id, params) in REAL.items():
        row = build_and_measure(vessel_id, params, (0xA12, lineage, "audit"), lineage)
        out["frozen_params"][lineage] = row
        if row["status"] == "OK":
            print(f"{lineage}: target={row['declared_z_rim_target_mm']:.4f} "
                  f"z_rim={row['profile_z_rim_mm']:.4f} "
                  f"short={row['profile_shortfall_mm']:.4f} r_max={row['profile_r_max_mm']:.4f} "
                  f"audit={row['audit_ok']} fail={row['audit_failures']}")
        else:
            print(f"{lineage}: {row['status']} {row.get('code', '')} {row.get('message', '')}")

    (HERE / "s11_fix_simulation.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
