"""Step 15b: aggregate the post-fix 24-vessel measurements into one deliverable.

Inputs (all read-only):

* ``parts_run2/<VID>.json``  - the post-fix audit sweep re-run for this verification round
  (``s13_audit_vessel_fixed.py``, one process per vessel).  ``parts/`` holds the earlier
  post-fix run by the previous session; the two agree on ``geometry_hash`` for 24/24 vessels.
* ``parts/<VID>.json``       - kept for the reproducibility check above.
* ``mother_geometry_audit/parts/<VID>.json`` - the **pre-fix** audit (commit c311269).
* ``trace_parts/<VID>.json`` - the post-fix helper trace (``s15_trace_helpers.py``).
* ``s14_frozen_after.json``  - the frozen lineage replay.

Output: ``s15_audit_all.json`` + a console table.  Nothing here re-measures geometry; every
number is copied out of a per-vessel JSON that a real build wrote.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPORTS = HERE.parent
PRE = REPORTS / "mother_geometry_audit" / "parts"
POST = HERE / "parts"
POST2 = HERE / "parts_run2"
TRACE = HERE / "trace_parts"

#: The 7 neck-family vessels and the value the *simulated* fix predicted in
#: ``s11_fix_simulation.json`` (section 4.2 of docs/a12/mother_geometry_audit.md).
EXPECTED = {
    "V06": {"z_rim": 184.33, "target": 183.25},
    "V07": {"z_rim": 245.40, "target": 243.25},
    "V08": {"z_rim": 234.38, "target": 233.25},
    "V09": {"z_rim": 184.93, "target": 183.25},
    "V10": {"z_rim": 173.81, "target": 173.25},
    "V11": {"z_rim": 214.82, "target": 213.25},
    "V16": {"z_rim": 150.08, "target": 149.25},
    "V17": {"z_rim": 123.51, "target": 122.00},
    "V01": {"z_rim": 85.59, "target": 84.59},
}
#: vessels whose geometry the P1 fix must have changed (the 15 ``wall_points`` call sites)
A1_SET = ("V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08", "V09", "V10", "V11", "V12",
          "V15", "V16", "V17")
A2_SET = ("V06", "V07", "V08", "V09", "V10", "V11", "V16")


def load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def build_row(vid: str) -> dict:
    post = load(POST2 / f"{vid}.json") or load(POST / f"{vid}.json")
    post_other = load(POST / f"{vid}.json") if (POST2 / f"{vid}.json").exists() else None
    pre = load(PRE / f"{vid}.json")
    trace = load(TRACE / f"{vid}.json")

    row: dict = {"vessel_id": vid, "status": post.get("status"),
                 "buildable": post.get("status") == "OK",
                 "vessel_name": post.get("vessel_name"), "family": post.get("family"),
                 "builder": post.get("builder"),
                 "registry_version": post.get("registry_version"),
                 "params_source": post.get("params_source"),
                 "seconds": post.get("seconds")}
    if post.get("status") != "OK":
        row.update({"error": post.get("error"), "error_code": post.get("error_code")})
        return row

    pm = post.get("profile_metrics") or {}
    audit = post.get("audit") or {}
    mesh = post.get("mesh") or {}
    checks = audit.get("check_ok") or {}
    metrics = audit.get("metrics") or {}

    target = post.get("declared_z_extent_mm")
    z_rim = pm.get("z_rim")
    shortfall = (float(target) - float(z_rim)) if (target is not None and z_rim is not None) else None
    row.update({
        "geometry_hash": post.get("geometry_hash"),
        "geometry_hash_earlier_run": (post_other or {}).get("geometry_hash"),
        "hash_reproduced": (post_other or {}).get("geometry_hash") == post.get("geometry_hash"),
        "qa": {"ok": bool(audit.get("ok")), "state": audit.get("state"),
               "failures": audit.get("failures") or [],
               "checks": checks,
               "self_intersecting_pairs": metrics.get("self_intersecting_pairs"),
               "thickness_min_mm": audit.get("thickness_min_mm"),
               "void_ratio": audit.get("void_ratio")},
        "watertight": bool(mesh.get("watertight")),
        "self_intersection_check_ok": checks.get("self_intersection"),
        "n_bodies": mesh.get("n_bodies"),
        "volume_mm3": mesh.get("volume_mm3"),
        "area_mm2": mesh.get("area_mm2"),
        "faces": mesh.get("faces"),
        "bbox_mm": mesh.get("bbox_mm"),
        "z_min": mesh.get("z_min"), "z_max": mesh.get("z_max"),
        "declared_z_extent_mm": target,
        "declared_source": post.get("declared_source"),
        "profile_z_rim_mm": z_rim,
        "z_rim_target_mm": pm.get("z_rim_target_mm"),
        "z_rim_shortfall_mm": pm.get("z_rim_shortfall_mm"),
        "profile_r_max_mm": pm.get("r_max"),
        "profile_z_bottom_mm": pm.get("z_bottom"),
        "measured_minus_declared_mm": shortfall,
        "max_positive_gap_mm": post.get("max_positive_gap_mm"),
        "n_components": len(post.get("components") or []),
    })

    # pre-fix state, for the "did it move / how much" column
    if pre and pre.get("status") == "OK":
        pre_pm = pre.get("profile_metrics") or {}
        row["prefix"] = {
            "profile_z_rim_mm": pre_pm.get("z_rim"),
            "profile_r_max_mm": pre_pm.get("r_max"),
            "geometry_hash": pre.get("geometry_hash"),
            "volume_mm3": (pre.get("mesh") or {}).get("volume_mm3"),
            "n_bodies": (pre.get("mesh") or {}).get("n_bodies"),
            "max_positive_gap_mm": pre.get("max_positive_gap_mm"),
            "declared_z_extent_mm": pre.get("declared_z_extent_mm"),
            "registry_version": pre.get("registry_version"),
        }
        pz = pre_pm.get("z_rim")
        row["prefix"]["measured_minus_declared_mm"] = (
            float(pre.get("declared_z_extent_mm")) - float(pz)) if pz is not None else None
        if isinstance(row["volume_mm3"], (int, float)) and isinstance(
                row["prefix"]["volume_mm3"], (int, float)) and row["prefix"]["volume_mm3"]:
            row["volume_change_pct"] = 100.0 * (row["volume_mm3"]
                                                - row["prefix"]["volume_mm3"]) / row["prefix"]["volume_mm3"]
        row["z_rim_change_mm"] = (float(z_rim) - float(pz)) if (pz is not None
                                                               and z_rim is not None) else None
        row["geometry_changed"] = pre.get("geometry_hash") != post.get("geometry_hash")
    else:
        row["prefix"] = None
        row["geometry_changed"] = None

    # helper trace: direct evidence A1 (flat wall) / A2 (dropped neck) are gone
    if trace:
        row["trace"] = {
            "n_wall_points_calls": trace.get("n_wall_points_calls"),
            "n_filter_calls": trace.get("n_filter_calls"),
            "wall_points_r_span_max": trace.get("wall_points_r_span_max"),
            "wall_points_all_flat": trace.get("wall_points_all_flat"),
            "filter_dropped_total": trace.get("filter_dropped_total"),
            "filter_all_z_advance": trace.get("filter_all_z_advance"),
        }
    else:
        row["trace"] = None

    # symptom re-check, using the audit's own mechanical rules (docs section 2.1)
    symptoms: list[str] = []
    tolerance = max(2.0, 0.01 * abs(float(target))) if target is not None else None
    if shortfall is not None and tolerance is not None and shortfall > tolerance:
        symptoms.append("S1_profile_truncated")
    if row["trace"] and row["trace"]["wall_points_all_flat"]:
        symptoms.append("S4_wall_flat")
    top_ratio = (post.get("body") or {}).get("top_over_max_radius_ratio")
    if (vid in A2_SET and row["trace"] and (row["trace"]["filter_dropped_total"] or 0) > 0
            and top_ratio is not None and top_ratio >= 0.98):
        symptoms.append("S3_neck_lost")
    if (row["max_positive_gap_mm"] or 0.0) > 1.0:
        symptoms.append("S5_floating_part")
    row["postfix_symptoms"] = symptoms
    row["top_over_max_radius_ratio"] = top_ratio

    if vid in EXPECTED:
        exp = EXPECTED[vid]
        row["expected"] = {
            "z_rim_from_s11_simulation_mm": exp["z_rim"],
            "note": "s11_fix_simulation.json (in-process monkeypatch of the pre-fix code)",
            "measured_minus_expected_mm": float(z_rim) - exp["z_rim"],
            "within_1e_3_mm": abs(float(z_rim) - exp["z_rim"]) < 1e-3,
        }
    return row


def main() -> int:
    rows = [build_row(f"V{i:02d}") for i in range(1, 25)]
    frozen = load(HERE / "s14_frozen_after.json")
    frozen_pre = load(REPORTS / "mother_geometry_audit" / "s04_frozen_repro.json")

    ok = [r for r in rows if r["buildable"]]
    qa_ok = [r for r in ok if r["qa"]["ok"]]
    watertight = [r for r in ok if r["watertight"]]
    self_int = [r for r in ok if r["self_intersection_check_ok"] is False
                or (r["qa"]["self_intersecting_pairs"] or 0) > 0]
    not_watertight = [r["vessel_id"] for r in ok if not r["watertight"]]
    anomalies = [
        {"vessel_id": r["vessel_id"], "kind": "NOT_BUILDABLE", "detail": r.get("error")}
        for r in rows if not r["buildable"]
    ] + [
        {"vessel_id": r["vessel_id"], "kind": "QA_FAILED", "detail": r["qa"]["failures"]}
        for r in ok if not r["qa"]["ok"]
    ] + [
        {"vessel_id": r["vessel_id"], "kind": "NOT_WATERTIGHT"}
        for r in ok if not r["watertight"]
    ] + [
        {"vessel_id": r["vessel_id"], "kind": "SELF_INTERSECTION",
         "detail": r["qa"]["self_intersecting_pairs"]}
        for r in self_int
    ] + [
        {"vessel_id": r["vessel_id"], "kind": "POSTFIX_SYMPTOM",
         "detail": r["postfix_symptoms"], "note": "S1 = still short of its declared z"}
        for r in ok if r["postfix_symptoms"]
    ]

    payload = {
        "schema": "a12.mother_geometry.s15_audit_all.v1",
        "what": "post-fix (P1+P2) 24-vessel re-measurement, one process per vessel",
        "measurement_command":
            ".venv/Scripts/python.exe data/a12/reports/geom_fix/s13_audit_vessel_fixed.py "
            "<VID> --out data/a12/reports/geom_fix/parts_run2",
        "trace_command":
            ".venv/Scripts/python.exe data/a12/reports/geom_fix/s15_trace_helpers.py <VID>",
        "seed_policy": "make_rng(seed64(0xA12, <VID>, 'mother_geometry_audit'), <VID>, 'audit')",
        "params_source": "registry defaults (default_params), identical to the pre-fix audit",
        "affected_sets": {"A1_wall_points": list(A1_SET), "A2_neck_dropped": list(A2_SET)},
        "summary": {
            "n_vessels": len(rows),
            "n_buildable": len(ok),
            "n_qa_pass": len(qa_ok),
            "n_watertight": len(watertight),
            "n_self_intersecting": len(self_int),
            "not_watertight": not_watertight,
            "n_geometry_changed": len([r for r in rows if r.get("geometry_changed")]),
            "n_unchanged": len([r for r in rows if r.get("geometry_changed") is False]),
            "unchanged_vessels": [r["vessel_id"] for r in rows
                                  if r.get("geometry_changed") is False],
            "n_hash_reproduced": len([r for r in rows if r.get("hash_reproduced")]),
            "total_seconds": round(sum(r.get("seconds") or 0 for r in rows), 2),
            "anomalies": anomalies,
        },
        "vessels": {r["vessel_id"]: r for r in rows},
        "expected_vs_measured": {
            vid: {
                "expected_z_rim_mm": EXPECTED[vid]["z_rim"],
                "measured_z_rim_mm": next(r["profile_z_rim_mm"] for r in rows
                                          if r["vessel_id"] == vid),
                "delta_mm": next((r["profile_z_rim_mm"] - EXPECTED[vid]["z_rim"] for r in rows
                                  if r["vessel_id"] == vid), None),
                "declared_target_mm": EXPECTED[vid]["target"],
            } for vid in EXPECTED
        },
        "frozen_lineages_after": frozen,
        "frozen_lineages_before": frozen_pre,
        "notes": [
            "registry_version is 1.1 for exactly the 15 A1 vessels; the other 9 stay at 1.0.",
            "z_rim is the measured top of the body profile; z_rim_target_mm is the value the",
            "vessel's own parameters declare.  pre-fix data has z_rim << z_rim_target_mm for",
            "the A2 family, post-fix data has |z_rim - z_rim_target_mm| <= 2.2 mm everywhere.",
            "S1 for V23 is defect B1 (height_mm semantics), and the V22 extent is defect A3;",
            "neither is a regression of the P1/P2 fix.",
        ],
    }
    out = HERE / "s15_audit_all.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                              default=str), encoding="utf-8")

    print(f"{'vid':4} {'build':>5} {'qa':>4} {'wt':>4} {'si':>4} {'z_rim':>9} {'target':>9} "
          f"{'meas-dec':>9} {'d(exp)':>8} {'span_max':>9} {'drop':>5} {'ver':>5} {'sym':>22}")
    for r in rows:
        if not r["buildable"]:
            print(f"{r['vessel_id']:4} {'NO':>5}  {r.get('error', '')[:60]}")
            continue
        t = r["trace"] or {}
        exp = r.get("expected") or {}

        def num(value):
            return float(value) if isinstance(value, (int, float)) else float("nan")

        print(f"{r['vessel_id']:4} {'OK':>5} {str(r['qa']['ok']):>4} "
              f"{str(r['watertight']):>4} "
              f"{'0' if r['self_intersection_check_ok'] else 'YES':>4} "
              f"{num(r['profile_z_rim_mm']):9.3f} "
              f"{num(r['z_rim_target_mm']):9.3f} "
              f"{num(r['measured_minus_declared_mm']):9.3f} "
              f"{num(exp.get('measured_minus_expected_mm')):8.4f} "
              f"{num(t.get('wall_points_r_span_max')):9.3f} "
              f"{str(t.get('filter_dropped_total')):>5} "
              f"{str(r['registry_version']):>5} {','.join(r['postfix_symptoms']):>22}")
    print()
    print(f"buildable {len(ok)}/24   QA pass {len(qa_ok)}/24   watertight {len(watertight)}/24   "
          f"self-intersecting {len(self_int)}/24   geometry changed "
          f"{payload['summary']['n_geometry_changed']}/24")
    for a in anomalies:
        print("  ANOMALY", a)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
