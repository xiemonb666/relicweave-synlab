"""Ad-hoc: print the s11 simulated post-fix table (defaults + frozen) for the benchmark."""
import json
from pathlib import Path

AUD = Path("data/a12/reports/mother_geometry_audit")
s11 = json.loads((AUD / "s11_fix_simulation.json").read_text(encoding="utf-8"))
print("keys:", sorted(s11))
for vid, row in sorted(s11["defaults"].items()):
    print("%s sim z_rim=%r target=%r short=%r r_max=%r bodies=%r audit=%r fail=%r" % (
        vid, row.get("profile_z_rim_mm"), row.get("declared_z_rim_target_mm"),
        row.get("profile_shortfall_mm"), row.get("profile_r_max_mm"), row.get("n_bodies"),
        row.get("audit_ok"), row.get("audit_failures")))
print("--- frozen")
for lin, row in sorted(s11["frozen_params"].items()):
    print("%s sim z_rim=%r short=%r bodies=%r hash=%s" % (
        lin, row.get("profile_z_rim_mm"), row.get("profile_shortfall_mm"), row.get("n_bodies"),
        str(row.get("geometry_hash"))[:22]))
    print("      gaps:", [(g["lower"], g["upper"], round(g["gap_mm"], 4))
                          for g in (row.get("component_gaps") or [])])
