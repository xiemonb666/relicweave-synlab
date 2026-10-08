"""S12: print the exact before/after numbers from the driver report (UTF-8, no shell quoting)."""

from __future__ import annotations

import io
import json
import os

REPORTS = "data/a12_reports"
FIELDS = ("n_faces", "n_vertices", "watertight", "boundary_edges", "volume_mm3",
          "lost_volume_mm3", "lost_volume_ratio", "bodies", "area_mm2")
MEAS = ("roi_external_drift_mm", "roi_external_drift_p50_mm", "roi_external_drift_p95_mm",
        "roi_external_drift_p99_mm", "roi_external_drift_moved_samples", "lost_volume_mm3",
        "grid_spacing_mm", "grid_nodes", "watertight", "components", "applied_depth_mm",
        "measured_max_recession_mm", "achieved_contact_loss", "linearised_predicted_loss_mm3",
        "lost_volume_vs_linear_ratio", "rim_vertices_pinned", "narrowband_vertices",
        "max_outside_clean_mm", "measured_max_displacement_mm")


def load(name):
    path = os.path.join(REPORTS, name)
    if not os.path.exists(path):
        return None
    with io.open(path, encoding="utf-8-sig") as handle:
        return json.load(handle)


def main() -> int:
    fix = load("s12_fix_before_after.json")
    if not fix:
        print("no fix report")
        return 1
    out = io.open(os.path.join(REPORTS, "_s12_fix_view.txt"), "w", encoding="utf-8")
    body = fix["fix"]
    out.write(f"body: {json.dumps(body.get('body'))}\n")
    out.write(f"fragment: {body.get('fragment_id')}\n")
    for axis, row in body["axes"].items():
        if "declared_route" not in row:
            out.write(f"\n{axis}: ERROR {row.get('error')}\n")
            continue
        out.write(f"\n=== {axis} recipe={row['recipe_id']} level={row['level']} "
                  f"params={json.dumps(row['params'])} roi={json.dumps(row['roi'])}\n")
        for label, key in (("DECLARED(narrowband)", "declared_route"),
                           ("LEGACY(global_sdf)  ", "legacy_global_sdf_route"),
                           ("FORCED(narrowband)  ", "forced_narrowband_route")):
            r = row[key]
            m = r.get("measured") or {}
            b = r.get("body") or {}
            a = r.get("audit") or {}
            out.write(f"  {label} backend={r.get('damage_backend')} "
                      f"requested={r.get('requested_backend')} err={r.get('error')} "
                      f"sec={r.get('seconds')}\n")
            out.write("    MEAS " + json.dumps({k: m.get(k) for k in MEAS
                                                if m.get(k) is not None}) + "\n")
            out.write("    BODY " + json.dumps({k: b.get(k) for k in FIELDS}) + "\n")
            out.write(f"    AUDIT status={a.get('status')} failure_codes={a.get('failure_codes')}\n")
            out.write("    DRIFTCHK " + json.dumps(a.get("roi_external_drift_check")) + "\n")
            out.write("    BUDGET " + json.dumps(r.get("spacing_budget")) + "\n")
            out.write("    DISPL " + json.dumps(m.get("displacement_family")) + "\n")
            out.write("    ROUTES " + json.dumps(r.get("routes")) + "\n")
    out.close()
    print(open(os.path.join(REPORTS, "_s12_fix_view.txt"), encoding="utf-8").read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
