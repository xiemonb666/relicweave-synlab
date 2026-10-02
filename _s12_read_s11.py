import json
d = json.load(open("data/a12_reports/s11_p03_sweep.json", encoding="utf-8-sig"))
print(list(d.keys()))
sw = d.get("sweep") or {}
print("sweep keys:", list(sw.keys()))
for r in sw.get("spacing_sweep", []):
    print("SP", {k: r.get(k) for k in ("requested_spacing_mm","effective_spacing_mm","roi_external_drift_mm")},
          (r.get("mesh") or {}).get("n_faces"), (r.get("spacing_choice") or {}))
c = json.load(open("data/a12_reports/s11_p03_context.json", encoding="utf-8-sig"))
print("context keys:", list(c.keys()))
print({k: c.get(k) for k in ("grid","spacing_choice","spacing_basis","halo_mm","surface_zero_level_max_mm")})
