"""Ad-hoc: line up s04 (pre-fix), s11 (simulated post-fix) and s14 (measured post-fix)."""
import json
from pathlib import Path

AUD = Path("data/a12/reports/mother_geometry_audit")
FIX = Path("data/a12/reports/geom_fix")

s04 = json.loads((AUD / "s04_frozen_repro.json").read_text(encoding="utf-8"))
s11 = json.loads((AUD / "s11_fix_simulation.json").read_text(encoding="utf-8"))
s14 = json.loads((FIX / "s14_frozen_after.json").read_text(encoding="utf-8"))

for lin in s04:
    a, b = s04[lin], s14[lin]
    sim = s11["frozen_params"].get(lin, {})
    print(f"=== {lin} ({a.get('vessel_id')})")
    print("   pre : z_rim=%r target=%r short=%r n_bodies=%d hash=%s" % (
        a.get("profile_z_rim_mm"), a.get("declared_z_rim_target_mm"),
        a.get("profile_shortfall_mm"), len(a.get("components") or []),
        str(a.get("geometry_hash"))[:22]))
    print("   sim : z_rim=%r short=%r hash=%s" % (
        sim.get("profile_z_rim_mm"), sim.get("profile_shortfall_mm"),
        str(sim.get("geometry_hash"))[:22]))
    print("   post: z_rim=%r target=%r short=%r n_bodies=%d hash=%s gap=%r" % (
        b.get("profile_z_rim_mm"), b.get("declared_z_rim_target_mm"),
        b.get("profile_shortfall_mm"), len(b.get("components") or []),
        str(b.get("geometry_hash"))[:22], b.get("max_positive_gap_mm")))
    print("   pre n_bodies=%d max_gap=%r | post n_bodies=%d max_gap=%r" % (
        len(a.get("components") or []), a.get("max_positive_gap_mm") if "max_positive_gap_mm" in a else None,
        len(b.get("components") or []), b.get("max_positive_gap_mm")))
    print("   delta z_rim = %+.4f mm" % (float(b["profile_z_rim_mm"]) - float(a["profile_z_rim_mm"])))
