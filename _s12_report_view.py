"""Print the S12 before/after tables from the driver reports (UTF-8 safe, no shell quoting)."""

from __future__ import annotations

import io
import json
import os
import sys

REPORTS = "data/a12_reports"


def load(name: str):
    path = os.path.join(REPORTS, name)
    if not os.path.exists(path):
        return None
    with io.open(path, encoding="utf-8-sig") as handle:
        return json.load(handle)


def main() -> int:
    fix = load("s12_fix_before_after.json")
    if fix:
        print("=" * 100)
        print("BEFORE/AFTER (declared route vs legacy global_sdf route), archived body")
        print("=" * 100)
        for axis, row in fix["fix"]["axes"].items():
            if "declared_route" not in row:
                print(f"{axis}: ERROR {row.get('error')}")
                continue
            print(f"\n--- {axis}  recipe={row['recipe_id']} level={row['level']} "
                  f"params={json.dumps(row['params'])} roi={json.dumps(row['roi'])}")
            for label, key in (("DECLARED", "declared_route"),
                               ("LEGACY  ", "legacy_global_sdf_route"),
                               ("FORCED  ", "forced_narrowband_route")):
                r = row[key]
                m = r.get("measured") or {}
                b = r.get("body") or {}
                a = r.get("audit") or {}
                print(f"  {label} backend={r.get('damage_backend')} err={r.get('error')} "
                      f"seconds={r.get('seconds'):.2f}" if r.get("seconds") else
                      f"  {label} backend={r.get('damage_backend')} err={r.get('error')}")
                print(f"    measured: drift={m.get('roi_external_drift_mm')} "
                      f"p50={m.get('roi_external_drift_p50_mm')} "
                      f"p95={m.get('roi_external_drift_p95_mm')} "
                      f"p99={m.get('roi_external_drift_p99_mm')} "
                      f"moved={m.get('roi_external_drift_moved_samples')}")
                print(f"              lost_volume={m.get('lost_volume_mm3')} "
                      f"grid={m.get('grid_spacing_mm')} nodes={m.get('grid_nodes')} "
                      f"watertight_measure={m.get('watertight')} "
                      f"applied_depth={m.get('applied_depth_mm')} "
                      f"recession={m.get('measured_max_recession_mm')} "
                      f"contact_loss={m.get('achieved_contact_loss')}")
                print(f"    body:     faces={b.get('n_faces')} verts={b.get('n_vertices')} "
                      f"watertight={b.get('watertight')} boundary_edges={b.get('boundary_edges')} "
                      f"volume={b.get('volume_mm3')} lost={b.get('lost_volume_mm3')} "
                      f"lost_ratio={b.get('lost_volume_ratio')} bodies={b.get('bodies')}")
                print(f"    audit:    status={a.get('status')} failure_codes={a.get('failure_codes')}")
                print(f"    driftchk: {json.dumps(a.get('roi_external_drift_check'))}")
                print(f"    budget:   {json.dumps(r.get('spacing_budget'))}")
    dv = load("s12_drift_versions.json")
    if dv and "drift_versions" in dv:
        print("\n" + "=" * 100)
        print("DRIFT METRIC VERSIONS (git HEAD vs S12)")
        print("=" * 100)
        print(json.dumps(dv["drift_versions"], indent=2, sort_keys=True))
    budget = load("s12_budget_curve.json")
    if budget and "budget" in budget:
        print("\n" + "=" * 100)
        print("NODE BUDGET -> SPACING -> DRIFT")
        print("=" * 100)
        print("s11_case:", json.dumps(budget["budget"]["s11_case"], indent=2)[:1500])
        print("\nrule_probe:")
        for row in budget["budget"]["rule_probe"]:
            print("  ", json.dumps(row))
        print("\nbudget_curve:")
        for row in budget["budget"]["budget_curve"]:
            print("  ", json.dumps({k: row.get(k) for k in (
                "max_nodes", "requested_mm", "spacing_mm", "basis", "relaxation_steps",
                "grid_nodes", "drift_mm", "drift_p95_mm", "drift_p99_mm", "lost_volume_mm3",
                "n_faces", "watertight", "boundary_edges", "audit_status", "failure_codes")}))
        print("\ndeclared_spacing_curve:")
        for row in budget["budget"]["declared_spacing_curve"]:
            print("  ", json.dumps({k: row.get(k) for k in (
                "declared_mm", "spacing_mm", "grid_nodes", "drift_mm", "drift_p95_mm",
                "drift_p99_mm", "lost_volume_mm3", "n_faces", "watertight", "boundary_edges",
                "audit_status", "failure_codes")}))
    table = load("s12_axis_table.json")
    if table:
        print("\n" + "=" * 100)
        print("31-AXIS DECLARE-VS-ROUTE TABLE")
        print("=" * 100)
        for row in table["table"]["rows"]:
            lvl = row["levels"][0]
            deg = lvl.get("degrade") or {}
            print(f"{row['axis_id']} {row['agree']:<9} declared={row['declared_implementation']:<46}"
                  f" executed={','.join(row['executed_backends']):<48}"
                  f" L1 realized={deg.get('realized')} fc={deg.get('failure_code')} "
                  f"drift={deg.get('drift_mm')} p95={deg.get('drift_p95_mm')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
