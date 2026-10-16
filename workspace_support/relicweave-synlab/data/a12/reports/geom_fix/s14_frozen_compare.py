"""Frozen lineage before/after table: component z spans, the two gap definitions, hashes."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PRE = REPO / "data/a12/reports/mother_geometry_audit/s04_frozen_repro.json"
POST = REPO / "data/a12/reports/geom_fix/s14_frozen_after.json"

pre = json.loads(PRE.read_text(encoding="utf-8"))
post = json.loads(POST.read_text(encoding="utf-8"))

out = {}
for lineage in sorted(set(pre) | set(post)):
    a = pre.get(lineage) or {}
    b = post.get(lineage) or {}

    def comps(d):
        return sorted(d.get("components") or [], key=lambda c: c["z_min"])

    ca, cb = comps(a), comps(b)

    def body(comps_):
        """The main body = the component containing the axis (largest volume fallback)."""
        return max(comps_, key=lambda c: c["volume_mm3"]) if comps_ else None

    def second_lowest(comps_):
        ordered = sorted(comps_, key=lambda c: c["z_min"])
        return ordered[1] if len(ordered) > 1 else None

    ba, bb = body(ca), body(cb)
    row = {
        "declared_z_rim_target_mm": b.get("declared_z_rim_target_mm")
        or a.get("declared_z_rim_target_mm"),
        "before": {
            "registry_version": a.get("registry_version"),
            "profile_z_rim_mm": a.get("profile_z_rim_mm"),
            "profile_r_max_mm": a.get("profile_r_max_mm"),
            "profile_shortfall_mm": a.get("profile_shortfall_mm"),
            "n_components": len(ca),
            "components": [{"faces": c["faces"], "volume_mm3": c["volume_mm3"],
                            "z": [c["z_min"], c["z_max"]]} for c in ca],
            "body_z": [ba["z_min"], ba["z_max"]] if ba else None,
            "max_positive_gap_mm": a.get("max_positive_gap_mm"),
            "mesh_volume_mm3": a.get("mesh_volume_mm3"),
            "geometry_hash": a.get("geometry_hash"),
            "audit_ok": a.get("audit_ok"),
        },
        "after": {
            "registry_version": b.get("registry_version"),
            "profile_z_rim_mm": b.get("profile_z_rim_mm"),
            "profile_r_max_mm": b.get("profile_r_max_mm"),
            "profile_shortfall_mm": b.get("profile_shortfall_mm"),
            "z_rim_shortfall_mm": b.get("z_rim_shortfall_mm"),
            "n_components": len(cb),
            "components": [{"faces": c["faces"], "volume_mm3": c["volume_mm3"],
                            "z": [c["z_min"], c["z_max"]]} for c in cb],
            "body_z": [bb["z_min"], bb["z_max"]] if bb else None,
            "max_positive_gap_mm": b.get("max_positive_gap_mm"),
            "mesh_volume_mm3": b.get("mesh_volume_mm3"),
            "geometry_hash": b.get("geometry_hash"),
            "audit_ok": b.get("audit_ok"),
        },
    }
    # "the lid floats above the body" in the same 口径 the audit used: body top -> lid base
    for tag, comps_, body_ in (("before", ca, ba), ("after", cb, bb)):
        others = [c for c in comps_ if c is not body_ and c["z_min"] > (body_["z_max"] if body_ else 0)]
        row[tag]["body_top_to_lowest_upper_part_base_mm"] = (
            min(c["z_min"] for c in others) - body_["z_max"]) if (others and body_) else None
    out[lineage] = row

    print(f"== {lineage}")
    print(f"   declared target {row['declared_z_rim_target_mm']:.4f}  "
          f"z_rim {row['before']['profile_z_rim_mm']:.4f} -> {row['after']['profile_z_rim_mm']:.4f}")
    print(f"   shortfall {row['before']['profile_shortfall_mm']:.4f} -> "
          f"{row['after']['profile_shortfall_mm']:.4f} mm")
    print(f"   body-top->upper-part-base {row['before']['body_top_to_lowest_upper_part_base_mm']} "
          f"-> {row['after']['body_top_to_lowest_upper_part_base_mm']}")
    print(f"   max_positive_gap {row['before']['max_positive_gap_mm']} -> "
          f"{row['after']['max_positive_gap_mm']}   components {row['before']['n_components']}"
          f" -> {row['after']['n_components']}")
    print(f"   hash {str(row['before']['geometry_hash'])[:14]} -> "
          f"{str(row['after']['geometry_hash'])[:14]}   audit_ok "
          f"{row['before']['audit_ok']} -> {row['after']['audit_ok']}")

target = REPO / "data/a12/reports/geom_fix/s14_frozen_compare.json"
target.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                  encoding="utf-8")
print("wrote", target)
