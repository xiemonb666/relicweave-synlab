"""Step 16b: fold the paired ``before``/``after`` gate sweeps into the drift deliverable.

Reads ``plan_drift/<VID>_before.json`` and ``plan_drift/<VID>_after.json`` (written by
``s16_plan_drift.py``) and writes ``plan_drift_after_geometry_fix.json`` with:

* the accepted count and fraction per vessel in both states, and the *paired* verdict flips
  (same candidate index -> accepted before / after), which is what "drift" actually means;
* per-parameter quantiles of the accepted set in both states;
* whether the frozen lineage parameter tuples still pass the real gate after the fix.

A candidate pool is drawn once with ``require_feasible=False`` (geometry independent), so both
states are judged on exactly the same candidates.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DRIFT = HERE / "plan_drift"
AFFECTED = ("V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08", "V09", "V10", "V11", "V12",
            "V15", "V16", "V17")
Q = (0.05, 0.25, 0.50, 0.75, 0.95)

FROZEN = {
    "LIN0004_V10_M06_PAT03": ("V10", {
        "base_mm": 10.649771173028173, "belly_ratio": 0.68991973127168,
        "diameter_mm": 222.77854733012697, "height_mm": 352.12756141776987,
        "knob_diameter_mm": 64.43440084462063, "lid_height_ratio": 0.568826035425881,
        "lid_seat_mm": 3.3710449924909853, "mouth_ratio": 0.30098125744230925,
        "wall_mm": 2.8443414248422236, "warp_amplitude": 0.016873063698682116,
        "warp_eccentricity_mm": 1.848518300460957, "warp_lobes": 2}),
    "LIN0000_V10_M11_PAT15": ("V10", {
        "base_mm": 16.25640284535809, "belly_ratio": 1.342951572929974,
        "diameter_mm": 243.40045346124103, "height_mm": 205.7264438423038,
        "knob_diameter_mm": 17.718809719300232, "lid_height_ratio": 0.34308726483786,
        "lid_seat_mm": 13.062273097916366, "mouth_ratio": 0.947908125947771,
        "wall_mm": 9.7008674906311, "warp_amplitude": 0.022576087632897448,
        "warp_eccentricity_mm": 1.4913959072464065, "warp_lobes": 2}),
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


def load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def quantiles(rows: list[dict]) -> dict:
    if not rows:
        return {}
    names = sorted(rows[0]["params"])
    out: dict[str, dict[str, float]] = {}
    for name in names:
        values = np.asarray([float(r["params"][name]) for r in rows], dtype=np.float64)
        out[name] = {f"p{int(q * 100):02d}": float(np.quantile(values, q)) for q in Q}
        out[name]["mean"] = float(values.mean())
        out[name]["min"] = float(values.min())
        out[name]["max"] = float(values.max())
    return out


def main() -> int:
    per_vessel: dict[str, dict] = {}
    for vid in AFFECTED:
        before = load(DRIFT / f"{vid}_before.json")
        after = load(DRIFT / f"{vid}_after.json")
        if before is None or after is None:
            per_vessel[vid] = {"status": "INCOMPLETE",
                               "has_before": before is not None, "has_after": after is not None}
            continue
        assert before["n_pool"] == after["n_pool"], vid
        b_rows = {r["index"]: r for r in before["rows"]}
        a_rows = {r["index"]: r for r in after["rows"]}
        idx = sorted(set(b_rows) & set(a_rows))
        acc_b = [b_rows[i] for i in idx if b_rows[i]["accepted"]]
        acc_a = [a_rows[i] for i in idx if a_rows[i]["accepted"]]
        gained = [i for i in idx if a_rows[i]["accepted"] and not b_rows[i]["accepted"]]
        lost = [i for i in idx if b_rows[i]["accepted"] and not a_rows[i]["accepted"]]
        params_changed = [
            {"index": i,
             "accepted": [b_rows[i]["accepted"], a_rows[i]["accepted"]],
             "reason_before": b_rows[i]["reason"], "reason_after": a_rows[i]["reason"]}
            for i in idx if b_rows[i]["accepted"] != a_rows[i]["accepted"]
        ]
        per_vessel[vid] = {
            "status": "OK",
            "n_pool": before["n_pool"],
            "n_accepted_before": len(acc_b),
            "n_accepted_after": len(acc_a),
            "accepted_fraction_before": len(acc_b) / len(idx) if idx else 0.0,
            "accepted_fraction_after": len(acc_a) / len(idx) if idx else 0.0,
            "accepted_delta": len(acc_a) - len(acc_b),
            "n_verdict_flips": len(params_changed),
            "n_gained": len(gained), "n_lost": len(lost),
            "gained_indices": gained, "lost_indices": lost,
            "verdict_flips": params_changed,
            "reason_counts_before": before["reason_counts"],
            "reason_counts_after": after["reason_counts"],
            "quantiles_before": quantiles(acc_b),
            "quantiles_after": quantiles(acc_a),
            "seconds_before": before.get("seconds"), "seconds_after": after.get("seconds"),
        }

    # do the frozen lineage parameter tuples still pass the real gate after the fix?
    import sys
    sys.path.insert(0, str(HERE))
    frozen_rows = {}
    try:
        import synlab.mothers.vessels.common as common_mod  # noqa: E402
        from synlab.mothers import api as mothers_api  # noqa: E402
        from synlab.seeds import make_rng, seed64  # noqa: E402

        for lineage, (vid, params) in FROZEN.items():
            gate_rng = make_rng(int(seed64(0xA12, vid, "sampler_gate")), vid, "sampler_gate")
            reason_pre = mothers_api._pre_gate(vid, params)
            reason = reason_pre or mothers_api._build_gate(vid, params, gate_rng)
            frozen_rows[lineage] = {
                "vessel_id": vid, "pre_gate_reason": reason_pre,
                "build_gate_reason": None if reason_pre else reason,
                "accepted_after_fix": reason is None,
                "gate": "api._pre_gate then api._build_gate (real create_mother + audit)",
                "note": "params are the frozen store record, replayed verbatim",
                "callee_names_present": {
                    "advancing_control_points": hasattr(common_mod, "advancing_control_points"),
                    "monotone_radius_control_points": hasattr(
                        common_mod, "monotone_radius_control_points"),
                },
            }
    except Exception as exc:  # reported, never hidden
        frozen_rows = {"ERROR": f"{type(exc).__name__}: {exc}"}

    complete = [v for v in per_vessel.values() if v.get("status") == "OK"]
    payload = {
        "schema": "a12.mother_geometry.plan_drift.v1",
        "what": "paired before/after feasibility sweep of the real plan gate",
        "method": [
            "pool: sample_parameters(vid, N, pool_rng, require_feasible=False) - the analytic",
            "pre-gate and the pydantic schema gate do not read the geometry, so the SAME pool",
            "is valid in both states; the pool therefore contains candidates the real gate",
            "refuses, which is exactly what is being measured.",
            "before: common.wall_points / the control-point filter monkeypatched back to the",
            "pre-fix bodies of c311269 inside that process only (s16_plan_drift.py --mode before).",
            "after: the repository code with P1+P2, no patch at all.",
        ],
        "gate": "synlab.mothers.api._pre_gate then _build_gate (real create_mother + audit_mother)",
        "n_candidates_per_vessel": {v: per_vessel[v].get("n_pool") for v in per_vessel},
        "affected_vessels": list(AFFECTED),
        "per_vessel": per_vessel,
        "frozen_lineage_params_through_the_new_gate": frozen_rows,
        "summary": {
            "n_vessels_measured": len(complete),
            "n_vessels_expected": len(AFFECTED),
            "total_candidates": sum(v["n_pool"] for v in complete),
            "accepted_before": sum(v["n_accepted_before"] for v in complete),
            "accepted_after": sum(v["n_accepted_after"] for v in complete),
            "vessels_with_verdict_flips": [v for v in per_vessel
                                           if per_vessel[v].get("n_verdict_flips")],
            "vessels_with_lost_candidates": [v for v in per_vessel
                                             if per_vessel[v].get("n_lost")],
            "vessels_with_gained_candidates": [v for v in per_vessel
                                               if per_vessel[v].get("n_gained")],
            "changed_existing_lineage_params": [
                {"lineage": k, "accepted_after_fix": v.get("accepted_after_fix"),
                 "reason": v.get("build_gate_reason") or v.get("pre_gate_reason")}
                for k, v in frozen_rows.items() if isinstance(v, dict)
            ],
        },
    }
    out = HERE / "plan_drift_after_geometry_fix.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                   encoding="utf-8")

    print(f"{'vid':4} {'pool':>5} {'acc_b':>6} {'acc_a':>6} {'delta':>6} {'flips':>6} "
          f"{'gained':>7} {'lost':>5}")
    for vid in AFFECTED:
        v = per_vessel[vid]
        if v.get("status") != "OK":
            print(f"{vid:4} INCOMPLETE {v}")
            continue
        print(f"{vid:4} {v['n_pool']:5d} {v['n_accepted_before']:6d} {v['n_accepted_after']:6d} "
              f"{v['accepted_delta']:6d} {v['n_verdict_flips']:6d} {v['n_gained']:7d} "
              f"{v['n_lost']:5d}")
    print()
    print("frozen lineages through the real gate after the fix:")
    for k, v in frozen_rows.items():
        print("  ", k, json.dumps(v, ensure_ascii=False)[:200] if isinstance(v, dict) else v)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
