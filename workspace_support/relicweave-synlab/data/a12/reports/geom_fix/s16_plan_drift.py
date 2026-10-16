"""Step 16: PLAN DRIFT measurement - does the P1+P2 geometry change the accepted set?

The plan sampler (``synlab.mothers.api.sample_parameters``) really builds and audits every
candidate (``_build_gate``), so a geometry change can move the *acceptance boundary* and thus
change which lineage parameters the planner hands out.  The audit only checked 24 prototype
points; this script measures the boundary on a real candidate pool.

Method (paired, reproducible, honest):

1. Draw a candidate pool that is **geometry independent**: ``sample_parameters(vid, N,
   rng, require_feasible=False)`` applies the analytic pre-gate and the vessel's own pydantic
   schema gate - neither reads the geometry - so the *same* pool is valid for both states.
   The pool therefore may contain candidates that the real gate rejects; that is the point.
2. Evaluate every candidate with the real ``_build_gate`` twice:
   * ``--mode before``: ``wall_points`` and the control-point filter are monkeypatched back to
     the pre-fix bodies of commit ``c311269`` (verbatim, in this process only);
   * ``--mode after`` : the repository code as it stands after P1+P2 (no patch at all).
3. Both modes write their own JSON, so a killed process loses at most one mode of one vessel.

Usage:
    python s16_plan_drift.py V10 --mode before --n 200
    python s16_plan_drift.py V10 --mode after  --n 200
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import synlab.mothers.vessels.common as common_mod  # noqa: E402
from synlab.mothers import api as mothers_api  # noqa: E402
from synlab.mothers.vessels import (group_composite, group_extrude,  # noqa: E402
                                    group_revolve, group_sheet)
from synlab.errors import ErrorCode, SynLabError  # noqa: E402
from synlab.seeds import make_rng, seed64  # noqa: E402

MODULES = (group_composite, group_extrude, group_revolve, group_sheet)


# ---------------------------------------------------------------------------------------
# pre-fix bodies, verbatim from c311269:synlab/mothers/vessels/common.py
# ---------------------------------------------------------------------------------------
def prefix_wall_points(*, r_start_mm: float, R_mm: float, z_start: float, z_rim_mm: float,
                       count: int = 6, exponent: float = 1.0, flare_mm: float = 0.0,
                       flare_from: float = 0.75, neck_r_mm: float | None = None,
                       neck_from: float = 0.75) -> list[tuple[float, float]]:
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
    out: list[tuple[float, float]] = []
    for rr, z in pts:
        if out and rr > out[-1][0]:
            rr = out[-1][0]
        out.append((rr, z))
    return out


def prefix_control_points(ctrl: np.ndarray, *, min_ratio: float = 0.05,
                          stage: str = "mothers.vessels.shell") -> np.ndarray:
    pts = np.asarray(ctrl, dtype=np.float64)
    kept: list[np.ndarray] = [pts[0]]
    for row in pts[1:]:
        if row[0] < kept[-1][0] - 1e-9:
            continue
        kept.append(row)
    out = np.asarray(kept, dtype=np.float64)
    if len(out) < 3:
        raise SynLabError(ErrorCode.MOTHER_INVALID,
                          "mid-line control points collapse after enforcing monotone radius",
                          stage=stage, measurements={"requested": int(len(pts)),
                                                     "kept": int(len(out))})
    if out[0, 0] > 1e-9:
        out = np.vstack([[0.0, out[0, 1]], out])
    if float(np.max(out[:, 0])) < float(min_ratio) * float(np.max(pts[:, 0])):
        raise SynLabError(ErrorCode.MOTHER_INVALID, "vessel radius is degenerate after cleanup",
                          stage=stage)
    return out


def install_prefix() -> None:
    """Restore the pre-fix geometry in this process only."""
    common_mod.wall_points = prefix_wall_points
    for module in MODULES:
        if hasattr(module, "wall_points"):
            module.wall_points = prefix_wall_points
    # the new name is what shell_profile resolves at call time
    common_mod.advancing_control_points = prefix_control_points
    if hasattr(common_mod, "monotone_radius_control_points"):
        common_mod.monotone_radius_control_points = prefix_control_points


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("vessel_id")
    ap.add_argument("--mode", choices=("before", "after"), required=True)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--out", default=str(HERE / "plan_drift"))
    args = ap.parse_args(argv[1:])

    if args.mode == "before":
        install_prefix()

    vid = args.vessel_id
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    pool_rng = make_rng(int(seed64(0xA12, vid, "plan_drift_pool")), vid, "plan_drift_pool")
    started = time.time()
    pool = mothers_api.sample_parameters(vid, int(args.n), pool_rng, require_feasible=False,
                                         max_attempts=8 * int(args.n))
    pool_report = mothers_api.last_sampling_report()

    gate_rng = make_rng(int(seed64(0xA12, vid, "sampler_gate")), vid, "sampler_gate")
    rows: list[dict] = []
    for index, candidate in enumerate(pool):
        # exactly the gate the planner uses
        reason = mothers_api._pre_gate(vid, candidate)
        if reason is None:
            reason = mothers_api._build_gate(vid, candidate, gate_rng)
        rows.append({"index": index, "accepted": reason is None, "reason": reason,
                     "params": {k: (float(v) if isinstance(v, float) else v)
                                for k, v in sorted(candidate.items())}})
        if (index + 1) % 25 == 0:
            print(f"  {vid} {args.mode}: {index + 1}/{len(pool)} "
                  f"accepted={sum(1 for r in rows if r['accepted'])} "
                  f"({time.time() - started:.0f}s)", flush=True)

    accepted = [r for r in rows if r["accepted"]]
    reasons: dict[str, int] = {}
    for row in rows:
        key = str(row["reason"] or "ACCEPTED")
        reasons[key] = reasons.get(key, 0) + 1
    payload = {
        "vessel_id": vid,
        "mode": args.mode,
        "n_pool": len(pool),
        "n_accepted": len(accepted),
        "accepted_fraction": len(accepted) / len(pool) if pool else 0.0,
        "reason_counts": reasons,
        "pool_sampling_report": pool_report,
        "pool_is_geometry_independent": True,
        "gate": "synlab.mothers.api._pre_gate then _build_gate (real create_mother + audit)",
        "prefix_geometry": args.mode == "before",
        "seconds": round(time.time() - started, 2),
        "rows": rows,
    }
    path = out_dir / f"{vid}_{args.mode}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8")
    print(f"{vid} {args.mode}: accepted {len(accepted)}/{len(pool)} in "
          f"{payload['seconds']}s -> {path.name}")
    print(f"   reasons: {reasons}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
