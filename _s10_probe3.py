import sys; sys.path.insert(0,'.')
from synlab.cameras.profiles import camera_profiles, _TIER_SPECS, _spec_for_tier
print("REGISTERED camera_profiles():")
for p in camera_profiles():
    print(f"   {p.profile_id:20s} tier={p.tier:7s} u={p.u_position_mm:7.1f} wd={p.working_distance_mm:7.1f} f={p.focal_length_mm}")
print()
print("TIER travel limits (the real enforcement):")
for s in _TIER_SPECS:
    lo, hi = s.u_travel_mm
    print(f"   {s.tier:7s} {s.profile_id:20s} u_nominal={s.u_position_mm:7.1f} travel=[{lo:7.1f},{hi:7.1f}] span={hi-lo:6.1f} step={s.u_step_mm}")
lo = min(s.u_travel_mm[0] for s in _TIER_SPECS); hi = max(s.u_travel_mm[1] for s in _TIER_SPECS)
print(f"   UNION travel = [{lo}, {hi}]  span = {hi-lo} mm")
print()
print("CONTRACT: travel_mm_nominal = 150, reserved [100,200]  (configs/a12/capture_contract.json t052)")
